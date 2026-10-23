# Carrier extension 3.0

This document extends the base language and durable execution contract.
These are public semantics, not facts about which incident requests succeeded.
Determine the incident outcome from the service records and supplied evidence.

## Separate authorities

Warehouse quantities, holds, events, variables and `deliveries` are LOCAL
transactional state. A transaction rollback restores all of those.

Carrier acceptance is independently durable. It is NOT local transactional
state. Local rollback, failed output publication, a fatal interpreter error,
or loading an older checkpoint must never rewind or erase carrier records.
The same applies to the carrier's attempt log.

A carrier timeout does not specify whether acceptance occurred. Receipt lookup
is authoritative. A recorded acceptance is irreversible in this simulator.
Do not retry with a new key or a different payload to resolve an uncertain
outcome. Receipt IDs are opaque strings; do not infer order from their spelling.

## Supplied deterministic service

`/app/carrier_service.py` is immutable environment code. `Carrier(path)` opens
an existing SQLite service database. It exposes:

* `.service_id`: stable nonempty string identifying that service history.
* `.lookup(key)`: accepted record dictionary, or `None` if no acceptance exists.
* `.submit(key, warehouse, sku_a, qty_a, sku_b, qty_b)`: receipt string, or raises
  `CarrierFailure(code, message)`. This call durably records its outcome before
  returning or raising a transport/domain response.

Accepted record fields are `receipt`, `warehouse`, `sku_a`, `qty_a`, `sku_b`,
`qty_b`. Exact ordered line payload is bound to the key. Different line ordering
counts as a different payload even if aggregate quantities match.

Database read interface: `metadata(name,value)`, `policies(request_key,mode)`,
`accepted(request_key,receipt,warehouse,sku_a,qty_a,sku_b,qty_b)`, and
`attempts(seq,request_key,outcome)`. Only the supplied API may write the service.
Successful acceptance and the attempt log are committed together.
Lookup is read-only. There are no threads, random delays or actual network calls.
SQL quantity columns hold decimal text to preserve arbitrary-precision integers;
the Python API returns quantities as integers.

Policies are deterministic:

* `ack` (default): accept and return a receipt.
* `accept_then_timeout_once`: first submission accepts, then raises
  `CARRIER_TIMEOUT`; later same-payload submissions return that receipt.
* `timeout_before_once`: first submission records a timeout without acceptance;
  a later submission accepts normally.
* `reject`: submissions raise `CARRIER_REJECTED` without acceptance.

Existing same-key/same-payload acceptance always returns the existing receipt.
An existing key with a different payload raises `CARRIER_CONFLICT` and leaves the
acceptance unchanged. Retries may add attempt records, never another acceptance.
Service inputs use nonempty strings and positive integer quantities.

Initialize a fresh fixture with:

```
python /app/carrier_service.py initialize --seed seed.json --database state.sqlite
```

Seed schema: `service_id` string, `policies` object, and optional `accepted` object
mapping keys to full accepted records. Receipt IDs in a valid seed are unique.
Initialization refuses an existing database. All acceptance fixtures are valid.

## CLI and checkpoint identity

The interpreter accepts optional `--carrier PATH`. Programs not using the
carrier continue to work without it. Carrier access without this option is IO
(7), not a recoverable domain failure. Source is still statically validated
before executing any statement or carrier submission.

Checkpoint `identity` now has exactly FOUR fields: `program`, `inventory`,
`library` as before, plus `carrier`. `carrier` is the service's `.service_id`,
or null without `--carrier`. The header version/format are unchanged.
All checkpoint checksums cover this extended identity normally.

Bind the service ID, not its file path or its mutable database hash. Paths may
change, and the service may advance between suspending and resuming. A different
service ID is CHECKPOINT (8); a missing/unreadable database is IO (7).
The live carrier is an explicit external dependency, NOT checkpoint payload.
Do not embed or restore a copy of its database inside continuation state.

Output/checkpoint paths must not alias the carrier database. Treat such aliases
as IO before execution. No acceptance test uses concurrent path races.

On pause, publish only the checkpoint. On completion, publish only the result.
On error preserve both preexisting output/checkpoint files, as before.
These file-publication guarantees do NOT reverse carrier effects.
Self-contained checkpoint relocation still applies to local interpreter state;
carrier-aware tests additionally supply the existing service at its new path.
Byte-identical inputs plus the same carrier history reproduce local results;
attempt counts can advance on repeated external calls and are not local stats.

## DSL additions

Builtins are positional, statically typed and evaluated left-to-right:

* `carrier_send(key:string, warehouse:string, sku_a:string, qty_a:int,
  sku_b:string, qty_b:int) -> string`
* `carrier_receipt(key:string) -> string`: accepted receipt, or empty string.
* `carrier_warehouse(key:string) -> string`: accepted warehouse, or empty string.
* `carrier_matches(key:string, warehouse:string, sku_a:string, qty_a:int,
  sku_b:string, qty_b:int) -> bool`: whether acceptance has exactly this payload.
* `delivered(key:string) -> bool`: whether LOCAL delivery bookkeeping exists.

Carrier builtin names are reserved against procedure definitions, like existing
builtins. `carrier_send` validates nonempty names (`NAME`), positive quantities
(`QUANTITY`), and a known LOCAL warehouse (`WAREHOUSE`) before calling the
service. It never changes local stock, holds, deliveries or events.
`carrier_receipt`/`carrier_warehouse`/`carrier_matches` read the carrier even
inside a transaction. Their results are not snapshot-isolated.
Empty key in any of these builtins or `delivered` is DOMAIN `NAME`.
An unknown nonempty key returns the documented empty/false value.
CarrierFailure codes become recoverable DOMAIN errors with original source
position and procedure stack. IO/SQLite failures are fatal IO, not DOMAIN.

New statement:

```
record_delivery(key_expression, receipt_expression);
```

Both operands are statically string. `record_delivery` is a reserved keyword.
Validate before mutation:

* Empty operands give `NAME`.
* A locally recorded key gives `ALREADY_POSTED`.
* Missing acceptance or wrong receipt gives `CARRIER_CONFLICT`.
* Holds `key + ".a"` and `key + ".b"` must exist, have remaining zero and
  match the carrier's warehouse and corresponding SKU. Otherwise `HOLD`.

On success, add a local delivery record equal to the six-field carrier accepted
record. It does not independently debit stock or emit an event; the workflow
must do that. The operation, its delivery record and `delivered()` participate
in ordinary local transaction rollback and checkpoint persistence.

Success results now additionally have `"deliveries": {key: accepted_record}`.
For programs with no recorded deliveries this is `{}`. A result's delivery
record does not replace the authoritative carrier receipt record.
`record_delivery` counts as one entered statement; builtins are expressions.
Base counters remain local diagnostics. Carrier calls do not add implicit steps.
