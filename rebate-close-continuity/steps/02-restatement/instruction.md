# Turn 2: April credit dispute

The March close has been approved and archived at
`output/archive/close-1.xlsx`. New ERP revisions and credit notes are now in
`inputs/source.xlsx`. Purchasing reports that one corrected invoice moved
supplier group, some March returns arrived in April, a cancelled event still
shows up in the first draft, and an older revision was appended late.

Restate through **2026-04-15**, compare with **close-1's entitlement**, and
deliver the updated workbook/report using your repaired CLI:

```
python refresh.py --source inputs/source.xlsx --as-of 2026-04-15 --previous output/archive/close-1.xlsx --output output/settlement.xlsx
```

These are data corrections, not new accounting rules. Follow the existing
policy, retain zero-current prior keys and all human notebook content, and do
not edit close-1. The new delivered workbook will become approved close-2.
