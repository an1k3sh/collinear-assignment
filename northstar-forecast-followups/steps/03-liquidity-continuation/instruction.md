# In-domain continuation: prepare the board's liquidity stress

Keep the baseline forecast and its handoff correct and unchanged in assumptions.
Add `/app/output/Northstar_Liquidity_Stress.xlsx`, a separately editable copy
with the same formatting, formulas, sheet structure and source traceability.
In its Assumptions!E:P only, override these five rows for **every month**:

| Row | Stress value |
|---|---:|
| 16: DSO | 50 |
| 17: DPO | 18 |
| 22: capex | 7,200 |
| 23: minimum cash | 45,000 |
| 24: annual interest | 14% |

All other assumptions, historical values and conventions stay unchanged. Each
workbook must have its own current financial results; no external workbook
links. Formula-driven stresses must respond to source edits outside the
overridden rows.

Also deliver `/app/output/board-pack.json`:

```json
{
  "method": "customer_cohort_calendar",
  "baseline": {
    "annual_revenue": 0, "december_active_customers": 0,
    "december_cash": 0, "december_revolver": 0,
    "peak_revolver": 0, "first_debt_free_month": null,
    "months": [
      {"month": "2026-01", "revenue": 0, "cfo": 0, "capex": 0,
       "draw": 0, "repay": 0, "closing_cash": 0, "closing_debt": 0}
    ]
  },
  "stress": {}
}
```

Both baseline/stress objects use the same schema and contain all twelve monthly
entries, chronologically Jan-Dec. `peak_revolver` is the maximum of January
opening debt and all monthly closing debts. `first_debt_free_month` is the
first month whose closing debt is <= 0.005, formatted `YYYY-MM`, or JSON null
if none. Numeric examples above are placeholders, not expected results.
Amounts/counts must match full-precision recalculation within 0.005 absolute.
Extra fields and object-key order do not matter. Update handoff.json for the
baseline only. Retain the previously requested baseline deliverables.
