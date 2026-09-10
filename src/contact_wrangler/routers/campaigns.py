from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.models import Campaign, CampaignStatus

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


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
