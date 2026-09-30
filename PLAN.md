# Prospecting Engine — Build Plan

Companion to `prospecting-engine-final-v1.3.docx`. The spec defines *what*; this defines *in what
order*, *how we'll know it works*, and *what we decided along the way*.

Task IDs (`P1-4`) are stable references. Acceptance refs (`FR-03`, `AC-4`) point back to spec
sections 17 and 21.

---

## Environment (measured 2026-09-30)

| Fact | Value | Consequence |
| --- | --- | --- |
| OS | Ubuntu 26.04.1 LTS | — |
| CPU | 8 cores | CPU-only inference; small models only |
| RAM | 30 GB total, ~15 GB free | One resident model at a time |
| GPU | Intel Iris Xe (integrated) | **No CUDA.** Expect 4-15 tok/s |
| Docker | 29.8.1, Compose v5.5.1 | Postgres via Compose |
| Python | 3.14.4 system | Pin 3.12 via uv (wheel availability) |
| Postgres | client only, no cluster | Container is the only instance |
| Ollama | not installed | P0-1 |

**The single most important consequence:** every LLM call is slow enough that it can never happen
inside an HTTP request. All model work runs as background jobs, and the snapshot-hash rule
(FR-03) is what keeps the system affordable rather than merely tidy.

---

## Phase 0 — Feasibility spike (before any application code)

Goal: find out whether a CPU-only local model can produce signals and hypotheses worth acting on.
If it can't, the product needs rethinking, and that is much cheaper to learn now.

- [x] **P0-1** Install Ollama; confirm it serves on `127.0.0.1:11434`.
- [x] **P0-2** Pull `numind/nuextract3:q4_k_m` (3.4 GB, Apache-2.0) as the extraction model.
      The namespace is required; bare `nuextract3:q4_k_m` does not resolve.
- [x] **P0-3** Pull one general instruct model for generation/drafting: `qwen3.5:4b` (3.4 GB).
      Escalate to ~9B only if 4B output quality proves unusable.
- [ ] **P0-4** Save 8-10 real company pages to `spike/pages/` by hand — mix of homepages, about
      pages, blog/news posts, product announcements. Include at least one dud (vague corporate
      site with no signal) and one recruiter/staffing site, which must be correctly rejected.
- [x] **P0-5** Write draft JSON schemas for `extract_company_facts` and `extract_signals`.
      Every signal object must carry a verbatim `evidence_excerpt` copied from the source.
- [x] **P0-6** Run extraction through NuExtract3's template protocol with `temperature: 0`
      and `think: false`. Record wall-clock time per page.
- [x] **P0-7** Draft `generate_opportunities` prompt; run it on the extracted signals.
- [ ] **P0-8** Score results against the rubric below and write the verdict into `DECISIONS.md`.

### P0 pass/fail rubric

Judge each of the 10 pages manually:

| Check | Threshold |
| --- | --- |
| Valid JSON matching schema, after ≤2 retries | 10/10 |
| Company facts materially correct (no invented industry/size) | ≥8/10 |
| `evidence_excerpt` is genuinely present in the source text | 10/10 — **zero tolerance** |
| Signals are real observations, not industry platitudes | ≥7/10 |
| At least one hypothesis you'd personally act on, for pages that warrant it | ≥5/10 |
| Dud and recruiter pages produce no signals / negative signal | 2/2 |
| No opportunity built only on `negative_weak` evidence | zero violations |
| Extraction latency per page | note it; >120s forces design changes |

### Smoke-test findings (synthetic page, before real URLs)

Both protocols work end to end on first attempt, with all evidence excerpts verbatim and a
hiring mention correctly classed `negative_weak`.

Measured on CPU: facts ~48s, signals ~48s, hypotheses ~130s, so roughly **4 minutes per
page**. Above the 120s guideline, which confirms rather than contradicts the architecture —
LLM work must be background-only, and the snapshot-hash skip is what makes the ongoing cost
bearable. Revisit only if a full refresh cycle stops fitting in its window.

The generation model produced a third hypothesis resting solely on the hiring signal —
precisely the job-hunting drift the spec forbids. Fixed in the prompt *and* as a
deterministic check in `verify.py`, since prompting alone cannot be trusted with a rule
this important (spec §15.2).

