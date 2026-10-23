#!/usr/bin/env python3
"""Offline maintenance planner for the Meridian campus fibre plant.

Reads the cable inventory, settings, phases, outages, services and the
transcribed topology, solves one CP-SAT model covering every phase at once
(the activation list is global), validates the result independently and
writes maintenance.json.

Usage:
  python build_plan.py --data DATA_DIR --topology topology.json --output maintenance.json
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from ortools.sat.python import cp_model


def parse_ts(text):
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def load_inputs(data_dir, topology_path):
    with open(os.path.join(data_dir, "settings.json"), encoding="utf-8") as fh:
        settings = json.load(fh)
    cutoff = parse_ts(settings["planning_cutoff"])
    budget = int(settings["budget_cents"])

    # Select the latest record at or before the cutoff for each cable.
    selected = {}
    for row in read_csv(os.path.join(data_dir, "cable_versions.csv")):
        ts = parse_ts(row["recorded_at"])
        if ts > cutoff:
            continue
        cur = selected.get(row["cable"])
        if cur is None or ts > cur[0]:
            selected[row["cable"]] = (ts, row)
    inventory = {}
    for cable, (_, row) in selected.items():
        status = row["status"].lower()
        if status not in ("lit", "dark", "blocked"):
            raise SystemExit(f"unknown status {status!r} for {cable}")
        inventory[cable] = {
            "status": status,
            "capacity": int(row["capacity"]),
            "risk_group": row["risk_group"],
            "activation_cents": int(row["activation_cents"]),
        }

    phases = [r["phase"] for r in read_csv(os.path.join(data_dir, "phases.csv"))]
    outages = defaultdict(set)
    for r in read_csv(os.path.join(data_dir, "outages.csv")):
        outages[r["phase"]].add(r["cable"])

    services = []
    for r in read_csv(os.path.join(data_dir, "services.csv")):
        prot = r["protection"].lower()
        if prot not in ("none", "1+1"):
            raise SystemExit(f"unknown protection {prot!r} for {r['service']}")
        services.append({
            "service": r["service"], "source": r["source"], "target": r["target"],
            "units": int(r["units"]),
            "roles": ["primary"] if prot == "none" else ["primary", "secondary"],
        })

    with open(topology_path, encoding="utf-8") as fh:
        topo = json.load(fh)
    links = {}
    for l in topo["links"]:
        if l["cable"] in links:
            raise SystemExit(f"duplicate cable {l['cable']} in topology")
        if l["a"] == l["b"]:
            raise SystemExit(f"self-loop cable {l['cable']} in topology")
        links[l["cable"]] = (l["a"], l["b"])

    missing = sorted(set(inventory) - set(links))
    unknown = sorted(set(links) - set(inventory))
    if missing:
        print(f"warning: inventory cables absent from topology: {missing}", file=sys.stderr)
    if unknown:
        print(f"warning: topology cables without known inventory (treated unusable): {unknown}",
              file=sys.stderr)
    return budget, inventory, phases, outages, services, links


def usable(cable, phase, inventory, outages):
    inv = inventory.get(cable)
    return inv is not None and inv["status"] != "blocked" and cable not in outages[phase]


def solve(budget, inventory, phases, outages, services, links, time_limit, workers):
    m = cp_model.CpModel()
    cables = sorted(links)
    nodes = sorted({n for ab in links.values() for n in ab})
    dark = [c for c in cables if c in inventory and inventory[c]["status"] == "dark"]
    act = {c: m.NewBoolVar(f"act_{c}") for c in dark}
    m.Add(sum(inventory[c]["activation_cents"] * act[c] for c in dark) <= budget)

    x = {}  # (phase, service, role, cable, dir) -> bool; dir 0: a->b, 1: b->a
    hop_terms = []
    for p in phases:
        load = defaultdict(list)
        for s in services:
            src, dst = s["source"], s["target"]
            if src == dst:
                raise SystemExit(f"service {s['service']} has identical endpoints")
            rg_use = {}
            for role in s["roles"]:
                out_arcs = defaultdict(list)
                in_arcs = defaultdict(list)
                used = {}
                for c in cables:
                    if not usable(c, p, inventory, outages):
                        continue
                    a, b = links[c]
                    f = m.NewBoolVar(f"x_{p}_{s['service']}_{role}_{c}_f")
                    r = m.NewBoolVar(f"x_{p}_{s['service']}_{role}_{c}_r")
                    x[p, s["service"], role, c, 0] = f
                    x[p, s["service"], role, c, 1] = r
                    m.Add(f + r <= 1)
                    u = f + r
                    used[c] = u
                    out_arcs[a].append(f); in_arcs[b].append(f)
                    out_arcs[b].append(r); in_arcs[a].append(r)
                    if c in act:
                        m.Add(f + r <= act[c])
                    load[c].append((s["units"], u))
                    hop_terms.append(f)
                    hop_terms.append(r)
                for n in nodes:
                    out_n, in_n = sum(out_arcs[n]), sum(in_arcs[n])
                    if n == src:
                        m.Add(out_n == 1)
                        m.Add(in_n == 0)
                    elif n == dst:
                        m.Add(in_n == 1)
                        m.Add(out_n == 0)
                    else:
                        m.Add(in_n == out_n)
                        m.Add(in_n <= 1)
                if len(s["roles"]) == 2:
                    groups = defaultdict(list)
                    for c, u in used.items():
                        groups[inventory[c]["risk_group"]].append(u)
                    rg_use[role] = groups
            if len(s["roles"]) == 2:
                g1, g2 = rg_use["primary"], rg_use["secondary"]
                for g in set(g1) & set(g2):
                    y = m.NewBoolVar(f"rg_{p}_{s['service']}_{g}")
                    for u in g1[g]:
                        m.Add(u <= y)
                    for u in g2[g]:
                        m.Add(u <= 1 - y)
        for c, terms in load.items():
            m.Add(sum(units * u for units, u in terms) <= inventory[c]["capacity"])

    cost = sum(inventory[c]["activation_cents"] * act[c] for c in dark)
    # Cheapest activation first; fewest cable hops as tie-breaker.
    m.Minimize(cost * 10000 + sum(hop_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 1
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit(f"no feasible plan found (solver status {solver.StatusName(status)})")
    print(f"solver status {solver.StatusName(status)}, objective {solver.ObjectiveValue():.0f}",
          file=sys.stderr)

    activate = sorted(c for c in dark if solver.Value(act[c]))
    plan_phases = []
    for p in phases:
        routes = []
        for s in services:
            for role in s["roles"]:
                arcs = {}
                for c in cables:
                    for d in (0, 1):
                        v = x.get((p, s["service"], role, c, d))
                        if v is not None and solver.Value(v):
                            a, b = links[c]
                            tail, head = (a, b) if d == 0 else (b, a)
                            arcs[tail] = (c, head)
                # Walk from source; any disjoint cycles are simply discarded.
                path, node, seen = [], s["source"], {s["source"]}
                while node != s["target"]:
                    c, node = arcs[node]
                    if node in seen:
                        raise SystemExit("internal error: non-simple walk")
                    seen.add(node)
                    path.append(c)
                routes.append({"service": s["service"], "role": role, "cables": path})
        plan_phases.append({"phase": p, "routes": routes})
    spend = sum(inventory[c]["activation_cents"] for c in activate)
    return {"activate": activate, "activation_cents": spend, "phases": plan_phases}


def validate(plan, budget, inventory, phases, outages, services, links):
    errors = []
    act = plan["activate"]
    if len(set(act)) != len(act):
        errors.append("duplicate activation")
    for c in act:
        if c not in inventory or inventory[c]["status"] != "dark":
            errors.append(f"{c} activated but not dark")
    spend = sum(inventory[c]["activation_cents"] for c in set(act) if c in inventory)
    if spend != plan["activation_cents"]:
        errors.append("reported activation spend mismatch")
    if spend > budget:
        errors.append(f"spend {spend} exceeds budget {budget}")
    if [ph["phase"] for ph in plan["phases"]] != phases:
        errors.append("phase list mismatch")
    actset = set(act)
    for ph in plan["phases"]:
        p = ph["phase"]
        load = defaultdict(int)
        by_key = {}
        for r in ph["routes"]:
            key = (r["service"], r["role"])
            if key in by_key:
                errors.append(f"{p}: duplicate route {key}")
            by_key[key] = r["cables"]
        for s in services:
            for role in s["roles"]:
                path = by_key.get((s["service"], role))
                if path is None:
                    errors.append(f"{p}: missing {s['service']}/{role}")
                    continue
                node, seen = s["source"], {s["source"]}
                if len(set(path)) != len(path):
                    errors.append(f"{p}: {s['service']}/{role} repeats a cable")
                for c in path:
                    if c not in links:
                        errors.append(f"{p}: unknown cable {c}")
                        break
                    inv = inventory.get(c)
                    if inv is None or inv["status"] == "blocked":
                        errors.append(f"{p}: {c} unusable")
                    elif inv["status"] == "dark" and c not in actset:
                        errors.append(f"{p}: {c} dark and not activated")
                    if c in outages[p]:
                        errors.append(f"{p}: {c} is out of service")
                    a, b = links[c]
                    if node == a:
                        node = b
                    elif node == b:
                        node = a
                    else:
                        errors.append(f"{p}: {s['service']}/{role} discontinuous at {c}")
                        break
                    if node in seen:
                        errors.append(f"{p}: {s['service']}/{role} repeats node {node}")
                    seen.add(node)
                    load[c] += s["units"]
                if node != s["target"]:
                    errors.append(f"{p}: {s['service']}/{role} does not reach target")
            if len(s["roles"]) == 2:
                g1 = {inventory[c]["risk_group"] for c in by_key.get((s["service"], "primary"), []) if c in inventory}
                g2 = {inventory[c]["risk_group"] for c in by_key.get((s["service"], "secondary"), []) if c in inventory}
                if g1 & g2:
                    errors.append(f"{p}: {s['service']} shares risk groups {sorted(g1 & g2)}")
        expected = {(s["service"], role) for s in services for role in s["roles"]}
        if set(by_key) != expected:
            errors.append(f"{p}: unexpected routes {sorted(set(by_key) - expected)}")
        for c, u in load.items():
            if u > inventory[c]["capacity"]:
                errors.append(f"{p}: {c} load {u} > capacity {inventory[c]['capacity']}")
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--topology", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=90.0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    budget, inventory, phases, outages, services, links = load_inputs(args.data, args.topology)
    plan = solve(budget, inventory, phases, outages, services, links, args.time_limit, args.workers)
    errors = validate(plan, budget, inventory, phases, outages, services, links)
    if errors:
        for e in errors:
            print("validation error:", e, file=sys.stderr)
        raise SystemExit(1)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, args.output)
    print(f"wrote {args.output}: {len(plan['activate'])} activations, "
          f"{plan['activation_cents']} of {budget} cents; validation passed", file=sys.stderr)


if __name__ == "__main__":
    main()
