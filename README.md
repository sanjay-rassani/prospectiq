# ProspectIQ

Self-hosted B2B prospecting for one operator. You seed companies from public pages; the
engine snapshots evidence, detects change, scores fit, and drafts outreach you review and
send yourself.

**No paid APIs — free only.** Postgres in Docker + local Ollama; discovery via public
feeds and manual seed (not paid search, not Google/LinkedIn login bots).  
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

# 3. Database (+ optional SearXNG on :8080 for Discover web research)
docker compose up -d
.venv/bin/alembic upgrade head
# Set SEARXNG_URL=http://127.0.0.1:8080 in .env after SearXNG is up.

# 4. Models (~7 GB total)
ollama pull numind/nuextract3:q4_k_m   # reads pages → facts & signals
ollama pull qwen3.5:4b                # drafts opportunities & outreach

# 5. Run
.venv/bin/uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Check `/health` if something looks wrong.

### First session

1. **Settings** — who you sell to and score thresholds.
2. Add companies:
   - **Seed** — paste domains/URLs you already know, or
   - **Discover** — add RSS/Atom/GitHub-release feeds; poll to import new company links.
3. Wait (CPU inference is slow). Use **Today** and **Failed jobs**.
4. Open a company → facts → signals → opportunities.
5. Open an opportunity → prepare outreach → edit/approve → you send → log the reply.

No Google scrape and no auto-email. LLM work never runs inside a page click. Unchanged pages are skipped.

---

## Understand the site

Top nav: **Today · Companies · Outreach · Settings**.

### The pipeline (in order)

