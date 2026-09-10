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

from contact_wrangler.api import app
from contact_wrangler.db import get_db


@pytest.fixture(scope="session")
def db_url():
    with PostgresContainer("postgres:16") as container:
        # testcontainers defaults to the psycopg2 driver in the URL;
        # this project uses psycopg (v3) everywhere else.
        yield container.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+psycopg"
        )


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
    yield TestClient(app)
    app.dependency_overrides.clear()
