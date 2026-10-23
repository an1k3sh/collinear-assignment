# Public contract

## C++ interfaces and execution

Implement the five functions declared in `include/tlp.hpp`. `generate(bytes)`
must be deterministic, process-local-state independent, bounded, and total for
every byte vector of length 0..512. Longer inputs may also be supported.
`compile(case)` receives a valid case and returns four read-only SELECTs:
baseline, true, false, NULL, in that order. Values must use SQLite bindings.
There must be no execution or dependence on the particular database rows during
compilation. A compiled plan must also work on different data with the same schema.

`compose(case, parts)` recombines the three independently executed results.
`equal(a,b)` compares typed multisets, preserving duplicates and column order.
Integer, real, text and NULL are distinct; row order is irrelevant. JSON signed
and unsigned integers are the same SQL integer type. Bounded arithmetic permits
exact float comparison here; do not use tolerances that hide small differences.
`check(case, execute)` compiles and invokes the supplied executor exactly four
times, then returns the actual baseline, recomposed rows and comparison result.
Propagate executor exceptions. Never substitute self-executed queries.

The protected harness creates fresh SQLite databases and closes all statements
and connections. A mismatch or exception aborts the libFuzzer callback, allowing
libFuzzer to save the original bytes. CLI replay executes those bytes afresh.
Do not catch failures and return success, reject arbitrary fuzz bytes, or replace
errors with empty results. A mismatch is a valid test input, not invalid SQL.

The CLI accepts one JSON request per line and emits one JSON answer per line:

* `{"op":"inspect","hex":"0123"}`: generate, compile, execute, compare.
* `{"op":"case","case":CASE}`: compile/execute an explicitly supplied valid case.
* `{"op":"compose","case":CASE,"parts":[ROWS,ROWS,ROWS]}`: composition alone.
* `{"op":"equal","a":ROWS,"b":ROWS}`: comparison alone.
* `{"op":"inject","case":CASE,"call":2,"rows":ROWS}`: replace one executor
  response (call numbers 1..4), to test mismatch sensitivity.
* `{"op":"error","case":CASE}`: executor throws; CLI must exit 2 with diagnostics.

Inspection answers contain `case`, `plan.base`, `plan.parts`, and `result`.
Queries have `sql` and `params`. Result has `base`, `combined`, `equivalent`,
and `calls`. The protected CLI implements this protocol; do not reimplement it.

## Case schema

Exact keys: `version,tables,source,predicate,where,mode,select,value,group_by`.
`version` is integer 1. Tables are exactly `t` and `u`, each a list of 0..32 rows.
A row is `[id,k,v,tag]`: the first three cells are integers in [-1000,1000] or
NULL; tag is a string of at most 32 Unicode characters or NULL. Duplicates are
allowed everywhere; no column is unique. Strings may contain quotes and NUL.

Sources: `single` = t; `inner` = t JOIN u ON t.k=u.k;
`left` = t LEFT JOIN u ON t.k=u.k. References to u are invalid in single mode.

Expressions are JSON arrays, at most 6 nodes deep (root depth 1):

* `["col",table,column]`
* `["lit",value]`: bounded integer, bounded string or NULL as above.
* `["add",numeric,numeric]`, `["sub",numeric,numeric]`
* `["eq"|"ne"|"lt"|"le"|"gt"|"ge",scalar,scalar]`
* `["and"|"or",predicate,predicate]`
* `["not",predicate]`, `["isnull",scalar_or_predicate]`
* At HAVING stage only: `["agg",function,numeric]`, where function is
  count/sum/avg/min/max. COUNT(*) uses `["agg","count",null]`.

Boolean operators require predicates; comparisons require non-predicate scalars.
Arithmetic and aggregate arguments must be numeric. No nested aggregates.
`where` is a row-stage predicate or NULL. `predicate` is mandatory: a row-stage
predicate except in HAVING mode, where it is a group-stage predicate.
`group_by` is a list of 0..2 row-stage scalar expressions.
At group stage a bare column is only valid as part of a complete expression
that appears in group_by, or inside an aggregate argument.

## Nine modes / ten oracle families

* `rows`: 1..3 scalar select expressions; group_by empty; value NULL. Partition
  with WHERE p, NOT p, p IS NULL and concatenate bags. If an existing WHERE is
  present, preserve it in all four queries (the WHERE Extended oracle).
* `distinct`: same schema; baseline and each partition use SELECT DISTINCT.
  Recombine with global set union, not concatenation.
* `group`: nonempty group_by; select exactly equals group_by; value NULL.
  Partition rows before grouping and recombine with set union.
* `having`: 1..3 group-stage scalar select expressions; value NULL. Partition
  complete groups with HAVING p, NOT p, p IS NULL, leaving aggregate input rows
  unchanged. Recombine bags, preserving identical projections of different
  groups. With no group keys SELECT must contain an aggregate, including for
  empty input's implicit aggregate group. There is no existing HAVING filter.
