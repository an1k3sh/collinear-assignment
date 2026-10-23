# Turn 3: June roll-forward and audit handoff

April's restatement is archived at `output/archive/close-2.xlsx`; close-1 is
still immutable. The source now includes Q2 purchases, more Q1 returns,
revised purchases, supplier reorganizations effective April 1, and Q2 contract
tiers. Refresh through **2026-06-30**, comparing ALL current group/quarters to
**close-2's entitlement**:

```
python refresh.py --source inputs/source.xlsx --as-of 2026-06-30 --previous output/archive/close-2.xlsx --output output/settlement.xlsx
```

Finance needs a repeatable handoff, not a one-off patch: test a repeated run,
check original-invoice attribution across quarters, exact tier boundaries,
per-event rounding and chart coverage. Your CLI will also be checked against
valid changes to prices, quantities, new/revised events, eligibility, aliases
and tier thresholds. Preserve both approved closes and the notebook.