**Go:** rubric passes → proceed to Phase 1 with model choices locked.
**Conditional:** facts fine but hypotheses weak → proceed, but treat hypothesis generation as
operator-assisted (system proposes, operator rewrites) and revisit the model later.
**No-go:** fabricated evidence excerpts → stop. Fix prompting/model before building anything,
because the entire evidence guarantee in spec §6.2 depends on this.

Deliverable: a short written verdict, chosen model tags, measured latency, and the first real
versions of two JSON schemas. The spike code is throwaway; the schemas are not.

---

## Phase 1 — Foundation

Goal: the app boots, talks to Postgres, and has migrations. No domain logic yet.

- [x] **P1-1** `git init`; `.gitignore` covering `.env`, `__pycache__`, spike scratch, `*.dump`.
- [x] **P1-2** Install uv; pin Python 3.12 (`.python-version`); create `pyproject.toml`.
- [x] **P1-3** Create the repo layout from spec §19 (`app/`, `app/services/*`, `migrations/`,
      `tests/`) with package `__init__.py` files.
- [x] **P1-4** `docker-compose.yml` with Postgres 17, named volume, port bound to `127.0.0.1`
      only. Ollama stays a host service (needs the CPU directly).
- [x] **P1-5** `app/config.py` with pydantic-settings; `.env.example` committed, `.env` ignored.
- [x] **P1-6** SQLAlchemy 2.x setup, sync engine + session factory. Sync is correct here — one
      operator, and async adds nothing but complexity.
- [x] **P1-7** Alembic initialised and pointed at the app's metadata, with the URL read from
      settings so credentials live only in `.env`.
- [x] **P1-8** FastAPI app with `/health` checking DB connectivity; bound to `127.0.0.1` (NFR §18).
- [x] **P1-9** Jinja2 + HTMX + Pico.css base template and shell layout. Both assets vendored
      into `app/static` rather than loaded from a CDN (decision D-13).
- [x] **P1-10** ruff + mypy config; pytest with a per-session test database.
- [x] **P1-11** `README.md`: setup from zero, no paid credentials (AC-1).

**Milestone reached.** `docker compose up` brings up Postgres 17, `alembic upgrade head`
applies the baseline revision, `/health` returns `{"status":"ok","database":"ok"}`, and the
Today page renders with vendored assets. Verified that stopping Postgres flips `/health` to
`degraded` and restarting it recovers without an app restart, so the check is meaningful
and `pool_pre_ping` works. ruff and mypy clean, 4 tests passing.

---

## Phase 2 — Ingest and change detection

Goal: paste a domain, get durable evidence. This is the foundation everything else reads from.

- [x] **P2-1** `Company` model per spec §13 + normalized-domain unique index.
- [x] **P2-2** Domain normalization helper: strip scheme, `www.`, trailing slash, lowercase,
      handle subdomains. Unit-test it hard — dedup correctness (FR-02) lives here.
- [x] **P2-3** `SourceSnapshot` model incl. `content_hash`, `previous_hash`, `published_at`.
- [x] **P2-4** Fetcher: httpx with timeouts, per-domain rate limit, global concurrency cap,
      identifying user-agent, conditional requests via ETag/Last-Modified (§11).
- [x] **P2-5** `robots.txt` check and cache before any fetch.
- [x] **P2-6** Content extraction with trafilatura → text, title, `published_at`.
- [x] **P2-7** Hash the *extracted text*, not raw HTML — raw HTML churns on every request
      (nonces, timestamps, CSRF tokens) and would defeat change detection.
- [x] **P2-8** Manual-seed adapter: accept name / domain / URL / pasted list (FR-01).
- [x] **P2-9** Company-page adapter: re-fetch known URLs, diff against `previous_hash`.
- [x] **P2-10** UI: seed form, company list, company detail showing snapshot history.
- [x] **P2-11** Tests with recorded HTTP fixtures: new snapshot, unchanged content, 304, 404,
      redirect chain, timeout.

**Milestone reached.** Paste a domain → snapshot stored with hash → re-fetch creates no
duplicate row. Verified live against `example.com`: first seed stored one snapshot; second
seed of the same domain returned `unchanged; no new snapshot` with still one row in
`source_snapshots`. 34 tests passing (normalize, fetcher fixtures, seed/refresh).
**Acceptance:** FR-01, FR-02, FR-03, AC-2, AC-3.

---

## Phase 3 — LLM gateway and fact extraction

Goal: one narrow, well-behaved seam between deterministic code and the model.

