import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

UTC=timezone.utc
DAY=timedelta(days=1)


def utc(value):
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00","Z")


def parse_calendar(path):
    lines=[]
    for line in path.read_text().splitlines():
        if line.startswith((" ","\t")):
            lines[-1]+=line[1:]
        else:
            lines.append(line)
    events=[]
    current=None
    for line in lines:
        if line=="BEGIN:VEVENT":
            current={}
        elif line=="END:VEVENT":
            events.append(current)
            current=None
        elif current is not None:
            left,value=line.split(":",1)
            name,*raw=left.split(";")
            params={k:v.strip('"') for k,v in (p.split("=",1) for p in raw)}
            current.setdefault(name,[]).append((params,value))
    return events


def prop(event,name,default=None):
    return event[name][0][1] if name in event else default


def moment(property,zone):
    params,value=property
    if params.get("VALUE")=="DATE" or len(value)==8:
        return datetime.combine(datetime.strptime(value,"%Y%m%d").date(),time(),zone)
    if value.endswith("Z"):
        return datetime.strptime(value,"%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    tz=ZoneInfo(params["TZID"]) if "TZID" in params else zone
    return datetime.strptime(value,"%Y%m%dT%H%M%S").replace(tzinfo=tz,fold=0)


def exists(value):
    roundtrip=value.astimezone(UTC).astimezone(value.tzinfo)
    return roundtrip.replace(tzinfo=None)==value.replace(tzinfo=None)


def duration(event,zone,start,inherited=None):
    if "DURATION" in event:
        match=re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",prop(event,"DURATION"))
        if match is None:
            raise ValueError("Unsupported duration")
        days,hours,minutes,seconds=(int(v or 0) for v in match.groups())
        return "nominal",days,hours*3600+minutes*60+seconds
    if "DTEND" in event:
        end=moment(event["DTEND"][0],zone)
        if event.get("DTSTART",[({},None)])[0][0].get("VALUE")=="DATE":
            return "nominal",(end.date()-start.date()).days,0
        return "elapsed",0,int((end.astimezone(UTC)-start.astimezone(UTC)).total_seconds())
    if inherited is not None:
        return inherited
    if event["DTSTART"][0][0].get("VALUE")=="DATE":
        return "nominal",1,0
    raise ValueError("Timed master requires duration")


def ending(start,spec):
    kind,days,seconds=spec
    if kind=="nominal":
        start=start+timedelta(days=days)
    return start.astimezone(UTC)+timedelta(seconds=seconds)


def recurrence(master,zone):
    start=moment(master["DTSTART"][0],zone)
    values={}
    if "RRULE" not in master:
        values[start.astimezone(UTC)]=start
    else:
        rule=dict(pair.split("=",1) for pair in prop(master,"RRULE").split(";"))
        interval=int(rule.get("INTERVAL",1))
        count=int(rule.get("COUNT",400000))
        until=moment(({},rule["UNTIL"]),zone) if "UNTIL" in rule else None
        weekdays=[["MO","TU","WE","TH","FR","SA","SU"].index(d) for d in rule.get(
            "BYDAY",["MO","TU","WE","TH","FR","SA","SU"][start.weekday()]).split(",")]
        day=start.date()
        generated=0
        while generated<count:
            current=datetime.combine(day,start.timetz()).replace(fold=0)
            if until is not None and current.astimezone(UTC)>until.astimezone(UTC):
                break
            delta=(day-start.date()).days
            if rule["FREQ"]=="DAILY":
                allowed=delta%interval==0
            else:
                weeks=((day-timedelta(days=day.weekday()))-
                       (start.date()-timedelta(days=start.weekday()))).days//7
                allowed=weeks%interval==0 and day.weekday() in weekdays
            if allowed and exists(current):
                values[current.astimezone(UTC)]=current
                generated+=1
            day+=DAY
    for params,text in master.get("RDATE",[]):
        for value in text.split(","):
            dt=moment((params,value),zone)
            values[dt.astimezone(UTC)]=dt
    for params,text in master.get("EXDATE",[]):
        for value in text.split(","):
            values.pop(moment((params,value),zone).astimezone(UTC),None)
    return values


def expand(calendar,source,as_of):
    zone=ZoneInfo(calendar["timezone"])
    chosen={}
    for file in calendar["files"]:
        for event in parse_calendar(source/file):
            timestamp=moment(event["DTSTAMP"][0],zone)
            if timestamp>as_of:
                continue
            rid=moment(event["RECURRENCE-ID"][0],zone).astimezone(UTC) if "RECURRENCE-ID" in event else None
            key=prop(event,"UID"),rid
            rank=int(prop(event,"SEQUENCE")),timestamp
            if key not in chosen or rank>chosen[key][0]:
                chosen[key]=rank,event
    results=[]
    for (uid,rid),(_,master) in chosen.items():
        if rid is not None or prop(master,"STATUS")=="CANCELLED":
            continue
        start=moment(master["DTSTART"][0],zone)
        periods=recurrence(master,zone)
        base_duration=duration(master,zone,start)
        current_duration=base_duration
        transparency=prop(master,"TRANSP","OPAQUE")
        shift=timedelta(0)
        for identity,original in sorted(periods.items()):
            override=chosen.get((uid,identity))
            override=override[1] if override else None
            is_range=override is not None and override["RECURRENCE-ID"][0][0].get("RANGE")=="THISANDFUTURE"
            if is_range:
                changed=moment(override["DTSTART"][0],zone)
                shift=(changed.astimezone(start.tzinfo).replace(tzinfo=None)-
                       original.astimezone(start.tzinfo).replace(tzinfo=None))
                current_duration=duration(override,zone,changed,current_duration)
                transparency=prop(override,"TRANSP",transparency)
            actual=original.astimezone(start.tzinfo)+shift
            length=current_duration
            transparent=transparency
            if override is not None:
                if prop(override,"STATUS")=="CANCELLED":
                    continue
                actual=moment(override["DTSTART"][0],zone)
                length=duration(override,zone,actual,current_duration)
                transparent=prop(override,"TRANSP",transparency)
            if transparent=="TRANSPARENT":
                continue
            results.append(dict(calendar=calendar["id"],uid=uid,recurrence_id=stamp(identity),
                                start=stamp(actual),end=stamp(ending(actual,length))))
    return results


def rebuild(source):
    request=json.loads((source/"request.json").read_text())
    manifest=json.loads((source/"manifest.json").read_text())
    occurrences=[o for calendar in manifest["calendars"] for o in expand(calendar,source,utc(request["as_of"]))]
    bookings,availability={"windows":[]},{"windows":[]}
    for window in request["windows"]:
        start,end=utc(window["start"]),utc(window["end"])
        selected=[o for o in occurrences if o["calendar"] in window["calendars"]
                  and utc(o["start"])<end and utc(o["end"])>start]
        merged=[]
        for a,b in sorted((max(start,utc(o["start"])),min(end,utc(o["end"]))) for o in selected):
            if merged and a<=merged[-1][1]:
                merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:
                merged.append((a,b))
        slots=[]
        clock=start
        length=timedelta(minutes=window["duration_minutes"])
        step=timedelta(minutes=window["grid_minutes"])
        while clock+length<=end:
            finish=clock+length
            if all(finish<=a or clock>=b for a,b in merged):
                slots.append(dict(start=stamp(clock),end=stamp(finish)))
            clock+=step
        bookings["windows"].append(dict(id=window["id"],occurrences=selected,
                                        busy=[dict(start=stamp(a),end=stamp(b)) for a,b in merged]))
        availability["windows"].append(dict(id=window["id"],slots=slots))
    return bookings,availability


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    bookings,availability=rebuild(args.source)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"bookings.json").write_text(json.dumps(bookings,indent=2)+"\n")
    (args.output/"availability.json").write_text(json.dumps(availability,indent=2)+"\n")
