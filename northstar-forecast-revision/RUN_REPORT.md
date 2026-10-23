# northstar-forecast-revision: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `northstar-copilot-opus-02` | `copilot-cli` / `claude-opus-5.5` | 0.0 | Historical raw result; consult detailed fairness analysis, not automatically a model failure |
| `northstar-copilot-opus-03` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./northstar-forecast-revision -a oracle
harbor run -p ./northstar-forecast-revision -a claude -m opus-5-5
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

# Northstar forecast revision

## Status and experimental claim

**The substantive failure objective has not been achieved.** The offline Docker
oracle and actual Harbor oracle pass every reward component. The first executed
Copilot CLI Opus 5.5 high trial passes the baseline, all four sensitivity cases,
formatting preservation and handoff. Its only raw failure was a verifier false
positive; the unmodified reconstructed solution passes the corrected grader.
A fresh repeat against the corrected grader also passes all five reward values.

This is a **combined-prompt revision-tracking experiment**. The single
[instruction](instruction.md) presents the original A/B/C commission and a
clearly superseding CFO memo replacing B with D/E/F. Both appear before the
agent starts. It does **not** measure an instruction delivered after the model
has already committed to an initial plan. A pass or failure here cannot by
itself establish the stronger hypothesis that models are weaker under actual
mid-execution revisions.

Copilot CLI is not native Claude Code. Its results cannot be represented as
satisfying the assignment's native-harness evidence requirement. No setup,
authentication, build or provider-compatibility error counts as model failure.

## Idea and economic connection

An FP&A analyst inherits a formatted forecast commissioned under a now-obsolete
growth-rate method. Finance changes the revenue methodology, but still needs
the original driver schedule, working-capital forecast, operating model, cash
waterfall, debt roll-forward and controls. The final artifact must survive
realistic source-input changes without sacrificing the workbook's presentation.

This mirrors recurring budgeting work: a valid methodological change is
incomplete if payroll stays frozen, AR still follows old revenue, July price
increases leak into later acquisition cohorts, closing-debt interest creates
cycles, or the model's controls merely report reassuring zeros.

The business is synthetic and the model deliberately simplified. It is not a
complete audited three-statement or GAAP revenue-recognition model.

## Linked subgoals

1. Inspect the ten-sheet starter and preserve the distinction between sources,
   unfinished targets and existing formulas.
2. Resolve the revised instruction hierarchy: retain A/C, replace B rather than
   blend methods, and retain the unused legacy driver for audit.
3. Model thirteen cohorts with different existing/new churn conventions,
   launch-month treatment, and calendar-month pricing.
4. Propagate revenue into operating earnings, day-based AR/AP and cash/debt
   schedules without introducing a circular interest reference.
5. Verify baseline and sensitivity results, live controls, workbook preservation
   and agreement with the durable JSON handoff.

There are 1,020 formula targets; this is not presented as 1,020 independent
reasoning challenges. The meaningful work is dependency modeling, state
tracking, financial conventions and verification. Difficulty must ultimately
be judged from a real agent trajectory, not the raw cell count.

## Verifier design

[tests/test.sh](tests/test.sh) writes
`/logs/verifier/reward.json` and `/logs/verifier/checks.json`.

The core grader does not import the oracle, compare target-formula strings,
require one editing library, grade narrative wording, or judge a trajectory.

- **Functional correctness:** LibreOffice recalculates a disposable submitted
  workbook. An independent Decimal implementation evaluates cohort survival
  and pricing as products over age intervals rather than copying the oracle's
  spreadsheet recurrences. Every monthly target, linked financial output and
  annual/exit summary is checked within the public 0.005 absolute tolerance.
- **Constraint satisfaction:** compare parsed workbook semantics against a
  trusted verifier-only template: immutable values/formulas, sheet structure,
  cell styles/comments, dimensions, print settings, chart/placement,
  validation and conditional formatting. XML order, ZIP bytes, cached values
  and target-formula spelling do not matter.
- **Robustness:** four fully disclosed sensitivity cases exercise abandoned-
  method independence, churn, additions, cohort-specific starting prices,
  calendar uplifts, source-to-driver links and liquidity. A separate disclosed
  fault audit changes January intermediate outputs and independently computes
  the residuals the checks must expose. This rejects zero-plug controls.
- **Artifact quality:** require a readable workbook and JSON object with method
  identifiers and independently correct baseline summary values.

Each category reports a fractional score. `overall` is 1 only when all four
categories pass completely. Per-cell style checks produce many assertions;
they are not treated as more important than financial correctness.

Original template copies are in the environment seed and verifier fixture.
Only the environment seed is present during the candidate's work; neither
oracle code nor expected outputs are copied into the task environment.

## Author iteration and fairness audit

- The workbook was generated for this exercise, then adapted to one combined
  brief. The obsolete method is explicitly superseded; no hidden instruction
  or surprise change is required.
