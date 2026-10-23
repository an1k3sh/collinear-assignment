import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from ortools.sat.python import cp_model


def rows(data,name):
    with (data/name).open() as f:
        return list(csv.DictReader(f))


def build(data,topology):
    settings=json.loads((data/"settings.json").read_text())
    inventory={}
    for row in rows(data,"cable_versions.csv"):
        if row["recorded_at"] <= settings["planning_cutoff"] and (
            row["cable"] not in inventory or row["recorded_at"] > inventory[row["cable"]]["recorded_at"]
        ):
            inventory[row["cable"]]=row
    nodes=[r["node"] for r in rows(data,"nodes.csv")]
    services=rows(data,"services.csv")
    phases=[r["phase"] for r in rows(data,"phases.csv")]
    outages={(r["phase"],r["cable"]) for r in rows(data,"outages.csv")}
    links={r["cable"]:(r["a"],r["b"]) for r in topology["links"]}
    assert set(links)==set(inventory)
    model=cp_model.CpModel()
    activate={c:model.new_bool_var("activate_"+c) for c,r in inventory.items() if r["status"]=="dark"}
    cost=sum(activate[c]*int(inventory[c]["activation_cents"]) for c in activate)
    model.add(cost<=settings["budget_cents"])
    all_paths={}
    capacity=defaultdict(list)
    arc_variables=[]
    for phase in phases:
        for service in services:
            roles=["primary","secondary"] if service["protection"]=="1+1" else ["primary"]
            risks={}
            for role in roles:
                arcs={}
                incoming,outgoing,groups=defaultdict(list),defaultdict(list),defaultdict(list)
                ranks={n:model.new_int_var(0,len(nodes)-1,f"rank_{phase}_{service['service']}_{role}_{n}") for n in nodes}
                for cable,(a,b) in links.items():
                    row=inventory[cable]
                    if row["status"]=="blocked" or (phase,cable) in outages:
                        continue
                    for u,v in [(a,b),(b,a)]:
                        var=model.new_bool_var(f"{phase}_{service['service']}_{role}_{cable}_{u}")
                        arcs[cable,u,v]=var
                        arc_variables.append(var)
                        incoming[v].append(var)
                        outgoing[u].append(var)
                        groups[row["risk_group"]].append(var)
                        capacity[phase,cable].append(var*int(service["units"]))
                        if cable in activate:
                            model.add(var<=activate[cable])
                        model.add(ranks[v]>=ranks[u]+1).only_enforce_if(var)
                for node in nodes:
                    ins,outs=sum(incoming[node]),sum(outgoing[node])
                    model.add(ins<=1)
                    model.add(outs<=1)
                    if node==service["source"]:
                        model.add(ins==0)
                        model.add(outs==1)
                    elif node==service["target"]:
                        model.add(ins==1)
                        model.add(outs==0)
                    else:
                        model.add(ins==outs)
                for group,variables in groups.items():
                    used=model.new_bool_var(f"risk_{phase}_{service['service']}_{role}_{group}")
                    model.add_max_equality(used,variables)
                    risks[role,group]=used
                all_paths[phase,service["service"],role]=arcs
            if len(roles)==2:
                for group in {g for _,g in risks}:
                    model.add(risks.get(("primary",group),0)+risks.get(("secondary",group),0)<=1)
    for (phase,cable),terms in capacity.items():
        model.add(sum(terms)<=int(inventory[cable]["capacity"]))
    model.minimize(cost*100+sum(arc_variables))
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=4
    solver.parameters.max_time_in_seconds=120
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        raise RuntimeError("No plan found: "+solver.status_name(status))
    result=dict(activate=sorted(c for c,v in activate.items() if solver.value(v)),
                activation_cents=solver.value(cost),phases=[])
    for phase in phases:
        output=dict(phase=phase,routes=[])
        for service in services:
            roles=["primary","secondary"] if service["protection"]=="1+1" else ["primary"]
            for role in roles:
                successors={u:(v,c) for (c,u,v),var in all_paths[phase,service["service"],role].items() if solver.value(var)}
                node=service["source"]
                cables=[]
                while node!=service["target"]:
                    node,cable=successors[node]
                    cables.append(cable)
                output["routes"].append(dict(service=service["service"],role=role,cables=cables))
        result["phases"].append(output)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--topology",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=build(args.data,json.loads(args.topology.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n")
    print(f"Activation cost: {result['activation_cents']} cents")
