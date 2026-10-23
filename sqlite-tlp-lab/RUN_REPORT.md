# sqlite-tlp-lab: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `sqlite-tlp-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `sqlite-tlp-v2-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./sqlite-tlp-lab -a oracle
harbor run -p ./sqlite-tlp-lab -a claude -m opus-5-5
harbor view ./jobs
```

The illustrative `claude` alias is provider/version dependent. Harbor 0.24.0 exposes `claude-code` for the native Claude Code harness; supply the actual available model ID, credentials and high reasoning configuration. See the detailed experiment commands below for the measured harness, rather than relabeling historical results.

## Checklist and fairness audit

* The task prompt states input locations, protected boundaries and durable deliverables. Only environment sources are copied into the agent image; reference solutions and tests are staged by Harbor separately.
* Metadata declares category, timeouts, resources and network policy. `public` network permits harness setup/inference; it is not an enforced offline sandbox.
* The Dockerfile pins the base image and declares dependencies. Validation uses fresh Docker containers on macOS Docker Desktop (Linux arm64); other architectures are not certified.
* Both shell entrypoints are executable. The verifier emits reward JSON or text under `/logs/verifier` on graded outcomes. Infrastructure errors must not be interpreted as model defects.
* Functional checks and existing alternate/mutation controls test the task's stated outcomes. A fresh untouched/no-op baseline is checked during collection validation; detailed verifier design and limitations follow below.
* Economic usefulness, long-horizon subgoals and provenance are recorded in the detailed notes. [LICENSES.md](LICENSES.md) inventories external tools and license sources.
* Versioned tasks reuse same-exercise work openly. They are not independent originality claims and are not ports of unrelated existing benchmarks.

## Detailed design and historical experiment notes

# Run report: SQLite TLP Lab, revision 2

## Status and version history

Updated 2026-10-22. Revision 2 adds standalone GROUP BY and HAVING partitioning.
The JSON envelope remains version 1 for backward compatibility; task metadata
and the public contract identify revision 2.

* Revision 1 oracle passed through Harbor.
* Revision 1 Opus 5.5 high through Copilot CLI 1.0.102 passed ALL 22 test methods,
  overall 1.0. This was not failure evidence.
* Revision 2 oracle passed through Harbor, overall 1.0.
* Revision 2 Opus 5.5 high through Copilot CLI 1.0.102 passed ALL 32 test
  methods, overall 1.0. Total job duration was approximately 26m20s;
  agent execution was approximately 20m21s.

Both observed model trials passed. This task has not demonstrated the
assignment's desired frontier-model failure.

The original v1 ZIP and job remain preserved outside this task directory.
No v1 outcome is retroactively graded as a failure under v2 requirements.

## Engineering task

The agent builds a bounded SQL AST compiler, a TLP plan generator, typed
multiset comparison, aggregate recomposition, reproducible case generation,
and a campaign/replay CLI.

Revision 2 covers all ten oracle categories in the cited paper, within the
explicit SQL subset: WHERE, WHERE Extended, GROUP BY, HAVING, DISTINCT,
COUNT, SUM, AVG, MIN, and MAX.

GROUP BY partitions rows before grouping and uses set union across results.
HAVING evaluates predicates after aggregation and concatenates result bags.
Different groups can have identical projections, which must be preserved.
Ungrouped aggregates on empty inputs still form an implicit group.

This is useful database-testing infrastructure: valid generated queries,
sound comparison, meaningful coverage, and reproducible artifacts are
valuable independently of discovering a previously unknown database bug.
The task does not claim to measure vulnerability-discovery rate.

## Reproducible environment

* Harbor 0.24.0; Docker provider.
* Python 3.12.12 slim-bookworm, pinned multi-architecture manifest digest.
* Observed SQLite 3.40.1; Linux aarch64.
* Python standard library only.
* Agent allowance: 3,600 seconds; verifier: 180 seconds.
* Application and verifier need no network or secrets. The author audit also
  passed with Docker `--network none`.
* Container setup and model installation/inference require network access.

Only `environment/app/` is copied into the agent's starting image.
Oracle code, private tests, reports, and prior-run evidence are not exposed.
Other architectures were not separately certified during authoring.

## Scoring, exactly

See [SCORING.md](SCORING.md) and [tests/grade.py](tests/grade.py).

The 32 candidate test methods comprise 9 validity, 10 completeness, 10 diversity,
and 3 artifact families. Each family passes only if every subcase passes.

Overall is zero unless:

1. All validity and completeness families pass.
2. Non-vacuous partition occupancy meets the public thresholds.
3. Fresh replay passes.
4. CLI mismatch/error handling passes.

Otherwise:

```
overall = round(0.45 * completeness
              + 0.35 * diversity
              + 0.20 * artifact_quality, 6)
