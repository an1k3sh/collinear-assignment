# CFO follow-up: replace B, keep A and C

Continue from the workbook you just delivered. Replace only the revenue
method, not the entire assignment. Keep all driver, working-capital, earnings,
cash, debt and preservation requirements from `/app/FINANCE_CONVENTIONS.md`.

**D. Cohort customers.** Complete Cohorts!E8:P20. Row 8 is the existing base:
January = Drivers!E12 x (1 - January existing churn, row 10); each later month
rolls the preceding customer count by (1 - current existing churn).
Rows 9-20 are the Jan-Dec launch cohorts. Before launch use `=0`; in launch
month use current additions (Drivers row 9) with no churn; afterwards roll
the same cohort by (1 - current new-cohort churn, row 11). Keep fractions.

**E. Cohort MRR.** Complete Cohorts!E25:P37; MRR row = customer row + 17.
Existing January MRR = active customers x Drivers!E13 x (1 + January uplift).
New-cohort launch MRR = launch customers x that month's Drivers row 14 x
(1 + launch-month uplift). Before launch use `=0`. Afterwards roll prior MRR
by its appropriate churn factor and (1 + current calendar-month uplift).
An uplift applies to all cohorts alive that month, **including a cohort
launched that month**, and persists thereafter. Later launch cohorts do not
inherit old uplifts. All customers are billed for a full launch month.

Preserve installed totals in Cohorts rows 21/38. Replace Revenue!E6:P10:
rows 6/8 link total cohort MRR; row 7 is current / previous revenue - 1;
row 9 links total cohort customers; row 10 is revenue / customers.
January growth still compares with December actual revenue.

**F. Propagate.** Recalculate all A/C schedules. Replace Checks row 14 with
Revenue revenue - Cohorts total MRR, row 15 with Revenue customers - Cohorts
total customers. Keep legacy-growth driver row 6 populated but unused by
revenue or downstream outputs. No parallel legacy scenario.

Update the same baseline workbook and handoff. Set `method` to
`customer_cohort_calendar`. January should derive 1,020 customers and $123,000
revenue. Later stages have not been requested; finish this one.
