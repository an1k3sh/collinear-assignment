# Release 1: stop stale cohort corrections

Repair `/app/maintainer.py` for the existing `inner` report. Inspect
`/app/docs/contract.md`, the host and schema, smoke checks, and release-1 incident
history. Classifications and order corrections currently leave the board wrong.
This is an incremental service, not a periodic full-query exporter: the public
contract includes a machine-independent work bound.

Deliver working projection code, your own regression checks, the incident
database produced by `python demo.py --through 1`, and `/app/REPAIR_REPORT.md`
with diagnosis, design and actual validation commands. Preserve source records.

Three follow-up releases will add reports. Keep this implementation and database;
later releases must preserve existing report behavior.
