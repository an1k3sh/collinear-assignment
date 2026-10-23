# rebate-close-continuity: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `rebate-opus-copilot-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `rebate-five-turn-opus` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./rebate-close-continuity -a oracle
harbor run -p ./rebate-close-continuity -a claude -m opus-5-5 --resume-trajectory
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

# Rebate close continuity

## Task idea and design process

One original task, five sequential user requests, one persistent workbook
workflow. A medical distributor calculates supplier rebates, then restates a
close after late credits, then rolls into a new quarter after vendor changes.
The agent must repair executable refresh logic, then build and maintain an exact
cash-claim optimizer, not just fill a spreadsheet.

The design considered three designs before selecting this one:

1. A financial forecast with successive assumption changes: realistic, but too
   close to common spreadsheet demos and easy to solve by replacing totals.
2. A laboratory lot-recall workbook: strong identity/lineage reasoning, but
   physical stock-allocation policy would require substantial extra domain rules.
3. Supplier rebate restatements: selected because original-invoice valuation,
   effective-dated identity, append-only revisions and frozen prior entitlements
   interact naturally, yet admit an exact, independently implemented verifier.

This is not a copy of a public task or a variation of a SheetCopilot dataset row.
All companies, IDs, notes and financial records are synthetic and newly authored.

The initial three-turn design was actually tested, not presumed difficult:
Opus 5.5 high passed every check in 14m 11s on native Copilot CLI. That passing
calibration is retained under `evidence/opus-calibration/` and is NOT represented
as a failure. After the user requested a harder extension, The extension added claim-batch
optimization and payment-state replanning. The resulting five-turn task is the
only submitted task directory; the calibration is evidence, not another task.

## Why it is long-horizon and economically real

The linked subgoals are:

1. Inspect six source sheets, a flawed draft exporter, and the policy/interface
   documents; reconstruct the correct event state as of the requested close.
2. Resolve revised invoices, pack/each unit economics and original-invoice
   attribution; calculate per-event rounded eligible amounts and all-volume tiers.
3. Produce an auditable workbook with live formulas, a correctly linked chart,
   preserved human notes, and a reconciled report.
4. Reuse the workflow after later corrections without rewriting an approved
   close or subtracting an earlier adjustment instead of an entitlement.
5. Carry the workflow to Q2 while Q1 continues to change; test idempotence and
   genuinely new valid inputs.
6. Optimize indivisible claim packets under per-key unpaid balances, supplier
   minimum batches, scoped evidence alternatives, prerequisite bundles, shared
   review time (including one-time setup), supplier counts and rail counts.
7. Replan after confirmed receipts, void receipts, PAID/BLOCKED packet revisions,
   new alternatives and July invoice corrections, without confusing an earlier
   recommendation with cash received.

Supplier rebates are a real receivable and purchasing-margin control. A late
credit can move an entire quarter below a retroactive tier; using the current
vendor group for an old credit misstates both group balances and the journal.
Automating this close can save analyst time and recover missed credits while
leaving a reviewable workbook for finance. No specialized accounting knowledge
beyond the supplied policy is necessary.

The optimization is economically meaningful rather than decorative: maximize
high-priority cash recovery before lower-priority packets, then minimize review
effort and packet count at those exact optima. The desk cannot partially submit
an evidence packet, reuse an alternative's evidence, or exceed a vendor's unpaid
rebate entitlement. The fixtures distinguish plausible greedy selection from
an exact optimum, as demonstrated by the negative controls.

## Relationship to SheetCopilot and provenance

Inspected the accessible local SheetCopilot checkout, particularly its README,
Linux evaluation guide, Claude Code workbook-editing harness and evaluator
layout. The inspiration is its ordinary-tools, real-XLSX workflow and
outcome-based checking, not its benchmark questions, seed workbooks, answers,
code or evaluator.

The local SheetCopilot checkout is GPL-3.0. No SheetCopilot code, text, workbook,
image, task or solution is redistributed here, so this is not a port or
derivative implementation of that benchmark.

External runtime dependencies:

* Python official Docker image, pinned by multi-platform SHA256 digest.
* Debian Bookworm packages from the fixed 2026-02-01 snapshot.
* openpyxl 3.1.5 (MIT), et-xmlfile 2.0.0 (MIT), LibreOffice (MPL-2.0 and
  associated distribution notices). These remain their respective authors' work.
