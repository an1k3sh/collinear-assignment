# Capacity rollout decision memo

Reproduce with:

```
python /app/submission/analyze.py --readings /app/submission/readings.json \
  --manifest /app/export-manifest.json --operations /app/operations.json \
  --planning /app/planning.json --registry /app/registry.csv \
  --out /app/submission/analysis.json
```

All numbers below come from `analysis.json`. The pipeline uses only the
standard library (`analyze.py`, `execution.py`, `common.py`). It does exact
rational arithmetic for the optimizations and rejects malformed inputs with a
diagnostic and exit code 2.

## 1. Sources and the corrected export

* **Selected (authoritative):** C1.r1, C2.r2, C3.r1, C4.r1, H1.r1, H2.r1,
  H3.r1, H4.r1. Each of the eight targets has exactly one counter page and
  one histogram page.
* **Rejected:** C2.r1. `export-manifest.json` says C2.r2 supersedes it as a
  whole page. `corrections.md` says the r1 Birch error series included
  retry-attempt accounting.
  * The request counters on both pages are identical context, so the pages
    are not additive.
  * Using C2.r2, Birch Query (BS) has 20,000 usable errors instead of
    28,000, and Birch Write (BI) has 16,000 instead of 26,000.
* All nine pages, including C2.r1, are transcribed in `readings.json`, so the
  pipeline resolves authority itself.
* Counter values are the printed marker labels, multiplied by 1,000.
  Intervals are ±800 requests and ±15 errors.
* Histogram bins are measured segment widths (pixel run lengths with
  Pillow) times the printed N. Intervals are ±9 samples (±24 for N = 10,000).
* Cedar Query (CS) W4 has segments above 300 ms that are only about 1–2 px
  wide. Their intervals include zero.

## 2. Interval reconstruction, exclusions and missing data

`analysis.json.intervals` lists all 32 target/window decisions. Each one
records its method, any reset, and its page, boundary and window citations.

* **AS W3 (Alder Query, C1.r1):** the counters fall from 800k to 100k
  requests and from 23k to 3k errors.
  * This is a documented reset at the start of W3 with baseline 0, so W3 has
    100,000 requests and 3,000 errors.
  * It is not negative traffic and is not clamped.
* **BI W2 errors (Birch Write, C2.r2):** documented errors-only reset, so W2
  has 4,500 errors. Requests are differenced normally.
* **DS (Delta Query, C4.r1):** the B2 sample is UNKNOWN, not zero.
  * W2 is `missing_traffic`.
  * W3 is reconstructed from the documented zero baseline: 220,000 requests
    and 4,000 errors.
  * W1 and W4 are usable.
  * The DS W2 histogram exists but is not joined, because a histogram cannot
    replace missing traffic.
* **DI W2 (Delta Write):** maintenance.
  * Its counters are still reconstructed and persisted (480,000 requests,
    9,000 errors).
  * It is excluded from demand, errors and latency. Its H4.r1 row (80% slow)
    is not pooled.
* No undocumented counter drop exists in the authoritative pages.
* Fleet usable totals: 7,240,000 requests, 92,700 errors, failure fraction
  1.28%.

## 3. Pooled latency (bin counts, not averaged percentiles)

| Target | Usable errors | Pooled samples | Slow fraction | p95 bin | Rollout |
|---|---|---|---|---|---|
| AS | 10,000 | 4,000 | 17.5% | (300,1000] | eligible |
| AI | 2,800 | 8,000 | 2.0% | (100,300] | blocked: latency |
| BS | 20,000 | 7,500 | 25.3% | >1000 | eligible |
| BI | 16,000 | 8,500 | 25.9% | >1000 | eligible |
| CS | 3,400 | 13,000 | 2.4% | (100,300] | blocked: latency |
| CI | 24,000 | 5,600 | 26.8% | >1000 | blocked: region_freeze |
| DS | 11,000 (W1,W3,W4) | 4,500 | 18.9% | >1000 | eligible |
| DI | 5,500 (W1,W3,W4) | 6,000 | 2.0% | (100,300] | blocked: latency |

* **CS:** three of its four windows show 10% slow, but its 10,000-sample W4
  row has only about 0.1% slow. Pooled, it falls below the 5% trigger.
* **DI:** pooling its maintenance window would wrongly push it to about 13%
  slow.
* All eight classifications are stable over the full interval envelopes. For
  example, the CS upper bound is 3.2% and the AS lower bound is 15.7%.

## 4. Static sizing allocation (nominal plan)

* **Winner:** BS tier 1 + BI tier 2. The only active region is Birch.
  * Credits used: 14 of 16.
  * Power used: 8 of 11.
* **Objective:** 26,320 (bounds 26,152.9–26,487.1).
* **Residual (unserved) weighted risk:** 90,530 of 116,850.
  * Largest unserved item: CI, 36,000. It is frozen even though it is
    latency-eligible.
  * DS (11,000) and AS (10,000) are eligible but lose in the optimization.
