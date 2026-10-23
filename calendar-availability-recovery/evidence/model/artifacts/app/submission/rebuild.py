#!/usr/bin/env python3
"""Rebuild booking availability exports from iCalendar feeds.

Implements the supported subset described in docs/feed-contract.md and
docs/export-contract.md:

* RFC 5545 line unfolding, quoted parameters, CRLF/LF;
* revision selection per (calendar, UID, RECURRENCE-ID instant) bounded by
  ``as_of`` (greatest SEQUENCE, then greatest DTSTAMP);
* DAILY/WEEKLY RRULE (INTERVAL, BYDAY, COUNT, UNTIL) expanded in local wall
  clock time, skipping nonexistent local times without consuming COUNT;
* RDATE/EXDATE, single-instance overrides/cancellations and
  RANGE=THISANDFUTURE wall-clock displacements;
* elapsed (DTEND) versus nominal-day (DURATION / all-day) durations;
* per-instance TRANSP resolution, busy unions and grid-aligned free slots.
"""

import argparse
import bisect
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
UTC_ZONE = ZoneInfo("UTC")
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

_ZONES = {}


def get_zone(name):
    zone = _ZONES.get(name)
    if zone is None:
        zone = ZoneInfo(name)
        _ZONES[name] = zone
    return zone


# --------------------------------------------------------------------------
# Local time helpers


def to_instant(naive, zone):
    """Local wall time -> UTC instant, choosing fold=0 for ambiguous times."""
    return naive.replace(tzinfo=zone, fold=0).astimezone(UTC)


def to_local(instant, zone):
    return instant.astimezone(zone).replace(tzinfo=None, fold=0)


def local_exists(naive, zone):
    return to_local(to_instant(naive, zone), zone) == naive


def fmt(instant):
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# --------------------------------------------------------------------------
# Content line parsing


def unfold(text):
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = []
    for raw in re.split(r"\r\n|\n", text):
        if raw.endswith("\r"):
            raw = raw[:-1]
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [line for line in lines if line.strip()]


def parse_content_line(line):
    """Return (NAME, {PARAM: value}, value) honouring quoted parameters."""
    i, n = 0, len(line)
    while i < n and line[i] not in ";:":
        i += 1
    name = line[:i].strip().upper()
    params = {}
    while i < n and line[i] == ";":
        i += 1
        start = i
        while i < n and line[i] not in "=;:":
            i += 1
        pname = line[start:i].strip().upper()
        pvalue = ""
        if i < n and line[i] == "=":
            i += 1
            parts, buf = [], []
            while i < n:
                ch = line[i]
                if ch == '"':
                    i += 1
                    while i < n and line[i] != '"':
                        buf.append(line[i])
                        i += 1
                    i += 1
                    continue
                if ch in ";:":
                    break
                buf.append(ch)
                i += 1
            parts.append("".join(buf))
            pvalue = "".join(parts)
        params[pname] = pvalue
    value = line[i + 1:] if i < n and line[i] == ":" else ""
    return name, params, value


def parse_vevents(text):
    """Return list of VEVENT property dicts: NAME -> [(params, value), ...]."""
    events = []
    stack = []
    current = None
    for line in unfold(text):
        name, params, value = parse_content_line(line)
        if name == "BEGIN":
            comp = value.strip().upper()
            stack.append(comp)
            if comp == "VEVENT" and len(stack) >= 1 and current is None:
                current = {}
                current_depth = len(stack)
            continue
        if name == "END":
            if stack:
                if current is not None and len(stack) == current_depth:
                    events.append(current)
                    current = None
                stack.pop()
            continue
        if current is not None and len(stack) == current_depth:
            current.setdefault(name, []).append((params, value))
    return events


# --------------------------------------------------------------------------
# Value types


class TimeValue:
    """A DATE or DATE-TIME value with its resolved local zone."""

    __slots__ = ("naive", "zone", "is_date", "instant")

    def __init__(self, naive, zone, is_date):
        self.naive = naive
        self.zone = zone
        self.is_date = is_date
        self.instant = to_instant(naive, zone)

    def local_in(self, zone):
        if self.zone.key == zone.key:
            return self.naive
        return to_local(self.instant, zone)


_TIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$")


def parse_time_values(params, value, cal_zone):
    out = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        out.append(parse_time_value(params, item, cal_zone))
    return out


