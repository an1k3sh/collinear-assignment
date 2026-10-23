# Projection contract

## Product context

An operations team uses a materialized cohort board while correcting imported
orders and account classifications. Tags are deliberately many-to-many:
different tag IDs with identical values are **different source rows**.
Rate-band records are also versioned source rows, not a unique lookup by segment.
Analysts sometimes clear a value to SQL NULL while investigating it.

The old exporter invalidates a whole day on an order write. It is both stale
after some corrections and too costly on a busy day. Repair the projection
without changing the source records, the transaction host, or the report's
meaning. These are fictional records, not regulated financial advice.

## Allowed changes and entrypoints

Implement `bootstrap(db, modes)` and `maintain(db, modes, changes)` in
`maintainer.py`. Helpers and your own tests are allowed. Do not modify
`runtime.py`, `schema.sql`, `demo.py`, this contract or incident input files.
Python 3.12 and the standard library are sufficient. No network is needed.

The host calls both hooks inside an existing SQLite transaction. Do not commit,
roll back, call `executescript` (it implicitly commits), open another database,
or change the host's pragmas, authorizer, progress handler, or transaction mode.
Keep all persistent auxiliary state in tables/indexes in the **same** database
whose names start with `aux_`. Temporary tables with this prefix are allowed.
You may write `rollup` and your auxiliary objects only. Do not change/drop source
tables, existing indexes, schema, `receipts`, or `settings`. No triggers,
virtual tables, background threads, external state files, or import-time I/O.

`modes` is a tuple of active report names. Releases only add modes.
`bootstrap` may scan all sources and rebuild auxiliary state during an explicit
new database/upgrade. It must produce all requested modes from existing sources.
Opening an already-upgraded database does NOT call bootstrap.

`maintain` runs once after all source writes in a batch. It sees the final
source state, plus a list of changes. Each change is:

```
{"table": "orders" | "tags" | "rates" | "links", "id": <text>,
 "before": <full old row or null>, "after": <full final row or null>}
```

A source ID may be written multiple times in one batch. The host coalesces it
to its pre-transaction and final images, omitting net no-ops. List order has no
semantic significance. No intermediate source state is available to the hook.
Deletes of nonexistent IDs and empty batches are valid no-ops. IDs, accounts,
days, segments and bands are arbitrary case-sensitive text, including empty
strings and strings resembling sentinel encodings. `account` is non-NULL.
`day`, `segment`, `band` and `cents` can be NULL. Cents are signed integers;
test values and sums fit signed 64-bit integers. No date parsing is required.

The host handles receipts and validation. Identical batch retries skip the hook.
Conflicting reuse raises. Hook exceptions and injected pre-commit failure roll
back sources, projection, auxiliary state and receipt together. The same batch
must then succeed when retried, even after closing/reopening the database.
Module globals cannot be relied on for persistent state.

## Exact report semantics

Each active mode has exactly one stored `rollup` row for every nonempty SQL
group and no rows for empty groups. The existing ten columns, in schema order:

`mode, day, segment, band, row_count, amount_count, total_cents,
account_count, min_cents, max_cents`.

The reference query for `inner` is:

```sql
SELECT 'inner', o.day, t.segment, NULL,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o JOIN tags t ON o.account=t.account
GROUP BY o.day, t.segment;
```

Release 2 adds `outer`, the same query but with `LEFT JOIN tags`.
Release 3 adds `rated`:

```sql
SELECT 'rated', o.day, t.segment, r.band,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o
LEFT JOIN tags t ON o.account=t.account
LEFT JOIN rates r ON t.segment=r.segment
GROUP BY o.day, t.segment, r.band;
```

Release 4 adds `household`. It has exactly the same joined rows, group keys and
amount metrics as `rated`, but `account_count` is the number of distinct
**household equivalence classes** represented in the group, not raw accounts.
All three older reports keep their original raw-account semantics.

