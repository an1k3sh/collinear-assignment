# Capacity rollout decision memo

All numbers are produced by `analyze.py` (`analysis.json`) from `readings.json`.
The arithmetic is exact rational, and only standard-library Python is used.

## 1. Source authority and correction

Nine pages were inventoried. The selected sources are C1.r1, C2.r2, C3.r1, C4.r1 and H1.r1–H4.r1.
C2.r1 is rejected as superseded:

- `export-manifest.json` and `corrections.md` state that C2.r2 replaces the whole C2.r1 page.
- The old Birch error series included retry-attempt accounting.
- The repeated request counters are context, not extra traffic.

C2.r1 is still transcribed so that the rejection is auditable, but it is never added to anything. Birch values come only from C2.r2:

| Target | Requests | Errors |
|---|---|---|
| BS | 840,000 | 20,000 |
| BI | 960,000 | 16,000 |

## 2. Counter reconstruction, missing and excluded data

Interval volumes are differences between end and start samples. Resets in `operations.json` happen immediately after the start sample, so the window's volume is the end sample minus the baseline. A reset never produces negative traffic.

- **AS W3 (C1.r1):** reset of requests and errors. W3 = 100,000 requests and 3,000 errors. Usable.
- **BI W2 errors (C2.r2):** reset with baseline 0. Usable.
- **DS W2 (C4.r1):** the B2 sample is UNKNOWN, which is not a zero. W2 cannot be reconstructed, so it is excluded as `missing_traffic` and its H4.r1 histogram is not pooled.
- **DS W3 (C4.r1):** reconstructed from the zero-baseline reset: 220,000 requests and 4,000 errors. Usable.
- **DI W2 (C4.r1, H4.r1):** maintenance exclusion. Counters are still reconstructed for transparency (480,000 requests, 9,000 errors), but they are excluded from demand, errors and latency.

The other 26 target-windows are usable. Every decision, with its derivation, is persisted in `analysis.json.intervals`.

Fleet totals over usable windows: 7,240,000 requests and 92,700 errors (failure fraction 1.280%).

## 3. Pooled-latency reasoning (H1.r1–H4.r1)

Histogram rows are 100% stacked bars. Counts come from each segment's share multiplied by the row's N. Bins are pooled across usable windows, and slow = the last two bins divided by pooled samples. Percentiles are never averaged, and windows never vote.

| Target | Pooled slow fraction | Latency-eligible |
|---|---|---|
| AS | 17.5% | yes |
| BS | 25.3% | yes |
| BI | 25.9% | yes |
| CI | 26.8% | yes, but blocked by freeze |
| DS | 18.9% | yes |
| AI | 2.0% | no |
| CS | 2.4% | no |
| DI | 2.0% | no |

The CS result is the key one. W1–W3 each show 10% slow, but W4 has N = 10,000 with about 12 slow samples. Pooled, that is 312/13,000 = 2.4% (bounds 1.8%–3.2%), so CS is ineligible.

Every classification stays the same across all reading bounds.

## 4. Corrected rollout (static plan, budget 16 credits / 11 power)

**Plan: BS tier 1, BI tier 2, all others tier 0.**

- Credits: 14 of 16, including the Birch activation cost of 2.
- Power: 8 of 11.
- Active regions: Birch only (1 of 2).
- Objective (risk reduction): 26,320, with bounds 26,097.2–26,542.8.

**Bottleneck.** The Birch block cap of 3 is binding (BS + BI = 3).

- Using DS as well means activating Delta: +1 credit, plus at least 3 credits for a tier.
- The best such rival, BS1/BI1/DS1, scores only 25,100.
- Credits are not the only limit. For example, AS1 + BS1 + DS1 costs 14 credits but activates 3 regions when the maximum is 2.

**Blocked targets.**

| Target | Reason |
|---|---|
| AI | latency |
| CS | latency |
| DI | latency |
| CI | region_freeze (Cedar is frozen; 24,000 errors, weighted risk 36,000) |

**Unserved risk.** Total weighted risk is 116,850. After the plan, residual risk is 90,530. The largest unserved pieces are:

