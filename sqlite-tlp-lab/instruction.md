# Build a trustworthy SQLite TLP testing tool (revision 2)

You are implementing an internal database-testing tool. Its purpose is to
generate meaningful tests and detect incorrect query results, not merely
produce many SQL strings. No discovery of a previously unknown SQLite bug is
required.

The scaffold is in `/app`. Read `docs/contract.md`, `tlp/model.py`,
`tlp/storage.py`, and the public tests before implementing the missing modules.
The fixed schema and structured expressions deliberately keep SQL generation
bounded; this is not an arbitrary-SQL parser task.

## Deliverables

Implement the functions in `tlp/compiler.py`, `tlp/runner.py`,
`tlp/generator.py`, and the command-line entry point `tlp/__main__.py`.
You may add helpers inside `tlp/` and tests inside `public_tests/`.
Do not modify `tlp/model.py`, `tlp/storage.py`, the contract, or examples.
Do not read verifier/oracle files or replace SQLite. Use Python's standard
library only.

The tool must:

1. Compile valid cases into a baseline SELECT and three SELECTs partitioned
   by a predicate being true, false, or NULL. Support rows, DISTINCT, COUNT,
   SUM, AVG, MIN, MAX, existing filters, inner/left joins, grouped aggregates,
   standalone GROUP BY set-union, and post-aggregation HAVING bag partitioning
   exactly as specified. These are different transformations: HAVING must not
   change which rows contribute to aggregates.
2. Execute every SELECT through the provided executor interface and compose
   partition results correctly. Preserve duplicates, NULLs, types, empty
   aggregates, and groups absent from individual partitions. Detect actual
   mismatches; never swallow execution errors or treat them as passes.
3. Generate reproducible, bounded test cases meeting the public structural
   and semantic diversity thresholds. Random strings and vacuous empty
   comparisons are not sufficient.
4. Run campaigns, save self-contained mismatch artifacts, and replay them
   from a fresh database without trusting recorded outcomes.

The contract defines interfaces, CLI exit codes, report shapes, limits,
numerical semantics, and all diversity criteria. Tests use other cases and
seeds within that contract. Correct alternatives are accepted; SQL formatting
and implementation similarity are not graded.

## Validation and scoring

Run `python -m unittest discover -s public_tests -v` for starter checks.
Add your own tests, including aggregate and replay cases; the starter tests
are intentionally not exhaustive.

The verifier independently checks compilation/partition semantics, aggregate
composition, typed multiset comparison, injected-result mismatch detection,
error propagation, generation coverage, CLI behavior, and replay.
Completeness, validity, diversity, and artifact reliability are reported
separately. Overall reward is zero unless all correctness/protected-file checks,
the published non-vacuity threshold (24 three-way and 48 nonempty cases),
fresh replay, and CLI mismatch/error handling pass; otherwise it is
`0.45 * completeness + 0.35 * diversity + 0.20 * artifact_quality`.
Full success requires every component to be 1.0.
Completeness covers ten equally weighted oracle families. Diversity covers
ten equally weighted test families (determinism plus nine published coverage
categories). Artifact quality covers three equally weighted families.
Every subcase in a family must pass for that family to earn credit.

The fixed environment provides Python and SQLite. The application and
verifier need no network, secrets, external database, or model calls.
