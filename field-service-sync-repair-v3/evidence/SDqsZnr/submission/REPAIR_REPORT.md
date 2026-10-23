# Repair report: offline work-order synchronization

Scope: the 2026-04-19 dispatch incident (`incidents/`), the v2.1 atomic closeout
paths and the v2.2 retention extension. `PROTOCOL.md` is the contract. The
interfaces and SQLite format did not change: no tables, columns or indexes were
added, and the journal mode was left alone.

## Root causes

### Server (`server/store.py`)

| Defect | Incident symptom |
|---|---|
| Receipt lookup used `(tenant, mutation)` and ignored the device. It also never compared the request digest. | Van 8 got van 7's receipt for the same local ID (09:18). A reused key could return an unrelated receipt. |
| Each write committed in three steps (document, then event, then receipt), with chaos hooks between them. | Fault injection left an uncommitted document visible (09:42). A lost response could leave an event that had no receipt, so the retry got a conflict instead of the original receipt (09:11). |
| Mutation took no write lock. It checked the revision and then wrote. | Two writes against one revision could both pass the check. |
| Receipts stored revision and seq as integers, not decimal strings. | Values above 2^53 lost precision in JS clients (09:04). |
| Snapshot pages joined the current `documents` projection, and every continuation re-read `cut = head`. | Pages of one snapshot disagreed. Deleted or new entities leaked into an open snapshot (09:27). Drifted projection rows were served as history. |
| Pull used `seq >= start`, so the boundary event was duplicated. Every continuation also chased the moving head instead of the frozen `until`. | Duplicate visits, and a catch-up that never reached a stable checkpoint. |
| `confirmed` was always `[]`. | Clients could not discover a commit whose HTTP receipt was lost. |
| `mutate_batch` called `mutate` once per operation, each in its own transaction. It had no batch receipt, no envelope validation and no `detail.index`. | A partial closeout: the valve conflicted but the pump still changed (closeout step 1). |
| `compact` rebuilt anchors from the current (drifted) `documents`. It deleted all anchors, ignored the boundary rules, committed between steps and did not validate `through`. | Tombstones and work orders disappeared from post-compaction snapshots (retention step 1). |
| No read or write path considered anchors. | After pruning, entities "did not exist", so revision checks were wrong. |
| No 410 `resnapshot_required` path existed. | Expired cursors were not reported. |
| Pull continuations did not check the scan start against the floor. | Retention step 3. |
| `repair_projection` only did `INSERT OR IGNORE` of events. It never fixed wrong rows, removed phantoms or used anchors, and its count included unchanged keys. | All four projection drifts in the archived database remained. |

### Client (`client/replica.mjs`, `client/durable.mjs`)

| Defect | Incident symptom |
|---|---|
| ACK removed every pending intent for the same entity ID. | The queued assignment edit disappeared after a delayed receipt (09:11). |
| PUSH and ACK set `checkpoint = record.seq`. | Reconnecting tablets skipped intervening events (09:36). |
| Partial snapshot pages were merged into `base` and set the checkpoint. Completion never removed stale entities. | A half-finished bootstrap removed or kept the wrong records (09:36). Deleted orders reappeared. |
| Pull did not process confirmations. Snapshots did not accumulate them. | A visit that committed without a receipt was re-applied optimistically (closeout steps 2 and 3, retention step 2). |
| Revisions and sequences were compared through `Number`. | Values above 2^53 compared as equal. |
| `SEND_BATCH` captured bases from the plain base without predicting revisions inside the batch. It also re-captured a new wire on every call. | Closeout step 4: the rebuilt batch omitted members. |
| `ACK_BATCH` cleared the whole pending queue without validating membership. | Later edits were lost. |
| `RECOVERY_REQUIRED` moved the checkpoint to the floor, dropped every sent intent and cleared the in-flight batch. | Retention step 4: the durable outbox was reset and a shorter retry batch was generated. |
| `save` overwrote the file in place, so the hook could not simulate a pre-rename crash. | A crash could corrupt the file. |
| `sendOnce` and `sendBatchOnce` did not persist the wire before the exchange. | Retries after a restart sent a different request (09:11). |

## Cross-layer effects

These defects combined into the observed failures:

- **Lost response.** A non-atomic server write plus a missing receipt caused a conflicting retry. Separately, entity-wide ACK removal on the client deleted the later edit.
- **Stable catch-up.** It needs three things: a frozen server `until`, an exclusive scan start, and a client that advances only on contiguous pages.
- **Confirmations.** Snapshot confirmations come from immutable receipts, not just events. A commit therefore stays discoverable after its event has been pruned or superseded.

## Repairs made

### Server

