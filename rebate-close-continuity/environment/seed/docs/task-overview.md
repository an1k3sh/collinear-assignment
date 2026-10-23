# Supplier rebate close continuity

This is one task delivered as five sequential user requests against the same
workspace. Complete the current request; later requests bring new business data.
The deliverable is an executable, repeatable spreadsheet refresh plus a real
Excel workbook, not an explanation of what someone else should do.

You maintain the quarterly supplier-rebate settlement for a medical distributor.
The ERP sends append-only event revisions; credits arrive after quarter end;
vendor aliases change when suppliers reorganize. Wrong settlements either lose
earned rebates or overstate receivables.

Read `/workspace/docs/settlement-policy.md` and
`/workspace/docs/workbook-contract.md`, inspect every source sheet and the
starter `/workspace/refresh.py`, then repair the workflow. No external data or
services are needed. Python, openpyxl and headless LibreOffice are installed.
Use `soffice` when you need genuine recalculation; openpyxl alone does not
evaluate formulas.

All turns require:

* A working `/workspace/refresh.py` with the documented CLI. It must handle
  additional valid source rows, prices, revisions, eligibility flags, alias
  intervals and contract thresholds, not just today's records.
* `/workspace/output/settlement.xlsx`, preserving the source sheets and notebook,
  with auditable event detail, live summary formulas and a linked adjustment chart.
* `/workspace/output/reconciliation.json` as specified in the workbook contract.
* Do not modify `inputs/`, `docs/` or `output/archive/`. Prior approved closes
  must not be rewritten. Repeated refreshes must be economically idempotent.

The final two requests add a constrained supplier-claim batch and a replan after
actual remittances. Their business policy and inputs arrive with turn 4. A
recommended claim is not itself a payment. Preserve that distinction and the
approved workbook history throughout the handoff.

The verifier checks workbook outcomes, recalculates formulas independently,
checks the old closes, and runs your CLI against valid input variations. It
does not require any particular implementation or formula spelling.
