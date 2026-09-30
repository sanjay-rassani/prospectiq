"""Score the spike results against the Phase 0 rubric (task P0-8).

Automates every check that can be automated. The remaining question -- "would I actually
act on this hypothesis?" -- only you can answer, so the report ends with the hypotheses
laid out for reading.

The evidence check is the one that can sink the project. If the model writes an
`evidence_excerpt` that is not in the source, it is fabricating proof, and spec section 6.2
is unimplementable on that model.
"""

import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

SPIKE = Path(__file__).parent
PAGES = SPIKE / "pages"
OUT = SPIKE / "out"

# Cosmetic differences we forgive: models routinely straighten curly quotes and dashes.
# Anything beyond this is a content change, which is what we are actually testing for.
TRANSLATIONS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u00a0": " ", "\u2026": "...",
})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(TRANSLATIONS)
    return re.sub(r"\s+", " ", text).strip().casefold()


def best_match_ratio(needle: str, haystack: str) -> float:
    """How close the excerpt came to appearing in the source.

    Distinguishes a near-miss (model tidied punctuation, ~0.95) from an invention
    (~0.4), which changes the diagnosis from "tighten the prompt" to "wrong model".
    """
    matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
    match = matcher.find_longest_match(0, len(needle), 0, len(haystack))
    return match.size / len(needle) if needle else 0.0


