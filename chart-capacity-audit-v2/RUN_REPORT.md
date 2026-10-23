# chart-capacity-audit-v2: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `chart-capacity-v2-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./chart-capacity-audit-v2 -a oracle
harbor run -p ./chart-capacity-audit-v2 -a claude -m opus-5-5
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

# Validation and experiment report

## Experiment status

**No v2 target-model trial has run. No v2 model failure is claimed.**

The earlier chart v1 task genuinely passed Opus 5.5 high through Copilot CLI
1.0.102: all components 1.0, approximately 4m26s total and 2m23s agent execution.
Its trajectory contained native image payloads. That result motivated a revision
with linked operational semantics, not merely more charts or smaller labels.
Earlier task files, rewards and archives were preserved separately.

Potential failure mechanisms for v2 are hypotheses: wrong revision authority,
confusing resets with negative demand, dropping recoverable traffic, averaging
percentiles, forgetting a rollout constraint, or reusing a nominal answer without
verification. They must not be presented as observed model behavior.

## Completed validation

* All nine PNGs visually inspected: labels, missing markers, units, target names,
  small bins and revision IDs are readable.
* Offline browser: all nine images loaded at natural width 1920 pixels; zoom
  displayed all nine at 1920 pixels. No web server or network data required.
* Six Python files passed Pylance syntax checks.
* Nine unit tests passed, including hand-calculated totals, metric-specific resets,
  missing-window recovery, weighted pooling, independent resource limits,
  extraction gates and the full reading-error envelope.
* Four acceptance variants passed: oracle, approximate estimates, reordered
  readings and one isolated reading error inside the published allowance.
* Sixteen faulty variants and the empty baseline were rejected.
* Final source-tree native Harbor oracle passed all seven reward fields at 1.0,
  no exception, approximately 9 seconds total.

The initial source oracle, before expanding valid counterfactuals from 16 to 20,
also passed. The authoritative final source job is
`chart-capacity-v2-oracle-final`; copied outputs are under
[evidence/oracle-final](evidence/oracle-final).

Author validation ran in a network-disabled Python 3.12.12 container:
[summary](evidence/author/summary.json) and
[unit test output](evidence/author/unit-tests.log).

## Independent numerical witnesses

These are author-only answers, not candidate instructions.

| Witness | Result |
|---|---|
| AS usable errors after its two-metric reset | 10,000 |
| BI usable errors after its errors-only reset | 16,000 |
| BI requests (must not reset with errors) | 960,000 |
| DS usable windows despite missing B2 | W1, W3, W4 |
| DS usable errors | 11,000 |
| DI errors, excluding maintenance | 5,500 |
| CS pooled slow fraction | 310 / 13,000, not the unweighted window mean |
| CI | Latency-eligible but frozen; retained in residual risk |
| Nominal rollout | BS tier 1, BI tier 2, all other tiers zero |
| Nominal credits / power | 14 / 8 |
| Weighted reduction / residual risk | 26,320 / 90,530 |
| Budget 14 | Same plan |
| Budget 18 | Add DS tier 1; reduction 31,820 |
| Exact winner-versus-rival margin | 1,220 |
| Oracle reading-interval margin | 1,165.6 |
| Envelope covering every admissible reading interval | Margin 1,002.4, all classifications stable |

The reference uses Decimal arithmetic and recursively pruned enumeration. The
oracle uses a separate implementation with Fraction-valued optimizer
coefficients and a flat tier product. Hand witnesses complement the two
implementations, rather than relying only on their agreement.

## Fairness iteration before any model trial

The original author draft gave normal AI/DI windows 1,000 latency samples.
Although their exact slow fraction was 2%, the largest legal visual-error
envelope could cross the 5% trigger. That would have contradicted the advertised
decision stability.

Their normal populations were increased to 2,000 samples while preserving the
2% slow fraction. Tolerances were not tightened. The full envelope now has upper
slow fraction 4% for these targets. The correction preceded all v2 model trials
and was followed by rendering, oracle and verifier validation.

Another validation improvement added explicit scenarios in which power,
active-region count and per-region block caps bind independently. Omitting
these constraints can produce the right original plan by coincidence. Such
programs now fail fresh execution, not an irrelevant source-code check.

Finally, a positive control with one isolated transcription error verified the
98% extraction allowance end-to-end. The verifier process now exits successfully
when mandatory gates pass with a fractional reward; it does not confuse a
legitimate 0.999123 with an evaluation error.

## Acceptance and rejection controls

| Control | Outcome |
|---|---|
| Oracle, shifted admissible estimates, reversed row ordering | Each overall 1.0 |
| One isolated reading error | Overall 0.999123; extraction 227/228 |
| Five isolated reading errors | Overall 0; extraction 223/228 below 98% |
| Use obsolete counter revision | Rejected: authority/reconstruction/planning |
| Clamp a counter reset instead of reconstructing it | Rejected: reconstruction/calculation |
| Reset both metrics when only errors reset | Rejected despite matching nominal plan |
| Drop a reset-recovered window with missing old start | Rejected: reconstruction/scenarios |
| Multiply cumulative deltas by duration | Rejected: calculations |
| Include excluded traffic's latency samples | Rejected: joined populations |
| Average window slow fractions | Rejected: pooled summaries |
| Ignore a regional freeze | Rejected: eligibility/planning |
| Omit region activation charges | Rejected: planning |
| Ignore power, active-region limit, or regional block caps | Each rejected by counterfactuals |
| Force `robust=true` | Rejected on a threshold-straddling counterfactual |
| Claim supported causality from a deployment marker | Rejected: claim audit |
| Static output program | Rejected: reusable execution and invalid inputs |
| Empty baseline | All components zero |

These are intentionally faulty controls, not model trials. The mutation runner
compiles each changed program and records initial execution exits, rewards and
per-probe diagnostics. Faults are not counted as successful model evidence.

## Reproducibility and evidence handling

The ZIP must contain exactly one task root and exclude bytecode caches.
[evidence/source-manifest.json](evidence/source-manifest.json) hashes non-evidence
task files. Protected candidate-visible source hashes are separately checked by
the verifier.

Run the oracle from a fresh extraction as well as the source checkout. Preserve
its result, original reward and detailed checks. Record packaging verification
next to the release archive; avoid modifying an already validated archive to
insert logs produced after its creation.

Before the eventual target-model trial, freeze task/grader hashes and the
archive. Use an image-capable native harness and high reasoning. Retain actual
model identity, effort settings, commands, timing, rewards, trajectory and image
access evidence. Investigate any failure against the published contract;
exclude environment/image-access problems and do not retune the grader during
the trial. If the model passes, report a pass.
