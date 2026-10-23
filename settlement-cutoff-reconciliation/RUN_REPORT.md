# settlement-cutoff-reconciliation: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `harbor-prototypes-opus-01` | `sync_harness_npm:NpmInstalledCopilot` / `claude-opus-5.5` | None | Infrastructure exception; not failure evidence |
| `harbor-prototypes-opus-02` | `prototype_harness:PrototypeCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./settlement-cutoff-reconciliation -a oracle
harbor run -p ./settlement-cutoff-reconciliation -a claude -m opus-5-5
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

# Settlement and cutoff reconciliation

**Short task:** Replace an apparently balanced April close with a traceable
reconciliation of processor deposits, reserve balances and invoice aging.

## Compounding assumptions

* Matching a deposit to gross sales explains it: fees/refunds/reserves matter.
* Settlement IDs are globally unique: two merchants reuse B-17.
* The last export contains only cutoff-known facts: revisions arrive in May.
* A credit reduces receivables: one is still a draft.
* An old invoice is overdue: payment terms start at acceptance, not issue.
* Leading zeros are cosmetic: two distinct invoices would be merged.

## Artifacts and deliverable

Seven structured data files include processor event revisions, bank lines,
invoice allocations, invoice acceptance dates, opening reserves and the cutoff.
A controller email and misleading draft-close CSV provide realistic context.
The deliverable is a reusable reconciliation script plus settlement/aging CSVs,
summary JSON and an explanation of unresolved differences.

## Verification and evidence

Native Harbor oracle: all six criteria pass. A separate SQLite/window-function
reference checks the loop-based oracle independently. Five replay variants test
row reordering, renamed IDs, scaled amounts, a later cutoff, revised terms and
future-effective latest revisions. Each variant runs twice to check replacement.
Alternative JSON formatting passes. Draft-credit application, cross-merchant
collision and future-knowledge leakage controls fail. See `evidence/`.

One Opus 5.5 high trial with Copilot CLI 1.0.102 passed all six criteria, overall
1.0, in 3m50s including setup/verification. Trial:
`harbor-prototypes-opus-02/settlement-cutoff-reconciliation__3v6fdqW`.
Diagnostic hints were removed from the top-level prompt before freezing;
required policy and inspectable evidence remained available. All frozen hashes
were unchanged afterward. This is a prototype, not demonstrated failure evidence.

## Reproduce

```sh
harbor run -p ./settlement-cutoff-reconciliation -a oracle
harbor run -p ./settlement-cutoff-reconciliation -a claude -m opus-5-5
harbor view ./jobs
```

Validated with Harbor 0.24.0. The model command is only a recipe; configure high
reasoning through the native adapter for an actual model trial.

The recorded trial used `author/prototype_harness.py`, which changes only setup
to install official SHA256-checked Node 22.14.0 if needed and Copilot CLI
1.0.102 from npm. Model execution remains Harbor's inherited Copilot invocation.

```sh
PYTHONPATH="$PWD/author" uvx --from harbor==0.24.0 harbor run -p . \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

An earlier missing-npm setup failure reached neither model nor verifier and is
not model-failure evidence. Native successful results and submission are in
`evidence/model/`. Copilot CLI is not native Claude Code.

Author controls, from this task directory:

```sh
docker build -t prototype-settlement:author environment
docker run --rm -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  -v "$PWD/author:/author:ro" prototype-settlement:author \
  sh -c '/solution/solve.sh && python /author/validate_controls.py'
```

## Provenance and limitations

All amounts, counterparties, policies and records are newly authored synthetic
fixtures. No external financial data is used. Runtime: digest-pinned official
Python image, standard libraries only. Build/model harness acquisition needs
network; calculations and verification do not. Scope is USD, calendar-day terms
and valid linked input universes, not tax advice, FX accounting or a full ledger.
