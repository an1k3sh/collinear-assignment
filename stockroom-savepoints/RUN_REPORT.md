# stockroom-savepoints: run report

## Validation notes

Removed the oracle CLI's decimal-string digit ceiling to honor the existing arbitrary-precision integer contract.

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `stockroom-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 0.0 | Infrastructure exception; not failure evidence |
| `stockroom-copilot-opus-02` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./stockroom-savepoints -a oracle
harbor run -p ./stockroom-savepoints -a claude -m opus-5-5
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

# Stockroom Savepoints

## Status

**The failure objective has not been achieved.** The oracle and the completed
Opus 5.5 high / Copilot CLI trial both pass all **134 acceptance checks**, with
every reward component **1.0**. Keep this as an original, validated DSL
construction task and a disclosed passing experiment, not as failure evidence.
Copilot CLI is not Claude Code and its result must not be represented as
satisfying the native-harness evidence requirement.

## Idea and why construction

Implement a typed imperative warehouse language from a specification and CLI
skeleton, then use it to fulfill atomic two-line orders. The supplied files are
not a broken interpreter with planted bugs. The candidate chooses the tokenizer,
parser, static representation, environment model, transaction mechanism and
publication strategy.

The linked subgoals are:

1. Parse a real language with precedence, named/default arguments and source
   positions; validate all procedures, scopes, types and call-graph cycles.
2. Execute lexical procedures and block scopes alongside inventory reservations,
   nested savepoints, recovery bindings and successful nonlocal control flow.
3. Implement a reusable fulfillment library; run a rehearsal and shortage incident;
   publish durable state/events and a handoff.

The hard interactions are not additional syntax: a return exits some, but not
all, active transactions; inner recoveries remain tentative inside outer
savepoints; rollback restores binding values without breaking active scope
identity; closed holds remain tombstones; available and on-hand differ.

## Economic connection

Order reservation systems must avoid partial fulfillment, overselling stock,
leaking reservations and recording abandoned shipments. A small deterministic
operations language lets a warehouse team inspect and replay business policies
without granting scripts arbitrary database or shell access. This is an offline
simulator, not a proposed replacement for a production transactional database.
The same interpreter engineering appears in policy engines, configuration
languages and migration runners.

## Originality and provenance

The language specification, interpreter, CLI skeleton, warehouse data, incident,
workflow, acceptance suite and mutation controls were written from scratch for
this exercise. The user's pasted warehouse-DSL
brainstorming was the conceptual starting point. No SCBench implementation,
public issue, SWE-bench/Terminal-Bench task, CTF or other benchmark was copied or
ported. The public DAG-language discussion inspired the choice of *task class*,
not this grammar or scenario.

No external datasets or source-code snippets are bundled. Python standard
library facilities are used; the pinned Docker Python image contains upstream
Python/Debian components under their own upstream licenses. Harbor is external
evaluation tooling, not a task dependency.

## Verifier

`tests/test.sh` launches a standard-library-only subprocess verifier. It imports
neither the oracle parser nor runtime. It writes detailed `checks.json` plus
multi-criterion `reward.json` under `/logs/verifier`.

There are 134 checks across seven groups:

* language execution: precedence, integer semantics, short-circuiting, default
  binding, forward calls, lexical scope and string tokenization;
* static/syntax validation, including unreachable code and unused procedures;
* inventory: free stock, tombstones, partial ship/release, failure codes and
  preservation of missing SKU entries;
* transactions: nested commit/abort, nested recovery, error propagation,
  shadowed bindings, return/break/continue, and execution counters;
* publication/input validation: fatal versus recoverable failures, original
  output-byte preservation, no new output on failure, duplicate JSON keys,
  invalid quantities/shapes, missing paths, and source stack positions;
* reusable fulfillment: sixteen deterministic generated streams of twelve
  orders (including same-SKU bundles), existing holds and enclosing rollback;
* the durable incident output: inventory, hold set, event payloads/order and
  existence of a nonempty handoff. Handoff prose is not keyword-graded.

The fulfillment reference is a small independent Python resource-allocation
model, not an interpreter for the tested DSL. Other expectations are hand
calculated witnesses and deterministic metamorphic snapshot cases.

`overall` is 1 only if every check passes. Functional correctness averages
language/inventory/workflow group pass rates; constraint satisfaction averages
validation/publication; robustness is the transaction pass rate; artifact
quality is the incident artifact check. A low overall caused only by a missing
handoff, source-position field or counter discrepancy is NOT automatically a
substantive target-model failure. Inspect the detailed checks.

Accepted implementations may use any architecture. JSON key order, extra
top-level descriptive result fields and diagnostic message wording are not
compared. Workflow instruction ordering inside an atomic attempt is not
over-specified: equivalent observable outcomes are accepted.

## Author validation and iteration

Tooling: Docker Desktop engine 29.5.3; Harbor 0.24.0; pinned Python 3.12.12 image.
The task runtime has no installed third-party packages.

* Initial author smoke had an incorrect expected statement count (11 instead of
  10). It was fixed before the first model trial.
* `jobs/stockroom-oracle-01`: 127/129 checks, failing only two hand-calculated
  statement-count expectations. Tracing the specified AST entries showed the
  expected counts were one too high; no semantic requirement was relaxed.
* `jobs/stockroom-oracle-02`: all 129 checks passed.
* Additional pretrial audit added five checks for empty IDs, left-to-right
  procedure argument errors, and no creation of absent output files on failure.
  The empty-ID check also led to a reference implementation correction.
* `jobs/stockroom-oracle-03`: all 134 checks; all five rewards **1.0**, no trial
  exception, approximately 24 seconds.
* `jobs/stockroom-release-oracle-01`: repeated after adding the report and model
  evidence; all five rewards **1.0**, no exception, approximately 26 seconds.
* Final unimplemented baseline: **0/134**, every reward **0.0**.
* Eight independently applied runtime mutations are rejected by selected
  semantic checks. Controls cover omitted variable rollback, shallow hold
  snapshots, leaked events, ignoring holds, catching fatal errors, undoing
  successful control transfers, floor division, and transactional counters.
  Most controls are rejected by wrong observable state/events, not crashes.
* Oracle incident, Python compilation and public smoke also passed in a
  network-disabled container. The Pylance service was unavailable; executable
  Python/container validation was used instead.

No model-informed tightening has been performed. Evaluated source files were
SHA-256-frozen before launching the first exploratory model trial.

## Model trial

Requested exploratory configuration:

* Harbor 0.24.0, `copilot-cli`, Copilot CLI pinned to 1.0.102.
* Model `claude-opus-5.5`, `reasoning_effort=high`.
* Web search tools disabled. Candidate still has normal local code/tool access.
* Fresh Docker environment, 2 CPUs, 2 GiB RAM, 7,200-second agent allowance.
* Authenticated job `stockroom-copilot-opus-02`.

| Job | Result | Interpretation |
|---|---|---|
| stockroom-copilot-opus-01 | Authentication error; zero grader rewards | Setup failure, excluded from model capability analysis |
| stockroom-copilot-opus-02 | 134/134; all rewards 1.0; no exception | Genuine pass; approximately 20m07s total, 18m27s agent execution |

The initial job `stockroom-copilot-opus-01` exited before inference with
`NonZeroAgentExitCodeError`: the author launcher mistakenly passed the macOS
keyring's base64-wrapped value instead of decoding the stored GitHub token.
Its 0/134 verifier result is an authentication/setup failure, NOT a model
attempt or capability-failure result. The credential handoff was corrected
without changing any frozen task files. Trial 02 completed with authenticated
model and tool events.

### What the successful agent did

The native trajectory records 35 tool executions and one specification-review
subagent. The model constructed its own parser and whole-program validator,
implemented transactional execution with an undo log, implemented the workflow,
ran the public smoke test and reported 25 additional developer checks.

The review subagent found a real intermediate defect: a procedure name remained
on the diagnostic call stack after a caught failure, because frame removal was
not in a `finally` block. The model fixed it and added a regression check before
submitting. This is successful inspection/debugging/verification, **not** an
observed final capability failure. The final grader accepts all seven groups,
including every generated order stream and nested transaction case.

### Preserved evidence

* [Passing model rewards](evidence/opus-02/reward.json),
  [all per-check results](evidence/opus-02/checks.json),
  [Harbor trial result](evidence/opus-02/trial-result.json).
* [Native JSONL trajectory](evidence/opus-02/copilot-cli.jsonl) and
  [Harbor-converted trajectory](evidence/opus-02/trajectory.json).
* [Excluded authentication attempt](evidence/auth-01/trial-result.json).
* [Oracle rewards](evidence/oracle/reward.json) and
  [oracle checks](evidence/oracle/checks.json).
* [Semantic mutation controls](evidence/author-controls/controls.json) and
  [empty-baseline rewards](evidence/author-controls/reward.json).
* [Pretrial SHA-256 manifest](evidence/pretrial-freeze.json): all 20 evaluated
  files were checked unchanged after the model completed. Report and evidence
  files were added separately and are not candidate inputs.

Harbor's parsed token metrics are incomplete (including a misleading parsed
zero output-token count); do not interpret them as reliable usage/cost data.
The retained native trajectory contains the actual generation/tool events.
The trial did not request separate source-tree artifact export before container
cleanup, so source writes are retained in the trajectory rather than as an
independently copied final submission tree.

There is no
Anthropic/OpenAI API key in the author shell; an existing local GitHub login is
used for the explicitly requested exploratory route. Credentials are never
included in the task or evidence. The user also authorized `gh auth token` as
a fallback; it was unnecessary after decoding fixed the existing keychain login.

## Fairness audit and limitations

* The complete grammar, type rules, domain codes, rollback boundary, publication
  behavior, result schema and business policy are public.
* There are no private data inputs, network calls, nondeterministic timestamps,
  random grading seeds, exact prose matches or LLM judges.
* The image digest is pinned and builds from a clean environment. Oracle and
  verification run offline; harness installation/inference may use network.
* The two-hour allowance is deliberately generous. No speed bonus exists.
* Tests are withheld, not the requirements. The visible smoke is a non-complete
  example and is explicitly identified as such.
* The finite suite cannot prove interpreter equivalence for every possible
  source. Source/input sizes and nesting bounds are documented. The step-limit
  probe uses a loop whose body enters a statement; no claim is made that a
  statement-count limit terminates an empty-body infinite loop.
* The oracle and verifier share development provenance, although the
  verifier does not reuse the interpreter. Mutation checks reduce but cannot
  eliminate correlated mistakes.
* This is an evaluation harness, not a hostile-submission security boundary.
* Neither the task's complexity nor rejection of mutants is evidence that Opus
  fails. A real trajectory and root-cause analysis are required.
* Do not submit this iteration as fulfilling the assignment's required failure
  evidence. A native Claude Code trial or a substantively different, predeclared
  extension would be a separate experiment; do not retroactively tighten this
  passing trial's grader or present its repaired intermediate defect as failure.

## Reproduction

From the parent directory containing the task:

```sh
harbor run -p ./stockroom-savepoints -a oracle
harbor run -p ./stockroom-savepoints -a claude -m opus-5-5
harbor view ./jobs
```

The second command is the assignment's requested shorthand. Provider model
aliases differ; confirm the installed Harbor Claude agent's available model ID
and set the appropriate API credential securely. For Harbor 0.24.0's Claude
agent, request high reasoning explicitly, for example:

```sh
harbor run -p ./stockroom-savepoints -a claude -m anthropic/claude-opus-5-5 \
  --ak reasoning_effort=high
```

That native command is a reproduction recipe, NOT a claim it was executed.
The exploratory configuration is:

```sh
harbor run -p ./stockroom-savepoints -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --ak disable_web_search=true
```

Authenticate using a supported GitHub/Copilot credential through the environment;
never paste a token into the task or logs.

Offline author checks from inside the task directory:

```sh
docker build -t stockroom-savepoints:author environment
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  stockroom-savepoints:author sh -c \
  '/solution/solve.sh && python -m unittest discover -s smoke -v && /tests/test.sh'
docker run --rm --network none \
  -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  stockroom-savepoints:author sh -c \
  '/solution/solve.sh && python /tests/author_controls.py'
```

To retain outputs, additionally bind a chosen host directory to
`/logs/verifier`. The author-control command deliberately mutates the disposable
container's oracle runtime and restores it afterward; never run it against a
candidate submission or the host source tree.