* **Bottleneck:** Birch's 3-block cap is exhausted. Adding Delta or Alder
  would cost at least 4 more credits including activation, which is more than
  the 2 left. Power is not binding.
* **Robustness:** the closest rival is BS1 + BI1 + DS1. The worst-case
  margin against every feasible rival is 1,138.4 > 0 (shared allocations
  cancel), and every classification is stable. **Reading uncertainty does not
  change the decision.**
* **Credit scenarios:**
  * **Budget 14:** the same plan (BS1, BI2), 14 credits, objective 26,320.
  * **Budget 18:** BS1 + BI2 + DS1, using Birch and Delta. 18 credits,
    power 10, objective 31,820. The extra credits buy the Delta activation
    plus a DS tier-1 block.

## 5. Executable change window (independently optimized, fixed schedule)

Candidates AS, BS, BI and DS are all rollout-eligible. 309 complete schedules
are feasible.

**Selected schedule** (it maximizes the minimum whole-window net):

* **Slot 0:** BS tier 1 starts (finishes 2, ready 2) and DS tier 1 starts
  (finishes 1, ready 1).
* **Slot 3:** BI tier 1 starts (finishes 4, ready 5). Its dependency rules
  are satisfied.
* **Final tiers:** BS1, BI1, DS1. Credits 14, power 8, regions Birch and
  Delta, peak crews 2.
* This differs from the static allocation. BI tier 2 would need DS tier 1
  ready first and would take two crew-slots of outage. The timed max-min
  objective prefers early protection over the static end state.

| Case | Baseline | Net benefit | Net bounds | Residual |
|---|---|---|---|---|
| weekday | 1,307,100 | 157,170 | [156,176.4, 158,163.6] | 1,149,930 |
| write-burst | 1,520,800 | 121,050 | [120,269.25, 121,830.75] | 1,399,750 |
| regional-shift | 1,333,850 | 171,690 | [170,575.8, 172,804.2] | 1,162,160 |

* Worst-case net is 121,050 (write-burst); the sum is 449,910.
* Slot 0 carries a disruption debit of -4,650 in every case.
* Net bounds use the aggregate shared-observation coefficient of each
  target's error total. They are bounds for this chosen schedule, not a proof
  that it is robustly optimal.

## 6. Contingent policy (exact case revealed at slot 1)

* **Common prefix:** DS tier 1 at slot 0 (ready 1). This is not the fixed
  schedule's prefix: the fixed schedule also starts BS at slot 0.
* **Branches after the reveal:**
  * **weekday:** BS1 at slot 1, then DS2 at slot 2. Net 144,260, 13
    credits.
  * **write-burst:** BI1 at slot 1, then BS1 at slot 3. Net 171,650, 14
    credits.
  * **regional-shift:** AS1 at slot 1, then DS2 at slot 2. Net 160,695, 11
    credits, Alder and Delta active.
* **Guaranteed (worst) net:** 144,260, against 121,050 for the fixed
  schedule.
* **Information value:** +23,210. The sum across cases is 476,605.
* The DS commitment and its sunk resources carry into every branch, and every
  branch separately satisfies all budgets.

## 7. Staged information (coarse group at slot 1, exact case at slot 3)

* **Signal groups:** weekday and write-burst share the label `shared`;
  regional-shift is `shift`. The objective is min + 0.1 × sum.
* **Policy commitments:**
  * **Before slot 1 (all cases):** BS1 and DS1 at slot 0.
  * **Before slot 3, `shared` group:** the same BS1 and DS1 prefix, plus
    nothing new.
  * **After slot 3:** each branch then runs BI1 at slot 3.
* **Result:** the optimal staged policy is the fixed schedule in every
  branch.
  * Policy value 166,041, equal to the fixed schedule's value under the same
    score. Worst net 121,050, sum 449,910.
* **Why there is no gain:** weekday and write-burst must share every job that
  starts before slot 3. Their best continuations need different slot-1 jobs
  (BS versus BI), so the early divergence that helps in the full-reveal policy
  cannot be applied to the binding write-burst case. An exhaustive
  brute-force cross-check confirms this optimum.

## 8. Claim audit summary

| Claim | Verdict | Reason |
|---|---|---|
| R1 | incorrect | Superseded page; not additive. |
| R2 | incorrect | Documented reset: W3 is 100k requests and 3k errors. |
| R3 | incorrect | Only DS W2 is missing; W3 is reconstructable. |
| R4 | incorrect | Pooled CS slow fraction is 2.4%. |
| R5 | incorrect | Cedar is frozen. |
| R6 | correct | DI W2 is maintenance. |
| R7 | incorrect | Region-count, block and power caps are separate rules. |
| R8 | unsupported | No causal identification. |

Details are in `audit.json`.
