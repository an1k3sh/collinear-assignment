# stockroom-carrier: run report

## Validation notes

Corrected the missing-output-parent verifier case to accept valid preflight rejection before any carrier call. Once an attempt occurs, the existing external-effect preservation checks still apply. The historical 258/259 zero is a false positive, not a model failure.

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `stockroom-carrier-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 0.0 | Historical raw result; consult detailed fairness analysis, not automatically a model failure |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./stockroom-carrier -a oracle
harbor run -p ./stockroom-carrier -a claude -m opus-5-5
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

# Stockroom Carrier: local rollback is not external cancellation

## Status and experiment history

This is a separately versioned, newly authored construction task. The earlier
Stockroom Savepoints and Stockroom Durable tasks and their graders are preserved.
Opus 5.5 high passed those revisions: respectively 134/134 and 204/204 checks.
A separate post-trial audit found two defects in the old durable oracle, not in
the model: serialization-tag collisions and Python's decimal-digit ceiling.
Both are corrected and regression-tested in this new revision only.

The carrier revision's offline oracle preflight passed 257/257 checks and all
three public smoke tests. The finalized suite adds immutable-service integrity
and an explicit same-SKU routing witness, for **259 checks**. Nine independently
introduced semantic mutants were rejected. The unimplemented baseline passes
only the immutable-service check: **1/259**, overall reward 0.

The native Harbor oracle trial passes **259/259**, with all seven rewards 1.0,
zero exceptions, and a total job duration of approximately 2m15s. Its exported
artifacts include both local deliverables and the actual carrier database.
The completed exploratory Opus 5.5 high / Copilot CLI trial,
`stockroom-carrier-copilot-opus-01`, has a raw score of **258/259**, overall reward
**0.0**, external consistency **54/55**, and all other component rewards **1.0**.
It completed in approximately **21m40s** total, including approximately **19m16s**
of agent execution, with zero harness exceptions. All **35** evaluated files
remain byte-identical to their pretrial freeze.

**The only failed check is a verifier false positive, not a substantive model
failure.** It assumes the interpreter must execute a shipment before noticing
that the output parent directory does not exist. The public contract requires
IO for that path but does not prohibit early path validation. The model safely
rejects the bad destination before executing any shipment. That does not undo
an acceptance; no acceptance occurred.

A fresh offline replay reproduces exactly 258/259 and passes all three public
smoke tests. A separate post-trial probe injects an actual IO failure at result
replacement, after the carrier call. **Both model and oracle pass:** the
acceptance and attempt remain durable, and both preexisting output/checkpoint
files remain unchanged. The raw score is retained without retroactive edits.

There is **no demonstrated substantive frontier-model failure for this revision**.
The frozen task is an auditable experiment, **not a submission-ready fair
failure case** until the invalid verifier check is corrected in a new version.
Do not present either previous pass, an author implementation defect, an
authentication problem or a setup failure as a model failure.

## Hypothesis and realism

The authoring hypothesis is:

> A competent implementer might assume a rolled-back transaction undoes its
> shipment, but an independently accepted carrier request survives local
> rollback. Carrier receipts and stable request keys distinguish the states.

The public prompt does not give the incident-specific answer. It explicitly
documents the general protocol: timeouts can occur before or after acceptance,
external acceptance is irreversible, and local continuations do not rewind it.
The candidate must establish what happened using the live service, source
observations, request histories, local holds and execution results.

This reflects ordinary fulfillment operations: a worker can lose a response
after dispatch acceptance, restart from a checkpoint, or abandon an enclosing
approval transaction. Incorrect retries can dispatch twice; an incorrect
rollback assumption can debit the wrong warehouse or omit fulfillment.
Reconciling an imported receipt without a local record is economically useful
work, not an artificial parsing puzzle.

The linked subgoals are a typed imperative interpreter, local transactions and
error recovery, portable cross-process continuations, stable external
idempotency, a reusable recovery workflow, and a verified operational handoff.
The deliverable includes code, completed local state, replayable checkpoints,
the actual service database and an evidence-backed report.

## Task and environment

The candidate starts with a CLI skeleton, language specifications, business
workflow signatures, two fixed incident drivers, inventory files, observation
logs, and three incomplete public smoke tests. No reference implementation or
private verifier is copied into the candidate image.

Python 3.12.12 slim-bookworm is pinned by digest in the Dockerfile. The language,
carrier, oracle and verifier use only the standard library. The carrier is a
local SQLite stand-in with deterministic response-loss policies: acknowledge,
accept then time out once, time out before acceptance once, and reject.
There are no network services, random delays, clocks, threads, credentials or
runtime downloads in the task itself. Harbor/harness setup and model inference
may use network; task metadata states this distinction.

The allowance remains two hours, 2 CPUs and 2048 MiB RAM. Time pressure is not
the intended failure mechanism. The verifier has 600 seconds.

## Fairness and specification

All consequential rules are public in `environment/app/docs/`:

* the base grammar, types, procedure binding, counters and diagnostics;
* rollback of local inventory, holds, bindings, events and delivery bookkeeping;
* independently committed carrier acceptance and attempts;
* opaque receipts and exact ordered payload binding to stable request keys;
* explicit IO versus recoverable carrier/domain errors;
* fresh-process checkpoints with a canonical integrity envelope;
* identity binding to stable service ID, not database hash or filesystem path;
* replay against a live, possibly advanced carrier;
* transactional local delivery recording and locally idempotent dispatch;
* required reserved and posted operational pauses;
* atomic output/checkpoint publication, without undoing external effects.

The incident diagnosis remains implicit. The simulator's implementation and
database read schema are inspectable. Accepted fixture receipts need not have
the simulator's generated spelling. Same-SKU lines must aggregate their demand.
Positive quantities remain arbitrary-precision integers; carrier SQL storage
uses decimal text and the API returns Python integers.

No implementation strategy, helper architecture, checkpoint internal layout,
number of local rollback attempts, exact workflow statement count or report
wording is graded. The verifier accepts lookup-based recovery or bounded
same-key retries. It does not demand a literal string in a trajectory.

## Independent verifier and controls

### Post-trial verifier defect

`publication-preserves-external-effect` in the frozen suite invokes a program
with a nonexistent output parent, then requires an accepted carrier record.
That expectation adds an unstated execution-order restriction. The model's
publication-path preflight is valid under the public specification.

The oracle executes first and only then attempts publication; the model
preflights first. Both return IO and preserve output/checkpoint bytes. This is
an author test-design error, not incorrect carrier reconciliation.

The separate `evidence/posttrial-publication-audit/probe.py` patches `os.replace`
only for the result destination in an author-controlled fresh process. Its
initial destination is valid, so the carrier request executes before the
injected EIO. Model and oracle both preserve the already accepted request.
This is supplemental fault-injection evidence, not part of the frozen grader
or a change to the candidate environment.

A subsequent version should replace the missing-parent assumption with a
genuine late-publication fault-injection check, and allow legitimate preflight
rejection. Do not silently change this trial's grader or relabel its raw result.

`tests/test.sh` writes `reward.json` and detailed per-check `checks.json`.
Overall reward is 1 only if all checks pass. Component rewards additionally
expose language/inventory/workflow correctness, constraints, robustness,
durability, external consistency and deliverable quality.

The 204 inherited checks cover grammar/static validation, expressions, scopes,
procedure/control-flow unwinding, nested transactions, reservations, publication,
generated fulfillment streams, integrity failures, and fresh-process durability.
Only the documented checkpoint identity extension was adjusted for this revision.

The 55 carrier checks add:

* hand-worked before/after-timeout and rollback witnesses;
* deduplication, conflict handling and preserved request audit history;
* validation before service calls and before local ledger mutation;
* fatal interpreter/publication errors after independently committed effects;
* external-expression evaluation order and short circuit;
* missing/corrupt/unidentified services and file-alias rejection;
* service relocation, advanced history, and different identity rejection;
* stale checkpoint replay without duplicate physical acceptance;
* local delivery rollback, resume and reapplication;
* imported opaque receipts and original-warehouse authority;
* unrelated existing holds and aggregate same-SKU routing;
* twelve fixed-seed generated order streams with mixed policies/repeated keys;
* two old-reference regressions, incident outputs and immutable service integrity.

Expected stock, holds, order routing, delivery membership and event payloads
come from hand witnesses or a small independent aggregate workflow model.
Opaque receipt values are compared with actual service records, never guessed
from UUID spelling. The verifier does not import the oracle interpreter.
It uses the supplied immutable carrier API solely as the environment service.

Nine negative controls reject these plausible wrong implementations:

1. keeping local delivery records after rollback;
2. erasing external acceptance and attempts on rollback;
3. binding checkpoints to a mutable database hash;
4. substituting a new retry key;
5. preferring current routing over an accepted warehouse;
6. treating a timeout as rejection;
7. removing the local idempotency guard;
8. failing to aggregate same-SKU demand;
9. omitting the required posted boundary.

The module hash check enforces an explicit immutable-environment constraint,
not a candidate-source style requirement. A skeleton retaining the environment
passes that check alone and earns overall 0.

## Reproduction

Evidence retained in this directory:

* `evidence/pretrial-freeze.json`: all 35 evaluated file hashes;
* `evidence/oracle/`: native Harbor reward/checks/result and exported source,
  checkpoints, incident results and carrier database;
* `evidence/author/mutations.json`: nine rejected semantic mutations;
* `evidence/author/baseline-reward.json`: unimplemented baseline overall 0.
* `evidence/opus-01/`: raw target trajectory/result/checks and exported source,
  workflows, checkpoints, local results and live carrier database;
* `evidence/opus-01/offline-replay/`: independent frozen-suite replay;
* `evidence/posttrial-publication-audit/`: identical supplemental probe and
  separate model/oracle results.

This package is an executable task and audit/evidence bundle, not a defensible
frontier-model-failure submission.

Install Harbor 0.24.0 and use Docker or a documented compatible provider.
From the parent of the task directory:

```sh
harbor run -p ./stockroom-carrier -a oracle
harbor run -p ./stockroom-carrier -a claude -m opus-5-5
harbor view ./jobs
```

Use the native Claude Code harness's documented high-reasoning configuration
for the target trial; model aliases and credentials depend on the provider.
Those native commands are the requested reproduction interface, not a claim
that a native Claude trial has already run.

In the author workspace, the task path is
`./collinear-candidate/stockroom-carrier`. The approved exploratory alternative is:

```sh
harbor run -p ./collinear-candidate/stockroom-carrier \
  -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --ak disable_web_search=true \
  --job-name stockroom-carrier-copilot-opus-01
