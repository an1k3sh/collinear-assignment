# Northstar Cloud: finish the forecast, incorporating the CFO's revision

You are taking over the FY2026 financial forecast for a subscription software
business. The workbook was commissioned under the original brief below; a CFO
revision is included later in this same message. **Deliver one final workbook
that satisfies the revised brief. The revision replaces B only; A and C remain
required. Do not deliver both scenarios or first submit the obsolete method.**

## Files, tools and deliverables

- Starter: `/app/seeds/Northstar_Forecast_Starter.xlsx`.
- Source assumptions and historical actuals are inside that workbook.
- Python 3, `openpyxl`, and LibreOffice Calc (`libreoffice`) are installed.
- Save `/app/output/Northstar_Forecast_Completed.xlsx`.
- Also save `/app/output/handoff.json`, as specified at the end.
- Do not modify the seed file. Work on a copy. No network or external data is
  needed. There is no requirement to use a particular editing tool.

The workbook has ten sheets. Yellow cells are unfinished completion targets.
Blue and green cells contain immutable actuals and source data. Gray cells
contain existing formulas. All amounts are USD, not USD thousands. Expenses,
capex and debt repayments are positive amounts; subtract them where appropriate.

## Original commission

### A. Complete drivers and working capital

Populate **Drivers!E6:P25** with direct references to matching **Assumptions**
cells. Keep all assumptions, including the legacy growth row, populated.

Complete **Working Capital!E6:P8** and **E10:P12**:

| Row | Required calculation |
|---|---|
| 6 | AR = current-month subscription revenue / actual days in month x DSO |
| 7 | AP = current-month hosting cost / actual days in month x DPO |
| 8 | Net operating working capital = AR - AP |
| 10 | Change in AR = current AR - previous-month AR |
| 11 | Change in AP = current AP - previous-month AP |
| 12 | Working-capital cash impact = -change in AR + change in AP |

For January movements, use December actual balances linked in column D.
There is no inventory, deferred revenue, accrued payroll or other operating
working capital.

### B. Original revenue method — superseded by the CFO revision below

The original request was to fill **Revenue!E6:P8** with revenue equal to the
previous month's revenue times (1 + the legacy monthly growth assumption in
Drivers row 6), compute month-on-month growth, and set exit MRR equal to
revenue. Cohorts and forecast customer counts would have remained inactive.

**This method must not be used in the final workbook.** It is retained here
to make the change history explicit, not as an additional deliverable.

### C. Complete earnings, cash flow, financing and controls

Complete **P&L!E7:P17**. Preserve the existing revenue-link formulas in row 6.

| Row | Required calculation |
|---|---|
| 7 | Hosting cost = revenue x hosting-cost percentage |
| 8 | Gross profit = revenue - hosting cost |
| 9 | Payroll = previous-month payroll x (1 + current payroll growth) |
| 10 | Sales & marketing = revenue x S&M percentage |
| 11 | G&A = previous-month G&A x (1 + current G&A growth) |
| 12 | EBITDA = gross profit - payroll - S&M - G&A |
| 13 | Depreciation = current depreciation assumption |
| 14 | EBIT = EBITDA - depreciation |
| 15 | Interest = opening revolver balance x annual interest rate / 12 |
| 16 | Cash taxes = MAX(EBIT - interest, 0) x tax rate |
| 17 | Net income = EBIT - interest - cash taxes |

January payroll and G&A roll from December historical actuals. There are no
tax refunds, loss carryforwards, interest income or other non-operating items.

Complete **Cash Flow!E10:P10**, **E12:P12** and **E14:P18**. Preserve other rows:

| Row | Required calculation |
|---|---|
| 10 | CFO = net income + depreciation + working-capital cash impact |
| 12 | Pre-financing closing cash = opening cash + CFO - capex |
| 14 | Draw = MAX(minimum cash - pre-financing closing cash, 0) |
| 15 | Repay = MIN(opening debt, MAX(pre-financing closing cash - minimum cash, 0)) |
| 16 | Net financing = draw - repay |
| 17 | Closing cash = pre-financing closing cash + net financing |
| 18 | Closing debt = opening debt + net financing |

The revolver is uncapped. No dividends, equity or other cash movements. Use
opening-debt interest to avoid circularity. Do not draw and repay together.

Complete **Checks!E6:P15** with the following formula-driven residuals:

| Row | Residual; zero means pass |
|---|---|
| 6 | P&L revenue - Revenue subscription revenue |
| 7 | AR / revenue x actual days - DSO |
| 8 | AP / hosting cost x actual days - DPO |
| 9 | Net income - (EBIT - interest - cash taxes) |
| 10 | Closing cash - (opening cash + CFO - capex + draw - repay) |
| 11 | Closing debt - (opening debt + draw - repay) |
| 12 | MAX(minimum cash - closing cash, 0) |
| 13 | MIN(draw, repay) |
| 14 | Revenue subscription revenue - total cohort MRR |
| 15 | Revenue active customers - total cohort active customers |

Rows 14-15 reflect the CFO revision. No hardcoded zero plugs are permitted.

## CFO revision: replace B with D, E and F

Change of plan: use a customer-cohort forecast, **not** the legacy growth-rate
revenue model. Keep A, C and every preservation constraint below.

### D. Build expected active customers by cohort

Complete **Cohorts!E8:P20**:

- Row 8 is the base existing at 31-Dec-2025. January active customers =
  **Drivers!E12** x (1 - January existing-customer churn, row 10). Thereafter,
  roll this cohort's previous-month customers by (1 - current existing churn).