- [x] **P3-1** `app/services/llm/` gateway: single entry point, Ollama HTTP client, strict
      `json_schema` format, `temperature: 0`, `think: false`, explicit timeouts.
- [x] **P3-2** Pydantic output schemas per task; validate then bounded-retry (max 2) on failure.
- [x] **P3-3** Prompt files with version identifiers; persist model name + prompt version +
      raw output on every call for debugging (§15.2).
- [x] **P3-4** **Untrusted-input handling.** Fetched text is hostile by default: wrap it in
      explicit delimiters, state in the system prompt that page content is data and never
      instruction, cap input length, and strip obvious injection patterns. The spec flags this
      (§18) without specifying a mitigation — this task is that mitigation.
- [x] **P3-5** `extract_company_facts` wired to new snapshots only.
- [x] **P3-6** Skip rule: unchanged hash never reaches the model (AC-3), enforced in code and
      covered by a test that asserts zero model calls.
- [x] **P3-7** Company detail UI: facts with a link to the originating snapshot.

**Milestone reached.** New snapshots run `extract_company_facts` through the local gateway
(NuExtract template protocol by default); results land on `companies.facts_json` with
`facts_snapshot_id` linking back to the source. Unchanged re-fetches create no snapshot and
make zero model calls (asserted in tests). Every call is persisted in `llm_calls` with
model, prompt version, raw output, and errors. 39 tests passing.
**Acceptance:** AC-3 (skip unchanged), AC-2 path extended with traceable facts.

---

## Phase 4 — Signals and opportunity hypotheses

Goal: the actual product value — evidence becomes a testable project idea.

- [x] **P4-1** `Signal` model with type enum from §6.3, incl. negative/weak evidence.
- [x] **P4-2** `extract_signals` task; reject any signal whose `evidence_excerpt` is not
      literally present in the snapshot text. Silent drop + log, never persist.
- [x] **P4-3** `Opportunity` model with the full §7.1 field set.
- [x] **P4-4** `OpportunityEvidence` join table.
- [x] **P4-5** `generate_opportunities`: company + signals → hypotheses, each linked to evidence.
- [x] **P4-6** Solution-family enum from §3.2; reject outputs that invent a family.
- [x] **P4-7** Fact / inference / hypothesis labelling surfaced in the UI (§6.2).
- [x] **P4-8** Opportunity detail page: problem, hypothesis, why-now, evidence, confidence,
      unknowns.
- [x] **P4-9** Change-triggered re-evaluation: a new signal re-runs hypothesis generation.

**Milestone reached.** New snapshots run facts → signals → opportunities. Fabricated
`evidence_excerpt` values are dropped before persist. Hypotheses that cite only
`negative_weak` signals are discarded. A content change with new signals supersedes prior
active opportunities and writes a fresh set with evidence links. Company detail and
opportunity detail pages label observed / inference / hypothesis. 43 tests passing.
**Acceptance:** FR-04, FR-06, AC-4, AC-5.

---

## Phase 5 — Scoring and priority

Goal: rank honestly and explain why. **The spec gives weights but not inputs — that design work
happens here.**

- [ ] **P5-1** Operator profile storage (spec §2.1): positioning, capabilities, target industries
      and regions, exclusions, commercial preferences. Start as a single settings row or YAML;
      the settings UI comes in Phase 9.
- [ ] **P5-2** Define concrete, deterministic inputs for each ICP dimension (§8.1). Write them
      down before coding — this is where hidden judgement calls accumulate.
- [ ] **P5-3** Implement ICP Fit. Assert in tests that **no timing/buying signal** can influence
      it (§8.1 explicitly forbids this).
- [ ] **P5-4** Define inputs for each Opportunity Score dimension (§8.2), incl. how signal
      recency maps to the timing component.
- [ ] **P5-5** Implement Opportunity Score.
- [ ] **P5-6** Human-readable score reasons per dimension, persisted alongside the number.
- [ ] **P5-7** Priority bands (High / Medium / Watch / Reject) with configurable thresholds.
- [ ] **P5-8** Exclusion rules: recruiters, staffing, do-not-contact, unwanted geo/industry.
- [ ] **P5-9** `OUTREACH_READY` promotion gate per §7.2, with operator override + reason.
- [ ] **P5-10** UI shows the two scores separately, never blended (AC-6).

**Milestone:** two companies with identical ICP Fit sit in different priority bands purely
because one has fresh evidence.
**Acceptance:** FR-05, FR-11, AC-6.

