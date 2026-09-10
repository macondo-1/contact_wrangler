"""Phase 4: synthetic data seed script.

Populates contacts/campaigns/campaign_quotas/campaign_contacts/contact_events
with realistic-volume fake data -- enough that indexing and dedup choices
visibly matter when querying. Run inside the Docker container:

    docker compose exec app uv run python scripts/seed.py

Design choices:
- Contacts go through ingestion.import_contacts() (not raw inserts) --
  that's the one table with real dedup logic, and running the actual
  production code path is the only way this script proves anything about
  it, rather than just exercising a reimplementation.
- Everything else (campaigns/quotas/campaign_contacts/contact_events) uses
  direct bulk SQL inserts -- there's no dedup/business logic there worth
  reusing, and bulk inserts are orders of magnitude faster than hundreds
  of thousands of individual ORM object adds.
- Duplicate contact emails are deliberately injected (not left to chance)
  -- some exact, some varying only in case/whitespace -- so Task 4.3's
  dedup verification is guaranteed to have something to find, not
  dependent on incidental Faker collisions.
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from faker import Faker
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from contact_wrangler.ingestion import import_contacts  # noqa: E402
from contact_wrangler.models import (  # noqa: E402
    AssignmentStatus,
    Campaign,
    CampaignContact,
    CampaignQuota,
    CampaignStatus,
    Contact,
    ContactEvent,
    ContactEventType,
)

load_dotenv()
fake = Faker()

CONTACT_COUNT = 100_000
BATCH_SIZE = 5_000
DUPLICATE_RATE = 0.02  # ~2% of rows are deliberate duplicates of an earlier one

CAMPAIGN_COUNT = 100
QUOTAS_PER_CAMPAIGN = (2, 4)
ASSIGNMENTS_PER_CAMPAIGN = (500, 2000)
EVENTS_PER_ASSIGNMENT = (1, 3)

COUNTRIES = ["Canada", "USA", "Mexico", "UK", "Germany", "France", "Australia"]
INDUSTRIES = ["Tech", "Finance", "Healthcare", "Retail", "Manufacturing", "Education"]


def gen_contact_row(recent_emails: list[str]) -> dict:
    """One fake contact row, occasionally a deliberate duplicate (exact,
    upper-cased, or whitespace-padded) of a recently-generated email, to
    guarantee the dedup path actually gets exercised.
    """
    if recent_emails and random.random() < DUPLICATE_RATE:
        email = random.choice(recent_emails)
        variant = random.choice(["exact", "upper", "whitespace"])
        if variant == "upper":
            email = email.upper()
        elif variant == "whitespace":
            email = f"  {email}  "
    else:
        email = fake.unique.email()
        recent_emails.append(email)
        if len(recent_emails) > 500:
            recent_emails.pop(0)

    return {
        "email": email,
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "phone": fake.phone_number(),
        "country": random.choice(COUNTRIES),
        "state": fake.state(),
        "city": fake.city(),
        "industry": random.choice(INDUSTRIES),
        "company_name": fake.company(),
        "job_title": fake.job(),
        "source": random.choice(["import", "web_form", "referral"]),
        "is_opt_in": random.random() < 0.6,
    }


def seed_contacts(session: Session) -> int:
    print(f"Seeding {CONTACT_COUNT} contacts...")
    recent_emails: list[str] = []
    inserted_total = 0
    skipped_total = 0
    buffer = []

    for i in range(CONTACT_COUNT):
        buffer.append(gen_contact_row(recent_emails))
        if len(buffer) >= BATCH_SIZE:
            result = import_contacts(session, buffer)
            inserted_total += result["inserted"]
            skipped_total += result["skipped_duplicate_count"]
            print(f"  {i + 1}/{CONTACT_COUNT} processed "
                  f"({inserted_total} inserted, {skipped_total} skipped as duplicates)")
            buffer = []

    if buffer:
        result = import_contacts(session, buffer)
        inserted_total += result["inserted"]
        skipped_total += result["skipped_duplicate_count"]

    print(f"Contacts done: {inserted_total} inserted, {skipped_total} skipped as duplicates")
    return inserted_total


def seed_campaigns(session: Session) -> list[int]:
    print(f"Seeding {CAMPAIGN_COUNT} campaigns...")
    rows = [
        {
            "project_number": f"PN-{100000 + i}",
            "name": f"{fake.catch_phrase()} #{i}",
            "status": random.choice(list(CampaignStatus)),
            "start_date": fake.date_between(start_date="-1y", end_date="today"),
        }
        for i in range(CAMPAIGN_COUNT)
    ]
    ids = session.scalars(
        insert(Campaign).returning(Campaign.id), rows
    ).all()
    session.commit()
    print(f"Campaigns done: {len(ids)} inserted")
    return list(ids)


def seed_quotas(session: Session, campaign_ids: list[int]) -> list[dict]:
    print("Seeding campaign_quotas...")
    rows = []
    for campaign_id in campaign_ids:
        for _ in range(random.randint(*QUOTAS_PER_CAMPAIGN)):
            dimension = random.choice(["country", "industry"])
            value = random.choice(COUNTRIES if dimension == "country" else INDUSTRIES)
            rows.append({
                "campaign_id": campaign_id,
                "dimension": dimension,
                "dimension_value": value,
                "target_count": random.randint(50, 500),
            })
    # Same campaign could roll the same (dimension, value) twice -- the
    # UniqueConstraint would reject the second one, so de-dupe here first.
    seen = set()
    deduped = []
    for row in rows:
        key = (row["campaign_id"], row["dimension"], row["dimension_value"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    result = session.execute(insert(CampaignQuota).returning(CampaignQuota.id, CampaignQuota.campaign_id), deduped)
    quotas = [{"id": r[0], "campaign_id": r[1]} for r in result.all()]
    session.commit()
    print(f"Quotas done: {len(quotas)} inserted")
    return quotas


def seed_assignments_and_events(
    session: Session, campaign_ids: list[int], quotas: list[dict], contact_ids: list[int]
) -> None:
    print("Seeding campaign_contacts and contact_events...")
    quotas_by_campaign: dict[int, list[int]] = {}
    for q in quotas:
        quotas_by_campaign.setdefault(q["campaign_id"], []).append(q["id"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total_assignments = 0
    total_events = 0

    for campaign_id in campaign_ids:
        n = min(random.randint(*ASSIGNMENTS_PER_CAMPAIGN), len(contact_ids))
        chosen_contacts = random.sample(contact_ids, n)
        campaign_quota_ids = quotas_by_campaign.get(campaign_id, [])

        assignment_rows = []
        for contact_id in chosen_contacts:
            status = random.choice(list(AssignmentStatus))
            assignment_rows.append({
                "campaign_id": campaign_id,
                "contact_id": contact_id,
                "quota_id": random.choice(campaign_quota_ids) if campaign_quota_ids and random.random() < 0.7 else None,
                "status": status,
                "last_sent_at": now - timedelta(days=random.randint(0, 60))
                if status != AssignmentStatus.PENDING else None,
            })

        assignment_ids = session.scalars(
            insert(CampaignContact).returning(CampaignContact.id), assignment_rows
        ).all()

        event_rows = []
        for assignment_id, row in zip(assignment_ids, assignment_rows, strict=True):
            contact_id = row["contact_id"]
            event_rows.append({
                "contact_id": contact_id,
                "campaign_id": campaign_id,
                "event_type": ContactEventType.ASSIGNED,
                "occurred_at": now - timedelta(days=random.randint(30, 90)),
            })
            if row["status"] != AssignmentStatus.PENDING:
                for _ in range(random.randint(*EVENTS_PER_ASSIGNMENT)):
                    event_rows.append({
                        "contact_id": contact_id,
                        "campaign_id": campaign_id,
                        "event_type": random.choice([
                            ContactEventType.EMAIL_SENT,
                            ContactEventType.EMAIL_OPENED,
                            ContactEventType.EMAIL_CLICKED,
                        ]),
                        "occurred_at": now - timedelta(days=random.randint(0, 30)),
                    })

        if event_rows:
            session.execute(insert(ContactEvent), event_rows)

        session.commit()
        total_assignments += len(assignment_rows)
        total_events += len(event_rows)

    print(f"Assignments done: {total_assignments} inserted")
    print(f"Events done: {total_events} inserted")


def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    with Session(engine) as session:
        seed_contacts(session)
        contact_ids = list(session.scalars(select(Contact.id)).all())

        campaign_ids = seed_campaigns(session)
        quotas = seed_quotas(session, campaign_ids)
        seed_assignments_and_events(session, campaign_ids, quotas, contact_ids)

    print("Seeding complete.")


if __name__ == "__main__":
    main()
