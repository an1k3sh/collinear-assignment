# Repair report — releases 1–2 (`inner`, `outer` reports)

## Release 2 — `outer` (LEFT JOIN tags)

**What changed in `maintainer.py`.**
- `SUPPORTED_MODES` is now `("inner", "outer")`.
- A mode is now a pure function of one account's sources. The sources are
  orders aggregated by day, plus a `Counter` of tag segments that counts every
  tag row.
- Both joins are keyed only by `account`, so an account's contribution to every
  group depends only on its own rows. The incremental mechanism from release 1
  (`aux_cell` deltas plus MIN/MAX index seeks) therefore applies to `outer`
  unchanged.
  - `inner`: orders × tag segments.
  - `outer`: the same, except that an account with **no tag rows** contributes
    its orders once under segment SQL NULL (`Counter({None: 1})`).
- A tag whose segment is NULL is still a real match. It multiplies rows exactly
  as in the SQL, and it shares the `(day, NULL)` group with untagged accounts.
- There are no defaults specific to the application. "Unclassified" is just the
  NULL segment that the LEFT JOIN produces, and text such as `"null"` or `""`
  stays as ordinary text.
- A batch now reads each touched account's sources once (two indexed reads) and
  passes them to every active mode. `bootstrap` likewise does one full scan
  that all modes share.

**Upgrade.** `python demo.py --through 2` calls `bootstrap(("inner", "outer"))`,
which rebuilds `aux_cell` and `rollup` for both modes from the sources that are
already stored.
- `rollup` for `inner` comes out the same. This is tested with
  `Upgrade.test_inner_to_outer_preserves_inner_and_continues`.
- Sources and receipts are only read, never written.
- The receipts for release 1 skip on replay. The release-2 batches then run
  incrementally.

**Release-2 incident database (`state/demo.sqlite`, modes `["inner","outer"]`).**
- Receipts: `r1/import`, `r1/correct`, `r2/late-classification`,
  `r2/withdraw-classification`.
- `rollup` equals the reference SQL for both modes.
- Running the replay twice produced byte-identical output.
- Expected changes after r2:
  - `t-c` moving to account `"null"` (segment NULL) removes the `inner`
    `(NULL, retail)` row and adds the `inner` `(NULL, NULL)` row.
  - The `outer` `(NULL, NULL)` group combines account `"null"` (tagged, segment
    NULL), account `"1"` (now untagged) and account `""` (untagged).
  - `o-103` appears under `outer` `(2026-10-01, NULL)`.

**Previously released behavior re-checked.**
- Every release-1 scenario runs twice: `inner` alone and `inner`+`outer`
  together.
- The randomized comparison with the reference SQL also runs in both
  configurations.
- The smoke test still passes.
- The VM budget is checked in three configurations:
  - `inner` only.
  - `inner`+`outer` with 80k tagged accounts.
  - `inner`+`outer` with 80k **untagged** accounts that share the `outer`
    `(day, NULL)` group.
- Each budget batch reopens the database first, and the board is compared with
  the reference afterwards. The largest batch measured was ~5.5k
  progress-handler callbacks (N=1); the limit is 300,000.

**New release-2 tests (`checks/test_projection.py`, renamed from
`test_inner_projection.py`):**
- the release-2 incident replayed after release 1
- orders of untagged accounts are visible only in `outer` and leave/rejoin
  that group as tags are added/removed
- tags without orders contribute nothing
- a NULL-segment tag and an untagged account share one group (distinct
  account count, MIN/MAX)
- upgrade from `inner` to `inner`+`outer` with a reopen, a skipped replay and
  further batches
- an upgrade to an unsupported `rated` mode rolls back without changing modes
  or the board

```
python -m unittest discover -s checks -v     # 30 tests, all OK
python demo.py --through 2                   # upgrade + replay r2
python demo.py --through 2                   # rerun: identical output
```

I also ran an ad-hoc comparison of `state/demo.sqlite` with the reference SQL
for both modes (match), and checked that the release-1 receipt rows were still
present after the upgrade.

---

## Release 1 — `inner`

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
python -m unittest discover -s checks -v     # 12 tests at release 1, all OK
python demo.py --through 1                   # creates state/demo.sqlite
python demo.py --through 1                   # rerun: no changes (receipts skip)
```

I also ran a few one-off checks:
- An ad-hoc script compared `state/demo.sqlite`'s `rollup` with the reference
  `inner` query (result: match).
- `EXPLAIN QUERY PLAN` confirmed that every maintenance query is an index seek.
- I measured the original implementation on the 80k fixture: about 3.2M
  callbacks.

`checks/test_projection.py` (originally `test_inner_projection.py`) covers:
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

- `rated` is not implemented yet. `bootstrap`/`maintain` raise
  `NotImplementedError`, so an upgrade to it rolls back instead of producing a
  wrong board. To support it:
  - Rate changes must fan out to the accounts tagged with the old and new
    segments (via `tags_segment`; NULL segments never join).
  - The cell function must cross each segment with its band multiplicity.
  - Cost must stay proportional to the actual fanout.
- Upgrades rebuild every requested mode from sources, including existing ones.
  The result is the same, but the cost is a full scan, which is allowed for
  upgrades.
- A single very large account (high fanout) costs in proportion to its rows.
  The contract does not limit high-fanout cost.
