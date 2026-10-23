# From allocation approval to an executable change window

The static allocation remains a required sizing comparison, NOT a prescribed
set of changes. Separately optimize the six-slot execution window from tier zero.
You may choose different final tiers. All execution inputs are under `execution`
in planning.json. Historical operations windows and future execution slots are
different coordinate systems; never treat a past maintenance record as a future
blackout. Future blackouts are explicitly listed in `execution`.

## Jobs, resources and dependencies

Only `execution.candidates` may receive jobs; all other targets remain tier zero.
Candidates still must satisfy the reconstructed `rollout_eligible` flag. All
eight targets continue to contribute to forecast residual risk.

A job installs exactly the NEXT tier (0->1 or 1->2). Durations and warmups are
indexed by destination tier minus one. Start slots are integers >=0.
`finish=start+duration`; occupied slots are start <= s < finish.
`ready=finish+warmup`. Ready must be <= horizon. At the START of slot `ready`,
the installed tier becomes effective. While occupied, effective reduction is
zero, including when upgrading an existing tier. During warmup, the prior tier
continues to provide its reduction; warmup uses neither crew nor outage capacity.
A target's next job may start at ready, but never before it.

For avoidance of doubt, `slots[].effective_tiers[target]` MUST be zero while
that target is occupied. This field describes serving capacity, not installed
or migration-ready state. A separate optional installed/ready-tier field may
retain the prior tier. During warmup after an upgrade, effective_tiers returns
to the previous ready tier until the new one is ready.

Each occupied job uses one crew. Per-slot crew counts must not exceed the
listed `crews` vector. No job may occupy any slot in its target's `blackouts`.
Same-region jobs (including different targets) cannot overlap and must have
at least `region_gap` completely idle slots between finish and the next start.
This gap is about occupied jobs, not warmup. Different regions may overlap.
Total job count is at most `max_jobs`.

Each dependency states that a particular target/destination tier job may start
only once the prerequisite target has reached the specified tier's READY time.
Readiness at the same start boundary is sufficient. A prerequisite may be
installed in this schedule; it does not start preinstalled. Dependencies can
point in either direction in target_order but supplied inputs have no cycles.
Readiness is not negated by a later upgrade outage: this is a completed
compatibility migration, not a live availability dependency.

The final-tier vector must satisfy ALL static credit, power, active-region and
regional block caps, as well as freezes and latency eligibility. Tier costs and
power are TOTALS: do not charge a tier-2 target its tier-1 cost a second time.
Region activation is charged once. Monotone total resources mean checking final
resources is sufficient. Crews, blackouts and region_gap are additional constraints.

## Risk over the window

For each named case and slot, `exposure[target][slot]` scales that target's usable
historical error total (not error rate). Define R_t = errors_t * risk_weight_t.
These are supplied forecast scenarios, not fitted statistical estimates.

At each slot:

* Baseline risk = sum R_t * exposure_t over ALL eight targets.
* Gross mitigation = sum R_t * exposure_t * effective_reduction_t.
* Each occupied job ALSO incurs a disruption debit
  R_t * exposure_t * disruption. It has zero gross mitigation in that slot.
* Each link earns extra mitigation
  R_owner * exposure_owner * factor *
  min(effective_reduction_left, effective_reduction_right).
  Multiple links add. This is a supplied valuation of an end-to-end path, not
  permission to add raw endpoint percentile values.

Case net benefit = sum gross mitigation + link mitigation - disruption debits
over all slots. Case residual = case baseline - case net benefit.
Empty schedules are feasible and have net zero. Negative case net is permitted.

Select ONE schedule BEFORE knowing the case. Maximize the MINIMUM whole-window
case net benefit. Do NOT take the minimum per slot or choose different schedules
per case. Tie-break by higher SUM of case net benefits, then lower final credits,
then lower final power, then lexicographically smaller start vector.

Start vector has two entries per target in planning.target_order, tier-1 start
then tier-2 start; absent jobs use horizon+1. This uniquely identifies a schedule.
Use arithmetic tolerance only for checking, not to change the stated objective.

For each winning case, aggregate the complete net-benefit coefficient of each
target's historical error total across all slots and links. The same observation
is shared by the debit and mitigation terms. Calculate `net_bounds` by multiplying
each aggregate positive coefficient by low/high error totals and each negative
coefficient by high/low totals. Do not independently bound slots before cancellation.
These are bounds on the CHOSEN schedule, not a proof of robust optimality. Do not
apply the static-plan winner-versus-rival certificate to this nonlinear max-min
problem. The schedule is chosen using estimates.

## Output under analysis.json's `execution` key

