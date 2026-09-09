from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.models import (
    Campaign,
    Contact,
    ContactEvent,
    ContactEventType,
    MailingStrategy,
)

router = APIRouter(prefix="/events", tags=["events"])


class EventCreate(BaseModel):
    contact_id: int
    campaign_id: int | None = None
    event_type: ContactEventType
    occurred_at: datetime | None = None
    mailing_strategy: MailingStrategy | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int
    campaign_id: int | None
    event_type: ContactEventType
    occurred_at: datetime
    mailing_strategy: MailingStrategy | None


@router.post("/", response_model=EventOut, status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db)):
    """Logs a contact_events row. Deliberately independent of
    campaign_contacts (Alberto's call) -- does NOT update last_sent_at or
    assignment status, even for EMAIL_SENT. That sync is meant to be owned
    by the future SMTP-sender service once it exists, not this generic
    logging endpoint.
    """
    if db.get(Contact, payload.contact_id) is None:
        raise HTTPException(404, f"Contact {payload.contact_id} not found")
    if (
        payload.campaign_id is not None
        and db.get(Campaign, payload.campaign_id) is None
    ):
        raise HTTPException(404, f"Campaign {payload.campaign_id} not found")

    event = ContactEvent(**payload.model_dump(exclude_none=True))
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
