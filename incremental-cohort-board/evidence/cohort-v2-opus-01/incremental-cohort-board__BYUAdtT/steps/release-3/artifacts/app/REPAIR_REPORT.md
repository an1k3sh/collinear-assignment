# Repair report — releases 1–3 (`inner`, `outer`, `rated`)

## Diagnosis

The original `maintainer.py` invalidated and re-queried whole days, keyed only
on `after["day"]` of **order** changes. That caused three stale-board failures
seen in `incidents/release-1.json` (`r1/correct`):

1. **Tag reclassification ignored** – tag changes never invalidated anything,
   so `t-a` retail→trade left the retail row overcounted and no trade row.
2. **Old day never invalidated** – moving `o-102` from `2026-10-01` to NULL
   recomputed only the NULL day; the old day kept its contribution.
3. **Deletes ignored** – `after is None` was skipped, so deleting `o-101`
   never refreshed its day.

It also violated the work bound: each recompute scanned a whole day
(80,000 unrelated accounts on one day ⇒ far above 300k VM instructions).

## Design

Joins are on `account`, so every report group is a sum of independent
per-account contributions. For `inner`, account *a* in group (d, s)
contributes `n_d·m_s` rows, `nn_d·m_s` amounts, `sum_d·m_s` cents, MIN/MAX of
its day-d cents and one distinct account (n_d = a's orders on day d, m_s = a's
tags with segment s — duplicate tag rows multiply).

* `aux_contrib(mode, day, segment, band, account, rows, nn, sm, mn, mx)` holds
  one row per (mode, group, account) with joined rows. It has indexes on
  `(account, mode)`, `(mode, group…, mn)` and `(mode, group…, mx)`.
* `maintain` collects the affected accounts (`before`/`after` accounts of
  order and tag changes), recomputes their contributions from the final
  sources through `orders_account`/`tags_account`, diffs those against the
  stored contributions, and applies net deltas to `rollup`. COUNT/SUM/
  account_count use additive deltas. MIN/MAX are re-read from the group's
  `mn`/`mx` index, which costs O(log group). Groups whose `row_count` drops
  to 0 are deleted. SUM is NULL when `amount_count = 0`.
* Group keys use `IS` comparisons (index-usable) so NULL day/segment/band work.
  Python holds arithmetic exactly. Per-account partial sums that exceed int64
  are stored as decimal TEXT in the untyped `sm` column.
* `bootstrap` rebuilds `rollup` and `aux_contrib` from all sources. It records
  `aux_meta('state')` = {version, modes}. If `maintain` ever sees missing or
  mismatched aux state (for example, a database built by the old code), it
  migrates once through `bootstrap`. That path never runs on a repaired database.
* All state lives in the same DB inside the host transaction. The code does
  not commit, use `executescript`, add triggers, or use globals. Rollback,
  retry and reopen are therefore safe.
* Each mode is a per-account multiplier rule (`_multipliers`) over
  {(segment, band): joined rows per order}. An account's sources are loaded
  once per batch and shared by all modes. Modes not yet implemented
  (`household`) raise `NotImplementedError`, so the host rolls back the
  upgrade instead of reporting wrong numbers.

## Release 2: `outer`

`outer` is the documented `LEFT JOIN tags` query. No application-specific
NULL default is involved. Its per-account rule matches `inner` except for an
account with **no tag rows**: each of its orders appears once with
`t.segment` NULL. It therefore lands in the same `(day, NULL)` group as
accounts whose tags have a NULL segment, because SQL GROUP BY merges NULLs.
`COUNT(DISTINCT account)` stays correct because one account is in exactly one
of those two cases. An account that gains or loses its last tag is already an
affected account (tag change `before`/`after`), so classifying an account and
withdrawing its classification are both incremental.

The upgrade path works as follows. `Store.upgrade(("inner","outer"))` calls
`bootstrap`, which rebuilds `rollup` and `aux_contrib` for both modes and
records them in `aux_meta`. The aux schema is unchanged, so `AUX_VERSION`
stays `1`. `inner` rows are recomputed identically, and a test asserts this.

## Release 3: `rated`

`rated` is `orders LEFT JOIN tags LEFT JOIN rates ON t.segment=r.segment`.
Rate rows are versioned source rows, not a lookup. For an account with
`m_s` tag rows of segment *s* and `k_{s,b}` rate rows of (segment *s*,
band *b*), each order on day *d* yields `m_s·k_{s,b}` joined rows in
(d, s, b). The NULL rules follow SQL directly:

* An untagged account contributes (d, NULL, NULL) once per order.
* A NULL tag segment never matches a rate, because `=` is not NULL-safe. Its
  rows stay in band NULL. Rate rows whose segment is NULL never join anything.
* A segment with no rate rows keeps its rows with band NULL. They share that
  group with rate rows whose band is NULL, since GROUP BY merges NULLs. Each
  account still counts once there.

**Rate changes.** A rate change with a non-NULL `before` or `after` segment
*s* affects exactly the accounts that have orders and a tag of segment *s*.
For accounts not otherwise touched in the batch, their stored contributions
are current. Such an account has `aux_contrib` rows with `segment = s` exactly
in that case. The new index `aux_contrib_segment(segment, account)` therefore
finds the real fan-out without scanning tag-only accounts. Accounts reached
only through rates are recomputed for rate-dependent modes only, since
`inner`/`outer` cannot change. Accounts with order/tag changes are recomputed
against the final rate rows. This makes rate imports combined with
classification corrections, tag rekeys and order moves in one transaction
correct, independent of change-list order.

