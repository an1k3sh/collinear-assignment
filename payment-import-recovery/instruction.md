# Recover the payment import

Finance has withheld sign-off on the latest payment import. Investigate the
provided application, records and operational evidence, and bring the importer
and working database into compliance with the documented contract.

Inspect `CONTRACT.md`, `incidents/`, `data/`, and `import_payments.py`. Repair the
existing importer; then import `data/payments.csv` into `state/payments.sqlite`
and write `submission/import-report.json`. Preserve the database's existing
valid payment and receipt. Add regression tests and `submission/REPAIR_REPORT.md`.

Keep the documented CLI, SQLite tables and `apply_payment` interface. Do not
modify input exports, incident evidence, CONTRACT.md, seed script or verifier.
The repaired implementation must satisfy the contract for other valid inputs
and operating conditions, not just this export. No network or third-party
packages are needed.
