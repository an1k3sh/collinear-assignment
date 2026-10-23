# Operating constraints

All intervals are half-open `[start,end)`. Ending at a boundary is allowed.
Customer deadlines and expiry are inclusive bounds on service END. Integers
are minutes from 08:00. No work may occur before minute 0 or after the
`horizon` in settings.

## Packing

Each order has exactly one nonpreemptive packing job of the SKU's required
duration. Assign a bench whose `families` contains the product family.
Benches handle one order at a time, within their `start`/`end` shift.
No packing interval may overlap any `bench_breaks.csv` interval for that bench.
Every allocated lot must already be available when packing starts.

Packed product leaves refrigerated storage when packing ENDS. For each order:

    service_end - pack_end <= sku.max_unrefrigerated

The packed product cannot be refrigerated again. This covers staging, loading,
driving, waiting and customer handover.

## Loading and trips

Each trip starts and ends at DEPOT, using one vehicle. A vehicle must support
the families of all orders on the trip; its family list is not a mixing ban.
Capacity is the SUM of quantities, not the number of stops. The stop count may
not exceed the vehicle's `max_stops`; no customer is visited without delivering
its entire order. Different orders at the same node still need separate
service intervals.

There is ONE loading dock. Every trip occupies it for
`load_base + load_per_unit * total_quantity` consecutive minutes. Loading
intervals may not overlap each other or dock closures in `dock_breaks.csv`.
All orders on the trip must finish packing at or BEFORE its loading START.
The vehicle is occupied starting at loading start. Departure is exactly at
loading end.

For every leg, use the directed matrix, including depot outbound and return.
Service may start after arrival (waiting is allowed) but not before.
Each customer's complete service interval must fit its [open,close] window.
After the last service, drive directly back to DEPOT: reported return time
must equal last service end plus the matrix return time.

The sum of DRIVING minutes on a trip cannot exceed that vehicle's
`max_drive`. Waiting and service do not count toward this limit.
The whole trip from loading start to depot return must be within the vehicle
shift. The vehicle's next loading start must be at least `turnaround` minutes
after its preceding return. A vehicle can make at most `max_trips` trips.
There is no additional vehicle break or cumulative range rule.

## Spend

Amounts are integer cents. Hiring a vehicle costs its `hire_cents` once if
used at all. Each dispatched trip costs `trip_cents` PLUS
`drive_cents_per_minute` times its driving minutes. All values come from the
vehicle row. No other fee or overtime applies.

The recomputed total must be at most `budget_cents` in settings.
