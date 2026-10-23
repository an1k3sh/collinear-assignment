# Dispatch desk, 07:50

This is a same-day plan, not a simulation of unknown future orders. The input
exports are the final complete evidence set for the planning cutoff in
`data/settings.json`. No additional requests need to be guessed.

The workstation's old summary used 20 orders. Operations cannot authorize that
summary. Reconstruct the order roster before scheduling, and record your roster
in the plan so customer services can understand what is actually going out.

Read `reconciliation.md`, `operations.md` and `output.md`. The CSV files are
exports, not prefiltered planning tables. All amounts and identifiers are exact;
leading zeroes and depot scopes are significant. All jobs belong to this depot,
but customer account namespaces remain separate.

The manager's budget is a hard procurement authorization, not an optimization
score. A feasible plan below the cap is sufficient. Staff and vehicles cannot
be added. Third-party solver packages already in the image are permitted.

The carrier charges for reserved vehicles, dispatched trips and driving minutes.
Waiting costs no additional money but consumes the vehicle's time, customer
window and product's thermal allowance. See `operations.md`.
