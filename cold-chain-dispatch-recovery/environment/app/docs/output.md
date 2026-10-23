# Plan format

`plan.json` is an object with these required fields. Additional fields are
allowed. Lists may be in any order except each trip's ordered `stops`.

* `roster`: one object for every dispatchable order, containing exactly the
  source values for `account`, `order_id`, `sku`, `quantity`, `node`, `open`,
  `close`, `service`. The numeric fields are JSON integers, identifiers strings.
* `allocations`: objects `{account, order_id, lot, quantity}`. The positive
  integer quantities for an order sum to its required quantity.
* `packing`: one object per order:
  `{account, order_id, bench, start, end}`.
* `trips`: objects with a unique string `trip_id`, a `vehicle` ID,
  integer `load_start`, integer `depart`, integer `return`, and ordered `stops`.
  Each stop is `{account, order_id, service_start}`. Every dispatchable order
  occurs exactly once across all trips.
* `cost_cents`: the correctly recomputed integer spend.

Example of the STRUCTURE only (not real IDs or a feasible schedule):

```json
{
  "roster": [
    {"account":"A","order_id":"001","sku":"S","quantity":2,"node":"N",
     "open":50,"close":100,"service":3}
  ],
  "allocations": [{"account":"A","order_id":"001","lot":"L","quantity":2}],
  "packing": [{"account":"A","order_id":"001","bench":"B","start":10,"end":20}],
  "trips": [{"trip_id":"T","vehicle":"V","load_start":25,"depart":31,"return":60,
             "stops":[{"account":"A","order_id":"001","service_start":40}]}],
  "cost_cents":10000
}
```

Write a real offline planning program, not a copy of a plan file. It must accept
`--data` and `--output`. It may use intermediate files under the output
directory. Reruns may choose different equally valid schedules.
The grading rerun uses the SAME input contents in another directory, not
undocumented mutations or future days, and has a 180-second runtime allowance.
Your own planning experiments can run longer; the final program must finish
within that allowance on the declared four-CPU environment.