- CI: 36,000, blocked by the freeze.
- AS: 10,000, and DS: 11,000. Both are eligible but lose the optimization.

## 5. Budget scenarios

| Budget | Plan | Credits | Power | Active regions | Objective |
|---|---|---|---|---|---|
| 14 | BS1 / BI2 | 14 | 8 | Birch | 26,320 (same as nominal) |
| 18 | BS1 / BI2 / DS1 | 18 | 10 | Birch, Delta | 31,820 |

At 18 credits there is enough to pay the Delta activation cost. The Birch block cap still binds.

## 6. Does reading uncertainty change the decision?

No.

- The nominal plan's robust margin against every feasible rival (30 feasible tier vectors) is +1,111.2 under worst-case error-bound coefficients, so the plan is robust.
- All eligibility classifications are stable.
- Reading uncertainty does not change which targets are eligible, which tiers are chosen, or the budget-scenario choices.

## 7. Executable timed schedule (fixed, 6 slots)

The timed problem has crews, durations, warmups, blackouts, dependencies and region gaps (`execution-policy.md`). It was optimized independently: 309 feasible schedules were enumerated, and the result was checked against a separate brute-force simulator. The best timed schedule is **not** the static allocation.

**Schedule:**

| Target | Tier | Start | Finish | Ready |
|---|---|---|---|---|
| BS | 1 | 0 | 2 | 2 |
| DS | 1 | 0 | 1 | 1 |
| BI | 1 | 3 | 4 | 5 |

- Final tiers: BS1, BI1, DS1.
- Credits 14, power 8, active regions Birch and Delta, peak crews 2.

**Forecast-case net reduction:**

| Case | Net | Bounds | Baseline |
|---|---|---|---|
| weekday | 157,170 | 155,845.2–158,494.8 | 1,307,100 |
| write-burst | 121,050 | 120,009–122,091 | 1,520,800 |
| regional-shift | 171,690 | — | 1,333,850 |

Worst case is 121,050 (write-burst); the total is 449,910. Per-slot state is in `analysis.json.execution`.

## 8. Contingent policy (reveal after slot 1)

Common prefix: DS tier 1 at slot 0. Pending jobs, sunk resources and prerequisites carry across the reveal.

| Branch | Actions after reveal | Net |
|---|---|---|
| weekday | BS1 at 1, DS2 at 2 | 144,260 |
| write-burst | BI1 at 1, BS1 at 3 | 171,650 |
| regional-shift | AS1 at 1, DS2 at 2 | 160,695 |

- Guaranteed (worst-case) value: 144,260, compared with 121,050 for the fixed schedule.
- Value of the forecast signal: **+23,210**.
- Total across cases: 476,605.

## 9. Staged information (coarse signal at slot 1, exact at slot 3, weight 0.1)

Cases are grouped by the coarse signal: weekday and write-burst share a label ("shared"); regional-shift is separate ("shift").

- Commitments before slot 1 must be common to all cases.
- Commitments before slot 3 must be common within each coarse group.

The global objective is worst-case net + 0.1 × total net.

**Result.** The optimum is BS1 and DS1 at slot 0, with every branch then following the fixed schedule.

- Policy value: 166,041, equal to the fixed schedule's value (121,050 + 0.1 × 449,910).
- Worst case: 121,050.

**Why the staged signal adds nothing here.** The coarse signal arrives after slot 1. Committing BS and DS together at slot 0 is what protects the write-burst worst case, and the exact signal at slot 3 arrives too late to change anything that matters. The contingent policy's gain depends on delaying BS until the reveal, which this objective does not reward.

## 10. Claim audit

`audit.json` gives verdicts on the eight draft claims:

| Claim | Verdict | Reason |
|---|---|---|
| R1 | incorrect | Pages are replaced, not added. |
| R2 | incorrect | Reset, not negative demand. |
| R3 | incorrect | Only DS W2 is lost. |
| R4 | incorrect | Pooled CS slow fraction is 2.4%. |
| R5 | incorrect | Cedar freeze. |
| R6 | correct | DI W2 maintenance exclusion. |
| R7 | incorrect | Several independent constraints. |
| R8 | unsupported | Observational data; the deployment coincides with resets. |
