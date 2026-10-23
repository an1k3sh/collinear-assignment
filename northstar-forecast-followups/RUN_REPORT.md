# northstar-forecast-followups: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `northstar-followups-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./northstar-forecast-followups -a oracle
harbor run -p ./northstar-forecast-followups -a claude -m opus-5-5 --resume-trajectory
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

# Northstar: genuine follow-ups, revisions and a finance detour

## Status

**No substantive model failure was found.** Opus 5.5 high, running through
Copilot CLI with native session continuation, passed every reward component at
all six stages. Both the six-stage oracle and exported-core oracle also pass.
The twelve author controls behave correctly. This is a validated passing
follow-up experiment, not a successful frontier-model failure submission.

## What this experiment tests

Harbor 0.24.0 supports sequential tasks through `[[steps]]`. Its Copilot CLI
adapter declares native resume support and uses `copilot --continue` when a
step resumes. The experiment is invoked with `--resume-trajectory`, retaining
both the native conversation and the shared `/app` filesystem.

Each later instruction is issued only after the preceding agent turn, artifact
collection and verification. The instruction is not disclosed in the initial
prompt. This is a real **successive follow-up experiment**, not a single prompt
containing all revisions. It is still not an asynchronous interruption of an
in-flight tool call.

The model initially builds and commits a legacy-method artifact. Subsequent
requests must selectively replace parts of that work, retain other parts,
switch to a related deliverable and return without losing prior obligations.
We do not inject new custom system instructions, make contradictory requests,
hide mathematical conventions or grade an abandoned requirement as active.

## Stages

| Stage | Type | Current obligation and intended state pressure |
|---|---|---|
| 01-growth | Original request | Build source-linked drivers, growth revenue, working capital, earnings, cash/debt and controls |
| 02-cohort-revision | Method replacement | Replace growth revenue with customer cohorts; retain A/C and format |
| 03-liquidity-continuation | In-domain extension | Add a separate stress workbook and monthly board bridge without changing baseline |
| 04-treasury-detour | Related task switch | Reconcile posted bank movements and duplicate deliveries; do not apply cutover yet |
| 05-renewal-pricing | Return and policy revision | Replace immediate calendar uplift with cohort-specific quarterly renewal adoption in both models; retain stress and reconciliation |
| 06-reconciled-cutover | Selective revision | Apply approved opening balances once; withdraw DSO stress, replace capex stress, retain other stress inputs and renewal method; refresh all handoffs |

No `min_reward` early stopping is configured. All six steps execute even if a
prior financial milestone earns zero, unless the harness itself raises a
stopping exception. This separates transient incompleteness from persistent
regression. `multi_step_reward_strategy = "mean"` reports the mean of each
component across evaluated stages; the individual rewards remain authoritative.
A mean `overall` of 5/6 means five stages passed, not that the final stage failed.

## Realism and economically meaningful failure modes

FP&A work often arrives as a sequence: finish the old plan, change methodology,
prepare a board stress, reconcile the cash cutover, incorporate a revised
customer contract policy, and produce one consistent final package.

The task deliberately tests selective state retention, not just workbook
volume. Meaningful candidate failures include retaining legacy growth after
replacement, resetting unrelated costs, applying a bank correction before
approval or twice after approval, forgetting the detour deliverable, leaving
the stress workbook on an obsolete policy, losing a retained debt covenant,
applying July pricing to post-July launches, or publishing stale board figures.

The 1,020 final completion cells are repeated schedule structure, not 1,020
independent reasoning problems. A strong model may script them rapidly.
An actual trajectory and stage results, not the number of cells or stages,
determine whether this becomes a hard long-horizon benchmark.

## Environment and reproducibility

The environment is the prior synthetic Northstar workbook with a neutral
engagement cover. Python 3.12.12 is digest-pinned; Debian package selection
uses the 2026-02-01 archive snapshots; openpyxl 3.1.5 and et_xmlfile 2.0.0 are
pinned. LibreOffice is preinstalled and recalculates disposable copies. There
are no task-time downloads, private datasets, secrets or model calls required
for the oracle or verifier.

