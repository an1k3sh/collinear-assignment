# Weekend reslotting authorization

## Inventory and locations

There are 80 distinct SKUs and 80 indivisible pick slots. Every SKU must occupy
exactly one slot, and every slot exactly one SKU. The tables use exact string
identifiers.

`skus.csv` gives each SKU's required `zone`, its integer `move_minutes`, and
`fixed` (1 or 0). `slots.csv` gives each slot's zone and aisle/bay coordinates.
A SKU must remain in a slot of its required zone. Fixed SKUs must stay in
their exact `baseline.csv` slot. There is no other hidden dimensional,
hazard, capacity, replenishment, adjacency or equipment constraint.

## Relocation resource

Moving a SKU away from its baseline slot consumes its `move_minutes` ONCE,
irrespective of travel distance or the number of intermediate moves.
Unchanged SKUs consume no minutes. Sum this over all SKUs and stay at or below
`relocation_budget_minutes` in settings. This is a layout authorization,
not a physical swap/empty-slot execution sequence.

## Walking metric

`transitions.csv` records directed historical picker transitions:
`from_sku,to_sku,traversals`. Each row contributes

    traversals * distance(assigned_slot(from_sku), assigned_slot(to_sku))

to the total walking metric. Sum EVERY row once. There are no depot terms,
normalization factors, routing alternatives, frequency weights to infer,
or implicit return legs.

`distances.csv` contains the complete slot-to-slot distance matrix in integer
walking ticks, including zeros on the diagonal. Use its entries directly.
It models walking via cross-aisles and is not straight-line distance.
No shortest-path recomputation is required.

The target `max_travel_ticks` in settings is a hard authorization criterion.
The supplied baseline is already improved by eligible pair swaps; merely
moving high-volume SKUs toward one end or stopping at a pair-swap local minimum
is not itself a success criterion. The target requires 2% less travel than that
baseline, rounded down to whole ticks. A verified feasible solution exists.
No exact optimum or specific arrangement is demanded.

## Artifact and verification

`layout.json` is:

```json
{
  "assignments":[{"sku":"SKU-000000","slot":"S00"}],
  "metrics":{"travel_ticks":12345,"relocation_minutes":100}
}
```

Include one entry per SKU; array order is irrelevant. Both metric values must
be correctly recomputed integers. Additional fields are allowed. The scorer
returns the measured objective, relocation use and explicit constraint errors.

Provide the code and command used to obtain the layout, with seeds/parameters
if relevant, so the search can be reproduced. Only the saved layout and
measured constraints determine feasibility; the verifier does not demand a
particular optimizer or rerun a long search. The report should summarize the
method, baseline comparison and validation.