def main() -> int:
    results = sorted(OUT.glob("*.json"))
    if not results:
        print(f"No results in {OUT}. Run run_spike.py first.")
        return 1

    pages = len(results)
    schema_ok = 0
    evidence_total = 0
    evidence_verbatim = 0
    evidence_failures: list[dict] = []
    label_checks: list[tuple[str, str, bool, str]] = []
    uncited_opportunities: list[str] = []
    negative_only_opportunities: list[str] = []
    numeric_claims: list[tuple[str, str]] = []
    latencies: list[float] = []
    review: list[dict] = []

    for path in results:
        r = json.loads(path.read_text())
        slug = r["meta"]["slug"]
        label = r["meta"]["label"]
        source = normalize((PAGES / f"{slug}.txt").read_text())

        calls = [r["facts"], r["signals"]] + ([r["opportunities"]] if r["opportunities"] else [])
        if all(c["ok"] for c in calls):
            schema_ok += 1
        latencies.append(sum(c["seconds"] for c in calls))

        facts = r["facts"]["output"] or {}
        signals = (r["signals"]["output"] or {}).get("signals", [])

        for signal in signals:
            excerpt = normalize(signal["evidence_excerpt"])
            evidence_total += 1
            if excerpt and excerpt in source:
                evidence_verbatim += 1
            else:
                evidence_failures.append({
                    "slug": slug,
                    "type": signal["type"],
                    "excerpt": signal["evidence_excerpt"][:160],
                    "ratio": round(best_match_ratio(excerpt, source), 2),
                })

        # Excluded targets must be identified, and must not generate positive signals.
        if label == "recruiter":
            flagged = bool(facts.get("is_recruiter_or_staffing"))
            label_checks.append((slug, label, flagged, "flagged as recruiter/staffing"))
            positive = [s for s in signals if s["type"] != "negative_weak"]
            label_checks.append((
                slug, label, not positive,
                f"no positive signals (found {len(positive)})",
            ))
        elif label == "dud":
            positive = [s for s in signals if s["type"] != "negative_weak"]
            label_checks.append((
                slug, label, not positive,
                f"no positive signals (found {len(positive)})",
            ))

        opportunities = (r["opportunities"] or {}).get("output") or {}
        for opp in opportunities.get("opportunities", []):
            indexes = opp.get("supporting_signal_indexes") or []
            if not indexes or any(i < 0 or i >= len(signals) for i in indexes):
                uncited_opportunities.append(f"{slug}: {opp['title']} -> {indexes}")
            else:
                # An opportunity resting only on negative_weak evidence -- typically a
                # hiring page -- is the spec's primary failure mode: drifting from project
                # work into job hunting. Prompting alone does not reliably prevent it, so
                # this stays a deterministic check (spec section 15.2).
                cited = [signals[i]["type"] for i in indexes]
                if cited and all(t == "negative_weak" for t in cited):
                    negative_only_opportunities.append(
                        f"{slug}: {opp['title']} -> cites only {cited}"
                    )
            # Invented numbers are forbidden by spec section 7.1; flag for human reading
            # rather than failing, since a figure quoted from the page is legitimate.
            outcome = opp.get("business_outcome", "")
            if re.search(r"\d+\s*(%|percent|x\b|hours|days|weeks)", outcome):
                numeric_claims.append((slug, opp["business_outcome"][:140]))
            review.append({"slug": slug, "label": label, "opp": opp})

    print("=" * 78)
    print("PHASE 0 RUBRIC")
    print("=" * 78)

    def line(name: str, got: str, passed: bool | None) -> None:
        mark = "PASS" if passed else ("FAIL" if passed is False else "----")
        print(f"  [{mark}] {name:<52} {got}")

    line("Schema-valid output on all calls", f"{schema_ok}/{pages} pages", schema_ok == pages)
    line(
        "Evidence excerpts verbatim (zero tolerance)",
        f"{evidence_verbatim}/{evidence_total}",
        evidence_total > 0 and evidence_verbatim == evidence_total,
    )
    if label_checks:
        passed = sum(1 for *_, ok, _ in label_checks if ok)
        line("Dud / recruiter pages rejected", f"{passed}/{len(label_checks)} checks",
             passed == len(label_checks))
    else:
        line("Dud / recruiter pages rejected", "no labelled pages", None)
    line("Opportunities cite valid signals", f"{len(uncited_opportunities)} violations",
         not uncited_opportunities)
    line("No opportunity built only on negative evidence",
         f"{len(negative_only_opportunities)} violations", not negative_only_opportunities)

    if latencies:
        worst = max(latencies)
        line("Latency per page", f"avg {sum(latencies) / len(latencies):.0f}s, worst {worst:.0f}s",
             worst <= 120)

    if evidence_failures:
        print("\n" + "=" * 78)
        print("EVIDENCE FAILURES -- this is the go/no-go check")
        print("=" * 78)
        for f in evidence_failures:
            verdict = "near-miss, likely fixable by prompt" if f["ratio"] >= 0.85 else "FABRICATED"
            print(f"  {f['slug']} [{f['type']}] match={f['ratio']} -- {verdict}")
            print(f"    {f['excerpt']!r}")

    if label_checks:
        failed = [(s, why) for s, _, ok, why in label_checks if not ok]
        if failed:
            print("\nEXCLUSION FAILURES")
            for slug, why in failed:
                print(f"  {slug}: {why}")

    if uncited_opportunities:
        print("\nOPPORTUNITIES WITH BAD CITATIONS")
        for item in uncited_opportunities:
            print(f"  {item}")

    if negative_only_opportunities:
        print("\nOPPORTUNITIES BUILT ON NEGATIVE EVIDENCE (job-hunting drift)")
        for item in negative_only_opportunities:
            print(f"  {item}")

    if numeric_claims:
        print("\nNUMERIC CLAIMS TO CHECK BY HAND (legitimate only if quoted from the page)")
        for slug, claim in numeric_claims:
            print(f"  {slug}: {claim}")

    print("\n" + "=" * 78)
    print(f"MANUAL REVIEW -- {len(review)} hypotheses. Would you send an email about these?")
    print("=" * 78)
    for item in review:
        o = item["opp"]
        print(f"\n  [{item['slug']}] ({item['label']}) confidence={o['confidence']}")
        print(f"  title:      {o['title']}")
        print(f"  problem:    {o['problem_or_change']}")
        print(f"  hypothesis: {o['project_hypothesis']}")
        print(f"  why now:    {o['why_now']}")
        print(f"  buyer:      {o['buyer_role']}")
        print(f"  family:     {o['solution_family']}")
        print(f"  unknowns:   {'; '.join(o['risks_or_unknowns']) or '(none stated)'}")

    print("\nThreshold: at least 5 of 10 pages should yield a hypothesis you would act on.")
    print("Record the verdict, chosen models, and latency in DECISIONS.md (task P0-8).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
