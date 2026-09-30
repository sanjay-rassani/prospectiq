"""Run the Phase 0 extraction pipeline over the sample pages (tasks P0-6, P0-7).

Usage:
    python run_spike.py --extract-model nuextract3:q4_k_m --gen-model qwen3.5:4b

Writes one JSON result per page into spike/out/, then prints a latency table. The verdict
itself comes from verify.py plus your own reading of the hypotheses.
"""

import argparse
import json
import sys
from pathlib import Path

import prompts
from ollama_client import available_models, call
from schemas import CompanyFacts, OpportunityList, SignalList

SPIKE = Path(__file__).parent
PAGES = SPIKE / "pages"
OUT = SPIKE / "out"


def run_page(meta: dict, text: str, extract_model: str, gen_model: str) -> dict:
    print(f"\n=== {meta['slug']}  ({meta['text_chars']} chars, label={meta['label']})")

    print("  facts...", end="", flush=True)
    facts = call(
        model=extract_model,
        system=prompts.EXTRACT_FACTS_SYSTEM,
        user=prompts.facts_user_prompt(meta["url"], text),
        output_model=CompanyFacts,
        prompt_version=prompts.PROMPT_VERSION,
    )
    print(f" {facts.seconds:.1f}s ok={facts.ok} attempts={facts.attempts}")

    print("  signals...", end="", flush=True)
    signals = call(
        model=extract_model,
        system=prompts.EXTRACT_SIGNALS_SYSTEM,
        user=prompts.signals_user_prompt(meta["url"], text),
        output_model=SignalList,
        prompt_version=prompts.PROMPT_VERSION,
    )
    n = len(signals.parsed.signals) if signals.parsed else 0
    print(f" {signals.seconds:.1f}s ok={signals.ok} signals={n}")

    result = {
        "meta": meta,
        "facts": {
            "ok": facts.ok,
            "seconds": round(facts.seconds, 2),
            "attempts": facts.attempts,
            "errors": facts.errors,
            "output": facts.parsed.model_dump(mode="json") if facts.parsed else None,
            "raw": None if facts.ok else facts.raw_output,
        },
        "signals": {
            "ok": signals.ok,
            "seconds": round(signals.seconds, 2),
            "attempts": signals.attempts,
            "errors": signals.errors,
            "output": signals.parsed.model_dump(mode="json") if signals.parsed else None,
            "raw": None if signals.ok else signals.raw_output,
        },
        "opportunities": None,
    }

    # Hypothesis generation needs signals to build on, and needs the larger model. Skipping
    # it on signal-free pages is not a shortcut: an opportunity with no signal is exactly
    # what spec section 7.2 forbids.
    if signals.ok and signals.parsed and signals.parsed.signals and facts.parsed:
        print("  opportunities...", end="", flush=True)
        opps = call(
            model=gen_model,
            system=prompts.GENERATE_OPPORTUNITIES_SYSTEM,
            user=prompts.opportunities_user_prompt(
                json.dumps(facts.parsed.model_dump(mode="json"), indent=2),
                json.dumps(signals.parsed.model_dump(mode="json"), indent=2),
            ),
            output_model=OpportunityList,
            prompt_version=prompts.PROMPT_VERSION,
        )
        count = len(opps.parsed.opportunities) if opps.parsed else 0
        print(f" {opps.seconds:.1f}s ok={opps.ok} opportunities={count}")
        result["opportunities"] = {
            "ok": opps.ok,
            "seconds": round(opps.seconds, 2),
            "attempts": opps.attempts,
            "errors": opps.errors,
            "output": opps.parsed.model_dump(mode="json") if opps.parsed else None,
            "raw": None if opps.ok else opps.raw_output,
        }
    else:
        print("  opportunities... skipped (no signals)")

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-model", default="nuextract3:q4_k_m")
    parser.add_argument("--gen-model", default="qwen3.5:4b")
    parser.add_argument("--only", help="Run a single page by slug substring.")
    args = parser.parse_args()

    try:
        installed = available_models()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot reach Ollama at 127.0.0.1:11434 ({exc}). Is `ollama serve` running?")
        return 1

    for model in (args.extract_model, args.gen_model):
        if model not in installed:
            print(f"Model not installed: {model}\nInstalled: {installed or '(none)'}")
            return 1

    metas = sorted(PAGES.glob("*.json"))
    if args.only:
        metas = [m for m in metas if args.only in m.stem]
    if not metas:
        print(f"No pages in {PAGES}. Run fetch_pages.py first.")
        return 1

    OUT.mkdir(exist_ok=True)
    results = []
    for meta_path in metas:
        meta = json.loads(meta_path.read_text())
        text = (PAGES / f"{meta['slug']}.txt").read_text()
        result = run_page(meta, text, args.extract_model, args.gen_model)
        (OUT / f"{meta['slug']}.json").write_text(json.dumps(result, indent=2))
        results.append(result)

    print(f"\n{'page':<42} {'facts':>8} {'signals':>8} {'opps':>8}")
    for r in results:
        opps = f"{r['opportunities']['seconds']:.1f}s" if r["opportunities"] else "-"
        print(
            f"{r['meta']['slug'][:42]:<42} "
            f"{r['facts']['seconds']:>7.1f}s {r['signals']['seconds']:>7.1f}s {opps:>8}"
        )

    total = sum(
        r["facts"]["seconds"]
        + r["signals"]["seconds"]
        + (r["opportunities"]["seconds"] if r["opportunities"] else 0)
        for r in results
    )
    print(f"\nTotal {total:.0f}s across {len(results)} pages "
          f"({total / len(results):.0f}s per page)")
    print(f"Results in {OUT}. Now run: python verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
