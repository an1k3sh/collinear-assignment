#!/usr/bin/env python3
"""Offline maintenance planner for the Meridian campus.

Usage:
  python build_plan.py --data DATA_DIR --topology topology.json --output maintenance.json

Reads the cable inventory (versioned, filtered by the planning cutoff), the
phase list and outages, the service records and the transcribed topology, then
solves a CP-SAT model:

* one directed unit flow per (phase, service, role) from source to target,
  with in/out degree <= 1 at every node (simple path), each cable used in at
  most one direction per route;
* cables blocked at the cutoff or out of service in a phase carry no flow;
* dark cables carry flow only if globally activated; activation spend is
  charged once and bounded by the budget;
* per phase and cable, the summed units of all routes (both directions)
  stay within the selected capacity;
* for 1+1 services, primary and secondary use disjoint risk groups.

The objective minimises activation spend, then total hop count. The result
is validated independently from the solver model before it is written.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime


def parse_ts(s):
    return datetime.fromisoformat(s.strip().replace('Z', '+00:00'))


def read_csv(path):
    with open(path, newline='') as f:
        return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                for r in csv.DictReader(f)]


def load(data_dir, topology_path):
    settings = json.load(open(os.path.join(data_dir, 'settings.json')))
    cutoff = parse_ts(settings['planning_cutoff'])
    budget = int(settings['budget_cents'])

    inv = {}
    for r in read_csv(os.path.join(data_dir, 'cable_versions.csv')):
        t = parse_ts(r['recorded_at'])
        if t > cutoff:
            continue
        if r['cable'] not in inv or t > inv[r['cable']]['_t']:
            inv[r['cable']] = {
                '_t': t, 'status': r['status'].lower(), 'capacity': int(r['capacity']),
                'risk_group': r['risk_group'], 'cost': int(r['activation_cents'])}

    phases = [r['phase'] for r in read_csv(os.path.join(data_dir, 'phases.csv'))]
    outages = {p: set() for p in phases}
    for r in read_csv(os.path.join(data_dir, 'outages.csv')):
        outages.setdefault(r['phase'], set()).add(r['cable'])

    services = []
    for r in read_csv(os.path.join(data_dir, 'services.csv')):
        prot = r['protection'].lower()
        roles = ['primary', 'secondary'] if prot == '1+1' else ['primary']
        services.append({'service': r['service'], 'source': r['source'], 'target': r['target'],
                         'units': int(r['units']), 'roles': roles})

    topo = json.load(open(topology_path))
    ends = {}
    for l in topo['links']:
        ends[l['cable']] = (l['a'], l['b'])
    return budget, inv, phases, outages, services, ends


def solve(budget, inv, phases, outages, services, ends, time_limit=120.0, workers=4):
    from ortools.sat.python import cp_model

    cables = sorted(c for c in ends if c in inv and inv[c]['status'] != 'blocked'
                    and ends[c][0] != ends[c][1])
    dark = [c for c in cables if inv[c]['status'] == 'dark']
    nodes = sorted({n for c in ends for n in ends[c]}
                   | {s['source'] for s in services} | {s['target'] for s in services})

    m = cp_model.CpModel()
    act = {c: m.NewBoolVar('act_' + c) for c in dark}
    m.Add(sum(inv[c]['cost'] * act[c] for c in dark) <= budget)

    flows = {}  # (phase, service, role) -> {(cable, dir): var}
    hop_terms = []
    for p in phases:
        usable = [c for c in cables if c not in outages.get(p, set())]
        load_terms = {c: [] for c in usable}
        for s in services:
            route_groups = {}
            for role in s['roles']:
                f = {}
                for c in usable:
                    a, b = ends[c]
                    f[(c, 0)] = m.NewBoolVar(f'f_{p}_{s["service"]}_{role}_{c}_ab')
                    f[(c, 1)] = m.NewBoolVar(f'f_{p}_{s["service"]}_{role}_{c}_ba')
                    m.Add(f[(c, 0)] + f[(c, 1)] <= 1)
                    if c in act:
                        m.Add(f[(c, 0)] + f[(c, 1)] <= act[c])
                    load_terms[c].append(s['units'] * (f[(c, 0)] + f[(c, 1)]))
                    hop_terms += [f[(c, 0)], f[(c, 1)]]
                out_arcs = {n: [] for n in nodes}
                in_arcs = {n: [] for n in nodes}
                for (c, d), v in f.items():
                    a, b = ends[c]
                    u, w = (a, b) if d == 0 else (b, a)
                    out_arcs[u].append(v)
                    in_arcs[w].append(v)
                for n in nodes:
                    bal = 1 if n == s['source'] else (-1 if n == s['target'] else 0)
                    m.Add(sum(out_arcs[n]) - sum(in_arcs[n]) == bal)
                    m.Add(sum(out_arcs[n]) <= 1)
                    m.Add(sum(in_arcs[n]) <= 1)
                    if n == s['source']:
                        m.Add(sum(in_arcs[n]) == 0)
                    if n == s['target']:
                        m.Add(sum(out_arcs[n]) == 0)
                flows[(p, s['service'], role)] = f
                if len(s['roles']) > 1:
                    groups = {}
                    for (c, d), v in f.items():
                        groups.setdefault(inv[c]['risk_group'], []).append(v)
                    route_groups[role] = groups
            if len(route_groups) == 2:
                g1, g2 = route_groups['primary'], route_groups['secondary']
                for g in set(g1) & set(g2):
                    u1 = m.NewBoolVar('')
                    u2 = m.NewBoolVar('')
                    for v in g1[g]:
                        m.AddImplication(v, u1)
                    for v in g2[g]:
                        m.AddImplication(v, u2)
                    m.Add(u1 + u2 <= 1)
        for c in usable:
            if load_terms[c]:
                m.Add(sum(load_terms[c]) <= inv[c]['capacity'])

    m.Minimize(1000 * sum(inv[c]['cost'] * act[c] for c in dark) + sum(hop_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 7
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit('no feasible plan found: ' + solver.StatusName(st))

    activate = sorted(c for c in dark if solver.Value(act[c]))
    plan_phases = []
    for p in phases:
        routes = []
        for s in services:
            for role in s['roles']:
                f = flows[(p, s['service'], role)]
                nxt = {}
                for (c, d), v in f.items():
                    if solver.Value(v):
                        a, b = ends[c]
                        u = a if d == 0 else b
                        w = b if d == 0 else a
                        nxt[u] = (c, w)
                path, cur, seen = [], s['source'], {s['source']}
                while cur != s['target']:
                    c, cur = nxt[cur]
                    if cur in seen:
                        raise SystemExit('internal error: non-simple path')
                    seen.add(cur)
                    path.append(c)
                routes.append({'service': s['service'], 'role': role, 'cables': path})
        plan_phases.append({'phase': p, 'routes': routes})
    return {
        'activate': activate,
        'activation_cents': sum(inv[c]['cost'] for c in activate),
        'phases': plan_phases,
    }, solver.StatusName(st)


def validate(plan, budget, inv, phases, outages, services, ends):
    errs = []
    act = plan['activate']
    if len(set(act)) != len(act):
        errs.append('duplicate activation')
    for c in act:
        if c not in inv or inv[c]['status'] != 'dark':
            errs.append(f'{c} activated but not dark')
    spend = sum(inv[c]['cost'] for c in set(act) if c in inv)
    if spend != plan['activation_cents']:
        errs.append('activation_cents mismatch')
    if spend > budget:
        errs.append('over budget')
    if sorted(ph['phase'] for ph in plan['phases']) != sorted(phases):
        errs.append('phase set mismatch')
    svc = {s['service']: s for s in services}
    for ph in plan['phases']:
        p = ph['phase']
        load = {}
        got = {}
        for r in ph['routes']:
            key = (r['service'], r['role'])
            if key in got:
                errs.append(f'{p} duplicate {key}')
            got[key] = r['cables']
            s = svc.get(r['service'])
            if s is None or r['role'] not in s['roles']:
                errs.append(f'{p} unexpected route {key}')
                continue
            cur, seen = s['source'], {s['source']}
            if len(set(r['cables'])) != len(r['cables']):
                errs.append(f'{p} {key} repeats a cable')
            for c in r['cables']:
                if c not in ends or c not in inv:
                    errs.append(f'{p} {key} unknown cable {c}')
                    break
                st = inv[c]['status']
                if st == 'blocked' or (st == 'dark' and c not in act) or c in outages.get(p, ()):
                    errs.append(f'{p} {key} uses unusable {c}')
                a, b = ends[c]
                if cur == a:
                    cur = b
                elif cur == b:
                    cur = a
                else:
                    errs.append(f'{p} {key} discontinuous at {c}')
                    break
                if cur in seen:
                    errs.append(f'{p} {key} repeats node {cur}')
                seen.add(cur)
                load[c] = load.get(c, 0) + s['units']
            if cur != s['target']:
                errs.append(f'{p} {key} does not reach target')
        for s in services:
            for role in s['roles']:
                if (s['service'], role) not in got:
                    errs.append(f'{p} missing {s["service"]}/{role}')
            if len(s['roles']) == 2 and all((s['service'], r) in got for r in s['roles']):
                g1 = {inv[c]['risk_group'] for c in got[(s['service'], 'primary')] if c in inv}
                g2 = {inv[c]['risk_group'] for c in got[(s['service'], 'secondary')] if c in inv}
                if g1 & g2:
                    errs.append(f'{p} {s["service"]} shares risk groups {sorted(g1 & g2)}')
        for c, u in load.items():
            if c in inv and u > inv[c]['capacity']:
                errs.append(f'{p} {c} overloaded {u}>{inv[c]["capacity"]}')
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data', required=True)
    ap.add_argument('--topology', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--time-limit', type=float, default=120.0)
    args = ap.parse_args()

    budget, inv, phases, outages, services, ends = load(args.data, args.topology)
    missing = sorted(set(inv) - set(ends))
    if missing:
        print('warning: inventory cables absent from topology:', missing, file=sys.stderr)
    plan, status = solve(budget, inv, phases, outages, services, ends, args.time_limit)
    errs = validate(plan, budget, inv, phases, outages, services, ends)
    if errs:
        for e in errs:
            print('VALIDATION ERROR:', e, file=sys.stderr)
        raise SystemExit(1)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(plan, f, indent=1)
    print(f'solver status {status}; activated {len(plan["activate"])} cables, '
          f'{plan["activation_cents"]} cents of {budget}; plan validated')


if __name__ == '__main__':
    main()
