# Operations policy and report semantics

## Report

All panels describe the same eight half-open UTC windows on 2026-09-14.
W1 is [08:00,08:30), W2 [08:30,09:00), through W8 [11:30,12:00).
The x-axis/window IDs identify intervals, not instantaneous samples. All
regions use the same clock. The authoritative ordered window list and
duration in minutes are in `policy.json`.

* P1: mean request arrival rate, requests/minute. Each region has its own
  clearly labelled vertical scale; a taller bar in another panel need not
  mean more traffic. A missing bar marked UNKNOWN is not zero.
* P2: failed requests as a percentage of all requests in that interval.
* P3: p95 request latency in milliseconds. The numerical cell labels are
  authoritative; color is only an aid.
* P4: operational status by region/window, plus one deployment marker.

Status is `normal`, `maintenance`, or `unknown`. Unknown means telemetry is
unavailable for all three metrics. Maintenance metrics are still plotted and
must be transcribed, but excluded from the workload and latency calculation.
Only normal windows count. This exclusion is per region, not fleet-wide.

## Chart readings and uncertainty

Read every available observation as an interval `[low, estimate, high]`.
Use these maximum interval widths:

| Quantity | Maximum high - low | Legal domain |
|---|---:|---|
| Requests/minute | 100 | >=0 |
| Failure percent | 0.5 percentage points | 0..100 |
| Latency milliseconds | 10 | >=0 |

Intervals must contain the plotted value and the estimate; exact readings may
have zero width. For example `[950,1000,1050]` represents a request-rate reading
near 1000. Use the grid and image zoom rather than inventing excess precision.
Labels in P3 support exact values. Unknown metrics must be JSON null, not
`[0,0,0]`. These are visual-reading intervals, not statistical confidence
intervals. No tolerance tighter than the stated chart resolution is intended.

## Calculate demand

For each normal region/window:

```
requests = rate_estimate * minutes
failed_requests = requests * failure_percent_estimate / 100
```

For each region, sum requests and failed_requests, then compute
`100 * failed_requests / requests`. The fleet rate is likewise a ratio of
fleet totals, not a mean of regional or interval percentages.

For failed-request bounds, use the monotone product on each normal window:

```
low = minutes * rate_low * failure_percent_low / 100
high = minutes * rate_high * failure_percent_high / 100
```

Sum bounds by region. Assume no correlations between reading errors; do not
cancel errors across different observations.

## Eligibility and allocation

A region is eligible if it has at least two normal windows and the p95
estimates in its last two normal windows BOTH strictly exceed the latency
trigger. Choose those windows by the policy's chronological order, not file
order. Record the selected window IDs even when the region is not eligible.
With fewer than two, record the available IDs and mark ineligible. Never pool
or average p95 values across windows.

All allowed reading intervals in this supplied report place these last-window
latencies unambiguously on one side of the trigger. The report therefore
supports a definite eligibility decision.

Use integer allocations from zero to `max_blocks_per_region`, constrained by
the total budget. Ineligible regions must receive zero. The benefit for a
region with k blocks is its total failed requests times `benefit_fraction[k]`.
Those fractions are prescribed planning weights, not a causal claim about
actual improvement. Maximize the sum of benefits. It is permissible not to
spend all blocks if no additional benefit is available.

Tie-breaking: choose the allocation with fewer total blocks, then the
lexicographically smallest count vector in the region order in policy.json.

## Robustness certificate

Choose the nominal winner using estimates. For each different feasible
allocation, subtract its benefit coefficients from the winner's coefficients.
For each region, multiply a positive difference by that region's failed-count
LOW bound, or a negative difference by its HIGH bound. Sum these terms.
The smallest resulting difference over all competitors is
`robust_margin`. Shared allocations cancel; do not independently bound two
whole objectives and lose that cancellation.

Set `robust` true iff `robust_margin > 0`. With only one feasible allocation,
use `robust_margin: null` and `robust: true`. The supplied chart has a strictly
robust winner even at the permitted reading uncertainty. Other inputs may
legitimately have `robust: false`; do not force a certificate.

## Reusable analysis scope

The analysis program must accept the same schema with reordered observation
records, changed finite nonnegative readings, and different statuses. Policy
may have 1..8 ordered windows (positive durations), a budget from 0..6, a latency
trigger from 250..450, and max blocks 1 or 2. Fractions start at zero, are
nonnegative and strictly increase. Regions remain the same four.
All inputs used for counterfactual grading obey the schema. Handle zero demand:
return a null rate when its denominator is zero. Reject malformed inputs with
a diagnostic and nonzero exit; do not silently drop records.
