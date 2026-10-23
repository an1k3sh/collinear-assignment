# Repair report: April shared-services allocation

## Defects found
1. **Calculation set to manual** (`calcMode="manual"`, no recalc on load), so the saved results were stale.
2. **The cost pool stopped at row 5.** `SUM(Costs!$C$2:$C$5)` left out BILL-005, the $1,000 bill added later. The stale total was 10,000; the correct pool is 11,000.
3. **A saved filter hid BILL-004** (row 5). Its filter range was A1:C5, so it did not cover appended rows.
4. **Weight lookups used approximate match.** `VLOOKUP(...,TRUE)` assumes sorted IDs, so it returns wrong weights when Rates rows are reordered, and it can mix up "002" and "02". The name lookups were also fixed to Rates!A2:C4.
5. **D3 held a pasted value** (2000) instead of a formula.
6. **D4 used the wrong weight.** It referenced `C2` (Field Operations) instead of `C4` (Engineering).
7. **The chart was bound to the hidden Legacy sheet** (`Legacy!A2:A4` / `B2:B4`), so it never changed.

## Repairs
- Summary B2:B4 / C2:C4: `INDEX(Rates!$B|$C$2:$1000, MATCH($A n, Rates!$A$2:$A$1000, 0))`. This is an exact text-ID match that doesn't depend on row order. A missing ID returns #N/A, so the error isn't hidden.
- Summary D2:D4: `SUM(Costs!$C$2:$C$1000)*C n/SUM($C$2:$C$4)`. Allocations aren't rounded; the display stays in the existing `$#,##0.00` format.
- D6: `SUM($D$2:$D$4)`.
- Costs filter: criteria cleared, row 5 unhidden, and the filter range extended to A1:C1000. Plain `SUM` counts hidden rows in any case.
- Chart: the series name now comes from Summary!D1, the categories from Summary!B2:B4 and the values from Summary!D2:D4. It is still a normal editable bar chart.
- Workbook: `calcMode="auto"` and `fullCalcOnLoad="1"`. Recalculated and saved with LibreOffice.
- No changes to source values or types (Rates, Costs, Legacy), sheet names, the hidden Legacy sheet or the Summary layout. No macros or external links.

## Checks performed
- Recalculated in LibreOffice: pool 11,000 → Field Operations 5,500, Customer Support 2,200, Engineering 3,300, total 11,000. The chart cache matches.
- Ran perturbations through openpyxl edits and a LibreOffice recalculation, once with forced recalculation and once with the default profile:
  - Rates reordered and weights changed to 4 / 7 / 1.5 → 3,520 / 6,160 / 1,320 (total 11,000).
  - Costs rows added at row 7 (hidden) and row 1000 → pool 11,623.25 → 5,811.625 / 2,324.65 / 3,486.975.
  - Both changes together → 3,719.44 / 6,509.02 / 1,394.79.
- Confirmed that "002" and "02" resolve to Field Operations and Customer Support respectively in every case.
