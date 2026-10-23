# TLP Lab contract, revision 2 (JSON wire version 1)

Revision 2 adds standalone GROUP BY and HAVING oracles. Existing version-1
cases remain valid. The revision changes the supported task, not the JSON
envelope version; cases, summaries, and replay artifacts still use `"version":1`.

## Data and expressions

Every case is a JSON object with exactly these fields:

```
{
  "version": 1,
  "tables": {"t": [[id, k, v, tag], ...], "u": [...]},
  "source": "single" | "inner" | "left",
  "predicate": expression,
  "where": expression | null,
  "mode": "rows" | "distinct" | "count" | "sum" | "avg" | "min" | "max" | "group" | "having",
  "select": [expression, ...],
  "value": expression | null,
  "group_by": [expression, ...]
}
```

Both tables have `(id INTEGER, k INTEGER, v INTEGER, tag TEXT)` with BINARY
text collation, no uniqueness constraints, and at most 32 rows each.
Integer cells are NULL or integers in [-1000, 1000]; text cells are NULL or
Unicode strings of at most 32 characters (including quotes and embedded NUL).
Duplicate IDs and rows are allowed. No REAL or BLOB input columns exist.

`source=single` reads t. `inner` and `left` join t to u on `t.k = u.k`;
the join must occur before the filter and partition. No column from u may
occur in a single-table case.

Expressions are JSON arrays:

* `["col", "t" | "u", "id" | "k" | "v" | "tag"]`
* `["lit", value]` with the same integer/text/NULL bounds as cells
* `["add", numeric, numeric]`, `["sub", numeric, numeric]`
* `["eq" | "ne" | "lt" | "le" | "gt" | "ge", scalar, scalar]`
* `["and" | "or", predicate, predicate]`
* `["not" | "isnull", expression]`
* HAVING-stage only: `["agg", "count" | "sum" | "avg" | "min" | "max", numeric]`;
  `["agg", "count", null]` means COUNT(*).

Expression depth is at most 6. `add` and `sub` operands are numeric columns,
integer/NULL literals, or numeric arithmetic. Boolean operators take
predicates. Comparisons use SQLite's normal semantics. A predicate is a
comparison, and/or/not, or isnull; isnull can inspect a scalar or predicate.
No raw SQL, nondeterministic functions, collations, aliases, or arbitrary
operators are supported. Values must be bound as parameters, never interpolated.
Aggregate arguments use the row-stage numeric grammar: no nested aggregates.
In HAVING mode, the predicate and select expressions may contain aggregate
nodes, literals, arithmetic, and complete grouping expressions. A column
outside an aggregate must itself be a grouping expression or occur inside a
complete grouping expression (structural equality with a group_by entry).
For example, if group_by is `[["add", ["col","t","k"], ["lit",1]]]`, that whole
addition is permitted, but a bare `t.k` outside it is not. WHERE and group_by
never contain aggregate nodes. This avoids SQLite's arbitrary bare-column
behavior in aggregate queries.

Rows/distinct cases have 1-3 scalar select expressions, empty group_by, and null value.
Count/sum/avg/min/max cases have empty select, 0-2 scalar group expressions, and numeric
value; count alone may use null value to mean COUNT(*). COUNT(value) excludes
NULL. SUM/AVG/MIN/MAX values are integer-valued or NULL. Bounds ensure exact
integer sums below 2^53; only AVG outputs floats. There is no DISTINCT inside
aggregates, LIMIT, ORDER BY, floating-point input, or window function.
Group mode has 1-2 grouping expressions, select exactly equal to group_by, and
null value; its predicate is a row-stage predicate. HAVING mode has 0-2 grouping
expressions, 1-3 non-predicate select expressions, and null value. Its predicate
is evaluated AFTER aggregation. The projection may omit group keys and two
different groups may produce identical output rows. With no group_by,
the projection must contain an aggregate node so the baseline has an implicit
single group, including on empty input.
Invalid case shapes must raise ValueError before running SQL.

