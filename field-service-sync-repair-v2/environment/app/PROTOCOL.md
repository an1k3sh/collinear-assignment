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

## Version 2.1: atomic closeouts and receipt-aware catch-up

This section extends the earlier interfaces. All earlier guarantees still apply.
There is one additional existing table:
`batches(tenant,device,batch,digest,response)`, primary key (tenant,device,batch).
Projection repair must preserve this table as well.

### Atomic server closeout

`Store.mutate_batch(request)` and POST `/batch` accept:
```
{"tenant":"north","device":"van-7","batch":"closeout-3",
 "operations":[
   {"mutation":"visit-3","id":"pump","base":"1","kind":"visit","data":{"amount":1}},
   {"mutation":"done-3","id":"pump","base":"2","kind":"patch","data":{"done":true}}
 ]}
```

Operations are an ordered list of 1..16 ordinary mutations, omitting tenant and
device (inherited from the envelope). Operation mutation IDs must be distinct.
They share the ordinary receipt namespace for that tenant/device. Batch IDs have
their own namespace. The base revision is checked against transaction-local
state, including earlier operations in the same batch.

Success is `{ok:true,tenant,device,batch,responses:[ordinary receipts in order]}`.
All operations and the batch receipt commit atomically. If any operation fails,
none of their projections, events, ordinary receipts or batch receipts remain.
Report that SyncError, with `detail.index` added (zero-based failing operation).
The same chaos hooks apply to every operation. Do not turn a storage exception
into success or partially commit earlier operations.

Exact batch retries return the original full response. Same batch key/different
semantic request returns 409 `idempotency_reuse`. An operation key already
committed outside this batch produces 409 `batch_conflict` with detail.index,
even if its request matches; a batch cannot pretend earlier independent work
was one atomic commit. Check the batch's own receipt FIRST so exact retries work.
Rejected batches consume neither batch nor operation IDs. Invalid envelopes,
unknown fields, duplicate operation IDs or non-list operations are 400 `invalid`.
Independent processes racing the same batch must return identical receipts and
create only one set of events.

### Authoritative confirmations

Every snapshot/pull page now includes `confirmed`, a list of
`{device,mutation,id,seq}` objects from immutable events, ordered by sequence.
For a pull page these correspond exactly to its returned events.
For a snapshot page include ALL event confirmations at or before cut for the
entity IDs in that page's rows, including older revisions and tombstones.
Do not include another tenant, another page's entity IDs or post-cut events.
This lets a client discover that a sent local mutation committed even if its
HTTP receipt was lost and newer updates have since superseded its after-image.
Empty pages have `confirmed:[]`. The list is not an operation replay.

For compatibility, clients accept older pages with no `confirmed` as an empty
list. On PULL, merge records and remove matching pending intents in one reducer
transition. A confirmation matches only this replica's device and mutation AND
entity ID; a matching mutation with a different entity is explicit corruption.
A confirmation must never remove an unsent intent (no persisted wire); reject
that inconsistency explicitly. Other devices' same-named mutation IDs are ignored.
Already-consumed pull pages remain idempotent and do not act on new local work.
Do not assume the confirmation sequence is the latest entity revision/sequence.

For SNAPSHOT, accumulate confirmations alongside staged rows and apply them only
when the snapshot completes. Until then, keep pending intents. On completion,
atomically replace base, reconcile confirmations, replay post-cut deliveries
and preserve unrelated pending edits. A delayed ACK after confirmation is safe.
Confirmations at/before a new snapshot cut can retire an old durable wire;
the same queue mutation ID is never intentionally reused after confirmation.

### Client batch send and acknowledgement

The existing single-send flow remains supported. Add actions:

* SEND_BATCH `{type,batch,count}`: capture the first count pending intents as
  one immutable batch request stored in `state.batch.wire`. Count is 1..16;
  the queue must contain that many intents. None may be blocked or already
  individually sent. All selected intents get their ordinary wire request.
  Compute base for each in order against authoritative base plus earlier
  selected operations' predicted revisions (not the optimistic view of the
  whole queue). A previously missing entity starts at `"0"`. Different IDs
  advance independently. Freeze all bodies and decimal strings.
  A repeated SEND_BATCH with the same batch/count returns the same wire even
  after pushes or partial confirmation; a different batch/count while a batch
  is in flight is an explicit error. SEND while a batch is in flight is an error.
* ACK_BATCH `{type,response}`: validate tenant/device and that batch, receipt
  membership and order match the captured wire. Merge each returned record
  without rolling back newer state, remove only acknowledged intents, and clear
  the in-flight batch. Wrong or incomplete membership is an explicit error;
  do not remove anything. Duplicate ACK_BATCH after completion is idempotent
  only for the same previously accepted response.

A snapshot or pull confirmation may retire some batch intents before ACK_BATCH,
but `state.batch.wire` remains immutable until ACK_BATCH accepts the full receipt.
This covers a pull page boundary inside a committed closeout. Later queued edits
must survive both partial confirmations and the final ACK_BATCH.
No conflict/retry/drop action may change a member of an in-flight batch: reject
such attempts explicitly. Failed batch HTTP responses are not acknowledgements;
this fixture requires error propagation, not interactive batch conflict resolution.

`client/durable.mjs` also exports `sendBatchOnce(path,batch,count,exchange)`.
Like sendOnce, persist the captured wire BEFORE exchange, retain it after an
uncertain transport failure, and atomically persist ACK_BATCH afterward.
On retry use the stored full batch, even if catch-up has retired some/all member
intents. `sendOnce` must not send a member of an in-flight batch.
