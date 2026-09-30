# Prospecting Engine

A self-hosted business-development engine for a software and AI solutions provider. It
discovers companies from public sources, snapshots the evidence, detects change signals,
and turns them into evidence-backed project hypotheses with a likely buyer role and a
drafted message — which **you** review and send.

Requirements and design live in `prospecting-engine-final-v1.3.docx`. The ordered build
plan, decision log, and open questions live in [`PLAN.md`](PLAN.md).

## Two rules that shape everything

**No paid dependencies.** No paid LLM APIs, lead databases, search APIs, CRM, proxies, or
cloud services. Postgres in Docker and a local Ollama model, and that's it.

**Evidence or it doesn't exist.** Every signal and hypothesis traces back to a stored
source snapshot. The system never claims a company has a problem because the model thinks
it's common in that industry.

It is not a job-hunting tool. Hiring signals count as evidence *against* a prospect.

## Setup

No credentials, API keys, or accounts are needed.

```bash
# 1. Python 3.12 environment
curl -fsSL https://astral.sh/uv/install.sh | sh     # if uv isn't installed
uv venv --python 3.12
uv pip install -e ".[dev]"

# 2. Configuration
cp .env.example .env                                 # defaults match docker-compose.yml

# 3. Database
docker compose up -d
.venv/bin/alembic upgrade head

# 4. Local models (Ollama installed separately: https://ollama.com/download)
ollama pull numind/nuextract3:q4_k_m                 # extraction; namespace is required
ollama pull qwen3.5:4b                               # generation

# 5. Run
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. `/health` reports database connectivity.

## Development

```bash
.venv/bin/pytest                 # needs Postgres up; uses a separate test database
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/alembic revision --autogenerate -m "description"
```

## Layout

```
app/
  main.py            FastAPI app, routes, templates
  config.py          settings from environment / .env
  db/                engine, session, declarative base
  models/            SQLAlchemy models (import every one in __init__.py)
  services/          one package per pipeline stage, per spec section 14
  jobs/              scheduled job handlers
  templates/         Jinja2 + HTMX
  static/            vendored Pico.css and HTMX — no CDN
migrations/          Alembic
spike/               Phase 0 feasibility harness (see spike/README.md)
tests/
```

## Things that are intentional, not oversights

**Sync SQLAlchemy.** One operator, no concurrency pressure. Async would complicate the job
handlers for no measurable gain.

**No Redis, Celery, or vector database.** APScheduler with Postgres job rows is sufficient
for one user. Postgres full-text search is sufficient for a personal dataset. These get
added when a measured bottleneck demands them, not before (spec section 12.1).

**Ollama on the host, not in Compose.** This machine has no discrete GPU, so the model
needs direct CPU access.

**Vendored CSS and JS.** The UI works offline and depends on no third-party service.

**LLM calls never happen in a request.** Inference here runs at roughly 4 minutes per page
on CPU. All model work is background jobs, and unchanged pages are never re-sent to the
model — that skip is what makes ongoing operation affordable.

**No LinkedIn automation, ever.** The engine recommends a buyer *role* and files a manual
research task. It does not scrape LinkedIn and does not guess email addresses.

## Security

Bound to `127.0.0.1` with no authentication. Do not expose it to a network until task
P10-7 adds an auth gate. Secrets live only in `.env`, which is gitignored. Fetched web
content is treated as untrusted input, both for rendering and as model input.
