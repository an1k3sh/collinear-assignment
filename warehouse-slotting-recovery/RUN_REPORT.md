# warehouse-slotting-recovery: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `slotting-opus-01` | `prototype_harness:PrototypeCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./warehouse-slotting-recovery -a oracle
harbor run -p ./warehouse-slotting-recovery -a claude -m opus-5-5
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

# Warehouse slotting recovery

An original constrained layout optimization task using historical picker
transitions. It differs from the earlier constraint-implementation prototypes:
a correct objective calculation and feasible baseline are not sufficient.
The agent must search for a materially better saved layout.

## Task and economic connection

Eighty SKUs occupy eighty slots across temperature zones and walking aisles.
Eight fixed SKUs cannot move. The weekend authorization permits 200 relocation
minutes. Historical transition counts and the complete aisle-distance matrix
define the walking metric exactly.

The baseline was improved by 77 steepest-descent pair swaps until no eligible
pair swap improved it. Its cost is 2,430,286 walking ticks. The release target
is at most 2,381,680 ticks, a 2% reduction. Meeting it requires escaping the
baseline local minimum while preserving compatibility, fixed stock and labor.

Subgoals include inspecting and joining the operating records, constructing
the correct directed-transition objective, planning an improved assignment
under relocation constraints, verifying the saved result and leaving
reproducible search code and a handover.

## Fairness and author calibration

The exact public scorer is available to the agent. There is no hidden metric,
undocumented placement rule, format trick or demand for a unique/global optimum.
Python, NumPy and a C++ compiler are installed. The agent has two hours.
The included generic simulated-annealing oracle compiles its search code,
reads the same public data, searches from the same baseline and passes.
It does not load a hidden answer or a planted solution.

An initial 3% target was NOT released to the model. Three author-side searches
failed to certify it (best observed 2,369,356 ticks, 196 minutes), so the target
was changed to 2% before any model trial. The calibrated native oracle then
passed all six criteria. Those initial author-search failures are not target
model evidence. See `evidence/pretrial-calibration.json`.

The task's arithmetic objective and assignment constraints are recomputed from
the saved artifact. A separate checker implementation validates complete
assignment, placement, relocation budget, travel target and reported metrics.
Positive controls include a different passing layout. Negative controls cover
the unmodified baseline, duplicate slots, wrong zones, moved fixed stock,
excess labor and an inaccurate reported score.

## Provenance and limitations

This 80-SKU instance, identifiers, transition history, distance matrix,
baseline and task code were generated from scratch for this exercise.
No public quadratic-assignment instance or benchmark was copied.
The demand includes co-picking affinities and smaller cross-group transitions.
Distances model cross-aisle access; the scenario is synthetic rather than
customer data.

The metric is the stated historical transition surrogate, not a claim to
optimize complete future picking tours. Relocation minutes authorize final
assignment changes; planning the physical temporary-space swap sequence is
explicitly outside scope. The source-code/report criterion checks presence;
the saved operational layout and exact measured criteria determine feasibility.

## Reproduction

From the parent directory:

```sh
harbor run -p ./warehouse-slotting-recovery -a oracle
harbor run -p ./warehouse-slotting-recovery -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the assignment recipe. The authorized experimental
run is Opus 5.5 high with Copilot CLI 1.0.102:

```sh
export PYTHONPATH="$PWD/warehouse-slotting-recovery/author"
# Supply valid Copilot authentication in the local environment.
uvx --from harbor==0.24.0 harbor run -p ./warehouse-slotting-recovery \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter changes installation only, using official checksum-verified Node
22.14.0 and the pinned official CLI npm package. Harbor's Copilot invocation
and trajectory processing remain unchanged.