- Rows 9-20 are the Jan-Dec 2026 acquisition cohorts in order.
- Before a cohort's launch, enter a formula `=0`.
- In its launch month, customers equal that month's new additions, **Drivers
  row 9**. Do not apply launch-month churn.
- In later months, roll that cohort's previous-month customers by (1 - current
  new-cohort churn, **Drivers row 11**).
- Customer counts are expected values. Retain fractions; do not round.

Preserve existing customer totals in row 21.

### E. Build MRR by cohort and replace the revenue forecast

Complete **Cohorts!E25:P37**. Each MRR row maps to the customer row 17 rows above.

- Existing-base January MRR = January existing active customers x starting
  existing monthly ARPC, **Drivers!E13**, x (1 + January calendar-month uplift,
  row 15).
- Existing-base later MRR = previous-month MRR x (1 - current existing churn)
  x (1 + current calendar-month uplift).
- New-cohort pre-launch MRR = `=0`.
- New-cohort launch MRR = launch customers x launch-month starting new monthly
  ARPC, **Drivers row 14**, x (1 + launch-month uplift).
- New-cohort later MRR = previous-month MRR x (1 - current new-cohort churn)
  x (1 + current calendar-month uplift).

**The July uplift applies to every cohort alive in July, including the July
launch cohort. Cohorts launched after July do not inherit July's uplift.**
Once applied, an uplift compounds into the affected cohort's subsequent MRR.
Use the same rule if another month has an uplift.

All active customers are billed for a full month, including acquisition month.
Revenue is recognized immediately. There are no annual prepayments, partial
months, discounts, services or deferred revenue. Drivers rows 12-14 are starting
reference assumptions, not recurring additions to the existing customer base.

Preserve the existing total MRR formulas in row 38. Complete **Revenue!E6:P10**:

| Row | Revised calculation |
|---|---|
| 6 | Link to matching month in Cohorts row 38 |
| 7 | Current revenue / immediately preceding-month revenue - 1 |
| 8 | Link to matching month in Cohorts row 38 |
| 9 | Link to matching month in Cohorts row 21 |
| 10 | Revenue / active customers |

January growth compares with December historical revenue. Keep
**Drivers!E6:P6** populated for audit, but no final forecast output may depend on
legacy growth. Do not blend the methods or keep an alternate scenario.

### F. Propagate, recalculate and verify

The cohort-based revenue must feed all applicable A/C schedules: hosting,
S&M, working capital, taxes, CFO, interest, cash and debt. All ten check rows
must be numeric and within **0.005 absolute** of zero.

The workbook must also respond correctly if finance changes source assumptions.
The verifier recalculates private temporary copies under these **public**
sensitivity cases (your delivered sources must remain unchanged):

1. Legacy growth is replaced with 70% every month: revised outputs must not
   change.
2. March additions become 67; June new-cohort churn becomes 2.5%; July uplift
   becomes 6%; October gets an additional 2% calendar uplift.
3. January existing customers become 940; starting existing ARPC becomes 125;
   August new-cohort starting ARPC becomes 149.
4. DSO becomes 50, DPO becomes 18, minimum cash becomes 45,000, annual debt
   interest becomes 14%, and monthly capex becomes 7,200, in every month.

These edits are made to the matching **Assumptions** cells, so the Drivers
references must transmit them. All schedules must remain correct without
hand-editing formulas, and the check rows must still pass.

To verify the controls themselves, the verifier also intentionally overwrites
January intermediate outputs (revenue, customer count, AR/AP, net income, cash,
debt, draw and repayment) in a disposable audit copy. Each check must then report
its stated residual from those changed values, rather than returning a constant
zero or hiding discrepancies. Only the controls are assessed in that deliberately
inconsistent copy, not the financial forecast.

## Preserve the workbook; do not rebuild it

- Write only the yellow completion ranges explicitly listed above. There are
  1,020 target cells, all of which must contain formulas in the final workbook.
- Do not change the historical actuals, source assumptions, other cell values,
  or pre-existing formulas. Keep their comments intact.
- Preserve sheet names/order, cell fonts/fills/borders, number formats,
  alignment, protection settings, row heights, column widths, merged cells,
  freeze panes, data validations, chart and its placement, conditional
  formatting, and print settings. XML serialization details are not graded.
- Do not add sheets, macros, external links, balancing plugs or hardcoded
  forecast outputs. Do not round intermediate calculations.
- Existing column-Q formulas compute annual sums for flows, December values
  for balances/rates/counts, January opening cash/debt for opening balances,
  and maximum absolute residuals for checks. Preserve these formulas.
- The verifier recalculates a disposable copy using LibreOffice. Cached
  formula values need not already be populated in your submitted file.
  You may use LibreOffice to validate your work, but submit the formatting-
  preserved original you edited rather than a conversion that restyles it.

## Durable handoff

Save the workbook and a machine-readable **handoff.json** with:

```json
{
  "method": "customer_cohort",
  "superseded_method": "legacy_monthly_growth",
  "annual_revenue": 0,
  "december_active_customers": 0,
  "december_cash": 0,
  "december_revolver": 0,
  "max_abs_check": 0
}
```

Replace the numeric examples with independently verified baseline forecast
results (not stressed results). Financial numbers and customer counts must be
within 0.005 absolute of recalculated results. Key order and extra explanatory
fields do not matter. The two method identifiers specify the selected scenario.
Do not claim completion unless the delivered workbook and handoff agree.
