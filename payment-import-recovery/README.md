# Payment import recovery

**Short task:** Repair a concurrent payment importer and replay an interrupted
bank export without duplicating payments, losing cents, misallocating invoices,
or hiding worker failures.

## Compounding assumptions

* Same amount/time means duplicate: two legitimate payments have both.
* Numeric-looking invoice IDs can be normalized: `00123` and `123` differ.
* A timeout means no commit: the incident payment already has a durable receipt.
* Exit zero means all rows imported: uncollected worker exceptions say otherwise.
* Floating-point dollars can be truncated to cents: `0.29` exposes the error.

## Artifacts and deliverable

`environment/app/` contains the flawed importer, invoice/payment CSVs, incident
log, compatibility contract and deterministic SQLite seed generator. Docker
builds the initial database, including one committed payment with a lost response.
The result is a code patch, repaired database, row-level import report and tests.

## Verification and evidence

Native Harbor oracle: all six criteria pass. The verifier checks original state,
exact receipts, altered inputs, malformed rows, post-commit faults and four
independent processes racing one payment. One valid serial-worker alternative
passes; float truncation, accepted key reuse and payment-without-receipt controls
fail. Full results are in `evidence/`.

One Opus 5.5 high trial with Copilot CLI 1.0.102 passed all six criteria, overall
1.0, in 6m57s including setup/verification. Trial:
`harbor-prototypes-opus-02/payment-import-recovery__CJhgYPc`.
The top-level prompt was made diagnostic-neutral before freezing; contracts and
incident evidence remained available. Source/verifier hashes stayed unchanged.
This is a small prototype, not a demonstrated frontier-model failure.

## Reproduce

From the directory containing this task:

```sh
harbor run -p ./payment-import-recovery -a oracle
harbor run -p ./payment-import-recovery -a claude -m opus-5-5
harbor view ./jobs
```

Validated with Harbor 0.24.0. The model command is a recipe, not run evidence;
configure high reasoning in the native adapter before a model trial.

The recorded Copilot trial used `author/prototype_harness.py`, an installation-
only subclass: install official SHA256-checked Node 22.14.0 if missing, then
`@github/copilot@1.0.102` via npm. Model invocation is inherited unchanged.
Reproduce from this task directory:

```sh
PYTHONPATH="$PWD/author" uvx --from harbor==0.24.0 harbor run -p . \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

An earlier setup-only attempt failed because npm was absent; it never invoked
the model or verifier and is not failure evidence. Raw successful run evidence
is under `evidence/model/`. Copilot CLI is not Claude Code.

Author controls, from this task directory:

```sh
docker build -t prototype-payments:author environment
docker run --rm -v "$PWD/solution:/solution:ro" -v "$PWD/tests:/tests:ro" \
  -v "$PWD/author:/author:ro" prototype-payments:author \
  sh -c '/solution/solve.sh && python /author/validate_controls.py'
```

## Provenance and limitations

All code, financial data and incident records were authored from scratch.
External components are the digest-pinned official Python image and its standard
libraries. No private data, API calls, secrets or external services are required
inside the task. Network is needed only to acquire images and run a model harness.
This is a bounded importer, not a payment network, bank integration or accounting
system. Tests are finite and do not establish general crash/power-loss safety.
