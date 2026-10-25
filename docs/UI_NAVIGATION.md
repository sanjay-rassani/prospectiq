# ProspectIQ — UI & navigation guide

Complete map of every screen, control, and typical workflow. Base URL: `http://127.0.0.1:8000`.

The app is **server-rendered** (FastAPI + Jinja + Pico.css). There is no React/Angular SPA. Clicking a button usually submits a form and reloads the page (or streams logs via SSE on Discover).

---

## 1. Global chrome (every page)

| Element | Location | What it does |
| --- | --- | --- |
| **ProspectIQ** logo + wordmark | Top-left | Click → home (`/`). Hover: “Go to Today…” |
| **Today** | Top-center nav | Daily desk — hover explains priority deals / drafts / follow-ups |
| **Companies** | Top-center nav | Discover, seed, research — hover explains |
| **Contacts** | Top-center nav | People directory — hover explains |
| **Outreach** | Top-center nav | Drafts & follow-ups — hover explains (you send) |
| **Settings** | Top-center nav | Profile, feeds, exports — hover explains |
| Footer note | Bottom | Reminder that sending is manual; times are PKT + US Eastern in brackets |
| Datetimes | Everywhere | Filter `when` → e.g. `23 Oct 2026, 11:40 AM PKT (2:40 AM EDT)` |
| Yellow **flash** | Under page title | One-shot success/error message from last action |

`aria-current="page"` highlights the active nav item. Hover any nav link for a new-user tip (`title=`).

Destructive / special actions use an in-app confirm modal via `data-confirm` on the form (not the browser dialog): delete company/contact, archive, remove feed, reject/approve/mark-sent, lifecycle move, stale check, reject lead, override, generate draft.

---

## 2. Site map (all HTML routes)

```
/                              Today
/companies                     Company list
/companies/discover            Lead discovery (primary)
/companies/seed                Manual domain/URL paste
/companies/{id}                Company detail
/opportunities/{id}            Opportunity detail
/contacts                      Contacts directory
/contacts/{id}                 Contact detail
/outreach                      Outreach queue
/outreach/{id}                 Outreach draft
/settings                      Settings
/jobs/failed                   Failed / running jobs
/login                         Auth (only if bound off-localhost)
/logout                        Clear auth cookie
/health                        JSON health (API)
/docs                          OpenAPI (only when DEBUG=true)
/export/companies.json         Download
/export/opportunities.csv      Download
/export/interactions.csv       Download
```

---

## 3. Recommended end-to-end journey

```
Settings (who you sell to)
    ↓
Discover (filters → Save → Run → Results)
    ↓
Qualify / Save lead  →  Company detail (research runs in background)
    ↓
Opportunity detail (scores, buyer role, contacts)
    ↓
Prepare outreach brief  →  Outreach draft (edit → approve → you send)
    ↓
Mark sent  →  Record reply / next follow-up
    ↓
Today (see what is due)
```

**Secondary path:** Companies → Seed → paste a known domain.

**Contacts path:** Company detail → Discover contacts → Contacts list/detail → use on opportunity outreach.

---

## 4. Today (`/`) — home desk

**Corrected product prompt:** Today is the welcome + attention desk: explain what the app does, put **Discover** / **Seed** / **Settings** up front, show pipeline counts, a short getting-started path (first-run or collapsible guide), then the usual attention lists. Stay in ProspectIQ/Pico styling — not a SaaS marketing landing page.

| Section | Contents | Actions |
| --- | --- | --- |
| Hero | What ProspectIQ does (you send; app never auto-sends) | **Discover leads**, **Seed a URL**, **Settings** |
| Snapshot stats | Priority deals, drafts, follow-ups, companies, contacts, ready | Click → jump to section or list |
| Welcome / How-to | First-run 3 steps, or collapsible guide for returning users | Links into Settings / Discover / Seed |
| Action tiles | Discover, Seed, Companies, Outreach | Large clickable areas |
| High-priority opportunities | Table: company, title, score, status | → company / opportunity |
| Drafts / follow-ups | Due outreach work | → `/outreach/{id}` or opportunity |
| Newly changed | Resurfaced + 48h content changes | → company |
| Footer | Attention count · Failed jobs | → `/jobs/failed` |

