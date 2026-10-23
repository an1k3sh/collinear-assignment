# Northstar finance engagement

This is a Harbor **multi-step** task, not a combined-prompt task. The root
instruction is an author-facing index; Harbor sends the six
`steps/*/instruction.md` files sequentially. Later requests are withheld until
the preceding step's agent run and verification finish. Use
`--resume-trajectory` to retain the native conversation as well as the workbook.

The six milestones are growth forecast, cohort-method revision, liquidity
continuation, treasury-reconciliation detour, renewal-pricing revision, and
reconciled opening-balance cutover. Each step specifies its own public acceptance
criteria; do not give this index to the candidate as an extra instruction.
