# Turn 4: Constrained cash-recovery batch

June's workbook is approved and frozen as `output/archive/close-3.xlsx`.
Do not rewrite any approved close. The June settlement remains the current
financial workbook; its journal still compares to close-2, not to itself.

Finance has more claim packets than the collections desk can review this week.
Read the NEW `/workspace/docs/claim-planning.md` and inspect ALL sheets of
`inputs/claims.xlsx`. Build `/workspace/plan.py` to select an optimal indivisible
claim batch against June's entitlements and confirmed cash receipts, respecting
review capacity, rail limits, supplier minimum batches, evidence alternatives
and same-batch prerequisites.

```
python plan.py --settlement output/settlement.xlsx --claims inputs/claims.xlsx \
  --as-of 2026-06-30 --output output/claim-plan.xlsx
```

Deliver the required claim-plan workbook and `plan.json`. The objective is
lexicographic, not a weighted sum or a greedy approximation. Any feasible plan
with the optimal objective vector is acceptable. SciPy is installed; you may
use an integer optimizer or another exact method. This plan will be approved
and archived before the next request. Your financial refresh CLI must continue
to work as previously specified.
