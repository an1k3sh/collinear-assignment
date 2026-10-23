# Reconciliation and rollout policy

## 1. Resolve authority before reading totals

Use registry.csv to map chart display names to stable target IDs. Resolve the
whole-page supersession edges in export-manifest.json: keep terminal pages,
reject superseded pages, and never add revisions together. Each target must
have exactly one selected counter page and one selected histogram page.
Page IDs, target IDs, and actual boundary/window IDs form evidence citations.

Readings in the submitted file are in BASE UNITS, not thousands. Counter
plots say "thousands"; multiply their displayed values by 1000. Latency pages
show independently normalized 100% stacked rows with exact printed sample total
N. Read each bin's segment share and multiply by that row's N to obtain counts
of sampled requests, not thousands. Submitted histogram intervals are COUNTS,
not percentages, cumulative boundaries or the row total repeated four times.
The unit multipliers in the manifest are authoritative.

Each available value is an interval `[low,estimate,high]`, containing the
plotted value and estimate. Maximum interval widths in base units:

* request counter: 2,000 requests;
* error counter: 40 failed requests;
* histogram bin: max(20, 0.005 * that row's printed N) sampled requests.

Exact readings may use zero-width intervals. UNKNOWN must be null. Do not
invent statistical confidence intervals; these bounds describe visual reading
uncertainty. Counter marker labels and latency row totals are part of the charts
and may be used. Bin shares must be read from the colored segment lengths.
Tiny or visually unresolved segments may have intervals including zero; you do
not need to resolve a segment smaller than its permitted uncertainty. Cropping,
zoom and pixel inspection are allowed; Pillow is installed for these authoring
operations. The submitted reusable analysis pipeline itself must use only the
standard library.

## 2. Reconstruct traffic intervals

For each target/window, separately reconstruct requests and errors.

* Without a documented reset, subtract the start-boundary counter from the
  end-boundary counter.
* With a documented reset for that metric/window, subtract its exact baseline
  from the end-boundary counter. Ignore the old-epoch start sample. Resets are
  metric-specific; a reset of errors does not reset requests.
* Missing required endpoints make that metric unknown. A missing old start
  sample is irrelevant when an exact reset baseline replaces it.
* Do not infer resets just because a line falls. An undocumented negative
  estimate is an input/instrument inconsistency and must cause an explicit
  error, not clamping or an invented reset.

For an interval difference, estimate = end_estimate - start_estimate,
low = max(0, end_low - start_high), high = end_high - start_low.
For exact reset baselines, low/high subtract that same baseline, with low
clipped at zero. A valid nonnegative estimate must lie in those bounds.

Persist all reconstructed values, including maintenance. A window is usable
iff it is not listed as maintenance AND both requests and errors can be
reconstructed. Reasons are `usable`, `maintenance`, or `missing_traffic`;
maintenance has precedence if both apply. Never infer a measured zero from
missing telemetry. The histogram does not replace missing traffic.

Cumulative deltas already are counts. Do NOT multiply them by window duration.
Mean requests/minute = reconstructed count / minutes. A duration change affects
mean rate, not the observed count. Every valid counterfactual has errors <=
requests, no counter wraparound, and resets only at window starts.

## 3. Join latency evidence and calculate workload

Sum requests/errors only over usable windows. A target's failure fraction is
total errors / total requests; return null if the denominator is zero.
Use fractions in [0,1], not percentages, in output.

Histogram bins are disjoint, with inclusive upper edges:

`<=100 ms`, `(100,300] ms`, `(300,1000] ms`, `>1000 ms`.

Only use histogram rows whose target/window traffic is usable AND whose entire
histogram is available. Missing latency does not invalidate usable traffic,
but cannot count toward a latency decision. Add BIN COUNTS over joined windows.
Do not average window percentiles or average normalized percentages. Latency
sample counts are independent subsamples, not the traffic denominator.

`samples` = sum pooled bins. `slow_fraction` = sum last two bins / samples.
The pooled p95 label is the first bin whose cumulative count is at least
95% of samples. It is a bin label, not an exact quantile; if no samples, both
slow_fraction and p95_bin are null.

`latency_eligible` requires at least `minimum_latency_samples` and
slow_fraction STRICTLY above `slow_fraction_trigger`. Use estimates for
nominal decisions. Record histogram window IDs in policy order.

For uncertainty, pool each bin's low and high separately. The slow-fraction
lower bound is slow_low / (slow_low + fast_high); upper is
slow_high / (slow_high + fast_low). Use [0,1] when a denominator is zero.
An eligibility decision is stable iff:

* eligible: sample_low >= minimum AND slow_low_bound > trigger;
* ineligible: sample_high < minimum OR slow_high_bound <= trigger.

This independent-envelope bound is conservative. The supplied charts have
stable classifications throughout allowed reading intervals.

## 4. Compute a constrained rollout

Each target offers tier 0, 1 or 2. Its cost, power and reduction arrays give
TOTALS for that tier, not incremental amounts. Zero tier has zero resources.
You may assign a positive tier only to a latency-eligible target in a region
that is not frozen. Reasons for no rollout must distinguish latency eligibility
from a regional change freeze.

Feasibility:

1. Sum target tier costs plus each ACTIVE region's activation_cost once; must
   not exceed credit_budget. A region is active iff any of its targets has
   positive tier.
2. Sum target power <= power_budget.
3. Number of active regions <= max_active_regions.
4. Sum tier NUMBERS within each region <= that region's max_blocks.
5. No positive tier for an ineligible target or frozen region.

Objective = sum usable errors * target risk_weight * reduction[tier].
These are supplied planning valuations, not measured causal treatment effects.
Maximize objective. Tie-break by lower credits used, then lower power used,
then lexicographically smaller tier vector in target_order.

Residual risk = sum risk_weight * usable errors across ALL targets minus
objective, including ineligible/frozen targets. Report blocked targets and
reasons separately. A constraint may intentionally leave high risk unserved.

## 5. Bound the decision, including shared observations

For each target, its error-total interval is the sum of the reconstructed
usable-window error intervals. Summing these intervals is intentionally
conservative even when neighboring windows share a counter endpoint; tighter
symbolic cancellation inside traffic totals is NOT required.

When comparing the winner with each feasible rival, shared TARGET allocations
must cancel. For each target compute risk_weight *
(winner_reduction - rival_reduction). Multiply positive coefficients by the
target's low total, negative coefficients by its high total, then sum.
`robust_margin` is the smallest difference. `robust` is true iff this is
positive AND all target latency classifications are stable. With only one
feasible vector, margin is null and robust equals all classifications stable.

Output the nominal winner even when robust is false. Also calculate the best
plan for credit budgets `max(0,budget-2)` and `budget+2`, holding all other
settings fixed. These scenarios expose binding constraints; do not simply add
or remove a block from the nominal plan.

## Reusable scope and malformed inputs

Support the fixed eight target IDs and four regions, 1..4 ordered windows
with referenced boundary IDs, positive durations, missing readings, per-metric
resets, maintenance, revised supersession edges, and changed planning numbers.
Budgets are integer 0..30 credits and 0..20 power; max active regions 0..4;
regional block caps 0..4. Each target has three finite nonnegative cost/power/
reduction entries starting at zero and nondecreasing, reduction <=1.
Weights are positive. Minimum sample size is >=1; slow trigger is in (0,1).
All counterfactuals obey these rules and have no ambiguous source coverage.

Your program must reject duplicate/missing reading coordinates, invalid page
IDs or units, nonfinite/negative values, reversed intervals, malformed bin
lists, supersession cycles and inconsistent counters, with diagnostics and
nonzero exit. Do not silently discard inputs. Do not hardcode chart values,
selected page IDs, window positions, winner tiers, or claim-specific totals in
the reusable program.