---

## 5. Companies list (`/companies`)

| Control | What it does |
| --- | --- |
| **Discover** | Go to lead discovery |
| **Seed** | Paste known URLs/domains |
| Table row name | Open company detail |
| **Delete** | Permanently remove company + cascaded data (confirm dialog) |

Columns: Name, Domain, Status, ICP Fit (+ priority band), Snapshots count, Last researched.

---

## 6. Discover (`/companies/discover`) — primary lead finder

Layout: **left = filters**, **right = Run log + Results**.

### 6.1 Header

| Control | What it does |
| --- | --- |
| **Seed URL** | Jump to manual seed (known URL) |

### 6.2 Left: Who (targeting)

Form posts to `POST /companies/discover/prefs` via **Save filters**.

| Control | What it does |
| --- | --- |
| **Preset** | Fills keyword/exclude checkboxes from a named recipe (`balanced`, `ai_software`, …). Does not wipe Type/Services. |
| **Type** chips | Lead kinds: Projects, Need developers, Startups, SMBs, Enterprise, Schools/unis, Research, Gov/nonprofit, Other |
| **Services** chips | What you sell (Backend/API, SaaS, AI/ML, Automation, …). Used to build search queries and score matches |
| **Industries** chips | Target industries |
| **Match** | Flexible = boost industry hits; Strict = drop listings with no industry terms |
| **Locations** | Multi-select dropdown of all countries (+ region shortcuts) |
| **Must include** | Keywords that *must* appear or the lead is discarded |
| **Allow remote / unknown location** | Keep listings without a clear place |
| **Min score** | Relevance 0–100; below this is not saved as a lead |

**More filters** (collapsed `<details>`):

| Control | What it does |
| --- | --- |
| Budget min/max/currency | Only used when a listing *publishes* a budget (never invented) |
| Keywords / Exclude groups | Topic include/exclude for RSS-style matching |
| Extra keywords / excludes | Free-text comma lists |
| Use Settings industries | Also match industries from Settings profile |
| Skip social links | Do not treat LinkedIn/Twitter/etc. as company sites |

### 6.3 Left: Sources

Built-in adapters only (no marketplace scrapers): Hacker News, UK Contracts Finder, SearXNG, GitHub public issues, RSS/Atom, plus **your custom sources**.

