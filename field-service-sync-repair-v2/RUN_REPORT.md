# field-service-sync-repair-v2: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `field-service-sync-v2-pair-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 0.0 | Historical raw result; consult detailed fairness analysis, not automatically a model failure |
| `field-service-sync-v2-pair-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 0.0 | Historical raw result; consult detailed fairness analysis, not automatically a model failure |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./field-service-sync-repair-v2 -a oracle
harbor run -p ./field-service-sync-repair-v2 -a claude -m opus-5-5
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

# Run report: revision 2

## Author validation

The pinned container builds and reports Python 3.11.2 and Node 22.14.0.
The seed's Python and Node public smoke tests pass.
Revision 1 passed both completed trials in `field-service-sync-pair-02`, with
all 24 tests and every component at 1.0. No failure is claimed for that revision.
This separate revision implements the user's policy: harden only after two
complete passes, then run a new frozen pair.

New requirements cover atomic multi-order closeouts, durable batch retry,
transaction-local revision prediction and historical confirmations that retire
pending intents before delayed HTTP receipts. All semantics are public.

The first direct revision-2 oracle run passed all 35 tests. The verifier retains
revision-1 coverage and adds server/client/batch/confirmation and real HTTP probes.
The author control suite adds four new faulty variants to the twelve prior
controls, plus an accepted alternative JSON encoding.

The source task is being validated before model trials. This file will retain
every result, including rejected infrastructure/ambiguity failures. Two
model-reaching runs remain in the five-run budget after revision 1's interrupted
execution and two passes. Three install-only failures do not consume that budget,
as explicitly authorized by the user.

## Model evidence

Both trials in `field-service-sync-v2-pair-01` completed without exceptions:
`ehKUT6K` and `tX5R9v2`. They used official Copilot CLI 1.0.102, Opus 5.5 high,
with the user-approved npm installer-only Harbor override. It is NOT Claude Code.
The job reported 27m52s.

Both raw rewards were overall 0.0 (32/35 tests passed). These are NOT valid
model-failure evidence. Inspection found two verifier defects:

1. HTTP tests constructed a handler/server directly, depending on the seed's
   private initialization. Both candidates legitimately moved Store construction
   into the documented CLI startup. The verifier bypassed startup, causing
   `AttributeError: ... has no attribute 'store'` and two false HTTP failures.
   Correction: start `python3 -m server.http --db PATH --port PORT` in a subprocess
   and test the real public endpoint.
2. The snapshot-interleaving probe acknowledged an intent that had never been
   sent and used revision history inconsistent with that intent's base. Both
   candidates rejected the impossible receipt. Correction: SEND before staging,
   then use causally consistent snapshot, commit, newer push and delayed ACK.
   The original assertions about atomic staging, later edits and replay remain.

The original verifier, frozen hashes, native trajectories and raw rewards were
preserved BEFORE either correction. No candidate implementation was changed.
Both recovered submissions were then replayed in fresh containers against the
corrected verifier: **35/35 tests passed, every component 1.0**. The oracle also
passes the corrected verifier. These are post-trial corrected replays, not new
native model runs, and must not overwrite or be confused with the raw rewards.

## Conclusion and budget

No substantive failure demonstrated. Revision 1 has two native full passes;
revision 2 has two corrected full passes after rejected verifier false positives.
The five authorized model-reaching executions are now consumed: one interrupted
revision-1 run, two revision-1 passes and two revision-2 runs. Three additional
launches failed during installation before any model invocation and were
excluded with user approval. Further inference requires a budget extension.

The included evidence preserves original-versus-corrected outcomes separately.
The task remains a solvable, original repair exercise, but this release is NOT
a successful frontier-model-failure benchmark.
