# SQLite TLP Lab, revision 2

One original Harbor coding task: build a reliable, reproducible SQLite
Ternary Logic Partitioning tester. No newly discovered database bug is needed.
The agent implements a structured SQL compiler, aggregate state merger,
type-sensitive multiset oracle, stratified generator, campaign CLI, and
portable replay. Revision 2 adds the paper's standalone GROUP BY and HAVING
oracles, bringing the bounded support matrix to all ten oracle families.
The SQL subset remains restricted; this is not complete SQL support.

Both recorded Opus 5.5 high trials (v1 and v2, Copilot CLI 1.0.102) passed.
This package therefore does not demonstrate frontier-model failure. Copilot
CLI also differs from the assignment's requested Claude Code harness.

## Why this task

Database-testing infrastructure is useful only when it produces valid,
non-vacuous tests and trustworthy failure reports. This task evaluates that
engineering work, rather than rewarding chance discovery of an unknown bug.
Its linked subgoals are:

1. inspect a bounded SQL/AST and executor contract;
2. compile baseline and three-way partition queries;
3. preserve duplicate, NULL, join, grouping, and aggregate semantics;
4. generate independently measured structural and semantic diversity;
5. save and replay complete test states.

The supported SQL subset deliberately excludes undefined ordering,
nondeterministic functions, integer overflow, arbitrary SQL parsing, and
floating-point inputs. Seeds and test data vary, but every graded feature
and coverage threshold is public in [the contract](environment/app/docs/contract.md).

## Contents and visibility

Only `environment/app/` is copied into the agent image. `solution/`, `tests/`,
this report, and author evidence are not agent starting files. Public examples
are not an exhaustive conformance suite. The task does not vendor SQLancer
or expose its own reference implementation.

The environment uses a Python image pinned by manifest digest and the included
SQLite/standard library; no application package installation is required.
Image pulling and native agent installation/inference require network access.
Application runs and verification do not.

## Reproduce

Use Docker Desktop/Linux containers and Harbor 0.24.0. From the parent
directory, the assignment's requested commands are:

```sh
harbor run -p ./sqlite-tlp-lab -a oracle
harbor run -p ./sqlite-tlp-lab -a claude -m opus-5-5
harbor view ./jobs
```

The second command is assignment shorthand, not a claim that every Harbor
release accepts those names. Harbor 0.24.0 uses the `claude-code` agent.
Use a model identifier actually provisioned by your endpoint:

```sh
harbor run -p ./sqlite-tlp-lab -a claude-code -m claude-opus-5-5 \
  --ak reasoning_effort=high --job-name sqlite-tlp-opus-high
```

Confirm model/effort support in your installed harness. Do not silently
substitute a different model or harness. Provider credentials belong in the
execution environment, never in this task package.

If Harbor is not installed:

```sh
uvx --from harbor==0.24.0 harbor run -p ./sqlite-tlp-lab -a oracle
```

For an offline container-level oracle check, from this task directory:

```sh
docker build -t sqlite-tlp-lab:local environment
mkdir -p evidence/container-oracle
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" \
  -v "$PWD/tests:/tests:ro" \
  -v "$PWD/evidence/container-oracle:/logs/verifier" \
  sqlite-tlp-lab:local sh -c '/solution/solve.sh && /tests/test.sh'
```

Author validation uses fresh temporary workspaces for each candidate:

```sh
python3.12 tests/author_check.py --out evidence/author
```

It runs the untouched scaffold, oracle, and deliberately incorrect variants.
It does not modify the starting environment. These mutations are tests of
the grader, **not frontier-model trials**.

## Verifier

`tests/test.sh` writes a zero reward before importing candidate code.
The grader reports validity, completeness, diversity, artifact quality, and
overall. All correctness tests, non-vacuous partition occupancy, fresh replay,
and CLI mismatch/error handling must pass before diversity/artifact points
count. Overall 1.0 requires every component to pass.

Post-trial diagnostics additionally report `oracle_correctness` as a clearer
alias for `validity`, and `input_validity_rate` as an actual emitted-case
percentage. Counts and errors are written to `input-validity.json`. These
diagnostics do not change the weighted score or rewrite prior trial results.

Independent checks include:

* direct SQL baselines and per-partition checks on varied fixtures, including
  GROUP BY set union and HAVING bag concatenation;
* execution against changed tables after compilation, rejecting baked answers;
* synthetic aggregate states, independent of SQLite;
* comparator tests preserving multiplicity, types, NULLs, and row width;
* executor fault injection and database cleanup after exceptions;
* actual SQL measurements of generator diversity over four seeds;
* portable replay and CLI tests, including induced mismatches and errors;
* checksums for protected public contract/runtime files.

See [SCORING.md](SCORING.md) for the exact gates, weights, test-family counts,
and author validation commands.

The verifier makes no model calls. This is a cooperative coding benchmark,
not a hardened sandbox against adversarial candidate code that attacks the
grader itself.

## Provenance

The scaffold, AST, task prompt, generator, oracle, conformance fixtures,
mutation audit, and grading design were authored for this exercise. No public issue, benchmark task, or SQLancer source was
ported.

TLP itself is established prior art:

* [OOPSLA 2020 paper, DOI 10.1145/3428279](https://doi.org/10.1145/3428279)
* [SQLancer](https://github.com/sqlancer/sqlancer): background on SQL generation
  and metamorphic testing; not bundled or used as an implementation dependency.

External infrastructure: Python (PSF license), SQLite (public domain), official
Python/Debian container components (their respective licenses), and Harbor.
Original task code is MIT-licensed; see [LICENSE](LICENSE).

See [RUN_REPORT.md](RUN_REPORT.md) for measured outcomes and limitations.
