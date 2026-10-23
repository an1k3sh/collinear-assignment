# Repair offline work-order synchronization

Field crews use this work-order application without a reliable connection.
The latest incident involved duplicate visits, disappearing offline edits,
deleted work orders reappearing, and a catch-up that never reached a stable
checkpoint. The application starts and the smoke tests pass; this is not a
request for a replacement application.

Repair the existing repository under `/app`. Read:

* `PROTOCOL.md`: authoritative compatibility and state-transition contract.
* `incidents/`: original packet/action traces and the incident chronology.
* `server/`: Python/SQLite service, wire codec and HTTP adapter.
* `client/`: JavaScript replica, durable file adapter and trace runner.
* `tools/`: reproducible incident seed and projection-repair entrypoint.
* `tests/`: public smoke tests; extend these with meaningful regressions.

Deliver:

1. A code patch preserving the documented interfaces and database format.
2. A repaired `/app/state/site.sqlite`. Recover its materialized work-order
   projection from the immutable event history without changing events,
   successful receipts or the database epoch.
3. A reusable repair command, `python3 tools/repair.py --db PATH`, that repairs
   another database with the same kind of projection drift, transactionally.
4. Regression tests and `REPAIR_REPORT.md`: root causes, cross-layer effects,
   repairs made, validation commands and any limitations.

No network services, external data or packages are needed. Python 3 and Node 22
are installed. Use their standard libraries. You may edit implementation files,
add helper modules and tests, and change the working state database. Do not
modify this prompt, PROTOCOL.md, incident evidence, the seed script, or verifier/
oracle files. Do not suppress errors, skip work, replace persistence with an
in-memory fake, hardcode incident IDs, or special-case the verifier.

Run `python3 tests/smoke.py` and `node --test tests/client-smoke.mjs`.
The verifier exercises fresh databases, restarts, concurrent writers, alternate
IDs, Unicode payloads, sequence values beyond JavaScript's safe integer range,
and legal reordering/retry of the documented messages. A fix for one recorded
trace alone is insufficient. No deliberately tiny time limit or performance
ranking is used.