| Control | What it does |
| --- | --- |
| Checkboxes next to sources | Enable that adapter for the next Run |
| Badge **on** | Source is available without extra config |
| Badge **setup** | Needs env config (e.g. SearXNG URL) |
| **Search engines** | Which SearXNG engines to query when SearXNG is on. Prefers local `SEARXNG_URL`, then optional public instances from [searx.space](https://searx.space/) (checkbox). Run then **visits public result pages** and scores page text — never scrapes Google HTML. Public instances often block bots; local compose SearXNG is more reliable. |
| **Your custom sources** | Add public RSS/Atom URLs by name; remove individually; enable via `custom_sources` |
| Prefer buying intent | Boost high-intent language in scoring |
| Max / source | Cap candidates pulled per adapter |
| Max seed | Cap how many domains auto-save into Companies |
| Auto-save company domains | When a lead has a real company domain, seed it |
| Skip known domains | Do not re-seed domains already in Companies |
| **Save filters** | Persist all of the above into `config/operator_profile.yaml` |

Marketplaces (Upwork, Fiverr, LinkedIn) are **not** scraped — paste a URL via Seed if you found something manually.

**RSS feeds** (collapsed): list existing feeds; add via suggested dropdown or custom name/URL/kind → `POST /companies/discover/feeds`.

### 6.4 Right: Run

| Control | What it does |
| --- | --- |
| **Run discovery** | First POSTs the current left-panel filters to `/companies/discover/prefs?ajax=1` (so Run always uses what is selected, not only a prior Save), then opens SSE `GET /companies/discover/poll/stream`. Log shows applied filters + progress; page reloads when done. |
| **Discovery history** | Under the Run log. One run: expands inline. Two or more: opens a popup listing recent polls; expand a row for that run’s log. |

Live log is also kept on each finished run (stored on a `discover_leads` job row).

### 6.5 Right: Results

| Control | What it does |
| --- | --- |
| Intent / Status dropdowns + **Filter** | Reload page with query params. Default status is **Active (hide rejected)**; choose **Rejected only** to review rejects. |
| Lead title link | Opens original source URL in a new tab |
| Intent badge | `high` / `potential` / `emerging` / `low` (buying-intent class — **not** ICP Fit) |
| Score | Relevance 0–100 |
| **Select all** / row checkboxes | Choose leads, then bulk **OK** / **Save** / **Reject** |
| **OK** | Mark lead(s) `qualified` |
| **Save** | Seed company from domain if possible → open company; else qualify + flash |
| **Reject** | Mark lead(s) `rejected` (hidden from Active; re-discovery keeps rejection) |
| **company** link | If already linked to a Company |

Counts: new · qualified · saved · rejected.

**Recent companies from feeds** (collapsed): companies seeded from RSS entries.

### 6.6 Intent class meanings

| Badge | Meaning |
| --- | --- |
| high | Explicit request (looking for developer, RFP, tender…) |
| potential | Company-like match without an explicit ask |
| emerging | Expansion / transformation language |
| low | Weak evidence |

---

## 7. Seed (`/companies/seed`)

| Control | What it does |
| --- | --- |
| Textarea | One domain/URL/`Name \| domain` per line |
| **Fetch** | `POST /companies/seed` — fetch page, store snapshot, queue research |
| **Discover** | Back to Discover |
| **Cancel** | Company list |

After fetch: single target → company detail; multiple → company list with flash.

---

## 8. Company detail (`/companies/{id}`)

Breadcrumb: Companies → name.

### Header actions

| Button | What it does |
| --- | --- |
| **Refresh now** | Re-fetch seed/company URL; new snapshot only if content changed |
| **Delete company** | Cascade-delete company and related rows (confirm) |

### Sections (top → bottom)

| Section | What you see / do |
| --- | --- |
| Last error / Excluded | Diagnostics if research failed or company was excluded |
| **ICP Fit** | Company-level fit score + dimension table (timing-blind) |
| **Extracted facts** | Observed facts from LLM extraction (linked to snapshot) |
| **Signals** | Evidence-backed change cues with excerpts |
| **Opportunities** | Hypotheses; click title → opportunity detail; superseded in `<details>` |
| **Contacts** | People table + company channels + research tasks |
| **Source snapshots** | History of fetched pages (hash, HTTP, change) |
| **Feedback** | Mark prospect good/bad (threshold hints only) |

### Contacts block buttons

| Control | What it does |
| --- | --- |
| **Discover contacts** | Queue job to fetch about/team/contact pages and extract people |
| **Refresh contacts** | Same with refresh=1 |
| **All contacts** | Contacts directory filtered to this company |
| Name link | Contact detail |
| **Add contact** form | Manual name/role/email/profile → Save contact |

---

## 9. Opportunity detail (`/opportunities/{id}`)

Breadcrumb: Companies → company → title.

**Corrected product prompt (what we built):**  
Redesign Opportunity detail for non-experts as a **stepper** (Understand → Find contact → Outreach → Follow up → Manage). Every step has a plain-language “what this is” help line. Contact finding uses layered actions: (A) scan public company website pages with loading/status UI; (B–C) open Google/LinkedIn search links in the operator’s browser (they use their own accounts — the app never logs in or scrapes LinkedIn/Google); (D) paste a contact found manually. Outreach never auto-sends.

**What this page is:** a 5-step workspace for one deal idea. Top tip explains that nothing is sent automatically.

### Stepper (always visible)

| Step | Purpose (plain language) |
| --- | --- |
| **1 Understand** | Why this company, what we could offer, company-fit vs deal-timing scores, evidence |
| **2 Find contact** | Find the buyer person via website scan / Google / LinkedIn (your browser) / paste |
| **3 Outreach** | Prepare brief + draft — you send outside the app |
| **4 Follow up** | Log sends/replies and next actions |
| **5 Manage** | Lifecycle status + stale-evidence check |

Query `?step=1…5` selects the panel. Default step is inferred (missing contact → 2, drafts → 3, interactions → 4).

### Step 2 — Find contact layers

| Layer | Control | What it does |
| --- | --- | --- |
| **A** | **Find contacts on website** | SSE `/opportunities/{id}/discover-contacts/stream` runs the scan and streams a single-line live log (URL currently being fetched) |
| **A** | **Refresh scan** | Same with refresh=1 |
| **B** | **Open Google search** | New tab: role + company (+ site:domain) — you research manually |
| **B** | **Google → LinkedIn profiles** | New tab: `site:linkedin.com/in` search |
| **C** | **Open LinkedIn search** | New tab: LinkedIn people search (you use your own login) |
| **C** | **Open company site** / people page links | Manual browse |
| **D** | **Save contact** form | Paste name/role/email/profile found yourself |

The app **never** logs into LinkedIn/Google and **never** scrapes them. Loading UI is only for Layer A (website scan job).

### Other opportunity controls

| Control | What it does |
| --- | --- |
| Score tables / story | Read-only narrative + optional “Why this deal score?” |
| **Override** (advanced) | Force `outreach_ready` with required reason |
| **Prepare outreach brief** | Pick contact + channel → creates outreach task |
| **Record interaction** | Log channel/direction/outcome + next action |
| **Move status** | watch, nurture, conversation, project_lead, rejected, closed |
| **Check stale evidence** | Apply stale-evidence stop rule |

Email channel requires a public email on the contact. **Nothing is sent by the app.**

---

## 10. Contacts (`/contacts`)

### List filters (`GET` query params)

| Filter | Effect |
| --- | --- |
| Search `q` | Name, role, email, company |
| Company | Restrict to one company |
| Email | Has / no email |
| Profile | Has / no profile URL |
| Seniority | c-level, founder, vp, … |
| Status | discovered, enriched, needs_research |
| **Filter** | Apply |
| Pagination | Previous / Next when > 50 |

Click name → contact detail; company name → company detail.

### Contact detail (`/contacts/{id}`)

| Control | What it does |
| --- | --- |
| **Enrich / re-discover** | Queue company contact discovery job |
| **Archive** | Soft-hide contact |
| Field provenance table | Per-field value, status, source URL, excerpt |
| Relevant opportunities | Why this person ranks for each opp |
| **Edit / verify** form | Correct fields; optional “manually verified” checkboxes |
| **Save** | Persist edits |
| **Delete permanently** | Hard delete |

Email status (`source_confirmed`, `manually_verified`, …) is **evidence strength**, not deliverability.

---

## 11. Outreach (`/outreach`)

### Queue

| Section | What it does |
| --- | --- |
| Awaiting action | Pending / draft_ready / approved / rejected tasks |
| Due follow-ups | Interactions whose next action is due |
| Ready without task | Opportunities outreach-ready but no open task |

Click a row → draft detail.

### Draft detail (`/outreach/{id}`)

| Control | What it does |
| --- | --- |
| Brief (read-only) | Deterministic assembly from evidence — not LLM |
| Draft textarea + **Save draft** | Your edited message |
| **Generate with local model** | Ollama draft (if LLM enabled); still needs your approve |
| **Approve** | Marks approved — does **not** send |
| **Reject** | Requires reason |
| **I sent it — mark sent** | After you send outside the app |
| Interaction timeline | History for this opportunity |

---

## 12. Settings (`/settings`)

| Section | Controls |
| --- | --- |
| **Exports** | Download companies JSON, opportunities CSV, interactions CSV |
| **Target profile & thresholds** | Same control style as Discover: industry checkboxes, country multi-select, excluded industries, services/solution-family checkboxes, score bands, refresh intervals, model labels (labels only — real models in `.env`) → **Save profile** |
| **Company pipeline adapters** | Read-only registry (Seed, RSS, page refresh, …) |
| **Discover sources** | Read-only list of lead adapters (HN, Contracts UK, SearXNG, GitHub issues, RSS, custom). Enable/configure on Discover |
| **Feeds** | Per feed: **Poll**, **Toggle**, **Remove**; form to **Add** RSS / github_releases / changelog |
| **Domain fetch policy** | Opt-in Playwright per domain |
| **Recent operator feedback** | Good/bad notes from company pages |

Profile file path is shown under the title (`config/operator_profile.yaml`). Discover filters (sources, engines, lead types) stay on **Discover → Save filters**.

---

## 13. Failed jobs (`/jobs/failed`)

| Section | Meaning |
| --- | --- |
| Scheduler status | Running / stopped; enabled flag |
| Failed table | Job type, entity id, attempts, error, correlation id |
| Currently running | Jobs locked right now |
| Back to Today | Link |

Jobs are processed by the in-process scheduler (not a separate worker). LLM/fetch work never runs inside a normal page click except Discover’s SSE stream and Seed/Refresh which trigger fetch+queue.

---

## 14. Login (`/login`) — optional

Only relevant if the app is bound beyond `127.0.0.1` and `AUTH_TOKEN` is set. Otherwise localhost needs no login.

| Control | What it does |
| --- | --- |
| Token field + submit | Sets auth cookie |
| `/logout` | Clears cookie |

---

## 15. Glossary (UI terms)

Statuses and bands show **friendly labels** (e.g. `outreach_ready` → **Ready to approach**). Hover any dotted-underline label for the full explanation. Source of truth: `app/ui/labels.py`.

| Term | Meaning |
| --- | --- |
| **Lead** | Discovery candidate (project or org listing). Not yet a full company research record |
| **Company** | Tracked organization with domain, snapshots, ICP Fit |
| **Snapshot** | Stored text of a fetched page + content hash |
| **Signal** | Observed change/cue with verbatim excerpt |
| **Opportunity** | Project *hypothesis* tied to signals |
| **Ready to approach** (`outreach_ready`) | Worth preparing a message — you still send it yourself |
| **Draft ready for you** (`draft_ready`) | Outreach draft waiting for your edit/approve |
| **ICP Fit** | “Is this our kind of customer?” (no timing) |
| **Opportunity Score** | “Is this idea worth acting on now?” |
| **Intent class** | Buying-intent label on a Discover lead |
| **Contact / Person** | Named individual from public pages or manual entry |
| **Outreach task** | Brief + draft you approve; you send outside ProspectIQ |
| **Research task** | To-do when no matching person exists for a buyer role |

---

## 16. What the app never does in the UI

- Never sends email or LinkedIn messages
- Never scrapes LinkedIn / Google / Upwork / Fiverr login areas
- Never invents emails or budgets
- Never treats format-valid email as “verified deliverable”
- Never runs long LLM work inside a simple button click (except generating a draft when you ask, and background jobs after Seed/Refresh)

---

## 17. Quick “where do I…?” index

| I want to… | Go to |
| --- | --- |
| Find new leads automatically | **Companies → Discover** → Save filters → Run |
| Add a known website | **Companies → Seed** |
| See my pipeline | **Companies** list / company detail |
| Find people at a company | Company detail → **Discover contacts** |
| Search all people | **Contacts** |
| Score / promote a deal idea | Opportunity detail |
| Draft a message | Opportunity → Prepare brief → **Outreach** |
| Log a reply | Opportunity → Record interaction |
| See what is due today | **Today** |
| Change ICP / industries | **Settings** |
| Download data | **Settings → Exports** |
| Debug broken jobs | **Today → Failed jobs** |
| Check API is up | `/health` |

---

*Generated from the ProspectIQ templates and routes. If a control is missing from this doc after a UI change, prefer the live page over this file.*
