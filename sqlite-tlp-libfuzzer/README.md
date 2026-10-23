# SQLite TLP with C++ and libFuzzer

This Harbor task asks an agent to implement a real C++17 libFuzzer target for
SQLite ternary logic partitioning. It replaces the previous Python-generator
approach with byte-driven database/AST generation, sanitizer-instrumented native
execution, input counterfactuals, and independent SQL validation.

Measured status: the oracle and Claude Opus 5.5 high (Copilot CLI 1.0.102) both
passed with overall 1.0. This task has not demonstrated a frontier-model
failure. See [the run report](RUN_REPORT.md) for the frozen trial evidence.

The intended workflow is realistic database QA: generate a database and query,
derive equivalent partitions, execute and compare, then replay failing bytes.
The difficult work is in composing sound transformations across joins,
aggregates and grouping while preserving NULLs, duplicates and weighted states.
The benchmark does not depend on discovering an unknown SQLite vulnerability.

## Deliverable and layout

* [instruction.md](instruction.md): agent assignment.
* [environment/app/docs/contract.md](environment/app/docs/contract.md): complete
  schema, interfaces, semantic rules, public thresholds and score gates.
* [environment/app/harness/](environment/app/harness/): protected libFuzzer,
  SQLite, JSON-line inspection and replay implementation.
* [environment/app/src/](environment/app/src/): unimplemented candidate files.
* [solution/](solution/): passing C++ oracle, not present in the agent image.
* [tests/verify.py](tests/verify.py): independent SQL/schema verifier.
* [SCORING.md](SCORING.md): how real diversity and correctness are measured.
* [RUN_REPORT.md](RUN_REPORT.md): measured results, limitations and evidence.

The submission ZIP contains exactly this one task directory. The earlier
`sqlite-tlp-lab` Python task and its passing model trials are preserved outside
this submission; they are not C++ model-run evidence.

## Reproduce

Use Docker and Harbor 0.24.0. From the directory containing this task:

```sh
uvx --from harbor==0.24.0 harbor run -p ./sqlite-tlp-libfuzzer -a oracle
uvx --from harbor==0.24.0 harbor run -p ./sqlite-tlp-libfuzzer -a claude -m opus-5-5
uvx --from harbor==0.24.0 harbor view ./jobs
```

The second command is the assignment's model/harness spelling; availability,
provider credentials and the high-effort setting must be confirmed in the
actual trial metadata. No Claude Code trial has been run for this C++ task.
To run the locally available Copilot harness instead:

```sh
GH_TOKEN="$(gh auth token)" uvx --from harbor==0.24.0 harbor run \
  -p ./sqlite-tlp-libfuzzer -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102
```

Copilot CLI is not Claude Code. A Copilot result must not be relabeled as a
Claude Code result. Model installation and inference require network and
credentials; application, verifier and author audits run offline.

Build and audit locally from this task directory:

```sh
docker build -t sqlite-tlp-libfuzzer:author environment
mkdir -p local-evidence
docker run --rm --network none \
  -v "$PWD:/submission:ro" -v "$PWD/local-evidence:/evidence" \
  sqlite-tlp-libfuzzer:author \
  python /submission/tests/author_check.py --out /evidence
docker run --rm --network none -v "$PWD:/submission:ro" \
  sqlite-tlp-libfuzzer:author \
  python -m unittest discover -s /submission/tests -p 'test_*.py' -v
```

Build dependencies are pinned through an immutable base-image digest, exact
package versions and a dated Debian snapshot. Network is needed for the first
image build; thereafter the code uses installed Clang/libFuzzer, SQLite,
nlohmann JSON, CMake and Python's standard library. Validation was performed
on Linux arm64 under Docker; other architectures have not been certified.

## Provenance

Created for this exercise, not ported from a public benchmark or bug issue.
The C++ harness, oracle generator/engine, diversity measurements, counterfactual
tests and negative controls were authored for this task. The bounded case
schema and independent reference fixtures are adapted from this exercise's
earlier, unpublished Python TLP task from the same exercise.

The established TLP technique is from *Finding Bugs in Database Systems via
Query Partitioning*, OOPSLA 2020, DOI
[10.1145/3428279](https://doi.org/10.1145/3428279). The paper's or SQLancer's
implementation was not copied. External runtime dependencies retain their
upstream licenses: SQLite is public domain, nlohmann JSON is MIT, and LLVM
uses Apache-2.0 with LLVM exceptions. No external dataset is required.
