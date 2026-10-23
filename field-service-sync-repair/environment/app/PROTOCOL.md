# Work-order sync protocol, version 2

This contract is authoritative. The implementation is not. IDs and text are
case-sensitive Unicode strings. JSON object member order is not significant.
The data model is deliberately small; do not introduce a new framework.

## Server surface and storage

`Store(path)` exposes `mutate(request)`, `snapshot(tenant, limit, cursor=None)`,
`pull(tenant, checkpoint, limit, cursor=None)`, and `repair_projection()`.
All return JSON-compatible dictionaries. `SyncError(status, code, detail)`
represents a protocol failure. Unexpected failures propagate; HTTP reports a
diagnostic 500 rather than success.

SQLite tables: metadata(epoch), documents(tenant,id,revision,body,deleted),
events(seq,tenant,id,revision,body,deleted,device,mutation),
receipts(tenant,device,mutation,digest,response). Do not change this format.
Events are immutable complete after-images, including tombstones. Sequence is
global across tenants; entity revision is per tenant/id. Gaps are valid.
All revisions, event sequences, cuts and checkpoints on the wire are canonical
nonnegative DECIMAL STRINGS, including values greater than 2^53. Internal SQLite
integers stay within signed 64-bit range. Zero is `"0"`, never `"00"`.

A wire record is `{id, revision, body, deleted, seq}`. Body is
`{title:string, assignee:string|null, visits:integer>=0, done:boolean}`.
Title must be nonempty. Visits/visit amounts must not exceed 2^53-1, including
the total after increment. `assignee:null` explicitly clears the field.
Absent patch members retain their old values. Unknown body/patch fields,
booleans as numeric counts, nonfinite numbers and invalid types are errors.
Mutation IDs, devices, tenants and entity IDs are nonempty strings.

### Mutations

Request:
```
{"tenant":"north","device":"van-7","mutation":"m-9","id":"w-1",
 "base":"3","kind":"patch","data":{"assignee":null}}
```

Kinds:
* create: base `"0"`, full valid body, entity ID has never existed.
* patch: partial body; currently live entity; exact current base revision.
* visit: `{"amount":positive integer}`; increment visits, live entity, exact base.
* delete: `{}`; live entity, exact base; preserve body in the tombstone.
* restore: partial body; currently deleted entity, exact base; explicit revival.

Each success increments revision by one, writes one event, updates the projection
and stores a receipt in ONE transaction. Rejected requests change none of them.
Normal success is `{ok:true, mutation, device, tenant, record}`.

Idempotency scope is `(tenant,device,mutation)`. A successful retry with the same
semantic request returns the ORIGINAL response, even after newer writes.
A successful key reused for a different request yields 409 `idempotency_reuse`.
Canonical digest covers the entire request; JSON key order must not matter.
Failed requests do not consume a key. Revision/deletion conflicts return
409 `conflict`, with `detail.current` holding the current record or null.
Unknown/invalid inputs return 400 `invalid`.

Concurrency must be correct across independent Store instances/processes.
Two writes against one revision cannot both succeed. `Store(path, fault=hook)`
is the existing chaos-test interface: hook is called with `"after_document"`
and `"after_event"` inside the transaction. An injected exception must roll
back documents, events and receipts. Never disable or catch-and-ignore the hook.
Each operation uses its own SQLite connection with a busy timeout.

### Stable snapshots and pull pages

Limits are integers 1..100. Cursors are opaque base64url JSON tokens created by
the server. Decode/validate them; malformed, wrong-mode, wrong-tenant, wrong-epoch
or inconsistent tokens produce 400 `invalid_cursor`. Tokens are not credentials
and need not be cryptographically signed.

The first snapshot page freezes the global event high-water mark `cut`.
Every page must return each tenant entity's latest event AT OR BEFORE that cut,
including tombstones, sorted by id. Do not read current projection rows as if
they were historical rows. The continuation holds the same cut and last id.
Concurrent writes/new entities never enter an already-open snapshot.
Response: `{kind:"snapshot",tenant,epoch,cut,rows,next_cursor}`.
Null next_cursor completes the snapshot, even for an empty tenant.

Pull starts from an exclusive checkpoint. The first page freezes global high
water `until`; subsequent pages keep it. Return this tenant's events with
checkpoint < seq <= until, sorted by seq. The token stores the exclusive
last-scanned position and original until. The caller must pass the same
checkpoint it used on page one when resuming with a token.
Response:
```
{kind:"events",tenant,epoch,from,after,until,events,next_cursor}
```
`from` is that page's exclusive scan start, not always the original checkpoint.
If more events remain, after is the last returned seq. On the final page, after
is until, even if there are no tenant events or global sequence gaps.
Do not duplicate boundary events or chase a moving until. Checkpoint beyond the
current global head is 400 `invalid_cursor`.

## Client replica

