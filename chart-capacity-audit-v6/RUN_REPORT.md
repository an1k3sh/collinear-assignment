# chart-capacity-audit-v6: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `chart-capacity-v6-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `chart-capacity-v6-copilot-opus-03` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `chart-capacity-v6-copilot-opus-02` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./chart-capacity-audit-v6 -a oracle
harbor run -p ./chart-capacity-audit-v6 -a claude -m opus-5-5
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

# Iteration report: no substantive model failure

**The failure objective has not been achieved.** V6 passed three fresh Opus 5.5
high trials. Do not submit this as evidence that the model fails the task.
The task, passing oracle, verifier controls and trajectories are retained for
further research rather than relabelled as a successful failure benchmark.

## All trials in this iteration session

| Revision / trial | Result | Interpretation |
|---|---|---|
| V2 / 01 | All components 1.0 | Genuine pass; ~9m39s |
| V3 / 01 | Raw overall 0, reproducibility .75 | Rejected as substantive failure; reporting ambiguity only |
| V4 / 01 | All components 1.0 | Genuine pass; ~19m23s |
| V5 / 01 | All components 1.0 | Genuine pass; ~30m36s total reported |
| V6 / 01 | All components 1.0 | Genuine pass; 17m57s wall time |
| V6 / 02 | All components 1.0 | Genuine pass; timing discrepancy noted below |
| V6 / 03 | All components 1.0 | Genuine pass; timing discrepancy noted below |

V1 also passed in an earlier session. Earlier Python/C++ SQL experiments likewise
did not supply failure evidence. They are separate task families and are not
included as additional task directories in this release.

All trials used Harbor 0.24.0, Copilot CLI 1.0.102, model `claude-opus-5.5`,
and requested `reasoning_effort=high`. These are NOT native Claude Code runs.
The assignment's requested Claude Code command is documented as a reproduction
recipe, not as an experiment that was performed.

## V6 evidence

[model-runs.json](evidence/model-runs.json) indexes all three trials.
Each trial folder contains original rewards, detailed verifier checks, graded
submission files, native JSONL trajectory and Harbor trial result:

* [Trial 01](evidence/opus-01): `chart-capacity-audit-v6__gPFds3q`
* [Trial 02](evidence/opus-02): `chart-capacity-audit-v6__8USTfVt`
* [Trial 03](evidence/opus-03): `chart-capacity-audit-v6__8rffxD4`

Each had nine native image-payload events, all 228 extraction observations
accepted, all 51 valid counterfactuals correct, and all 25 malformed inputs
rejected. Original static, fixed, full-reveal and staged policy outputs passed.
There were no reported trial exceptions. The repeats used fresh environments;
the task was not altered between trials. All frozen hashes were checked after
completion. [trial-freeze.json](evidence/trial-freeze.json) records the evaluated
files; subsequently added evidence and this report were not candidate inputs.

**Timing caveat:** repeats 02/03 have wall-clock trial durations of about 3h17m24s
and 3h16m05s in their result timestamps. Harbor's progress display instead showed
30m40s and 29m22s. These clocks disagree; the cause was not investigated.
Do not use the progress durations as precise end-to-end measurements or infer
a timeout failure. Both runs finished with all rewards 1.0 and no exception.

## Why the v3 raw zero was rejected

V3's three failed valid probes differed only at one
`execution.slots[].effective_tiers` value during a tier-2 upgrade outage.
The model returned the previously ready tier (1) and separately returned zero
effective reduction; the reference returned tier 0. Schedules, benefits, bounds,
resources and all other fields agreed.

The policy specified zero reduction while occupied but did not explicitly say
whether the tier field described installed or serving state. Two reference
implementations agreeing with each other did not resolve that public ambiguity.
It was therefore not accepted as a substantive failure.
V4 clarified the field explicitly before its trial. Original v3 rewards were
preserved, not overwritten. Subsequent trials passed the clarified requirement.

## How the task evolved

* V2: corrected exports, per-metric resets, missing/maintenance joins, pooled
  latency, multi-resource sizing and interval certificates.
* V3: timed incremental upgrades, crews, readiness, blackouts, prerequisites,
  regional gaps, disruption, path bottlenecks and max-min forecasts.
* V4: common irreversible prefixes and case-dependent continuations.
* V5: normalized stacked chart segments instead of labelled per-bin counts;
  sample totals still printed, with explicit uncertainty and Pillow available.
* V6: partial then exact signals and a global risk-adjusted policy objective.

The v6 pre-trial negative control is meaningful: conditional-greedy optimization
gets value 88,732.9 where joint optimization gets 95,112.9, with 63,800 more
total case benefit for the latter. Nevertheless, the actual model solved this
counterexample in all three v6 trials. Do not confuse a rejected mutant with an
observed model failure.

## Solvability and fairness checks

* Native source-tree Harbor oracle: all seven reward fields 1.0.
* Twenty unit tests: independent forward-time/Fraction and per-target/Decimal
  solvers agree on all valid probes; hand witnesses and malformed cases pass.
* Six full-grader acceptance/boundary controls were run for v6: oracle,
  approximate readings, reordered readings, one tolerated reading mistake,
  five over-threshold reading mistakes and the empty baseline.
* Unit controls reject 11 scheduling faults, five full-reveal policy faults and
  the conditional-greedy staged-policy fault.
* V5's pixel-only bin reconstruction (same PNGs used by v6) recovered all 128 bins
  inside half their permitted interval width; largest count error was about 5.88.
  That extraction also passed the complete v5 pipeline. Charts were visually
  inspected; tiny segments need only be bounded within the published allowance.
* The complete original reading envelope preserves static eligibility and plan,
  with winner margin 1,002.4. The schedule/policies are recomputed from each
  candidate's admissible readings, not matched against one hidden schedule.

Proof is functional, not based on prose or source-code similarity. Additional
descriptive output fields are accepted. All dependencies, image access and
supported changes are public. There is no speed bonus or LLM judge.

## Interpretation and next decision

This family has become a substantial, realistic multi-step task, but repeated
full passes make it poor evidence for the requested capability failure.
More complexity or more samples might eventually expose a mistake; neither is
a guarantee, and repeated sampling introduces selection bias. Every pass must
remain disclosed if a later failure is found.

The current recommendation is to decide explicitly between a domain pivot,
a materially different repository-repair setting, or a bounded additional
experiment budget, rather than tightening tolerances or treating an ambiguous
field as success.
