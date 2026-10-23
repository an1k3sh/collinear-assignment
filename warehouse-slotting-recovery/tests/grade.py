from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import traceback

ROOT=Path("/app")
LOGS=Path("/logs/verifier")
details={}


def rows(name):
    with (ROOT/"data"/name).open() as f:
        return list(csv.DictReader(f))


def check(name,function):
    try:
        function()
        details[name]={"passed":True}
    except Exception:
        details[name]={"passed":False,"error":traceback.format_exc()}


def integrity():
    for name,digest in json.loads(Path("/tests/protected.json").read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, "Source changed: "+name


def load():
    layout=json.loads((ROOT/"submission/layout.json").read_text())
    skus={r["sku"]:r for r in rows("skus.csv")}
    slots={r["slot"]:r for r in rows("slots.csv")}
    assert Counter(r["sku"] for r in layout["assignments"])==Counter({s:1 for s in skus}), "SKU coverage"
    assert Counter(r["slot"] for r in layout["assignments"])==Counter({s:1 for s in slots}), "Slot bijection"
    assignment={r["sku"]:r["slot"] for r in layout["assignments"]}
    return layout,skus,slots,assignment


def placement():
    layout,skus,slots,assignment=load()
    baseline={r["sku"]:r["slot"] for r in rows("baseline.csv")}
    for sku,slot in assignment.items():
        assert skus[sku]["zone"]==slots[slot]["zone"], "Incompatible zone: "+sku
        assert skus[sku]["fixed"]!="1" or slot==baseline[sku], "Fixed SKU moved: "+sku


def labor():
    layout,skus,slots,assignment=load()
    baseline={r["sku"]:r["slot"] for r in rows("baseline.csv")}
    value=sum(int(skus[s]["move_minutes"]) for s in skus if assignment[s]!=baseline[s])
    settings=json.loads((ROOT/"data/settings.json").read_text())
    assert value<=settings["relocation_budget_minutes"], f"Labor {value} exceeds authorization"
    assert type(layout["metrics"]["relocation_minutes"]) is int and layout["metrics"]["relocation_minutes"]==value


def quality():
    layout,skus,slots,assignment=load()
    distance={(r["from_slot"],r["to_slot"]):int(r["ticks"]) for r in rows("distances.csv")}
    total=0
    for row in rows("transitions.csv"):
        total+=int(row["traversals"])*distance[assignment[row["from_sku"]],assignment[row["to_sku"]]]
    settings=json.loads((ROOT/"data/settings.json").read_text())
    assert type(layout["metrics"]["travel_ticks"]) is int and layout["metrics"]["travel_ticks"]==total, "Reported travel differs from saved layout"
    assert total<=settings["max_travel_ticks"], f"Travel {total} exceeds target {settings['max_travel_ticks']}"


def artifacts():
    assert (ROOT/"submission/REPORT.md").read_text().strip(), "Missing reproducibility report"
    assert list((ROOT/"submission").glob("*.py")) or list((ROOT/"submission").glob("*.cpp")), "Missing search/analysis source"


if __name__=="__main__":
    LOGS.mkdir(parents=True,exist_ok=True)
    for name,function in [("input_integrity",integrity),("assignment",load),("placement",placement),
                          ("relocation_budget",labor),("travel_target",quality),("artifacts",artifacts)]:
        check(name,function)
    rewards={k:float(v["passed"]) for k,v in details.items()}
    rewards["overall"]=float(all(rewards.values()))
    (LOGS/"reward.json").write_text(json.dumps(rewards,indent=2)+"\n")
    (LOGS/"details.json").write_text(json.dumps(details,indent=2)+"\n")
    print(json.dumps(rewards,indent=2))
