from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.eligibility import baseline_contactable_filters
from contact_wrangler.models import (
    AssignmentStatus,
    Campaign,
    CampaignContact,
    CampaignQuota,
    CampaignStatus,
    Contact,
)


router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{label} {obj_id} not found")
    return obj


class CampaignCreate(BaseModel):
    project_number: str
    name: str
    description: str | None = None
    status: CampaignStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_number: str
    name: str
    description: str | None
    status: CampaignStatus
    start_date: date | None
    end_date: date | None
    finished_at: datetime | None
    created_at: datetime


@router.post("/", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(**payload.model_dump(exclude_none=True))
    db.add(campaign)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "A campaign with that project_number or name already exists"
        )
    db.refresh(campaign)
    return campaign


@router.get("/", response_model=list[CampaignOut])
def list_campaigns(
    status: CampaignStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(Campaign)
    if status is not None:
        query = query.where(Campaign.status == status)
    query = query.order_by(Campaign.id).limit(limit).offset(offset)
    return db.scalars(query).all()


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Campaign, campaign_id, "Campaign")


class AssignmentCreate(BaseModel):
    contact_id: int
    quota_id: int | None = None


class AssignmentOut(BaseModel):
    id: int
    campaign_id: int
    contact_id: int
    quota_id: int | None
    status: AssignmentStatus
    assigned_at: datetime
    quota_exceeded: bool


@router.post(
    "/{campaign_id}/contacts", response_model=AssignmentOut, status_code=201
)
def assign_contact(
    campaign_id: int, payload: AssignmentCreate, db: Session = Depends(get_db)
):
    """Quota-aware assignment. Decision (Task 3.8): when the given quota is
    already at or past its target_count, the assignment is still created
    (accept), but the response flags it via quota_exceeded -- a human
    decides what to do about it, rather than the API hard-blocking it.
    """
    campaign = get_or_404(db, Campaign, campaign_id, "Campaign")
    if campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.PAUSED):
        raise HTTPException(
            409,
            f"Campaign {campaign_id} is {campaign.status.value}, no new assignments allowed",
        )

    contact = get_or_404(db, Contact, payload.contact_id, "Contact")
    is_contactable = (
        db.scalar(
            select(Contact.id).where(
                Contact.id == contact.id, *baseline_contactable_filters()
            )
        )
        is not None
    )
    if not is_contactable:
        raise HTTPException(
            400,
            f"Contact {payload.contact_id} is not contactable "
            "(inactive, not opted in, missing email, or invalid email)",
        )

    quota_exceeded = False
    if payload.quota_id is not None:
        # with_for_update locks this quota row for the rest of the
        # transaction, so a second concurrent request against the SAME
        # quota_id blocks until this one commits (or rolls back) --
        # without it, two near-simultaneous requests could both read
        # current_count as under target and both insert, silently
        # exceeding target_count with neither response ever flagging it.
        quota = db.get(CampaignQuota, payload.quota_id, with_for_update=True)
        if quota is None or quota.campaign_id != campaign_id:
            raise HTTPException(
                400,
                f"Quota {payload.quota_id} does not belong to campaign {campaign_id}",
            )
        current_count = db.scalar(
            select(func.count())
            .select_from(CampaignContact)
            .where(
                CampaignContact.quota_id == payload.quota_id,
                # EXCLUDED assignments explicitly don't count toward the
                # quota they were excluded from.
                CampaignContact.status != AssignmentStatus.EXCLUDED,
            )
        )
        quota_exceeded = current_count >= quota.target_count

    assignment = CampaignContact(
        campaign_id=campaign_id,
        contact_id=payload.contact_id,
        quota_id=payload.quota_id,
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError:
        # By this point campaign/contact/quota have all already been
        # confirmed to exist above, so in practice this is almost always
        # the (campaign_id, contact_id) unique constraint -- the narrow
        # exception is a genuinely concurrent delete of one of those rows
        # between the checks above and this commit, which would still
        # surface here as this same message (acknowledged, not fixed:
        # the failure window is narrow enough that a driver-specific
        # constraint-name check isn't worth the added coupling right now).
        db.rollback()
        raise HTTPException(
            409,
            f"Contact {payload.contact_id} is already assigned to campaign {campaign_id}",
        )
    db.refresh(assignment)

    return AssignmentOut(
        id=assignment.id,
        campaign_id=assignment.campaign_id,
        contact_id=assignment.contact_id,
        quota_id=assignment.quota_id,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        quota_exceeded=quota_exceeded,
    )


class QuotaOut(BaseModel):
    id: int
    campaign_id: int
    dimension: str
    dimension_value: str
    target_count: int
    message_template: str | None
    current_count: int


@router.get("/{campaign_id}/quotas", response_model=list[QuotaOut])
def list_campaign_quotas(campaign_id: int, db: Session = Depends(get_db)):
    """current_count is computed on read (COUNT() against campaign_contacts),
    consistent with the Phase 1 decision not to store a denormalized counter
    that could drift out of sync.
    """
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    quotas = db.scalars(
        select(CampaignQuota).where(CampaignQuota.campaign_id == campaign_id)
    ).all()

    return [
        QuotaOut(
            id=quota.id,
            campaign_id=quota.campaign_id,
            dimension=quota.dimension,
            dimension_value=quota.dimension_value,
            target_count=quota.target_count,
            message_template=quota.message_template,
            current_count=db.scalar(
                select(func.count())
                .select_from(CampaignContact)
                .where(CampaignContact.quota_id == quota.id)
            ),
        )
        for quota in quotas
    ]
