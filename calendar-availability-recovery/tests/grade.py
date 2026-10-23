from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import traceback

from cases import all_cases,expected_exports,request_for,source_files

ROOT=Path("/app")
LOGS=Path("/logs/verifier")
details={}


def normalized_time(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    assert dt.tzinfo is not None, "Timestamp lacks UTC offset"
    return dt.timestamp()


def normalized(document,field):
    windows=document["windows"]
    assert len({w["id"] for w in windows})==len(windows), "Duplicate output window"
    result={}
    for window in windows:
        entries=[]
        for row in window[field]:
            times=tuple(normalized_time(row[k]) for k in ("start","end"))
            if field=="occurrences":
                entries.append((row["calendar"],row["uid"],normalized_time(row["recurrence_id"]),*times))
            else:
                entries.append(times)
        result[window["id"]]=Counter(entries)
    return result


def compare(bookings,availability,expected_bookings,expected_availability):
    for actual,reference,field in [
        (bookings,expected_bookings,"occurrences"),(bookings,expected_bookings,"busy"),
        (availability,expected_availability,"slots")]:
        a,b=normalized(actual,field),normalized(reference,field)
        assert set(a)==set(b), f"{field}: output window coverage mismatch"
        for key in b:
            missing=b[key]-a[key]
            extra=a[key]-b[key]
            assert not missing and not extra, f"{key}/{field}: missing {list(missing.items())[:8]}, extra {list(extra.items())[:8]}"


def execute(source,output):
    process=subprocess.run(["python",str(ROOT/"submission/rebuild.py"),"--source",str(source),
                            "--output",str(output)],cwd=source.parent,capture_output=True,text=True,timeout=30)
    assert process.returncode==0, "Exporter failed: "+process.stderr[-4000:]
    return json.loads((output/"bookings.json").read_text()),json.loads((output/"availability.json").read_text())


def integrity():
    for name,digest in json.loads(Path("/tests/protected.json").read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, "Input changed: "+name
    assert (ROOT/"submission/REPORT.md").read_text().strip(), "Missing handover"


def delivered():
    expected=json.loads(Path("/tests/seed_expected.json").read_text())
    compare(json.loads((ROOT/"submission/bookings.json").read_text()),
            json.loads((ROOT/"submission/availability.json").read_text()),
            expected["bookings"],expected["availability"])


def run_case(case):
    request=request_for(case)
    expected=expected_exports(request,case["expected"])
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        source=folder/"feeds"
        source_files(source,case["calendars"],request)
        compare(*execute(source,folder/"export"),*expected)


def check(name,function):
    try:
        function()
        details[name]={"passed":True}
    except Exception:
        details[name]={"passed":False,"error":traceback.format_exc()}


if __name__=="__main__":
    LOGS.mkdir(parents=True,exist_ok=True)
    check("input_integrity",integrity)
    check("delivered",delivered)
    for case in all_cases():
        check(case["name"],lambda case=case:run_case(case))
    rewards={k:float(v["passed"]) for k,v in details.items()}
    rewards["overall"]=float(all(rewards.values()))
    (LOGS/"details.json").write_text(json.dumps(details,indent=2)+"\n")
    (LOGS/"reward.json").write_text(json.dumps(rewards,indent=2)+"\n")
    print(json.dumps(rewards,indent=2))
