# Spec §21 acceptance checklist (P10-8)

Walked 2026-10-07 against the running local stack.

| # | Criterion | Status | Notes |
| --- | --- | --- | --- |
| AC-1 | Starts locally with documented setup and no paid credentials | pass | `README.md` + `.env.example`; no paid APIs |
| AC-2 | Manually seeded company researched with source evidence | pass | Phase 2–3 seed + snapshots + facts |
| AC-3 | Unchanged page not repeatedly sent to the LLM | pass | content-hash skip; tests assert zero model calls |
| AC-4 | Changed source can create a signal and re-evaluate opportunities | pass | Phase 4 supersede + regenerate |
| AC-5 | Opportunity shows evidence, why-now, buyer role, confidence, unknowns, score reasons | pass | opportunity detail UI |
| AC-6 | ICP Fit and Opportunity Score visibly separate | pass | Phase 5 UI + tests |
| AC-7 | LinkedIn/email outreach brief without LinkedIn automation | pass | Phase 7 deterministic brief; no scrape |
| AC-8 | Operator can record a reply and receive a due next action | pass | Phase 7 interactions |
| AC-9 | Dormant companies refreshed by cadence and can resurface | pass | Phase 8 cadence + resurface |
| AC-10 | Restart does not lose prospects, jobs, or interaction state | pass | Postgres + stale-lock recovery test |
| AC-11 | Core works with PostgreSQL + local Ollama only | pass | no Redis/Celery/cloud APIs |

Restore drill (P10-3): documented in `README.md` and `scripts/restore_pg.sh`. Perform once on a spare database before relying on backups in production use.