- A direct preservation self-check found that comparing two openpyxl
  `StyleProxy` instances rejects even an identical workbook. This false
  positive was fixed by comparing copied underlying style objects before the
  evaluated task was frozen.
- Harbor 0.24 Docker rejects verifier-only `no-network` phase overrides.
  The unsupported override was removed before the actual model trial.
  Metadata now accurately declares public harness networking; a separate
  `docker run --network none` oracle proves the task/verifier themselves
  operate without network access.
- The rubric's `-a claude` command is not an installed Harbor 0.24 agent name.
  The native adapter is `claude-code`. The initial CLI rejection did not start
  a model session and is not a capability failure.
- Two hours of agent time, 4 GB RAM, two CPUs and a 15-minute verifier allowance
  avoid an artificially short time budget. LibreOffice and Python packages
  are installed in advance; no task-time dependency installation is needed.
- All target ranges, financial conventions, tolerance, handoff schema,
  sensitivity cases and control-audit purpose are public.
- Recalculation happens on disposable copies so LibreOffice serialization
  cannot falsely fail the submitted file's formatting preservation.
- Full-precision formulas are required; cached results are optional.
- The financial oracle passed both directly offline and through Harbor.

The original evaluated inputs are indexed in
[evidence/frozen-inputs.json](evidence/frozen-inputs.json). The original grader
and controls are preserved in [evidence/pre-fairness-fix/](evidence/pre-fairness-fix/).
The release input hashes separately record the fairness correction below and a
final nonfunctional Docker cleanup change: apt's temporary list directory is
removed explicitly rather than through a wildcard. The dependency versions,
candidate instruction and financial conventions were not changed. Both model
trials used the original, also preserved, Dockerfile. The release archive is
separately checked with an oracle after that cleanup change.

## Measured results

| Run | Harness | Result |
|---|---|---|
| Offline oracle | Direct pinned Docker image, no network | All five reward values 1.0 |
| `northstar-oracle-02` | Harbor 0.24.0 oracle | All five reward values 1.0; no exception |
| `northstar-copilot-opus-02` | Copilot CLI 1.0.102; `claude-opus-5.5`; requested effort `high` | Raw overall 0; rejected false positive; corrected regrade all 1.0 |
| `northstar-oracle-03` | Harbor 0.24.0 oracle; corrected grader | All five reward values 1.0; no exception |
| `northstar-copilot-opus-03` | Fresh Copilot CLI 1.0.102; same model and high effort; corrected grader | All five reward values 1.0; no exception |
| `northstar-zip-oracle-01` | Extracted release ZIP; new Harbor build; final cleanup Dockerfile | All five reward values 1.0; no exception |

The passing oracle has 1,232 functional assertions, 16,914 constraint assertions,
4,938 robustness assertions and 10 artifact assertions. The high assertion
count is mainly semantic cell preservation, not evidence of task difficulty.

Baseline witnesses independently agreed with LibreOffice:

| Metric | Value |
|---|---:|
| January customers | 1,020 |
| January revenue | $123,000 |
| January net income | $18,720 |
| January closing cash | $20,000 |
| January closing revolver | $6,683.22580645 |
| FY2026 revenue | $1,772,564.52101988 |
| December customers | 1,352.64897118915 |
| December closing cash | $274,738.507762398 |
| December closing revolver | $0 |

Author controls are defined in [tests/controls.py](tests/controls.py). Both
positive controls passed and all ten negative controls were rejected before
the fairness fix. The corrected suite additionally exercises the P&L revenue
alias within its equivalent-formula positive control; both positives pass
and all ten negatives are still rejected.

## Why the first raw zero is not a model failure

The only rejected assertion was the January AR-days residual during the
deliberately inconsistent audit. The candidate used:

```text
AR / P&L revenue * days - DSO
```

The verifier assumed:

```text
AR / Revenue-sheet revenue * days - DSO
```

Both are correct under the public brief's unqualified "revenue" convention.
The audit deliberately overwrote these revenue aliases with different values,
making them diverge only in that inconsistent copy. The original residuals
were 0.0513972380178771 versus 0.0716253891360239; no financial forecast was
wrong. Treating that as a capability failure would violate the fairness goal.

The correction accepts the legitimate revenue aliases in this one audit
assertion. It does not relax baseline accuracy, source sensitivities,
formatting, or the requirement for live, nonconstant checks. The alternate-
formula positive control now covers the candidate's valid denominator.

The original container had already been removed without artifact collection.
Its unmodified build and verification scripts and original 513-byte handoff
were recovered from the native tool events. The build script deterministically
patches the trusted seed's XML and preserves ZIP entry metadata. Running that
script regenerated the 57,353-byte submission and reproduced the original
single-failure reward exactly. That same reconstruction passes the corrected
grader with every reward value 1.0. This is explicitly a reconstruction/regrade,
not a second original model run or a claim of a previously recorded byte hash.
The fresh repeat enables Harbor artifact collection.