The source `links(id, left_account, right_account)` records confirmed undirected
account aliases. Each row contributes one edge. Endpoints are arbitrary
non-NULL, case-sensitive text; self-links, cycles and different IDs with the
same endpoints are valid. Accounts are equivalent precisely when a path exists
in the current link graph, including paths through accounts that have no
orders or tags. Every unlinked order account is its own class. Equivalence is
global, not recomputed separately within a report group. A conceptual canonical
class label is its least account string under SQLite BINARY ordering, although
no class label is part of the output and any correct internal identity is valid.

Equivalently, construct a relation `households(account, representative)` from
the final source graph, with one representative per connected component and
isolated order account. The `household` query is the `rated` query with mode
`'household'`, an additional join `JOIN households h ON h.account=o.account`,
and `COUNT(DISTINCT h.representative)` replacing `COUNT(DISTINCT o.account)`.
Links do not deduplicate order, tag or rate rows or change any amount metric.

Deleting the last edge supporting a connection may split a class. Deleting
one of multiple parallel edges does not. Link rekeys can merge and split
classes in the same batch; orders, tags and rates may also change in that batch.
Link changes arrive through the same coalesced before/final-image protocol.
Updates to a class label with no immediate output effect still need durable
state suitable for subsequent edits. A full graph rebuild per small batch is
not acceptable.

Ordinary SQLite bag, join, aggregate, and NULL semantics apply. In particular,
join comparisons use `=`, not NULL-safe equality, while GROUP BY combines NULL
keys. SUM over all-NULL amounts is NULL, not zero. Negative/zero amounts and
duplicate values are valid. DISTINCT is over account identities, not joined
rows. Several unrelated accounts may occupy one output group. Row ordering
and internal auxiliary representation are unrestricted.

## Work and durability constraints (all releases)

This service receives small correction batches against a much larger archive.
Full rebuilds on `maintain`, full-day scans, global distinct recomputation, and
startup rebuilds on reopen are not acceptable substitutes for incremental work.

The verifier counts **SQLite virtual-machine instructions**, not wall time:
on a database with 80,000 unrelated accounts sharing the target day and segment,
a batch touching one small account (at most eight orders, four tags, four rates)
must use at most **300,000 VM instructions**, including host source writes and
receipt handling. A segment-rate correction whose actual account fanout is small
has the same limit. Counters run only during `apply`, not fixture loading,
upgrades or reference verification. In release 4 the same cap also applies to
alias edits and source corrections involving up to eight accounts in the union
of the old and final affected components, with up to eight orders and four tags
per account, and four matching rate rows per segment. Unrelated archive accounts
can share those output groups. There is no limit for high-fanout updates;
correctness is still required. For an empty/net-no-op batch the same limit
applies. This work bound is machine-independent and allows ample headroom for
indexed account/bucket maintenance. Do not disable or replace instrumentation.

The bound includes work across all active modes. The final tests also vary
other-group cardinality and reopen the database between updates. Do not move
source scans to Python globals or external files; that violates durability.
Report reads use only stored `rollup`, not the source join.

## Release artifacts and local checks

`python demo.py --through N` opens `state/demo.sqlite`, upgrades reports and
replays incident releases 1..N using stable receipt IDs. It does not repair
incorrect previously acknowledged projections for you. It can be repeated
without changing correct state. Keep this durable database and all original
sources/receipts. Do not delete it to conceal a failed upgrade.

At each release, run the matching replay, add/update your own regression tests,
and update `REPAIR_REPORT.md` with your design, diagnosed failure mechanism,
commands actually run, and any known limitations. The report is a human handover,
not an exact-string grading target. The verifier checks code behavior and the
database, not prose phrasing.

Useful starting commands:

```
python -m unittest discover -s checks -v
python demo.py --through 1
```

The public smoke checks are intentionally not exhaustive. Build your own tests
against the SQL above, including corrections and restarts.