```
Targeting filters → Discover (HN / UK tenders / optional SearXNG / RSS)
  → scored leads (intent class ≠ ICP Fit)
  → qualify / save → fetch page → snapshot
  → extract facts → extract signals
  → score ICP Fit (company) + Opportunity Score (deal idea)
  → recommend buyer role → contacts → draft outreach (you send)
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

- **Discover** (`/companies/discover`) — **default lead-gen path.** Set lead type, services,
  industries, geography, and keywords; pick permitted sources; **Run discovery** (live SSE).
  Results are scored leads (high-intent project vs potential company vs emerging vs low
  relevance), not automatic companies. Qualify / reject / save into the research pipeline.
- **Seed** — paste domains/URLs you already know (secondary).
- **Feeds** — optional RSS/Atom/GitHub releases still work as a supplementary source.
- **List** — all companies and status.
- **Detail** — ICP Fit + reasons, extracted facts, signals, opportunities, **contacts**,
  snapshot history, good/bad feedback, **Refresh now**, delete.
  Use **Discover contacts** to fetch about/team/leadership/contact pages (robots-respecting),
  extract named people and public emails, and store generic inboxes separately as company channels.

Open an **opportunity** from here for scores, evidence, buyer role, and outreach.
Short tips appear on Today, Companies, Seed, Discover, Outreach, and Settings.

### Contacts (`/contacts`)

Searchable directory of people discovered from permitted company pages or added manually.
Filter by company, email/profile availability, seniority, and discovery status.
Open a contact for field-level provenance, quality score, verification controls, and
relevant opportunities. Email labels mean evidence strength (`source_confirmed`,
`manually_verified`) — never inbox deliverability.

**Sources (implemented):** company about/team/leadership/contact pages from the company
domain (and existing snapshots of those paths). Explicit emails/phones/profile URLs on
those pages. Manual operator entry. Generic `info@` / `sales@` go to company channels,
not people.

**Not implemented (by design):** LinkedIn scraping, mailbox guessing, SMTP probing,
paid enrichment APIs, CAPTCHA bypass. If a buyer role has no matching person, a **research
task** asks you to find and paste a public profile or email.

### Opportunity detail (`/opportunities/…`)

One deal idea: problem, hypothesis, why-now, confidence, evidence quotes, Opportunity
Score (separate from ICP), buyer role / **ranked contacts**, promote to outreach-ready,
select a contact + channel, prepare draft, record interactions (sent / reply / next action),
lifecycle (watch / nurture / etc.).

### Outreach (`/outreach`)

Queue of drafts and due follow-ups. Open a task → edit draft → **approve** or reject →
mark sent yourself → come back when they reply. The app never emails for you.
Briefs prefills public email / profile URL only when evidence-backed on the selected contact.

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
| Add a known prospect | Companies → Seed |
| Find new leads | Companies → Discover (targeting + Run) |
| Remove a prospect | Companies → Delete (cascades all related data) |
| Judge fit / evidence | Company or opportunity detail |
| Find / enrich people | Company → Discover contacts, or Contacts |
| Send / follow up | Outreach (pick contact + channel) |
| Tune who you target | Settings |
| Fix broken background work | Failed jobs |

After pulling this feature, run migrations:

```bash
.venv/bin/alembic upgrade head
```

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

## Stack & why

Core web framework pieces (FastAPI, Uvicorn, SQLAlchemy, Pydantic, Jinja2, Postgres)
are assumed. Everything below is a deliberate pick — including third-party public
APIs and optional self-hosted services. Rule of thumb: **no paid APIs, no SSPL/BSL
deps, UI works offline.**

### Runtime & packaging

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package/env manager from Astral | Pins **Python 3.12** (not system 3.14) so wheels for `lxml` / optional Playwright stay available; one command to recreate the env. |
| **[hatchling](https://hatch.pypa.io/)** | PEP 517 build backend | Lightweight packaging for `uv pip install -e ".[dev]"` without a heavy setuptools layout. |
| **Docker Compose** | Runs companion services on localhost | Isolates **Postgres** and optional **SearXNG**; Ollama stays on the host for direct CPU access. |
| **Postgres 17 (Alpine image)** | Relational database in Docker | Durable store for companies, snapshots, jobs, LLM audit rows; bound to `127.0.0.1` only. |
| **[psycopg](https://www.psycopg.org/) 3** | Modern Postgres driver | Actively maintained successor to psycopg2; first-class SQLAlchemy 2.x support. |
| **[Alembic](https://alembic.sqlalchemy.org/)** | Schema migration tool | Versioned DB changes; URL comes from app config so migrations never target a different DB than the app. |
| **[APScheduler](https://apscheduler.readthedocs.io/) 3.x** | In-process job scheduler | Drains Postgres `Job` rows on a tick without Redis/Celery. Pinned to 3.x for API stability. |

### Local LLMs (host, not Docker)

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **[Ollama](https://ollama.com/)** | Local model runner (HTTP API on `:11434`) | Free, offline inference; no cloud LLM bills. Models need host CPU/RAM, so Ollama is not containerized. |
| **[NuExtract3](https://huggingface.co/numind/NuExtract-2.0-4B)** (`numind/nuextract3:q4_k_m`) | Extraction-specialist model (Apache-2.0) | Turns page text into facts/signals via NuExtract’s **template protocol** (not a free-form chat prompt). `verbatim-string` fields push the “evidence or it doesn’t exist” rule into the model. |
| **[Qwen3.5](https://ollama.com/library/qwen3.5)** (`qwen3.5:4b`) | Small general instruct model | Drafts opportunity hypotheses and outreach; constrained JSON via Ollama’s `format`. Separate from extraction so each model does one job. |

Context is capped (`LLM_NUM_CTX=8192`) so the KV cache fits typical RAM; every call is persisted in `llm_calls` for auditability.

### Fetching, parsing & change detection

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **[httpx](https://www.python-httpx.org/)** | HTTP client | Fetches public pages with timeouts, politeness delays, robots.txt checks, and easy mock transports in tests. |
| **[trafilatura](https://trafilatura.readthedocs.io/)** | HTML → main-text extractor | Maintained alternative to readability; also yields `published_at`. We **hash extracted text** (not raw HTML) so chrome churn doesn’t fake “page changed.” |
| **[feedparser](https://feedparser.readthedocs.io/)** | RSS/Atom parser | Polls operator-added feeds and GitHub `releases.atom` as a supplementary discovery source. |
| **[Playwright](https://playwright.dev/python/)** (optional) | Headless browser | Per-domain opt-in fallback when plain HTTP can’t get useful HTML (JS-heavy sites). Off by default; not required to run the app. |

### UI (vendored — no CDN)

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **[Pico.css](https://picocss.com/)** | Class-light CSS framework | Sensible defaults for a single-operator tool without building a design system. Copied into `app/static` so the UI works with no internet. |
| **[HTMX](https://htmx.org/)** | Small JS library for HTML-over-the-wire | Vendored for the same offline / no-third-party-service rule; progressive enhancement without an SPA. |
| **SSE (`EventSource`)** | Browser API for server-sent events | Live progress logs on Discover and contact scans — long CPU/LLM work must not sit inside a normal form POST. |

### Lead discovery sources (third-party / public)

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **Hacker News via [Algolia HN API](https://hn.algolia.com/api)** | Public, keyless search over HN | Finds Ask HN / hiring-builder style intent posts without scraping HTML or paying for search. |
| **[UK Contracts Finder](https://www.contractsfinder.service.gov.uk/)** (OCDS search) | UK gov procurement notices API | Free public tenders as high-intent project leads; no API key. |
| **[SearXNG](https://docs.searxng.org/)** | Self-hosted metasearch (JSON API) | Optional web research without scraping Google HTML or using paid SERP APIs. Prefer the Compose service on `:8080`; can also fail over to community instances listed on [searx.space](https://searx.space/). |
| **GitHub public API** (issues search) | Optional, rate-limited | Finds public “help wanted” / project signals; `GITHUB_TOKEN` recommended only for higher limits — still free. |

**Not used (by design):** paid enrichment, LinkedIn/Google HTML scrapers, Upwork/Fiverr search (import a listing URL via Seed only).

### Dev quality & ops

| Tech | What it is | Why we use it |
| --- | --- | --- |
| **[pytest](https://docs.pytest.org/)** | Test runner | Acceptance-style coverage (hash skip, fetcher, scoring) without needing Ollama (`LLM_ENABLED` / fake gateway). |
| **[Ruff](https://docs.astral.sh/ruff/)** | Linter/formatter | Fast, single-tool lint aligned with Astral’s uv toolchain. |
| **[mypy](https://mypy.readthedocs.io/)** (+ Pydantic plugin) | Static type checker | Catches contract drift on services that talk to LLMs and the DB. |
| **systemd timers** (`deploy/prospectiq-backup.*`) | Host cron-like scheduling | Optional nightly Postgres dumps via `scripts/backup_pg.sh`. |

Decision detail (IDs D-01…): [`PLAN.md`](PLAN.md).

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

## Lead discovery sources (what actually runs)

| Source | Status | Config |
| --- | --- | --- |
| Hacker News (Algolia public API) | **On by default** | None |
| UK Contracts Finder (public OCDS search) | **On by default** | None |
| RSS / Atom / GitHub releases.atom | Supplementary | Add feeds on Discover |
| SearXNG | Optional | `SEARXNG_URL` (self-hosted JSON API) |
| GitHub public issues | Optional, off by default | `GITHUB_TOKEN` recommended |
| Upwork / Fiverr | **Restricted** — not searched | Import a listing URL via Seed |
| LinkedIn / Google HTML | **Never** | — |

Intent class on a lead is **not** ICP Fit. Saving a lead with a company domain runs the existing snapshot/research pipeline. Project listings on HN/tender hosts stay as leads until you seed an organization URL. Contact discovery is a later, separate step.

```bash
.venv/bin/alembic upgrade head
```

---

## Security notes

Bound to `127.0.0.1` with no login by default. If you bind beyond localhost, set
`AUTH_TOKEN` in `.env`. Secrets stay in `.env` only — run `./scripts/audit_secrets.sh`
after changes. No LinkedIn scraping; no email guessing. Contact discovery refuses loopback/private
fetch targets (SSRF guard), respects robots.txt, and never labels format-valid emails as
verified.

Acceptance: [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md).
