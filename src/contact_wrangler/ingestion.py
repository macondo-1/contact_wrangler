from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from contact_wrangler.models import Contact

# Fields raw import data is allowed to set. Deliberately excludes:
# - id/created_at/updated_at (server-managed)
# - email_normalized/is_gmail/email_domain (Postgres GENERATED columns --
#   the DB computes these; setting them ourselves would error)
# - gender_normalized/email_validation (derived by separate cleanup/
#   verification processes, not raw import data)
IMPORTABLE_FIELDS = {
    "email", "first_name", "middle_name", "last_name", "phone",
    "age_raw", "date_of_birth", "gender_raw", "ethnicity", "nationality",
    "education", "linkedin", "facebook", "twitter", "other_links",
    "country", "state", "city", "zip_code", "job_title", "industry",
    "company_name", "job_keywords", "source", "filename",
    "is_active", "is_opt_in",
}

LIST_FIELDS = {"other_links", "job_keywords"}


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    return email.strip().lower()


def _coerce_value(field: str, value):
    if value in (None, ""):
        return None
    if field in LIST_FIELDS:
        if isinstance(value, list):
            return value
        return [v.strip() for v in str(value).split(";") if v.strip()]
    if field == "date_of_birth":
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None
    if field in ("is_active", "is_opt_in"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes")
    return value


def _row_to_contact_kwargs(row: dict) -> dict:
    return {
        field: _coerce_value(field, row[field])
        for field in IMPORTABLE_FIELDS
        if field in row
    }


def import_contacts(db: Session, rows: list[dict]) -> dict:
    """Bulk-import contacts. A row whose email matches an existing contact
    (or one already inserted earlier in this same batch) is skipped
    entirely -- existing data is never modified by an import. Deliberately
    the simplest safe policy, not a merge (see Task 3.1 design notes).
    """
    incoming_emails = {
        _normalize_email(row.get("email"))
        for row in rows
        if _normalize_email(row.get("email"))
    }
    existing_emails = set(
        db.scalars(
            select(Contact.email_normalized).where(
                Contact.email_normalized.in_(incoming_emails)
            )
        )
    )

    seen_emails: set[str] = set()
    inserted = 0
    skipped: list[str] = []

    for row in rows:
        normalized = _normalize_email(row.get("email"))

        if normalized and (normalized in existing_emails or normalized in seen_emails):
            skipped.append(row.get("email"))
            continue

        if normalized:
            seen_emails.add(normalized)

        db.add(Contact(**_row_to_contact_kwargs(row)))
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped_duplicates": skipped}
