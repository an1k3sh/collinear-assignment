# Release 4: distinct households under reversible identity resolution

Add the `household` report defined in `/app/docs/contract.md`. Confirmed alias
links can join accounts through dormant identities, and corrected links can
split an old household. The new report counts distinct equivalence classes
within each existing rated group. It must not deduplicate joined amount rows
or change any of the three older reports.

Aliases and orders/classifications/rates may be corrected in the same batch.
Preserve exact transactional, restart and small-neighborhood work guarantees,
including on a busy group shared by many unrelated accounts.

Continue the existing incident database with `python demo.py --through 4`.
Deliver working code and persistent auxiliary state, extend regression checks
for reversible identity changes, and update `/app/REPAIR_REPORT.md`.
The final verifier rechecks all four releases.

