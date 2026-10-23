# Repair report — releases 1–2 (`inner`, `outer`)

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
* Releases 3–4 can add per-mode contribution functions (`_contribs`) and
  more affected-key sources (rates → accounts via `tags_segment`, links →
  components). Until then, unsupported modes raise `NotImplementedError` so
  the host rolls back the upgrade instead of reporting wrong numbers.

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

The release-1 tests moved to `checks/test_projection.py` and now run with
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

`state/demo.sqlite` was upgraded in place by `python demo.py --through 2`. Its
modes are `["inner","outer"]`. It holds receipts `r1/import`, `r1/correct`,
`r2/late-classification` and `r2/withdraw-classification`, and its `rollup`
equals both reference queries.

## Known limitations

* Only `inner` and `outer` are implemented. Releases 3–4 must add `rated` and
  `household`, including rate fanout and incremental link components.
* A single account with very many orders or tags costs work proportional to
  that account's rows (no bound required for high fanout).
