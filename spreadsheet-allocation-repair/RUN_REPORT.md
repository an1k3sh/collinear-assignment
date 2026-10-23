# spreadsheet-allocation-repair: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `harbor-prototypes-opus-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | None | Infrastructure exception; not failure evidence |
| `harbor-prototypes-opus-02` | `prototype_harness:PrototypeCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./spreadsheet-allocation-repair -a oracle
harbor run -p ./spreadsheet-allocation-repair -a claude -m opus-5-5
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

# Spreadsheet allocation repair

**Short task:** Repair a real Excel workbook whose saved total looks plausible
while its formulas, lookup behavior, cost range and chart disagree.

## Compounding assumptions

* A displayed total is current: the XLSX has manual calculation and stale caches.
* Copy-down formulas are consistent: one cell is pasted, another points to the wrong row.
* A lookup populated a number, so it matched correctly: approximate lookup uses unsorted text IDs.
* New source rows are included: the original cost range excludes the appended bill.
* A nearby chart uses the nearby table: it points to a hidden prior-period sheet.
* Filtered-out rows do not count: the allocation policy includes all April costs.

## Artifacts and deliverable

`environment/app/allocation.xlsx` is a genuine editable workbook with Rates,
Costs, Summary and hidden Legacy sheets, styled inputs and a bar chart. It
contains original synthetic formulas and deliberately stale numeric caches.
The controller note and policy define the required economic result.
Deliver a repaired XLSX with live formulas, current saved values and chart
bindings, plus a short repair report. No Python script is required from the agent.

The original workbook can be regenerated with `author/generate_workbook.py`
using the included openpyxl environment; byte-for-byte ZIP metadata is not a
grading requirement.

## Verification and evidence

Native Harbor oracle: all eight criteria pass. The verifier loads actual XLSX
files and recalculates through LibreOffice in isolated profiles. It changes
weights, reorders the lookup table, renames a department and appends costs as
far as row 1000. It checks saved values, source preservation, formula presence
and editable chart source ranges. It does not demand a particular formula string.

An equivalent SUMIF implementation passes. Truncated ranges, pasted constants,
Legacy chart bindings and approximate lookups fail. Each control is recalculated
before grading so failures are not merely missing formula caches.
One Opus 5.5 high trial with Copilot CLI 1.0.102 passed all eight criteria, overall
1.0, in 3m08s including setup/verification. Trial:
`harbor-prototypes-opus-02/spreadsheet-allocation-repair__E6ndXQV`.
The top-level prompt no longer names the defects; the policy and inspectable
incident evidence remain available. All task/verifier hashes stayed frozen.
See `evidence/model/` for the native trajectory, repaired XLSX and original rewards.

## Reproduce

```sh
harbor run -p ./spreadsheet-allocation-repair -a oracle
harbor run -p ./spreadsheet-allocation-repair -a claude -m opus-5-5
harbor view ./jobs
```

Validated with Harbor 0.24.0. Configure high reasoning for actual model trials;
the second command above is a recipe, not evidence.

The actual Copilot run used `author/prototype_harness.py`, an installation-only
adapter that installs official SHA256-checked Node 22.14.0 if missing and the
official Copilot CLI 1.0.102 npm package. All execution options remain inherited.

```sh
PYTHONPATH="$PWD/author" uvx --from harbor==0.24.0 harbor run -p . \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

An initial setup-only attempt failed because npm was absent; no model or verifier
ran then. That infrastructure failure does not count as model failure. The
successful run uses Copilot CLI, not the assignment's native Claude Code harness.

Author controls, from this task directory:

```sh
docker build -t prototype-sheet:author environment
docker run --rm -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  -v "$PWD/author:/author:ro" prototype-sheet:author \
  sh -c '/solution/solve.sh && python /author/validate_controls.py'
```

## Provenance, resources and limitations

All workbook content and incident evidence are original synthetic material.
External tools: openpyxl 3.1.5 (MIT), et-xmlfile 2.0.0 (MIT), LibreOffice
(MPL/LGPL project licensing), and official Python/Debian runtime packages.
Python image is digest-pinned, Python packages version-pinned, Debian packages
resolved from the fixed 2026-02-01 snapshot. Build needs public package access.
Task execution and verification are offline and use no macros or external links.

This is a small repair prototype, not a demonstrated long-horizon model failure.
It tests normal formulas with LibreOffice compatibility, not arbitrary Excel
features, VBA, pivot models, or visual styling quality. Source rows must remain
intact; charts intentionally must bind to the public Summary output range.
