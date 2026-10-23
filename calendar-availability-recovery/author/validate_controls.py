from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))
from cases import all_cases,expected_exports,request_for
from grade import compare

cases={c["name"]:c for c in all_cases()}
results={}


def assess(name,case_name,change,accepted):
    case=cases[case_name]
    reference=expected_exports(request_for(case),case["expected"])
    actual=deepcopy(reference)
    change(*actual)
    try:
        compare(*actual,*reference)
        result,error=True,None
    except AssertionError as exc:
        result,error=False,str(exc)
    results[name]=dict(accepted=result,expected=accepted,error=error)
    assert result==accepted, f"{name}: {results[name]}"


def offset_strings(bookings,availability):
    for document in (bookings,availability):
        document["windows"].reverse()
        for window in document["windows"]:
            for name in ("occurrences","busy","slots"):
                for row in window.get(name,[]):
                    for field in ("recurrence_id","start","end"):
                        if field in row:
                            row[field]=datetime.fromisoformat(row[field].replace("Z","+00:00")).astimezone(
                                timezone(timedelta(hours=2))).isoformat()
                if name in window:
                    window[name].reverse()


def move_identity(bookings,availability):
    for row in bookings["windows"][0]["occurrences"]:
        row["recurrence_id"]=row["start"]


def lose_occurrence(bookings,availability):
    bookings["windows"][0]["occurrences"].pop()


def shift_hours(bookings,availability):
    row=bookings["windows"][0]["occurrences"][-1]
    for field in ("start","end"):
        value=datetime.fromisoformat(row[field].replace("Z","+00:00"))+timedelta(hours=1)
        row[field]=value.isoformat()


def extend_end(bookings,availability):
    row=bookings["windows"][0]["occurrences"][0]
    row["end"]=(datetime.fromisoformat(row["end"].replace("Z","+00:00"))+timedelta(hours=1)).isoformat()


def unclipped_union(bookings,availability):
    bookings["windows"][0]["busy"][0]["start"]=bookings["windows"][0]["occurrences"][0]["start"]


assess("valid_offset_timestamps_and_reordering","range_wall_shift_across_dst",offset_strings,True)
assess("valid_empty_calendar","orphan_detached",lambda b,a:None,True)
assess("count_consumed_by_nonexistent_local_time","spring_gap_count",lose_occurrence,False)
assess("half_hour_transition_mishandled","half_hour_gap",shift_hours,False)
assess("moved_instance_identity_replaced","moved_into_window",move_identity,False)
assess("range_shift_as_elapsed_day","range_wall_shift_across_dst",shift_hours,False)
assess("range_shifts_compounded","range_displacements_do_not_compound",shift_hours,False)
assess("nominal_day_as_24_hours","nominal_day",extend_end,False)
assess("all_day_dst_duration_wrong","all_day_spring",extend_end,False)
assess("transparent_master_override_lost","transparent_master_opaque_override",lose_occurrence,False)
assess("busy_union_not_clipped","adjacent_and_clipped",unclipped_union,False)
assess("valid_slot_missing","floating_uses_calendar_zone",
       lambda b,a:a["windows"][0]["slots"].clear(),False)
target=ROOT/"evidence/controls.json"
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(results,indent=2)+"\n")
print(f"{len(results)} controls classified as expected")
