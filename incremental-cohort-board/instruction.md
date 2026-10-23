# Repair the incremental cohort board across four releases

You own the SQLite analytics projection in `/app`. The application is being
released in four consecutive steps. Files and databases persist between steps.
Keep previously released behavior working when later requirements arrive.

The runtime, reference SQL and update protocol are documented in
`/app/docs/contract.md`. Modify the projection implementation, not the trusted
runtime or source schema. Each release requires working code, a durable incident
replay database, and an updated engineering handover.

This is one task with four release milestones, not four independent tasks.
The last verifier rechecks all released behavior. Offline Python/SQLite tools
are sufficient; no outside service or model calls are part of the application.
