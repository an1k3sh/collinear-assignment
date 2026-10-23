# Grant allocation close: repair report

## Problems found in `/app/grants.xlsx`
1. **Hard-coded Summary.** `Summary!B2:F9` held typed constants (every eligible, ideal and award value was $100). The caps had been copied in as values. Nothing was linked to the Ledger, Programs, Rates or Control sheets.
2. **Wrong totals.** The awards added up to $800.00 against a $900.03 budget. Several awards were above their caps (for example, Food access got $100 against an $80 cap, and Language classes got $100 against $60). The awards ignored the weights and tie ranks.
3. **Stale chart.** The chart read its data from the hidden `PriorClose` sheet, not from the current awards.
4. **Manual calculation.** The workbook was set to `calcMode="manual"`.

## Repairs (input values, types and formats are unchanged)
- **Ledger!I:N (rows 2–501, helper formulas):**
  - I: an unambiguous key, built as `LEN(program)|program&item`.
  - J: whether the row was recorded at or before the cutoff.
  - K: whether the row is the selected version. A row is selected when no in-scope row with the same key (matched exactly, case-sensitive, using `EXACT`) has a higher revision.
  - L: whether the selected row counts. It must have status exactly `posted` and an effective time at or before the cutoff. An ineligible selected version does not bring back an earlier one.
  - M: the FX rate, found with a case-sensitive lookup.
  - N: the line amount in cents, `ROUND(ROUND(amount*rate*100,6),0)`. This rounds half-cents away from zero and is safe against floating-point error.
  - Blank, hidden and filtered rows are handled correctly because all aggregation uses `SUMPRODUCT`, not `SUBTOTAL`.
- **New `Calc` sheet (all in integer cents):**
  - Looks up each program by its exact text ID, so `001`, `01` and `1` stay distinct.
  - Computes the eligible net balance and the cap: `approved` programs get `max(0, min(max award, balance))`; any other approval gets 0.
  - Sets T = min(budget, sum of caps).
  - Runs the weighted water-filling allocation. A program is saturated when f(C_i/w_i) ≤ T, tested exactly as integer cross-products. This gives the multi-round result in one step.
  - Unsaturated programs get (T − saturated caps)·w_i / remaining weight.
  - Each program gets the floor of its share. Leftover cents go in order of exact remainder numerator (descending), then tie rank (ascending).
  - Check cells at `Calc!S8:S10`: awards = T, 0 ≤ award ≤ cap, and all IDs resolved.
- **Summary:**
  - B:F are formulas: name, eligible USD, cap USD, unrounded ideal USD (shown to 5 decimals) and award USD.
  - `F12 = SUM(F2:F9)` and `F13 = ROUND(Control!B3-F12,2)`.
- **Chart:** replaced with an editable bar chart. Categories are `Summary!$B$2:$B$9` and the only series is `Summary!$F$2:$F$9`.
- **Calculation:** set to automatic with full calculation on load. Cached results are saved, as computed by LibreOffice.
- `PriorClose` (still hidden) and all source sheet names are kept. The workbook has no macros, external links or queries.

## Initial close (cutoff 2026-04-30 23:59, budget $900.03)
| ID | Eligible | Cap | Ideal | Award |
|---|---|---|---|---|
| 001 | 133.20 | 80.00 | 80.000 | 80.00 |
| 01 | 261.00 | 180.00 | 76.265 | 76.27 |
| 1 | 88.80 | 60.00 | 60.000 | 60.00 |
| 010 | 127.50 | 127.50 | 127.500 | 127.50 |
| 10 | 666.00 | 250.00 | 250.000 | 250.00 |
| A2 | 192.00 | 90.00 | 90.000 | 90.00 |
| A10 | 177.60 | 110.00 | 76.265 | 76.26 |
| R&D | 223.09 | 140.00 | 140.000 | 140.00 |

The total awarded is $900.03 and the unspent amount is $0.00. Programs 01 and A10 tie on a half-cent remainder, so the extra cent goes to 01 (tie rank 2 beats 8). Some ledger rows are correctly left out:
- 001/001 revision 2 was recorded after the cutoff.
- 010/001 revision 2 was selected but is effective after the cutoff, so it counts as nothing.
- 01/01 revision 2 is `void`.
- 1/DRAFT is a draft.
- R&D's −10.005 USD refund rounds to −10.01.

## Validation
- An independent Python reference used exact `Fraction`/`Decimal` arithmetic and iterative water-filling. It was compared with LibreOffice headless recalculation in these cases:
  - the delivered file;
  - 17 targeted edits: budget sweeps from $0 to $5,000 including the full-funding boundary, programs on hold, changed cutoffs, hidden rows, rows cleared or added at row 501, reordered or changed rates, and equal weights;
  - 68 randomized scenarios with up to 499 shuffled rows, IDs that differ only in case or leading zeros, half-cent amounts, refunds, and records exactly at the cutoff.
- There were 0 mismatches.
- The source sheets are identical to the original in value, type and number format.