* NumPy 2.3.3 and SciPy 1.16.2 (BSD-3-Clause and bundled third-party notices).
  SciPy supplies the HiGHS integer optimizer; it is installed for the agent as
  well as the verifier. No optimizer install or network access is needed at runtime.
* Harbor 0.24.0 is the host runner, not a task dependency.

Everything else in this directory was created for this exercise. No external
dataset or network lookup is needed to solve or verify the task.

## Verifier design and false-positive/negative controls

`tests/test_settlement.py` implements an exact-rational financial reference;
the oracle independently uses decimal arithmetic. The verifier does not import,
execute or compare against the oracle to obtain expected financial results.

For claim planning, the oracle enumerates feasible supplier-local subsets and
uses exact integer resource-state dynamic programming. The verifier instead
constructs a binary MILP with separate group-activation variables and solves
five successive objectives, fixing each optimum before the next. It checks the
returned selection again with an integer constraint evaluator. It grades the
objective vector, not an exact list of IDs, so equivalent optimal batches pass.

It checks every active event's identity, group, quarter and signed cents;
every required summary key, tier, entitlement, prior entitlement and journal;
raw source preservation; human notebook values, comments, review fills and view;
all earlier closes; linked chart ranges and report reconciliation.

It independently recalculates copies with LibreOffice. It changes a Detail
amount across a tier boundary and checks the entire live formula dependency.
It invokes the delivered CLI twice and on four variations: price/quantity,
eligibility/aliases, new events plus revision history, and exact tier equality.
These variations change only documented inputs and preserve valid references.
The grader accepts alternate formulas and row ordering; no generated binary
workbook, style ID, formula spelling or chart title is compared exactly.

The plan CLI is also run twice and against changed receipts, review/rail/supplier
limits, new packets and revisions, priorities and minimum-batch requirements.
The plan's actual feasibility, exact optimality, capacity formulas, reports and
input/archive preservation are checked. A selection-cell edit must flow through
the Capacity sheet's selected and remaining amounts.

The task uses final-step aggregation, but final verification also validates BOTH
earlier archived closes against their own historically correct input state,
plus the approved first claim recommendation and its exact historical financial
input/report.
All turns execute even if an earlier one failed, so the trajectory remains
diagnosable. No too-short timeout or early-stop gate creates the failure.

The verifier removes its own reference module and future-turn fixtures after
each step, before the agent resumes in the shared container. Only the current
turn's business source is staged into the workspace. The oracle is uploaded
only for the oracle agent and is not in the task image.

`evidence/verifier-audit.json` records 14 controls: four valid cases accepted,
ten plausible wrong cases rejected. These include correctly valued but
hardcoded summaries, omitted ineligible events, arrival-quarter credits,
subtracting prior adjustments, dropping vanished keys, stale rates, a wrong
chart, a static lookalike chart, overwritten human notes and a fabricated report total.

`evidence/planning-audit.json` adds seven controls: two independent DP/MILP
agreements and five realistic failures rejected. For the June batch, a plausible
priority-and-value-per-minute greedy heuristic obtains
`[294278, 119776, 0, -186, -13]`, while the proven optimum is
`[338459, 52128, 0, -187, -12]`. The larger second-priority recovery does not
compensate for $441.81 of missing first-priority recovery. The July optimum is
`[35437, 65275, 21409, -163, -10]`. Other controls reject resubmitting paid claims,
resurrecting void receipts and ignoring supplier setup review.

During development, independent recalculation revealed two integration issues:
LibreOffice represents booleans differently and alters frozen-pane views on an
XLSX round-trip. Raw-cell comparisons now compare semantic values, not boolean
storage encodings; the oracle preserves the source notebook and only
recalculates disposable copies. Neither issue is claimed as model failure.

The final trial's business specification, seed data and objective were fixed
before launch. An in-flight verifier audit found that an added future-only
revision reused the fixture's already-existing future revision number 999.
It was renumbered to 10001 so the alternate input remains a valid append-only
history. Both records are beyond the cutoff; this changes no current expected
answer or grading criterion. The oracle was rerun after that validity fix and
again passed every criterion. No requirement was added based on the target's
solution or trajectory.

## Reproduction

From the directory containing `collinear-candidate/`, using Docker and Harbor
0.24.0 or a compatible newer version:

