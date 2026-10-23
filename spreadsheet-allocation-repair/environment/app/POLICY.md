# April shared-services allocation

Repair `allocation.xlsx` and deliver it as `submission/allocation.xlsx`.
Workbook calculation, not cached values or pasted answers, is the deliverable.

Input sheets:
* Rates: department ID (text, leading zeros significant), display name, positive
  allocation weight. Row order has no meaning.
* Costs: transaction ID, posting date, amount in dollars. All supplied rows
  belong to April and all count, including rows excluded by a saved filter.
* Summary: department IDs in column A, name in B, weight in C, allocation in D.
  Row 6 is the total. Keep this layout for downstream consumers.

Allocate the total Costs amount pro rata to the exact department's weight.
Do not round the underlying allocations; currency display may show two decimals.
Department allocations must sum to the pool, and their individual amounts must
match their own weights. Rates are positive and unique by exact text ID.
The initial three departments are fixed, but cost rows may be appended through
row 1000. Costs headers are in row 1; data starts in row 2.

Preserve all source values, their types, sheet names, the four departmental
Summary row positions (three departments plus total), and the workbook's chart.
You may change formulas, calculation settings, chart bindings, input formatting,
table/filter ranges, and add helper sheets. No macros or external links.
Summary B2:D4 must remain formulas: they must react to reordered Rates rows,
changed weights and appended Costs. D6 is a formula total. Do not hide errors
with a blanket IFERROR that substitutes a valid-looking number.

The Summary chart must show the three CURRENT department allocations from
Summary D2:D4 with labels from B2:B4, not the hidden Legacy sheet and not total
row 6. Preserve it as a normal editable spreadsheet chart.

Set automatic calculation and refresh the saved results using the installed
LibreOffice. The verifier recalculates copies through LibreOffice, perturbs
source rows and checks actual results. It accepts different equivalent formulas.

Deliver `submission/REPAIR_REPORT.md` with defects, repairs and checks performed.
The historical Legacy sheet is evidence: retain its values.
