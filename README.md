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
ollama pull numind/nuextract3:q4_k_m
ollama pull qwen3.5:4b

# 5. Run
.venv/bin/uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Check `/health` if something looks wrong.

### First session

1. **Settings** — set your offer / target profile (who you sell to).
2. **Companies** — seed a domain (or paste a list). That queues a fetch + LLM jobs.
3. Wait for jobs (inference on CPU is slow — minutes per page). Watch **Today** / failed jobs.
4. Open a company → review facts, signals, opportunities, scores.
5. **Outreach** — prepare a draft, edit, approve; you send it yourself, then log the reply.

LLM work never runs in the browser request. Unchanged pages are skipped.

---

## Day-to-day

| Screen | Use for |
| --- | --- |
| Today | High-priority opps, due follow-ups, newly changed prospects |
| Companies | Seed, browse snapshots and people |
| Outreach | Drafts, queue, interactions |
| Settings | Profile, feeds, adapters, exports |

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