```bash
harbor run -p ./collinear-candidate/rebate-close-continuity -a oracle
harbor view ./jobs
```

The assignment's illustrative target command is:

```bash
harbor run -p ./collinear-candidate/rebate-close-continuity -a claude -m opus-5-5
```

In installed Harbor 0.24.0 the native harness name is **claude-code**, not
`claude`; use the available endpoint's exact model ID:

```bash
# Requires a separately configured Anthropic account/endpoint.
harbor run -p ./collinear-candidate/rebate-close-continuity \
  -a claude-code -m opus-5-5 --ak reasoning_effort=high --resume-trajectory

# User-approved alternate: native Copilot CLI.
# Authenticate with COPILOT_GITHUB_TOKEN/GH_TOKEN using your own credentials.
harbor run -p ./collinear-candidate/rebate-close-continuity \
  -a copilot-cli -m claude-opus-5.5 --ak reasoning_effort=high \
  --ak version=1.0.103 --ak disable_web_search=true --resume-trajectory

harbor run -p ./collinear-candidate/rebate-close-continuity -a nop
```

`--resume-trajectory` retains the conversation across user turns. The workspace
persists either way; without this flag Harbor starts fresh conversations.

To reproduce the deliberate-error audit (no model, no runtime network):

```bash
TASK=./collinear-candidate/rebate-close-continuity
docker build -t rebate-close-continuity:author "$TASK/environment"
mkdir -p "$TASK/evidence"
docker run --rm --network none --cpus 2 --memory 4g \
  -v "$PWD/$TASK/tests:/tests:ro" \
  -v "$PWD/$TASK/solution:/solution:ro" \
  -v "$PWD/$TASK/authoring:/authoring:ro" \
  -v "$PWD/$TASK/evidence:/evidence" \
  rebate-close-continuity:author python /authoring/audit_verifier.py
```

The checked-in XLSX seed files are already generated. Optionally regenerate
their deterministic contents using `python authoring/build_seed.py` in an
environment with openpyxl; ZIP timestamps need not be byte-identical.

Run the same offline audit command with `python /authoring/audit_planning.py`
to reproduce the seven planning controls. These audits use synthetic variants
and never invoke a model or use an LLM judge.

## Network, resources and fairness

The image builds from public pinned/snapshot sources. Runtime business logic,
recalculation and the verifier require no network or secrets. The declared
Harbor network mode is `public` for native agent installation, authentication
and model calls; it is NOT an enforced egress sandbox. The local Docker
provider rejects Harbor's phase-specific `no-network` setting, so the submitted
configuration does not pretend to enforce it. The standalone audit was run
with Docker `--network none`.

Each turn has 2,400 agent seconds; verification has 420 seconds. The container
requests two CPUs, 4 GiB RAM and 8 GiB storage. There are no private services,
hardware requirements, Excel license, model-dependent grading or LLM judges.
The environment build was tested on the available Docker engine.

The agent is told every graded business rule, output schema and preservation
constraint, including alternate-input and formula-recalculation checks. Future
requests introduce new data, not hidden retroactive policy changes. Human
formatting is limited to explicit, meaningful notebook features. Arbitrary
workbook appearance is not graded.

## Runs and evidence

Oracle: native Harbor, all FIVE turns passed all reward dimensions in
`rebate-five-turn-oracle-final`; total runtime approximately 2m 0s.
No-op: native Harbor `rebate-five-turn-nop`, overall 0.
Verifier audits: 14 financial controls and seven planning controls passed.
Passing three-turn calibration: native Copilot CLI 1.0.103,
`claude-opus-5.5`, high effort, resumed trajectory, all criteria passed.

The five-turn target trial uses the same native harness/model/effort, starts
from scratch, and retains the earlier passing calibration as a distinct result.
Its final outcome is recorded below after completion.

## Limitations

This is a synthetic, bounded reconciliation workflow, not a whole ERP system.
It has no concurrent writers or untrusted formulas. Invalid-input recovery,
chart rendering aesthetics and every possible Excel feature are not graded.
Storage size is declared but Docker/provider enforcement may differ.
A single target-model trial is evidence of one observed outcome, not a
statistically estimated failure rate.

No Claude Code target-model failure is claimed without an actual Claude Code
run. A Copilot trial is explicitly an alternate-harness result, even when the
underlying requested model is Opus.