def parse_time_value(params, item, cal_zone):
    m = _TIME_RE.match(item.strip().upper())
    if not m:
        raise ValueError("unsupported time value %r" % item)
    y, mo, d, hh, mi, ss, z = m.groups()
    is_date = hh is None or params.get("VALUE", "").upper() == "DATE"
    if is_date:
        return TimeValue(datetime(int(y), int(mo), int(d)), cal_zone, True)
    naive = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss))
    if z:
        zone = UTC_ZONE
    elif params.get("TZID"):
        zone = get_zone(params["TZID"].strip().strip('"'))
    else:
        zone = cal_zone
    return TimeValue(naive, zone, False)


_DUR_RE = re.compile(
    r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_duration(text):
    """Return (days, seconds): days are nominal local days, seconds elapsed."""
    m = _DUR_RE.match(text.strip().upper())
    if not m or text.strip().upper() in ("P", "PT"):
        raise ValueError("unsupported duration %r" % text)
    sign, w, d, h, mi, s = m.groups()
    days = int(w or 0) * 7 + int(d or 0)
    secs = int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
    if sign == "-":
        days, secs = -days, -secs
    return days, secs


def end_of(start, start_local, zone, spec):
    days, secs = spec
    if days:
        start = to_instant(start_local + timedelta(days=days), zone)
    return start + timedelta(seconds=secs)


# --------------------------------------------------------------------------
# Component model


def first(props, name):
    vals = props.get(name)
    return vals[0] if vals else None


class Component:
    def __init__(self, props, cal_zone):
        self.props = props
        self.cal_zone = cal_zone
        uid = first(props, "UID")
        self.uid = uid[1].strip() if uid else None
        seq = first(props, "SEQUENCE")
        self.sequence = int(seq[1].strip()) if seq and seq[1].strip() else 0
        stamp = first(props, "DTSTAMP")
        self.dtstamp = (parse_time_value(stamp[0], stamp[1], UTC_ZONE).instant
                        if stamp else datetime.min.replace(tzinfo=UTC))
        status = first(props, "STATUS")
        self.cancelled = bool(status and status[1].strip().upper() == "CANCELLED")
        transp = first(props, "TRANSP")
        self.transp = None
        if transp:
            self.transp = transp[1].strip().upper() != "TRANSPARENT"  # True = blocking
        rid = first(props, "RECURRENCE-ID")
        self.rid = None
        self.range = False
        if rid:
            self.rid = parse_time_value(rid[0], rid[1], cal_zone)
            self.range = rid[0].get("RANGE", "").upper() == "THISANDFUTURE"
        dtstart = first(props, "DTSTART")
        self.dtstart = parse_time_value(dtstart[0], dtstart[1], cal_zone) if dtstart else None

    def key(self):
        return self.rid.instant if self.rid is not None else None

    def explicit_duration(self, start=None):
        """Duration spec from DTEND/DURATION relative to DTSTART, or None."""
        start = start if start is not None else self.dtstart
        dtend = first(self.props, "DTEND")
        if dtend is not None:
            end = parse_time_value(dtend[0], dtend[1], self.cal_zone)
            if start is not None and start.is_date and end.is_date:
                return ((end.naive.date() - start.naive.date()).days, 0)
            base = start.instant if start is not None else None
            if base is None:
                return None
            return (0, int((end.instant - base).total_seconds()))
        duration = first(self.props, "DURATION")
        if duration is not None:
            return parse_duration(duration[1])
        return None


# --------------------------------------------------------------------------
# Recurrence expansion


def parse_rrule(value):
    rule = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.strip().upper()] = v.strip()
    return rule