## Interfaces

Keep the signatures/imports in the supplied modules:

* `compile_case(case) -> Plan`: calls `validate_case`; returns a baseline Query,
  exactly three partition Queries in true/false/unknown order, mode, and group
  column count. Every query is one read-only SELECT, with positional `?`
  parameters. Queries must work on any database populated to this schema;
  compilation cannot bake in answers from case.tables.
* `compose(plan, partition_rows) -> list[list[Cell]]`: combines three
  partition result lists into baseline-shaped rows. It must not read SQLite,
  consult table data, or execute extra queries.
* `equivalent(expected, actual) -> bool`: order-independent, type-sensitive
  multiset equality, preserving multiplicity. NULL differs from every other
  value; integer 1, float 1.0, and text "1" are distinct. Float equality is
  exact (these bounded integer aggregate workloads do not need tolerances).
* `run_case(case, executor=None) -> dict`: builds a fresh in-memory database,
  compiles once, and executes the baseline then the three partitions, exactly
  once each through `executor(connection, query)`. Default executor uses
  SQLite. Returns `{"ok": bool, "expected": rows, "actual": composed_rows}`.
  Propagate executor/SQLite errors. Always close the database.
* `generate(seed, count) -> list[case]`: deterministic within the pinned
  environment, without changing global random state; count in [0, 4096],
  signed 64-bit seed. Invalid arguments raise ValueError. Same seed/count
  gives the same JSON structures; different seeds vary data and cases.
* `save_failure(path, case, result)` writes UTF-8 JSON with exactly
  `{"version": 1, "case": case, "result": result}` for a mismatching result.
  Passing results raise ValueError. Create parent directories.
* `replay(path, executor=None) -> result`: validate artifact shape and case,
  rebuild from its embedded tables, and rerun. Never reuse recorded results.
  Missing/malformed artifacts raise explicit exceptions.

## SQL plan layout and composition

Except for HAVING mode, the baseline reads the source after the optional WHERE filter W.
Partitions read that same source with `(W) AND (P)`, `(W) AND NOT(P)`,
and `(W) AND (P IS NULL)`; omit W when absent.

* rows: select the projection in baseline and partitions; concatenate bags.
* distinct: baseline SELECT DISTINCT; partitions may retain duplicates or
  use DISTINCT; deduplicate across the entire combined result.
* group: baseline and partitions project the grouping expressions and apply
  GROUP BY. The predicate partitions input rows BEFORE grouping. The same
  group may occur in multiple partitions: combine their outputs by set union,
  not concatenation. This is the paper's standalone GROUP BY oracle, distinct
  from the grouped aggregate states below.
* having: baseline evaluates the projection on the full groups after WHERE.
  Partitions preserve that same WHERE and GROUP BY, then apply respectively
  HAVING P, HAVING NOT(P), HAVING (P IS NULL). Concatenate their output bags:
  DO NOT recompute aggregates from partial rows or deduplicate projected
  groups. The plan's group_count is still len(group_by), but HAVING projections
  need not have group keys as a prefix. No existing HAVING filter is modeled.
* count: baseline groups followed by COUNT(value) or COUNT(*); each partition
  returns the same layout. Sum counts by group.
* sum/avg: baseline groups followed by SUM(value)/AVG(value); each partition
  returns groups followed by SUM(value), COUNT(value). Merge sufficient
  statistics, not averages of averages. Zero non-NULL count yields NULL.
* min/max: baseline and partitions return groups followed by MIN/MAX(value).
  Merge non-NULL extrema; all-NULL values yield NULL.

All grouped SELECTs GROUP BY the specified expressions. Group keys may contain
NULL or text. Merge groups across partitions even if absent from some.
Ungrouped aggregates return one row even for empty inputs; grouped aggregates
on empty inputs return no rows. No source or group may be dropped.
For HAVING mode, an ungrouped aggregate on empty input still has one group:
its NULL-valued predicate belongs to the unknown partition, rather than
making every partition empty.