Harbor setup and model inference need public network access. Harbor 0.24's
Docker provider does not support a verifier-only no-network policy, so the
metadata does not claim enforced runtime isolation. Author controls can run
using `docker run --network none`.

The initial environment contains only the workbook and shared conventions.
Future prompts, the oracle and verifier are not copied into `/app`.
Treasury data arrives through stage 04's `workdir/treasury/`, after stage 03.
The verifier has its own trusted copy. Harbor clears shared `/tests` and
verifier logs before each subsequent agent phase; this was checked in the
installed `multi_step.py` implementation rather than assumed.

## Verifier

[tests/test.sh](tests/test.sh) uses the per-step `PHASE` configured by Harbor
to run [grade_phase.py](tests/grade_phase.py). It writes `reward.json` and
`checks.json` under `/logs/verifier`.

- **Functional correctness:** compare monthly and annual financial outcomes
  against an independent 40-digit Decimal reference after LibreOffice
  recalculation. The reference uses product-based cohort survival and
  enumerated renewal schedules; the oracle constructs spreadsheet formulas.
- **Constraint satisfaction:** compare the workbook semantically against a
  trusted template with only explicitly authorized scenario/history changes.
  Inactive cells stay blank at stage 01; all 1,020 targets become formulas at
  stage 02. Styles, actuals, comments, chart, validation, sheet structure and
  pre-existing formulas remain intact.
- **Robustness:** source-input perturbations exercise legacy-method dependence,
  cohort churn, launch pricing, multiple queued price events, renewals beyond
  year-end and financial dependencies. A separate disclosed inconsistent-copy
  audit tests live residuals. Legitimate revenue aliases are accepted rather
  than repeating the earlier experiment's denominator false positive.
- **Artifact quality:** baseline handoff and both monthly board bridges must
  agree with independent results, including peak debt and first debt-free month.
  Treasury data is checked for per-ID classification, scope precedence,
  duplicates, adjustments and corrected opening balances.

All financial conventions, editable ranges, 0.005 absolute tolerance, scenario
overrides, renewal timing, audit purpose, sensitivity cases and JSON schemas
are public at the stage where they apply. No exact target-formula strings or
ZIP serialization are graded. Objects may include extra explanatory fields;
treasury item ordering does not matter.

Oracle development caught one serialization-only false positive before any
target-model trial: openpyxl dropped an explicit zero outline-level attribute.
The grader now normalizes omitted and zero outline metadata, while retaining
actual grouping/dimension checks. The original rejected oracle remains
disclosed rather than represented as a financial or agent failure.

## Author controls

[tests/controls.py](tests/controls.py) exercises two positive cases (the correct
final package and equivalent revenue-reference formulas) and ten faults:

1. Legacy method not replaced.
2. Calendar-immediate pricing not replaced.
3. Board figures stale after cutover.
4. Constant-zero controls.
5. Withdrawn DSO and capex stresses layered onto the new stress.
6. Still-required stress inputs incorrectly withdrawn.
7. Authorized cutover not propagated.
8. Cutover applied before authorization.
9. Duplicate bank export counted twice.
10. Treasury detour deliverable lost.

Controls are not model runs. Their purpose is to demonstrate useful rejection
and acceptance boundaries, not to claim a frontier-model failure.

## Results

The six-stage Harbor oracle (`northstar-followups-oracle-02`) passes every
reward component at every stage. The original development oracle had the
outline-serialization-only failures described above; its numerical, sensitivity
and artifact checks passed and it is not treated as an agent failure.

All twelve author controls behaved as expected: two valid packages pass and
all ten deliberate regressions fail. Seventeen hand-derived financial
witnesses independently confirm delayed July adoption, multiple queued uplifts,
December events outside the 2026 renewal window and cutover interest.
Treasury net adjustments are -330 cash and +1,500 revolver, producing opening
cash 29,670 and debt 31,500. January interest then becomes 262.50 and net income
18,710.625, with no second cash posting of the cutover.

