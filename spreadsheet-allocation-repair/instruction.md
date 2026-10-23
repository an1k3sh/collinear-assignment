# Repair the shared-services allocation workbook

The controller has withheld sign-off on the April allocation workbook. Audit
it against the supplied policy and evidence, repair any discrepancies, and
leave a workbook suitable for continued use.

Inspect `allocation.xlsx`, `POLICY.md`, and `incidents/controller-note.txt`.
Deliver a repaired, recalculated `submission/allocation.xlsx` and a short
`submission/REPAIR_REPORT.md`. Preserve source data and the editable chart.

The workbook must remain correct after Rates rows are reordered, weights change,
and cost rows are appended through row 1000. Do not replace formulas with fixed
answers. LibreOffice and openpyxl are installed; use actual recalculation to
validate saved values. The verifier checks formulas' behavior and chart data
bindings, not exact formula strings. No network is needed.
