import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))
from cases import all_cases,expected_exports,iso,instant,source_files

cases={c["name"]:c for c in all_cases()}
names=["spring_gap_count","autumn_first_fold","half_hour_gap","range_wall_shift_across_dst",
       "range_displacements_do_not_compound","single_override_inherits_range_duration",
       "transparent_master_opaque_override","default_all_day_duration","sequence_precedes_timestamp",
       "rdate_exdate_original_set","floating_uses_calendar_zone","cancelled_master_blocks_detached"]
ids=["001","01","1","020","20","002","A","B","C","D","E","F"]
calendars=[]
truth=[]
for name,key in zip(names,ids):
    case=cases[name]
    calendars.append(dict(case["calendars"][0],id=key))
    truth.extend(dict(row,calendar=key) for row in case["expected"])
windows=[]
for key,a,b in [
    ("spring","20260306T000000Z","20260312T000000Z"),
    ("europe","20260328T000000Z","20260331T000000Z"),
    ("summer","20260701T000000Z","20260706T000000Z"),
    ("southern","20261002T000000Z","20261007T000000Z"),
    ("autumn","20261031T000000Z","20261103T000000Z")]:
    windows.append(dict(id=key,start=iso(instant(a)),end=iso(instant(b)),calendars=ids,
                        duration_minutes=45,grid_minutes=30))
request=dict(as_of="2027-01-01T00:00:00Z",windows=windows)
source_files(ROOT/"environment/app/input",calendars,request)
bookings,availability=expected_exports(request,truth)
(ROOT/"tests/seed_expected.json").write_text(json.dumps(dict(bookings=bookings,availability=availability),indent=2)+"\n")
print(f"Created {len(calendars)} source calendars; {len(all_cases())} independent behavioral cases")
