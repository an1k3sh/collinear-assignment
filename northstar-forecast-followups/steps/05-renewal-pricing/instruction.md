# Return to the model: revise price adoption; keep the other work

Resume both forecast workbooks. The CFO withdraws **calendar-immediate price
adoption**, not cohort acquisition or churn. Replace it with **quarterly renewal
adoption** below. Keep the stress assumptions from the board request, the
treasury reconciliation, all financial schedules and formatting constraints.
Do not apply the reconciled opening balances yet.

Calendar uplift assumptions still announce price events, but the event reaches
an eligible cohort only at its next scheduled quarterly renewal:

- Existing base renews in January, April, July and October (zero-based month
  indices 0, 3, 6, 9).
- A new cohort launched in month `s` first renews at `s+3`, then `s+6`, `s+9`,
  etc. Acquisition month is not a renewal.
- A price event announced in month `t` applies only to cohorts launched on or
  before `t`. A cohort launched after `t` never inherits that event.
- For an eligible cohort, apply (1 + event uplift) once, at its first scheduled
  renewal month **on or after t**. If none occurs within FY2026, it contributes
  no 2026 uplift. A cohort launched in the event month starts at its un-uplifted
  launch ARPC, then adopts that event at its first renewal three months later.
- Applied events remain in that cohort's price thereafter. Multiple events
  awaiting the same renewal multiply together; no event is lost or applied
  twice. This must work for an uplift in any calendar month, not just July.
- Customer counts and their churn timing do not change. Existing cohort uses
  its January starting ARPC; each launch cohort uses its own launch-month ARPC.
  MRR = current active customers x that cohort's correctly uplifted ARPC.

Keep Revenue, P&L, working capital, cash/debt, checks, sensitivities, handoff and
board pack consistent in both baseline and stress. Use `method` =
`customer_cohort_renewal` in both JSON outputs. No new worksheet or pricing
source changes. Existing yellow cohort MRR targets may be rewritten; preserve
their number formats and all other presentation.

Retain treasury_reconciliation.json unchanged in meaning and keep its net
adjustments **out of** the workbooks for this step.