```

Full success requires 1.0. Completeness is also a gate, so its 45% contribution
is fixed when the gate opens. This avoids giving a useful-looking score to an
unsound query oracle. Subscores remain diagnostic even when overall is zero.

No judge model, exact SQL formatting, source similarity, or new-bug discovery
contributes to the score.

### Input-validity diagnostics added after the trial

Only after the v2 trial ended, diagnostics revision 1 added
`oracle_correctness` (an alias for legacy `validity`) and
`input_validity_rate`. The overall formula and gates are unchanged.

Measured against the saved v2 Opus implementation, independently of its
reported comparison outcomes:

| Measurement | Result |
|---|---:|
| Requested cases | 448 |
| Emitted cases | 448 |
| Schema-valid cases | 448 |
| Executable cases | 448 |
| Input validity rate | 1.0 |
| Recorded generation/schema/execution errors | 0 |

This means the emitted cases obeyed the schema and all four SQL queries
executed. It does not independently establish TLP soundness or bug-finding
yield. Mismatches are not classified as invalid inputs.

Five new author tests validate the diagnostic, including partial failure
rates, short generation, explicit error records, denied writes, and valid
inputs whose results differ.
The updated grader passed a further Harbor oracle trial with every reported
metric at 1.0. The complete positive/negative audit was repeated offline after
the diagnostics change: both correct alternatives still passed and all
17 faulty implementations still received zero overall. Retrospective Opus
measurement used the pinned Python 3.12.12 / SQLite 3.40.1 container.

The original [v2 rewards](evidence/v2-copilot/reward.json) are untouched.
The [retrospective measurement](evidence/v2-copilot/post-run-input-validity.json)
is explicitly separate.

## Grading validation

Measured before the model retry:

| Control | Overall |
|---|---:|
| Untouched scaffold | 0.0 |
| Oracle | 1.0 |
| Equivalent derived-table SQL wrapper | 1.0 |
| Equivalent reversed result ordering | 1.0 |
| Each of 17 faulty implementations | 0.0 |

These outcomes were repeated locally and in a network-disabled container.
Three author-side unit tests additionally check score arithmetic, every gate
failure/missing result, and partial-credit weighting.

The 17 negative controls include the twelve v1 faults plus:

* GROUP BY bag concatenation rather than set union.
* HAVING set union that erases identical projections.
* Missing the unknown HAVING partition.
* Losing the implicit empty aggregate group.
* Applying a SUM predicate to rows before aggregation.

The final case runs valid SQL but implements the wrong transformation, so it
checks substantive semantics rather than just syntax rejection.

Independent reference SQL covers 219 fixtures. Each compiled plan is checked
against both its original data and changed data, preventing baked answers.
Hand-calculated witnesses validate both candidate results and the reference
queries. Composition is also checked without SQLite using synthetic states.
Generator diversity is measured using actual SQL on four 112-case campaigns.

Evidence:

* [v1 passing Copilot trial](evidence/v1-copilot/trial-result.json)
* [v2 passing Copilot trial](evidence/v2-copilot/trial-result.json)
* [v2 verifier output](evidence/v2-copilot/verifier.log)
* [v2 agent trajectory](evidence/v2-copilot/trajectory.json)
* [v2 Harbor oracle](evidence/v2-harbor-oracle/trial-result.json)
* [v2 offline grader audit](evidence/v2-author/summary.json)
* [frozen v2 file hashes](evidence/v2-frozen-files.json)
* [post-diagnostic audit](evidence/v2-diagnostics-author/summary.json)
* [post-diagnostic Harbor oracle](evidence/v2-diagnostics-oracle/trial-result.json)

Acceptance of two alternative implementations and rejection of representative
faults improve confidence but do not prove universal grader correctness.
This is a cooperative coding benchmark, not a hardened hostile-code sandbox.

## Model trial commands and interpretation

From the workspace root, the requested retry uses the same harness/version as
the user's v1 attempt:

```sh
GH_TOKEN="$(gh auth token)" \
uvx --from harbor==0.24.0 harbor run \
  -p ./collinear-candidate/sqlite-tlp-lab \
  -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --job-name sqlite-tlp-v2-copilot-opus-01
```

Credentials must never be saved in the package. The command assumes a token
authorized for Copilot and access to the specified model.

**Copilot CLI is not Claude Code.** Even a substantive failure in this retry
is not evidence of failure with the assignment's requested Claude Code harness.
Approval or an additional native Claude Code trial is needed for that claim.

The completed trajectory metadata confirms `claude-opus-5.5`, high effort,
and Copilot CLI 1.0.102. There were no Harbor trial exceptions.

From the directory containing the task, the assignment commands are:

```sh
harbor run -p ./sqlite-tlp-lab -a oracle
harbor run -p ./sqlite-tlp-lab -a claude -m opus-5-5
harbor view ./jobs
```

The second is assignment shorthand. Harbor 0.24.0 uses `claude-code`, and a
provider-provisioned model ID is required:

```sh
harbor run -p ./sqlite-tlp-lab -a claude-code -m claude-opus-5-5 \
  --ak reasoning_effort=high --job-name sqlite-tlp-v2-claude-native
```

## Fairness and limitations

The new modes, aggregate expression grammar, grouping restrictions, oracle
layouts, and generator thresholds were disclosed before the retry. The oracle,
negative controls, and positive controls passed before the target was launched.
The task and grader are frozen during the trial.

The SQL grammar intentionally excludes floating-point input, overflow,
arbitrary collations, windows, nondeterminism, and unsupported bare columns.
It is not full SQL or a replacement for SQLancer.

Passing or failing one trial is an observation about that run, not a reliable
failure-rate estimate. No difficulty or failure claim is made solely from
the task's added complexity.

## Provenance

TLP is established prior art: OOPSLA 2020,
[DOI 10.1145/3428279](https://doi.org/10.1145/3428279).
[SQLancer](https://github.com/sqlancer/sqlancer) is background, not vendored
source or an implementation dependency.

The bounded AST, scaffold, task contract, generated fixtures, oracle, verifier,
and audit were created for this exercise. No public
benchmark task or public bug fix was ported. Original code is MIT-licensed.
Python, SQLite, Harbor, and the container retain their own licensing.
