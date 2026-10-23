#!/usr/bin/env python3
"""Capacity analysis from chart-read observations (standard library only)."""
import argparse
import itertools
import json
import math
import sys
from fractions import Fraction

STATUSES = ("normal", "maintenance", "unknown")
METRICS = ("rate", "failure_pct", "p95_ms")
UPPER = {"rate": None, "failure_pct": 100, "p95_ms": None}


class InputError(Exception):
    pass


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def load_json(path, label):
    def bad_const(c):
        raise InputError(f"{label}: non-finite constant {c} not allowed")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh, parse_constant=bad_const)
    except OSError as e:
        raise InputError(f"{label}: cannot read {path}: {e}")
    except json.JSONDecodeError as e:
        raise InputError(f"{label}: invalid JSON in {path}: {e}")


def validate_policy(p):
    if not isinstance(p, dict):
        raise InputError("policy: top level must be an object")
    for k in ("regions", "windows", "latency_trigger_ms", "budget_blocks",
              "max_blocks_per_region", "benefit_fraction"):
        if k not in p:
            raise InputError(f"policy: missing key '{k}'")
    regions = p["regions"]
    if (not isinstance(regions, list) or not regions
            or not all(isinstance(r, str) and r for r in regions)
            or len(set(regions)) != len(regions)):
        raise InputError("policy: 'regions' must be a non-empty list of unique strings")
    windows = p["windows"]
    if not isinstance(windows, list) or not windows:
        raise InputError("policy: 'windows' must be a non-empty list")
    ids = []
    minutes = {}
    for i, w in enumerate(windows):
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not w["id"]:
            raise InputError(f"policy: windows[{i}] needs a string 'id'")
        m = w.get("minutes")
        if not is_num(m) or m <= 0:
            raise InputError(f"policy: window {w['id']} needs positive finite 'minutes'")
        if w["id"] in minutes:
            raise InputError(f"policy: duplicate window id {w['id']}")
        ids.append(w["id"])
        minutes[w["id"]] = Fraction(m)
    trig = p["latency_trigger_ms"]
    if not is_num(trig):
        raise InputError("policy: 'latency_trigger_ms' must be a finite number")
    budget = p["budget_blocks"]
    if not is_int(budget) or budget < 0:
        raise InputError("policy: 'budget_blocks' must be a nonnegative integer")
    mx = p["max_blocks_per_region"]
    if not is_int(mx) or mx < 1:
        raise InputError("policy: 'max_blocks_per_region' must be a positive integer")
    fr = p["benefit_fraction"]
    if not isinstance(fr, list) or len(fr) < mx + 1 or not all(is_num(x) for x in fr):
        raise InputError("policy: 'benefit_fraction' must list finite numbers for 0..max_blocks_per_region")
    if fr[0] != 0:
        raise InputError("policy: benefit_fraction[0] must be 0")
    if any(x < 0 for x in fr) or any(fr[i + 1] <= fr[i] for i in range(len(fr) - 1)):
        raise InputError("policy: benefit_fraction must be nonnegative and strictly increasing")
    return {
        "regions": regions, "window_ids": ids, "minutes": minutes,
        "trigger": Fraction(trig), "budget": budget, "max_blocks": mx,
        "fractions": [Fraction(x) for x in fr[:mx + 1]],
    }


def validate_interval(v, metric, where):
    if not isinstance(v, list) or len(v) != 3 or not all(is_num(x) for x in v):
        raise InputError(f"{where}: '{metric}' must be [low, estimate, high] of finite numbers")
    lo, est, hi = v
    if not (lo <= est <= hi):
        raise InputError(f"{where}: '{metric}' must satisfy low <= estimate <= high")
    if lo < 0:
        raise InputError(f"{where}: '{metric}' must be nonnegative")
    if UPPER[metric] is not None and hi > UPPER[metric]:
        raise InputError(f"{where}: '{metric}' exceeds {UPPER[metric]}")
    return tuple(Fraction(x) for x in v)


