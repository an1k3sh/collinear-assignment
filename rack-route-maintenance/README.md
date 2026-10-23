# Rack-route maintenance recovery

This original task variant asks an agent to consolidate nine routed as-built drawings into
one 48-node, 87-cable topology, reconcile cable inventory, and generate protected
service routes for three successive maintenance phases.

## Real-world connection and long-horizon work

Network operations teams maintain diagrams and asset histories separately.
Planning maintenance against an incorrectly reconstructed graph can produce
routes that look valid to a solver but do not physically connect. Likewise,
two different cables can share a duct failure domain, and duplicate active
service copies consume capacity even if one is called "secondary".

The linked subgoals are:

1. Inspect six room schematics and three spine sheets, transcribing all cable
   endpoints into a durable consolidated as-built record.
2. Reconcile the cutoff-known inventory, maintenance outages and dark-fiber
   activation choices.
3. Jointly route five services through each phase, including three protected
   1+1 services, within capacity and the activation budget.
4. Produce a reproducible planner and operational handover.

## Fairness

All drawn labels are high contrast, on original 3200x2600 PNGs. The drawings
can be viewed at full size or cropped without lossy encoding. Crossing semantics
are explicit in the brief and on every drawing. Endpoint orientation is
irrelevant; no unique route, exact optimum, formatting style or textual
explanation wording is prescribed.

The inventory and protection rules are public. There is no hidden endpoint
file in the candidate environment. Machine-readable reference topology,
generator source, solutions and verifier are excluded from the Docker image.
Source PNGs contain no embedded topology metadata. OR-Tools and Pillow are
installed at pinned versions, and solving requires no outside data.

The activation limit is a feasibility cap, not a demand to match the oracle's
cost. Agent time is two hours; a final rerun has the stated 180-second limit.
Only identical inputs are used for regeneration. Infrastructure interruptions
or timeout-only outcomes will not count as substantive model failures.

## Verifier and oracle

The verifier compares undirected endpoint sets, walks every cable path against
the original as-built graph, and separately checks coverage, availability,
failure-domain separation, aggregate undirected capacity and activation cost.
Using the candidate's invented graph to validate its own routes would hide
visual transcription errors, so operational checks use the independent original
reference, not submitted connectivity.

The oracle uses CP-SAT directed arc decisions with cycle-eliminating ranks,
shared undirected capacity, and shared-risk exclusions. The verifier uses
direct graph walks and counters, and reconstructs inventory with SQLite
window queries rather than the oracle's Python version selector.

The underlying straight-line variant's clean-container oracle passed all ten
criteria, including regeneration. This routed version is validated separately
before its model trial. Valid endpoint reversal/list reorder and protected-route role
swaps must pass. Controls reject incorrect topology, incomplete phases,
disconnected routes, inventory/outage mistakes, missing activation, shared
risk groups even on edge-disjoint routes, excess capacity and wrong spend.
Results are preserved under `evidence/`.

## Provenance and limitations

All images, records, scenario, code and grading logic were newly authored for
this exercise. No public benchmark instance, proprietary asset or customer
data is used. Standard external libraries are declared in the pinned
requirements. The scenario is fictional and simplified: no latency, port
assignment, node failure or live traffic uncertainty is implied.

The drawings are synthesized, not scans of an actual operator's records.
Full topology accuracy is an explicit deliverable, including unused cables.
Do not generalize a single model trial to an estimated failure rate.

## Completed target-model trial

`rack-opus-01/rack-route-maintenance__nRoqP6j`: Opus 5.5 high, Copilot CLI
1.0.102, all ten criteria passed, overall 1.0, about 5m41s including setup and
verification. The model wrote a pixel-tracing extractor and recovered all 87
multi-bend wires correctly. It also produced a valid maintenance plan.
Frozen input and verifier hashes were unchanged. No failure was observed.

This variant preserves the preceding straight-line task's entire operational
problem and changes only its diagram presentation to routed rack wiring.
The variant's own clean-container oracle also passed all ten criteria.

## Reproduction

From the parent directory:

```sh
harbor run -p ./rack-route-maintenance -a oracle
harbor run -p ./rack-route-maintenance -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the assignment recipe, not evidence of execution.
The authorized target experiment uses Harbor 0.24.0 and Copilot CLI 1.0.102:

```sh
export PYTHONPATH="$PWD/rack-route-maintenance/author"
# Supply valid Copilot authentication in the local environment.
uvx --from harbor==0.24.0 harbor run -p ./rack-route-maintenance \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter changes installation only: official Node 22.14.0 with checksum
verification if needed, followed by the official pinned CLI npm package.
Copilot execution and trajectory handling remain inherited from Harbor.
