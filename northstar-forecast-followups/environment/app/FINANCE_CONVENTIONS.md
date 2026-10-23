# Northstar model conventions

Use the current instruction to select the active method. This document states
only shared mechanics and preservation constraints, not future requests.

## Files and tools

Starter: `/app/seeds/Northstar_Forecast_Starter.xlsx`.
Baseline deliverables: `/app/output/Northstar_Forecast_Completed.xlsx` and
`/app/output/handoff.json`. Python 3, openpyxl and LibreOffice are installed.
Do not modify the starter. No network, external data or dependency installation
is required. All values are USD, not thousands. Keep fractional expected
customers and full intermediate precision.

## Drivers and financial schedules

Drivers!E6:P25 must directly reference matching Assumptions cells. Unused
drivers remain populated for audit. All expenses and repayments are positive.

Complete Working Capital!E6:P8 and E10:P12:

| Row | Formula |
|---|---|
| 6 | AR = revenue / actual days in month x DSO |
| 7 | AP = hosting cost / actual days in month x DPO |
| 8 | AR - AP |
| 10 | current AR - preceding AR; January uses December actual |
| 11 | current AP - preceding AP; January uses December actual |
| 12 | -change in AR + change in AP |

There is no inventory, deferred revenue or other operating working capital.
Complete P&L!E7:P17; preserve row 6's installed revenue links:

| Row | Formula |
|---|---|
| 7 | hosting = revenue x hosting percentage |
| 8 | gross profit = revenue - hosting |
| 9 | preceding payroll x (1 + current payroll growth) |
| 10 | S&M = revenue x S&M percentage |
| 11 | preceding G&A x (1 + current G&A growth) |
| 12 | EBITDA = gross profit - payroll - S&M - G&A |
| 13 | depreciation assumption |
| 14 | EBIT = EBITDA - depreciation |
| 15 | opening revolver x annual interest rate / 12 |
| 16 | MAX(EBIT - interest, 0) x cash tax rate |
| 17 | EBIT - interest - cash taxes |

January payroll and G&A use December actuals. No refunds or loss carryforwards.
Complete Cash Flow!E10:P10, E12:P12 and E14:P18; preserve the other rows:

| Row | Formula |
|---|---|
| 10 | CFO = net income + depreciation + working-capital cash impact |
| 12 | pre-financing cash = opening cash + CFO - capex |
| 14 | draw = MAX(minimum cash - pre-financing cash, 0) |
| 15 | repay = MIN(opening debt, MAX(pre-financing cash - minimum cash, 0)) |
| 16 | financing = draw - repay |
| 17 | closing cash = pre-financing cash + financing |
| 18 | closing debt = opening debt + financing |

No equity, dividends, other investing flows or borrowing cap. Opening debt
interest prevents circularity. Never draw and repay together.

Checks!E6:P15 must be live formula residuals:

| Row | Residual |
|---|---|
| 6 | P&L revenue - Revenue revenue |
| 7 | AR / revenue x actual days - DSO |
| 8 | AP / hosting x actual days - DPO |
| 9 | net income - (EBIT - interest - taxes) |
| 10 | closing cash - (opening cash + CFO - capex + draw - repay) |
| 11 | closing debt - (opening debt + draw - repay) |
| 12 | MAX(minimum cash - closing cash, 0) |
| 13 | MIN(draw, repay) |
| 14 | cohort revenue tie-out, or =0 only if the active instruction disables cohorts |
| 15 | cohort customer tie-out, or =0 only if cohorts are disabled |

All monthly residuals must have absolute value <= 0.005. The verifier also
changes intermediate outputs on a disposable inconsistent copy to confirm
checks report their stated residual rather than a constant zero. Equivalent
revenue aliases are accepted in the AR-days check.

## Preservation

Write only active yellow targets; there are 1,020 when all cohorts are active.
Keep inactive targets blank. No hardcoded forecast outputs (even disguised
as formulas), zero-plug controls, external links, macros, extra sheets or
rounding. Explicit `=0` is allowed before a cohort exists.

Do not change actuals, source assumptions, labels, pre-existing formulas or
other values unless a later instruction expressly authorizes a particular
exception. Preserve all sheet names/order, fonts/fills/borders, number
formats/alignment/protection, dimensions, merged cells, comments, freeze panes,
data validations, conditional formatting, chart/placement and print settings.
XML/ZIP serialization and formula spelling are not graded.

Existing column Q formulas sum flows, use December for counts/rates/balances,
January for opening cash/debt, and maximum absolute residuals for controls.
They must remain unchanged. The verifier recalculates disposable copies in
LibreOffice; caches in the delivered workbook are optional. Do not submit a
LibreOffice-converted version if it changes the supplied presentation.

## Handoff and sensitivities

handoff.json is an object with `method` (as specified by the active instruction),
numeric `annual_revenue`, `december_cash`, `december_revolver`, and
`max_abs_check`; include numeric `december_active_customers` when cohorts are
active. Values must match the recalculated baseline within 0.005 absolute.
Key order and extra explanatory fields do not matter.

The verifier changes Assumptions in disposable copies and requires the entire
model to stay correct. Base sensitivity: replace all legacy growth rates with
70%. Cohort sensitivities, when applicable: March additions 67, June new churn
2.5%, July uplift 6%, October uplift 2%, January opening customers 940, January
existing ARPC 125, and August new starting ARPC 149. Financial sensitivity:
February DSO 47, May DPO 21, September capex 11,000. It may also change every
month's minimum cash to 45,000 and annual interest to 14%. These are tests, not
permission to alter delivered sources. Later requested scenarios must retain
their explicit scenario overrides while still following other source changes.
Calendar/renewal timing is also tested with February uplift 3%, March 2% and
December 5% to exercise combined pending events and renewals beyond year-end.
