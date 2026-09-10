"""Task 5.3: dedup logic tests (Task 1.6 design, Task 3.1 wiring).

Covers the checklist accumulated during Phase 3 manual testing -- see
memory/phase5-test-cases.md for the original bug reports these guard
against, so they stop being "things Claude tested once by hand" and
become permanent regressions.
"""

from contact_wrangler.models import Contact


def test_exact_resubmission_skips_everything(client):
    payload = [{"email": "a@example.com", "first_name": "Alice"}]

    r1 = client.post("/contacts/import", json=payload)
    assert r1.json() == {"inserted": 1, "skipped_duplicate_count": 0}

    r2 = client.post("/contacts/import", json=payload)
    assert r2.json() == {"inserted": 0, "skipped_duplicate_count": 1}


def test_case_and_whitespace_variants_are_deduped(client):
    client.post("/contacts/import", json=[{"email": "Alice@Example.com"}])

    r = client.post("/contacts/import", json=[{"email": "  alice@example.com  "}])
    assert r.json() == {"inserted": 0, "skipped_duplicate_count": 1}


def test_intra_batch_duplicate_is_skipped(client):
    payload = [
        {"email": "dup@example.com", "first_name": "First"},
        {"email": "dup@example.com", "first_name": "Second"},
    ]
    r = client.post("/contacts/import", json=payload)
    assert r.json() == {"inserted": 1, "skipped_duplicate_count": 1}


def test_no_email_rows_are_never_deduped(client):
    payload = [{"first_name": "NoEmail"}]

    r1 = client.post("/contacts/import", json=payload)
    assert r1.json()["inserted"] == 1

    # Same payload again -- still inserted both times, since there's no
    # email to key dedup on at all.
    r2 = client.post("/contacts/import", json=payload)
    assert r2.json() == {"inserted": 1, "skipped_duplicate_count": 0}


def test_is_gmail_computed_correctly_with_no_email(client, db_session):
    """Regression for a real bug: NULL LIKE '...' evaluates to NULL, not
    false, which violated is_gmail's NOT NULL constraint before the
    COALESCE(..., false) fix (migration 72a603fe6339).
    """
    r = client.post("/contacts/import", json=[{"first_name": "NoEmail"}])
    assert r.status_code == 200

    contact = db_session.query(Contact).filter_by(first_name="NoEmail").one()
    assert contact.is_gmail is False


def test_csv_and_json_produce_equivalent_dedup_behavior(client):
    r_json = client.post("/contacts/import", json=[{"email": "parity@example.com"}])
    assert r_json.json()["inserted"] == 1

    csv_content = "email\nparity@example.com\n"
    r_csv = client.post(
        "/contacts/import",
        files={"file": ("test.csv", csv_content, "text/csv")},
    )
    assert r_csv.json() == {"inserted": 0, "skipped_duplicate_count": 1}
