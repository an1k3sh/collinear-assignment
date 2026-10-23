# Repair report: offline work-order synchronization

Scope: server store/HTTP adapter, client reducer/durable adapter, maintenance
tools, the working database `state/site.sqlite`, and regression tests. The
database schema/format, events, receipts, batch receipts, epoch and sequence
allocation are unchanged. `PROTOCOL.md`, `incidents/` and `tools/seed.py` were
not modified.

## Root causes

### Server (`server/store.py`)
| Defect | Incident effect |
|---|---|
| Write steps were committed separately (`commit()` after document, after event, after receipt), so a fault hook left a half-applied write. | Phantom "uncommitted" work order visible after a failed request (09:42); projection drift. |
| Plain `BEGIN` (deferred) for writes; check-then-write raced across processes. | Two writes against one revision could both succeed. |
| Receipt lookup ignored `device` and never compared the request digest. | Van 8 received van 7's receipt for the same local ID (09:18); key reuse returned stale success instead of `409 idempotency_reuse`. |
| Revision/seq emitted as JSON integers. | Precision loss beyond 2^53 after the sequence migration (09:04): desktop vs handheld views disagreed. |
| Snapshot read the *current* projection joined to events and re-read the head on every page; continuation ignored the token's cut. | Pages of one snapshot disagreed; deletes/new orders leaked into an open snapshot (09:27). |
| Pull scanned `seq >= start` and re-read `until` from the live head. | Boundary events duplicated, a moving `until` was chased. |
| Confirmations were always `[]`. | Lost receipts could never be discovered by catch-up; optimistic visits doubled. |
| `mutate_batch` called `mutate` per operation (separate transactions, no batch receipt, no envelope validation). | Partial closeouts: valve conflicted but pump still changed. |
| `compact` built anchors from *current documents*, committed between steps, set retention outside the transaction, and ignored bounds. | Drifted projection leaked into the retained baseline; faults left partial state. |
| Reads/mutations ignored anchors and retention. | After a full prune snapshots were empty, tombstones "reappeared", no 410. |
| `repair_projection` used `INSERT OR IGNORE`, so it never fixed wrong rows nor removed phantoms, and ignored anchors. | Drift persisted while reporting it as repaired. |

### Client (`client/replica.mjs`, `client/durable.mjs`)
| Defect | Incident effect |
|---|---|
| ACK removed every pending intent for the same *entity*. | Delayed receipt erased the unsent assignment edit (09:11). |
| PUSH/ACK/CONFLICT advanced the checkpoint. | Cursor jumped past undelivered events (09:36). |
| Partial snapshot pages merged into base and moved the checkpoint; completion never dropped stale entities. | Bootstrap restart briefly removed/kept the wrong records; deleted orders reappeared. |
| `Number()` comparisons of decimal strings. | Wrong ordering beyond 2^53. |
| SEND recaptured the wire each time. | Restart/retry sent a different request → conflict instead of the original receipt. |
| `sendOnce` persisted only after the exchange; `save` wrote in place (no temp/rename). | Lost response + restart lost or changed the outbox. |
| SEND_BATCH ignored validation and in-flight state; bases ignored earlier batch members; ACK_BATCH cleared the whole queue. | Shorter rebuilt batch failed idempotency; later edits vanished. |
| No confirmation handling; RECOVERY_REQUIRED dropped all sent intents, the batch, and moved the checkpoint to the floor. | Double visits after re-bootstrap; outbox reset during recovery. |
| `selectView` let ordinary edits revive deleted entities. | Deleted work orders reappeared locally. |

### Tools / HTTP
`tools/repair.py` and `tools/compact.py` silently created a new database for a
wrong path and had no failure diagnostics/exit code. HTTP accepted `NaN`,
duplicate JSON members, signed/blank limits.

## Cross-layer effects
* Integer wire values (server) × `Number()` comparisons (client) produced
  divergent views only after the sequence migration crossed 2^53.
* Missing confirmations (server) × entity-based ACK removal (client) turned one
  lost HTTP response into either a doubled visit or a lost unsent edit.
* Projection-based snapshots (server) × partial-page application (client)
  made stale/phantom rows visible and let tombstones be resurrected.
* Document-based anchors (compaction) would have frozen projection drift into
  the authoritative baseline; now anchors derive only from events/anchors.