---

## Phase 6 — Buyer role and people

Goal: know who to talk to without crossing the scraping line.

- [ ] **P6-1** `Person` model (nullable email, `source`, `verified_at`).
- [ ] **P6-2** Deterministic opportunity→role mapping table from §9.1.
- [ ] **P6-3** `recommend_buyer_role` for nuance, constrained to the mapping's vocabulary.
- [ ] **P6-4** Person capture from permitted public pages (team/about/contact) only.
- [ ] **P6-5** Manual research task generator — "Find Head of Operations on LinkedIn" — when no
      reliable person exists (§9.2).
- [ ] **P6-6** Hard guardrails: no LinkedIn scraping, no email pattern guessing. Enforce in code
      and state it in the README so future-you doesn't "improve" it.
- [ ] **P6-7** UI: people on company detail, role recommendation on opportunity detail.

**Acceptance:** FR-07.

---

## Phase 7 — Outreach and interactions

Goal: a reviewable draft and a memory of what happened. Sending stays human.

- [ ] **P7-1** `OutreachTask` model with status lifecycle.
- [ ] **P7-2** Outreach brief assembly per §10.1 (deterministic, not generated).
- [ ] **P7-3** `draft_outreach` constrained by §10.2: lead with context, never assert hypotheses
      as fact, never invent clients/metrics/familiarity.
- [ ] **P7-4** Editable draft + explicit approve/reject; approval is operator-only.
- [ ] **P7-5** `Interaction` model; record sent/reply/outcome with next action (FR-09).
- [ ] **P7-6** `summarize_interaction` → outcome + suggested next step, operator-editable.
- [ ] **P7-7** Lifecycle state machine from §10.3 incl. WATCH / NURTURE / DISQUALIFIED / CLOSED.
      State transitions are deterministic Python only — never model output (§15.2).
- [ ] **P7-8** Outreach queue screen and per-opportunity interaction timeline.
- [ ] **P7-9** Stop/nurture rules: declined, irrelevant, unresponsive after N, evidence stale.

**Milestone:** brief → draft → approve → record reply → a due next action appears.
**Acceptance:** FR-08, FR-09, AC-7, AC-8.

---

## Phase 8 — Scheduler, monitoring, resurfacing

Goal: it keeps working while you don't look at it.

- [ ] **P8-1** `Job` model per §13 (`due_at`, `attempts`, `last_error`, `locked_at`).
- [ ] **P8-2** APScheduler 3.x in-process, with Postgres `Job` rows as the durable record.
- [ ] **P8-3** Row-level locking so a restart mid-job doesn't duplicate or lose work.
- [ ] **P8-4** Idempotent job handlers; capped exponential backoff on failure (§18).
- [ ] **P8-5** Adaptive refresh cadence per §11 (High 1-3d, Medium 7d, Watch 14d, Nurture 30d).
- [ ] **P8-6** `next_refresh_at` computed on priority change.
- [ ] **P8-7** Resurfacing: meaningful change on a dormant company raises priority and surfaces
      it on Today.
- [ ] **P8-8** Follow-up reminder jobs from `Interaction.next_action_at`.
- [ ] **P8-9** "Today" screen: high-priority opportunities, due outreach, newly changed prospects.
- [ ] **P8-10** Failed-jobs view (§18 observability).
- [ ] **P8-11** Restart-safety test: kill mid-run, confirm no state loss (AC-10).

**Acceptance:** FR-10, AC-9, AC-10.

---

## Phase 9 — Discovery breadth and settings

Only now, once the pipeline is proven. Adding sources earlier just scales noise.

- [ ] **P9-1** RSS/Atom adapter with feedparser; dedupe by entry id/link.
- [ ] **P9-2** Feed management UI (add/remove/enable).
- [ ] **P9-3** Adapter registry with per-source enable/disable and rate config (§5).
- [ ] **P9-4** Settings screen: target profile, offer families, thresholds, refresh intervals,
      adapters, model selection.
- [ ] **P9-5** Operator feedback capture (good/bad prospect) stored with reasons. Feeds
      deterministic threshold tuning only — no training claims (§2.3).
- [ ] **P9-6** Optional, permitted-only: public technical sources (GitHub, changelogs).
- [ ] **P9-7** Playwright fallback, opt-in per domain, only where HTTP is genuinely insufficient.

