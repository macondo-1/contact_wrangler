"""SQLAlchemy models for Contact Wrangler.

Five tables: contacts, campaigns, campaign_contacts, campaign_quotas,
contact_events.

Dedup rule (contacts): case-insensitive email match, enforced via a unique
index on `email_normalized`.

campaign_quotas has no stored "current count" column on purpose: it's
derived on read via a COUNT() query against campaign_contacts, to avoid
a denormalized counter drifting out of sync with reality.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger
    ,Date
    ,Enum
    ,ForeignKey
    ,Index
    ,UniqueConstraint
    ,func
    ,Computed
    ,true
    ,false
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Every `Mapped[int]` column (PKs and FKs alike) becomes BigInteger,
    # instead of writing `mapped_column(BigInteger, ...)` on each one.
    type_annotation_map = {
        int: BigInteger,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class CampaignStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class AssignmentStatus(enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    EXCLUDED = "excluded"


class ContactEventType(enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    ASSIGNED = "assigned"
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


class ContactGenderNormalized(enum.Enum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    SELF_DESCRIBED = "self_described"


class EmailValidation(enum.Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    CATCH_ALL = "catch_all"


class MailingStrategy(enum.Enum):
    MAILMERGE = "mailmerge"
    SALESFORGE = "salesforge"
    GREENARROW = "greenarrow"
    SUPERSEND = "supersend"


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_active_validation", "is_active", "email_validation"),
        Index("ix_contacts_country", "country"),
        Index("ix_contacts_ethnicity", "ethnicity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None]
    email_normalized: Mapped[str | None] = mapped_column(
        Computed("lower(trim(email))"), unique=True
    )
    first_name: Mapped[str | None]
    middle_name: Mapped[str | None]
    last_name: Mapped[str | None]
    phone: Mapped[str | None]

    age_raw: Mapped[str | None]
    age: Mapped[int | None]
    date_of_birth: Mapped[date | None]
    gender_raw: Mapped[str | None]
    gender_normalized: Mapped[ContactGenderNormalized | None] = mapped_column(
        Enum(ContactGenderNormalized, name="contact_gender_normalized")
    )
    ethnicity: Mapped[str | None]
    nationality: Mapped[str | None]
    education: Mapped[str | None]

    linkedin: Mapped[str | None]
    facebook: Mapped[str | None]
    twitter: Mapped[str | None]
    other_links: Mapped[list[str] | None] = mapped_column(JSONB)

    # location related fields
    country: Mapped[str | None]
    state: Mapped[str | None]
    city: Mapped[str | None]
    zip_code: Mapped[str | None]

    # job related fields
    job_title: Mapped[str | None]
    industry: Mapped[str | None]
    company_name: Mapped[str | None]
    job_keywords: Mapped[list[str] | None] = mapped_column(JSONB)

    # metadata fields
    source: Mapped[str | None]
    filename: Mapped[str | None]
    email_validation: Mapped[EmailValidation | None] = mapped_column(
        Enum(EmailValidation, name="email_validation")
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    is_opt_in: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_gmail: Mapped[bool] = mapped_column(Computed("lower(email) LIKE '%@gmail.com'"))
    email_domain: Mapped[str | None] = mapped_column(Computed("split_part(email, '@', 2)"))

    campaign_links: Mapped[list["CampaignContact"]] = relationship(
        back_populates="contact"
    )
    events: Mapped[list["ContactEvent"]] = relationship(back_populates="contact")


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_number: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"),
        default=CampaignStatus.DRAFT,
        server_default=CampaignStatus.DRAFT.name,
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    finished_at: Mapped[datetime | None]

    contact_links: Mapped[list["CampaignContact"]] = relationship(
        back_populates="campaign"
    )
    quotas: Mapped[list["CampaignQuota"]] = relationship(back_populates="campaign")
    events: Mapped[list["ContactEvent"]] = relationship(back_populates="campaign")


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id"),
        Index("ix_campaign_contacts_contact_last_sent", "contact_id", "last_sent_at"),
        Index("ix_campaign_contacts_quota", "quota_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    quota_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_quotas.id"))
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="assignment_status"),
        default=AssignmentStatus.PENDING,
        server_default=AssignmentStatus.PENDING.name,
    )
    assigned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_sent_at: Mapped[datetime | None]

    campaign: Mapped["Campaign"] = relationship(back_populates="contact_links")
    contact: Mapped["Contact"] = relationship(back_populates="campaign_links")
    quota: Mapped["CampaignQuota | None"] = relationship(back_populates="assignments")


class CampaignQuota(Base):
    __tablename__ = "campaign_quotas"
    __table_args__ = (
        UniqueConstraint("campaign_id", "dimension", "dimension_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    dimension: Mapped[str]
    dimension_value: Mapped[str]
    target_count: Mapped[int]
    message_template: Mapped[str | None]

    campaign: Mapped["Campaign"] = relationship(back_populates="quotas")
    assignments: Mapped[list["CampaignContact"]] = relationship(back_populates="quota")


class ContactEvent(Base):
    __tablename__ = "contact_events"
    __table_args__ = (
        Index("ix_contact_events_contact_occurred", "contact_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    event_type: Mapped[ContactEventType] = mapped_column(
        Enum(ContactEventType, name="contact_event_type")
    )
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    mailing_strategy: Mapped[MailingStrategy | None] = mapped_column(
        Enum(MailingStrategy, name="mailing_strategy")
    )
    contact: Mapped["Contact"] = relationship(back_populates="events")
    campaign: Mapped["Campaign | None"] = relationship(back_populates="events")

