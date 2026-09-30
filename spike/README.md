# Phase 0 spike

Answers one question: **can a CPU-only local model produce evidence-backed signals and
hypotheses good enough to build a product on?**

This machine has no discrete GPU, so the answer is not obvious, and it determines model
choices, refresh cadence, and whether hypothesis generation is automatic or
operator-assisted.

## Run it

```bash
# 1. Ollama must be installed and serving on 127.0.0.1:11434
ollama pull numind/nuextract3:q4_k_m   # extraction (4B, Apache-2.0). Note the namespace:
                                       # bare `nuextract3:q4_k_m` does not resolve.
ollama pull qwen3.5:4b                 # generation; try 9b only if 4b output is unusable

# 2. List your sample pages
cp urls.example.txt urls.txt && $EDITOR urls.txt

# 3. Fetch, run, score
source ../.venv/bin/activate
python fetch_pages.py
python run_spike.py                    # defaults to the two models above
python verify.py
```

## Two models, two protocols

Extraction and generation are different jobs, so they use different models and different
wire formats.

**NuExtract3** takes no system prompt. It expects an extraction *template* in its own
vocabulary via a `template` message role, with `instructions` standing in for the system
prompt. `schemas.nuextract_template()` derives that template from the same Pydantic models
that validate the output, so the two representations cannot drift.

Its native `verbatim-string` type is why it's here: it means "copy this exactly from the
source", which is precisely the guarantee `evidence_excerpt` needs. That moves the evidence
rule from something we request in a prompt to something the model was trained to do, and
leaves `verify.py` as a check the model should pass by construction.

**qwen3.5:4b** handles hypothesis generation through an ordinary system prompt plus
grammar-constrained JSON via Ollama's `format` parameter.

Passing `--extract-model qwen3.5:4b` switches extraction to the general model and the
standard protocol, which is the comparison to run if the verdict comes out borderline.

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
| `schemas.py` | Output schemas + both renderers (JSON Schema, NuExtract template). **The durable artifact** — becomes `app/services/llm` in Phase 3. |
| `prompts.py` | System prompts and NuExtract `instructions`, including the first draft of untrusted-input framing (P3-4). |
| `ollama_client.py` | Thin client: both protocols, validation, bounded retries. |
| `fetch_pages.py` | Rehearsal of the Phase 2 fetcher; hashes extracted text, not HTML. |
| `run_spike.py` | Runs the three tasks over every page, records latency. |
| `verify.py` | Automated rubric plus the manual-review dump. |

`pages/` and `out/` are gitignored; the code is tracked because the schemas and prompts
graduate into the real application.
