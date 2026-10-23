# Availability export reconstruction — handover

## Deliverables

- `rebuild.py` — stdlib + `zoneinfo` (pinned `tzdata` 2025b) exporter.
  Run with `python /app/submission/rebuild.py --source /app/input --output /app/submission`.
  It works from any current directory and writes both files atomically.
- `bookings.json`, `availability.json` — regenerated from `/app/input`.
  `/app/input` and `/app/docs` were checked by SHA-256 before and after: no changes.

## How it works

1. **Parsing.** Unfolds lines (one leading space or tab; CRLF or LF). Parses
   parameters, including quoted values such as a quoted `TZID`. Reads top-level
   VEVENT properties and ignores nested components.
2. **Revisions.** Components are keyed by (calendar, UID, RECURRENCE-ID instant).
   Revisions with `DTSTAMP > as_of` are dropped. The exporter keeps the highest
   `(SEQUENCE, DTSTAMP)` regardless of file order. A cancelled master deactivates
   the whole UID. Detached components without a master are ignored.
3. **Recurrence.** DAILY and WEEKLY rules (INTERVAL, BYDAY, Monday week start)
   are expanded in the master's local wall clock.
   - Nonexistent local times are skipped and do not count towards COUNT.
   - Ambiguous times use fold=0.
   - UNTIL is inclusive.
   - RDATE values are added, EXDATE values are removed, and duplicates are removed
     by original instant. All-day dates mean local midnight.
4. **Detached changes.**
   - Single overrides and cancellations take precedence over a range.
   - A RANGE=THISANDFUTURE component applies a wall-clock displacement, measured
     from the original IDs in the master's zone. Displacements do not compound.
     Duration and TRANSP are inherited along the chain of ranges.
   - Detached components whose RID is not in the recurrence set are ignored.
5. **Durations.**
   - DTEND on a timed event gives elapsed seconds.
   - DURATION advances local days first and then adds H/M/S as elapsed time.
   - All-day events use local calendar days, with a default of 1 day.
6. **Exports.**
   - An occurrence is listed when it is blocking and its actual interval overlaps
     `[start,end)`. Endpoints are not clipped.
   - Busy blocks are clipped to the window and merged when they overlap or touch.
   - Slots are on the grid from the window start, fit inside the window and do not
     intersect any busy block. Touching a busy block is allowed.

**Interpretation note.** The contract leaves one case open: a start written in a
different zone from the master (for example an RDATE or override with a `Z`
suffix). For these, nominal-day (`P…D`) arithmetic uses **the master's timezone**,
the same anchor the contract specifies for range displacement. When the master
`DTSTART` uses `Z`, the master's zone is UTC; a floating or all-day `DTSTART`
uses the calendar's timezone.

## Incident results (hand-checked)

| Window | Key behaviour confirmed |
|---|---|
| spring | NY 02:30 daily skips the 8 Mar gap without consuming COUNT. Range on calendar `020` shifts +1 local day (EST→EDT kept at 09:00 local). |
| europe | Berlin all-day 29 Mar lasts 23 h (28T23:00Z–29T22:00Z). |
| summer | Ranges on calendar `20` do not compound (10:00, then 08:00). On calendar `002` the override inherits the range's 2 h. On `A` the override is opaque while the master is transparent. On `C`, seq 10 is past as_of so seq 9 is used. On `D`, RDATE/EXDATE are applied. `E` uses the floating time in Berlin. The cancelled master on `F` suppresses its override. |
| southern | Lord Howe's 30-minute DST gap: 4 Oct 02:15 is omitted. |
| autumn | NY 01:30 on 1 Nov resolves to the first instance (EDT). |

## Verification performed

- **RRULE fuzzing.** Compared against `dateutil.rrule` with gap filtering on 3,000
  random rules. Zones covered New York, Lord Howe, Berlin, Santiago, Tehran,
  Chatham and UTC. Rules varied DAILY/WEEKLY, INTERVAL 1–12, BYDAY, COUNT and
  UNTIL, and included all-day events. All matched.
- **End-to-end fixtures with hand-computed expectations:**
  - P1D vs PT24H vs P1DT1H30M across the DST change, DTEND elapsed time, folded
    and quoted `TZID`, LF endings;
  - weekly BYDAY with INTERVAL and UNTIL, EXDATE, a duplicate RDATE, a cancelled
    single, an orphan detached component, a future DTSTAMP;
  - range chains with TRANSP/duration inheritance, override precedence, a move out
    of the window, revisions split across files;
  - all-day DTEND/RDATE/EXDATE/UNTIL and moves in Lord Howe;
  - clipping and merging of touching blocks, separate calendar namespaces, a fold=1
    override start.
- **Brute-force check.** Busy blocks and slots for the delivered exports were
  recomputed at minute resolution from the listed occurrences. They match, and no
  occurrences are duplicated.
- **Load at the bounds.** 20 calendars, 100 masters × COUNT=4000 with 500 range
  components, and 20 windows of 14 days on a 1-minute grid took about 4.4 s.
