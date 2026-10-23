# Query and output contract

`request.json`:

```json
{
  "as_of":"2027-01-01T00:00:00Z",
  "windows":[
    {"id":"W","start":"2026-03-01T00:00:00Z","end":"2026-03-02T00:00:00Z",
     "calendars":["001","01"],"duration_minutes":45,"grid_minutes":30}
  ]
}
```

Window IDs and manifest calendar IDs are unique exact strings. Calendars named
by a window always exist. Bounds are UTC instants, end greater than start,
and meeting duration and grid are positive integers. Window length is at most
14 days. There are at most 20 calendars, 100 selected masters, 100 detached
components and 20 query windows. The whole finite recurrence sets may be
expanded; no streaming or asymptotic requirement is imposed.

Only blocking occurrences on a window's requested calendars whose ACTUAL
interval overlaps the half-open query `[start,end)` appear in its export.
Keep actual occurrence endpoints, not clipped endpoints, in the occurrence
list. Its `recurrence_id` is the ORIGINAL start converted to an instant
(including local midnight for all-day events). Moved instances retain that ID.

`bookings.json`:

```json
{"windows":[
  {"id":"W","occurrences":[
    {"calendar":"001","uid":"event","recurrence_id":"2026-03-01T09:00:00Z",
     "start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}
  ],"busy":[{"start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}]}
]}
```

`busy` is the union across all requested calendars of those actual intervals,
CLIPPED to the query. Merge overlap and touching intervals into maximal blocks.
There must be no duplicate occurrences. Ordering of windows and occurrences
is irrelevant. Timestamp strings are compared as instants, not formatting.

`availability.json`:

```json
{"windows":[
  {"id":"W","slots":[{"start":"2026-03-01T00:00:00Z","end":"2026-03-01T00:45:00Z"}]}
]}
```

Enumerate ALL meeting slots whose start is `window.start + k*grid_minutes`,
k an integer >=0, whose full elapsed duration fits in the window and intersects
no busy block. Meetings ending exactly at a booking's start, or starting
exactly at its end, are allowed. There is no extra working-hours rule.

The examples illustrate shape, not full outputs for a real input. Additional
object fields are permitted. Keep the original files unchanged. The program
must use the provided --source and --output arguments and work from another
current directory. The verifier's individual small fixture runs have a
30-second limit; their recurrence sets contain fewer than 100 instances.
