# Scoring inputs (Phase 5)

The spec gives weights, not inputs. These are the concrete, deterministic rules. Change them
deliberately — they encode commercial judgement.

## ICP Fit (company-level) — §8.1

Answers only: *Is this the kind of business we want as a client?*

**Forbidden inputs:** any `Signal`, any `Opportunity`, any freshness/timing field, any
`why_now`. Tests assert that adding strong growth signals does not change ICP Fit.

| Dimension | Weight | Inputs (deterministic) |
| --- | --- | --- |
| Business fit | 30% | Industry match vs `target_industries`; penalty if industry in `excluded_industries`; hard 0 if recruiter/staffing/job page in facts. |
| Ability to buy | 25% | `size_hint` map (large/medium high, small mid, solo/unclear low); B2B/both preferred over B2C/unclear. |
| Outsourcing plausibility | 20% | Penalise solo; boost when products/services are named (real operating business); agencies only if `allow_agency_white_label`. |
| Solution-domain fit | 15% | Overlap between facts technologies/products tokens and operator `capabilities` / `preferred_solution_families`. |
| Decision-maker accessibility | 10% | Geography overlap with `target_regions`; mid-market sizes preferred; never uses signals. |

## Opportunity Score (opportunity-level) — §8.2

Answers: *Is there a credible project worth approaching now?*

| Dimension | Weight | Inputs (deterministic) |
| --- | --- | --- |
| Evidence strength | 25% | Mean strength of *linked* signals (strong=1.0, moderate=0.66, weak=0.33). |
| Timing / why-now | 20% | Age of newest linked signal snapshot (`fetched_at`): ≤3d=100, ≤7d=80, ≤14d=60, ≤30d=40, else 20. Boost if any linked signal type is growth/product/ai/leadership. |
| Solution fit | 20% | `solution_family` in operator `preferred_solution_families` (100) else 40. |
| Potential business value | 15% | Confidence map (high=85, medium=60, low=35) minus 5 per unknown (floor 10). |
| Buyer relevance | 10% | Buyer role present and matches known role vocabulary keywords (100/60/30). |
| Confidence / unknowns | 10% | Confidence map minus 8 per unknown (floor 0). |

## Priority bands

Derived from Opportunity Score (not ICP): High / Medium / Watch / Reject via configurable
thresholds in the operator profile. ICP Fit is shown separately and never blended (AC-6).

## OUTREACH_READY (§7.2)

Promoted only when: not excluded; has ≥1 evidence link; non-empty hypothesis + buyer role;
Opportunity Score ≥ `outreach_ready_min`; and either a recent (≤14d) linked signal or at
least one strong linked signal. Operator may override with a stored reason.
