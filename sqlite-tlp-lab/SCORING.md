# Exact scoring and grader validation (revision 2)

The verifier runs 32 test methods against the submitted implementation:

| Component | Test families | How the component is calculated |
|---|---:|---|
| Validity | 9 | Fraction of validity methods passing |
| Completeness | 10 | Fraction of oracle-family methods passing |
| Diversity | 10 | Fraction of generator methods passing |
| Artifact quality | 3 | Fraction of CLI/replay methods passing |

Every subcase in a method must pass. Assertion failures, exceptions, and
timeouts are not successful comparisons. There is no LLM judge, source-code
similarity check, requirement to discover a new database bug, or elapsed-time
speed bonus.

## Gate and formula

Overall is zero unless ALL of these hold:

1. Validity = 1.
2. Completeness = 1.
3. The partition-occupancy diversity test passes.
4. The fresh save/replay test passes.
5. The CLI mismatch/error-path test passes.

If the gate passes:

```
overall = round(0.45 * completeness
              + 0.35 * diversity
              + 0.20 * artifact_quality, 6)
```

Full success means overall = 1.0. Any missing component remains visible in
the detailed results, including when overall is zero.

### Post-trial input diagnostics

After the frozen v2 Opus trial completed, diagnostics revision 1 added two
reward fields without changing the overall formula or gates:

* `oracle_correctness`: explicit alias for the original `validity` component.
  The legacy key is retained for compatibility. Neither is an input percentage.
* `input_validity_rate`: schema-valid, successfully executable cases divided
  by all emitted cases across four 112-case campaigns. Empty emission yields
  0.0, not a vacuous 100%.

`input-validity.json` also records requested, emitted, schema-valid, and
executable counts, exact emission-count agreement, and stage-specific errors.
Schema validation uses the supplied contract validator; execution uses fresh
SQLite databases and an independent executor, not candidate `run_case` success
claims. All four SELECTs must execute. Writes are denied.

An executable case with a result mismatch is still a valid input. Conversely,
four executable SELECTs do not establish a sound TLP transformation; the
correctness suite checks that separately. Empty-table cases can have 100%
input validity while failing non-vacuity/diversity requirements.

The frozen trial's original rewards are not rewritten. Retrospective
measurements are saved separately as `post-run-input-validity.json`.

Completeness is both a diagnostic component and a gate: its 45% contribution
is necessarily 0.45 whenever the gate opens. The weights do NOT imply that
finding most aggregate answers correctly compensates for an unsound oracle.

Example: all correctness gates pass, 9/10 diversity families pass, and all
artifact families pass: overall = 0.965. An incorrect HAVING transformation
instead gives overall = 0, regardless of generator coverage.

## Validity: nine methods

* Protected files retain their expected checksums.
* Compiled baseline and each partition agree with independently assembled
  SQL, including when executed against changed data after compilation.
* Literal values are parameter-bound rather than interpolated.
* Comparison preserves types, NULLs, duplicates, and column order, while
  ignoring row order.
* Composition handles synthetic bags and aggregate states without a database.
* The executor sees exactly four queries; injected observable mismatches are
  detected; database resources are closed.
* Errors propagate and invalid cases/arguments are rejected explicitly.
* Hand-calculated GROUP BY/HAVING witnesses preserve shared groups, duplicate
  projections, empty input semantics, and mismatch detection.
* Hand-calculated witnesses also check the independent SQL reference itself.

These are semantic checks; alternative SQL formulations and output row order
are accepted. For example, an equivalent derived-table wrapper is valid.

## Completeness: ten equally weighted oracle families

WHERE, WHERE Extended, GROUP BY, HAVING, DISTINCT, COUNT, SUM, AVG, MIN, MAX.
Each is exercised on fixtures within the public contract. The suite includes
219 cases overall, with join variants, filters, NULL/group keys, all-NULL
aggregates, and empty inputs. The plan-validity method additionally executes
each plan against changed data.

GROUP BY partitions rows before grouping and uses set union. HAVING partitions
already-computed groups and uses bag concatenation. Identical projected rows
from different groups must not disappear.

## Diversity: ten equally weighted families

One family checks deterministic generation, seed/count bounds, no changes to
global random state, and variation across seeds.

The other nine are exactly the numbered requirements in
[the public contract](environment/app/docs/contract.md). They are assessed
on 112 cases for each of four fixed seeds: 0, 17, -435, 9823.
Seed identities are not needed to satisfy the contract: it requires the
thresholds for every assessed seed.

Measurements are computed by the verifier using SQL and AST structure:

1. Nine modes, each at least eight times.
2. Three sources, each at least 16 times; at least 16 filters.
3. At least 20 grouped legacy aggregate cases covering all five aggregates;
   both COUNT forms.
4. Required operators and at least 12 sufficiently nested predicates.
5. At least 20 structural fingerprints after erasing literal values/data.
6. At least 24 three-way occupied cases and 48 nonempty cases.
7. At least six empty row-stage inputs, six nonempty all-NULL aggregate
   inputs, and six duplicate row projections.
8. At least six GROUP BY cases sharing groups across partitions; two filtered.
9. At least six HAVING cases with all partitions occupied, four with duplicate
   projected rows, two ungrouped, and two filtered.

HAVING occupancy is measured over groups, not source rows. Generator labels
and self-reported coverage are not trusted. Stratified generation is allowed.

## Artifact quality: three methods

1. Normal campaign/report CLI, empty-directory policy, replay CLI, invalid
   artifact diagnostics, and deterministic cases.
2. Save/replay schema, portable database reconstruction, and fresh execution
   rather than trusting recorded outcomes.
3. CLI mismatches produce exit 1 and replay files; execution errors produce
   exit 2, diagnostics, and no success summary.

## Validate the grader

From this task directory:

```sh
python3.12 -m unittest discover -s tests -p test_grading.py -v
python3.12 -m unittest discover -s tests -p test_input_validity.py -v
python3.12 tests/author_check.py --out evidence/author-v2
```

The first command checks score arithmetic, all gate failures/missing results,
and partial-credit weighting. The second checks the input-rate denominator,
schema versus execution failures, short generation, denied writes, and the
fact that mismatches remain valid inputs. The third checks:

* the untouched scaffold is rejected;
* the oracle passes;
* equivalent SQL wrappers and reversed output row order both pass;
* 17 deliberately faulty implementations receive zero overall.

Five new faults target the added oracles: GROUP BY bag concatenation, HAVING
set union, omission of the unknown HAVING partition, loss of the implicit
empty aggregate group, and moving a SUM predicate to the row stage.

These controls validate acceptance of some correct alternatives and rejection
of representative wrong implementations. They do not prove universal grader
correctness. Actual measured outcomes are recorded in [RUN_REPORT.md](RUN_REPORT.md).