```
{
 "actions":[{"target":"AS","tier":1,"start":0,"finish":1,"ready":2}],
 "slots":[{"slot":0,"occupied":["AS"],"effective_tiers":{"AS":0}}],
 "final_tiers":{"AS":1},
 "credits":0,"power":0,"active_regions":["Alder"],"peak_crews":1,
 "cases":[{"id":"weekday","baseline":0,"net":0,"net_bounds":[0,0],"residual":0}],
 "worst_case_net":0,"total_case_net":0,
 "start_vector":[0,7]
}
```

Illustration only, not a complete answer. Include ALL eight targets in
effective_tiers and final_tiers; two start-vector entries for ALL eight.
Actions sort by start, then index in target_order, then tier. Occupied target
lists sort by target_order. Slots are 0..horizon-1; cases retain config order;
active_regions sort lexically. Include no jobs for absent tiers.
State the schedule and its risk tradeoff in decision.md. The static eight-claim
audit still refers to the original sizing comparison, not this execution problem.

## Reusable execution scope

Valid probes may change any execution numbers, case IDs/order, candidate order,
blackouts, links and dependencies. Up to four distinct candidates, horizon 3..6,
max_jobs 0..4, 1..3 cases, crews 0..2, duration 1..2, warmup 0..1, gap 0..1.
All other targets are included in case exposure arrays. Every exposure is finite
and nonnegative; disruption is in [0,1]; link factors in [0,.2]. Dependencies
reference candidates and tiers 1 or 2 and are acyclic. No external optimizer is
required: this bounded instance admits exhaustive search with pruning. Each
fresh execution has 90 seconds; there is no speed bonus.

Reject invalid horizon, mismatched crew/exposure lengths, invalid candidate IDs,
negative/nonfinite exposure, invalid job duration, invalid blackout slot, and
cyclic dependencies (including the intrinsic tier-1-before-tier-2 edges).
Return nonzero with a diagnostic. Do not change static telemetry semantics.

## V4: contingent continuation after a forecast signal

In addition to the fixed schedule above, compute an optimal two-stage POLICY.
At the START of slot `execution.reveal`, an external signal identifies exactly
which configured forecast case will occur. Before this signal no case-dependent
action is allowed; forecast exposures do not themselves reveal the case.
Reveal is an integer from zero through horizon, inclusive.

Each policy branch is a COMPLETE schedule from slot zero, with the SAME set of
jobs starting STRICTLY BEFORE reveal. These jobs are irreversible commitments:
keep their target, tier, start, finish and ready times identical in every branch.
This includes jobs still running or warming at reveal. A job starting AT reveal
may differ by case. No early restart, cancellation, free prerequisite, reset of
budget, reset of region activation, or refund is permitted at the branch point.
Every branch separately satisfies all rules and total resources for its full
schedule. A later job uses readiness and regional cooldown left by earlier jobs.

Choose the shared prefix and one continuation per case jointly. Maximize minimum
REALIZED whole-window branch net across cases; then maximize their sum; then
minimize SUM of branch credits, SUM of branch power, and lexicographically the
concatenation of branch start vectors in configured case order. These sums are
tie-break valuations across alternative worlds, not a shared budget: only one
branch happens. Each branch is evaluated in its own case, not by a minimum over
all cases. You may not choose each complete branch independently and merely
delete its differing early jobs. Nor is the best fixed schedule's prefix
necessarily the best contingent prefix.

The fixed schedule remains required for comparison. Put the policy in
`execution.contingency`:

```
{
 "reveal":3,
 "prefix":[],
 "branches":[
   {"actions":[],"slots":[],"final_tiers":{},"credits":0,"power":0,
    "active_regions":[],"peak_crews":0,"start_vector":[],
    "case":{"id":"weekday","baseline":0,"net":0,"net_bounds":[0,0],"residual":0}}
 ],
 "worst_case_net":0,"total_case_net":0,"total_credits":0,"total_power":0
}
```

Use all fields and sorting/coverage rules from the fixed schedule. Branches are
in case order and contain only their own realized `case` record. Prefix is the
common actions with start < reveal, in the usual action order. Each branch's
uncertainty interval is for that chosen branch's complete shared-observation
coefficients, not a reoptimized schedule or independent slot-wise bounds.
At reveal=0 the common prefix is empty; at reveal=horizon no jobs may differ.
The generic valid-probe scope includes these boundary cases, case permutations,
jobs crossing the signal, and changed forecasts. Invalid reveal boundaries
(noninteger, negative, greater than horizon) must produce diagnostics.

Discuss the information value (contingent worst net minus fixed worst net) and
prefix commitments in the decision memo. You may enumerate feasible complete
schedules, group by common prefix and select continuations, or use any correct
standard-library search method. Planning strategy is not graded.