## Repairs made
* **Store**: every write (mutate, batch, compact, repair) runs in one
  `BEGIN IMMEDIATE` transaction on its own connection with a busy timeout;
  fault hooks run inside it and any exception rolls back. Authoritative state
  = latest of anchors ∪ remaining events (never documents). Receipts keyed by
  `(tenant,device,mutation)` with canonical digests. Wire values are decimal
  strings. Snapshots reconstruct state at a frozen cut (anchors + events ≤ cut)
  and carry historical confirmations from immutable receipts (plus remaining
  events), so they survive pruning. Pulls use exclusive scans and frozen
  `until`; continuation tokens are validated (400 `invalid_cursor`) before the
  retention check (410 `resnapshot_required` with `{epoch,floor}`).
  `mutate_batch` validates the envelope, checks its own receipt first, reports
  `batch_conflict`/errors with `detail.index`, and commits atomically.
  `compact` validates `floor ≤ through ≤ head`, upserts anchors from events
  only, prunes, advances retention; AUTOINCREMENT state is untouched and a
  guard rejects any allocation at/below the floor.
* **Projection repair**: rebuilds documents from anchors + events; inserts
  missing, rewrites wrong, deletes projection-only rows; counts changed keys;
  idempotent and transactional.
* **Client reducer**: rewritten to the contract — decimal-string comparisons
  (BigInt only transiently), immutable wires, mutation-scoped ACK, staged
  snapshots with atomic completion/replay/confirmation reconciliation,
  contiguous pulls with confirmations, batch capture/ack, recovery mode.
* **Durable adapter**: fsynced temp sibling + rename with cleanup; wire saved
  before exchange; errors propagate; ACK applied to freshly loaded state.
* **Tools**: shared CLI wrapper; nonexistent DB is an error; JSON result on
  stdout, diagnostic on stderr, nonzero exit on failure.
* **Working database**: `python3 tools/repair.py --db state/site.sqlite`
  returned `{"repaired": 4}` (north/pump-17 stale revision 41→43, north/valve-4
  tombstone restored, south/pump-17 restored, north/phantom removed); a second
  run returns `{"repaired": 0}`. Metadata, events, receipts, batches,
  retention, anchors and `sqlite_sequence` were verified identical to the
  pre-repair copy; `PRAGMA integrity_check` is `ok`.

## Validation
```
python3 tests/smoke.py                       # 27 server/HTTP/tool tests
node --test tests/client-smoke.mjs           # 15 client + end-to-end tests
node client/trace.mjs < incidents/client-actions.json
python3 tools/seed.py --db /tmp/x.sqlite && python3 tools/repair.py --db /tmp/x.sqlite
```
Regression coverage: values beyond 2^53, idempotent retries after newer
writes, per-device keys, key reuse, conflicts/tombstones/restore, validation,
Unicode, fault-hook rollback (mutation, batch, compaction), multi-process
races on one revision and on one batch, frozen snapshots with concurrent
deletes/inserts, confirmations, exclusive/frozen pull pages, cursor errors,
full and partial compaction, 410s and serviceable continuations, repair after
compaction, CLI behaviour, HTTP routes, reducer purity, ACK/CONFLICT/RESOLVE,
staged snapshots, batch capture/partial confirmation/ACK_BATCH, recovery mode,
atomic durable save, and an end-to-end lost-response/compaction/recovery run
against the real HTTP server.

## Limitations and judgement calls
* While bootstrapping a *different* epoch, ACK/ACK_BATCH/CONFLICT records are
  rejected explicitly: they answer requests sent under the old epoch and
  cannot be attributed to the new history. The durable wire is retained and
  can be retried after the new snapshot completes.
* Continuation tokens are checked against history (snapshot `last` must exist
  at the cut; pull `after` must be a returned tenant event, or the floor).
* Accepted batch receipts are remembered per batch ID so delayed duplicates
  stay idempotent even while a later batch is in flight.
* SEND/SEND_BATCH are rejected while a snapshot is being staged (only QUEUE,
  PUSH, ACK, ACK_BATCH and snapshot pages are accepted then).
* A same-epoch page identical to one from the last completed snapshot is a
  no-op retry (not while recovery is required).
* `sendOnce`/`sendBatchOnce` treat any non-success response as an error
  (no automatic CONFLICT handling), per the contract's error-propagation rule.
* A pending `create` whose own after-image arrives by PUSH before its ACK is
  shown as a conflict until the ACK or a confirmation retires it.
* Legacy archive receipts carry a placeholder digest, so a client retry of those
  historical mutations yields `idempotency_reuse`; history is not rewritten.
* SQLite stays in rollback-journal mode (no WAL) to avoid changing the file
  format; long readers can delay writers up to the 30 s busy timeout.
