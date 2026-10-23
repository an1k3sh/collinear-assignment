# Turn 5: Payments are not recommendations

The first claim recommendation is archived at
`output/archive/claim-plan-1.xlsx`. Do not change it or closes 1, 2, 3.
Its report and exact financial input were also archived beside it for audit.
Bank evidence and vendor responses now disagree with parts of that recommendation:
some packets were paid, some blocked, one receipt reversed, and new alternatives
arrived. `inputs/source.xlsx` also contains July corrections to earlier invoices.

First refresh the financial workbook through July 15 against the approved
JUNE entitlement, NOT against the original March close or a proposed claim batch:

```
python refresh.py --source inputs/source.xlsx --as-of 2026-07-15 \
  --previous output/archive/close-3.xlsx --output output/settlement.xlsx
```

Then re-optimize using the latest claims/receipts, retaining the same documented
objective and constraints:

```
python plan.py --settlement output/settlement.xlsx --claims inputs/claims.xlsx \
  --as-of 2026-07-15 --prior-plan output/archive/claim-plan-1.xlsx \
  --output output/claim-plan.xlsx
```

Read `docs/claim-planning.md` again if needed. The old plan is an audit baseline,
not a paid ledger: OPEN claims may be reconsidered even if previously selected;
PAID/BLOCKED claims are unavailable even if previously recommended; only latest
CONFIRMED Paid receipts reduce capacity. Do not silently drop the original
rebate workbook or its live formulas/chart while adding the planning workflow.
Both CLIs will be rerun on additional valid source, claim and receipt revisions,
changed capacities, changed supplier constraints and new candidate packets.
