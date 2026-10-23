# Repair report — releases 1–4 (`inner`, `outer`, `rated`, `household`)

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
* Each *join shape* is a per-account multiplier rule (`_multipliers`) over
  {(segment, band): joined rows per order}. An account's sources are loaded
  once per batch and shared by all shapes. `aux_contrib.mode` stores the
  shape. `inner`, `outer` and `rated` are their own shapes, and `household`
  reuses the `rated` shape (release 4). Unknown modes raise
  `NotImplementedError`, so the host rolls back the upgrade.

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

## Release 4: `household`

`household` has exactly `rated`'s joined rows, groups and amount metrics. Only
`account_count` changes, to count distinct alias equivalence classes. The
design follows from that:

* **Shared contributions.** `household` uses the `rated` shape's
  `aux_contrib` rows, so its row/amount/sum/min/max values are produced by
  the same deltas and the same MIN/MAX index read as `rated`. Links can
  therefore never deduplicate amounts, and the three older reports never
  read link state. Household-only mode sets (for example `("household",)` or
  `("inner","household")`) still maintain the `rated` shape internally and
  write only the active modes' rows.
* **Components (`aux_comp(account PRIMARY KEY, rep)`, index on `rep`).** One
  row per account incident to at least one link. An account without a row is
  its own class. `rep` is the least account in the component. Any label would
  do; this one is deterministic. Accounts with no orders (dormant bridges)
  are stored too, so a label change with no immediate output effect remains
  durable for later edits. `bootstrap` builds the table with union-find over
  all links.
* **Incremental link maintenance (`_update_components`).**
  1. Collect the endpoints of every link `before`/`after` image.
  2. Load their **old** components through `aux_comp_rep`.
  3. Search the **final** link graph from those nodes (`links_left`/`links_right`).

  A path leaving the union of old components would need an unchanged edge,
  whose ends share an old component, or a changed edge, whose ends are
  loaded. The search therefore stays inside that union; on-demand loading is
  only a safeguard. This single recomputation handles:
  * merges, including through dormant accounts;
  * splits after deleting the last supporting edge;
  * parallel-edge deletes, which change nothing;
  * cycles and self-links;
  * rekeys that merge and split in one batch.

  Only changed `aux_comp` rows are written. The step returns
  `{account: (old_rep, new_rep)}`. No global graph rebuild happens.
* **Distinct counts (`aux_hh(day, segment, band, rep, n)`, index on
  group+rep).** `n` is the number of contributing accounts in a group with
  class `rep`. The household `account_count` of a group is its number of
  `aux_hh` rows. Each affected account contributes −1 for every (old group,
  old rep) pair and +1 for every (new group, new rep) pair. Pairs that are
  unchanged cancel without SQL. Applying these deltas yields per-group
  0↔positive transitions, which become the `account_count` delta.
  * Accounts whose sources changed use the old/new keys from their
    `rated`-shape refresh.
  * Accounts whose only change is the rep (link-only effect) read their
    current keys from `aux_contrib`.

  A link-only batch therefore touches `aux_comp`, `aux_hh` and the household
  `account_count` of affected groups only. Older reports are untouched.
* **Same-batch mixes.** Components are updated first. Source and rate
  refreshes then see each account's (old_rep, new_rep), so alias edits
  combined with order, tag and rate corrections are applied consistently,
  independent of change order.
* **Upgrade.** Adding `household` runs `bootstrap`, which creates
  `aux_comp`/`aux_hh` and rebuilds everything. The tables are used only when
  `household` is active, so `AUX_VERSION` stays `1`. A database with three
  modes ignores link changes, and they are picked up by the bootstrap when
  `household` is added.

## Validation (commands actually run)

Release 1:

```
python -m unittest discover -s checks -v      # 10 tests, all OK
python demo.py --through 1                    # run twice; identical output
python3 -c "...compare rollup to reference inner SQL on state/demo.sqlite..."  # True
```

Release 4:

```
python -m unittest discover -s checks -v      # 26 tests, all OK
python demo.py --through 4                    # upgrade + replay; run twice, identical output
python3 - <<EOF ... EOF   # rollup == reference SQL for each of the 4 modes: True;
                          # all r1–r3 receipts preserved; integrity_check ok
# mutation check: ignoring link `before` images (missed splits) => 6 tests fail
# progress-handler sanity: `SELECT 1` counts 5 = its 5 opcodes
```

Release 4 tests:

* The household reference in `checks/test_projection.py` is built directly
  from the contract with a recursive CTE: undirected reachability over
  `links` with `MIN` under BINARY as the representative, joined to the
  `rated` query. It does not share code with the implementation. Every
  generic check compares all active modes against it.
* `HouseholdSemantics` covers:
  * Merging through a dormant bridge, then splitting after reopen. Household
    amounts equal `rated`, and `rated` keeps raw accounts.
  * Parallel edges, cycles and self-links. Deleting one parallel edge or a
    cycle edge does not split a class; deleting the last edge does.
  * A link rekey that splits and merges in the same batch as tag/rate/order
    edits and a coalesced link rewrite.
  * Dormant-only components with no output change, which are durable across
    reopen and used by later joins, relabels and splits.
  * A failed alias batch leaving no component state, then a successful retry.
* `Randomized.test_random_alias_heavy_batches`: 400 batches with 60% link
  edits (dormant endpoints, self-links, parallel IDs), plus failure, retry
  and reopen. The original randomized test now also includes links.
* `RandomizedModeSubsets` covers `("household",)`, `("inner","household")`
  and the full release path inner→outer→rated→household, with random batches
  and reopen at each stage.
* `IncidentReplay` now replays all four incident files with
  failure/reopen/retry and checks every mode after each step.
* `WorkBound.test_alias_edits_on_busy_groups_stay_within_budget`: 8 accounts,
  each with 8 orders and 4 tags. Each segment has 4 rate rows, sharing groups
  with the 80,000-account archive. VM instructions per batch:
  * rate setup 656
  * seed 96,663
  * chain merge 29,399
  * split 11,234
  * parallel edge 249
  * rekey merge+split 15,193
  * dormant relabel 6,928
  * all 64 orders and 32 tags rewritten plus a merge and a split 188,207
  * segment-rate fix 57,929
  * unlink all 40,907
  * delete all 116,334

  An ad-hoc harsher probe rewrote all 8 accounts × 8 distinct days × 4
  segments × 4 bands (1,024 rated groups) during a split. It peaked at
  204,280. The earlier single-account budget test, now with four modes,
  stays ≤ 23,776.

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

`state/demo.sqlite` was upgraded in place by `python demo.py --through 4`.
Its modes are `["inner","outer","rated","household"]`. It holds all ten
receipts (`r1/*`…`r4/*`) with the original sources. Its `rollup` equals all
four reference queries, and replaying again changes nothing.

## Known limitations

* Splitting or merging a very large component costs work proportional to its
  size and to the groups of its order-bearing members, which the contract
  leaves unbounded for high fan-out. The worst bounded case measured
  (8 accounts, every contribution rewritten) uses about 2/3 of the 300k cap.
  Accounts with more distinct days × segments × bands than the stated limits
  scale linearly.
* A rate change on a segment shared by many order-bearing accounts costs work
  proportional to that fan-out. The contract sets no bound for high fan-out.
* A single account with very many orders or tags costs work proportional to
  that account's rows (no bound required for high fanout).
