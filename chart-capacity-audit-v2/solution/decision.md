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
