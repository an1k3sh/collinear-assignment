# Chart capacity audit v2

One original Harbor task: reconstruct an operations review from raster exports,
resolve corrected evidence, and produce a replayable, resource-constrained
capacity proposal. This is a separate revision; v1 and its passing model trial
have not been overwritten.

**Status:** validated oracle and verifier; no v2 frontier-model trial yet.
There is no claimed model failure. See [RUN_REPORT.md](RUN_REPORT.md).

## Why this is a longer, more realistic task

The candidate acts as an SRE reviewing a change request assembled from exported
dashboards after the original time series became unavailable. Finance needs
an auditable allocation, not a screenshot-based ranking.

The evidence covers eight service/region targets, four unequal-duration windows,
five cumulative-counter pages (including an obsolete revision), four latency
histogram pages, an exporter operations log, a registry, and planning policies.
There are 228 individual metric/bin reading checks and 32 interval decisions.

Linked responsibilities:

1. **Source reconciliation:** preserve all observations, but resolve whole-page
   supersession before calculating totals.
2. **Instrument reconstruction:** treat counter resets per metric, use exact
   reset baselines, and distinguish genuinely missing traffic from an old epoch's
   missing sample that no longer matters.
3. **Sample population reasoning:** join latency only with usable traffic and
   pool disjoint counts rather than averaging percentages or window percentiles.
   A target with three slow windows is not necessarily slow after pooling.
4. **Constrained planning:** separate latency eligibility from regional freezes;
   optimize tiers under credits, activation charges, power, regional block caps,
   and limits on active regions.
5. **Decision verification:** propagate reading uncertainty, cancel shared
   target allocations when comparing rivals, account for unserved risk, and
   independently optimize two budget scenarios.
6. **Audit and handoff:** adjudicate eight claims, preserve intermediate evidence,
   and deliver a standard-library program that works on changed valid inputs and
   rejects malformed ones.

This resembles real incident/change-review work where joins, metric semantics,
revision authority, sample weighting and operational constraints matter more than
an attractive chart. Errors can misdirect capacity spending or violate a change
freeze. Credits and risk reductions are explicitly synthetic planning valuations,
not predictions of measured production treatment effects.

## Candidate and author boundaries

Start with [instruction.md](instruction.md). Candidate-visible material is only
[environment/app](environment/app); the Dockerfile copies nothing else.
The [offline viewer](environment/app/report/index.html) displays raster images
and supports full-resolution zoom. It contains no machine-readable source values.

The candidate produces five files under `/app/submission`: readings, reusable
analysis program, numerical result, claim audit and decision memo. Complete
contracts and tolerances are public in
[interfaces.md](environment/app/interfaces.md) and
[policy.md](environment/app/policy.md).

Author-only material:

* [author/render.py](author/render.py): original fixture construction and rendering.
* [solution](solution): oracle readings, program, memo and claim audit.
* [tests/reference.py](tests/reference.py): independent Decimal reconstruction and
  resource-pruned optimizer. It imports neither the oracle nor candidate program.
* [tests/grade.py](tests/grade.py): functional checks and fresh executable probes.
* [tests/test_verifier.py](tests/test_verifier.py): hand-calculated witnesses.
* [tests/author_check.py](tests/author_check.py): acceptance/rejection controls.
* [evidence](evidence): oracle logs and author-validation results.

Do not expose author-only files to the candidate before or during a trial.

## Fairness and verifier design

The task is not a tiny-text test. All nine PNGs have readable numerical labels;
exact readings, manual transcription and native image tools are allowed.
Request-counter, error-counter and histogram interval widths are public.
Missingness, units, reset timing, exclusion precedence, histogram semantics,
tie-breaking and supported input changes are specified.

The verifier computes from the **candidate's readings**, then checks those readings
against the images' private generating values. It accepts valid approximate
estimates, rather than matching one oracle JSON file. A 98% extraction floor
tolerates a small number of isolated reading mistakes; missingness and substantive
downstream decisions remain mandatory.

The nominal decision is unchanged even across an envelope that contains every
permitted reading interval. This was calculated before any v2 model trial.
No marginal chart reading is needed to distinguish the winner.

Six separately reported reward components:

| Component | Weight | Checks |
|---|---:|---|
| Extraction | 20% | 228 counter metrics/bin observations and missingness |
| Reconciliation | 20% | Source inventory and 32 interval decision families |
| Calculations | 20% | Eight target summaries and fleet totals |
| Planning | 20% | Nominal plan/certificate and two budget scenarios |
| Claims | 10% | Eight verdicts and declared evidence sources |
| Reproducibility | 10% | Fresh original run, valid changes, invalid inputs, memo presence |

Mandatory gates zero overall on substantive failure, while preserving diagnostic
component scores. The reproducibility check executes 20 valid counterfactuals
and 10 malformed-input probes. Changes include source authority, page IDs,
missingness, maintenance, reset baselines, durations, uncertainty, costs, weights,
freezes and independently binding resource limits. A static answer cannot pass.
The full categories, rather than private fixture values, are public.

There is no LLM judge, source-code similarity check, speed bonus or
pixel-difference grading. Prose presence and evidence identifiers are checked;
prose quality and causal explanations still need human review.

## Reproduction

Requires Docker and Harbor. Validation used Harbor **0.24.0**, pinned Python
**3.12.12** with the image digest in
[environment/Dockerfile](environment/Dockerfile), on macOS ARM64 with Docker.
The task runtime and verifier need only Python's standard library. Committed
charts mean no rendering dependency or network access is needed for solving.

From the directory containing this task:

```sh
harbor run -p ./chart-capacity-audit-v2 -a oracle
harbor run -p ./chart-capacity-audit-v2 -a claude -m opus-5-5
harbor view ./jobs
```

For the pinned Harbor version without a global install:

```sh
uvx --from harbor==0.24.0 harbor run -p ./chart-capacity-audit-v2 -a oracle
```

The Claude command is the assignment's provider-dependent model alias, not a
completed trial. Configure provider credentials, image-capable Claude Code and
high reasoning before running; verify the actual resolved model/effort in the
trajectory. Native harness installation and inference require network and
credentials. No credentials belong in the task or evidence archive.

The previous v1 comparison used Copilot CLI 1.0.102:

```sh
harbor run -p ./chart-capacity-audit-v2 -a copilot-cli \
  -m claude-opus-5.5 --ak reasoning_effort=high --ak version=1.0.102
```

This is an optional comparison recipe, not evidence that v2 has been tested,
and not a substitute for the assignment's requested native Claude Code run.
Network policy in the metadata permits harness setup/inference; task data,
viewer, calculations and verifier are entirely offline.

Run author tests from the task root with Python 3.12:

```sh
python -m unittest discover -s tests -p test_verifier.py -v
python tests/author_check.py /tmp/chart-v2-controls
```

For a network-disabled container check:

```sh
docker build -t chart-capacity-v2-author environment
mkdir -p /tmp/chart-v2-controls
docker run --rm --network none \
  -v "$PWD:/task:ro" -v /tmp/chart-v2-controls:/evidence \
  chart-capacity-v2-author python /task/tests/author_check.py /evidence
```

Only authors need chart-rendering dependencies:

```sh
python3.12 -m venv /tmp/chart-v2-render
/tmp/chart-v2-render/bin/pip install -r author/requirements.txt
/tmp/chart-v2-render/bin/python author/render.py
```

The renderer recreates charts and private generating values. If evidence is
changed, regenerate oracle readings and protected-file hashes and rerun all
checks **before** freezing a new trial. Do not edit a frozen task during a run.

## Originality and limitations

Created for this exercise. The
scenario, values, revision/reset history, policy, oracle and verifier were written
for this task. It extends the same author's chart v1 exercise; it does not port
a public benchmark, issue, CTF or external dataset. Matplotlib, NumPy and Pillow
are ordinary author-time dependencies; no third-party incident data or chart
content is included.

This is bounded synthetic operations work, not a deployed system. Labels
deliberately reduce pure optical difficulty. The intended challenge is coherent
evidence-to-decision reasoning and reusable implementation. Greater complexity
does not establish a capability failure: only a frozen target-model trial can do
that. Successful browser QA is not proof that a future harness can read images;
verify actual image payloads before attributing any failure to chart reasoning.