**Acceptance:** FR-01 (full), FR-12.

---

## Phase 10 — Hardening

- [ ] **P10-1** Nightly `pg_dump` via systemd timer, with retention.
- [ ] **P10-2** JSON/CSV export of companies, opportunities, interactions.
- [ ] **P10-3** Documented restore-from-backup drill, actually performed once.
- [ ] **P10-4** Structured logging with correlation ids across job runs.
- [ ] **P10-5** Output sanitization before rendering fetched content (§18 XSS).
- [ ] **P10-6** Secrets audit: nothing but `.env`; confirm nothing is committed.
- [ ] **P10-7** Auth gate that activates if bound beyond localhost.
- [ ] **P10-8** Walk the full §21 acceptance list and tick every line.

---

## Open questions the spec leaves to us

| # | Question | Resolve by |
| --- | --- | --- |
| Q1 | Concrete inputs for each scoring dimension | P5-2, P5-4 |
| Q2 | Which "conditional" directories are actually permitted | P9-3, case by case |
| Q3 | What operator feedback mechanically changes | P9-5 |
| Q4 | Prompt-injection mitigation specifics | P3-4 |
| Q5 | Whether a 4B model can draft usable outreach on CPU | P0-3, P0-8 |
| Q6 | "Meaningful change" threshold vs. trivial page edits | P8-7 |

---

## Decision log

Record as we go, with reasoning. Seeded with what's already settled:

| ID | Decision | Why |
| --- | --- | --- |
| D-01 | Python 3.12 via uv, not system 3.14 | Wheel availability for lxml/Playwright |
| D-02 | Sync SQLAlchemy | Single operator; async buys nothing |
| D-03 | Postgres in Docker, Ollama on host | Model needs direct CPU access |
| D-04 | trafilatura over readability | Maintained; also yields `published_at` |
| D-05 | APScheduler pinned to 3.x | 4.x churn; 3.x is stable |
| D-06 | Two models: NuExtract3 for extraction, general instruct for generation | Different jobs; both Apache-2.0 |
| D-07 | Hash extracted text, not raw HTML | Raw HTML churns and breaks change detection |
| D-08 | No SSPL/BSL dependencies ever | Long-term license safety |
| D-09 | NuExtract3 via its native template protocol, not JSON Schema | It takes no system prompt; `verbatim-string` enforces the evidence rule at the model level |
| D-10 | NuExtract templates derived from the same Pydantic models | One source of truth; the two wire formats cannot drift |
| D-11 | `num_ctx` 8192, not the model default 131072 | KV cache at 131k would not fit in available RAM |
| D-12 | Negative-evidence citation blocked deterministically, not just by prompt | Job-hunting drift is the spec's primary failure mode |
| D-13 | Pico.css and HTMX vendored, not CDN-loaded | UI must work offline and depend on no third-party service |
| D-14 | Alembic URL from `app.config`, `alembic.ini` left blank | One place for credentials; migrations cannot target a different database than the app |
| D-15 | Tests build schema from `Base.metadata`, not by replaying migrations | Fast suite; migration correctness verified separately against the real database |
| D-16 | `psycopg` 3 over `psycopg2` | Current driver, actively maintained, first-class SQLAlchemy 2.x support |
| D-17 | Hash extracted text; skip insert when hash matches latest | Raw HTML churn would defeat change detection; AC-3 requires no duplicate work |
| D-18 | robots.txt fail-open on fetch errors | Broken robots endpoint must not permanently block an explicitly seeded public page |
| D-19 | Keep meaningful subdomains (`blog.x.com` ≠ `x.com`) | Over-collapsing would merge distinct properties; only strip `www` |
| D-20 | Persist every LLM call in `llm_calls` | Spec §15.2 auditability; failures are inspectable without re-running |
| D-21 | `facts_snapshot_id` FK with `use_alter` | Avoid create-order deadlock between companies and source_snapshots |
| D-22 | `LLM_ENABLED` gate; tests default off, inject FakeGateway | Seed works without Ollama; AC-3 tests count real gateway calls |
| D-23 | Drop signals whose excerpt is not in source text | Spec §6.2: fabricated evidence must never persist |
| D-24 | Discard opportunities that cite only `negative_weak` | Deterministic block on job-hunting drift (extends D-12) |
| D-25 | Supersede active opportunities on signal-triggered re-eval | Change-triggered refresh (P4-9) without mutating history |
