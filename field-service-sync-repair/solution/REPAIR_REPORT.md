# Repair report

The receipt lookup now uses tenant/device/mutation and validates a canonical
digest before returning the original response. BEGIN IMMEDIATE precedes all
reads in the mutation transaction; neither chaos hook can leave a projection
or journal fragment behind. Receipts and after-images commit together.

Snapshot pages now query immutable history at a frozen cut, rather than current
projection state. Pull is exclusive, freezes until, validates cursor context
and advances across tenant sequence gaps. Wire counters are decimal strings.

The client compares integer strings without rounding, stages bootstrap pages,
buffers post-cut deliveries, and replaces rather than merges completed snapshots.
Only contiguous pull pages advance checkpoint. Authoritative base and optimistic
intents remain separate; acknowledgement removes only its own intent. Sends
freeze their wire request, conflicts require explicit resolution, tombstones
block ordinary pending edits, and delayed delivery cannot overwrite newer state.

The durable adapter uses temporary-write/rename and persists SEND before exchange.
An uncertain transport failure therefore leaves the original request retryable.

Projection repair independently reconstructs latest per-tenant/entity events
in one transaction. It does not rewrite receipts, journal or epoch.

Validation: `python3 tests/smoke.py`, `node --test tests/client-smoke.mjs`,
`python3 tests/regressions.py`, and the external integration verifier.
Limitations: this fixture has no compaction, authentication or schema migration.