**Upgrade.** Adding `rated` calls `bootstrap`, which creates the new index and
rebuilds all modes. The index is only consulted when a rate mode is active,
and adding a mode always bootstraps, so `AUX_VERSION` stays `1`. A database
already at `["inner","outer"]` therefore keeps working without a rebuild.

## Validation (commands actually run)

Release 1:

```
python -m unittest discover -s checks -v      # 10 tests, all OK
python demo.py --through 1                    # run twice; identical output
python3 -c "...compare rollup to reference inner SQL on state/demo.sqlite..."  # True
```

Release 2:

```
python -m unittest discover -s checks -v      # 14 tests, all OK
python demo.py --through 2                    # upgrade + replay; run twice, identical output
python3 - <<EOF ... EOF   # rollup == inner+outer reference SQL: True;
                          # all release-1 receipts still present
```

Release 3:

```
python -m unittest discover -s checks -v      # 18 tests, all OK
python demo.py --through 3                    # upgrade + replay; run twice, identical output
python3 - <<EOF ... EOF   # rollup == inner+outer+rated reference SQL: True;
                          # all release-1/2 receipts still present; integrity_check ok
# ad-hoc worst case: one account, 8 orders on distinct days, 4 segments,
# 4 distinct bands, all contributions rewritten => 33,525 VM instructions
```

Release 3 adds these tests. All previous tests now also run with `rated` active.

* `RatedSemantics` covers several cases:
  * Duplicate rate rows multiply.
  * NULL band, NULL tag segment and NULL rate segment.
  * An untagged account in (d, NULL, NULL).
  * A rate import combined with a tag rekey and an order move in one batch.
  * Deleting the last rates for a segment.
  * A rate change reaching an untouched account after reopen, while a
    tag-only account is ignored.
  * Moving rates to another segment or to NULL.
* `IncidentReplay`: replays `incidents/release-1..3.json` in a fresh database
  and upgrades modes exactly as `demo.py` does. Before each batch it injects
  a pre-commit failure, then checks, reopens, applies, checks again, and
  confirms the retry is idempotent. Every active mode is compared with its
  reference SQL at each step.
* `Randomized` now runs 400 batches mixing orders, tags and rates, including
  `""`, `"NULL"` and NULL segments/bands, with random failure, retry and reopen.
* `WorkBound`: four versioned rates on the 80,000-account target segment.
  An account with private segments and four rates is seeded, then gets a
  small-fanout segment-rate correction, then a combined rate and
  classification correction, then cleanup. The measured counts were
  [9182, 7633, 4628, 5089, 4034, 1494, 1091, 12427, 4250, 7855, 5311, 47, 78]
  VM instructions per batch.

Release 2: and now run with
both modes active, checking each mode against its own reference SQL. Release 2
adds these tests:

* `OuterSemantics`: an untagged account and a NULL-segment tag share one
  group with 2 distinct accounts. Further cases classify an account, move its
  tag away (the account returns to the NULL segment), and add a tag for an
  account without orders.
* `Upgrade`: an inner-only DB is reopened and upgraded. Its inner rows are
  unchanged and outer matches the reference. Later batches stay correct, and
  removing a mode is refused.
* `InnerOnly`: previously released inner-only behavior (no outer rows, last
  tag deletion empties the board).
* The budget test now covers both modes and includes unclassify/reclassify
  batches. The measured counts were
  [5325, 4544, 3207, 2393, 2122, 778, 830, 47, 78] instructions per batch
  against the 300,000 cap.

Coverage from release 1:

* The incident shape, NULL and sentinel-like keys (`""`, `"null"`, `"NULL"`).
* Rekeys and repeated writes to the same ID in one batch.
* Duplicate tags, deletes of missing IDs and empty batches.
* An int64-overflowing partial sum.
* Injected failure, then reopen and retry.
* Bootstrap over existing sources.
* 250 randomized batches checked against the reference SQL, with random
  reopen and failure.
* A VM-instruction budget test on 80,000 accounts sharing day and segment
  (`set_progress_handler(…, 1)`). The measured counts were
  [3017, 2363, 2937, 390, 964, 47, 78] instructions per batch against the
  300,000 cap.

The original implementation fails 7 of the 10 release-1 tests, including the smoke check.

`state/demo.sqlite` was upgraded in place by `python demo.py --through 3`.
Its modes are `["inner","outer","rated"]`. It holds all seven receipts
(`r1/*`, `r2/*`, `r3/*`) with the original sources. Its `rollup` equals all
three reference queries.

## Known limitations

* `household` (release 4) is not implemented yet. It needs incremental link
  components. In that release the 300k bound covers up to eight accounts across
  four modes, so contribution work may need to be shared between `rated` and
  `household`.
* A rate change on a segment shared by many order-bearing accounts costs work
  proportional to that fan-out. The contract sets no bound for high fan-out.
* A single account with very many orders or tags costs work proportional to
  that account's rows (no bound required for high fanout).
