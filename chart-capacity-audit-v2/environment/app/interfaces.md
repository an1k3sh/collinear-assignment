# Submission and executable contract

Create `readings.json`, `analyze.py`, `analysis.json`, `audit.json`, and
`decision.md` under `/app/submission`.

## Readings

Read all nine pages, including the obsolete revision. Keeping the source
inventory complete lets the pipeline explicitly resolve authority rather than
silently deleting evidence.

```
{
  "units": "base-counts",
  "counters": [
    {"page":"C1.r1","target":"AS","boundary":"B0",
     "requests":[0,0,0],"errors":[0,0,0]}
  ],
  "histograms": [
    {"page":"H1.r1","target":"AS","window":"W1",
     "bins":[[0,0,0],[0,0,0],[0,0,0],[0,0,0]]}
  ]
}
```

Zeros illustrate shape, not values. A whole missing metric is null.
Histograms are either a list of four intervals or null. Counter requests and
errors can independently be null. Cover every page's listed targets and every
operations boundary/window, including superseded pages, exactly once.

Do not put interpolated/made-up data in missing cells. Only the supplied images
determine original readings. All intervals are in base counts; no multiplying
by 1000 inside the calculation program.

## Program

```
python /app/submission/analyze.py \
  --readings /app/submission/readings.json \
  --manifest /app/export-manifest.json \
  --operations /app/operations.json \
  --planning /app/planning.json \
  --registry /app/registry.csv \
  --out /app/submission/analysis.json
```

Use only Python's standard library. All input/output paths may change. Work
from any current directory; do not use installed oracle modules. Valid probes
may reorder JSON lists, remove windows and unused boundary readings, replace
page IDs and supersession choices, change numeric readings, alter reset and
maintenance events, or change supported planning settings. Registry target
identities remain fixed but display names and row order may change.
Malformed-input probes stay within the rejection categories in policy.md.
Exit 0 on success; nonzero with explicit diagnostics on malformed input.

## Output

Use these fields (additional descriptive fields are allowed):

```
{
 "inventory": {
   "selected":["C1.r1"],
   "rejected":["C2.r1"],
   "by_target":{"AS":{"counters":"C1.r1","histograms":"H1.r1"}}
 },
 "intervals":[
   {"target":"AS","window":"W1","reason":"usable",
    "requests":[0,0,0],"errors":[0,0,0],"mean_requests_per_minute":0,
    "counter_page":"C1.r1","histogram_page":"H1.r1","latency_included":true}
 ],
 "targets":{
   "AS":{
     "usable_windows":["W1"],"histogram_windows":["W1"],
     "requests":0,"errors":0,"failure_fraction":null,"error_bounds":[0,0],
     "pooled_bins":[0,0,0,0],"sample_bounds":[0,0],"samples":0,
     "slow_fraction":null,"slow_bounds":[0,1],"p95_bin":null,
     "latency_eligible":false,"eligibility_stable":true,
     "rollout_eligible":false,"block_reason":"latency"
   }
 },
 "fleet":{"requests":0,"errors":0,"failure_fraction":null},
 "plan":{
   "tiers":{"AS":0},"credits":0,"power":0,"active_regions":[],
   "objective":0,"objective_bounds":[0,0],"residual_risk":0,
   "robust_margin":null,"robust":true
 },
 "scenarios":[
   {"credit_budget":0,"tiers":{"AS":0},"credits":0,"power":0,
    "active_regions":[],"objective":0}
 ]
}
```

Include ALL eight targets and 32 original target/window decisions. Sort
inventory lists lexically; intervals by target_order then operations window
order; window lists by operations order; active_regions lexically.
Counters on excluded windows still contain reconstructed values if available;
mean rate is null only when requests cannot be reconstructed.
`latency_included` is true only for usable traffic AND available bins.

`requests` and `errors` in each target and fleet are summed estimates.
`pooled_bins` are four summed estimates. `sample_bounds` sums all bin bounds.
`block_reason` is `latency` if latency-ineligible, otherwise `region_freeze` if
frozen, otherwise null. No deployment reason should be fabricated for an
eligible target that merely loses in the optimization.

The nominal plan includes all eight tier counts. Scenarios are exactly two
entries, first budget-2 clipped at zero, then budget+2; include the six plan
fields shown, without needing a separate robustness certificate.
All count/fraction/benefit consistency checks allow absolute tolerance 1e-5
plus relative tolerance 1e-6. This is arithmetic tolerance, not chart-reading
tolerance. Output must be finite JSON, with null where specified.

## Claim audit and memo

`audit.json`:

```
{"claims":[{"id":"R1","verdict":"incorrect",
 "evidence":["C1.r1","operations.json"],
 "explanation":"Your reasoning, referring to target and windows as needed."}]}
```

Exactly one verdict per R1..R8: `correct`, `incorrect`, or `unsupported`.
Evidence tokens may be actual page IDs or the supplied filenames
`operations.json`, `planning.json`, `export-manifest.json`, `corrections.md`,
`registry.csv`, `policy.md`. Each draft claim declares the sources needed to
evaluate it. Include those sources; any prose phrasing is allowed.

`decision.md`: explain the corrected rollout, resource bottleneck, missing/
excluded data, pooled-latency reasoning, source correction and unserved risk.
Cite source pages. Summarize both budget scenarios and state whether reading
uncertainty changes the decision. Prose is for human review; the automated
grader checks its presence, not style or exact phrases.

## Reward

Six components:

* extraction: fraction of individual counter metrics/histogram bins whose
  intervals cover the reference reading within the published width; null
  observations are checked explicitly.
* reconciliation: inventory family plus 32 interval-decision families.
* calculations: eight complete target summaries plus fleet totals.
* planning: nominal plan plus two independently optimized budget scenarios.
* claims: eight source-backed verdicts.
* reproducibility: fresh original run, all valid counterfactuals, all
  malformed-input diagnostics, and nonempty decision.md.

Overall is zero unless all source, reconciliation, calculation, planning and
reproducibility checks pass; extraction is >=0.98; all original missing-value
locations are preserved; and all eight claim verdicts/evidence pass. The
nominal original tiers and latency classifications must also match the
reference decision, which is stable across admissible chart-reading errors.

If gates pass:
`overall = .20*extraction + .20*reconciliation + .20*calculations
         + .20*planning + .10*claims + .10*reproducibility`.

The verifier calculates from YOUR readings, not an exact-value template.
Valid approximate extraction is accepted. It separately checks reference
coverage, so an internally consistent but unsupported transcription cannot
pass. No LLM judge, pixel-matching, source similarity or speed bonus is used.
