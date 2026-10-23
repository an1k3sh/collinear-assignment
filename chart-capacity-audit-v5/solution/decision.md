# Reconciled rollout decision

Use Birch Query API (BS) tier 1 and Birch Write API (BI) tier 2. All other
targets receive tier zero. Cost is 14 credits including Birch's activation
cost, power is 8, and only Birch is active. The nominal weighted benefit is
26,320 and residual weighted risk is 90,530. This is an optimization under
the supplied planning assumptions, not a measured causal benefit.

The original budget is 16 credits. Two unused credits do not buy another
admissible improvement: opening Delta and its first Query tier needs four
additional credits. With 14 credits the same plan remains best. With 18,
add DS tier 1: 18 credits, power 10, two active regions, benefit 31,820.
The Birch regional block cap also prevents simply increasing both Birch
targets to tier 2. Power and active-region limits are checked independently.

Source authority: C2.r2 replaces all of C2.r1. Keep the original in the
inventory for traceability but do not add it to the corrected counter series.
The other r1 pages remain current.

Traffic reconstruction: AS W3 resets both counters; BI W2 resets only the
error counter. DS B2 is missing, which excludes W2. DS W3 remains measurable
because its explicit resets replace the missing start readings. DI W2 is
maintenance; its values are preserved but excluded. Counts are counter deltas,
not rates to multiply by duration. Mean arrival rates divide by duration.

Latency: pool disjoint counts only from usable, matched windows. CS has 310
slow samples out of 13,000, despite three individually slow windows. AI and DI
also fail the latency trigger. CI passes latency but Cedar's change freeze
blocks deployment; its high risk is still in the residual.

The report readings include bounded uncertainty. The analysis cancels shared
target coefficients when comparing the nominal winner against every feasible
rival. The positive worst-rival margin and stable latency classifications
support a robust nominal plan; see analysis.json for the computed certificate.
The causal claim about the deployment is unsupported.

Every conclusion is backed by inventory, per-window reconstruction, joined
histograms and the executable counterfactual-capable analysis.
# Executable change window (v3)
# Contingent policy (v4)

With the forecast revealed at slot 1, commit only DS tier 1 at slot 0.
Then:
* weekday: BS1 at slot 1, DS2 at slot 2; net 144,260.
* write-burst: BI1 at slot 1, BS1 at slot 3; net 171,650.
* regional-shift: AS1 at slot 1, DS2 at slot 2; net 160,695.

Each branch retains the DS0 commitment and accounts for all its costs,
readiness and resource occupation. Guaranteed net increases from fixed-schedule
121,050 to 144,260: information value 23,210. Net sum is 476,605.
The sums used only for policy tie-breaking are 38 credits and 21 power across
alternative worlds, not one branch's consumption or a shared three-case budget.
This policy does not reuse the fixed plan's BS0/DS0 prefix. Planning.json and
execution-policy.md specify the information boundary and irreversible state.


This is a separate decision from the static sizing optimum. Start BS tier 1 and
DS tier 1 in slot 0. DS finishes and is ready in slot 1; BS finishes and is ready
in slot 2. Leave the Birch region idle in slot 2, then install BI tier 1 in slot
3. BI finishes at 4 and becomes effective at 5 after warmup.

The schedule ends with BS1, BI1, DS1, not the static BS1/BI2 allocation.
It uses 14 credits, 8 power, two regions, three jobs, and peak crew use two.
Worst-case net benefit is 121,050 (write-burst); all-case sum is 449,910.
Weekday net is 157,170 and regional-shift net is 171,690. Forecast residuals
are 1,149,930; 1,399,750; and 1,162,160 respectively.

The write-burst net interval is [120,529.5,121,570.5] for the oracle readings.
Bounds aggregate shared target coefficients before selecting interval endpoints.
These bound this chosen schedule, not its optimality under uncertain readings.
Disruption, warmup, per-slot crew availability, Birch's idle gap and the
BS/BI path valuation are included. See planning.json and execution-policy.md;
the workload basis remains corrected C2.r2 and the reset-aware C4.r1 history.