def validate_observations(obs, pol):
    if not isinstance(obs, dict) or not isinstance(obs.get("records"), list):
        raise InputError("observations: top level must be an object with a 'records' list")
    regions, wids = set(pol["regions"]), set(pol["window_ids"])
    table = {}
    for i, rec in enumerate(obs["records"]):
        where = f"observations: records[{i}]"
        if not isinstance(rec, dict):
            raise InputError(f"{where}: must be an object")
        r, w, s = rec.get("region"), rec.get("window"), rec.get("status")
        if r not in regions:
            raise InputError(f"{where}: unknown region {r!r}")
        if w not in wids:
            raise InputError(f"{where}: unknown window {w!r}")
        where = f"observations: {r}/{w}"
        if (r, w) in table:
            raise InputError(f"{where}: duplicate record")
        if s not in STATUSES:
            raise InputError(f"{where}: status must be one of {STATUSES}, got {s!r}")
        for m in METRICS:
            if m not in rec:
                raise InputError(f"{where}: missing key '{m}'")
        if "sources" in rec and not isinstance(rec["sources"], dict):
            raise InputError(f"{where}: 'sources' must be an object")
        vals = {}
        if s == "unknown":
            for m in METRICS:
                if rec[m] is not None:
                    raise InputError(f"{where}: unknown status requires null '{m}'")
                vals[m] = None
        else:
            for m in METRICS:
                if rec[m] is None:
                    raise InputError(f"{where}: {s} status requires an interval for '{m}'")
                vals[m] = validate_interval(rec[m], m, where)
        table[(r, w)] = (s, vals)
    missing = [f"{r}/{w}" for r in pol["regions"] for w in pol["window_ids"] if (r, w) not in table]
    if missing:
        raise InputError("observations: missing records for " + ", ".join(missing))
    return table


def ratio_pct(num, den):
    return None if den == 0 else 100 * num / den


def num(x):
    return None if x is None else float(x)


def analyze(pol, table):
    fr = pol["fractions"]
    out_regions, stats = {}, {}
    fleet_req = fleet_fail = Fraction(0)
    for r in pol["regions"]:
        included = [w for w in pol["window_ids"] if table[(r, w)][0] == "normal"]
        req = failed = lo = hi = Fraction(0)
        for w in included:
            vals = table[(r, w)][1]
            mins = pol["minutes"][w]
            rl, re, rh = vals["rate"]
            fl, fe, fh = vals["failure_pct"]
            q = re * mins
            req += q
            failed += q * fe / 100
            lo += mins * rl * fl / 100
            hi += mins * rh * fh / 100
        lat = included[-2:]
        eligible = len(lat) == 2 and all(table[(r, w)][1]["p95_ms"][1] > pol["trigger"] for w in lat)
        stats[r] = (failed, lo, hi, eligible)
        fleet_req += req
        fleet_fail += failed
        out_regions[r] = {
            "included_windows": included,
            "latency_windows": lat,
            "latency_p95_estimates": [float(table[(r, w)][1]["p95_ms"][1]) for w in lat],
            "requests": float(req),
            "failed_requests": float(failed),
            "failure_pct": num(ratio_pct(failed, req)),
            "failed_bounds": [float(lo), float(hi)],
            "eligible": eligible,
        }

    regs = pol["regions"]
    choices = [range(pol["max_blocks"] + 1) if stats[r][3] else range(1) for r in regs]
    feasible = [a for a in itertools.product(*choices) if sum(a) <= pol["budget"]]

    def benefit(a, idx):
        return sum(stats[r][idx] * fr[k] for r, k in zip(regs, a))

    best = min(feasible, key=lambda a: (-benefit(a, 0), sum(a), a))
    margin = None
    for c in feasible:
        if c == best:
            continue
        m = Fraction(0)
        for r, kw, kc in zip(regs, best, c):
            d = fr[kw] - fr[kc]
            m += d * (stats[r][1] if d > 0 else stats[r][2])
        margin = m if margin is None or m < margin else margin

    return {
        "regions": out_regions,
        "fleet": {
            "requests": float(fleet_req),
            "failed_requests": float(fleet_fail),
            "failure_pct": num(ratio_pct(fleet_fail, fleet_req)),
        },
        "allocation": {r: k for r, k in zip(regs, best)},
        "expected_benefit": float(benefit(best, 0)),
        "benefit_bounds": [float(benefit(best, 1)), float(benefit(best, 2))],
        "robust_margin": num(margin),
        "robust": True if margin is None else margin > 0,
        "feasible_allocations": len(feasible),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--observations", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        pol = validate_policy(load_json(args.policy, "policy"))
        table = validate_observations(load_json(args.observations, "observations"), pol)
        result = analyze(pol, table)
    except InputError as e:
        print(f"analyze.py: error: {e}", file=sys.stderr)
        return 2
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, allow_nan=False)
            fh.write("\n")
    except OSError as e:
        print(f"analyze.py: error: cannot write {args.out}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