def expand_rrule(rule, dtstart, zone, horizon):
    """Yield local naive original starts produced by the RRULE."""
    freq = rule.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY"):
        raise ValueError("unsupported FREQ %r" % freq)
    interval = int(rule.get("INTERVAL", "1") or 1)
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until_date = until_instant = None
    if "UNTIL" in rule:
        until = parse_time_value({}, rule["UNTIL"], zone)
        if until.is_date:
            until_date = until.naive.date()
        else:
            until_instant = until.instant
    byday = None
    if rule.get("BYDAY"):
        byday = sorted({WEEKDAYS[d.strip().upper()[-2:]]
                        for d in rule["BYDAY"].split(",") if d.strip()})
    all_day = dtstart.is_date
    d0 = dtstart.naive.date()
    t0 = dtstart.naive.time()
    limit = horizon if count is None and until_date is None and until_instant is None else None

    def dates():
        if freq == "DAILY":
            k = 0
            while True:
                d = d0 + timedelta(days=k * interval)
                if byday is None or d.weekday() in byday:
                    yield d
                k += 1
        else:
            days = byday if byday is not None else [d0.weekday()]
            monday = d0 - timedelta(days=d0.weekday())
            w = 0
            while True:
                week = monday + timedelta(weeks=w * interval)
                for wd in days:
                    d = week + timedelta(days=wd)
                    if d >= d0:
                        yield d
                w += 1

    produced = 0
    for d in dates():
        naive = datetime.combine(d, t0)
        if until_date is not None and d > until_date:
            return
        if until_instant is not None and to_instant(naive, zone) > until_instant:
            return
        if limit is not None and d > limit:
            return
        if not all_day and not local_exists(naive, zone):
            continue  # nonexistent local time: omitted, does not consume COUNT
        yield naive
        produced += 1
        if count is not None and produced >= count:
            return


class Occurrence:
    __slots__ = ("calendar", "uid", "rid", "start", "end", "blocking")

    def __init__(self, calendar, uid, rid, start, end, blocking):
        self.calendar, self.uid, self.rid = calendar, uid, rid
        self.start, self.end, self.blocking = start, end, blocking


def expand_series(cal_id, master, detached, horizon):
    """Expand one selected, non-cancelled master with its detached components."""
    dtstart = master.dtstart
    if dtstart is None:
        return []
    zone = dtstart.zone  # the master's timezone (calendar zone for all-day/floating)
    all_day = dtstart.is_date
    master_dur = master.explicit_duration()
    if master_dur is None:
        master_dur = (1, 0) if all_day else (0, 0)
    master_blocking = master.transp if master.transp is not None else True

    # Original recurrence set keyed by original start instant.
    originals = {}
    rrules = master.props.get("RRULE") or []
    if rrules:
        for _, value in rrules[:1]:
            for naive in expand_rrule(parse_rrule(value), dtstart, zone, horizon):
                originals.setdefault(to_instant(naive, zone), naive)
    else:
        originals[dtstart.instant] = dtstart.naive
    for params, value in master.props.get("RDATE") or []:
        for tv in parse_time_values(params, value, master.cal_zone):
            originals.setdefault(tv.instant, tv.local_in(zone))
    for params, value in master.props.get("EXDATE") or []:
        for tv in parse_time_values(params, value, master.cal_zone):
            originals.pop(tv.instant, None)

    singles = {}
    ranges = []
    for comp in detached:
        rid = comp.rid.instant
        if rid not in originals:
            continue
        if comp.range:
            ranges.append(comp)
        else:
            singles[rid] = comp
    ranges.sort(key=lambda c: c.rid.instant)

    # Resolve range states in original order with duration/TRANSP inheritance.
    range_keys, range_states = [], []
    prev_dur, prev_blocking = master_dur, master_blocking
    for comp in ranges:
        if comp.cancelled:
            state = {"cancelled": True}
        else:
            delta = timedelta(0)
            if comp.dtstart is not None:
                delta = comp.dtstart.local_in(zone) - comp.rid.local_in(zone)
            dur = comp.explicit_duration()
            dur = dur if dur is not None else prev_dur
            blocking = comp.transp if comp.transp is not None else prev_blocking
            state = {"cancelled": False, "delta": delta, "dur": dur, "blocking": blocking}
            prev_dur, prev_blocking = dur, blocking
        range_keys.append(comp.rid.instant)
        range_states.append(state)

    out = []
    for orig in sorted(originals):
        orig_local = originals[orig]
        start_local = orig_local
        dur, blocking = master_dur, master_blocking
        idx = bisect.bisect_right(range_keys, orig) - 1
        if idx >= 0:
            state = range_states[idx]
            if state["cancelled"]:
                continue
            start_local = orig_local + state["delta"]
            dur, blocking = state["dur"], state["blocking"]
        start = to_instant(start_local, zone)
        single = singles.get(orig)
        if single is not None:
            if single.cancelled:
                continue
            if single.dtstart is not None:
                # Nominal-day arithmetic is done in the master's timezone.
                start_local = single.dtstart.local_in(zone)
                start = single.dtstart.instant
                own = single.explicit_duration()
            else:
                own = single.explicit_duration(TimeValue(start_local, zone, False))
            if own is not None:
                dur = own
            if single.transp is not None:
                blocking = single.transp
        end = end_of(start, start_local, zone, dur)
        out.append(Occurrence(cal_id, master.uid, orig, start, end, blocking))
    return out


