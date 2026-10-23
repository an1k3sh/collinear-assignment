# Field-service sync repair, revision 2

An original Harbor repair task: an offline field-service application has
cross-layer defects spanning a Python/SQLite service and a JavaScript replica.
It starts successfully and passes its shallow public smoke tests. The candidate
must investigate incidents, repair the actual code, recover a materialized
projection and leave regression tests and a repair report.

Revision 1 passed both completed model trials. This revision adds an existing
but flawed atomic multi-order closeout path and receipt-aware catch-up. The
linked failure modes are partial transactions, imprecise per-entity batch
revision prediction, optimistic double application after lost HTTP receipts,
and rebuilding a retry from a partially confirmed queue.

**Result:** both revision-2 submissions pass all 35 corrected checks. Their raw
native runs returned zero because of two verifier defects, which were diagnosed
and rejected as failure evidence. Raw rewards and corrected replays are retained
separately. No substantive model failure is claimed; see the run report.

## Why this is real work

Offline delivery is common in maintenance, inspections and mobile dispatch.
Duplicate side effects, missing catch-up events and overwritten unsent edits
have direct operational cost. The task joins transaction reasoning, historical
queries, retry identity, optimistic state and crash recovery; a local patch to
one function cannot satisfy the whole workflow.

## Fairness and provenance

All service/client code, incident history, fixtures and tests were created from
scratch for this exercise. The seed is an intentionally flawed original
implementation, not a copied public issue, benchmark or production repository.
External components are the official Node image and bundled Python/SQLite/Node
standard libraries. No external datasets or private services are used.

The public protocol defines identity, rollback, paging, wire integers, delivery
ordering, tombstones, optimistic projection, durable send and repair semantics.
Chaos hooks exist in the seed and are documented. Limits are generous: three
hours for the agent, fifteen minutes for verification. No performance or exact
report-format grading. The environment is digest-pinned and includes Python
3.11.2 and Node 22.14.0; no package installation is required for the task.

The verifier checks behavior using fresh SQLite databases, six independent
writer processes, a generated 100-operation reference replay, 96 client
delivery permutations, file failures and actual HTTP/Node integration. It does
not import oracle implementation code. The immutable incident history is
compared with the delivered database before checking repaired projections.
Core tests compare structured semantics, not source strings or SQL plans.

Reward components: transactions, sync, client, durability, batches, confirmations, integration, recovery
and artifacts. Each is its fraction of passing test cases. Overall is 1 only if
all tests pass. Details and assertion failures are retained separately.

The author control runner demonstrates acceptance of alternate JSON encoding
and rejection of sixteen partial repairs. Source strings in that author-only
runner generate known faulty implementations; they are NOT grading criteria.

## Reproduction

Required standard Harbor entrypoints:

```sh
harbor run -p ./field-service-sync-repair-v2 -a oracle
harbor run -p ./field-service-sync-repair-v2 -a claude -m opus-5-5
harbor view ./jobs
```

The second command is the requested Claude Code recipe, not a claim that this
machine has run that harness. Confirm high reasoning through your provider's
native adapter configuration and retain the resolved trial configuration.

Locally available model-trial configuration:

```sh
uvx --from harbor==0.24.0 harbor run \
  -p ./collinear-candidate/field-service-sync-repair-v2 \
  -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --job-name field-service-sync-v2-opus-01
```

Copilot CLI is not Claude Code. Its results must not be represented as meeting
the assignment's native Claude Code harness requirement.

GitHub release-asset downloads failed in this exercise's environment. The
user-approved `author/sync_harness_npm.py` subclass changes only installation to
the official `@github/copilot@1.0.102` npm package. Model invocation, reasoning,
options and trajectory handling remain inherited unchanged. From this task root:

```sh
PYTHONPATH="$PWD/author" uvx --from harbor==0.24.0 harbor run -p . \
  -a sync_harness_npm:NpmInstalledCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5 -k 2 --job-name sync-v2-pair
```

Direct offline author checks, from this task directory:

```sh
docker build -t field-service-sync:author environment
docker run --rm -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  field-service-sync:author sh -c '/solution/solve.sh && /tests/test.sh'
docker run --rm -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  -v "$PWD/author:/author:ro" field-service-sync:author \
  sh -c '/solution/solve.sh && python3 /author/validate_controls.py'
```

## Limitations

This is a small synthetic service, not a production deployment. There is no
authentication, event compaction, schema migration, UI or power-loss hardware
simulation. File crash tests cover atomic replacement before rename, not disk
controller behavior. Tests are deterministic and finite; passing is evidence
for the documented scenarios, not a formal proof of all possible interleavings.

See [RUN_REPORT.md](RUN_REPORT.md) for trial outcomes. No model failure is claimed
before the raw evidence has been reproduced and checked for ambiguity.
