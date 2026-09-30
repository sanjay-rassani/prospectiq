# Phase 0 spike

Answers one question: **can a CPU-only local model produce evidence-backed signals and
hypotheses good enough to build a product on?**

This machine has no discrete GPU, so the answer is not obvious, and it determines model
choices, refresh cadence, and whether hypothesis generation is automatic or
operator-assisted.

## Run it

```bash
# 1. Ollama must be installed and serving on 127.0.0.1:11434
ollama pull nuextract3:q4_k_m          # extraction (4B, Apache-2.0)
ollama pull qwen3.5:4b                 # generation; try 9b only if 4b output is unusable

# 2. List your sample pages
cp urls.example.txt urls.txt && $EDITOR urls.txt

# 3. Fetch, run, score
source ../.venv/bin/activate
python fetch_pages.py
python run_spike.py --extract-model nuextract3:q4_k_m --gen-model qwen3.5:4b
python verify.py
```

## What to put in urls.txt

Ten pages, labelled. The labels aren't decoration — `verify.py` uses them to check that
excluded targets are actually rejected.

- **6-7 `normal`**: real companies you'd genuinely want as clients. Favour pages where
  something is *happening* — a product launch, an expansion announcement, a blog post
  about an operational problem. A homepage alone is often signal-free.
- **1-2 `dud`**: a real company whose site is pure vague marketing. Must produce no
  positive signals.
- **1 `recruiter`**: a staffing or recruiting firm. Must be flagged as an excluded target.
  This is the guard against the spec's primary failure mode of drifting into job hunting.

## Reading the result

`verify.py` automates what it can. Two outcomes matter most:

**Evidence excerpts verbatim** is the go/no-go. An excerpt that isn't in the source means
the model invented proof, and the entire evidence guarantee (spec §6.2) is unimplementable
on that model. The report separates near-misses (punctuation tidying, fixable by prompting)
from genuine fabrication.

**The hypotheses themselves** only you can judge. Five of ten should be things you'd
actually act on. If facts extract cleanly but hypotheses are generic, that's a *conditional*
pass: build the pipeline, but treat generation as a draft the operator rewrites.

## Files

| File | Role |
| --- | --- |
| `schemas.py` | Output schemas. **The durable artifact** — becomes `app/services/llm` in Phase 3. |
| `prompts.py` | Prompts, including the first draft of untrusted-input framing (P3-4). |
| `ollama_client.py` | Thin client: constrained JSON, validation, bounded retries. |
| `fetch_pages.py` | Rehearsal of the Phase 2 fetcher; hashes extracted text, not HTML. |
| `run_spike.py` | Runs the three tasks over every page, records latency. |
| `verify.py` | Automated rubric plus the manual-review dump. |

`pages/` and `out/` are gitignored; the code is tracked because the schemas and prompts
graduate into the real application.
