# Cold-chain dispatch recovery

An original depot-release task combining source-of-record reconciliation,
inventory allocation, production scheduling and vehicle routing. The deliverable
is a runnable plan generator plus a complete operational dispatch plan.

## Why this task

Real dispatch failures cross organizational boundaries: customer-service exports,
warehouse stock, quality release, packing staff, carriers and customer windows.
Each local plan can look sensible while the combined plan cannot be executed.
The economic outcome here is delivering all 18 orders with released, unexpired
stock while respecting labor and equipment limits under a $790 authorization.

The evidence set contains versioned orders, an at-least-once stock movement feed,
quality decisions, directed travel times, product thermal limits, three packing
benches, a single dock and five available vehicles. An acceptable plan must
reconcile the state, jointly schedule production and dispatch, and leave a
durable reproducible handover.

## Fairness and verification

The top-level prompt identifies the deliverables and points to public operating
documents; it does not name specific defects to fix. Every grading rule is
stated in those documents. IDs, reference tables, timestamps and units are
explicit. The installed OR-Tools package is available to candidates. No
unpublished data, guessed industry policy or network resource is needed.

The budget is a feasibility cap, not an optimum-equality test: a passing oracle
has cost 67,280 cents, leaving 11,720 cents of headroom. Different allocations,
bench assignments, routing, waiting and schedules are valid.

The independent checker uses SQLite window queries for source reconstruction
and direct interval/ledger simulation for the plan. The oracle uses Python
record selection and CP-SAT route/packing decisions. It does not import the
verifier. Checks cover roster, stock, packing, fleet/dock, thermal/expiry,
spend, protected inputs and regeneration in a different directory. Output is
`/logs/verifier/reward.json`, with all criteria required for overall 1.0.

The rerun uses unchanged input contents and a stated 180-second allowance.
The solver has no machine-specific state. A full oracle trial, including
building the image and regeneration, passed in 46 seconds.

`author/validate_controls.py` tests valid alternative plans and intentionally
invalid plans. It is an author tool, not copied into the agent environment.

## Provenance and limitations

All scenario files, formulas, synthetic records, solver code and checks were
created from scratch for this exercise. No public benchmark instance or real
customer information was used. Python, OR-Tools and their dependencies are
external libraries installed at pinned versions. The base image is digest
pinned. This is a stylized fixed-day planning problem, not a stochastic fleet
simulator; road times are given and no live traffic is required.

The task allows two hours of agent time. A failure caused only by agent or
infrastructure timeout will not be claimed as a reasoning failure.
Model evidence is recorded separately after freezing the task.

## Completed target-model trial

`dispatch-opus-01/cold-chain-dispatch-recovery__4EnEFum`: Opus 5.5 high,
Copilot CLI 1.0.102, all nine criteria passed, overall 1.0, about 5m30s including
setup and verification. The model delivered six trips costing 66,510 cents,
below both the cap and the oracle witness above. Frozen files were verified
unchanged after the trial. There is no failure evidence from this task.

## Reproduction

From the parent directory:

```sh
harbor run -p ./cold-chain-dispatch-recovery -a oracle
harbor run -p ./cold-chain-dispatch-recovery -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the requested assignment recipe, not a claim that
it was used. The authorized experiment uses Opus 5.5 high with Copilot CLI
1.0.102 and Harbor 0.24.0:

```sh
export PYTHONPATH="$PWD/cold-chain-dispatch-recovery/author"
# Supply valid Copilot authentication using your local environment.
uvx --from harbor==0.24.0 harbor run -p ./cold-chain-dispatch-recovery \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter only installs official Node 22.14.0 with checksum verification
when needed, then the official pinned Copilot CLI npm package. Model execution
and trajectory capture remain Harbor's native inherited implementation.
