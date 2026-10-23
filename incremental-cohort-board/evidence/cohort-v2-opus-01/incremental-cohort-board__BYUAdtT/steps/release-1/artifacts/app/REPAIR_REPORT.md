# Repair report — release 1 (`inner`)

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
* Releases 2–4 can add per-mode contribution functions (`_contribs`) and
  more affected-key sources (rates → accounts via `tags_segment`, links →
  components). Until then, unsupported modes raise `NotImplementedError` so
  the host rolls back the upgrade instead of reporting wrong numbers.

## Validation (commands actually run)

```
python -m unittest discover -s checks -v      # 10 tests, all OK
python demo.py --through 1                    # run twice; identical output
python3 -c "...compare rollup to reference inner SQL on state/demo.sqlite..."  # True
```

`checks/test_inner_projection.py` covers these cases:

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

The original implementation fails 7 of these 10 tests, including the smoke check.

`state/demo.sqlite` is produced by `python demo.py --through 1`. It holds the
original sources and receipts `r1/import` and `r1/correct`, and its `rollup`
equals the reference query.

## Known limitations

* Only `inner` is implemented. Releases 2–4 must add `outer`, `rated` and
  `household`, including rate fanout and incremental link components.
* A single account with very many orders or tags costs work proportional to
  that account's rows (no bound required for high fanout).