The original trial took about 3m18s overall, including about 2m24s of agent
execution. The model inspected the workbook, implemented the revised method
and independently validated the public sensitivities and a fault audit.
This is evidence against this particular combined brief being a hard
long-horizon failure task. It is not evidence about true mid-run interruptions.
The fresh repeat passed in about 3m10s overall, including about 2m27s of agent
execution. Neither run timed out or had a trial exception.

## Evidence index

- [Run metadata and results](evidence/runs.json): harness/model/effort,
  timestamps, task checksums and all measured rewards.
- [Original frozen inputs](evidence/frozen-inputs.json) and
  [release input hashes](evidence/release-inputs.json): distinguish the measured
  original, fairness correction and final Docker cleanup.
- [First trial's raw checks](evidence/copilot-01-original/verifier/checks.json)
  and [native events](evidence/copilot-01-original/agent/copilot-cli.jsonl).
- [Unmodified reconstruction](evidence/copilot-01-reconstruction/build.py),
  [reproduced raw reward](evidence/copilot-01-reconstruction/replay-original/reward.json)
  and [corrected regrade](evidence/copilot-01-reconstruction/regrade/reward.json).
- [Fresh repeat's reward](evidence/copilot-02-release/verifier/reward.json),
  [native events](evidence/copilot-02-release/agent/copilot-cli.jsonl) and
  [collected workbook](evidence/copilot-02-release/artifacts/app/output/Northstar_Forecast_Completed.xlsx).
- [Original control results](evidence/controls-original/summary.json) and
  [corrected control results](evidence/controls-release/summary.json).
- [Exported-archive oracle result](evidence/release-archive-oracle/result.json)
  and [reward](evidence/release-archive-oracle/verifier/reward.json): the
  packaged task's core inputs build and pass independently of the author tree.

Authentication values are not required for any of this evidence. Collected
text is scanned/redacted for the active token and recognizable GitHub token
patterns before packaging; no token is stored in the submission.

## Reproduction

Use Docker and Harbor 0.24.0. From the directory containing this one task:

```sh
uv tool install harbor==0.24.0
harbor run -p ./northstar-forecast-revision -a oracle
harbor view ./jobs
```

The assignment's requested native command is:

```sh
harbor run -p ./northstar-forecast-revision -a claude -m opus-5-5
```

For Harbor 0.24.0, use its actual adapter name and request high effort:

```sh
# Requires native Claude authentication configured outside the task.
harbor run -p ./northstar-forecast-revision \
  -a claude-code -m opus-5-5 --effort high
```

The user specifically requested the following Copilot alternative. This does
not print the token, put it on the command line, or save it into the task:

```sh
token="$(gh auth token)" || exit 1
COPILOT_GITHUB_TOKEN="$token" harbor run -p ./northstar-forecast-revision \
  -a copilot-cli -m claude-opus-5.5 --effort high --ak version=1.0.102 \
  --artifact /app/output
unset token
```

To reproduce author controls without any model or authentication:

```sh
docker build -t northstar-forecast-revision:author ./northstar-forecast-revision/environment
mkdir -p author-output author-verifier author-controls
docker run --rm --network none \
  -v "$PWD/northstar-forecast-revision/solution:/solution:ro" \
  -v "$PWD/northstar-forecast-revision/tests:/tests:ro" \
  -v "$PWD/author-output:/app/output" \
  -v "$PWD/author-verifier:/logs/verifier" \
  -v "$PWD/author-controls:/logs/controls" \
  northstar-forecast-revision:author \
  sh -c '/solution/solve.sh && /tests/test.sh && python /tests/controls.py'
```

The container base is digest-pinned. Debian package selection is frozen to
the 2026-02-01 snapshots; Python dependencies and the measured Copilot CLI
version are pinned. Builds need access to Docker Hub, Debian snapshots and
PyPI. Copilot setup/inference additionally needs the GitHub/Copilot services.
No secrets or network calls are required to solve or grade the financial task.
The tested platform was Linux/arm64 through Docker Desktop on macOS, with
Python 3.12.12, LibreOffice 7.4.7.2 (`4:7.4.7-1+deb12u10`), openpyxl 3.1.5
and et_xmlfile 2.0.0.

## Originality and provenance

The company, historical data, forecast assumptions, styled workbook, CFO
revision, oracle formulas, independent numerical reference, fault controls and
grader were created from scratch for this assignment. This extends the
workbook created earlier in this same exercise; it is not copied from another
Collinear task or from a public issue, tutorial, benchmark or financial model.
No external financial dataset, workbook or proprietary material was used.

Third-party runtime dependencies are Python (PSF license), openpyxl (MIT),
et_xmlfile (MIT), LibreOffice (MPL-2.0 and upstream notices) and Debian packages
under their respective upstream licenses. Harbor and Copilot CLI are external
evaluation tools, not original task implementations. Upstream license notices
remain in their installed packages.

Public Harbor documentation was used only to confirm task layout, metadata
and agent invocation conventions:
<https://docs.harborframework.com/tasks/overview> and
<https://docs.harborframework.com/tasks/configuration>.
