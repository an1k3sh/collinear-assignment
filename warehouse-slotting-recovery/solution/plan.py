import argparse
import csv
import json
from pathlib import Path
import subprocess
import tempfile


def rows(data,name):
    with (data/name).open() as f:
        return list(csv.DictReader(f))


def run(data,output,seed):
    skus=rows(data,"skus.csv")
    slots=rows(data,"slots.csv")
    settings=json.loads((data/"settings.json").read_text())
    sku_index={r["sku"]:i for i,r in enumerate(skus)}
    slot_index={r["slot"]:i for i,r in enumerate(slots)}
    n=len(skus)
    baseline={r["sku"]:r["slot"] for r in rows(data,"baseline.csv")}
    cost=[[0]*n for _ in range(n)]
    distances=[[0]*n for _ in range(n)]
    for row in rows(data,"transitions.csv"):
        i,j=sku_index[row["from_sku"]],sku_index[row["to_sku"]]
        cost[i][j]+=int(row["traversals"])
        cost[j][i]+=int(row["traversals"])
    for row in rows(data,"distances.csv"):
        distances[slot_index[row["from_slot"]]][slot_index[row["to_slot"]]]=int(row["ticks"])
    vectors=[[int(r["zone"]) for r in skus],[int(r["fixed"]) for r in skus],
             [int(r["move_minutes"]) for r in skus],
             [slot_index[baseline[r["sku"]]] for r in skus]]
    text=f"{n} {settings['relocation_budget_minutes']} {settings['max_travel_ticks']}\n"
    for values in vectors+cost+distances:
        text+=" ".join(map(str,values))+"\n"
    with tempfile.TemporaryDirectory() as tmp:
        executable=Path(tmp)/"search"
        subprocess.run(["g++","-O3","-std=c++17",str(Path(__file__).with_name("search.cpp")),"-o",str(executable)],check=True)
        process=subprocess.run([str(executable),str(seed)],input=text,text=True,capture_output=True,timeout=1200)
        print(process.stderr)
        if process.returncode:
            raise RuntimeError(f"Search has not met the target: {process.stdout}")
    lines=process.stdout.splitlines()
    travel,labor=map(int,lines[0].split())
    permutation=list(map(int,lines[1].split()))
    result=dict(assignments=[dict(sku=r["sku"],slot=slots[permutation[i]]["slot"]) for i,r in enumerate(skus)],
                metrics=dict(travel_ticks=travel,relocation_minutes=labor))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result["metrics"]))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=7341)
    args=parser.parse_args()
    run(args.data,args.output,args.seed)
