"""Expected instants are independently specified, not obtained from the oracle."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def instant(text):
    return datetime.strptime(text,"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def iso(value):
    return value.isoformat().replace("+00:00","Z")


def event(*lines,uid="event",sequence=1,dtstamp="20260101T000000Z"):
    return "\n".join(["BEGIN:VEVENT","UID:"+uid,"SEQUENCE:"+str(sequence),"DTSTAMP:"+dtstamp,*lines,"END:VEVENT"])


def occurrence(identity,start=None,end=None,minutes=60,uid="event",calendar="room"):
    start=instant(start or identity)
    return dict(calendar=calendar,uid=uid,recurrence_id=iso(instant(identity)),
                start=iso(start),end=iso(instant(end) if end else start+timedelta(minutes=minutes)))


def case(name,components,expected,zone="UTC",bounds=("20260701T000000Z","20260706T000000Z")):
    return dict(name=name,calendars=[dict(id="room",timezone=zone,components=components)],expected=expected,
                bounds=bounds)


def all_cases():
    e,o=event,occurrence
    result=[]
    result.append(case("adjacent_and_clipped",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H",uid="a"),
        e("DTSTART:20260701T100000Z","DURATION:PT1H",uid="b")],
        [o("20260701T090000Z",uid="a"),o("20260701T100000Z",uid="b")],
        bounds=("20260701T093000Z","20260701T113000Z")))
    result.append(case("spring_gap_count",[
        e("DTSTART;TZID=America/New_York:20260307T023000","DURATION:PT30M","RRULE:FREQ=DAILY;COUNT=3")],
        [o(t,minutes=30) for t in ["20260307T073000Z","20260309T063000Z","20260310T063000Z"]],
        zone="America/New_York",bounds=("20260307T000000Z","20260311T000000Z")))
    result.append(case("autumn_first_fold",[
        e("DTSTART;TZID=America/New_York:20261031T013000","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=3")],
        [o(t) for t in ["20261031T053000Z","20261101T053000Z","20261102T063000Z"]],
        zone="America/New_York",bounds=("20261031T000000Z","20261103T000000Z")))
    result.append(case("half_hour_gap",[
        e("DTSTART;TZID=Australia/Lord_Howe:20261003T021500","DURATION:PT30M","RRULE:FREQ=DAILY;COUNT=3")],
        [o(t,minutes=30) for t in ["20261002T154500Z","20261004T151500Z","20261005T151500Z"]],
        zone="Australia/Lord_Howe",bounds=("20261002T000000Z","20261007T000000Z")))
    result.append(case("all_day_spring",[
        e("DTSTART;VALUE=DATE:20260308","DTEND;VALUE=DATE:20260309")],
        [o("20260308T050000Z",end="20260309T040000Z")],
        zone="America/New_York",bounds=("20260308T000000Z","20260310T000000Z")))
    result.append(case("all_day_fall",[
        e("DTSTART;VALUE=DATE:20261101","DTEND;VALUE=DATE:20261102")],
        [o("20261101T040000Z",end="20261102T050000Z")],
        zone="America/New_York",bounds=("20261101T000000Z","20261103T000000Z")))
    for duration,end,label in [("P1D","20260308T160000Z","nominal_day"),
                               ("PT24H","20260308T170000Z","elapsed_day"),
                               ("P1DT2H30M","20260308T183000Z","mixed_duration")]:
        result.append(case(label,[e("DTSTART;TZID=America/New_York:20260307T120000","DURATION:"+duration)],
                           [o("20260307T170000Z",end=end)],zone="America/New_York",
                           bounds=("20260307T000000Z","20260309T000000Z")))
    result.append(case("dtend_elapsed_recurrence",[
        e("DTSTART;TZID=America/New_York:20260307T120000","DTEND;TZID=America/New_York:20260308T120000",
          "RRULE:FREQ=DAILY;COUNT=2")],
        [o("20260307T170000Z",end="20260308T160000Z"),o("20260308T160000Z",end="20260309T150000Z")],
        zone="America/New_York",bounds=("20260307T000000Z","20260310T000000Z")))
    result.append(case("rdate_exdate_original_set",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=3",
          "RDATE:20260702T090000Z,20260705T090000Z","RDATE:20260705T090000Z",
          "EXDATE:20260702T090000Z")],
        [o(t) for t in ["20260701T090000Z","20260703T090000Z","20260705T090000Z"]]))
    result.append(case("sequence_precedes_timestamp",[
        e("DTSTART:20260701T100000Z","DURATION:PT1H",sequence=9,dtstamp="20260102T000000Z"),
        e("DTSTART:20260701T110000Z","DURATION:PT1H",sequence=8,dtstamp="20260601T000000Z"),
        e("DTSTART:20260701T120000Z","DURATION:PT1H",sequence=10,dtstamp="20270102T000000Z")],
        [o("20260701T100000Z")]))
    result.append(case("same_sequence_timestamp",[
        e("DTSTART:20260701T120000Z","DURATION:PT1H",sequence=2,dtstamp="20260103T000000Z"),
        e("DTSTART:20260701T110000Z","DURATION:PT1H",sequence=2,dtstamp="20260102T000000Z")],
        [o("20260701T120000Z")]))
    result.append(case("cancelled_master_blocks_detached",[
        e("DTSTART:20260701T100000Z","DURATION:PT1H"),
        e("STATUS:CANCELLED",sequence=2),
        e("RECURRENCE-ID:20260701T100000Z","DTSTART:20260701T130000Z","DURATION:PT1H",sequence=3)],[]))
    result.append(case("cancel_one_instance",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=3"),
        e("RECURRENCE-ID:20260702T090000Z","STATUS:CANCELLED",sequence=2)],
        [o("20260701T090000Z"),o("20260703T090000Z")]))
    result.append(case("moved_into_window",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=2"),
        e("RECURRENCE-ID:20260701T090000Z","DTSTART:20260703T090000Z",sequence=2)],
        [o("20260701T090000Z",start="20260703T090000Z"),o("20260702T090000Z")],
        bounds=("20260703T080000Z","20260703T120000Z")))
    result.append(case("moved_out_of_window",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H"),
        e("RECURRENCE-ID:20260701T090000Z","DTSTART:20260702T090000Z",sequence=2)],
        [o("20260701T090000Z",start="20260702T090000Z")],
        bounds=("20260701T000000Z","20260702T000000Z")))
    result.append(case("range_wall_shift_across_dst",[
        e("DTSTART;TZID=America/New_York:20260306T090000","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=5"),
        e("RECURRENCE-ID;TZID=America/New_York;RANGE=THISANDFUTURE:20260307T090000",
          "DTSTART;TZID=America/New_York:20260308T090000",sequence=2)],
        [o("20260306T140000Z"),o("20260307T140000Z",start="20260308T130000Z"),
         o("20260308T130000Z",start="20260309T130000Z"),o("20260309T130000Z",start="20260310T130000Z"),
         o("20260310T130000Z",start="20260311T130000Z")],
        zone="America/New_York",bounds=("20260306T000000Z","20260312T000000Z")))
    result.append(case("range_displacements_do_not_compound",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=5"),
        e("RECURRENCE-ID;RANGE=THISANDFUTURE:20260702T090000Z","DTSTART:20260702T100000Z",sequence=2),
        e("RECURRENCE-ID;RANGE=THISANDFUTURE:20260704T090000Z","DTSTART:20260704T080000Z",sequence=3)],
        [o("20260701T090000Z"),o("20260702T090000Z",start="20260702T100000Z"),
         o("20260703T090000Z",start="20260703T100000Z"),o("20260704T090000Z",start="20260704T080000Z"),
         o("20260705T090000Z",start="20260705T080000Z")]))
    result.append(case("single_override_inherits_range_duration",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=4"),
        e("RECURRENCE-ID;RANGE=THISANDFUTURE:20260702T090000Z","DTSTART:20260702T100000Z","DURATION:PT2H",sequence=2),
        e("RECURRENCE-ID:20260703T090000Z","DTSTART:20260703T120000Z",sequence=3)],
        [o("20260701T090000Z"),o("20260702T090000Z",start="20260702T100000Z",minutes=120),
         o("20260703T090000Z",start="20260703T120000Z",minutes=120),
         o("20260704T090000Z",start="20260704T100000Z",minutes=120)]))
    result.append(case("transparent_master_opaque_override",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=3","TRANSP:TRANSPARENT"),
        e("RECURRENCE-ID:20260702T090000Z","DTSTART:20260702T110000Z","TRANSP:OPAQUE",sequence=2)],
        [o("20260702T090000Z",start="20260702T110000Z")]))
    result.append(case("range_transparency_inheritance",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=5"),
        e("RECURRENCE-ID;RANGE=THISANDFUTURE:20260702T090000Z","DTSTART:20260702T100000Z","TRANSP:TRANSPARENT",sequence=2),
        e("RECURRENCE-ID:20260703T090000Z","DTSTART:20260703T090000Z","TRANSP:OPAQUE",sequence=3),
        e("RECURRENCE-ID;RANGE=THISANDFUTURE:20260704T090000Z","DTSTART:20260704T110000Z","TRANSP:OPAQUE",sequence=4)],
        [o("20260701T090000Z"),o("20260703T090000Z"),o("20260704T090000Z",start="20260704T110000Z"),
         o("20260705T090000Z",start="20260705T110000Z")]))
    result.append(case("default_all_day_duration",[
        e("DTSTART;VALUE=DATE:20260329")],[o("20260328T230000Z",end="20260329T220000Z")],
        zone="Europe/Berlin",bounds=("20260328T000000Z","20260331T000000Z")))
    result.append(case("floating_uses_calendar_zone",[
        e("DTSTART:20260701T090000","DURATION:PT1H")],[o("20260701T070000Z")],zone="Europe/Berlin"))
    for suffix in ("COUNT=4","UNTIL=20260318T130000Z"):
        result.append(case("weekly_"+suffix.split("=")[0].lower(),[
            e("DTSTART;TZID=America/New_York:20260302T090000","DURATION:PT1H",
              "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;"+suffix)],
            [o(t) for t in ["20260302T140000Z","20260304T140000Z","20260316T130000Z","20260318T130000Z"]],
            zone="America/New_York",bounds=("20260315T000000Z","20260320T000000Z")))
    result.append(case("all_day_until_inclusive",[
        e("DTSTART;VALUE=DATE:20260308","RRULE:FREQ=DAILY;UNTIL=20260310")],
        [o("20260308T050000Z",end="20260309T040000Z"),o("20260309T040000Z",end="20260310T040000Z"),
         o("20260310T040000Z",end="20260311T040000Z")],
        zone="America/New_York",bounds=("20260308T000000Z","20260312T000000Z")))
    result.append(case("rdate_in_utc",[
        e("DTSTART;TZID=America/New_York:20260701T090000","DURATION:PT1H","RDATE:20260702T120000Z")],
        [o("20260701T130000Z"),o("20260702T120000Z")],zone="America/New_York"))
    result.append(case("unfold_and_quoted_tzid",[
        e('DTSTART;TZID="Europe/Berlin":20260601T090000',"DURATION:PT1H",
          "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO,\n WE,FR")],
        [o(t) for t in ["20260601T070000Z","20260603T070000Z","20260605T070000Z"]],
        zone="Europe/Berlin",bounds=("20260601T000000Z","20260606T000000Z")))
    result.append(case("component_sequence_independent",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H",sequence=10),
        e("RECURRENCE-ID:20260701T090000Z","DTSTART:20260701T110000Z",sequence=1)],
        [o("20260701T090000Z",start="20260701T110000Z")]))
    result.append(case("excluded_identity_not_revived",[
        e("DTSTART:20260701T090000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=2","EXDATE:20260702T090000Z"),
        e("RECURRENCE-ID:20260702T090000Z","DTSTART:20260704T090000Z",sequence=2)],
        [o("20260701T090000Z")]))
    result.append(case("orphan_detached",[
        e("RECURRENCE-ID:20260701T090000Z","DTSTART:20260701T110000Z","DURATION:PT1H")],[]))
    separate=case("calendar_namespaces",[],[
        o("20260701T090000Z",calendar="001"),o("20260701T100000Z",calendar="01")])
    separate["calendars"]=[
        dict(id="001",timezone="UTC",components=[e("DTSTART:20260701T090000Z","DURATION:PT1H")]),
        dict(id="01",timezone="UTC",components=[e("DTSTART:20260701T100000Z","DURATION:PT1H")])]
    result.append(separate)
    return result


def source_files(folder,calendars,request):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    manifest={"calendars":[]}
    for i,calendar in enumerate(calendars):
        files=[]
        # Separate component revisions across independently ordered transport files.
        for j in range(2):
            file=f"export-{i}-{j}.ics"
            components=calendar["components"][j::2]
            text="BEGIN:VCALENDAR\nVERSION:2.0\n"+"\n".join(components)+"\nEND:VCALENDAR\n"
            (folder/file).write_bytes(text.replace("\n","\r\n").encode())
            files.append(file)
        manifest["calendars"].append({k:calendar[k] for k in ("id","timezone")}|{"files":files})
    (folder/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    (folder/"request.json").write_text(json.dumps(request,indent=2)+"\n")


def request_for(case):
    return dict(as_of="2027-01-01T00:00:00Z",windows=[
        dict(id="W",start=iso(instant(case["bounds"][0])),end=iso(instant(case["bounds"][1])),
             calendars=[c["id"] for c in case["calendars"]],duration_minutes=45,grid_minutes=30)])


def expected_exports(request,occurrences):
    def dt(text):
        return datetime.fromisoformat(text.replace("Z","+00:00"))
    bookings,availability={"windows":[]},{"windows":[]}
    for window in request["windows"]:
        a,b=dt(window["start"]),dt(window["end"])
        selected=[r for r in occurrences if r["calendar"] in window["calendars"] and dt(r["start"])<b and dt(r["end"])>a]
        # Endpoint partitioning independently derives the union from golden intervals.
        boundaries=sorted({a,b}|{max(a,dt(r["start"])) for r in selected}|{min(b,dt(r["end"])) for r in selected})
        pieces=[]
        for left,right in zip(boundaries,boundaries[1:]):
            if any(dt(r["start"])<=left<dt(r["end"]) for r in selected):
                if pieces and pieces[-1]["end"]==iso(left):
                    pieces[-1]["end"]=iso(right)
                else:
                    pieces.append(dict(start=iso(left),end=iso(right)))
        slots=[]
        grid=window["grid_minutes"]*60
        length=window["duration_minutes"]*60
        for seconds in range(0,int((b-a).total_seconds())-length+1,grid):
            start=a+timedelta(seconds=seconds)
            end=start+timedelta(seconds=length)
            if not any(max(start,dt(r["start"]))<min(end,dt(r["end"])) for r in selected):
                slots.append(dict(start=iso(start),end=iso(end)))
        bookings["windows"].append(dict(id=window["id"],occurrences=selected,busy=pieces))
        availability["windows"].append(dict(id=window["id"],slots=slots))
    return bookings,availability
