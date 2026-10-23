# Release 2: retain unclassified accounts

Add the `outer` report specified in `/app/docs/contract.md` without regressing
`inner`. The business needs unclassified orders to remain visible while account
tags are investigated. Do not substitute application-specific NULL defaults
for the documented SQL query.

Upgrade and continue the existing incident database with
`python demo.py --through 2`; preserve its sources and receipts. Maintain the
same incremental-work, restart and transaction guarantees for both modes.
Extend your regression tests and update `/app/REPAIR_REPORT.md` with what you
checked, including previously released behavior.

