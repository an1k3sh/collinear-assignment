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

Atomic closeouts share a single connection and write transaction across all
operations. Their independently scoped receipt is checked before operation
receipts, so retries are stable without accepting previously independent writes
as an atomic batch. Rejection and injected faults roll back the entire closeout.

Catch-up confirmations derive from the frozen journal, not current projection
rows. The client retires only its own sent intents, at the same transition as
the authoritative state becomes visible. Snapshot confirmations are staged.
Batch wires survive partial confirmation and restart; per-entity predicted
revisions use exact integer arithmetic. The durable batch adapter saves before
exchange and validates complete membership before accepting the response.

Compaction builds a retained baseline from historical anchors/events inside a
single write transaction, not from the potentially drifted current projection.
Reads, mutation conflicts and repair share that authoritative history. Event
head includes the retention floor and AUTOINCREMENT allocation is untouched.
Expired cursors fail explicitly; serviceable pull continuations are checked
against their actual scan position, not their original already-consumed prefix.

Historical confirmations now come from durable ordinary receipts so pruning
cannot make a committed optimistic operation look unsent. Recovery mode keeps
all immutable wires and blocks sending until atomic bootstrap completion.
The full closeout wire remains retryable after its members are confirmed.

Validation: `python3 tests/smoke.py`, `node --test tests/client-smoke.mjs`,
`python3 tests/regressions.py`, and the external integration verifier.
Limitations: this fixture has no compaction, authentication or schema migration.
