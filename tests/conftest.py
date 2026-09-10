"""Phase 5 test infrastructure.

Run with: `uv run pytest` -- directly on the host, NOT via
`docker compose exec`. testcontainers needs direct access to the Docker
daemon to spin up a throwaway Postgres; running on the host reaches it
naturally (same daemon Docker Desktop already runs), avoiding the need to
mount the Docker socket into the app container just for tests.

Throwaway-DB strategy (Task 5.1): testcontainers[postgres] over a separate
docker-compose.test.yml -- it manages the whole container lifecycle
automatically from within pytest (start once per session, guaranteed
cleanup after), with zero risk of colliding with the dev Postgres (it picks
its own container + port), and no second compose file to keep in sync with
the real one.
"""

import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

# contact_wrangler.db reads DATABASE_URL from the environment at IMPORT
# time (module-level `create_engine(os.environ["DATABASE_URL"])`), and
# importing contact_wrangler.api below pulls that in transitively. On a
# fresh clone/CI with no .env, that import would crash with KeyError
# before the throwaway container even starts. setdefault (not a plain
# assignment) ensures a syntactically-valid-but-unused URL only when
# nothing is already set -- this module-level engine is never actually
# used by tests (the `client` fixture overrides get_db with the real
# testcontainers session instead), so it never needs to connect.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused"
)

from contact_wrangler.api import app
from contact_wrangler.db import get_db
from contact_wrangler.models import Campaign, Contact


@pytest.fixture(scope="session")
def db_url():
    # testcontainers defaults to the psycopg2 driver in the connection
    # URL; this project uses psycopg (v3) everywhere else, so ask for it
    # directly rather than string-replacing the URL after the fact.
    with PostgresContainer("postgres:16", driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def engine(db_url):
    """Runs the REAL Alembic migration chain against the throwaway
    container, once per test session -- tests run against the exact
    schema production uses, not a hand-maintained duplicate.
    """
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env={**os.environ, "DATABASE_URL": db_url},
        check=True,
    )
    eng = create_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """One test = one outer transaction, rolled back at the end -- fast,
    fully isolated, no need to re-migrate per test.

    Application code (the actual endpoints under test) calls session.commit()
    itself. A plain single transaction would let that first commit() commit
    the whole thing for real, defeating isolation. This SAVEPOINT-based
    pattern (SQLAlchemy's own documented recipe for this exact situation)
    lets application code commit/rollback normally while the OUTER
    transaction -- rolled back here at the end -- stays in full control.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Entered as a context manager so ASGI lifespan (startup/shutdown)
    # events actually run -- a plain TestClient(app) never triggers them.
    # No-op today (no lifespan handlers exist yet), but future ones would
    # otherwise silently never run under test.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_contact(db_session):
    """Factory fixture, shared across test modules that need ad-hoc
    Contact rows (test_eligibility.py, test_quota_assignment.py) -- kept
    in one place so their required-field defaults can't drift apart.
    """

    def _make(email, **overrides):
        defaults = {"email": email, "is_active": True, "is_opt_in": True}
        defaults.update(overrides)
        contact = Contact(**defaults)
        db_session.add(contact)
        db_session.flush()
        return contact

    return _make


@pytest.fixture
def make_campaign(db_session):
    def _make(project_number, name, **overrides):
        defaults = {"project_number": project_number, "name": name}
        defaults.update(overrides)
        campaign = Campaign(**defaults)
        db_session.add(campaign)
        db_session.flush()
        return campaign

    return _make