Eight author-only randomized agreement cases (fixed seed 20261023) also passed:
for each, all 1,222 expected monthly/annual values from the independent Decimal
reference agree with the oracle workbook recalculated by LibreOffice. These
change additions, churn, launch prices and multiple calendar price events.
They validate the reference/oracle relationship; they are not extra hidden
model acceptance tests or model-failure evidence.

The frozen task was separately exported and freshly extracted, then passed all
six Harbor oracle milestones (`northstar-followups-zip-oracle-01`). Its task
inputs match the evaluated hashes; no private local state was needed.

### Target-model trial

`northstar-followups-copilot-opus-01`, trial
`northstar-forecast-followups__EeQUw2d`, used Harbor 0.24.0, Copilot CLI 1.0.102,
`claude-opus-5.5`, and requested reasoning effort `high`. The recorded command
includes `--resume-trajectory`; all five follow-ups invoke native `--continue`.
Every stage's saved native state contains the same session ID:
`e27c118d-ba7a-4711-ab7e-8ccd13a3082b`.

| Stage | Agent execution | Overall | Functional | Constraints | Robustness | Artifacts |
|---|---:|---:|---:|---:|---:|---:|
| 01-growth | 143.56 s | 1 | 1 | 1 | 1 | 1 |
| 02-cohort-revision | 65.54 s | 1 | 1 | 1 | 1 | 1 |
| 03-liquidity-continuation | 43.23 s | 1 | 1 | 1 | 1 | 1 |
| 04-treasury-detour | 25.91 s | 1 | 1 | 1 | 1 | 1 |
| 05-renewal-pricing | 114.63 s | 1 | 1 | 1 | 1 | 1 |
| 06-reconciled-cutover | 80.96 s | 1 | 1 | 1 | 1 | 1 |

Total recorded trial wall time was **634.74 seconds (10m35s)**, with approximately
473.84 seconds of agent execution. No step or trial exceptions occurred.
There were no target-model repeats, timeout failures or post-hoc grading
corrections. Inputs were frozen at the start of the model experiment; their
hashes are checked again during packaging.

### What happened instead of the hypothesized failure

The model replaced the revenue method rather than blending it, extended the
existing model for the stress, completed the treasury switch, returned to the
renewal policy in both workbooks and selectively replaced the final stress.
All public input sensitivities and live control audits pass independently;
the pass is not based on the model's completion claims.

The baseline workbook, stress workbook, handoff and board pack are all
**byte-identical between stages 03 and 04**. That is additional observed
evidence that the model respected the detour's instruction not to apply the
cutover or disturb existing financial work. The authorized cutover then
propagates correctly at stage 06, without a duplicate January posting.

The higher reasoning time for the pricing revision is descriptive only, not
evidence of weaker performance. This one sequence does not substantiate the
hypothesis that follow-up revisions expose a capability gap. A matched
all-at-once final-request condition and multiple fresh trials would be needed
to estimate a causal revision penalty. The earlier combined Northstar task is
not a matched control because it lacks the stress, treasury and renewal work.

### Evidence index

- [Run metadata, stage rewards, continuity and retention hashes](evidence/runs.json).
- [Frozen candidate/oracle/verifier input hashes](evidence/frozen-inputs.json).
- [Oracle stage results](evidence/oracle/result.json) and
  [exported-core oracle](evidence/exported-core-oracle/result.json).
- [Original model result](evidence/copilot-opus-01/result.json) and
  [native command log](evidence/copilot-opus-01/trial.log).
- [Final stage detailed checks](evidence/copilot-opus-01/steps/06-reconciled-cutover/verifier/checks.json)
  and [native events](evidence/copilot-opus-01/steps/06-reconciled-cutover/agent/copilot-cli.jsonl).
