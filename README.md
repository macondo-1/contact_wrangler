Contact Wrangler

Python project with the following capabilities:

- Wrangle your contact's information

- Email sequencer (SMPT)

- Set-up mailing campaigns

- Dashboard of your data

- Data ingestions and clean-up

## Synthetic data

`scripts/seed.py` populates the database with realistic-volume fake data
(contacts, campaigns, quotas, assignments, events) via `faker`, enough that
indexing and dedup choices visibly matter when querying it. Run it inside
the Docker stack:

```
docker compose exec app uv run python scripts/seed.py
```

`faker` is a **dev dependency**, not a regular one -- it's a data-generation
tool the running app never needs at request time, the same category as a
test framework. It still runs fine inside the container as configured
today (the Dockerfile doesn't currently exclude dev dependencies from the
image), but if the Docker build is ever hardened to a `--no-dev`
production install, this script would need `faker` installed separately
(e.g. `uv pip install faker`) to keep working.

## Dashboard

`GET /dashboard` returns a funnel-style JSON aggregate (assignment counts
per status, fixed stage order, optionally scoped with `?campaign_id=`).
`GET /dashboard/view` renders the same data as an interactive Plotly page
-- a funnel chart for the real PENDING -> SENT -> OPENED -> CLICKED ->
REPLIED progression, plus a separate bar chart for the terminal exception
statuses (BOUNCED / UNSUBSCRIBED / EXCLUDED), which aren't further steps
in that progression and would misrepresent a real funnel if lumped in
with it. Visit `http://localhost:8001/dashboard/view` (add `?campaign_id=`
to scope it) once the stack is running.

## Tests

```
uv run pytest
```

Run this **on the host**, not via `docker compose exec` -- the suite uses
`testcontainers[postgres]` to spin up a throwaway Postgres container per
test session (migrated with the real Alembic chain, then rolled back per
test via a SAVEPOINT), which needs direct access to the Docker daemon.
Running on the host reaches that daemon naturally; running inside the app
container would require mounting the Docker socket into it just for
tests. Docker Desktop (or another local Docker daemon) must be running.
