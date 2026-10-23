import argparse
from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile

TASK=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TASK/"tests"))
from check_plan import Check


def controls(topology,plan):
    data=TASK/"environment/app/data"
    Check(data,topology,plan).all()
    results={"oracle":{"accepted":True}}

    def assess(name,graph,dispatch,expected,method="all",source=data):
        try:
            getattr(Check(source,graph,dispatch),method)()
            accepted,error=True,None
        except AssertionError as exc:
            accepted,error=False,str(exc)
        results[name]=dict(accepted=accepted,expected=expected,error=error)
        assert accepted==expected, f"{name}: {results[name]}"

    alternative=deepcopy(topology)
    alternative["links"].reverse()
    for row in alternative["links"]:
        row["a"],row["b"]=row["b"],row["a"]
    assess("valid_endpoint_orientation_and_order",alternative,plan,True)
    alternative=deepcopy(plan)
    for phase in alternative["phases"]:
        for row in phase["routes"]:
            if row["service"] in ("S1","S2","S3"):
                row["role"]="secondary" if row["role"]=="primary" else "primary"
        phase["routes"].reverse()
    alternative["phases"].reverse()
    assess("valid_protected_role_swap",topology,alternative,True)
    bad=deepcopy(topology)
    bad["links"][0]["a"]=next(r["a"] for r in bad["links"] if r["a"] not in (bad["links"][0]["a"],bad["links"][0]["b"]))
    assess("misread_cable_endpoint",bad,plan,False,"transcription")
    bad=deepcopy(topology)
    bad["links"].pop()
    assess("omitted_unused_cable",bad,plan,False,"transcription")
    bad=deepcopy(plan)
    bad["phases"].pop()
    assess("missing_maintenance_phase",topology,bad,False,"coverage")
    bad=deepcopy(plan)
    bad["phases"][0]["routes"][0]["cables"].reverse()
    assess("noncontiguous_cable_path",topology,bad,False,"connectivity")
    bad=deepcopy(plan)
    bad["activate"]=[]
    assess("dark_cables_used_without_activation",topology,bad,False,"availability")
    checker=Check(data,topology,plan)
    bad=deepcopy(plan)
    phase,cable=next(iter(checker.outages))
    next(p for p in bad["phases"] if p["phase"]==phase)["routes"][0]["cables"].append(cable)
    assess("maintenance_outage_ignored",topology,bad,False,"availability")
    bad=deepcopy(plan)
    blocked=next(c for c,r in checker.inventory.items() if r["status"]=="blocked")
    bad["phases"][0]["routes"][0]["cables"].append(blocked)
    assess("superseded_lit_inventory_used",topology,bad,False,"availability")
    bad=deepcopy(plan)
    bad["activation_cents"]-=1
    assess("incorrect_activation_spend",topology,bad,False,"budget")

    with tempfile.TemporaryDirectory() as tmp:
        source=Path(tmp)/"records"
        shutil.copytree(data,source)
        with (source/"cable_versions.csv").open() as f:
            rows=list(csv.DictReader(f))
        pathset={(r["service"],r["role"]):r["cables"] for r in plan["phases"][0]["routes"]}
        primary,secondary=pathset["S1","primary"],pathset["S1","secondary"]
        assert set(primary).isdisjoint(secondary)
        group=checker.inventory[primary[0]]["risk_group"]
        for row in rows:
            if row["cable"]==secondary[0]:
                row["risk_group"]=group
        with (source/"cable_versions.csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        assess("edge_disjoint_but_shared_failure_domain",topology,plan,False,"protection",source)
        for row in rows:
            if row["cable"]==primary[0]:
                row["capacity"]=1
        with (source/"cable_versions.csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        assess("capacity_exceeded",topology,plan,False,"capacity",source)
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    results=controls(json.loads((TASK/"author/topology.json").read_text()),json.loads(args.plan.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+"\n")
    print(f"{len(results)} controls classified as expected")