- [Collected final baseline workbook](evidence/copilot-opus-01/steps/06-reconciled-cutover/artifacts/app/output/Northstar_Forecast_Completed.xlsx),
  [stress workbook](evidence/copilot-opus-01/steps/06-reconciled-cutover/artifacts/app/output/Northstar_Liquidity_Stress.xlsx),
  [handoff](evidence/copilot-opus-01/steps/06-reconciled-cutover/artifacts/app/output/handoff.json),
  [board pack](evidence/copilot-opus-01/steps/06-reconciled-cutover/artifacts/app/output/board-pack.json)
  and [reconciliation](evidence/copilot-opus-01/steps/06-reconciled-cutover/artifacts/app/output/treasury_reconciliation.json).
- [Twelve control results](evidence/controls/summary.json),
  [hand witnesses](evidence/hand-witnesses.json) and
  [seeded reference agreement](evidence/seeded-reference-agreement.json).

Each collected stage also contains its original workbook/JSON artifacts and
verifier output. No active GitHub token is saved into the package: evidence is
scanned/redacted for the token and recognizable GitHub token patterns before
archiving. Native session databases, personal keychain data and credential
stores are not bundled.

## Reproduction commands

From the directory containing the single task directory:

```sh
uv tool install harbor==0.24.0
harbor run -p ./northstar-forecast-followups -a oracle

token="$(gh auth token)" || exit 1
COPILOT_GITHUB_TOKEN="$token" harbor run \
  -p ./northstar-forecast-followups \
  -a copilot-cli -m claude-opus-5.5 --effort high \
  --ak version=1.0.102 --resume-trajectory
unset token

harbor view ./jobs
```

Each step declares `/app/output` as an artifact, so its workbook and JSON
package are collected before grading. The model trial is Copilot CLI, not
native Claude Code; it cannot be represented as the assignment's native
Claude Code evidence. If native authentication is available:

```sh
# The assignment's spelling; Harbor 0.24 uses claude-code rather than claude.
harbor run -p ./northstar-forecast-followups -a claude -m opus-5-5

# Actual Harbor 0.24 adapter, high effort and session continuation:
harbor run -p ./northstar-forecast-followups \
  -a claude-code -m opus-5-5 --effort high --resume-trajectory
```

Without `--resume-trajectory`, Harbor preserves the filesystem but starts fresh
conversations. That is a different condition, not an equivalent reproduction.
In this task the oracle uses its normal root `solution/solve.sh` fallback
and a private sequential phase counter; oracle runs do not need native resume.

To run the non-model regression controls using the oracle's collected snapshots:

```sh
harbor run -p ./northstar-forecast-followups -a oracle --job-name followups-oracle
docker build -t northstar-followups:author ./northstar-forecast-followups/environment
mkdir -p author-controls
ORACLE_TRIAL="$(find ./jobs/followups-oracle -maxdepth 1 -type d -name 'northstar-forecast-followups__*')"
docker run --rm --network none \
  -v "$PWD/northstar-forecast-followups/tests:/tests:ro" \
  -v "$PWD/$ORACLE_TRIAL/steps:/samples:ro" \
  -v "$PWD/author-controls:/logs/controls" \
  northstar-followups:author python /tests/controls.py
```

## Provenance and limitations

The workbook, business data and common financial schedules extend the earlier
Northstar task authored in this same exercise. The sequential requests,
quarterly renewal policy, staged treasury exports, stress revision, oracle,
phase-aware reference/grader and regression controls were newly created for
this experiment. This is an explicitly disclosed derivative **within the same
exercise**, not six unrelated tasks and not a claimed independent dataset.
No public benchmark, issue, CTF, tutorial, external financial dataset or
proprietary workbook was copied.

Python (PSF), openpyxl (MIT), et_xmlfile (MIT), LibreOffice (MPL-2.0 and upstream
notices) and Debian dependencies retain their upstream licenses. Harbor and
Copilot CLI are external evaluation tools. Harbor's public
[multi-step documentation](https://docs.harborframework.com/tasks/multi-step.md)
was used to confirm the task format and invocation.

A pass would not prove resistance to all revisions; a failure would not alone
prove revision handling is worse than a length-/difficulty-matched static
control. Causal attribution would need paired trials across conditions.
This first experiment tests whether this particular realistic sequence exposes
a substantive failure at all.
