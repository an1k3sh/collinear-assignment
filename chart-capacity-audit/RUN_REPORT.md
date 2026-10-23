# chart-capacity-audit: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `chart-capacity-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./chart-capacity-audit -a oracle
harbor run -p ./chart-capacity-audit -a claude -m opus-5-5
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

# Chart-capacity audit: validation report

## Status

The oracle and Claude Opus 5.5 high both pass with all six reward fields at
1.0. **No model failure was demonstrated.** The model trial used Copilot CLI
1.0.102, with confirmed native image access.

## Target-model trial: chart-capacity-copilot-opus-01

Trial `chart-capacity-audit__9GkfHdD` completed in 4 minutes 26 seconds overall.
Actual agent execution was approximately 2 minutes 23 seconds. The trajectory
confirms model `claude-opus-5.5`, high reasoning, and Copilot CLI 1.0.102.
All 28 frozen task files matched their pre-run hashes after completion.

All 32 extraction records, five calculation families, the allocation family,
six memo claims and four reproducibility families passed. The submitted program
also passed all twelve counterfactual cases and five invalid-input checks.
There were no verifier errors or infrastructure exceptions.

### Confirmed visual access

The trajectory records successful native `view` calls for P1, P2, P3 and P4.
Each returned an image in `binaryResultsForLlm`, not just a textual file path.
The model attempted optional crops using Pillow, discovered it was not
installed, then continued successfully using the original full-resolution
images. No crop dependency was required by the task; this did not prevent
visual access or cause a failure.

The model transcribed the chart values, implemented reusable analysis with
exact rational arithmetic, and produced the correct allocation and claim
audit. This was a genuine observed pass, not evidence that the model ignored
the charts or obtained raw data from the author files.

### Interpretation

This particular chart task did not expose the hypothesized weakness. Its
legible, grid-aligned observations and explicit policy were solved quickly;
the observed execution time also provides weak support for calling it a
long-horizon challenge for this model. Do not relabel the optional crop error
as a substantive task failure or alter the grader retrospectively.

Evidence: [original reward](evidence/opus-copilot-01/reward.json),
[all checks](evidence/opus-copilot-01/details.json),
[trajectory](evidence/opus-copilot-01/trajectory.json),
[model deliverables](evidence/opus-copilot-01/submission/),
[frozen hashes](evidence/opus-copilot-01/frozen-files.json).

## Task and long-horizon structure

The agent must inspect four original raster charts, extract 32 region/window
records, distinguish missing observations from maintenance and ordinary data,
join traffic and failure percentages, calculate weighted totals, apply a
latency eligibility rule, optimize a discrete allocation and certify it under
reading uncertainty. It must then reconcile six memo claims and produce an
analysis script that works on changed inputs.

The script requirement makes the result durable and testable. It is not a
requirement to build OCR or an image-processing pipeline: tool-assisted visual
reading and manual transcription are allowed.

## Visual fairness

* P1/P2 are 1800x1200 PNGs; P3/P4 are 1800x840.
* All four images were opened and visually inspected by the authoring assistant.
* Axis labels, units, region names and window IDs are readable; no overlapping
  series or hidden legends are necessary to identify observations.
* P1 uses separate explicitly labelled scales, all starting at zero.
* P3 uses numerical labels rather than requiring precise color interpolation.
* Unknown intervals are labelled and hatched, not represented as zero.
* Browser validation confirmed all four images load and the zoom button gives
  1800-pixel-wide images. No data arrays or numerical hover values are embedded
  in the HTML. PNG metadata was stripped.

This confirms the deliverable is viewable in the authoring environment.
The eventual trial harness still needs a verified image-capable tool. A
text-only trajectory would not be valid chart-reasoning evidence.

## Reading uncertainty cannot flip the correct decision

Published maximum interval widths are 100 requests/minute, 0.5 percentage
points and 10 ms. Intervals must contain their estimates and the plotted values.
The numerical calculation tolerance is separate from these visual intervals.

For the report's allocation, independent interval arithmetic gives:

| Input intervals | Worst difference from a competing allocation |
|---|---:|
| Exact readings | 1,518 benefit units |
| Oracle's symmetric intervals | 990 benefit units |
| Envelope containing EVERY permitted reading interval | 270 benefit units |

Every possible admissible interval endpoint lies within one full allowed width
of the true value. Bounding all such endpoints simultaneously still leaves a
positive margin. Eligibility is likewise separated from its threshold by more
than the maximum latency-reading width.

This is stronger than checking only one convenient extraction. A valid
approximate reading cannot be penalized for changing an inherently ambiguous
decision. The acceptance controls deliberately perturb readings and still
earn full reward.

## Verifier design

The verifier uses private source data only for reading accuracy, interval
coverage and broad demand envelopes. It independently recalculates results
from the candidate's OWN readings, using Decimal arithmetic, and accepts
approximate readings. It checks ordered eligibility windows, actual demand
denominators, integer allocation, objective bounds and the robustness margin.

It executes the submitted program afresh on the original observations and
twelve valid counterfactual inputs: different durations, statuses, rates,
budgets, fractions, latency thresholds, zero demand, tie-breaking, reordered
records and a single-window case. Five malformed inputs must produce explicit
failure diagnostics. No timing race, network service or LLM judge is involved.

The memo audit checks verdicts and panel/region/window evidence, not exact
explanation strings. The Markdown report is for human review; prose quality
is not scored. This means the automated verifier cannot catch every possible
misleading sentence when the structured answers are correct.

## Measured validation

* Native Harbor job `chart-capacity-oracle-01`: overall 1.0, no exceptions,
  approximately nine seconds.
* Six author unit tests passed: hand-calculated totals, worst-case reading
  robustness, status semantics, counterfactual boundaries, claim evidence,
  and score gates/arithmetic.
* Three positive controls passed: oracle, perturbed approximate readings and
  reordered observation records.
* Untouched baseline and ten faulty controls scored zero overall: wrong-axis
  readings, maintenance inclusion, unknown-as-zero, unweighted fleet rate,
  missing duration conversion, wrong allocation, causal overclaim, static
  output program, false robustness margin and wrong panel citation.

Evidence is in [evidence/author/summary.json](evidence/author/summary.json) and
[evidence/harbor-oracle/](evidence/harbor-oracle/).
The tests reduce grading errors but do not prove universal verifier correctness.

## Guidance for further experiments

For any further trial, verify visual access, keep the task frozen, and
inspect both structured outcomes and trajectory. A meaningful failure analysis
should identify a concrete incorrect reading, lost exclusion, denominator error,
misaligned evidence or invalid allocation. An image-access failure, parser-only
artifact issue, or timeout caused by the environment is not the desired result.

The charts are intentionally readable and the allocation rule explicit.
A strong model may pass. Do not claim demonstrated long-horizon difficulty or
retroactively change the grading criteria to turn a pass into a failure.
