import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def rows(data,name):
    with (data/name).open() as f:
        return list(csv.DictReader(f))


def evaluate(data,layout):
    settings=json.loads((data/"settings.json").read_text())
    skus={r["sku"]:r for r in rows(data,"skus.csv")}
    slots={r["slot"]:r for r in rows(data,"slots.csv")}
    baseline={r["sku"]:r["slot"] for r in rows(data,"baseline.csv")}
    entries=layout["assignments"]
    errors=[]
    if Counter(r["sku"] for r in entries)!=Counter({s:1 for s in skus}):
        raise ValueError("Assignment must contain each known SKU exactly once")
    if Counter(r["slot"] for r in entries)!=Counter({s:1 for s in slots}):
        raise ValueError("Assignment must use each known slot exactly once")
    assignment={r["sku"]:r["slot"] for r in entries}
    labor=0
    for sku,slot in assignment.items():
        if skus[sku]["zone"]!=slots[slot]["zone"]:
            errors.append(f"Zone mismatch: {sku} in {slot}")
        if skus[sku]["fixed"]=="1" and slot!=baseline[sku]:
            errors.append(f"Fixed SKU moved: {sku}")
        if slot!=baseline[sku]:
            labor+=int(skus[sku]["move_minutes"])
    distance={(r["from_slot"],r["to_slot"]):int(r["ticks"]) for r in rows(data,"distances.csv")}
    travel=sum(int(r["traversals"])*distance[assignment[r["from_sku"]],assignment[r["to_sku"]]]
               for r in rows(data,"transitions.csv"))
    if labor>settings["relocation_budget_minutes"]:
        errors.append(f"Relocation budget exceeded: {labor}>{settings['relocation_budget_minutes']}")
    if travel>settings["max_travel_ticks"]:
        errors.append(f"Travel target missed: {travel}>{settings['max_travel_ticks']}")
    for name,value in [("travel_ticks",travel),("relocation_minutes",labor)]:
        if type(layout["metrics"][name]) is not int or layout["metrics"][name]!=value:
            errors.append(f"Incorrect reported {name}: {layout['metrics'][name]} != {value}")
    return dict(valid=not errors,travel_ticks=travel,relocation_minutes=labor,
                target=settings["max_travel_ticks"],errors=errors)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--layout",type=Path,required=True)
    args=parser.parse_args()
    try:
        result=evaluate(args.data,json.loads(args.layout.read_text()))
    except (ValueError,KeyError,TypeError) as exc:
        result=dict(valid=False,errors=[str(exc)])
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["valid"] else 1)
