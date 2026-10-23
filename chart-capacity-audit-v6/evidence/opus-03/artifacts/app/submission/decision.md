# Decision memorandum: capacity rollout for the multi-region API platform

Prepared from the nine raster pages in `report/`, plus `registry.csv`,
`export-manifest.json`, `corrections.md`, `operations.json`, `planning.json`
and `policy.md`. All numbers below come from `analysis.json`, produced by
`analyze.py` (standard library only) from `readings.json`. Rerun with the command
in `interfaces.md`.

## 1. Recommendation

**Static sizing (nominal budget of 16 credits):** Birch / Query API (BS) goes to
tier 1 and Birch / Write API (BI) to tier 2. Every other target stays at tier 0.

| item | value |
|---|---|
| credits used | 14 of 16 (BS 4 + BI 8 + Birch activation 2) |
| power used | 8 of 11 |
| active regions | Birch (1 of max 2); Birch blocks 3 of 3 |
| objective (weighted errors mitigated) | 26,320 (reading bounds 26,119.48 to 26,520.52) |
| total weighted risk | 116,850 |
| residual (unserved) risk | 90,530 |
| robust margin vs best rival | +1,122.08 (rival BS1 + BI1 + DS1, nominal 25,100) |
| robust | **yes**: margin > 0 and every latency classification is stable |

**Executable change window (separately optimized, six slots):** In the
fixed schedule, BS tier 1 runs in slots 0-1, Delta / Query API (DS) tier 1 in
slot 0, and BI tier 1 in slot 3 (ready at slot 5). Final tiers are BS 1, BI 1
and DS 1 (14 credits, 8 power, Birch and Delta active, peak crews 2). The final tiers
differ from the static sizing (see section 7).

## 2. Source authority (inventory)

* Selected pages: C1.r1, C2.r2, C3.r1, C4.r1, H1.r1, H2.r1, H3.r1 and H4.r1.
  **Rejected page: C2.r1.**
* `export-manifest.json` records that C2.r2 supersedes C2.r1 for the whole
  page. `corrections.md` explains that the r1 Birch error series included
  retry-attempt accounting. Its request counters are identical context
  (BS 640k to 1,480k and BI 710k to 1,670k on both pages), not extra traffic. The
  revisions are never added together. C1.r1 is not obsolete just because C2 has an r2,
  because revisions are numbered per logical page.
* All nine pages are transcribed in `readings.json`, including C2.r1, so that the
  pipeline resolves authority explicitly. Each target has exactly one selected
  counter page and one selected histogram page (`inventory.by_target`).

## 3. Readings and their uncertainty

* **Counters:** I used the printed marker labels, multiplied by 1,000. I checked
  every label against the pixel position of its marker with a linear fit, and every
  residual was within about 2.5k requests and 0.06k errors. The reading intervals
  are ±900 requests (width 1,800, below the permitted 2,000) and ±18 errors
  (width 36, below the permitted 40).
* **Delta Query API (DS) at B2:** C4.r1 marks both requests and errors as UNKNOWN,
  so the readings are `null`. No value was interpolated.
* **Histograms:** I measured the segment boundaries in pixels against the 0-100% axis
  and multiplied each share by the row's printed N. All shares fall on clean
  fractions (for example BS W3 at N=1,500 is 700/400/300/100). The intervals are
  ±9 samples. The tiny tail segments for AI and DI (1.5% and 0.5% of 2,000)
  include zero where appropriate.
* **Cedar Query API (CS) W4 (H3.r1, N=10,000):** the boundary is at about 99.88%.
  The readings are 7,000 / 2,990 / 10 / 0, with intervals [0,40] for the
  (300,1000] bin and [0,30] for the >1000 bin, within the 50-sample allowance.

## 4. Interval reconstruction and exclusions

The pipeline persists all 32 target/window decisions, with their reasons and notes,
in `analysis.json.intervals`.

* **Counter resets are not negative traffic:**
  * **AS W3 (C1.r1):** requests fall from 800k to 100k and errors from 23k to 3k.
    `operations.json` documents zero-baseline resets of both metrics at the start
    of W3, so W3 = 100,000 requests and 3,000 errors. The old-epoch B2 sample is
    ignored. Clamping to zero (claim R2) is wrong.
  * **BI W2 (C2.r2):** only the error metric has a documented reset, so W2 errors =
    4,500 (end sample minus baseline 0). BI requests use the normal difference.
