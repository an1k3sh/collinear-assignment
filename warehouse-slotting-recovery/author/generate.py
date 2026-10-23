import csv
import json
from pathlib import Path
import random

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"environment/app/data"
DATA.mkdir(parents=True,exist_ok=True)
R=random.Random(849305)
N=80
ids=[f"SKU-{n:06}" for n in R.sample(range(100000,999999),N)]
zones=[i%2 for i in range(N)]
fixed=[int(i<8) for i in range(N)]
minutes=[R.randint(1,6) for _ in range(N)]
slots=[f"S{i:02}" for i in range(N)]
slot_zones=[(i//10)%2 for i in range(N)]
directed=[[0]*N for _ in range(N)]
for i in range(N):
    for j in range(N):
        if i!=j:
            directed[i][j]=(R.randint(60,160) if i//10==j//10 else R.randint(0,10))
            if abs(i//10-j//10) in (1,7):
                directed[i][j]+=R.randint(0,15)
cost=[[directed[i][j]+directed[j][i] for j in range(N)] for i in range(N)]
distance=[]
for a in range(N):
    aisle,bay=divmod(a,10)
    row=[]
    for b in range(N):
        other,position=divmod(b,10)
        row.append(2*abs(bay-position) if aisle==other else
                   6*abs(aisle-other)+min(2*(bay+position+2),2*(20-bay-position)))
    distance.append(row)
permutation=[None]*N
for zone in (0,1):
    candidates=[j for j in range(N) if slot_zones[j]==zone]
    R.shuffle(candidates)
    for i,slot in zip([i for i in range(N) if zones[i]==zone],candidates):
        permutation[i]=slot


def travel(p):
    return sum(cost[i][j]*distance[p[i]][p[j]] for i in range(N) for j in range(i))


def delta(p,i,j):
    return sum((cost[i][k]-cost[j][k])*(distance[p[j]][p[k]]-distance[p[i]][p[k]])
               for k in range(N) if k!=i and k!=j)


steps=0
while True:
    best=(0,None,None)
    for i in range(8,N):
        for j in range(i+1,N):
            if zones[i]==zones[j]:
                change=delta(permutation,i,j)
                if change<best[0]:
                    best=change,i,j
    if best[1] is None:
        break
    _,i,j=best
    permutation[i],permutation[j]=permutation[j],permutation[i]
    steps+=1
baseline_cost=travel(permutation)


def write(name,records):
    with (DATA/name).open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


write("skus.csv",[dict(sku=ids[i],zone=str(zones[i]),move_minutes=minutes[i],fixed=fixed[i]) for i in range(N)])
write("slots.csv",[dict(slot=slots[i],zone=str(slot_zones[i]),aisle=i//10,bay=i%10) for i in range(N)])
write("baseline.csv",[dict(sku=ids[i],slot=slots[permutation[i]]) for i in range(N)])
write("transitions.csv",[dict(from_sku=ids[i],to_sku=ids[j],traversals=directed[i][j])
                         for i in range(N) for j in range(N) if directed[i][j]])
write("distances.csv",[dict(from_slot=slots[i],to_slot=slots[j],ticks=distance[i][j]) for i in range(N) for j in range(N)])
(DATA/"settings.json").write_text(json.dumps(dict(baseline_travel_ticks=baseline_cost,
    max_travel_ticks=baseline_cost*98//100,relocation_budget_minutes=200),indent=2)+"\n")
(ROOT/"author/instance.json").write_text(json.dumps(dict(ids=ids,slots=slots,zones=zones,fixed=fixed,
    minutes=minutes,baseline=permutation,cost=cost,distance=distance),indent=2)+"\n")
print(f"Baseline: {baseline_cost}; target {baseline_cost*98//100}; {steps} improving swaps before local minimum")
