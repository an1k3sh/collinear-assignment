# chart-capacity-audit-v3: run report

## Validation notes

Clarified the public effective_tiers field as serving capacity (zero during an occupied upgrade), resolving the historical installed-versus-serving ambiguity. The original zero is not failure evidence.

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `chart-capacity-v3-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 0.0 | Historical raw result; consult detailed fairness analysis, not automatically a model failure |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./chart-capacity-audit-v3 -a oracle
harbor run -p ./chart-capacity-audit-v3 -a claude -m opus-5-5
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

# V3: raw rejection, not accepted failure evidence

The Opus 5.5 high trial through Copilot CLI 1.0.102 finished in 12m32s.
Native Harbor reported overall 0, reproducibility 0.75, all other components 1.
The original answers passed, all 18 malformed inputs were rejected, and 31/34
valid counterfactuals passed.

Exact replay isolated one field in each failed case:

| Probe | Field | Actual | Reference |
|---|---|---:|---:|
| 13 | execution.slots[2].effective_tiers.DS | 1 | 0 |
| 27 | execution.slots[1].effective_tiers.AS | 1 | 0 |
| 33 | execution.slots[2].effective_tiers.DS | 1 | 0 |

During a tier-2 upgrade outage the model reported the previously ready tier in
this field, and separately correctly reported zero effective reduction.
All actions, chosen schedules, risk values, bounds and resource accounting
matched. The public rule said reduction is zero during occupation but did not
explicitly define this tier field's encoding for an installed-but-unavailable
tier. The author therefore rejects this result as a substantive failure.

Raw trial outputs remain unchanged under the workspace job
`chart-capacity-v3-copilot-opus-01/chart-capacity-audit-v3__hog9aXN`.
Both independent reference solvers agreed during replay, but their agreement
does not remove the public-contract ambiguity. Do not use this result as evidence
of chart reasoning or scheduling failure.

V4 clarifies the field and introduces an independently validated two-stage
contingent policy. No changes were made to the v3 verifier or original reward.
