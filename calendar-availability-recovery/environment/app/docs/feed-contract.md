# Supported calendar feed contract

## Source and revision selection

`manifest.json` lists `calendars`, each with a string `id`, an IANA `timezone`
and a list of relative `.ics` `files`. Every file is a VCALENDAR of VEVENTs.
Calendars are independent namespaces. `request.json` supplies a global
`as_of` timestamp and the query windows.

Unfold RFC content lines: a physical line beginning with one space or tab
continues its predecessor after removing that first whitespace character.
CRLF and LF are supported. Property/parameter names are uppercase. Ignore
unneeded properties such as SUMMARY, DESCRIPTION, PRODID and VERSION.
Relevant parameters are TZID, VALUE=DATE and RANGE=THISANDFUTURE. TZID values
may be double-quoted. No embedded VTIMEZONE definitions occur.

Each VEVENT has UID, SEQUENCE (nonnegative integer) and DTSTAMP (UTC).
A component is keyed by `(calendar ID, UID, RECURRENCE-ID)`; the series master
has no RECURRENCE-ID. Discard revisions with DTSTAMP after `as_of`. For each
component, choose greatest SEQUENCE, breaking equal sequences by greatest
DTSTAMP. Distinct versions never tie on both. Arrival/file order does not
matter. Cancellation is a selected state, not a reason to revive an old one.

If the selected master has STATUS:CANCELLED, the entire UID is inactive,
including detached components. Otherwise it has DTSTART and either DTEND or
DURATION (or, for all-day masters only, neither). Detached components without
a selected master are ignored. Confirmed status may be omitted.

## Times and duration

DATE-TIME values have basic form YYYYMMDDTHHMMSS. A trailing Z means UTC.
TZID names a zone; without either, use the manifest calendar's timezone.
DATE values (VALUE=DATE) are all-day dates in the manifest calendar timezone.
RECURRENCE-ID, EXDATE and RDATE use the same time-value forms.

When a local time is ambiguous, choose the FIRST occurrence (fold=0).
A recurrence candidate at a nonexistent local time is omitted and does NOT
consume an RRULE COUNT occurrence. Explicit DTSTART/RDATE/override dates
are valid local times. No fixed one-hour transition size may be assumed.

For a timed component, DTEND establishes an ELAPSED duration: subtract the
two UTC instants, and reuse that many elapsed seconds for every occurrence.
A DURATION value can contain integer days, hours, minutes and seconds in
ISO form, such as P1D, PT24H or P1DT2H30M. Apply DAYS by advancing local
calendar dates first, then apply H/M/S as elapsed seconds. Thus a calendar
day and 24 elapsed hours need not be equal. Source durations are positive.
Day advancement used in these inputs always lands on an existing local time.

For all-day events, DTEND is an exclusive date and establishes the number of
LOCAL calendar days. DURATION may instead supply whole days. With neither,
an all-day event lasts one local calendar day.

## Recurrence set

An optional single RRULE uses FREQ=DAILY or WEEKLY; INTERVAL is 1..12,
default 1. WEEKLY can use comma-separated BYDAY values MO,TU,WE,TH,FR,SA,SU
(no ordinals); absent BYDAY, use DTSTART's weekday. Week starts Monday.
DTSTART always conforms to its rule. No other BY* fields occur.

Every RRULE has either COUNT (1..4000) or UNTIL (at most five years after
DTSTART), not both. UNTIL is inclusive and is UTC for timed events or a DATE
for all-day events. Generated instances retain DTSTART's local clock time,
not a fixed UTC offset. EXDATE removals do not replenish COUNT.

Start with the RRULE occurrences (or just DTSTART when there is no RRULE),
union all comma-separated RDATE values, then remove all EXDATE values.
There may be repeated RDATE/EXDATE properties. Deduplicate by the ORIGINAL
occurrence start instant. All-day original starts mean midnight local time.
RDATE entries are dates/timestamps, not PERIOD values.

## Detached changes

A detached component identifies an ORIGINAL recurrence start with
RECURRENCE-ID, not the new start after moving it. A detached component whose
original instance is not in the recurrence set is ignored.

Without RANGE, a selected STATUS:CANCELLED removes that one instance.
Otherwise DTSTART supplies the replacement start; omitted duration inherits
the currently applicable master/range duration. An explicit override DTEND or
DURATION supplies its own duration. Source noncancelled detached components
have DTSTART.

RANGE=THISANDFUTURE changes that original occurrence and every later ORIGINAL
occurrence until another range component. Its start displacement is a
LOCAL WALL-CLOCK difference between its DTSTART and RECURRENCE-ID in the
master's timezone, not an elapsed UTC difference. Apply that displacement
independently to each later original start. A range's explicit duration
replaces the duration for its suffix; if omitted, inherit the preceding one.
Range displacements do not compound: each is measured against original IDs.
Range components in these inputs are noncancelled and do not move generated
times into gaps.

A single-instance override takes precedence over an applicable earlier range,
but does not change later instances. All identity, COUNT, UNTIL, RDATE and
EXDATE decisions use ORIGINAL starts. Moves can cross query boundaries, so
select an occurrence for a query only after applying the changes.

TRANSP:TRANSPARENT means nonblocking. Resolve TRANSP per instance: use an
explicit single override's value, else the applicable range's value if it
has one, else the inherited preceding range/master value. The default is
OPAQUE. Transparency changes do not remove instances from the recurrence set;
they affect only whether those instances appear in a busy export.
