"""Sanity checks for the test infrastructure itself, before trusting it
for real test suites.
"""

from contact_wrangler.models import Campaign


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_db_session_is_isolated_between_tests_a(db_session):
    """Insert a row; test_..._b (below) must NOT see it if isolation works."""
    db_session.add(Campaign(project_number="ISO-1", name="Isolation Test A"))
    db_session.commit()
    assert db_session.query(Campaign).count() == 1


def test_db_session_is_isolated_between_tests_b(db_session):
    """If the previous test's rollback didn't work, this sees 1 row, not 0."""
    assert db_session.query(Campaign).count() == 0
