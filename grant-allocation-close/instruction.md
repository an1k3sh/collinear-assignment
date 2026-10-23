# Complete the grant allocation close

The controller has withheld release of `/app/grants.xlsx`. Audit and repair the
workbook against `/app/POLICY.md` and the handover in `/app/evidence`.

Deliver `/app/submission/grants.xlsx` and a concise
`/app/submission/REPAIR_REPORT.md` describing the corrections and checks.
The workbook must remain formula-driven: the controller needs to edit the
documented input cells and receive a correct recalculated close without
running your code.

Preserve the source records, input values and source sheet names. You may
replace derived formulas, add helper columns/sheets and repair the chart.
Save correct cached results, leave calculation automatic, and retain an
editable chart of the repaired award amounts. Do not change `/app/grants.xlsx`,
`/app/POLICY.md` or the handover evidence.

LibreOffice Calc and openpyxl are installed. Use actual spreadsheet
recalculation to validate the delivered workbook. There is no requirement to
use a particular formula spelling or implementation.