* `count,sum,avg,min,max`: select empty; value is a numeric row-stage expression,
  except COUNT(*) may use NULL. Baseline outputs group keys then the aggregate.
  All three partitions use row-stage WHERE. For SUM/AVG each partition outputs
  group keys, SUM(value), COUNT(value); other modes output keys then aggregate.
  Merge matching keys across partitions, including keys absent in some parts.
  COUNT adds counts; SUM uses NULL if all counts are zero; AVG uses total SUM
  divided by total COUNT (not average-of-averages); MIN/MAX ignore NULL states,
  yielding NULL if all states are NULL.

Grouping always uses SQL semantics, not positional assumptions about HAVING
projections. No real-valued inputs, raw SQL AST nodes, aggregate DISTINCT,
arbitrary collations, ORDER BY, LIMIT, windows, or arbitrary schema are required.
Input bounds prevent integer overflow and inexact integer accumulation.

## Diversity: measured behavior, not generator labels

The verifier measures 1,024 unseen deterministic pseudorandom byte vectors
(lengths 16..512), plus boundary inputs. Its seed values are not a required
interface and must not be special-cased. On that 1,024-input corpus require:

1. All nine modes >=40 cases each; all three sources >=100 each; existing
   WHERE >=200; grouped legacy aggregates >=100.
2. >=950 distinct complete cases and >=900 distinct database contents.
3. >=256 structural fingerprints and >=128 topology fingerprints. Structural
   fingerprints remove all table rows and literal values. Topology fingerprints
   additionally erase column identities. Each mode has >=8 topology fingerprints.
4. At least 50 cases have nonempty true, false AND NULL partitions; at least
   500 have nonempty baseline results. Occupancy is independently executed and
   is group-stage for HAVING. Require >=6 GROUP BY cases with overlapping groups
   across partitions, >=6 HAVING cases with duplicate baseline projections,
   >=6 empty row-stage cases, and >=6 all-NULL SUM/AVG/MIN/MAX inputs.
5. All AST operators listed above occur. Row expressions use t and u, id/k/v/tag;
   each of the five aggregate nodes occurs in HAVING. Require >=100 predicates
   of depth >=3. Both COUNT(*) and COUNT(expression) must occur.

For 64 further 128-byte inputs, independently replace each 32-byte quarter.
In every quarter at least 32/64 replacements must change the complete case,
and in at least TWO quarters at least 16/64 must change topology. Repeating the
same bytes in the same or a fresh process must reproduce the same case and plan.
This rejects ignored payloads, prefix-only selectors and literal-only variation.
Direct decoders, grammars, and deterministic local random expansion of input
entropy are all allowed. No requirement to use every byte one-to-one.

The verifier also starts real libFuzzer with ASan/UBSan for 10,000 executions,
a bounded seed corpus and max_len=512. It inspects up to 256 resulting corpus
entries: at least 16 topology fingerprints and four modes must occur. There is
no absolute edge-coverage threshold, speed bonus, or requirement to find a bug.
Raw libFuzzer coverage/features are recorded as evidence, not conflated with
semantic query diversity. The finite campaign must finish without sanitizer
errors, crashes, timeouts or mismatches. Individual inputs must finish within
five seconds; the generous verifier budget includes rebuilding.

## Validity, correctness and rewards

For sampled emitted cases, report schema-valid count, four-query-executable
count, and independent semantic-match count. The input-validity rate divides
schema-valid/executable cases by attempted inputs; errors cannot disappear from
the denominator. Correct SQL syntax and correct partition meaning are separate.
The four compiled queries must match independently generated SQL on the
original AND changed database contents. No result comparison alone can replace
these checks. Output correctness covers supplied fixtures as well as generation.

Reward fields:

* `input_validity_rate`: valid and independently executable / attempted inputs.
* `semantic_validity_rate`: all four queries mean the specified transformation,
  including changed data / attempted inputs.
* `oracle_correctness`: fraction of correctness test families passing.
* `diversity`: fraction of the seven diversity families passing (five numbered
  requirements above, counterfactual input sensitivity, live corpus).
* `overall`: 0 unless build/protected harness, all correctness families, both
  validity rates at 1, determinism/replay, actual libFuzzer execution, and the
  data/structure/occupancy/sensitivity/live-corpus diversity families pass.
  Otherwise equal to diversity. Coverage and grammar can earn partial credit
  only after these gates pass. Full success is 1.

All thresholds are public. Positive alternative implementations must be
accepted. Known wrong recomposition, data-only variation, fixed catalogues and
ignored fuzz payloads are author-tested negative controls. These controls and
finite corpora are evidence, not proof of absence of every possible hardcoding.
