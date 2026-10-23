# Reusable carrier reconciliation workflow

Implement `/app/workflows/dispatch.stock` as a library with no main procedure:

```
proc dispatch_order(order:string, sku_a:string, qty_a:int,
                    sku_b:string, qty_b:int, preferred:string, fallback:string)
```

Inputs are valid names, positive quantities, known distinct warehouses. Both
lines may use the same SKU. Repeated calls for an order have the same ordered
SKU/quantity payload, although preferred/fallback may change. Hold IDs `.a` and
`.b` are reserved for this order and are not used by unrelated operations.

1. If `delivered(order)` is already true, return normally with NO stock change,
   carrier call, event or pause. Repeated application is a local no-op.
2. If the carrier has already accepted this key, use ITS recorded warehouse,
   even if current preferences differ. Assert/reject mismatched payloads
   explicitly; never create a new key or redirect an accepted shipment.
3. Otherwise choose preferred if it has enough FREE stock for both lines,
   fallback if not, or emit exactly one `deferred` event and return if neither
   fits. Account for same-SKU lines by adding their quantities. Deferred event:
   `{"order":order,"reason":"SHORTAGE"}`.
4. Apply a chosen attempt inside a LOCAL transaction: reserve both holds,
   pause `order + ":reserved"`, obtain an accepted receipt with the SAME order
   key/payload (using lookup or submit), ship both lines, record the local
   delivery, emit one `fulfilled` event, then pause `order + ":posted"`.
   Return normally after this attempt commits.

   Fulfilled payload:
   `{"order":order,"warehouse":chosen,"units":qty_a+qty_b,"receipt":receipt}`.

5. On `CARRIER_TIMEOUT`, roll back LOCAL effects and reconcile/retry with the
   same key. Do not interpret the timeout alone as success or rejection.
   The supplied policies resolve within at most two submissions for a new key.
   At most two submissions per not-yet-locally-delivered call are needed.
   Lookup of an existing receipt does not count as a submission.
6. On `CARRIER_REJECTED`, leave no local holds, debit or delivery and emit exactly
   one `rejected` event: `{"order":order,"reason":"CARRIER_REJECTED"}`.
   Return normally, so subsequent orders continue.
7. Other errors must fail explicitly rather than being mislabeled deferred or
   rejected. Exact propagated domain code is not pinned for workflow-internal
   assertion-based error checks. There is no DSL rethrow statement.

The procedure must compose with a caller's enclosing transaction. An outer
rollback can remove its local fulfilled event, stock debit, holds and delivery
record. It cannot remove the carrier's acceptance. A later application must
reconcile that acceptance with local state once, rather than submit another
physical shipment.

The verifier checks final inventory, holds, delivery mappings, event
payloads/order, carrier acceptances and bounded submissions. It does not require
a particular helper structure, rollback count or workflow statement count.
The reserved/posted pauses are required operational boundaries, not optional
debug logging.
