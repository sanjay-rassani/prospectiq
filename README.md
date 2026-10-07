# ProspectIQ

Self-hosted B2B prospecting for one operator. You seed companies from public pages; the
engine snapshots evidence, detects change, scores fit, and drafts outreach you review and
send yourself.

**No paid APIs.** Postgres in Docker + local Ollama only.  
**Evidence or it doesn't exist.** Every signal links to a stored page snapshot.  
**Not a job board.** Hiring signals count *against* a prospect.

Full build plan: [`PLAN.md`](PLAN.md). Spec: `prospecting-engine-final-v1.3.docx`.

---

## Get started

### You need

- Docker (for Postgres)
- [uv](https://docs.astral.sh/uv/) (Python 3.12)
- [Ollama](https://ollama.com/download) on the host

### Setup (once)

```bash
# 1. Python env
uv venv --python 3.12
uv pip install -e ".[dev]"

# 2. Config
cp .env.example .env

# 3. Database
docker compose up -d
.venv/bin/alembic upgrade head

# 4. Models (~7 GB total)
ollama pull numind/nuextract3:q4_k_m   # reads pages → facts & signals
ollama pull qwen3.5:4b                # drafts opportunities & outreach

# 5. Run
.venv/bin/uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Check `/health` if something looks wrong.

### First session

1. **Settings** — who you sell to and score thresholds.
2. **Companies → Seed** — paste a domain or URL list.
3. Wait (CPU inference is slow). Use **Today** and **Failed jobs**.
4. Open a company → facts → signals → opportunities.
5. Open an opportunity → prepare outreach → edit/approve → you send → log the reply.

LLM work never runs inside a page click. Unchanged pages are skipped.

---

## Understand the site

Top nav: **Today · Companies · Outreach · Settings**.

### The pipeline (in order)

```
Seed company → fetch page → snapshot
  → extract facts → extract signals
  → score ICP Fit (company) + Opportunity Score (deal idea)
  → recommend buyer role → draft outreach (you send)
  → log reply / next action → refresh later on a schedule
```

| Word | Meaning |
| --- | --- |
| Snapshot | Saved copy of a page (text + hash). Evidence lives here. |
| Fact | Something observed on the page (not a guess). |
| Signal | A change or cue (product launch, hiring, etc.) with a quote. |
| Opportunity | A project hypothesis tied to signals — not a guaranteed deal. |
| ICP Fit | “Is this company our kind of customer?” (no timing signals). |
| Opportunity Score | “Is this idea worth acting on *now*?” |
| Priority band | High / Medium / Watch / Reject from your thresholds. |

### Today (`/`)

Your daily desk: high-priority opportunities, drafts/follow-ups due, companies that
changed, recent snapshots. Link to **Failed jobs** if something broke.

### Companies (`/companies`)

- **Seed** — paste domains/URLs; fetch + research jobs are queued.
- **List** — all companies and status.
- **Detail** — ICP Fit + reasons, extracted facts, signals, opportunities, people,
  snapshot history, good/bad feedback, **Refresh now**.

Open an **opportunity** from here for scores, evidence, buyer role, and outreach.

### Opportunity detail (`/opportunities/…`)

One deal idea: problem, hypothesis, why-now, confidence, evidence quotes, Opportunity
Score (separate from ICP), buyer role / people, promote to outreach-ready, prepare draft,
record interactions (sent / reply / next action), lifecycle (watch / nurture / etc.).

### Outreach (`/outreach`)

Queue of drafts and due follow-ups. Open a task → edit draft → **approve** or reject →
mark sent yourself → come back when they reply. The app never emails for you.

### Settings (`/settings`)

- **Profile** — positioning, industries, regions, exclusions, score bands, refresh days.
- **Adapters** — which source types exist (company page, RSS, GitHub, …).
- **Feeds** — add RSS/Atom/changelog URLs; poll, enable/disable, remove.
- **Playwright** — optional per-domain JS fetch (off by default).
- **Exports** — download companies / opportunities / interactions.

Models shown here are labels; real model names live in `.env`
(`EXTRACTION_MODEL`, `GENERATION_MODEL`).

### Jobs (`/jobs/failed`)

Background work that failed (fetch, LLM, etc.). From Today’s footer. Retry or fix the
underlying issue (Ollama down, bad URL, …).

---

## Day-to-day cheatsheet

| Want to… | Go to |
| --- | --- |
| See what needs attention | Today |
| Add a prospect | Companies → Seed |
| Judge fit / evidence | Company or opportunity detail |
| Send / follow up | Outreach |
| Tune who you target | Settings |
| Fix broken background work | Failed jobs |

```bash
.venv/bin/pytest
.venv/bin/ruff check app tests
.venv/bin/mypy app
```

---

## Layout

```
app/           FastAPI, models, services, templates
migrations/    Alembic
config/        Operator profile YAML
scripts/       Backup, restore, secrets audit
deploy/        systemd backup timer
docs/          Acceptance checklist
spike/         Phase 0 LLM experiments
tests/
```

---

## Backups & export

```bash
./scripts/backup_pg.sh
./scripts/restore_pg.sh backups/prospectiq_YYYYMMDDTHHMMSSZ.sql.gz
.venv/bin/alembic upgrade head
```

Exports: `/export/companies.json`, `/export/opportunities.csv`, `/export/interactions.csv`
(also linked from Settings). Optional nightly timer: `deploy/prospectiq-backup.*`.

---

## Security notes

Bound to `127.0.0.1` with no login by default. If you bind beyond localhost, set
`AUTH_TOKEN` in `.env`. Secrets stay in `.env` only — run `./scripts/audit_secrets.sh`
after changes. No LinkedIn scraping; no email guessing.

Acceptance: [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md).
