#!/usr/bin/env python3
"""Rebuild the cold-chain dispatch plan from the depot operating records.

Usage: python build_plan.py --data /app/data --output /app/submission/plan.json
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

from ortools.sat.python import cp_model

DEPOT = "DEPOT"


def ts(value):
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def read_csv(data, name):
    with open(os.path.join(data, name), newline="", encoding="utf-8") as fh:
        return [{k.strip(): (v.strip() if v is not None else v) for k, v in row.items()}
                for row in csv.DictReader(fh)]


def fams(value):
    return set(f for f in value.split("|") if f)


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------
def load_inputs(data):
    with open(os.path.join(data, "settings.json"), encoding="utf-8") as fh:
        settings = json.load(fh)
    cutoff = ts(settings["planning_cutoff"])

    # Orders: latest version known at cutoff per (account, order_id), then filter.
    latest = {}
    for row in read_csv(data, "order_versions.csv"):
        rec = ts(row["recorded_at"])
        if rec > cutoff:
            continue
        key = (row["account"], row["order_id"])
        if key not in latest or rec > latest[key][0]:
            latest[key] = (rec, row)
    roster, excluded = [], []
    for key in sorted(latest):
        row = latest[key][1]
        if row["status"] == "confirmed" and ts(row["effective_at"]) <= cutoff:
            roster.append({
                "account": row["account"], "order_id": row["order_id"], "sku": row["sku"],
                "quantity": int(row["quantity"]), "node": row["node"],
                "open": int(row["open"]), "close": int(row["close"]),
                "service": int(row["service"]),
            })
        else:
            reason = row["status"] if row["status"] != "confirmed" else "not effective at cutoff"
            excluded.append({"account": key[0], "order_id": key[1], "reason": reason})

    skus = {}
    for r in read_csv(data, "skus.csv"):
        skus[r["sku"]] = {"family": r["family"], "pack_base": int(r["pack_base"]),
                          "pack_per_unit": int(r["pack_per_unit"]),
                          "max_unrefrigerated": int(r["max_unrefrigerated"])}

    # Stock: dedupe by (warehouse, event_id), count only movements known at cutoff.
    seen = {}
    for r in read_csv(data, "stock_events.csv"):
        key = (r["warehouse"], r["event_id"])
        if key not in seen:
            seen[key] = r
    balance = {}
    for r in seen.values():
        if ts(r["recorded_at"]) <= cutoff:
            balance[r["lot"]] = balance.get(r["lot"], 0) + int(r["delta"])

    quality = {}
    for r in read_csv(data, "quality_versions.csv"):
        rec = ts(r["recorded_at"])
        if rec > cutoff:
            continue
        if r["lot"] not in quality or rec > quality[r["lot"]][0]:
            quality[r["lot"]] = (rec, r)

    lots = {}
    for r in read_csv(data, "lots.csv"):
        q = quality.get(r["lot"])
        bal = balance.get(r["lot"], 0)
        usable = q is not None and q[1]["status"] == "released" and bal > 0
        lots[r["lot"]] = {"sku": r["sku"], "expiry": int(r["expiry"]), "balance": bal,
                          "status": q[1]["status"] if q else "no disposition",
                          "available": int(q[1]["available"]) if q else None,
                          "usable": usable}

    travel = {}
    for r in read_csv(data, "travel.csv"):
        travel[(r["origin"], r["destination"])] = int(r["minutes"])

    benches = [{"bench": r["bench"], "families": fams(r["families"]),
                "start": int(r["start"]), "end": int(r["end"])}
               for r in read_csv(data, "benches.csv")]
    bench_breaks = [(r["bench"], int(r["start"]), int(r["end"]))
                    for r in read_csv(data, "bench_breaks.csv")]
    dock_breaks = [(int(r["start"]), int(r["end"])) for r in read_csv(data, "dock_breaks.csv")]
    vehicles = []
    for r in read_csv(data, "vehicles.csv"):
        v = {"vehicle": r["vehicle"], "families": fams(r["families"])}
        for k in ("capacity", "max_stops", "max_drive", "start", "end", "turnaround",
                  "max_trips", "hire_cents", "trip_cents", "drive_cents_per_minute"):
            v[k] = int(r[k])
        vehicles.append(v)
    return dict(settings=settings, roster=roster, excluded=excluded, skus=skus, lots=lots,
                travel=travel, benches=benches, bench_breaks=bench_breaks,
                dock_breaks=dock_breaks, vehicles=vehicles)


# --------------------------------------------------------------------------
# CP-SAT model
# --------------------------------------------------------------------------
def solve(inp, time_limit, seed):
    S = inp["settings"]
    H = int(S["horizon"])
    load_base, load_pu = int(S["load_base"]), int(S["load_per_unit"])
    budget = int(S["budget_cents"])
    orders, skus, lots, travel = inp["roster"], inp["skus"], inp["lots"], inp["travel"]
    vehicles, benches = inp["vehicles"], inp["benches"]
    n = len(orders)
    m = cp_model.CpModel()

    fam = [skus[o["sku"]]["family"] for o in orders]
    pdur = [skus[o["sku"]]["pack_base"] + o["quantity"] * skus[o["sku"]]["pack_per_unit"]
            for o in orders]
    maxu = [skus[o["sku"]]["max_unrefrigerated"] for o in orders]
    svc = [o["service"] for o in orders]
    qty = [o["quantity"] for o in orders]
    node = [o["node"] for o in orders]

    # Service start per order (whole service inside [open, close] and horizon)
    sstart = [m.NewIntVar(o["open"], min(o["close"], H) - o["service"], f"s{i}")
              for i, o in enumerate(orders)]
    send = [sstart[i] + svc[i] for i in range(n)]

    # Packing: one nonpreemptive job per order on a compatible bench
    pstart = [m.NewIntVar(0, H, f"ps{i}") for i in range(n)]
    pend = [m.NewIntVar(0, H, f"pe{i}") for i in range(n)]
    bench_iv = {b["bench"]: [] for b in benches}
    bench_lit = {}
    for i in range(n):
        m.Add(pend[i] == pstart[i] + pdur[i])
        m.Add(send[i] - pend[i] <= maxu[i])
        lits = []
        for b in benches:
            if fam[i] not in b["families"]:
                continue
            lit = m.NewBoolVar(f"pb{i}_{b['bench']}")
            m.Add(pstart[i] >= b["start"]).OnlyEnforceIf(lit)
            m.Add(pend[i] <= b["end"]).OnlyEnforceIf(lit)
            iv = m.NewOptionalIntervalVar(pstart[i], pdur[i], pend[i], lit, f"pi{i}_{b['bench']}")
            bench_iv[b["bench"]].append(iv)
            bench_lit[(i, b["bench"])] = lit
            lits.append(lit)
        if not lits:
            raise SystemExit(f"no bench for order {orders[i]}")
        m.AddExactlyOne(lits)
    for bname, s, e in inp["bench_breaks"]:
        if bname in bench_iv and e > s:
            bench_iv[bname].append(m.NewIntervalVar(s, e - s, e, f"bb{bname}{s}"))
    for ivs in bench_iv.values():
        m.AddNoOverlap(ivs)

    # Lot allocation (availability at pack start, expiry at service end, conservation)
    alloc = {}
    for i, o in enumerate(orders):
        terms = []
        for lname, l in lots.items():
            if l["sku"] != o["sku"] or not l["usable"]:
                continue
            q = m.NewIntVar(0, min(qty[i], l["balance"]), f"q{i}_{lname}")
            u = m.NewBoolVar(f"u{i}_{lname}")
            m.Add(q <= qty[i] * u)
            m.Add(q >= 1).OnlyEnforceIf(u)
            m.Add(pstart[i] >= l["available"]).OnlyEnforceIf(u)
            m.Add(send[i] <= l["expiry"]).OnlyEnforceIf(u)
            alloc[(i, lname)] = (q, u)
            terms.append(q)
        m.Add(sum(terms) == qty[i])
    for lname, l in lots.items():
        terms = [alloc[(i, lname)][0] for i in range(n) if (i, lname) in alloc]
        if terms:
            m.Add(sum(terms) <= l["balance"])

    # Trips: one slot per (vehicle, trip index), routed with a circuit constraint.
    dock_iv = []
    trips = []
    assign = [[] for _ in range(n)]
    cost_terms = []
    for v in vehicles:
        vused = m.NewBoolVar(f"vu{v['vehicle']}")
        cost_terms.append(v["hire_cents"] * vused)
        prev = None
        for k in range(v["max_trips"]):
            tid = f"{v['vehicle']}-{k + 1}"
            used = m.NewBoolVar(f"used{tid}")
            m.AddImplication(used, vused)
            y = {}
            arcs = []
            depot_loop = m.NewBoolVar(f"dl{tid}")
            m.Add(depot_loop == used.Not())
            arcs.append((0, 0, depot_loop))
            elig = [i for i in range(n) if fam[i] in v["families"]]
            for i in elig:
                y[i] = m.NewBoolVar(f"y{tid}_{i}")
                assign[i].append((tid, y[i]))
                arcs.append((i + 1, i + 1, y[i].Not()))
                m.AddImplication(y[i], used)
            L = m.NewIntVar(max(0, v["start"]), H, f"L{tid}")
            D = m.NewIntVar(0, H, f"D{tid}")
            R = m.NewIntVar(0, min(H, v["end"]), f"R{tid}")
            load_q = sum(qty[i] * y[i] for i in elig)
            m.Add(load_q <= v["capacity"])
            m.Add(sum(y.values()) <= v["max_stops"])
            m.Add(D == L + load_base + load_pu * load_q)
            m.Add(R >= D)
            dur = m.NewIntVar(0, H, f"ld{tid}")
            m.Add(dur == load_base + load_pu * load_q).OnlyEnforceIf(used)
            m.Add(dur == 0).OnlyEnforceIf(used.Not())
            dend = m.NewIntVar(0, H, f"de{tid}")
            dock_iv.append(m.NewOptionalIntervalVar(L, dur, dend, used, f"dock{tid}"))
            drive_terms = []
            for i in elig:
                a = m.NewBoolVar(f"a{tid}_D_{i}")
                arcs.append((0, i + 1, a))
                t = travel[(DEPOT, node[i])]
                drive_terms.append(t * a)
                m.Add(sstart[i] >= D + t).OnlyEnforceIf(a)
                b = m.NewBoolVar(f"a{tid}_{i}_D")
                arcs.append((i + 1, 0, b))
                t = travel[(node[i], DEPOT)]
                drive_terms.append(t * b)
                m.Add(R >= send[i] + t).OnlyEnforceIf(b)
                m.Add(pend[i] <= L).OnlyEnforceIf(y[i])
                for j in elig:
                    if i == j:
                        continue
                    t = travel[(node[i], node[j])]
                    if orders[i]["open"] + svc[i] + t + svc[j] > orders[j]["close"]:
                        continue
                    c = m.NewBoolVar(f"a{tid}_{i}_{j}")
                    arcs.append((i + 1, j + 1, c))
                    drive_terms.append(t * c)
                    m.Add(sstart[j] >= send[i] + t).OnlyEnforceIf(c)
            m.AddCircuit(arcs)
            drive = m.NewIntVar(0, v["max_drive"], f"drv{tid}")
            m.Add(drive == sum(drive_terms))
            cost_terms.append(v["trip_cents"] * used)
            cost_terms.append(v["drive_cents_per_minute"] * drive)
            if prev is not None:
                pused, pR = prev
                m.AddImplication(used, pused)  # symmetry: use a vehicle's slots in order
                m.Add(L >= pR + v["turnaround"]).OnlyEnforceIf(used)
            trips.append({"tid": tid, "vehicle": v["vehicle"], "used": used, "L": L, "D": D,
                          "R": R, "y": y})
            prev = (used, R)
    for s, e in inp["dock_breaks"]:
        if e > s:
            dock_iv.append(m.NewIntervalVar(s, e - s, e, f"dockbrk{s}"))
    m.AddNoOverlap(dock_iv)
    for i in range(n):
        if not assign[i]:
            raise SystemExit(f"no vehicle for order {orders[i]}")
        m.AddExactlyOne([lit for _, lit in assign[i]])

    cost = m.NewIntVar(0, budget, "cost")
    m.Add(cost == sum(cost_terms))
    m.Minimize(cost)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    solver.parameters.random_seed = seed
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit(f"no feasible plan found: {solver.StatusName(st)}")

    # Extract; the reported timeline is recomputed from the chosen stop sequence.
    out_alloc, out_pack, out_trips = [], [], []
    for i, o in enumerate(orders):
        for (ii, lname), (q, u) in alloc.items():
            if ii == i and solver.Value(q) > 0:
                out_alloc.append({"account": o["account"], "order_id": o["order_id"],
                                  "lot": lname, "quantity": solver.Value(q)})
        bench = next(b for (ii, b), lit in bench_lit.items() if ii == i and solver.Value(lit))
        out_pack.append({"account": o["account"], "order_id": o["order_id"], "bench": bench,
                         "start": solver.Value(pstart[i]), "end": solver.Value(pend[i])})
    for t in trips:
        if not solver.Value(t["used"]):
            continue
        members = [i for i, lit in t["y"].items() if solver.Value(lit)]
        members.sort(key=lambda i: solver.Value(sstart[i]))
        stops = [{"account": orders[i]["account"], "order_id": orders[i]["order_id"],
                  "service_start": solver.Value(sstart[i])} for i in members]
        last = members[-1]
        ret = solver.Value(sstart[last]) + svc[last] + travel[(node[last], DEPOT)]
        out_trips.append({"trip_id": t["tid"], "vehicle": t["vehicle"],
                          "load_start": solver.Value(t["L"]), "depart": solver.Value(t["D"]),
                          "return": ret, "stops": stops})
    out_trips.sort(key=lambda t: t["load_start"])
    return out_alloc, out_pack, out_trips, solver.StatusName(st)


# --------------------------------------------------------------------------
# Independent validation and cost recomputation
# --------------------------------------------------------------------------
def trip_drive(inp, trip):
    omap = {(o["account"], o["order_id"]): o for o in inp["roster"]}
    nodes = [DEPOT] + [omap[(s["account"], s["order_id"])]["node"] for s in trip["stops"]] + [DEPOT]
    return sum(inp["travel"][(a, b)] for a, b in zip(nodes, nodes[1:]))


def compute_cost(inp, trips):
    vmap = {v["vehicle"]: v for v in inp["vehicles"]}
    total, used = 0, set()
    for t in trips:
        v = vmap[t["vehicle"]]
        used.add(t["vehicle"])
        total += v["trip_cents"] + v["drive_cents_per_minute"] * trip_drive(inp, t)
    return total + sum(vmap[v]["hire_cents"] for v in used)


def validate(inp, plan):
    errs = []
    S = inp["settings"]
    H = S["horizon"]
    omap = {(o["account"], o["order_id"]): o for o in inp["roster"]}
    vmap = {v["vehicle"]: v for v in inp["vehicles"]}
    bmap = {b["bench"]: b for b in inp["benches"]}
    skus, lots, travel = inp["skus"], inp["lots"], inp["travel"]

    def overlap(a, b, c, d):
        return a < d and c < b

    pack = {(p["account"], p["order_id"]): p for p in plan["packing"]}
    if set(pack) != set(omap) or len(plan["packing"]) != len(omap):
        errs.append("packing coverage")
    stop_count = {}
    for t in plan["trips"]:
        for s in t["stops"]:
            k = (s["account"], s["order_id"])
            stop_count[k] = stop_count.get(k, 0) + 1
    if set(stop_count) != set(omap) or any(c != 1 for c in stop_count.values()):
        errs.append("trip coverage")
    if len({t["trip_id"] for t in plan["trips"]}) != len(plan["trips"]):
        errs.append("duplicate trip ids")
    for k, p in pack.items():
        o = omap[k]
        sk = skus[o["sku"]]
        b = bmap[p["bench"]]
        if sk["family"] not in b["families"]:
            errs.append(f"bench family {k}")
        if p["end"] - p["start"] != sk["pack_base"] + o["quantity"] * sk["pack_per_unit"]:
            errs.append(f"pack duration {k}")
        if p["start"] < max(0, b["start"]) or p["end"] > min(H, b["end"]):
            errs.append(f"bench shift {k}")
        for bn, s, e in inp["bench_breaks"]:
            if bn == p["bench"] and overlap(p["start"], p["end"], s, e):
                errs.append(f"bench break {k}")
        for k2, p2 in pack.items():
            if k2 < k and p2["bench"] == p["bench"] and \
                    overlap(p["start"], p["end"], p2["start"], p2["end"]):
                errs.append(f"bench overlap {k} {k2}")
    svc_end = {}
    dock = []
    by_vehicle = {}
    for t in plan["trips"]:
        v = vmap[t["vehicle"]]
        qs = [omap[(s["account"], s["order_id"])] for s in t["stops"]]
        if not qs:
            errs.append(f"empty trip {t['trip_id']}")
            continue
        tq = sum(o["quantity"] for o in qs)
        if tq > v["capacity"] or len(qs) > v["max_stops"]:
            errs.append(f"capacity/stops {t['trip_id']}")
        if any(skus[o["sku"]]["family"] not in v["families"] for o in qs):
            errs.append(f"vehicle family {t['trip_id']}")
        if t["depart"] != t["load_start"] + S["load_base"] + S["load_per_unit"] * tq:
            errs.append(f"depart {t['trip_id']}")
        dock.append((t["load_start"], t["depart"]))
        cur, here = t["depart"], DEPOT
        for s, o in zip(t["stops"], qs):
            k = (o["account"], o["order_id"])
            if pack[k]["end"] > t["load_start"]:
                errs.append(f"packed late {k}")
            cur += travel[(here, o["node"])]
            if s["service_start"] < cur or s["service_start"] < o["open"] or \
                    s["service_start"] + o["service"] > o["close"]:
                errs.append(f"service time {k}")
            cur = s["service_start"] + o["service"]
            svc_end[k] = cur
            if cur - pack[k]["end"] > skus[o["sku"]]["max_unrefrigerated"]:
                errs.append(f"thermal {k}")
            here = o["node"]
        if t["return"] != cur + travel[(here, DEPOT)]:
            errs.append(f"return {t['trip_id']}")
        if trip_drive(inp, t) > v["max_drive"]:
            errs.append(f"max_drive {t['trip_id']}")
        if t["load_start"] < max(0, v["start"]) or t["return"] > min(H, v["end"]):
            errs.append(f"vehicle shift {t['trip_id']}")
        by_vehicle.setdefault(t["vehicle"], []).append(t)
    for vid, vts in by_vehicle.items():
        vts.sort(key=lambda t: t["load_start"])
        if len(vts) > vmap[vid]["max_trips"]:
            errs.append(f"max_trips {vid}")
        for a, b in zip(vts, vts[1:]):
            if b["load_start"] < a["return"] + vmap[vid]["turnaround"]:
                errs.append(f"turnaround {vid}")
    for i, (a, b) in enumerate(dock):
        for s, e in inp["dock_breaks"]:
            if overlap(a, b, s, e):
                errs.append("dock break")
        for c, d in dock[:i]:
            if overlap(a, b, c, d):
                errs.append("dock overlap")
    got, used_lot = {}, {}
    for a in plan["allocations"]:
        k = (a["account"], a["order_id"])
        l = lots[a["lot"]]
        o = omap[k]
        if a["quantity"] <= 0 or l["sku"] != o["sku"] or not l["usable"]:
            errs.append(f"bad alloc {k} {a['lot']}")
            continue
        if pack[k]["start"] < l["available"]:
            errs.append(f"lot not available {k}")
        if svc_end.get(k, 10 ** 9) > l["expiry"]:
            errs.append(f"lot expiry {k}")
        got[k] = got.get(k, 0) + a["quantity"]
        used_lot[a["lot"]] = used_lot.get(a["lot"], 0) + a["quantity"]
    for k, o in omap.items():
        if got.get(k) != o["quantity"]:
            errs.append(f"alloc qty {k}")
    for ln, q in used_lot.items():
        if q > lots[ln]["balance"]:
            errs.append(f"lot balance {ln}")
    cost = compute_cost(inp, plan["trips"])
    if cost != plan["cost_cents"]:
        errs.append("cost mismatch")
    if cost > S["budget_cents"]:
        errs.append("over budget")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    inp = load_inputs(args.data)
    alloc, pack, trips, status = solve(inp, args.time_limit, args.seed)
    plan = {
        "roster": inp["roster"],
        "allocations": alloc,
        "packing": pack,
        "trips": trips,
        "cost_cents": compute_cost(inp, trips),
        "budget_cents": inp["settings"]["budget_cents"],
        "excluded_orders": inp["excluded"],
        "lot_balances": {k: {"balance": v["balance"], "status": v["status"],
                             "available": v["available"], "expiry": v["expiry"]}
                         for k, v in sorted(inp["lots"].items())},
        "solver_status": status,
    }
    errs = validate(inp, plan)
    if errs:
        print("VALIDATION FAILED:", *errs, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    print(f"orders={len(inp['roster'])} trips={len(trips)} cost={plan['cost_cents']} "
          f"budget={inp['settings']['budget_cents']} status={status}")


if __name__ == "__main__":
    main()
