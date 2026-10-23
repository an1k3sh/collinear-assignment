# field-service-sync-repair-v3: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `field-service-sync-v3-pair-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `field-service-sync-v3-pair-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./field-service-sync-repair-v3 -a oracle
harbor run -p ./field-service-sync-repair-v3 -a claude -m opus-5-5
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

# Run report: revision 3

## Author validation

The pinned runtime provides Python 3.11.2 and Node 22.14.0. The direct oracle
passes all 45 tests, including new retained-baseline, cursor-expiry, rollback,
writer-race, generated pruning, recovery-mode and end-to-end HTTP probes.
The author control suite correctly classified one valid alternative and twenty
faulty variants. Native Harbor source and fresh-archive oracles both passed.

## Prior revisions and rejected false positives

Revision 1: two native full passes (24/24).
Revision 2: two corrected full passes (35/35). Its raw native rewards were zero
because the HTTP verifier bypassed documented CLI initialization and a client
trace acknowledged an unsent intent with inconsistent revision history.
Those false positives were rejected, not presented as model failures.
Original rewards and corrected unchanged-submission replays remain preserved
in the separately packaged revision 2.

This revision retains both corrections and adds realistic compaction/recovery
behavior rather than counting stricter private implementation assumptions.

## Revision-3 trials and budget

The user explicitly authorized a harder revision and two more trials after the
five initial model-reaching runs were consumed. Both completed with no exceptions:

| Trial | Tests | Overall | Elapsed |
|---|---:|---:|---:|
| `SDqsZnr` | 45/45 | 1.0 | 19m33s |
| `tD3r8y6` | 45/45 | 1.0 | 20m27s |

Job: `field-service-sync-v3-pair-01`. Every component in both trials was 1.0.
Resolved model configuration was `claude-opus-5.5`, high reasoning, Copilot CLI
1.0.102 with the disclosed installation-only npm override. This is not the
assignment's native Claude Code harness.

All 38 frozen source hashes remained unchanged through both trials. The release
includes native trajectories, configurations, original rewards, verifier
assertion results and repaired candidate submissions. No grader changes were
needed for these outcomes.

## Conclusion

**No substantive model failure.** This revision is another genuine 2/2 pass.
The added compaction, retained history, cursor expiry and durable recovery did
not defeat the model. Increasing the feature checklist has not yet produced the
requested capability failure.

The two additional authorized model executions are consumed. Further inference
requires another budget extension. Prior revisions and all unsuccessful
experiments remain preserved; no pass is omitted to manufacture a failure rate.
