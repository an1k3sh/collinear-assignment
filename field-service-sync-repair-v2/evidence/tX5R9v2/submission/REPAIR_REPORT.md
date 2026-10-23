# Repair report: offline work-order synchronization

Scope: server (`server/`), client replica and durable adapter (`client/`), the
projection-repair tool (`tools/repair.py`), the working database
`state/site.sqlite`, and regression tests. Public interfaces and the SQLite
format (tables, columns, keys, the existing index) are unchanged. No schema
objects, journal mode or dependencies were added.

## Root causes and cross-layer effects

| # | Incident symptom | Root cause | Layer |
|---|---|---|---|
| 1 | Retry after lost response conflicted instead of returning the receipt; a van got another device's receipt (09:11, 09:18) | Receipt lookup used `(tenant, mutation)` and ignored `device`; the stored digest was never compared, so key reuse with a different request returned the old receipt too | server `mutate` |
| 2 | Uncommitted work order visible after fault injection (09:42) | `mutate` committed the document, then the event, then the receipt as three transactions; the chaos hook ran between commits | server `mutate` |
| 3 | Two writes against one revision could both pass | Deferred `BEGIN` read-then-write race across processes | server `mutate` |
| 4 | Desktop and handheld disagreed about deliveries after the sequence migration (09:04) | Server put integer `revision`/`seq`/`cut` on the wire; the client compared via `Number()`, which collapses values above 2^53 (`…993` == `…992`) | server wire + client |
| 5 | Snapshot pages disagreed; deleted valve and new urgent order leaked into an open snapshot (09:27) | Continuation pages re-read the *current* head as the cut, and rows came from a JOIN with the *current projection*, so tombstones/updated entities fell out or changed between pages | server `snapshot` |
| 6 | Duplicate boundary events; catch-up never stabilised | Pull used `seq >= start` (re-sending the boundary event) and recomputed `until` from the moving head on every page | server `pull` |
| 7 | Tablets skipped intervening work orders after a push (09:36) | Client `PUSH`/`ACK`/`CONFLICT` set `checkpoint = record.seq`, so the next pull started after events never received | client `receive` |
| 8 | Restarting a bootstrap removed rows not on the latest page (09:36) | Every snapshot page was merged into `base` and advanced the checkpoint before completion; stale entities were never removed on completion | client `SNAPSHOT` |
| 9 | Delayed receipt erased the unsent assignment edit (09:11) | `ACK` removed *every* pending intent for the entity (`p.id !== record.id`) instead of the acknowledged mutation | client `ACK` |
| 10 | Deleted work orders reappeared | `selectView` let a pending patch/visit apply to a tombstone and clear `deleted` | client view |
| 11 | Restart resent a different request / lost the wire | `sendOnce` persisted only after the network call and `save` wrote the target file in place (no temp + rename) | client durable |
| 12 | Partial closeout: valve conflicted but pump changed | `mutate_batch` called `mutate` per operation, each committing independently; no batch receipt, no `detail.index`, no `batch_conflict` | server batch |
| 13 | Lost batch receipt: later pull/snapshot could not retire committed intents; doubled optimistic visit | Pages always returned `confirmed: []`; client ignored confirmations | server pages + client |
| 14 | Rebuilt batch omitted confirmed intents and failed idempotency | `SEND_BATCH` rebuilt the envelope from the current queue; `ACK_BATCH` cleared the whole queue; bases ignored earlier operations in the batch | client batch |
| 15 | Four projection discrepancies persisted | `repair_projection` used `INSERT OR IGNORE`: it never fixed wrong rows or removed phantom rows, and its count was not what it did | server repair |

Cross-layer interactions: (4) made the client treat distinct server records as
equal-revision conflicts or ignore newer ones; (5)+(8) together meant a
half-finished bootstrap could expose a base no cut ever contained; (7) hid (6)
and the gaps it produced; (1)+(9)+(13) produced both doubled visits and lost
edits after a lost response; projection drift (2, 15) was visible to clients
only because snapshots read the projection (5).

## Repairs

### Server (`server/store.py`, `server/codec.py`, `server/http.py`)
* Every write is one `BEGIN IMMEDIATE` transaction on its own connection with a
  busy timeout (autocommit mode, explicit `COMMIT`/`ROLLBACK`). Document, event
  and receipt are written together; fault hooks run inside the transaction and
  any exception rolls everything back and propagates.
* Current state is read from the latest immutable event, not the projection.
* Idempotency key is `(tenant, device, mutation)`; the canonical request digest
  is compared — same request returns the stored original response, a different
  one returns 409 `idempotency_reuse`.
* All wire integers (`revision`, `seq`, `cut`, `from`, `after`, `until`) are
  canonical decimal strings. Visit amounts and totals are capped at 2^53-1.
  Lone surrogates and NaN/Infinity are rejected as 400 `invalid`.
* `snapshot` freezes `cut` in the token, returns each entity's latest event at
  or before the cut from `events` (tombstones included), keyset-paged by id, and
  validates mode/tenant/epoch/cut/last. `pull` uses an exclusive `seq > from`,
  keeps the original `until` in the token, validates origin/after/until, and
  ends with `after = until`.
* Both page kinds now return `confirmed` (`{device,mutation,id,seq}` ordered by
  seq): pull = exactly its events; snapshot = all events at/before the cut for
  the page's entity IDs.