`client/replica.mjs` exports `createReplica(tenant,device)`,
`reduce(state, action)`, and `selectView(state)`. Reducer is deterministic and
does not mutate its input state or action. State is JSON-serializable.
`client/trace.mjs` reads one JSON object `{state?,tenant?,device?,actions}` from
stdin and outputs `{state,view}`; malformed actions produce stderr/nonzero.
No BigInt may leak into JSON. Comparisons must preserve decimal-string precision.

State contains tenant/device, epoch (null before bootstrap), base (record map),
pending (ordered local intents), checkpoint (`"0"` initially), and snapshot
(null or staging state). Additional implementation fields are allowed.

Actions:
* QUEUE: `{type,mutation,id,kind,data}`. Append a unique local intent. Do not
  freeze a base revision until its first send. Preserve queue order.
* SEND: choose the FIRST pending intent, unless it is blocked; capture an
  immutable request in `pending[0].wire`. Repeated SEND returns the identical
  wire request even if remote records change. Only the first pending intent
  may be sent; requests after it wait for ACK or explicit resolution.
* ACK: `{type,response}`. Match tenant, device and mutation; remove ONLY that
  intent. Merge the record only if newer. A delayed ACK must not overwrite a
  newer remote record. A duplicate ACK may merge but cannot clear other edits.
* CONFLICT: `{type,mutation,current}`. Merge current if newer and mark this
  intent blocked. Preserve its wire. Do not automatically retry/rebase.
* RESOLVE: `{type,mutation,mode,newMutation?}`. Mode drop removes that blocked
  intent. Mode retry replaces its mutation ID, discards the old wire, and
  unblocks it; next SEND captures the current base. Only blocked intents may
  be resolved. IDs remain unique in the pending queue.
* PUSH: `{type,record,epoch}`. Merge a newer record but NEVER advance the stream
  checkpoint: receipt/push arrival is not proof of contiguous delivery.
  Unknown/new epoch requires a new snapshot, not mixing histories.
* SNAPSHOT: `{type,page}`. Stage pages at one epoch/cut; no partial page may
  replace base or advance checkpoint. On completion atomically replace base,
  set epoch/cut checkpoint, preserve pending intents, and replay pushes/ACK
  records received after that cut. This must remove stale local base entities.
  A later page with a different epoch/cut is an explicit error.
* PULL: `{type,page}`. No pull pages while a snapshot is in progress. Tenant/
  epoch must match. `from` must equal the committed checkpoint, except an
  already-consumed page (`after <= checkpoint`) is an idempotent duplicate.
  Merge its records then commit after. A gap/out-of-order page is an error,
  not permission to jump the checkpoint.

The first snapshot is mandatory before network actions other than SNAPSHOT.
QUEUE is allowed before bootstrap. During snapshot staging, PUSH/ACK may arrive
for its epoch; buffer them, and preserve local queue handling. Only records with
seq > cut replay after completion. Individual record comparison uses revision;
equal revisions must have the same semantic record or are explicit corruption.
Snapshot rows can repeat on page retries if identical. Mixed/conflicting rows
must fail explicitly. Backward same-epoch snapshot cuts must be rejected.

`selectView` returns `{records:[...], conflicts:[mutation IDs...]}`. Start from
authoritative base and replay pending intents exactly once in queue order.
Records sort by id; exclude tombstones. Blocked intents are listed as conflicts
and do not apply. A pending ordinary edit cannot revive a remotely deleted or
missing entity; list it as a conflict instead. Explicit restore can revive a
tombstone. Preserve other pending intents after ACK. Optimistic visit increments
must not be doubled when the server acknowledgement already contains the visit.
Projection is never written back as authoritative base.

## Durable client state

`client/durable.mjs` exports `save(path,state,hook?)`, `load(path)`, and
`sendOnce(path, exchange)`. `save` writes a temporary sibling then atomically
renames it; hook `"before_rename"` simulates a crash before replacement. The old
file must remain valid; clean the temporary file on failure. Missing load is
an error, not an empty successful replica.

`sendOnce` loads, performs SEND, saves the resulting immutable wire BEFORE
calling exchange(wire), then applies ACK and saves again. Exchange may throw
after server commit (lost response). Propagate the error and keep the persisted
wire so restart/retry sends exactly the same request. Never dequeue on a transport
error or persist only after the network side effect. A blocked/empty queue
produces no exchange call and returns the current state.

## Projection repair and public HTTP adapter

`repair_projection()` transactionally rebuilds documents from each tenant/id's
last event. Remove projection-only rows, restore missing rows, fix wrong body,
revision/deleted values. Never alter events, receipts, epoch or their sequences.
It is idempotent and returns `{repaired:integer}` counting changed entity keys.
The incident seed has sufficient authoritative history; do not invent data.

Run `python3 -m server.http --db PATH --port PORT`. GET /health returns 200.
POST /mutate accepts a mutation. GET /snapshot uses tenant,limit,cursor query
parameters; GET /pull adds checkpoint. Successful calls return 200 JSON.
SyncError uses its status with `{ok:false,code,detail}`. Other errors are
logged and return 500 `{ok:false,code:"internal"}`. JSON is UTF-8.
No authentication work, UI redesign or new database schema is requested.
