# Dispatch note — cold-chain morning dispatch (cutoff 2026-06-15 07:50Z)

## Order roster: 18 dispatchable orders (not 20)
Orders are keyed by `(account, order_id)`. For each key I took the latest version
recorded at or before the cutoff, then kept it only if it is `confirmed` and
already effective.
- **NORTH/900** excluded: the 07:40 version cancels it.
- **SOUTH/901** excluded: the 07:45 version is not effective until 09:00Z. The
  older confirmed version does not apply.
- **NORTH/003**: the 08:20 revision (qty 8) arrived after the cutoff, so the
  06:10 version (qty 2) applies.
- **SOUTH/002**: the 07:35 revision applies (qty 2, close 170).
- NORTH, SOUTH and WEST each have orders 001–006. IDs with the same number in
  different accounts are separate orders (for example SOUTH/003 and WEST/003).

## Stock
Events were deduplicated on `(warehouse, event_id)`; ANNEX and MAIN events with
the same ID are separate movements. The `*-future` receipts (08:30) were
excluded. Usable balances: C1 9, C2 8, C3 10, F1 9, F2 8, F3 10. C4 and F4 are
quarantined as of 07:49, so they cannot be used even though they were released
earlier. Lot use by window: NORTH uses C1/F1 (available from minute 0, expiry
140). SOUTH uses C1/C2/F2. WEST uses C3/F3 (available 115), because C1 and F1
expire before the WEST window. Total allocated: C1 9/9, C2 4/8, C3 7/10, F1 7/9,
F2 7/8, F3 7/10.

## Schedule (minutes after 08:00)
| Trip | Vehicle | Load | Depart | Return | Stops (service start) |
|---|---|---|---|---|---|
| V3-1 | V3 | 23 | 34 | 96 | NORTH/003 60, /002 70, /001 80 |
| V2-1 | V2 | 35 | 46 | 100 | NORTH/004 60, /006 73, /005 84 |
| V1-1 | V1 | 75 | 85 | 147 | SOUTH/001 105, /002 115, /003 127 |
| V3-2 | V3 | 111 | 122 | 184 | SOUTH/006 142, /005 153, /004 162 |
| V2-2 | V2 | 151 | 162 | 232 | WEST/004 184, /005 195, /006 206 |
| V1-2 | V1 | 162 | 173 | 241 | WEST/003 197, /002 207, /001 217 |

Key decisions:
- Each trip carries one account and one product family (3 stops, 7 units).
- Loading avoids the dock closure from 96 to 110. V1-1 finishes loading at 85,
  and V3-2 starts loading at 111.
- The plan uses only the minute-0 vehicles V1, V2 and V3. The more expensive
  V4 and V5 are not hired.
- Packing is timed so each order stays within its unrefrigerated limit (77 min
  chilled, 62 min frozen). Packing also avoids every bench break.

## Spend
3 hires × 11,500 = 34,500. Trips: 6 × 1,800 + 70¢ × 303 driving minutes = 32,010.
**Total 66,510¢**, which is under the 79,000¢ authorization. The solver proved
this is the lowest-cost plan for this model.

## Checks performed
`build_plan.py` builds a CP-SAT model with OR-Tools. It then checks the result
with a separate validator before writing the plan. The validator checks:
- roster coverage, with each order on exactly one trip and one packing job
- bench family, shift, break and overlap rules, plus packing duration
- lot SKU, release status, availability, expiry at service end and balance
- whole-order allocation
- vehicle family, capacity, stop limit and `max_drive` on the directed matrix
- service windows, arrival before service, and return equal to last service end
  plus the return leg
- vehicle shifts, turnaround and `max_trips`
- dock overlap and closures
- the recomputed cost and the budget

If any check fails, the program exits without writing a plan. I reran it from a
copied data directory in another working directory. It produced a valid plan in
about 10 s, well under the 180 s allowance.