# --------------------------------------------------------------------------
# Feed loading and revision selection


def load_calendar(source, cal, as_of, horizon):
    cal_id = cal["id"]
    cal_zone = get_zone(cal["timezone"])
    selected = {}
    for rel in cal.get("files", []):
        path = os.path.join(source, rel)
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        for props in parse_vevents(text):
            comp = Component(props, cal_zone)
            if comp.uid is None or comp.dtstamp > as_of:
                continue
            key = (comp.uid, comp.key())
            cur = selected.get(key)
            if cur is None or (comp.sequence, comp.dtstamp) > (cur.sequence, cur.dtstamp):
                selected[key] = comp

    by_uid = {}
    for (uid, rid), comp in selected.items():
        entry = by_uid.setdefault(uid, {"master": None, "detached": []})
        if rid is None:
            entry["master"] = comp
        else:
            entry["detached"].append(comp)

    occurrences = []
    for uid, entry in by_uid.items():
        master = entry["master"]
        if master is None or master.cancelled:
            continue
        occurrences.extend(expand_series(cal_id, master, entry["detached"], horizon))
    return occurrences


# --------------------------------------------------------------------------
# Exports


def merge(intervals):
    merged = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    return merged


def free_slots(ws, we, busy, duration, grid):
    slots = []
    step = timedelta(minutes=grid)
    length = timedelta(minutes=duration)
    starts = [b[0] for b in busy]
    s = ws
    while s + length <= we:
        e = s + length
        # busy blocks are disjoint and sorted; check the last block starting before e
        i = bisect.bisect_left(starts, e) - 1
        if i < 0 or busy[i][1] <= s:
            slots.append({"start": fmt(s), "end": fmt(e)})
        s += step
    return slots


def build(source):
    with open(os.path.join(source, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(source, "request.json"), encoding="utf-8") as fh:
        request = json.load(fh)
    as_of = parse_iso(request["as_of"])
    windows = request.get("windows", [])
    latest = max([parse_iso(w["end"]) for w in windows] + [as_of])
    horizon = (latest + timedelta(days=5 * 366)).date()

    needed = {c for w in windows for c in w["calendars"]}
    calendars = {}
    for cal in manifest["calendars"]:
        if cal["id"] in needed:
            calendars[cal["id"]] = load_calendar(source, cal, as_of, horizon)

    bookings, availability = [], []
    for w in windows:
        ws, we = parse_iso(w["start"]), parse_iso(w["end"])
        occs, intervals, seen = [], [], set()
        for cal_id in w["calendars"]:
            if cal_id in seen:
                continue
            seen.add(cal_id)
            for occ in calendars.get(cal_id, []):
                if not occ.blocking or not (occ.start < we and occ.end > ws):
                    continue
                occs.append(occ)
                intervals.append((max(occ.start, ws), min(occ.end, we)))
        occs.sort(key=lambda o: (o.start, o.end, o.calendar, o.uid, o.rid))
        busy = merge(intervals)
        bookings.append({
            "id": w["id"],
            "occurrences": [{
                "calendar": o.calendar, "uid": o.uid, "recurrence_id": fmt(o.rid),
                "start": fmt(o.start), "end": fmt(o.end)} for o in occs],
            "busy": [{"start": fmt(s), "end": fmt(e)} for s, e in busy],
        })
        availability.append({
            "id": w["id"],
            "slots": free_slots(ws, we, busy, int(w["duration_minutes"]),
                                int(w["grid_minutes"])),
        })
    return {"windows": bookings}, {"windows": availability}


def write_json(path, data):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    source = os.path.abspath(args.source)
    output = os.path.abspath(args.output)
    os.makedirs(output, exist_ok=True)
    bookings, availability = build(source)
    write_json(os.path.join(output, "bookings.json"), bookings)
    write_json(os.path.join(output, "availability.json"), availability)
    return 0


if __name__ == "__main__":
    sys.exit(main())
