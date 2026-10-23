#!/usr/bin/env python3
"""Reproducible reslotting search: builds QAP matrices from /app/data, runs the
C++ simulated-annealing core (sa.cpp) over several seeds, keeps the best
feasible layout, recomputes metrics independently and writes layout.json."""
import argparse, csv, json, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent

def rows(p):
    with open(p) as f:
        return list(csv.DictReader(f))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("/app/data"))
    ap.add_argument("--out", type=Path, default=HERE / "layout.json")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6, 7, 8])
    ap.add_argument("--iters", type=int, default=20_000_000)
    ap.add_argument("--restarts", type=int, default=2)
    ap.add_argument("--t0", type=float, default=10000.0, help="initial SA temperature")
    ap.add_argument("--t1", type=float, default=2.0, help="final SA temperature")
    a = ap.parse_args()

    settings = json.loads((a.data / "settings.json").read_text())
    skus = rows(a.data / "skus.csv"); slots = rows(a.data / "slots.csv")
    baseline = {r["sku"]: r["slot"] for r in rows(a.data / "baseline.csv")}
    si = {r["sku"]: i for i, r in enumerate(skus)}
    li = {r["slot"]: i for i, r in enumerate(slots)}
    n = len(skus)
    F = [[0] * n for _ in range(n)]
    for r in rows(a.data / "transitions.csv"):
        F[si[r["from_sku"]]][si[r["to_sku"]]] += int(r["traversals"])
    D = [[0] * n for _ in range(n)]
    for r in rows(a.data / "distances.csv"):
        D[li[r["from_slot"]]][li[r["to_slot"]]] = int(r["ticks"])

    inp = [f"{n} {settings['relocation_budget_minutes']}"]
    inp += [f"{r['zone']} {r['fixed']} {r['move_minutes']} {li[baseline[r['sku']]]}" for r in skus]
    inp += [r["zone"] for r in slots]
    inp += [" ".join(map(str, row)) for row in F] + [" ".join(map(str, row)) for row in D]
    inp = "\n".join(inp) + "\n"

    (HERE / "sa_input.txt").write_text(inp)
    exe = HERE / "sa"
    subprocess.run(["g++", "-O2", "-o", str(exe), str(HERE / "sa.cpp")], check=True)
    best = None
    for s in a.seeds:
        out = subprocess.run([str(exe), str(s), str(a.iters), str(a.restarts), str(a.t0), str(a.t1)],
                             input=inp, capture_output=True, text=True, check=True).stdout.split()
        c, lab, perm = int(out[0]), int(out[1]), list(map(int, out[2:]))
        print(f"seed {s}: travel={c} labor={lab}")
        if best is None or c < best[0]:
            best = (c, lab, perm, s)

    c, _, perm, seed = best
    assign = {skus[i]["sku"]: slots[perm[i]]["slot"] for i in range(n)}
    # independent recomputation of metrics
    dist = {(r["from_slot"], r["to_slot"]): int(r["ticks"]) for r in rows(a.data / "distances.csv")}
    travel = sum(int(r["traversals"]) * dist[assign[r["from_sku"]], assign[r["to_sku"]]]
                 for r in rows(a.data / "transitions.csv"))
    labor = sum(int(r["move_minutes"]) for r in skus if assign[r["sku"]] != baseline[r["sku"]])
    assert travel == c
    layout = {"assignments": [{"sku": k, "slot": v} for k, v in assign.items()],
              "metrics": {"travel_ticks": travel, "relocation_minutes": labor},
              "search": {"method": "simulated annealing, zone-preserving swaps, hard labor cap",
                         "best_seed": seed, "iters": a.iters, "restarts": a.restarts, "t0": a.t0, "t1": a.t1, "seeds": a.seeds}}
    a.out.write_text(json.dumps(layout, indent=1) + "\n")
    print(f"best seed {seed}: travel={travel} (target {settings['max_travel_ticks']}, "
          f"baseline {settings['baseline_travel_ticks']}) labor={labor}/{settings['relocation_budget_minutes']}")

if __name__ == "__main__":
    main()
