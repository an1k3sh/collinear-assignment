# Chart capacity audit v6: visual evidence and staged-information policies

**Current result: Opus 5.5 high passed 3/3 v6 trials. No substantive failure has
been demonstrated.** See [RUN_REPORT.md](RUN_REPORT.md) for all iterations,
the rejected v3 false positive, timing caveats and preserved trajectories.

One self-contained Harbor task, created for this exercise. V6 combines normalized
stacked latency charts to the contingent
change-window decision to the chart reconciliation and capacity-sizing audit.
The candidate must not assume a good static allocation is the best executable
schedule. The task includes nine original PNGs, eight service/region targets,
228 reading checks and 32 historical interval decisions.

Read [instruction.md](instruction.md), the [viewer](environment/app/report/index.html),
and the public [execution policy](environment/app/execution-policy.md).

## What changed after v2 passed

V2 passed Opus 5.5 high through Copilot CLI 1.0.102 in 9m39s with every reward
component at 1.0. Nine native image payloads were confirmed; all frozen task
hashes matched after the run. This was a genuine pass, not a failure.

V6 retains readable chart evidence and explicit telemetry rules. It includes:

* tier-by-tier jobs, durations and warmup/readiness transitions;
* per-slot crews, blackouts, regional idle gaps and prerequisite migrations;
* total-resource accounting across incremental upgrades;
* three alternative forecast cases and one precommitted max-min schedule;
* disruption costs and end-to-end links whose value is limited by the weaker
  effective endpoint;
* interval bounds with shared-observation coefficient cancellation.
* a shared irreversible early prefix and case-dependent continuations after
  a forecast signal, optimized jointly rather than by hindsight.

V3 returned raw overall zero in 12m32s, but diagnosis rejected it as a substantive
failure: only a serving-tier versus installed-tier reporting ambiguity differed.
Its actual plans and risk arithmetic were correct. That raw score is preserved,
not promoted as evidence of a capability failure. V4 explicitly defines the state
field and adds a genuinely new contingent decision.

V4 then genuinely passed in 19m23s, including all 41 valid counterfactuals and
21 malformed inputs. V5 changes the latency evidence from individually labelled
bin counts to normalized stacked segments with printed sample totals. The agent
must recover counts from relative widths and population sizes. Public interval
width is max(20,0.005*N), with unresolved tiny segments permitted to include zero.
Pillow is preinstalled for crop/pixel tools; no OCR implementation is required.
All four changed charts were visually inspected. An independent pixel-reading
control checks that the raster geometry supports the permitted precision.

V5 passed all components as well, in 30m36s total. Its agent used actual image
payloads and pixel-based extraction. V6 adds partial information before exact
information, with irreversible shared commitments at both boundaries and a
global risk-adjusted policy valuation. It is not sufficient to optimize each
conditional signal group independently.

A pre-trial control demonstrates the distinction on a valid changed forecast:
global policy value 95,112.9 versus conditional-greedy 88,732.9. Both preserve
the same guaranteed 22,799; the correct global policy gains 63,800 more in the
case-net sum. This is a control witness, not an observed model failure.

Candidates deliver reusable standard-library Python, intermediate state, claim
audit and memo. The six-slot/four-candidate/four-job scope is deliberately bounded.
Exhaustive search with pruning is sufficient; no commercial solver or network is
needed. Per-execution allowance is 90 seconds; the agent has three hours.

## Fairness and verification

All reset timing, missingness, source authority, uncertainty widths, ordering and
tie-breaks are public. Exact readings and manual transcription of chart labels
are allowed. The old static plan remains stable across the complete admissible
reading envelope; the timed schedule is graded against the candidate's own
admissible readings, not a hidden fixed schedule.

The independent static reference uses Decimal plus recursively pruned tier
enumeration. The execution reference enumerates per-target schedules as a product
and evaluates Decimal-valued risk. The oracle independently searches forward by
slot with Fraction-valued objective comparisons. Hand calculations supplement
agreement between implementations.

The six original reward components and mandatory gates remain; planning now
also checks the entire executable schedule and per-case accounting. The verifier
runs a fresh original, 51 valid changed inputs, and 25 malformed inputs.
It evaluates actual structured outputs, not implementation strategy or exact
prose. There is no LLM judge or pixel comparison.

Twenty author unit tests cover both implementations, original hand witnesses,
all changed inputs, empty plans, upgrade readiness, malformed schedules and
eleven executable scheduling faults, five contingent-policy faults, and a
conditional-greedy staged-policy fault. These
include hindsight leakage, forgetting running commitments, choosing the wrong
information boundary and reusing the best fixed prefix. Inherited controls cover
approximate readings, row reordering, the 98% extraction allowance, and mistakes
in reset/source/planning logic.

## Reproduce

Requires Docker and Harbor. Tested tooling is Harbor 0.24.0 and the Python 3.12.12
image pinned by digest in [Dockerfile](environment/Dockerfile). The submitted
pipeline uses only the standard library; Pillow 12.0.0 is installed for image
inspection, and PNGs are checked in. Only author rendering uses the pinned
packages in [author/requirements.txt](author/requirements.txt).

From the directory containing the task:

```sh
harbor run -p ./chart-capacity-audit-v6 -a oracle
harbor run -p ./chart-capacity-audit-v6 -a claude -m opus-5-5
harbor view ./jobs
```

The Claude command is the assignment's provider-dependent alias. Configure
credentials, image access and high reasoning, and record the actual resolved
model/effort. It is not a claim that Claude Code was tested.
For the same comparison harness as previous runs:

```sh
uvx --from harbor==0.24.0 harbor run -p ./chart-capacity-audit-v6 \
  -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102
```

Harness installation and inference require network/credentials. The task itself
is offline. No credentials are included. Verify actual image payloads before
interpreting failures; a text-only harness is not a fair visual trial.

From the task root, author validation:

```sh
python3.12 -m unittest discover -s tests -p 'test_*.py' -v
python3.12 tests/author_check.py /tmp/chart-v6-controls
python3.12 author/check_raster.py /tmp/chart-v6-raster
```

The candidate sees only environment/app. Do not expose solution, tests, author
source or evidence before or during the trial. Additional helper modules under
submission are allowed. Original chart source lives in author/render.py; rerender
with its pinned requirements only before freezing and rerun validation afterward.

## Provenance and limitations

All scenario data, charts, code, policies, fixtures and verification logic were
created for this exercise. This extends
earlier v1/v2 tasks from this exercise, not a public benchmark or issue. No external dataset is
used. Matplotlib/NumPy/Pillow are ordinary author-time dependencies.

The scenario represents an SRE/finance review of exported dashboards and a
resource-limited change window. Bad decisions can misallocate capacity, ignore
change freezes or start dependent work too soon. It is still a synthetic bounded
simulation; forecast valuations are supplied assumptions, not measured causal
effects. Prose is human-reviewable but only presence/evidence tokens are checked
automatically. Preserve every pass as well as every failure.