* `mutate_batch` validates the envelope, checks its own receipt first (exact
  retry / `idempotency_reuse`), then `batch_conflict` for operation keys already
  committed elsewhere, then applies operations in one transaction against
  transaction-local state. Failures carry `detail.index` and roll back all.
* `repair_projection` deletes projection-only rows, inserts missing rows and
  rewrites rows whose revision/body/deleted differ from the last event per
  tenant/id, in one transaction, returning the number of changed entity keys.
* HTTP: one `Store` per server, strict limit/query parsing, UTF-8 JSON, blank
  cursor → `invalid_cursor`, unexpected exceptions logged and reported as 500.

### Client (`client/replica.mjs`, `client/durable.mjs`, `client/trace.mjs`)
* Decimal strings are validated and compared with BigInt locally; state stays
  plain JSON.
* `PUSH`/`ACK`/`CONFLICT` merge by revision and never move the checkpoint.
  Other epochs require a snapshot. During staging they are buffered.
* `SNAPSHOT` stages rows and confirmations without touching `base`; identical
  page retries are accepted, mixed rows/cuts rejected, backward cuts rejected
  (including replays of an already completed snapshot older than the checkpoint).
  Completion atomically replaces `base`, reconciles confirmations, replays
  records newer than the cut, and preserves unrelated pending intents.
* `PULL` requires `from == checkpoint`, accepts already-consumed pages as no-ops,
  merges events and applies confirmations in one transition. A continuation page
  must end at its last event and a final page at `until`, so the checkpoint
  cannot jump over events that were not delivered.
* Confirmations match device + mutation + entity; mismatched entity or an
  unsent intent is an explicit error; other devices are ignored. Pull
  confirmations must correspond one-to-one with the page's events, and snapshot
  confirmations must name entities in that page's rows. Otherwise a fabricated
  confirmation could retire durable work.
* `ACK` removes only the matching mutation; `SEND` freezes the wire once.
* `SEND_BATCH` freezes an immutable envelope with bases predicted from the
  authoritative base plus earlier selected operations; it is idempotent for
  the same batch/count. `ACK_BATCH` validates membership and order, and
  removes only acknowledged intents. Accepted receipts are kept per batch ID
  (`state.acceptedBatches`). A delayed duplicate `ACK_BATCH` is therefore a
  no-op even after later batches, a different receipt for that ID is rejected,
  and acknowledged batch IDs cannot be reused. CONFLICT/RESOLVE on batch members are rejected.
* `selectView`: ordinary edits on tombstones/missing entities are conflicts;
  only `restore` revives. Sorting uses code-point order to match SQLite.
* `save` writes and fsyncs a unique temporary sibling, calls the hook, renames,
  and removes the temp file on failure. `sendOnce`/`sendBatchOnce` persist the
  wire before `exchange`, keep it after transport errors, and persist the ACK.

### Data repair (`state/site.sqlite`)
`python3 tools/repair.py --db state/site.sqlite` → `{"repaired": 4}`, then
`{"repaired": 0}` on a second run:
* `north/pump-17`: revision 41 → 43, body restored (assignee null, done true).
* `north/valve-4`: `deleted` 0 → 1 (tombstone, body preserved).
* `south/pump-17`: missing row restored from event at seq 9007199254740998.
* `north/phantom`: projection-only row with no event removed.

`metadata`, `events`, `receipts`, `batches` and `sqlite_sequence` were compared
before and after and are identical; epoch remains `dispatch-2026-04`.
`PRAGMA integrity_check` is `ok`.

An independent review against `PROTOCOL.md` found five more edge cases. All
are fixed and covered by tests: pull boundary checks, strict confirmation
matching, per-batch receipt history, backward-cut checks before duplicate
detection, and lone-surrogate snapshot cursors now return `invalid_cursor`
instead of 500.

## Validation

```
python3 tests/smoke.py                 # 25 tests: server, batch, pages, repair, HTTP
node --test tests/client-smoke.mjs     # 18 tests: reducer, durable, end-to-end over HTTP
node client/trace.mjs < incidents/client-actions.json
python3 tools/seed.py --db /tmp/copy.sqlite && python3 tools/repair.py --db /tmp/copy.sqlite
```

The new tests fail against the original code (21 of 25 server, 16 of 18
client) and pass after the fix. They cover multi-process races (single winner
and identical concurrent batches), fault-hook rollback at both points, Unicode
IDs and bodies, sequence values above 2^53, frozen snapshot cuts under
concurrent writes, contiguous pull pages, lost single and batch responses with
restart, a pull page boundary inside a committed closeout, and snapshot
confirmation of a superseded visit. A separate 8-process stress run (snapshot,
mutate and paged pull in a loop) produced contiguous revisions with no lost
updates or lock errors.

## Limitations and notes
* `selectView` and the server sort ids by Unicode code point (SQLite BINARY on
  UTF-8). This differs from JavaScript's default UTF-16 sort only for astral
  characters compared with U+E000–U+FFFF.
* The client does not keep a ledger of confirmed single-mutation IDs. The
  protocol says they are not reused. Accepted batch receipts are retained in
  `state.acceptedBatches`, which grows by one entry for each acknowledged batch.
* `sendOnce` applies `ACK` to whatever `exchange` returns. A 409 body is
  therefore reported as an error, and the wire is kept. The caller must
  dispatch `CONFLICT` itself, as the documented flow requires.
* A legacy page with no `confirmed` field is treated as an empty list, so
  it cannot retire intents. Those intents stay pending until an ACK or a
  confirming page arrives.
* `tools/repair.py` refuses a missing path rather than creating a new database.
