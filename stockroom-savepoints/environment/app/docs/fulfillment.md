# Bundle dispatch migration

Implement this procedure in `/app/workflows/fulfill.stock`:

```
proc fulfill(order: string, sku_a: string, qty_a: int,
             sku_b: string, qty_b: int, preferred: string, fallback: string)
```

Inputs to this business procedure are valid nonempty order/SKU names and positive
quantities; warehouses exist, preferred differs from fallback. Order identifiers
are unique across calls and neither `order + ".a"` nor `order + ".b"` already
exists as a hold. SKU A and B MAY be the same SKU.

1. Try to fulfill BOTH lines from preferred. Use holds named `order + ".a"` and
   `order + ".b"`, respectively. Reserving both before shipping either is a
   natural implementation; another operation order inside the same fully atomic
   attempt is accepted if its observable state and events are equivalent.
2. If that attempt fails with SHORTAGE, roll back the entire attempt and try
   BOTH lines from fallback using the same hold IDs. No splitting warehouses,
   partial shipment, replenishment, transfer, or bypassing holds.
3. If fallback also fails with SHORTAGE, roll back it too and emit one event
   named `deferred` with data `{"order": order, "reason": "SHORTAGE"}`. Return
   normally; subsequent orders must still run. No holds from either failed
   attempt may survive and on-hand must be unchanged.
4. A successful attempt ships both lines completely, leaves both closed holds,
   and emits exactly one `fulfilled` event with data:
   `{"order": order, "warehouse": chosen, "units": qty_a + qty_b}`.
   No other workflow events. Do not swallow other domain errors. There is no
   rethrow statement; an `assert code(e) == "SHORTAGE";` in recovery is an
   acceptable way to fail explicitly for a non-shortage.

The shipped procedure may use helpers. Your workflow file is a library: no
main procedure. Your implementation must also work inside a caller's enclosing
transaction, and must not accidentally read or write same-named caller locals.
Stats are checked against language statement semantics when executing arbitrary
test programs, but workflow stats are not pinned to an implementation.