## CLI

Run from /app:

```
python -m tlp campaign --seed 17 --count 112 --out reports/run
python -m tlp replay reports/run/failure-000000.json
```

Campaign exits 0 if all comparisons match, 1 for any mismatch, 2 for invalid
input or execution failure. On a successful execution (including mismatches)
write `cases.jsonl`, one generated case per line, and `summary.json`:
`{"version":1,"seed":N,"requested":N,"executed":N,"passed":N,"mismatches":N}`.
Mismatch files use zero-based case indices, six-digit names as above.
Reject a nonempty output directory explicitly; never leave stale success
artifacts or overwrite prior reports. Execution errors must print a diagnostic
to stderr and must not produce a success summary.

Replay prints its fresh result as JSON; exits 0 if it now matches, 1 if the
mismatch reproduces, 2 on invalid input/execution errors. Reports are portable
across working directories. Correct SQLite may not reproduce a mismatch
originally induced by a testing executor; that is expected.

## Published diversity requirements

For every assessed seed, a 112-case campaign must:

1. Include all nine modes at least 8 times each.
2. Include each source kind at least 16 times; at least 16 cases have WHERE.
3. Include at least 20 grouped count/sum/avg/min/max cases, with all five modes
   represented among them; include both COUNT(*) and COUNT(value).
4. Include predicate operators eq, lt, and, or, not, isnull; at least 12
   predicates have depth >= 3.
5. Have at least 20 distinct structural fingerprints. Fingerprints erase
   literal values (retaining type) and table rows; they retain source, mode,
   expression operators/columns, projections, filters, and groups.
6. Include at least 24 cases where true, false, and unknown partitions ALL
   contain rows after the join and WHERE, and at least 48 with nonempty input.
7. Include at least 6 cases with empty filtered input, at least 6 aggregate
   cases with nonempty input and all-NULL value expressions, and at least 6
   rows/distinct cases with duplicate projected rows before DISTINCT.
8. Among group-mode cases, at least 6 must have a group occurring in two or
   more partitions, and at least 2 must have WHERE.
9. Among having-mode cases, at least 6 must have groups in ALL three partitions,
   at least 4 must have duplicate baseline projected rows, at least 2 must be
   ungrouped, and at least 2 must have WHERE.

For HAVING, partition occupancy counts groups after WHERE/GROUP BY, not input
rows; an ungrouped aggregate on empty input counts as one group. The empty
input and all-NULL-value requirements in item 7 are measured on row-stage
cases (all modes except having).

These are actual execution measurements, not self-reported labels. Stratified
generation is encouraged; random luck is unnecessary. Seeds and cases vary in
private tests but categories and thresholds do not.

## Assessment

The verifier uses direct independently assembled SQL and controlled result
perturbations. It does NOT require finding a new SQLite bug. Coverage means
coverage of this finite support matrix, not all SQL. Correct comparisons,
compilation, composition, validation, and error handling form a correctness
gate. The gate also requires the published partition-occupancy threshold
(24 three-way and 48 nonempty cases per 112-case campaign), fresh replay
rather than trusting saved outcomes, and correct CLI mismatch/error handling.
Diversity and report quality cannot compensate for an unsound oracle or
vacuous generator. Other diversity categories and normal CLI artifact checks
contribute the partial-credit components described in the task instruction.
Feature completeness has ten equally weighted test families matching the
paper: WHERE, WHERE Extended, GROUP BY, HAVING, DISTINCT, and five aggregates.
All must pass to open the correctness gate. Diversity is the fraction of ten
test families passed: determinism/bounds plus the nine numbered categories
above. Artifact quality is the fraction of three families passed: ordinary
CLI/report behavior, save/replay, and CLI mismatch/error behavior. The last
two are also required gates. A family passes only if all its subcases pass.
