# stockroom-durable: run report

## Validation notes

Repaired the oracle's checkpoint encoding so ordinary mapping keys cannot collide with error tags, and removed Python's decimal-string digit ceiling to honor arbitrary-precision integer semantics. No candidate architecture or checkpoint encoding is prescribed.

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `stockroom-durable-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./stockroom-durable -a oracle
harbor run -p ./stockroom-durable -a claude -m opus-5-5
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

# Stockroom Durable: construction with portable continuations

## Current status

The original Savepoints task is preserved separately, along with its disclosed
Opus pass. This is a new, materially extended construction revision, not a
retroactive regrade of that trial.

**The failure objective has not been achieved.** The oracle and the completed
Opus 5.5 high / Copilot CLI trial both pass **204/204 acceptance checks**, with
all six rewards **1.0**. Public smoke tests pass; nine semantic mutations are
rejected. All 25 evaluated files were SHA-256-frozen before the exploratory
trial and verified unchanged after completion. Do not present this iteration
as evidence of frontier-model failure.

**Post-trial audit caveat:** 19 additional probes were run after the model pass.
The model passes all 19; the unchanged oracle passes 17 and fails two valid
edge cases. These expose reference defects, not model defects. The 204-check
trial is unchanged, but the current oracle is not a complete reference for the
expanded audit. Details and reproduction are below.

## Task idea

Build an interpreter from a specification and minimal CLI skeleton; implement a
warehouse reservation workflow; then execute it through seven process restarts.
The durable extension adds `pause`, portable JSON checkpoints, and CLI resume.
Pause can occur in a procedure, loop, active transaction or recovery handler.

A pause is not commit or rollback. A resumed outer transaction can reverse
stock, reservation, variable and event changes made in earlier processes.
Procedure returns and loop controls after restart must target the correct
continuations. Error bindings, shadowing, event ordering and execution counters
must survive. Repeated and empty labels are valid; the label cannot serve as
the continuation address.

## Realism and economic viability

Inventory reservation workflows often wait for approval, dispatch capacity or
human confirmation. Worker replacement must not duplicate reservations, consume
stock twice or publish abandoned shipments. Durable workflow engines and
restartable policy runners require the same continuation and state-management
discipline. This task models those concerns offline with deterministic state;
it does not claim to provide production distributed transactions.

The linked engineering goals are language parsing/static validation, stateful
transactional interpretation, cross-process durable execution, reusable business
workflow implementation, and a durable operational handoff.

## Why this revision

Opus 5.5 high passed the earlier 134-check construction task through Copilot CLI
in about 20 minutes. Its reviewer found a stack-cleanup defect, which it fixed
before submission. That was a genuine pass and successful self-correction.

This revision adds a distinct problem: continuation state can no longer reside
only in Python's live stack. It is not just additional grammar, more hidden
inputs, tighter tolerances, or a reduced timeout. The two-hour allowance remains.
The extension was specified and its verifier/oracle validated before its model
trial. All trial outcomes must remain disclosed.

## Public contract and fairness

The base grammar and operational rules are in `environment/app/docs/language.md`.
`environment/app/docs/durability.md` specifies the complete pause/resume protocol:

* byte-identity fingerprints for program, inventory and optional library;
* relocatable, self-contained JSON checkpoint envelope and canonical checksum;
* implementation-defined internal state representation;
* success exit 10 at pause, exit 0 at completion, CHECKPOINT exit 8 on rejection;
* atomic one-file publication per invocation, with no two-file commit problem;
* no result publication while suspended, no checkpoint mutation at completion;
* immutable snapshot replay is allowed and deterministic;
* no sidecars, in-memory worker dependencies or absolute-path dependencies;
* corruption/identity checks before compilation of resumed input;
* preservation of cumulative steps, counters, errors and transaction snapshots.

Exactly-once refers to simulated state and committed event outcomes, not an
external effect or one-use token protocol. Fresh-process deterministic
reconstruction is allowed if observable semantics agree; an explicit VM is not
mandated. The format is public and JSON key order is immaterial.

The workflow requires a pause after both order lines are reserved and before
shipping. Failed attempts do not pause. The incident's seven labels follow
directly from the supplied orders and documented workflow:

1. `practice:reserved`
2. `rehearsal:before-abort`
3. `ASSERT` (inside the recovery handler)
4. `alpha:reserved`
5. `dispatch:after-alpha`
6. `beta:reserved`
7. `delta:reserved`

Gamma is deferred without reserving both lines; it does not pause.

No network, special hardware, secrets or external packages are needed for the
task, oracle or verifier. Harness setup/inference may use network. The pinned
Python 3.12.12 image builds from the task's environment directory; the solution
and verifier are never copied into the candidate image.

## Oracle and independent verifier

The oracle uses a tokenizer/precedence parser and whole-program static checker.
Its execution machine makes scope IDs, procedure frames, loop boundaries,
transaction snapshots and recovery targets explicit. Error values have a safe
JSON representation. It uses standard-library JSON, SHA-256 and atomic sibling
replacement; there is no pickle, host-language evaluation or unsafe loading.

The grader imports no oracle interpreter code. It checks:

* All 134 base-language, inventory, validation, workflow, publication and
  incident checks retained from the passing original task.
* 70 durability checks: cross-process pause/resume equivalence; hand-calculated
  witnesses for state/events/counters; repeated/empty labels; nested loops and
  successful control transfers; pre-pause inner commits undone by outer rollback;
  recovery bindings and shadowing; mutable hold snapshots; cumulative step limits;
  relocated library/source/input; deliberate source/JSON corruption; fingerprint
  mismatches; envelope corruption; aliases; no premature checkpoint writes;
  distinct checkpoint input/output; completion and failure atomicity; six fresh
  generated durable order streams; and replay of the delivered last checkpoint.

The continuation checker copies only checkpoint and byte-identical input/source
files into a new directory, deletes the old directory, and invokes a fresh
Python interpreter at every pause. It also replays the final snapshot twice.
Uninterrupted execution is cross-checked against split execution, and important
witnesses additionally have independently calculated expected results.

The verifier writes `/logs/verifier/checks.json` and `reward.json`.
`overall` is 1 only when every check passes. Other rewards report functional
correctness, constraint satisfaction, transaction/durability robustness,
durability alone, and delivered artifact quality. Exact diagnostic prose and
handoff wording are not matched. A final failure only in prose existence,
diagnostic position or incidental bookkeeping is not automatically substantive.

### Negative controls

Nine independently applied mutations are rejected:

1. Drop tentative events during checkpoint export.
2. Reset the resumed statement budget.
3. Reset already committed inner-transaction counters.
4. Lose rollback binding restoration.
5. Lose rollback hold restoration.
6. Lose serialized recovery error codes.
7. Treat pause as a commit.
8. Accept changed source fingerprints.
9. Rewrite/consume a checkpoint at completion.

The controls run only in disposable containers. Their failures demonstrate
verifier sensitivity, not frontier-model failure.

## Author validation and iteration

* Docker image build succeeded; all task dependencies are standard library.
* The first oracle incident exposed a real author bug: deep-copying recovery
  exception objects in binding snapshots failed. Binding values in this
  language are immutable scalars/error references, so snapshots copy the binding
  dictionaries while serialization explicitly encodes error values.
* Initial full preflight: 194/195, with one hand-calculated statement count
  incorrectly 11 instead of 10. Corrected by counting entered AST statements;
  no semantic requirement was relaxed.
* Strengthened suite added mutable-hold, nested-loop, recovery-return and fresh
  durable workflow checks. Final offline oracle: **204/204**; two smoke tests
  pass. Nine mutation controls: **9/9 rejected**.
* Native Harbor 0.24.0 oracle, job `stockroom-durable-oracle-01`: all six rewards
  **1.0**, no exception, approximately 75 seconds.
* Final pretrial configuration, `stockroom-durable-oracle-02`: all six rewards
  **1.0**, no exception, approximately 68 seconds. Harbor artifact export
  successfully retained the interpreter, workflow and last checkpoint.
* Unimplemented baseline: **0/204**, all six rewards **0.0**.

Retained author evidence:
[oracle rewards](evidence/oracle/reward.json),
[oracle checks](evidence/oracle/checks.json),
[Harbor oracle result](evidence/oracle/trial-result.json),
[mutation controls](evidence/author-controls/controls.json),
[baseline rewards](evidence/author-controls/reward.json), and
[pretrial SHA-256 manifest](evidence/pretrial-freeze.json).

## Model trial

Completed exploratory configuration: Harbor 0.24.0, Copilot CLI 1.0.102,
`claude-opus-5.5`, `reasoning_effort=high`, web tools disabled, fresh Docker
environment, 2 CPUs, 2 GiB RAM, 7,200-second agent allowance. Requested source,
workflow and deliverable artifact export is enabled.
Job: `stockroom-durable-copilot-opus-01`, trial `stockroom-durable__XBxyeet`.

| Experiment | Result | Interpretation |
|---|---|---|
| Original Savepoints / Opus | 134/134, all rewards 1.0 | Disclosed earlier pass, approximately 20m07s |
| Durable revision / Opus 01 | 204/204, all rewards 1.0 | Genuine pass; no exception |
| Durable exported-source offline replay | 204/204 plus both smoke tests | Pass persists in a fresh container with no network or original worker |

The durable trial ran from 2026-10-23 13:46:52.880676 UTC to
14:24:55.659960 UTC (38m02.779s total). Agent execution was from
13:48:24.970719 UTC to 14:24:06.507603 UTC (35m41.537s). These timestamps come
from the Harbor trial result; do not conflate total runtime with model execution.

### What happened in the trajectory

The native trajectory contains 27,825 events, 67 tool executions and one
review subagent. The model constructed a flat-bytecode interpreter with explicit
procedure frames, block stacks and an undo journal. Its continuation state
includes active transaction marks, lexical bindings, errors and counters.

The model developed its own differential fuzzer, found a syntax bug in that
generator, repaired it and continued verification. Its final handoff reports
29 additional developer tests and 6,000 generated uninterrupted-versus-resumed
program comparisons. Those counts are the candidate's reported validation;
the independently verified result is the frozen 204-check acceptance suite.

Its review subagent flagged library-only `main` acceptance. The model chose
to require main in the program file, added a regression and reran its checks.
That was self-correction before submission, not a final model failure. The
combined-unit wording leaves some room for interpretation about library-only
entrypoints; this verifier does not use that distinction to establish failure.

The candidate completed all seven incident pauses and delivered a replayable
last checkpoint. Its workflow prechecks available stock before attempting a
warehouse, avoiding doomed partial reservations. That is a legitimate
implementation choice under the public observable-state contract; extra
rollbacks or a particular workflow statement count are not required.

### Persistence check and evidence

The author copied only the exported interpreter, workflow and deliverables into
a fresh copy of the pinned task image and reran both public smoke tests and all
204 frozen checks with `--network none`. Everything passed. The candidate's
optional `.pth` installation outside `/app` was not copied or needed for this
documented `/app` CLI invocation. There were no hidden worker/cache dependencies
in the replay.

* [Model rewards](evidence/opus-01/reward.json) and
  [all acceptance checks](evidence/opus-01/checks.json).
* [Harbor trial result](evidence/opus-01/trial-result.json).
* [Native JSONL trajectory](evidence/opus-01/copilot-cli.jsonl) and
  [Harbor-converted trajectory](evidence/opus-01/trajectory.json).
* [Exported model source and deliverables](evidence/opus-01/submission/),
  including its [handoff](evidence/opus-01/submission/deliverable/HANDOFF.md)
  and [last checkpoint](evidence/opus-01/submission/deliverable/checkpoint.json).
* [Fresh offline replay rewards](evidence/opus-01/offline-replay/reward.json)
  and [replay checks](evidence/opus-01/offline-replay/checks.json).

No evaluated task source, test, oracle or requirement changed after freezing.
Only this report and evidence were added. There is no final failure root cause
to report: the candidate solved the tested task. No native Claude Code trial
was performed.

The user selected Copilot CLI for exploration. This is NOT the assignment's
native Claude Code harness, and must not be represented as such. The earlier task's authentication
setup failure and its later pass remain documented in that task's run report.
Credentials are never bundled or printed in task evidence.

## Limitations

* A finite verifier cannot prove all-program equivalence. The standard language
  bounds are public; an empty-body infinite loop is not a statement-budget
  termination guarantee.
* Checksum detects corruption, not authenticity. Rechecksummed arbitrary forged
  internal states are outside scope, except the explicitly required rejection
  of empty `state:{}`.
* Clean suspension/restart is tested, not arbitrary process killing mid-write,
  concurrent writers, external effects or malicious filesystem races.
* Oracle and grader share development provenance; independent expectations
  and mutations reduce but do not eliminate correlated mistakes.
* The original task passed. Increased complexity is not itself failure evidence.
  Do not tighten this revision after looking at model results without recording
  a new revision and preserving the prior outcome.

## Post-trial edge-case audit

At the user's request, a separate set of 19 probes examined gaps in the frozen
suite. They cover the exact 20,000-statement success boundary, Unicode labels
and payloads, sibling scope/call-frame reuse, a terminal pause, valid checkpoint
reserialization, arbitrary data keys, large integers, missing checkpoint input,
floating-point version rejection, nested break/return/continue across
transactions, closed holds across restarts, builtin-name shadowing, restoration
of zero/missing SKU entries, three-level calls, unhandled post-resume errors,
and rollback of string/bool bindings.

| Implementation | Frozen acceptance | Additional post-trial probes |
|---|---|---|
| Opus exported submission | 204/204 | **19/19** |
| Frozen oracle | 204/204 | **17/19** |

No oracle-pass/model-fail case was demonstrated. In particular, it would be
incorrect to reverse these outcomes or turn the audit into failure evidence.
The two oracle defects are:

1. **Serialization tag/data collision.** Inventory
   `{"warehouses":{"east":{"$fault":1,"$token":2}}}` uses valid nonempty SKU names.
   The oracle's recursive generic decoder mistakes this ordinary stock map for
   an encoded error and rejects its own checkpoint. The model resumes it
   successfully. Error decoding should be scoped to typed binding locations or
   use an unambiguous representation in a future reference revision.
2. **Python integer conversion ceiling.** A valid 5,000-digit integer literal
   is below the public source-size bound and fits arbitrary-precision language
   semantics. The oracle leaves Python's default 4,300-digit conversion limit
   enabled and exits with an uncaught ValueError. The model explicitly disables
   that host limit and passes the cross-process test.

The reference was intentionally NOT patched inside the frozen iteration. A
corrected oracle and expanded acceptance suite require a separately identified
revision. Arbitrary forged internal checkpoints, mid-write crash injection,
out-of-bound nesting and unspecified entrypoint interpretations were not used
to manufacture candidate failures.

Audit artifacts:
[runnable probes](evidence/posttrial-audit/probes.py),
[model results](evidence/posttrial-audit/model-results.json), and
[oracle results](evidence/posttrial-audit/oracle-results.json).
These are supplemental tests under `evidence`, not changes to `tests/test.sh`.
Their aggregate script exits after writing individual results; inspect each
record's `passed` field rather than treating script exit 0 as all-tests-pass.

For example, inside this task directory, run against the frozen oracle with:

```sh
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  -v "$PWD/evidence/posttrial-audit/probes.py:/audit.py:ro" \
  stockroom-durable:author sh -c '/solution/solve.sh && python /audit.py'
