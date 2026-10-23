# Grant allocation close

An original formula-driven finance task. A grants analyst must reconcile a
versioned multi-currency expense ledger, apply per-program funding caps,
redistribute a weighted budget and award exact whole cents. The controller
must be able to keep using the workbook without rerunning code.

## Why it matters

A correct grand total does not establish that each program received the right
award. Errors in ledger identity/version selection propagate into the caps;
incorrect capped redistribution or remainder handling can move funds between
programs while a chart still looks plausible.

The linked work is source reconstruction, per-line currency conversion,
funding eligibility, capped proportional distribution, exact cent allocation,
formula lifecycle and a live editable chart. The seeded workbook has styled
source sheets, a prior close, a versioned 30-record ledger, a controller handover
and an unapproved draft summary.

## Fairness and verifier

The complete policy, output locations and supported update bounds are public.
No particular formulas, helper layout or algorithm are required. Exact text
keys, cutoff selection, signed rounding, caps and tie rank are explicit.
The verifier checks real LibreOffice recalculation, not formula strings.

Fourteen criteria cover input/formula preservation, saved values, chart binding,
the original close and ten documented-class input changes: budget, weights,
approvals/caps, the final supported ledger row, later cutoff, FX/rate order,
small-cent ties, zero caps, revised/refund records and zero budget.

The independent reference uses Decimal for currency conversion and exact
Fraction arithmetic to solve the water level by removing saturated programs.
The workbook oracle uses formula-based iterative redistribution, capped at
eight rounds for eight programs, followed by largest-remainder ranking.
This avoids comparing one formula implementation against itself.

The oracle passed every criterion in a native Harbor container. Positive
and negative controls are recalculated, so rejected faults are not merely
missing caches. The task requires no internet, macros or private state.

## Provenance and limitations

The workbook, synthetic records, policy and code were authored for this
exercise; no public benchmark or customer workbook was copied. The fixed
Python base image is digest pinned, LibreOffice comes from a dated Debian
snapshot, and Python package versions are pinned.

The scenario intentionally fixes eight programs and 500 ledger slots, as
stated in the policy. This is not a full grant accounting system. The handover
report is checked for presence, not scored by an LLM judge. Mathematical
correctness, source preservation, recalculation and chart bindings determine
the result.

## Completed target-model trial

`grant-opus-01/grant-allocation-close__2Bommq6`: Opus 5.5 high, Copilot CLI
1.0.102, all fourteen criteria passed, overall 1.0, about 6m40s including setup
and verification. All eleven workbook recalculation scenarios passed.
Task and verifier hashes stayed frozen; no failure was observed.

Author control testing found that a SUMIF-based grouping alternative preserves
the supplied text identities in this LibreOffice runtime. It was accepted as
a valid alternative, not misclassified as a model fault. Explicit numeric ID
normalization and seven other faulty controls were rejected.

## Reproduction

From the parent directory:

```sh
harbor run -p ./grant-allocation-close -a oracle
harbor run -p ./grant-allocation-close -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the assignment recipe. The authorized experimental
run uses Copilot CLI, not Claude Code:

```sh
export PYTHONPATH="$PWD/grant-allocation-close/author"
# Supply valid Copilot authentication in the local environment.
uvx --from harbor==0.24.0 harbor run -p ./grant-allocation-close \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter is the installation-only official Node/npm workaround used in the
other trials. It inherits Harbor's native Copilot invocation and trajectory
capture unchanged.
