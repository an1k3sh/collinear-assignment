# Chart capacity audit v3: from evidence to an executable rollout

One self-contained Harbor task, created for this exercise. V3 adds a timed
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

V3 retains the readable chart evidence and explicit telemetry rules. It adds:

* tier-by-tier jobs, durations and warmup/readiness transitions;
* per-slot crews, blackouts, regional idle gaps and prerequisite migrations;
* total-resource accounting across incremental upgrades;
* three alternative forecast cases and one precommitted max-min schedule;
* disruption costs and end-to-end links whose value is limited by the weaker
  effective endpoint;
* interval bounds with shared-observation coefficient cancellation.

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
runs a fresh original, 34 valid changed inputs, and 18 malformed inputs.
It evaluates actual structured outputs, not implementation strategy or exact
prose. There is no LLM judge or pixel comparison.

Fifteen author unit tests cover both implementations, original hand witnesses,
all changed inputs, empty plans, upgrade readiness, malformed schedules and
eleven executable scheduling faults. Inherited full-grader controls cover
approximate readings, row reordering, the 98% extraction allowance, and mistakes
in reset/source/planning logic.

## Reproduce

Requires Docker and Harbor. Tested tooling is Harbor 0.24.0 and the Python 3.12.12
image pinned by digest in [Dockerfile](environment/Dockerfile). Runtime uses only
the standard library; PNGs are checked in. Only author rendering uses the pinned
packages in [author/requirements.txt](author/requirements.txt).

From the directory containing the task:

```sh
harbor run -p ./chart-capacity-audit-v3 -a oracle
harbor run -p ./chart-capacity-audit-v3 -a claude -m opus-5-5
harbor view ./jobs
```

The Claude command is the assignment's provider-dependent alias. Configure
credentials, image access and high reasoning, and record the actual resolved
model/effort. It is not a claim that Claude Code was tested.
For the same comparison harness as previous runs:

```sh
uvx --from harbor==0.24.0 harbor run -p ./chart-capacity-audit-v3 \
  -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102
```

Harness installation and inference require network/credentials. The task itself
is offline. No credentials are included. Verify actual image payloads before
interpreting failures; a text-only harness is not a fair visual trial.

From the task root, author validation:

```sh
python3.12 -m unittest discover -s tests -p 'test_*.py' -v
python3.12 tests/author_check.py /tmp/chart-v3-controls
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