- **Atomic writes.** Every mutation, batch, compaction and repair runs in one `BEGIN IMMEDIATE` transaction on its own connection with a busy timeout. Writers serialize across processes. Any exception, including chaos-hook exceptions, rolls everything back and propagates.
- **Authoritative state.** It is "latest remaining event, else anchor" (`_current`). Snapshots reconstruct each entity at the frozen cut from anchors plus events ≤ cut. Continuations keep their frozen cut and last ID.
- **Pull.** Pull is exclusive (`seq > start`) and keeps its frozen `until`. The final page reports `after = until`. Expired positions return 410 `resnapshot_required` with `{epoch, floor}`. A continuation is checked by its own scan start.
- **Batches.** The batch receipt is checked first. Base checks see the transaction's own earlier operations. `batch_conflict` is raised for operations already committed independently. Errors carry `detail.index`, and failures roll back all operations.
- **Sequence allocation.** New sequences come from `max(sqlite_sequence, remaining events, floor) + 1`, so they never reuse a value after events are pruned.
- **Compaction.** It upserts anchors only from events ≤ `through` and keeps untouched anchors. It then prunes and advances retention in the same transaction, with the hooks `after_anchor` and `after_prune`.
- **Projection repair.** It rebuilds from anchors plus events, deletes phantom rows and counts only keys that changed.

### Client

- Comparisons use BigInt on decimal strings, and no BigInt is stored in state.
- Receipts and confirmations match on device, mutation and entity. A confirmation for an unsent intent, or for a different entity, is an explicit error.
- Snapshots are staged and complete in one step: the base is replaced at the cut, confirmations are reconciled, and pushes and ACKs after the cut are replayed.
- The batch wire stays immutable until the full `ACK_BATCH`. Members cannot be conflicted or resolved while the batch is in flight.
- Recovery mode blocks SEND, SEND_BATCH and PULL until a snapshot at or beyond the floor completes.
- `save` writes a temporary sibling, fsyncs it and renames it. The temporary file is removed on failure.
- The send helpers persist the wire before calling exchange, keep it after a transport error, and reload the file before applying the acknowledgement.
- The replica keeps a durable ledger (`state.retired`) of its own mutations that a receipt or confirmation proved committed. A delayed or duplicate ACK for one of those mutations is accepted safely. An ACK for an unknown mutation is rejected. A confirmed mutation ID cannot be queued again.
- PULL checks each page's shape. A final page must end at `until`, and a partial page must end at its last event, so a malformed page cannot move the checkpoint forward past unseen events. CONFLICT is rejected before the first snapshot.

### Other changes

- **Idempotency check order.** Mutations and batches look up their own receipt before validating operation values, so a changed retry of a committed key gets `idempotency_reuse`.
- **HTTP.** Strict `limit` parsing. A blank `cursor=` is `invalid_cursor`; before, it silently started a fresh read. NaN and Infinity are rejected. A non-object `/batch` body returns 400 instead of 500.
- **Tools.** `tools/compact.py` and `tools/repair.py` print JSON and exit nonzero with a diagnostic on failure.
- **Working database.** `python3 tools/repair.py --db state/site.sqlite` returned `{"repaired": 4}`, and a second run returned `{"repaired": 0}`. The four keys were:
  - `pump-17`: projection at revision 41, now 43.
  - `valve-4`: tombstone resurrected, now deleted again.
  - `south/pump-17`: missing, restored.
  - `phantom`: never committed, removed.

  Events, receipts, batches, retention, anchors, epoch (`dispatch-2026-04`) and `sqlite_sequence` were compared before and after, and are byte-identical.

## Validation

```
python3 tests/smoke.py                 # smoke + server regressions
node --test tests/client-smoke.mjs     # smoke + client regressions
node client/trace.mjs < incidents/client-actions.json
python3 tools/seed.py --db /tmp/x.sqlite && python3 tools/repair.py --db /tmp/x.sqlite
python3 tools/compact.py --db /tmp/x.sqlite --through 9007199254740996
```

The regression tests cover:

- Device-scoped idempotency and key-order-insensitive digests.
- Rollback at each fault point.
- Multi-process races (a single winner, and identical batch receipts).
- Unicode tenants, devices and IDs.
- Sequences above 2^53.
- Frozen snapshots under concurrent delete and create.
- Exclusive and frozen pull pages.
- Confirmations, including after pruning.
- Compaction boundaries, 410 paths and continuations across compaction.
- Repair after compaction.
- The HTTP surface.
- Every reducer action, including reordered and duplicate deliveries.
- Durable crash and retry paths.
- An end-to-end run of the JS replica against the real HTTP service. It covers a lost batch response, compaction, recovery and a full-wire retry.

## Limitations

- Snapshot confirmations parse receipt JSON (`json_extract`) for each page, so their cost grows with the tenant's receipt count. The database format had to stay the same, so no index was added.
- The rollback journal (the existing format) serializes writers against open readers. This is correct, but readers briefly block commits.
- Sorting is by Unicode code point on both server (SQLite BINARY / UTF-8) and client, so it can differ from JS UTF-16 default ordering for astral characters.
- Archived legacy receipts carry digests of `{"archived": mutation}`. Replaying one of those legacy requests therefore yields `idempotency_reuse`. They were left untouched because they are authoritative.
- The `state.retired` ledger grows with the number of acknowledged mutations. It is never pruned, because a delayed receipt can arrive at any time.
- A failed batch HTTP response is not translated into a client conflict state. As the contract requires, it propagates as an error.
