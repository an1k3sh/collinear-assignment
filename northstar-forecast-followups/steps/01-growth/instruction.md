# First request: finish the FY2026 forecast

Read `/app/FINANCE_CONVENTIONS.md`, inspect the starter, and complete the baseline
forecast and JSON handoff. Preserve all existing presentation and installed
formulas. This is a synthetic subscription business.

Do A, B and C:

**A.** Populate all driver formulas and the working-capital schedule described
in the conventions.

**B.** Use the legacy monthly growth method. Complete Revenue!E6:P8:
revenue = previous month's revenue x (1 + current Drivers row 6);
month-on-month growth = current / previous revenue - 1; exit MRR = revenue.
January uses December historical revenue. Leave Revenue!E9:P10 and all yellow
Cohorts targets blank. Checks rows 14-15 must contain `=0` because cohorts are
not applicable.

**C.** Complete the P&L, cash flow, revolver and live controls using the shared
conventions. Set `method` in handoff.json to `legacy_monthly_growth`.

Save `/app/output/Northstar_Forecast_Completed.xlsx` and
`/app/output/handoff.json`. Stop after completing this request.