* **Missing traffic is not zero:**
  * **DS W2:** traffic is `missing_traffic` because the B2 endpoints are UNKNOWN.
    The DS W2 histogram (60% slow) therefore is **not** joined, because a histogram
    cannot replace missing traffic.
  * **DS W3:** recoverable through the documented reset (220,000 requests and
    4,000 errors), so claim R3 is wrong.
* **Maintenance:** DI W2 is listed as maintenance. Its counters are still
  reconstructed and persisted (480,000 requests, 9,000 errors), but they are
  excluded from demand, and its 80%-slow histogram is excluded from latency
  (claim R6 is correct).
* **Rates:** mean requests per minute is count / minutes. For example, AS W2 =
  200,000 / 60 = 3,333.3 per minute. The cumulative deltas are not multiplied by
  window duration.
* **Fleet totals (usable windows):** 7,240,000 requests and 92,700 errors, a
  failure fraction of 0.012804.

## 5. Pooled latency and eligibility

Bin counts are added across joined windows. Percentiles and per-window
percentages are never averaged. The trigger is slow fraction > 0.05 with at least
1,000 samples.

| target | samples | pooled slow (bounds) | p95 bin | latency | rollout |
|---|---|---|---|---|---|
| AS | 4,000 | 0.175 (0.157–0.193) | (300,1000] | eligible | eligible |
| AI | 8,000 | 0.020 (0.011–0.029) | (100,300] | ineligible | blocked: latency |
| BS | 7,500 | 0.253 (0.244–0.263) | >1000 | eligible | eligible |
| BI | 8,500 | 0.259 (0.250–0.267) | >1000 | eligible | eligible |
| CS | 13,000 | 0.024 (0.019–0.033) | (100,300] | ineligible | blocked: latency |
| CI | 5,600 | 0.268 (0.255–0.281) | >1000 | eligible | blocked: region_freeze |
| DS | 4,500 (W1, W3, W4) | 0.189 (0.177–0.201) | >1000 | eligible | eligible |
| DI | 6,000 (W1, W3, W4) | 0.020 (0.011–0.029) | (100,300] | ineligible | blocked: latency |

Notes on the table:

* **CS:** three of its four windows are individually 10% slow, but the
  N=10,000 W4 row dominates the pooled count. Its pooled slow fraction is about
  0.024, so CS is ineligible (claim R4 is wrong).
* **Stability:** every classification is stable over the full reading envelopes.
* **AS p95:** the label sits exactly on the 95% cumulative boundary
  (3,800 of 4,000). This label is informational and does not drive any decision.

## 6. Constrained plan, bottlenecks and unserved risk

Weighted risk is usable errors × risk_weight:

| target | AS | AI | BS | BI | CS | CI | DS | DI |
|---|---|---|---|---|---|---|---|---|
| weighted risk | 10,000 | 4,200 | 20,000 | 24,000 | 3,400 | 36,000 | 11,000 | 8,250 |

* **Admissible targets:** only AS, BS, BI and DS.
* **Cedar Write API (CI):** this is the largest single risk (36,000), but Cedar is
  frozen, so its risk is reported as unserved (claim R5 is wrong).
* **Bottlenecks:**
  * **Credits:** the binding constraint is lumpy credits including activation
    charges. The 2 unused credits cannot buy any further tier, because DS or AS
    tier 1 needs 3 credits plus a 1-credit activation.
  * **Birch block cap (3):** prevents BS tier 2 together with BI tier 2.
  * **Active-region cap (2):** excludes mixes such as AS1 + BI1 + DS1, even
    though that mix fits within 14 credits.
  * Power (8 of 11) is not binding. Budget is not the only constraint (claim R7 is
    wrong).
* **Unserved risk by target (90,530 in total):**

  | target | CI | DS | AS | BS | DI | BI | AI | CS |
  |---|---|---|---|---|---|---|---|---|
  | unserved | 36,000 | 11,000 | 10,000 | 10,000 | 8,250 | 7,680 | 4,200 | 3,400 |

* **Budget scenarios** (each re-optimized from scratch, not edited from the nominal plan):

  | credit budget | plan | objective | credits | power |
  |---|---|---|---|---|
  | 14 | BS1 + BI2 (same plan) | 26,320 | 14 | 8 |
  | 18 | BS1 + BI2 + DS1 (Birch and Delta) | 31,820 | 18 | 10 |

  * **14 credits:** the plan is unchanged.
  * **18 credits:** the extra 2 credits unlock Delta's activation plus DS tier 1.
