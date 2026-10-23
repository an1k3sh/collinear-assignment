# Final follow-up: authorize cutover, replace the stress and retain renewal pricing

Use the reconciliation you already delivered. In **both** workbooks, update
only Historical!D22 and D23 to the corrected opening cash and revolver.
These two numeric historical corrections are now explicitly authorized;
all other historical cells and pre-existing formulas remain immutable.
The net adjustments are already part of opening balances: do not also book
them as January CFO, financing, capex or revenue.

Keep the **quarterly renewal adoption** method from the latest pricing
revision, acquisition/churn, financial conventions, source-linked drivers and
all baseline assumptions. Refresh every dependent monthly result, interest,
cash/debt roll-forward, handoff and board pack. Keep the reconciliation.

Replace, rather than layer on, the previous board stress:

- **Withdraw the DSO stress:** stress DSO must return to the matching baseline
  source value in every month (35 at delivery), not retain 50.
- **Replace the all-year 7,200 capex assumption:** January-June stress capex
  returns to baseline (5,000 at delivery); July-December stress capex is 12,000.
- Retain stress DPO 18, minimum cash 45,000 and annual interest 14% in every
  month. These three stress requirements were not withdrawn.
- Other stress source values stay aligned with baseline. The stress workbook
  still uses its own Assumptions cells and no external links.

The verifier may change matching non-overridden baseline/stress Assumptions
cells on disposable copies. For example a new January capex source must flow
through January, while the July-December fixed 12,000 stress remains fixed.

Deliver the same five artifacts: baseline workbook, stress workbook,
handoff.json, board-pack.json and treasury_reconciliation.json. Preserve their
schemas and the `customer_cohort_renewal` method identifiers. Refresh the board
pack's monthly bridge, peaks and first debt-free months; do not leave it at
the prior stress or unadjusted opening balances. Revalidate before finishing.