```

For the model, start a fresh task image, copy the exported
`evidence/opus-01/submission/stockroom` and `workflows` into `/app`, mount the
same tests/probe script, and run `python /audit.py`. Bind a chosen host directory
to `/logs/verifier` to retain `supplemental-edge-audit.json`.

## Provenance

Original language, fixtures, interpreter, tests and documentation created for
this exercise. Revision 2 reuses this exercise's original
Savepoints baseline and adds newly authored durable semantics and tests. The
user's pasted warehouse-DSL brainstorming was the initial conceptual source.
No public benchmark task, issue, CTF, implementation or dataset was ported.
No third-party code or data is bundled; Python/Debian image components retain
upstream licenses. Harbor is external evaluation tooling.

## Reproduction

From the directory containing the task:

```sh
harbor run -p ./stockroom-durable -a oracle
harbor run -p ./stockroom-durable -a claude -m opus-5-5
harbor view ./jobs
```

Provider aliases vary. The native command above is the requested recipe, NOT
an experiment already performed. Configure credentials securely and request high
reasoning explicitly for the installed Claude agent/provider, for example:

```sh
harbor run -p ./stockroom-durable -a claude -m anthropic/claude-opus-5-5 \
  --ak reasoning_effort=high
harbor run -p ./stockroom-durable -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --ak disable_web_search=true
```

Inside the task directory, offline author validation:

```sh
docker build -t stockroom-durable:author environment
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  stockroom-durable:author sh -c \
  '/solution/solve.sh && python -m unittest discover -s smoke -v && /tests/test.sh'
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  stockroom-durable:author sh -c \
  '/solution/solve.sh && python /tests/author_controls.py'
```

Bind a chosen host directory to `/logs/verifier` to retain rewards and checks.
