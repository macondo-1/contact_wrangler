import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.eligibility import eligible_contacts_for_campaign
from contact_wrangler.ingestion import import_contacts
from contact_wrangler.models import Campaign, Contact, EmailValidation

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ImportResult(BaseModel):
    inserted: int
    skipped_duplicates: list[str]


@router.post("/import", response_model=ImportResult)
async def import_contacts_endpoint(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if file is None:
            raise HTTPException(400, "Expected a 'file' field in the form data")
        raw = await file.read()
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))

    elif content_type.startswith("application/json"):
        body = await request.json()
        if not isinstance(body, list):
            raise HTTPException(400, "JSON body must be a list of contact objects")
        rows = body

    else:
        raise HTTPException(
            415, "Content-Type must be multipart/form-data (CSV) or application/json"
        )

    return import_contacts(db, rows)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    first_name: str | None
    last_name: str | None
    phone: str | None
    country: str | None
    state: str | None
    city: str | None
    industry: str | None
    company_name: str | None
    job_title: str | None
    is_active: bool
    is_opt_in: bool
    email_validation: EmailValidation | None
    created_at: datetime


@router.get("/", response_model=list[ContactOut])
def search_contacts(
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    country: str | None = None,
    industry: str | None = None,
    is_active: bool | None = None,
    email_validation: EmailValidation | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Search/filter contacts. Text fields (email, first_name, last_name)
    are partial/case-insensitive matches; the rest are exact filters.
    All filters are optional and combine with AND when multiple are given.
    """
    query = select(Contact)

    if email:
        query = query.where(Contact.email.ilike(f"%{email}%"))
    if first_name:
        query = query.where(Contact.first_name.ilike(f"%{first_name}%"))
    if last_name:
        query = query.where(Contact.last_name.ilike(f"%{last_name}%"))
    if country:
        query = query.where(Contact.country == country)
    if industry:
        query = query.where(Contact.industry == industry)
    if is_active is not None:
        query = query.where(Contact.is_active == is_active)
    if email_validation is not None:
        query = query.where(Contact.email_validation == email_validation)

    query = query.order_by(Contact.id).limit(limit).offset(offset)

    return db.scalars(query).all()


@router.get("/eligible", response_model=list[ContactOut])
def get_eligible_contacts(campaign_id: int, db: Session = Depends(get_db)):
    """Wires up the Phase 1.8 assignment-time eligibility query: which
    contacts are eligible to be newly assigned to `campaign_id` right now.
    NOTE: this is the ASSIGNMENT-time check (no cooldown) -- the SEND-time
    check (sendable_assignments_for_campaign, which does apply the cooldown)
    belongs to Task 3.8's assignment endpoint instead, once campaign_contacts
    rows actually exist to check cooldown against.

    Registered before /{contact_id} deliberately: FastAPI matches routes in
    registration order, and a literal path like /eligible must come before
    a variable path like /{contact_id}, or a request to /contacts/eligible
    would incorrectly match /{contact_id} first and 422 (failing to parse
    "eligible" as an int) instead of ever reaching this route.
    """
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    query = eligible_contacts_for_campaign(campaign_id)
    return db.scalars(query).all()


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(404, f"Contact {contact_id} not found")
    return contact
