# Turn 1: March provisional close

Read `/workspace/docs/task-overview.md` and the other `/workspace/docs/` files. Inspect
`inputs/source.xlsx` and repair `refresh.py`. Prepare the March 31 provisional
rebate close, with no previous approved workbook:

```
python refresh.py --source inputs/source.xlsx --as-of 2026-03-31 --output output/settlement.xlsx
```

Deliver the workbook, linked adjustment chart and reconciliation report required
by the contract. Verify the formulas and event selection, not only grand totals.
This becomes approved close-1 before your next request; the workflow must remain
usable when new revisions and credits arrive. Do not change input data.
