# Repair report: offline work-order synchronization

Scope: the existing application in `/app` was repaired against `PROTOCOL.md`
(v2 and v2.1). All public interfaces, the HTTP surface and the SQLite schema are
unchanged. No dependencies were added.

## Root causes and cross-layer effects

| # | Layer | Defect | Incident symptom |
|---|-------|--------|------------------|
| 1 | server `mutate` | The receipt lookup ignored `device` and never compared the request digest. | Van 8's `m-9` got van 7's receipt (09:18), and a reused key silently returned a stale receipt instead of 409 `idempotency_reuse`. |
| 2 | server `mutate` | Document, event and receipt were committed in three separate transactions, and the chaos hook ran *after* each commit. | Fault after the projection write left an uncommitted ("phantom") work order visible (09:42). A lost receipt (event committed, receipt not) made a retry *conflict* instead of replaying (09:11), which caused duplicate visits. |
| 3 | server `mutate` | A deferred `BEGIN` plus a read-then-write without a reserved lock. | Concurrent writers could race; the fix serializes with `BEGIN IMMEDIATE`. |
| 4 | server wire codec | Revisions and seqs were emitted as JSON numbers. | JS clients lost precision past 2^53 after the 09:04 sequence migration, so desktop and handheld disagreed. |
| 5 | server `snapshot` | Continuation pages re-read `cut` from the live head, and rows came from the *current projection* joined to events. | Pages disagreed (09:27). The deleted valve and a new urgent order leaked into an open snapshot, and drifted projection rows were served as history. |
| 6 | server `pull` | Scan used `seq >= from` (duplicating boundary events), and continuations chased a moving `until` taken from the head. | Duplicate and unstable catch-up that never reached a stable checkpoint. |
| 7 | server `repair_projection` | Only `INSERT OR IGNORE`: wrong rows, revisions and flags were never fixed, and phantom rows never removed. | The archived DB kept four discrepancies (stale pump-17, revived valve-4, missing south/pump-17, phantom). |
| 8 | server `mutate_batch` | A loop of independent `mutate` calls: no validation, no batch receipt, no atomicity. | Closeout incident step 1: the valve conflicted but the pump still changed. |
| 9 | server pages | `confirmed` was always `[]`. | Clients could not learn that a sent mutation committed when its receipt was lost. |
| 10 | client `receive` | ACK and PUSH set `checkpoint = record.seq`. | Tablets skipped intervening work orders after a push (09:36). |
| 11 | client ACK | Removed every pending intent for the same *entity*. | The unsent assignment edit disappeared after the delayed receipt (09:11). |
| 12 | client numbers | Decimals were converted with `Number()`. | Wrong newer/older decisions above 2^53. |
| 13 | client SNAPSHOT | Every page merged into `base` and moved the checkpoint; completion did not replace `base`. | A half-finished bootstrap altered the view (09:36), and stale or deleted entities were never removed. |
| 14 | client batch | SEND_BATCH used the raw base for every op (no predicted revisions), had no in-flight guard, and was not immutable. ACK_BATCH cleared the *whole* queue without validation. | Closeout steps 2 and 4: later edits were lost, and a rebuilt batch omitted confirmed members and failed idempotency. |
| 15 | client view | `restore` and edits were not checked against tombstones. | Deleted work orders reappeared locally. |
| 16 | durable | `save` wrote in place (not atomic, and the hook ran after the write). `sendOnce`/`sendBatchOnce` persisted only *after* the network call. | After a tablet restart the wire was gone. The rebuilt request had a new base and conflicted (09:11), causing a duplicate visit. |
| 17 | HTTP | `parse_qs` dropped blank `cursor=`, which silently restarted paging. Parse `ValueError`s raised deep in the store were mislabelled as 400. A new `Store` (and write lock) was opened per request. | Silent restarts of paging; unexpected faults masked as client errors. |

## Repairs

### Server (`server/store.py`, `server/codec.py`, `server/http.py`)
* **Transactions.** Every write uses its own connection (autocommit mode, explicit `BEGIN IMMEDIATE`, 15 s busy timeout). The document, chaos hook, event, chaos hook and receipt steps all run inside ONE transaction. Any exception rolls the transaction back and propagates; the hook is never caught.
* **Idempotency.** Idempotency is keyed on `(tenant, device, mutation)` with a canonical request digest: a matching retry returns the original stored response, and a different request gets 409 `idempotency_reuse`. Failed requests leave no trace. The current state is read from the immutable event log, not the projection.
* **Wire format.** Revisions, seqs, cuts and checkpoints are canonical decimal strings. Visit amounts and totals are bounded by 2^53-1. Lone-surrogate strings and `NaN`/`Infinity` are rejected as 400 (earlier they caused 500s).
* **Snapshot.** Each page returns the latest event per id at or before the frozen `cut` (tombstones included) and keeps paging after `last`. The token's `cut` is validated (decimal, at or below the head).
* **Pull.** The scan start is exclusive, `until` comes from the token, and the token is fully validated.
* **Confirmations.** Snapshot pages carry all confirmations at or before the cut for the page's ids. Pull pages carry one confirmation per returned event.
* **`mutate_batch`.**
  * Validation: strict envelope validation, 1–16 operations, distinct mutation IDs.
  * Retries: the batch receipt is checked first; a matching retry returns the original response and a mismatch gets `idempotency_reuse`.
  * Key collisions: a committed operation key gets `batch_conflict` with `detail.index`.
  * Atomicity: all operations run against transaction-local state in one IMMEDIATE transaction with per-operation chaos hooks. Any failure rolls back everything and reports `detail.index`.
