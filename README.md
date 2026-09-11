# Contact Wrangler

A generic, from-scratch rebuild of a real internal recruiting-campaign
platform I work with professionally — reimplemented as a public,
Dockerized, PostgreSQL-backed system to deliberately close three skill
gaps: **Postgres schema depth, Docker, and migrations.**

No code, business logic, client data, or entity names were copied from the
original system. Contact Wrangler works with generic entities (contacts,
campaigns, quotas, events) and is seeded entirely with synthetic data via
[Faker](https://faker.readthedocs.io/).

## The problem this rebuilds

The system this is modeled on is a real, in-use recruiting/outreach
platform: a single ~3,300-line file, raw `sqlite3` (no ORM), server-rendered
templates, no migration tooling — schema changes applied by hand against a
live database holding on the order of **22 million rows** across its core
tables. It works, and has for years, but that combination (no ORM, no
migrations, a file-based database) is exactly the ceiling this project
exists to demonstrate a way past.

Rather than port that code, Contact Wrangler re-implements the same
*conceptual* problems from scratch, against a proper schema: deduplicating
inbound contact data, computing who's eligible to be contacted (and when),
and enforcing per-segment outreach quotas — the parts of the original
system that are genuinely nontrivial regardless of what language or
database sit underneath them.

## Why Postgres, not SQLite

The production system runs on SQLite, and works at its current scale. This
rebuild uses PostgreSQL from the very first migration, deliberately —
that choice is the entire point of the exercise. SQLite doesn't have
`information_schema`-driven migration tooling in the same way, has no
native `CHECK`/generated-column ecosystem as mature as Postgres's, and
(for a single-writer file-based engine) starts making real concurrency
tradeoffs well before 22M rows. None of that is a knock on the original
system — SQLite is a perfectly reasonable choice for what it needed to do.
It's just not what this project is trying to show. Contact Wrangler exists
to demonstrate schema design, indexing decisions, and a real Alembic
migration history directly — Postgres is a requirement for that, not an
incidental choice.

## Architecture

- **FastAPI** + **SQLAlchemy 2.0** (typed `Mapped[...]` columns) + **Alembic**
  migrations, **PostgreSQL 16**, all wired together via **Docker Compose**.
- 5 tables: `contacts`, `campaigns`, `campaign_quotas`, `campaign_contacts`
  (the assignment/join table carrying send status), `contact_events`.
- 5 real migrations, each committed as its own step in the schema's
  history: initial schema → server-side defaults → indexes for
  filtering/eligibility → an `is_gmail` NULL-handling fix → an additional
  demographic index — not one big upfront migration, but the kind of
  incremental evolution schemas actually go through.
- 12 functional endpoints plus a `GET /health` liveness check (13 routes
  total; `GET /docs` for the full interactive spec once the stack is
  running), covering contact ingestion/dedup, campaign/quota management,
  assignment, event logging, and a funnel dashboard.
- `pytest` + `testcontainers[postgres]`: the test suite runs against a
  real, throwaway Postgres container migrated with the actual Alembic
  chain, not a hand-maintained schema stand-in.

## Design tradeoffs

### Dedup

Email dedup is enforced at the database layer, not just in application
code: `email_normalized` is a Postgres **generated column**
(`lower(trim(email))`) carrying a unique constraint, so the guarantee
holds no matter what code path writes to the table. `POST /contacts/import`
skips duplicates (exact matches, case variants, whitespace variants, and
duplicates within the same batch) rather than merging or overwriting, and
reports only a *count* of what was skipped — not the conflicting emails
themselves, to avoid turning a bulk-import endpoint into an email
enumeration oracle. `is_active`/`is_opt_in` are deliberately excluded from
what a bulk import can set, so an import can never silently reactivate a
dormant contact or forge consent.

### Indexing

Indexes were added to match the queries this project actually runs, not
speculatively: a composite index on `(is_active, email_validation)` for
the "who's actually contactable" filter every eligibility check starts
from; single-column indexes on `country`/`ethnicity`/`industry` for
demographic-slice quota queries; a composite index on
`(contact_id, last_sent_at)` for the cooldown lookup that's the
eligibility query's hot path. At a seeded ~100k contacts / ~120k
assignments, `EXPLAIN ANALYZE` confirms these indexes are actually used
for the queries they target — and that a deliberately low-selectivity
filter with a small `LIMIT` correctly falls back to a sequential scan
instead, real planner behavior rather than a forced index hit.

### Eligibility-window design

Two separate queries exist on purpose, not one: `eligible_contacts_for_campaign`
(assignment-time — no cooldown check, since being assigned to a campaign
isn't the same as being emailed) and `sendable_assignments_for_campaign`
(send-time — enforces a rolling cooldown that's **global across all
campaigns**, not per-campaign, so a contact assigned to five campaigns
couldn't legitimately be emailed by all five in the same week). Both share
one `baseline_contactable_filters()` helper for the underlying "is this
contact even reachable" check, so the two queries and the assignment
endpoint's own re-check of that same condition can't drift out of sync
with each other.

Worth being honest about: `sendable_assignments_for_campaign` is fully
implemented and has real test coverage, but **no endpoint calls it yet**.
This MVP's scope stops at recording that a contact was assigned and that
an email event happened (`POST /events`) — it deliberately doesn't include
an actual email-sending step (see "What I'd change" below), so there's
nothing yet in the running API that would call the send-time check. It's
written as the contract a future sending process should use, not as
currently-enforced behavior.

### Quota-assignment semantics

A "quota" here is a per-campaign, per-segment *target headcount* (e.g. "50
contacts from Canada") — a different thing from a sending-rate limit,
which is the more natural first reading of the word and was deliberately
scoped out. Going over quota is **accepted, not rejected**: the response
flags `quota_exceeded: true` and leaves the decision to a human, rather
than hard-blocking an operator who sometimes needs to knowingly exceed a
target. The fill count that decision is based on excludes
`EXCLUDED`-status assignments (they were deliberately pulled from a
segment, so they shouldn't count against filling it), and the quota row is
row-locked (`SELECT ... FOR UPDATE`) for the duration of the check, closing
a race where two near-simultaneous assignment requests could both read
"under quota" and both insert. Campaign status gates assignment
independently of quota — a `COMPLETED`/`PAUSED` campaign rejects new
assignments outright.

## What I'd change / lessons learned

- **Realistic synthetic data means matching the shape of a distribution,
  not just its scale.** The seed script originally assigned each
  assignment's status uniformly at random across all 8 possible values —
  "realistic volume," 100k+ rows, but a *flat* distribution, which made
  the dashboard's funnel chart render as a rectangle instead of an actual
  funnel. Fixed by weighting the distribution to model a real drop-off
  (most contacts still early-stage, fewer at each later stage). Volume
  alone doesn't make fixture data realistic.
- **"Merged" on GitHub isn't proof code reached `main`.** Stacked PRs
  (branch B built on not-yet-merged branch A) hit a real gotcha: GitHub
  silently retargets a PR's base branch to the next branch up the stack
  when its predecessor's branch is auto-deleted on merge, so a PR can show
  "Merged" while its code sits in a dead-end branch that was never merged
  forward. The fix is procedural: always check `baseRefName` is actually
  `main` after a stack merges, and diff `main` against the stack's tip
  rather than trusting merge status alone.
- **A manual conflict resolution can look done and still be wrong.**
  Resolving a merge conflict by hand (e.g. in GitHub's web editor) can
  leave both sides of a hunk half-applied — a duplicated block, a stray
  leftover line — without erroring, because the result is still valid
  code. Diffing the merged result against the branch you meant to land is
  worth doing every time, not just when something looks obviously off.
- **I'd sequence testing earlier next time.** Tests (Phase 5) came after
  all 12 endpoints (Phase 3) here, so early endpoint work was verified by
  hand (`curl` against live Docker data) rather than against an automated
  suite. That caught real bugs, but later — writing tests right after the
  schema would give every endpoint a regression safety net from its first
  commit, not just from Phase 5 onward.
- **Actually sending an email is still out of scope.** This MVP models
  contacts, campaigns, quotas, assignments, and event logging, but stops
  short of an SMTP-sending step — `POST /events` records that a send
  happened, it doesn't trigger one, and the send-time cooldown query
  (`sendable_assignments_for_campaign`) is implemented and tested but has
  no caller yet, because nothing in this MVP actually performs a send. A
  real sender service consuming that query is the natural next piece.

## Setup

Requires Docker (with Docker Desktop's daemon, or equivalent, running) and
[`uv`](https://docs.astral.sh/uv/) for running tests outside the container.

```bash
git clone <this repo>
cd contact_wrangler
cp .env.example .env   # any values work locally -- it's all synthetic data
docker compose up --build
```

This builds and starts Postgres + the app; migrations run automatically on
startup (`entrypoint.sh` runs `alembic upgrade head` before `uvicorn`
starts). The API is then live at `http://localhost:8001` (`/docs` for the
interactive OpenAPI spec).

### Synthetic data

```bash
docker compose exec app uv run python scripts/seed.py
```

Populates ~100k contacts (with deliberately injected duplicates to
exercise the dedup path for real), 100 campaigns, quotas, assignments, and
events — enough volume that indexing and dedup choices visibly matter.
Not idempotent; run once against a fresh database
(`docker compose down -v` first if re-seeding). `faker` is a **dev
dependency**, not a runtime one — it's a data-generation tool the running
app never needs at request time, the same category as a test framework.
It runs fine inside the container as configured today (the Dockerfile
doesn't currently exclude dev dependencies from the image), but if the
build is ever hardened to a `--no-dev` production install, this script
would need `faker` installed separately to keep working.

### Dashboard

Visit `http://localhost:8001/dashboard/view` (optionally `?campaign_id=`
to scope it) for an interactive Plotly funnel chart of assignment
statuses, or `GET /dashboard` for the same aggregate as JSON.

### Tests

```bash
uv run pytest
```

Run this **on the host**, not via `docker compose exec` — the suite uses
`testcontainers[postgres]` to spin up a throwaway Postgres container per
test session (migrated with the real Alembic chain, then rolled back per
test via a SAVEPOINT-based session), which needs direct access to the
Docker daemon.

## License

MIT — see [LICENSE](LICENSE).
