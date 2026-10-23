# Repair report — release 1 (`inner` report)

## Diagnosed failure mechanism

The original `maintainer.maintain` invalidated whole days, keyed only on the
**after** image of **order** changes:

1. **Tag reclassifications were ignored.** Changes to `tags` never produced a
   day to refresh, so after `t-a` moved `001` from `retail` to `trade` the board
   kept the old segment counts (stale `retail` row, missing `trade` row).
2. **The old day of moved/deleted orders was never refreshed.** `o-102` moving
   from `2026-10-01` to NULL refreshed only the NULL day, and the deleted
   `o-101` (`after = null`) refreshed nothing, so `2026-10-01/retail` still
   counted both orders.
3. **Cost.** Each refresh re-ran the reference join for the whole day. On the
   contract's 80,000-account fixture one order write cost about **3.2 million**
   progress-handler callbacks, compared with the 300,000 VM-instruction limit.

## Design

The persistent state lives in the same database. The host still owns all
transactions.

- `aux_cell(mode, account, day, segment, band, n, c, s, mn, mx)` stores one row
  per (mode, account, output group) where the account adds at least one joined
  row. For `inner`, an account's order statistics for each day (`COUNT(*)`,
  `COUNT(cents)`, `SUM`, `MIN`, `MAX`) are crossed with its tag multiplicity for
  each segment (`m` = the number of tag rows; duplicate values count
  separately):
  `n = rows*m`, `c = amounts*m`, `s = sum*m` (0 when there are no amounts), and
  `mn`/`mx` are unchanged. Each account has at most one cell per group, so
  `account_count` is the number of cells. This makes `COUNT(DISTINCT account)`
  exact without a global distinct recount.
- Indexes: `aux_cell_account(mode, account)` for per-account replacement, and
  `aux_cell_min/max(mode, day, segment, band, mn|mx)` for a single seek per
  group to find the group's MIN or MAX after a retraction.
- `maintain`: gathers the accounts in the before and after images of every
  `orders`/`tags` change. Rates do not affect `inner`. For each account it
  recomputes the cells from sources using `orders_account` and `tags_account`,
  then compares them with the stored cells and writes only the cells that
  changed. It adds up the exact per-group deltas in Python (arbitrary
  precision). For each affected group it reads the `rollup` row through
  `rollup_key`, applies the delta, and re-reads MIN/MAX with an index seek. It
  deletes the row when the group becomes empty and inserts it when the group
  appears. `total_cents` is NULL exactly when `amount_count = 0`. NULL
  keys are matched with `IS`, so the plans still use the indexes (checked with
  `EXPLAIN QUERY PLAN`).
  Work is proportional to the touched accounts' rows and groups, not to day or
  group size. Empty and net-no-op batches do no hook work.
- `bootstrap`: creates the `aux_` objects with separate `execute` calls (no
  `executescript`), then rebuilds `aux_cell` and `rollup` for the requested
  modes from a full scan. It is never needed on reopen.
- Durability: there are no globals, files or triggers. Everything rolls back
  with the host transaction, so a retried batch recomputes from the same state.
- Source tables, receipts, settings and existing indexes are left unchanged.

Measured cost on an 80,000-account shared day/segment, with a reopen before each
batch. The numbers are progress-handler callbacks at N=1:

| batch | callbacks |
|---|---|
| 8 orders + 4 tags + 4 rates for a new small account | ~3,300 |
| reclassify/move same account | ~2,400 |
| delete it | ~800 |
| empty / delete of a missing ID | <100 |
| update/reclassify a single existing account | ~400–450 |

## Validation commands actually run

```
python -m unittest discover -s checks -v     # 12 tests, all OK
python demo.py --through 1                   # creates state/demo.sqlite
python demo.py --through 1                   # rerun: no changes (receipts skip)
```

I also ran a few one-off checks:
- An ad-hoc script compared `state/demo.sqlite`'s `rollup` with the reference
  `inner` query (result: match).
- `EXPLAIN QUERY PLAN` confirmed that every maintenance query is an index seek.
- I measured the original implementation on the 80k fixture: about 3.2M
  callbacks.

`checks/test_inner_projection.py` covers:
- the release-1 incident
- NULL sums and NULL keys
- duplicate tags
- sentinel-like strings (`""`, `"null"`, `"None"`)
- MIN/MAX retraction
- repeated writes and net no-ops in one batch
- rate writes that leave `inner` unchanged
- injected failure followed by reopen and retry
- bootstrap from existing sources
- exact large values
- a 250-step randomized comparison with the reference SQL, with reopens and an
  "incremental aux state equals fresh bootstrap" check
- the VM budget on the 80k fixture, with a reopen between batches

## Known limitations / follow-ups

- Only `inner` is implemented. `bootstrap`/`maintain` raise
  `NotImplementedError` for `outer`/`rated`, so an upgrade to an unsupported
  mode rolls back instead of producing a wrong board. To add a mode, register
  a per-account and full-scan cell function in `_ACCOUNT_CELLS`/`_ALL_CELLS`.
  - For `outer`, a tagless account contributes an `m = 1`, segment-NULL cell.
  - For `rated`, rate changes also need to fan out to the accounts tagged with
    the affected segments (via `tags_segment`) and cross with the band
    multiplicity.
- Upgrades rebuild every requested mode from sources, including existing ones.
  The result is the same, but the cost is a full scan, which is allowed for
  upgrades.
- A single very large account (high fanout) costs in proportion to its rows.
  The contract does not limit high-fanout cost.