```

Copilot CLI is **not** the assignment's native Claude Code harness. Any result
from it must retain that qualification. Authentication is supplied only through
the child process environment; no credentials belong in the task or evidence.

An offline oracle preflight can also mount `solution/` and `tests/` read-only:

```sh
docker build -t stockroom-carrier:author ./stockroom-carrier/environment
mkdir -p ./carrier-verifier
docker run --rm --network none \
  -v "$PWD/stockroom-carrier/solution:/solution:ro" \
  -v "$PWD/stockroom-carrier/tests:/tests:ro" \
  -v "$PWD/carrier-verifier:/logs/verifier" \
  stockroom-carrier:author sh -c \
  '/solution/solve.sh && python -m unittest discover -s smoke -v && /tests/test.sh'
```

## Provenance and limitations

The DSL, implementation, observations, business scenario, service, fixtures,
oracle and checks were created from scratch for this assignment, with Copilot
assistance. This is not a port of a public issue, benchmark, CTF or tutorial.
The same author's earlier stockroom revisions supply the base semantics and
tests; their passing results and reference defects are disclosed above.
The new external-authority scenario and service are original to this revision.

No third-party code or public dataset is vendored. Python's standard library
and pinned official container retain their upstream licensing. Harbor and
Copilot CLI are external execution tools, not redistributed source. Harbor's
public documentation, https://www.harborframework.com/docs, informed the
packaging and runner interface.

This is a deterministic authority/reconciliation model, not a production
carrier, distributed consensus implementation or concurrent lease system.
Concurrent filesystem races and mid-write process kills are not tested.
Continuation state is implementation-defined; adversarial arbitrary
rechecksummed internals are outside scope beyond the specified empty-state
rejection. The handoff's presence is programmatic; its evidence quality should
be reviewed by a human, not an LLM trajectory judge.

All evaluated files are frozen before the model trial. A model pass remains
a pass; additional discoveries must be separately labeled rather than used to
retroactively manufacture a failure.