* **Reading uncertainty does not change the decision.** The worst-case margin over
  every feasible rival is +1,122.08, computed with shared target allocations
  cancelling and error totals at their adverse bounds. All eligibility
  classifications are stable.

These benefit numbers are supplied planning valuations, not measured causal
effects. The B2 collector deployment coincides with resets and missing telemetry.
It does not establish any causal performance effect (claim R8 is unsupported).

## 7. Executable schedule (`analysis.json.execution`)

The schedule is optimized independently from tier 0 over six slots. It covers
all 309 feasible schedules for the eligible candidates AS, BS, BI and DS. The
constraints are:

* crews [2,1,2,2,1,2] per slot;
* blackouts: AS slot 3, BI slot 0, DS slot 4;
* a Birch one-slot region gap;
* dependencies: BS tier 2 needs BI tier 1, and BI tier 2 needs DS tier 1;
* at most 4 jobs;
* the static caps on the final tiers.

**Fixed schedule (max-min over cases):**

| job | slots | ready at |
|---|---|---|
| BS → 1 | 0–1 | slot 2 |
| DS → 1 | 0 | slot 1 |
| BI → 1 | 3 | slot 5 (after warmup) |

Effective tiers are 0 while a target is occupied and during warmup. The
start vector is [7,7,7,7,0,7,3,7,7,7,7,7,0,7,7,7].

| case | baseline | net (bounds) | residual |
|---|---|---|---|
| weekday | 1,307,100 | 157,170 (155,977.68 – 158,362.32) | 1,149,930 |
| write-burst | 1,520,800 | **121,050** (120,113.10 – 121,986.90) | 1,399,750 |
| regional-shift | 1,333,850 | 171,690 (170,352.96 – 173,027.04) | 1,162,160 |

* **Worst case and total:** the worst-case net is 121,050 (write-burst) and the
  total across the three cases is 449,910.
* **Why the final tiers differ from the static BS1 + BI2 sizing:**
  * BI tier 2 requires DS tier 1 to be ready first.
  * BI tier 2 occupies two slots, during which BI earns zero reduction.
  * Every occupied slot charges a 15% disruption debit.
  * Within six slots, a BS1 / DS1 / BI1 path protects more risk in the worst case
    than BS1 + BI2.
* **Bounds:** the net bounds are reading bounds on this chosen schedule's
  shared-observation coefficients. They are not a robustness certificate.

## 8. Information experiments

**Full reveal at slot 1 (`contingency`):**

* **Commitment:** DS → 1 in slot 0 (ready at slot 1). Each branch then adapts:

  | case | continuation | net |
  |---|---|---|
  | weekday | BS → 1 at slot 1, DS → 2 at slot 2 | 144,260 |
  | write-burst | BI → 1 at slot 1, BS → 1 at slot 3 | 171,650 |
  | regional-shift | AS → 1 at slot 1, DS → 2 at slot 2 | 160,695 |

* **Guaranteed value:** the worst-case net rises to 144,260, against 121,050 for the
  fixed schedule. The **information value is +23,210**.
* **Totals:** total net 476,605 over the three branches; branch credits 38 and power
  21, summed across alternative worlds (only one branch happens). The prefix is
  deliberately different from the fixed schedule's first slot (BS1 is not started
  in slot 0). The DS prefix job is sunk and carries into every branch.

**Staged signal: coarse at slot 1, exact at slot 3 (`staged`):**

* **Signal groups:** weekday and write-burst share the label `shared`;
  regional-shift is `shift`.
* **Global objective:** min net + 0.1 × sum of nets. The optimum commits BS → 1 and
  DS → 1 in slot 0. Both groups keep the identical continuation, BI → 1 at slot 3,
  so every branch equals the fixed schedule.
* **Value:** policy value 166,041 (121,050 + 0.1 × 449,910); worst-case net 121,050.
* **Why the coarse signal adds nothing:** the full-reveal gain depends on weekday and
  write-burst diverging at slot 1 (BS1 versus BI1). They are indistinguishable until
  slot 3, so the exact signal arrives too late to matter under these crews and
  blackouts.
* **Verification:** an independent exhaustive search over all branch combinations
  confirmed the fixed, contingent and staged optima.

## 9. Caveats

* The window counts are visual readings within the stated tolerances.
* Exposures, reductions and link factors are supplied forecast valuations.
* The DS W2 and DI W2 data are excluded, not imputed.