* **Repair.** `repair_projection()` / `repair_documents(db)` rebuild `documents` from each tenant/id's last event in one IMMEDIATE transaction. They delete projection-only rows, insert missing rows and rewrite wrong revision/body/deleted values. They return the number of changed keys and never touch events, receipts, batches, metadata or `sqlite_sequence`.
* **HTTP.** One `Store` per server, strict `limit` parsing, blank cursors kept (so they yield `invalid_cursor`), and SyncErrors raised only for real protocol failures; anything else is logged and returns 500 `internal`.

### Repair tool (`tools/repair.py`)
`python3 tools/repair.py --db PATH` refuses to run on a missing file (it never creates a new DB with a new epoch). It also rejects files that lack the work-order tables or don't have exactly one epoch. Otherwise it runs the transactional repair and prints `{"repaired": N}`. A second run prints `{"repaired": 0}`.

### Client (`client/replica.mjs`, `client/durable.mjs`, `client/trace.mjs`)
* **Precision.** Comparisons and arithmetic on decimals use transient BigInt; state remains JSON. Ids sort in code-point order, matching SQLite's UTF-8 order.
* **Merge rules.** A record merges only if its revision is strictly newer; equal revisions with different content raise an explicit corruption error. The checkpoint moves only on a completed snapshot (to its cut) or a contiguous pull page (to `after`).
* **ACK.** ACK removes exactly the matching mutation, merges its record only if newer, and rejects foreign receipts and receipts for unsent intents. CONFLICT and RESOLVE follow the contract and refuse members of an in-flight batch.
* **Snapshot staging.** Pages are staged with their epoch, cut, rows, confirmations and a post-cut buffer. Completion atomically replaces `base`, reconciles confirmations, replays post-cut PUSH/ACK records and preserves pending work. Mixed or backward cuts are rejected; a duplicate page from a completed snapshot is a no-op. The staging state records `next` so a restart can resume the same cut.
* **Pull.** PULL merges events, retires confirmed intents (matched on device + mutation + entity) and commits `after`, all in one transition. Consumed pages are no-ops; a gap is an error.
* **Batches.** SEND_BATCH freezes the batch wire using predicted per-entity bases; repeats are idempotent, and conflicting or overlapping sends are errors. ACK_BATCH validates membership and order, merges without rollback and removes only members. A duplicate of an accepted response is a no-op; fingerprints of the last 64 accepted batches are kept.
* **Durable storage.** `save` writes and fsyncs a temporary sibling, then renames it over the target. If the hook fails the temporary file is cleaned up. `sendOnce`/`sendBatchOnce` persist the wire before calling the exchange, keep it on transport failure and persist the ACK atomically.
* **Visit bound.** An optimistic visit that would push the projected total past 2^53-1 is listed as a conflict instead of producing an imprecise count.
* **Trace runner.** `trace.mjs` reports malformed input or actions on stderr with a nonzero exit.

### Working database (`state/site.sqlite`)
`python3 tools/repair.py --db state/site.sqlite` returned `{"repaired": 4}`:
* `north/pump-17`: revision 41 → 43, matching the last event (assignee null, done).
* `north/valve-4`: deleted flag 0 → 1 (it is a tombstone).
* `south/pump-17`: restored at revision 6.
* `north/phantom`: removed (it has no events).

Metadata (epoch `dispatch-2026-04`), events, receipts, batches and `sqlite_sequence` are byte-for-byte identical to before the repair; this was checked by comparing table dumps.

## Validation

```
python3 tests/smoke.py                       # 28 server/HTTP/repair tests
node --test tests/client-smoke.mjs           # 23 client/durable/end-to-end tests
node client/trace.mjs < incidents/client-actions.json
python3 tools/seed.py --db /tmp/x.sqlite && python3 tools/repair.py --db /tmp/x.sqlite
```

The regression tests cover:
* the incident traces;
* idempotent retries after newer writes;
* same mutation IDs on different devices;
* fault-hook rollback at both points;
* multi-process races (single writes and identical batches);
* frozen snapshot cuts under concurrent writes;
* the pull boundary and frozen `until`;
* seqs above 2^53;
* Unicode ids and payloads;
* cursor tampering;
* atomic and partial closeouts;
* confirmations (pull boundary inside a closeout, rebootstrap after a lost response);
* atomic durable saves;
* identical retries after restart;
* an end-to-end JS client against the real HTTP server.

## Limitations

* **Lost responses during a push.** Before a confirmation-bearing pull or snapshot arrives, a PUSH (which carries no confirmations) of a record that already contains our unacknowledged visit can show that visit twice in the optimistic view. This resolves on the next ACK, pull or snapshot. The protocol provides no other evidence to act on.
* **Duplicate snapshot pages and batch ACKs.** Detection uses a compact non-cryptographic hash. Only pages of the most recently completed snapshot, and the last 64 accepted batch receipts, are recognised.
* **Reused mutation IDs.** The client relies on the protocol rule that a mutation ID is never intentionally reused after confirmation; it does not keep an unbounded history of retired IDs.
* **Delayed old-epoch receipts.** Receipts (ACK, CONFLICT, ACK_BATCH) carry no epoch, so one from a previous epoch that arrives during a new-epoch bootstrap is attributed to the epoch being staged.
* **Cursor positions.** Cursors are checked for format, mode, tenant, epoch and internal consistency, but they are unsigned (as the protocol allows). A hand-forged position that is consistent but was never issued can skip rows.
* **Single-send conflicts.** `sendOnce` applies ACK; a non-ok response (e.g. 409 conflict) is propagated as an error with the wire kept. The adapter decides whether to dispatch CONFLICT.
* **Journal mode.** SQLite stays in rollback-journal mode, so readers briefly block a committing writer (bounded by the busy timeout). WAL was not enabled because it changes the on-disk database format.
