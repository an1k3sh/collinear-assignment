# Source-of-record rules

## Orders

`order_versions.csv` is an append-only export. An order key is the pair
`(account, order_id)`. Treat all IDs as strings. Each row is a complete
replacement, not a delta.

For each key, first select the row with greatest `recorded_at` at or before
`planning_cutoff`. Timestamps are ISO UTC, unique within each key. Then retain
the selected row only if `status` is `confirmed` AND `effective_at` is at or
before the cutoff. Do not use an older row if the selected version is cancelled
or not yet effective. Rows recorded after the cutoff were not known to the desk.

Customer service accepts a delivery only if the whole order arrives together.
One order uses one packing job and one trip/stop. It may consume multiple
compatible stock lots. `quantity` is the number of units (also vehicle capacity
units). `open` and `close` bound the complete customer service interval.
`service` is the fixed time to hand over the whole order.

## Stock

`lots.csv` supplies each lot's SKU and absolute expiry minute (after 08:00).
`stock_events.csv` is an at-least-once movement feed. Deduplicate by
`(warehouse,event_id)`; repeats describe the identical movement. Sum signed
`delta` values for each lot whose `recorded_at` is at or before the planning
cutoff. Do not count later movements. Inventory is shared by all orders.

`quality_versions.csv` is a versioned complete disposition, keyed by lot.
Select the latest record known at the cutoff. Only a selected `released` row
may be used. Its `available` minute is the earliest packing start for that lot.
Quarantined lots cannot be used, irrespective of an older release.

Lot expiry is checked at the END of customer handover, not vehicle departure.
The sum allocated from a lot cannot exceed its deduplicated available balance.
An allocation must match the order's SKU. Quantities must be positive integers.
No special FIFO/FEFO policy applies; expiry and conservation are mandatory.

## Reference tables

`skus.csv` defines product family, `pack_base`, `pack_per_unit` and
`max_unrefrigerated`. Packing duration is
`pack_base + quantity * pack_per_unit`.

`travel.csv` is the complete DIRECTED driving-time matrix, including `DEPOT`.
Use the supplied entries directly; do not symmetrize, substitute straight-line
distances, or find shorter paths through other customer locations.
