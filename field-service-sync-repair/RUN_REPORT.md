# field-service-sync-repair: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `field-service-sync-pair-01` | `copilot-cli` / `claude-opus-5.5` | None | Infrastructure exception; not failure evidence |
| `field-service-sync-pair-02` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `field-service-sync-pair-02` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./field-service-sync-repair -a oracle
harbor run -p ./field-service-sync-repair -a claude -m opus-5-5
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

# Run report

## Author validation

The pinned container builds and reports Python 3.11.2 and Node 22.14.0.
The seed's Python and Node public smoke tests pass.
The first direct oracle run passed all 23 behavioral tests and all reward groups.
An immutable-input check then brought the suite to 24 tests. Native Harbor
oracle job `field-service-sync-oracle-01` passed every reward component.

The buggy seed passed both public smoke tests but failed 22 of the initial 23
verifier tests. Its overall reward was zero; this is an author negative control,
not a target-model failure.

All thirteen controlled variants were classified correctly: alternate valid
JSON encoding passed; twelve partial repairs failed. The bad variants covered
receipt scope/digest, partial commit, moving snapshot cut, inclusive pull,
unsafe integer comparison, deleting later edits, receipt checkpoint advancement,
lost staged pushes, stale snapshot merge, late persistence and incomplete repair.

The source task is being validated before model trials. This file will retain
every model result, including passes and rejected infrastructure/ambiguity
failures. The authorized budget for this repair pivot is five model trials.

## Model evidence

Both completed trials in `field-service-sync-pair-02` passed all 24 tests and
every reward component (overall 1.0). Trial IDs: `T6gwtPa` and `bFzwH7V`.
There is no demonstrated model failure for this revision.

Before that pair, one model execution was interrupted by host SIGTERM and three
launches failed during harness installation. None is valid failure evidence.
The installer failures were a timeout and two truncated GitHub release downloads.
Installing the same official Copilot CLI 1.0.102 via npm succeeded. With user
approval, a subclass changed ONLY Harbor's install method to use npm; inherited
model invocation, options and trajectory processing were unchanged. Model was
`claude-opus-5.5`, high reasoning, using Copilot CLI rather than Claude Code.

All raw jobs and frozen hashes were retained. The completed pair's Harbor output
showed 25m53s progress but 2h5m19s total runtime; the discrepancy is not interpreted
as a capability failure. Per-trial timestamps remain in raw results.

Following the user's two-pass escalation policy, revision 2 adds atomic closeouts
and authoritative catch-up confirmations in a separate task directory.
