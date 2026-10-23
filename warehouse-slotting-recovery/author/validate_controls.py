import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"environment/app/tools"))
from evaluate import evaluate,rows


def controls(original):
    data=ROOT/"environment/app/data"
    skus={r["sku"]:r for r in rows(data,"skus.csv")}
    base={r["sku"]:r["slot"] for r in rows(data,"baseline.csv")}
    results={}

    def refresh(layout):
        measured=evaluate(data,layout)
        layout["metrics"]={k:measured[k] for k in ("travel_ticks","relocation_minutes")}
        return layout

    def assess(name,layout,expected):
        try:
            result=evaluate(data,layout)
        except ValueError as exc:
            result=dict(valid=False,errors=[str(exc)])
        results[name]=dict(result,expected=expected)
        assert result["valid"]==expected, f"Control {name}: {result}"

    assess("oracle",original,True)
    alternate=None
    records=original["assignments"]
    for i,a in enumerate(records):
        if skus[a["sku"]]["fixed"]=="1":
            continue
        for j in range(i+1,len(records)):
            b=records[j]
            if skus[b["sku"]]["fixed"]=="1" or skus[a["sku"]]["zone"]!=skus[b["sku"]]["zone"]:
                continue
            trial=deepcopy(original)
            trial["assignments"][i]["slot"],trial["assignments"][j]["slot"]=b["slot"],a["slot"]
            refresh(trial)
            if evaluate(data,trial)["valid"]:
                alternate=trial
                break
        if alternate is not None:
            break
    assert alternate is not None, "No distinct passing assignment found"
    alternate["assignments"].reverse()
    assess("valid_different_assignment_and_order",alternate,True)
    bad=dict(assignments=[dict(sku=k,slot=v) for k,v in base.items()],metrics=original["metrics"].copy())
    assess("baseline_misses_required_improvement",refresh(bad),False)
    bad=deepcopy(original)
    bad["assignments"][1]["slot"]=bad["assignments"][0]["slot"]
    assess("two_skus_in_one_slot",bad,False)
    bad=deepcopy(original)
    i=next(i for i,r in enumerate(records) if skus[r["sku"]]["fixed"]=="0")
    j=next(j for j,r in enumerate(records) if skus[r["sku"]]["fixed"]=="0" and skus[r["sku"]]["zone"]!=skus[records[i]["sku"]]["zone"])
    bad["assignments"][i]["slot"],bad["assignments"][j]["slot"]=records[j]["slot"],records[i]["slot"]
    assess("wrong_zone",refresh(bad),False)
    bad=deepcopy(original)
    i=next(i for i,r in enumerate(records) if skus[r["sku"]]["fixed"]=="1")
    j=next(j for j,r in enumerate(records) if skus[r["sku"]]["fixed"]=="0" and skus[r["sku"]]["zone"]==skus[records[i]["sku"]]["zone"])
    bad["assignments"][i]["slot"],bad["assignments"][j]["slot"]=records[j]["slot"],records[i]["slot"]
    assess("fixed_inventory_moved",refresh(bad),False)
    bad=dict(assignments=[dict(sku=k,slot=v) for k,v in base.items()],metrics=original["metrics"].copy())
    for zone in ("0","1"):
        indices=[i for i,r in enumerate(bad["assignments"]) if skus[r["sku"]]["zone"]==zone and skus[r["sku"]]["fixed"]=="0"]
        old=[bad["assignments"][i]["slot"] for i in indices]
        for i,slot in zip(indices,old[1:]+old[:1]):
            bad["assignments"][i]["slot"]=slot
    refresh(bad)
    assert bad["metrics"]["relocation_minutes"]>json.loads((data/"settings.json").read_text())["relocation_budget_minutes"]
    assess("relocation_budget_ignored",bad,False)
    bad=deepcopy(original)
    bad["metrics"]["travel_ticks"]-=1
    assess("reported_score_not_actual_artifact",bad,False)
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--layout",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    results=controls(json.loads(args.layout.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+"\n")
    print(f"{len(results)} controls classified as expected")
