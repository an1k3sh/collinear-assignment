# Community grant allocation: authoritative close policy

## Workbook inputs and supported updates

`Control!B2` is the close cutoff (Excel date/time); `Control!B3` is the available
USD budget. `Programs!A2:F9` contains eight fixed programs, with columns
program ID, name, weight, maximum award USD, approval, tie rank.
`Rates!A2:B4` contains currency codes and USD per unit of currency.
`Ledger!A:H` contains program ID, item ID, revision, recorded timestamp,
effective timestamp, status, currency and signed amount in that currency.

The program and item IDs are exact TEXT identifiers, not numbers. Different
text is a different ID even if numeric conversion gives the same value.
Names and visual number formats are not identifiers. All keys and
currencies are case-sensitive; the supplied keys are already in canonical case.

The controller may:

* change budget, cutoff, weights, maximum awards, approvals and FX rates;
* add, replace, reorder or clear ledger rows within rows 2 through 501 inclusive;
* change program names and reorder rate rows;
* hide or filter source rows without excluding them economically.

The set/order of eight program IDs and their unique integer tie ranks remains
fixed. Weights are integers 1..100. Budgets and maximum awards are nonnegative
USD amounts with at most two decimals and at most $100,000. Signed ledger
amounts have at most three decimal places; absolute USD-equivalent amounts
are at most $100,000 per record. FX rates are positive and at most 10 with
at most four decimals. All ledger currencies and program IDs exist in the
reference tables. A blank ledger row has blank A:H and is ignored.
No new currency, ninth program or row beyond 501 is required.

## Reconstruct eligible expenses at the cutoff

The ledger is a versioned complete-state export, keyed by
`(program ID,item ID)`. Revisions are positive integers, unique and increasing
with recorded time within a key; rows are not necessarily sorted.

For each key, among records whose RECORDED time is at or before the cutoff,
select the greatest revision. Only AFTER selecting that version, count it if
its status is `posted` and its EFFECTIVE time is at or before the cutoff.
Statuses `draft` and `void` do not count. An ineligible selected version does
not revive a prior version.

Convert each counted signed amount to USD using the current Rates table.
Round EACH converted line to whole cents, with half cents rounded away from
zero, then sum those integer cents for the program. This net sum is the
program's eligible expense balance. It may be negative after refunds.

## Fundable caps

Only a program whose approval is exactly `approved` receives funding.
Its cap in cents is the smaller of its maximum award and its eligible balance,
clamped below at zero. A program on `hold` has cap zero, but its eligible expense
balance must still be reported. Convert budget and maximum awards to exact cents.

## Weighted capped distribution

Let C_i be each program's fundable cap in cents and w_i its weight.
Distribute T = min(budget_cents, sum(C_i)).

The ideal nonnegative fractional-cent allocation q_i is capped proportional
allocation (weighted water filling):

    q_i = min(C_i, lambda * w_i), with sum(q_i) = T.

If T is zero, all q_i are zero. At full funding use q_i=C_i. Otherwise choose
the nonnegative water level lambda satisfying the equation. Capped programs
do not consume an ongoing share of weight; their excess is redistributed to
remaining programs, potentially across several rounds.

First award floor(q_i) whole cents to every program. Then distribute the
remaining T - sum(floor(q_i)) cents, one per program, in DESCENDING order of
fractional remainder q_i-floor(q_i). Equal remainders are resolved by ASCENDING
integer tie rank from Programs column F. Do not round each share independently.
Final awards must sum to T, must not exceed caps, and must not be negative.

## Required workbook outputs

Keep `Summary!A2:A9` as the original program IDs in their original order.
For those rows, these cells must be formulas with the following meaning:

* B: program name
* C: eligible expense balance in USD
* D: fundable cap in USD
* E: ideal fractional allocation in USD (do not round away its fractional cents)
* F: final award in USD, exactly two-decimal cents

`Summary!F12` is the total awarded and `Summary!F13` is budget minus total
awarded (unspent authorization); both must be formulas.
Show one editable chart on Summary whose eight categories reference B2:B9
and whose sole values series references final awards F2:F9, not a stale copy.
Additional helper tables or sheets are permitted.

Preserve all original input values/types in Control, Programs, Rates and
Ledger; additional derived columns can start at Ledger column I.
Preserve the historical `PriorClose` sheet's original values as audit evidence.
No macros, external workbook links, external queries or required scripts.
The workbook must recalculate correctly in the installed LibreOffice and save
numeric cached results for the initial close.
