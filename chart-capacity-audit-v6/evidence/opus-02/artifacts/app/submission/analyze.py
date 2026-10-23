#!/usr/bin/env python3
"""Reconcile dashboard readings and plan a constrained capacity rollout.

Standard library only.  All arithmetic is exact (fractions.Fraction parsed from
the decimal JSON text) and converted to floats only when writing output.

Usage:
  python analyze.py --readings R --manifest M --operations O --planning P \
                    --registry REG --out OUT
"""
import argparse
import bisect
import csv
import itertools
import json
import os
import sys
from collections import OrderedDict, defaultdict
from fractions import Fraction as F

TARGET_IDS = ("AS", "AI", "BS", "BI", "CS", "CI", "DS", "DI")
METRICS = ("requests", "errors")
DEFAULT_P95_LABELS = ["<=100", "(100,300]", "(300,1000]", ">1000"]
MAX_ABS = F(10) ** 15


class InputError(Exception):
    pass


def warn(msg):
    sys.stderr.write("WARNING: %s\n" % msg)


# --------------------------------------------------------------------------
# Generic parsing helpers
# --------------------------------------------------------------------------

def load_json(path):
    def bad_constant(token):
        raise InputError("%s: non-finite number %r is not allowed" % (path, token))

    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh, parse_float=F, parse_constant=bad_constant)
    except InputError:
        raise
    except (OSError, ValueError) as exc:
        raise InputError("%s: cannot read JSON (%s)" % (path, exc))


def is_num(x):
    return (isinstance(x, int) and not isinstance(x, bool)) or isinstance(x, F)


def num(x, where, nonneg=False, positive=False):
    if not is_num(x):
        raise InputError("%s: expected a finite number, got %r" % (where, x))
    x = F(x)
    if abs(x) > MAX_ABS:
        raise InputError("%s: number %s out of supported range" % (where, x))
    if nonneg and x < 0:
        raise InputError("%s: negative value %s" % (where, x))
    if positive and x <= 0:
        raise InputError("%s: value must be positive, got %s" % (where, x))
    return x


def integer(x, where, lo=None, hi=None):
    if isinstance(x, F) and x.denominator == 1:
        x = int(x)
    if not isinstance(x, int) or isinstance(x, bool):
        raise InputError("%s: expected an integer, got %r" % (where, x))
    if lo is not None and x < lo:
        raise InputError("%s: %d below minimum %d" % (where, x, lo))
    if hi is not None and x > hi:
        raise InputError("%s: %d above maximum %d" % (where, x, hi))
    return x


def req(obj, key, where):
    if not isinstance(obj, dict):
        raise InputError("%s: expected an object" % where)
    if key not in obj:
        raise InputError("%s: missing field %r" % (where, key))
    return obj[key]


def string(x, where):
    if not isinstance(x, str) or not x:
        raise InputError("%s: expected a nonempty string, got %r" % (where, x))
    return x


def interval(v, where):
    """[low, estimate, high] or None."""
    if v is None:
        return None
    if not isinstance(v, list) or len(v) != 3:
        raise InputError("%s: interval must be [low, estimate, high] or null, got %r" % (where, v))
    lo, est, hi = (num(x, where, nonneg=True) for x in v)
    if not (lo <= est <= hi):
        raise InputError("%s: reversed/inconsistent interval %r (need low<=estimate<=high)" % (where, v))
    return (lo, est, hi)


def out_num(x):
    if x is None:
        return None
    if isinstance(x, F):
        if x.denominator == 1:
            return int(x)
        return float(x)
    return x


def out_iv(iv):
    return None if iv is None else [out_num(v) for v in iv]


def div(a, b):
    return None if b == 0 else F(a) / F(b)


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def parse_registry(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise InputError("%s: cannot read registry (%s)" % (path, exc))
    reg = {}
    for i, row in enumerate(rows):
        where = "registry row %d" % (i + 2)
        t = (row.get("target") or "").strip()
        if t not in TARGET_IDS:
            raise InputError("%s: unknown target %r" % (where, t))
        if t in reg:
            raise InputError("%s: duplicate target %s" % (where, t))
        reg[t] = {"region": (row.get("region") or "").strip(),
                  "service": (row.get("service") or "").strip(),
                  "display_name": (row.get("display_name") or "").strip()}
    missing = [t for t in TARGET_IDS if t not in reg]
    if missing:
        raise InputError("registry: missing targets %s" % missing)
    return reg


def parse_operations(ops):
    where = "operations"
    bl = req(ops, "boundaries", where)
    if not isinstance(bl, list):
        raise InputError("operations.boundaries must be a list")
    boundaries = []
    for i, b in enumerate(bl):
        bid = string(req(b, "id", "operations.boundaries[%d]" % i), "operations.boundaries[%d].id" % i)
        if bid in boundaries:
            raise InputError("operations: duplicate boundary %s" % bid)
        boundaries.append(bid)
    wl = req(ops, "windows", where)
    if not isinstance(wl, list) or not (1 <= len(wl) <= 4):
        raise InputError("operations.windows must be a list of 1..4 windows")
    windows = []
    seen = set()
    for i, w in enumerate(wl):
        wh = "operations.windows[%d]" % i
        wid = string(req(w, "id", wh), wh + ".id")
        if wid in seen:
            raise InputError("operations: duplicate window %s" % wid)
        seen.add(wid)
        start = string(req(w, "start", wh), wh + ".start")
        end = string(req(w, "end", wh), wh + ".end")
        for b in (start, end):
            if b not in boundaries:
                raise InputError("%s: references unknown boundary %s" % (wh, b))
        if start == end:
            raise InputError("%s: start and end boundary are identical" % wh)
        minutes = num(req(w, "minutes", wh), wh + ".minutes", positive=True)
        windows.append({"id": wid, "start": start, "end": end, "minutes": minutes})
    wids = [w["id"] for w in windows]
    resets = {}
    for i, r in enumerate(ops.get("resets", []) or []):
        wh = "operations.resets[%d]" % i
        t = req(r, "target", wh)
        if t not in TARGET_IDS:
            raise InputError("%s: unknown target %r" % (wh, t))
        w = string(req(r, "window", wh), wh + ".window")
        m = req(r, "metric", wh)
        if m not in METRICS:
            raise InputError("%s: unknown metric %r" % (wh, m))
        b = num(req(r, "baseline", wh), wh + ".baseline", nonneg=True)
        if w not in wids:
            warn("%s refers to window %s that is not in operations.windows; not applicable" % (wh, w))
            continue
        if (t, w, m) in resets:
            raise InputError("%s: duplicate reset for %s/%s/%s" % (wh, t, w, m))
        resets[(t, w, m)] = b
    maintenance = set()
    for i, r in enumerate(ops.get("maintenance", []) or []):
        wh = "operations.maintenance[%d]" % i
        t = req(r, "target", wh)
        if t not in TARGET_IDS:
            raise InputError("%s: unknown target %r" % (wh, t))
        w = string(req(r, "window", wh), wh + ".window")
        if w not in wids:
            warn("%s refers to window %s that is not in operations.windows; not applicable" % (wh, w))
            continue
        maintenance.add((t, w))
    return {"boundaries": boundaries, "windows": windows, "resets": resets,
            "maintenance": maintenance}


def parse_manifest(man):
    pl = req(man, "pages", "manifest")
    if not isinstance(pl, list) or not pl:
        raise InputError("manifest.pages must be a nonempty list")
    pages = OrderedDict()
    for i, p in enumerate(pl):
        wh = "manifest.pages[%d]" % i
        pid = string(req(p, "id", wh), wh + ".id")
        if pid in pages:
            raise InputError("manifest: duplicate page id %s" % pid)
        kind = req(p, "kind", wh)
        if kind not in ("counters", "histograms"):
            raise InputError("%s: invalid kind %r" % (wh, kind))
        targets = req(p, "targets", wh)
        if not isinstance(targets, list) or not targets:
            raise InputError("%s: targets must be a nonempty list" % wh)
        for t in targets:
            if t not in TARGET_IDS:
                raise InputError("%s: unknown target %r" % (wh, t))
        if len(set(targets)) != len(targets):
            raise InputError("%s: duplicate targets" % wh)
        units = p.get("series_units")
        need = ("requests", "errors") if kind == "counters" else ("samples",)
        if not isinstance(units, dict):
            raise InputError("%s: series_units missing or invalid" % wh)
        for k in need:
            num(req(units, k, wh + ".series_units"), "%s.series_units.%s" % (wh, k), positive=True)
        pages[pid] = {"id": pid, "kind": kind, "targets": list(targets),
                      "file": p.get("file"), "revision": p.get("revision")}
    edges = []
    for i, e in enumerate(man.get("supersedes", []) or []):
        wh = "manifest.supersedes[%d]" % i
        new = req(e, "new", wh)
        old = req(e, "old", wh)
        for x in (new, old):
            if x not in pages:
                raise InputError("%s: unknown page id %r" % (wh, x))
        if new == old:
            raise InputError("%s: supersession cycle (page supersedes itself: %s)" % (wh, new))
        if pages[new]["kind"] != pages[old]["kind"]:
            raise InputError("%s: %s and %s have different kinds" % (wh, new, old))
        edges.append((new, old))
    # cycle detection on new -> old graph
    graph = defaultdict(list)
    for n, o in edges:
        graph[n].append(o)
    state = {}

    def visit(n, stack):
        state[n] = 1
        for m in graph[n]:
            if state.get(m) == 1:
                raise InputError("manifest: supersession cycle %s" % " -> ".join(stack + [n, m]))
            if state.get(m) is None:
                visit(m, stack + [n])
        state[n] = 2

    for n in list(graph):
        if state.get(n) is None:
            visit(n, [])
    rejected = sorted({o for _, o in edges})
    selected = sorted(p for p in pages if p not in rejected)
    by_target = {}
    for t in TARGET_IDS:
        entry = {}
        for kind in ("counters", "histograms"):
            cands = [p for p in selected if pages[p]["kind"] == kind and t in pages[p]["targets"]]
            if len(cands) != 1:
                raise InputError("manifest: target %s needs exactly one selected %s page, found %s"
                                 % (t, kind, cands or "none"))
            entry[kind] = cands[0]
        by_target[t] = entry
    superseded_by = {}
    for n, o in edges:
        superseded_by.setdefault(o, []).append(n)
    return {"pages": pages, "edges": edges, "selected": selected, "rejected": rejected,
            "by_target": by_target, "superseded_by": superseded_by}


def parse_readings(rd, manifest, ops):
    if not isinstance(rd, dict):
        raise InputError("readings: expected an object")
    units = rd.get("units")
    if units != "base-counts":
        raise InputError("readings: invalid units %r (must be 'base-counts')" % (units,))
    pages = manifest["pages"]
    counters = {}
    histos = {}
    cl = req(rd, "counters", "readings")
    hl = req(rd, "histograms", "readings")
    if not isinstance(cl, list) or not isinstance(hl, list):
        raise InputError("readings: counters and histograms must be lists")
    for i, c in enumerate(cl):
        wh = "readings.counters[%d]" % i
        pid = req(c, "page", wh)
        if pid not in pages:
            raise InputError("%s: invalid page id %r" % (wh, pid))
        if pages[pid]["kind"] != "counters":
            raise InputError("%s: page %s is not a counter page" % (wh, pid))
        t = req(c, "target", wh)
        if t not in pages[pid]["targets"]:
            raise InputError("%s: target %r not on page %s" % (wh, t, pid))
        b = string(req(c, "boundary", wh), wh + ".boundary")
        key = (pid, t, b)
        if key in counters:
            raise InputError("%s: duplicate reading coordinate %s/%s/%s" % (wh, pid, t, b))
        rq = interval(req(c, "requests", wh), wh + ".requests")
        er = interval(req(c, "errors", wh), wh + ".errors")
        if b not in ops["boundaries"]:
            warn("%s: boundary %s is not in operations; reading not used" % (wh, b))
        counters[key] = {"requests": rq, "errors": er}
    wids = [w["id"] for w in ops["windows"]]
    for i, h in enumerate(hl):
        wh = "readings.histograms[%d]" % i
        pid = req(h, "page", wh)
        if pid not in pages:
            raise InputError("%s: invalid page id %r" % (wh, pid))
        if pages[pid]["kind"] != "histograms":
            raise InputError("%s: page %s is not a histogram page" % (wh, pid))
        t = req(h, "target", wh)
        if t not in pages[pid]["targets"]:
            raise InputError("%s: target %r not on page %s" % (wh, t, pid))
        w = string(req(h, "window", wh), wh + ".window")
        key = (pid, t, w)
        if key in histos:
            raise InputError("%s: duplicate reading coordinate %s/%s/%s" % (wh, pid, t, w))
        bins = req(h, "bins", wh)
        if bins is not None:
            if not isinstance(bins, list) or len(bins) != 4:
                raise InputError("%s: bins must be a list of four intervals or null" % wh)
            bins = tuple(interval(b, "%s.bins[%d]" % (wh, j)) for j, b in enumerate(bins))
            if any(b is None for b in bins):
                raise InputError("%s: individual bins cannot be null; use null for the whole histogram" % wh)
        if w not in wids:
            warn("%s: window %s is not in operations; reading not used" % (wh, w))
        histos[key] = bins
    used_b = []
    for w in ops["windows"]:
        for b in (w["start"], w["end"]):
            if b not in used_b:
                used_b.append(b)
    for pid, p in pages.items():
        for t in p["targets"]:
            if p["kind"] == "counters":
                for b in used_b:
                    if (pid, t, b) not in counters:
                        raise InputError("readings: missing counter coordinate %s/%s/%s" % (pid, t, b))
            else:
                for w in wids:
                    if (pid, t, w) not in histos:
                        raise InputError("readings: missing histogram coordinate %s/%s/%s" % (pid, t, w))
    return counters, histos


def parse_planning(pl):
    order = req(pl, "target_order", "planning")
    if not isinstance(order, list) or sorted(order) != sorted(TARGET_IDS) or len(order) != 8:
        raise InputError("planning.target_order must be a permutation of %s" % (TARGET_IDS,))
    regions_in = req(pl, "regions", "planning")
    if not isinstance(regions_in, dict) or not regions_in:
        raise InputError("planning.regions must be an object")
    regions = {}
    for r, v in regions_in.items():
        wh = "planning.regions.%s" % r
        frozen = req(v, "frozen", wh)
        if not isinstance(frozen, bool):
            raise InputError("%s.frozen must be boolean" % wh)
        regions[r] = {"activation_cost": num(req(v, "activation_cost", wh), wh + ".activation_cost", nonneg=True),
                      "max_blocks": integer(req(v, "max_blocks", wh), wh + ".max_blocks", lo=0),
                      "frozen": frozen}
    targets_in = req(pl, "targets", "planning")
    targets = {}
    for t in TARGET_IDS:
        wh = "planning.targets.%s" % t
        v = req(targets_in, t, "planning.targets")
        reg = req(v, "region", wh)
        if reg not in regions:
            raise InputError("%s: unknown region %r" % (wh, reg))
        rec = {"region": reg,
               "risk_weight": num(req(v, "risk_weight", wh), wh + ".risk_weight", positive=True)}
        for k in ("cost", "power", "reduction"):
            arr = req(v, k, wh)
            if not isinstance(arr, list) or len(arr) != 3:
                raise InputError("%s.%s must have three entries" % (wh, k))
            arr = [num(x, "%s.%s" % (wh, k), nonneg=True) for x in arr]
            if arr[0] != 0 or arr[1] > arr[2] or arr[0] > arr[1]:
                raise InputError("%s.%s must start at zero and be nondecreasing" % (wh, k))
            if k == "reduction" and arr[2] > 1:
                raise InputError("%s.reduction must not exceed 1" % wh)
            rec[k] = arr
        targets[t] = rec
    trig = num(req(pl, "slow_fraction_trigger", "planning"), "planning.slow_fraction_trigger")
    if not (0 < trig < 1):
        raise InputError("planning.slow_fraction_trigger must be in (0,1)")
    labels = pl.get("p95_labels", DEFAULT_P95_LABELS)
    if not isinstance(labels, list) or len(labels) != 4 or not all(isinstance(x, str) for x in labels):
        raise InputError("planning.p95_labels must be four strings")
    return {
        "order": list(order), "regions": regions, "targets": targets,
        "credit_budget": num(req(pl, "credit_budget", "planning"), "planning.credit_budget", nonneg=True),
        "power_budget": num(req(pl, "power_budget", "planning"), "planning.power_budget", nonneg=True),
        "max_active_regions": integer(req(pl, "max_active_regions", "planning"), "planning.max_active_regions", lo=0),
        "min_samples": num(req(pl, "minimum_latency_samples", "planning"), "planning.minimum_latency_samples", positive=True),
        "trigger": trig, "p95_labels": labels,
    }


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------

def reconstruct(manifest, ops, counters, histos):
    intervals = []
    for t in TARGET_IDS:
        cp = manifest["by_target"][t]["counters"]
        hp = manifest["by_target"][t]["histograms"]
        for w in ops["windows"]:
            vals = {}
            notes = []
            for m in METRICS:
                end = counters[(cp, t, w["end"])][m]
                if (t, w["id"], m) in ops["resets"]:
                    b = ops["resets"][(t, w["id"], m)]
                    if end is None:
                        vals[m] = None
                        notes.append("%s: end sample %s missing (reset baseline %s)" % (m, w["end"], b))
                        continue
                    est = end[1] - b
                    if est < 0:
                        raise InputError("inconsistent counters: %s %s %s end %s below reset baseline %s"
                                         % (t, w["id"], m, end[1], b))
                    vals[m] = (max(F(0), end[0] - b), est, end[2] - b)
                    notes.append("%s: documented reset, %s - baseline %s" % (m, w["end"], b))
                else:
                    start = counters[(cp, t, w["start"])][m]
                    if start is None or end is None:
                        vals[m] = None
                        miss = [x for x, v in ((w["start"], start), (w["end"], end)) if v is None]
                        notes.append("%s: missing endpoint %s" % (m, ",".join(miss)))
                        continue
                    est = end[1] - start[1]
                    if est < 0:
                        raise InputError(
                            "inconsistent counters: %s %s %s decreases from %s to %s without a documented reset"
                            % (t, w["id"], m, start[1], end[1]))
                    vals[m] = (max(F(0), end[0] - start[2]), est, end[2] - start[0])
                    notes.append("%s: %s - %s" % (m, w["end"], w["start"]))
            if vals["requests"] is not None and vals["errors"] is not None \
                    and vals["errors"][1] > vals["requests"][1]:
                raise InputError("inconsistent counters: %s %s errors %s exceed requests %s"
                                 % (t, w["id"], vals["errors"][1], vals["requests"][1]))
            if (t, w["id"]) in ops["maintenance"]:
                reason = "maintenance"
            elif vals["requests"] is None or vals["errors"] is None:
                reason = "missing_traffic"
            else:
                reason = "usable"
            bins = histos[(hp, t, w["id"])]
            intervals.append({
                "target": t, "window": w["id"], "reason": reason,
                "requests": vals["requests"], "errors": vals["errors"],
                "mean_requests_per_minute": None if vals["requests"] is None else vals["requests"][1] / w["minutes"],
                "minutes": w["minutes"], "counter_page": cp, "histogram_page": hp,
                "bins": bins, "histogram_available": bins is not None,
                "latency_included": reason == "usable" and bins is not None,
                "notes": notes,
            })
    return intervals


def summarize(intervals, plan, ops):
    order_w = [w["id"] for w in ops["windows"]]
    out = {}
    for t in TARGET_IDS:
        rows = [r for r in intervals if r["target"] == t]
        rows.sort(key=lambda r: order_w.index(r["window"]))
        usable = [r for r in rows if r["reason"] == "usable"]
        lat = [r for r in rows if r["latency_included"]]
        reqs = sum((r["requests"][1] for r in usable), F(0))
        errs = sum((r["errors"][1] for r in usable), F(0))
        e_lo = sum((r["errors"][0] for r in usable), F(0))
        e_hi = sum((r["errors"][2] for r in usable), F(0))
        pooled = [[F(0)] * 3 for _ in range(4)]
        for r in lat:
            for j in range(4):
                for k in range(3):
                    pooled[j][k] += r["bins"][j][k]
        est = [pooled[j][1] for j in range(4)]
        samples = sum(est)
        s_lo = sum(pooled[j][0] for j in range(4))
        s_hi = sum(pooled[j][2] for j in range(4))
        slow = est[2] + est[3]
        if samples > 0:
            slow_frac = slow / samples
            cum = F(0)
            p95 = None
            for j in range(4):
                cum += est[j]
                if cum >= F(95, 100) * samples:
                    p95 = plan["p95_labels"][j]
                    break
        else:
            slow_frac = None
            p95 = None
        slow_low = pooled[2][0] + pooled[3][0]
        slow_high = pooled[2][2] + pooled[3][2]
        fast_low = pooled[0][0] + pooled[1][0]
        fast_high = pooled[0][2] + pooled[1][2]
        lb = slow_low / (slow_low + fast_high) if (slow_low + fast_high) > 0 else F(0)
        ub = slow_high / (slow_high + fast_low) if (slow_high + fast_low) > 0 else F(1)
        eligible = samples >= plan["min_samples"] and slow_frac is not None and slow_frac > plan["trigger"]
        if eligible:
            stable = s_lo >= plan["min_samples"] and lb > plan["trigger"]
        else:
            stable = s_hi < plan["min_samples"] or ub <= plan["trigger"]
        region = plan["targets"][t]["region"]
        frozen = plan["regions"][region]["frozen"]
        if not eligible:
            block = "latency"
        elif frozen:
            block = "region_freeze"
        else:
            block = None
        out[t] = {
            "region": region,
            "usable_windows": [r["window"] for r in usable],
            "excluded_windows": {r["window"]: r["reason"] for r in rows if r["reason"] != "usable"},
            "histogram_windows": [r["window"] for r in lat],
            "requests": reqs, "errors": errs, "failure_fraction": div(errs, reqs),
            "error_bounds": [e_lo, e_hi],
            "pooled_bins": est, "pooled_bin_bounds": [[pooled[j][0], pooled[j][2]] for j in range(4)],
            "sample_bounds": [s_lo, s_hi], "samples": samples,
            "slow_fraction": slow_frac, "slow_bounds": [lb, ub], "p95_bin": p95,
            "latency_eligible": eligible, "eligibility_stable": stable,
            "rollout_eligible": eligible and not frozen, "block_reason": block,
        }
    return out


# --------------------------------------------------------------------------
# Static allocation
# --------------------------------------------------------------------------

def static_resources(tiers, plan):
    credits = F(0)
    power = F(0)
    blocks = defaultdict(int)
    active = set()
    for t in TARGET_IDS:
        k = tiers[t]
        tp = plan["targets"][t]
        credits += tp["cost"][k]
        power += tp["power"][k]
        if k > 0:
            active.add(tp["region"])
            blocks[tp["region"]] += k
    for r in active:
        credits += plan["regions"][r]["activation_cost"]
    return credits, power, sorted(active), blocks


def static_feasible(tiers, plan, summary, credit_budget):
    credits, power, active, blocks = static_resources(tiers, plan)
    if credits > credit_budget or power > plan["power_budget"]:
        return None
    if len(active) > plan["max_active_regions"]:
        return None
    for r, b in blocks.items():
        if b > plan["regions"][r]["max_blocks"]:
            return None
    for t in TARGET_IDS:
        if tiers[t] > 0 and not summary[t]["rollout_eligible"]:
            return None
    return credits, power, active


def objective(tiers, plan, summary):
    return sum((summary[t]["errors"] * plan["targets"][t]["risk_weight"]
                * plan["targets"][t]["reduction"][tiers[t]] for t in TARGET_IDS), F(0))


def enumerate_static(plan, summary, credit_budget):
    feas = []
    order = plan["order"]
    for combo in itertools.product(range(3), repeat=8):
        tiers = dict(zip(order, combo))
        r = static_feasible(tiers, plan, summary, credit_budget)
        if r is None:
            continue
        credits, power, active = r
        obj = objective(tiers, plan, summary)
        feas.append({"tiers": tiers, "vec": combo, "credits": credits, "power": power,
                     "active_regions": active, "objective": obj})
    feas.sort(key=lambda p: (-p["objective"], p["credits"], p["power"], p["vec"]))
    return feas


def plan_static(plan, summary):
    feas = enumerate_static(plan, summary, plan["credit_budget"])
    best = feas[0]
    all_stable = all(summary[t]["eligibility_stable"] for t in TARGET_IDS)
    lo_hi = {t: summary[t]["error_bounds"] for t in TARGET_IDS}
    margin = None
    closest = None
    for rival in feas[1:]:
        d = F(0)
        for t in TARGET_IDS:
            red = plan["targets"][t]["reduction"]
            c = plan["targets"][t]["risk_weight"] * (red[best["tiers"][t]] - red[rival["tiers"][t]])
            d += c * (lo_hi[t][0] if c > 0 else lo_hi[t][1])
        if margin is None or d < margin:
            margin = d
            closest = rival
    robust = all_stable if margin is None else (margin > 0 and all_stable)
    ob_lo = F(0)
    ob_hi = F(0)
    total_risk = F(0)
    for t in TARGET_IDS:
        w = plan["targets"][t]["risk_weight"]
        red = plan["targets"][t]["reduction"][best["tiers"][t]]
        ob_lo += w * red * lo_hi[t][0]
        ob_hi += w * red * lo_hi[t][1]
        total_risk += w * summary[t]["errors"]
    slack = {
        "credits": plan["credit_budget"] - best["credits"],
        "power": plan["power_budget"] - best["power"],
        "active_regions": plan["max_active_regions"] - len(best["active_regions"]),
    }
    res = {
        "tiers": {t: best["tiers"][t] for t in plan["order"]},
        "credits": best["credits"], "power": best["power"],
        "active_regions": best["active_regions"],
        "objective": best["objective"], "objective_bounds": [ob_lo, ob_hi],
        "total_weighted_risk": total_risk,
        "residual_risk": total_risk - best["objective"],
        "robust_margin": margin, "robust": robust,
        "closest_rival": None if closest is None else {
            "tiers": {t: closest["tiers"][t] for t in plan["order"]},
            "objective": closest["objective"], "credits": closest["credits"], "power": closest["power"]},
        "feasible_vectors": len(feas),
        "slack": slack,
        "blocked": {t: summary[t]["block_reason"] for t in plan["order"] if summary[t]["block_reason"]},
    }
    scenarios = []
    for b in (max(F(0), plan["credit_budget"] - 2), plan["credit_budget"] + 2):
        fb = enumerate_static(plan, summary, b)[0]
        scenarios.append({"credit_budget": b, "tiers": {t: fb["tiers"][t] for t in plan["order"]},
                          "credits": fb["credits"], "power": fb["power"],
                          "active_regions": fb["active_regions"], "objective": fb["objective"]})
    return res, scenarios


# --------------------------------------------------------------------------
# Execution schedule
# --------------------------------------------------------------------------

def parse_execution(pl, plan):
    ex = pl.get("execution")
    if ex is None:
        return None
    wh = "planning.execution"
    if not isinstance(ex, dict):
        raise InputError("%s must be an object" % wh)
    H = integer(req(ex, "horizon", wh), wh + ".horizon (invalid horizon)", lo=3, hi=6)
    reveal = integer(req(ex, "reveal", wh), wh + ".reveal (invalid reveal boundary)", lo=0, hi=H)
    cands = req(ex, "candidates", wh)
    if not isinstance(cands, list) or len(cands) > 4:
        raise InputError("%s.candidates must be a list of at most four targets" % wh)
    for c in cands:
        if c not in TARGET_IDS:
            raise InputError("%s.candidates: invalid candidate id %r" % (wh, c))
    if len(set(cands)) != len(cands):
        raise InputError("%s.candidates: duplicate candidate ids" % wh)
    max_jobs = integer(req(ex, "max_jobs", wh), wh + ".max_jobs", lo=0)
    crews = req(ex, "crews", wh)
    if not isinstance(crews, list) or len(crews) != H:
        raise InputError("%s.crews must have exactly horizon=%d entries" % (wh, H))
    crews = [integer(c, wh + ".crews", lo=0) for c in crews]
    gap = integer(req(ex, "region_gap", wh), wh + ".region_gap", lo=0)
    disruption = num(req(ex, "disruption", wh), wh + ".disruption", nonneg=True)
    if disruption > 1:
        raise InputError("%s.disruption must be in [0,1]" % wh)
    durations = req(ex, "durations", wh)
    warmups = req(ex, "warmups", wh)
    blackouts = ex.get("blackouts", {}) or {}
    for name, d in (("durations", durations), ("warmups", warmups), ("blackouts", blackouts)):
        if not isinstance(d, dict):
            raise InputError("%s.%s must be an object" % (wh, name))
        for k in d:
            if k not in TARGET_IDS:
                raise InputError("%s.%s: invalid target id %r" % (wh, name, k))
    dur = {}
    warm = {}
    black = {}
    for t, v in durations.items():
        if not isinstance(v, list) or len(v) != 2:
            raise InputError("%s.durations.%s must have two entries (invalid job duration)" % (wh, t))
        dur[t] = [integer(x, "%s.durations.%s (invalid job duration)" % (wh, t), lo=1, hi=2) for x in v]
    for t, v in warmups.items():
        if not isinstance(v, list) or len(v) != 2:
            raise InputError("%s.warmups.%s must have two entries" % (wh, t))
        warm[t] = [integer(x, "%s.warmups.%s" % (wh, t), lo=0, hi=1) for x in v]
    for t, v in blackouts.items():
        if not isinstance(v, list):
            raise InputError("%s.blackouts.%s must be a list" % (wh, t))
        black[t] = set(integer(x, "%s.blackouts.%s (invalid blackout slot)" % (wh, t), lo=0, hi=H - 1) for x in v)
    for c in cands:
        if c not in dur:
            raise InputError("%s.durations: missing candidate %s (invalid job duration)" % (wh, c))
        if c not in warm:
            raise InputError("%s.warmups: missing candidate %s" % (wh, c))
        black.setdefault(c, set())
    deps = []
    for i, d in enumerate(ex.get("dependencies", []) or []):
        dw = "%s.dependencies[%d]" % (wh, i)
        t = req(d, "target", dw)
        r = req(d, "requires", dw)
        for x in (t, r):
            if x not in cands:
                raise InputError("%s: %r is not a candidate (invalid candidate id)" % (dw, x))
        tier = integer(req(d, "tier", dw), dw + ".tier", lo=1, hi=2)
        rt = integer(req(d, "requires_tier", dw), dw + ".requires_tier", lo=1, hi=2)
        deps.append((t, tier, r, rt))
    # cycle detection including intrinsic tier-1 -> tier-2 edges
    graph = defaultdict(set)
    for c in cands:
        graph[(c, 2)].add((c, 1))
    for t, tier, r, rt in deps:
        graph[(t, tier)].add((r, rt))
    color = {}

    def dfs(n):
        color[n] = 1
        for m in graph[n]:
            if color.get(m) == 1:
                raise InputError("%s.dependencies: cyclic dependency through %s/%d" % (wh, m[0], m[1]))
            if color.get(m) is None:
                dfs(m)
        color[n] = 2

    for n in list(graph):
        if color.get(n) is None:
            dfs(n)
    links = []
    for i, l in enumerate(ex.get("links", []) or []):
        lw = "%s.links[%d]" % (wh, i)
        left = req(l, "left", lw)
        right = req(l, "right", lw)
        owner = req(l, "owner", lw)
        for x in (left, right, owner):
            if x not in TARGET_IDS:
                raise InputError("%s: invalid target id %r" % (lw, x))
        if owner not in (left, right):
            raise InputError("%s: owner must be left or right" % lw)
        factor = num(req(l, "factor", lw), lw + ".factor", nonneg=True)
        if factor > 1:
            raise InputError("%s.factor must be <= 1" % lw)
        links.append((left, right, owner, factor))
    cases_in = req(ex, "cases", wh)
    if not isinstance(cases_in, list) or not cases_in:
        raise InputError("%s.cases must be a nonempty list" % wh)
    cases = []
    for i, c in enumerate(cases_in):
        cw = "%s.cases[%d]" % (wh, i)
        cid = string(req(c, "id", cw), cw + ".id")
        if cid in [x["id"] for x in cases]:
            raise InputError("%s: duplicate case id %s" % (cw, cid))
        expo = req(c, "exposure", cw)
        if not isinstance(expo, dict):
            raise InputError("%s.exposure must be an object" % cw)
        e = {}
        for t in TARGET_IDS:
            arr = req(expo, t, cw + ".exposure")
            if not isinstance(arr, list) or len(arr) != H:
                raise InputError("%s.exposure.%s must have exactly horizon=%d entries" % (cw, t, H))
            e[t] = [num(x, "%s.exposure.%s (negative/nonfinite exposure)" % (cw, t), nonneg=True) for x in arr]
        cases.append({"id": cid, "exposure": e})
    signals = None
    if "signals" in ex:
        sg = ex["signals"]
        sw = wh + ".signals"
        if not isinstance(sg, dict):
            raise InputError("%s must be an object" % sw)
        coarse = integer(req(sg, "coarse_at", sw), sw + ".coarse_at (invalid boundary)", lo=0, hi=H)
        exact = integer(req(sg, "exact_at", sw), sw + ".exact_at (invalid boundary)", lo=0, hi=H)
        if coarse > exact:
            raise InputError("%s: coarse_at %d must not exceed exact_at %d (invalid boundary order)" % (sw, coarse, exact))
        groups = req(sg, "groups", sw)
        if not isinstance(groups, list):
            raise InputError("%s.groups must be a list (missing group labels)" % sw)
        if len(groups) != len(cases):
            raise InputError("%s.groups has %d labels but there are %d cases (mismatched group count)"
                             % (sw, len(groups), len(cases)))
        for g in groups:
            if not isinstance(g, str) or not g:
                raise InputError("%s.groups: group labels must be nonempty strings, got %r" % (sw, g))
        weight = num(req(sg, "sum_weight", sw), sw + ".sum_weight (invalid valuation weight)")
        if not (0 <= weight <= F(1, 2)):
            raise InputError("%s.sum_weight must be in [0,0.5] (invalid valuation weight)" % sw)
        signals = {"coarse_at": coarse, "exact_at": exact, "groups": list(groups), "sum_weight": weight}
    else:
        warn("planning.execution.signals absent; staged policy not computed")
    return {"H": H, "reveal": reveal, "cands": list(cands), "max_jobs": max_jobs, "crews": crews,
            "gap": gap, "disruption": disruption, "dur": dur, "warm": warm, "black": black,
            "deps": deps, "links": links, "cases": cases, "signals": signals}


class Scheduler:
    def __init__(self, ex, plan, summary):
        self.ex = ex
        self.plan = plan
        self.summary = summary
        self.H = ex["H"]
        self.order = plan["order"]
        self.tidx = {t: i for i, t in enumerate(self.order)}
        self.cands = [t for t in self.order if t in ex["cands"]]
        self.errors = {t: summary[t]["errors"] for t in TARGET_IDS}
        self.R = {t: self.errors[t] * plan["targets"][t]["risk_weight"] for t in TARGET_IDS}
        self.ncase = len(ex["cases"])
        self.baselines = [sum((self.R[t] * sum(c["exposure"][t], F(0)) for t in TARGET_IDS), F(0))
                          for c in ex["cases"]]
        self._build_options()
        self._enumerate()

    # -- options per candidate --
    def _build_options(self):
        H = self.H
        ex = self.ex
        self.options = {}
        for t in self.cands:
            opts = [()]
            if self.summary[t]["rollout_eligible"]:
                d1, d2 = ex["dur"][t]
                w1, w2 = ex["warm"][t]
                bl = ex["black"][t]
                for s1 in range(H):
                    f1, r1 = s1 + d1, s1 + d1 + w1
                    if r1 > H or any(s in bl for s in range(s1, f1)):
                        continue
                    j1 = (s1, self.tidx[t], 1, f1, r1)
                    opts.append((j1,))
                    for s2 in range(max(r1, f1 + ex["gap"]), H):
                        f2, r2 = s2 + d2, s2 + d2 + w2
                        if r2 > H or any(s in bl for s in range(s2, f2)):
                            continue
                        opts.append((j1, (s2, self.tidx[t], 2, f2, r2)))
            recs = []
            for jobs in opts:
                recs.append(self._option_record(t, jobs))
            self.options[t] = recs

    def _option_record(self, t, jobs):
        H = self.H
        occ = [False] * H
        eff = [0] * H
        for s in range(H):
            for j in jobs:
                if j[0] <= s < j[3]:
                    occ[s] = True
            if not occ[s]:
                eff[s] = max([j[2] for j in jobs if j[4] <= s] or [0])
        red = self.plan["targets"][t]["reduction"]
        effred = [red[k] for k in eff]
        w = self.plan["targets"][t]["risk_weight"]
        coefs = []
        for c in self.ex["cases"]:
            e = c["exposure"][t]
            coef = sum(((w * e[s] * (effred[s] - (self.ex["disruption"] if occ[s] else 0))) for s in range(H)), F(0))
            coefs.append(coef)
        tier = max([j[2] for j in jobs] or [0])
        return {"target": t, "jobs": jobs, "occ": occ, "eff": eff, "effred": effred,
                "coef": coefs, "contrib": [cf * self.errors[t] for cf in coefs], "tier": tier}

    def _effred(self, t, choice):
        if t in self.cpos:
            return self.options[t][choice[self.cpos[t]]]["effred"]
        return [F(0)] * self.H

    def _link_coef(self, link, choice, ci):
        left, right, owner, factor = link
        el = self._effred(left, choice)
        er = self._effred(right, choice)
        e = self.ex["cases"][ci]["exposure"][owner]
        w = self.plan["targets"][owner]["risk_weight"]
        return sum((w * e[s] * factor * min(el[s], er[s]) for s in range(self.H)), F(0))

    # -- enumerate all feasible complete schedules --
    def _enumerate(self):
        H = self.H
        ex = self.ex
        self.cpos = {t: i for i, t in enumerate(self.cands)}
        region = {t: self.plan["targets"][t]["region"] for t in TARGET_IDS}
        schedules = []
        static_cache = {}
        n = len(self.cands)
        crews_used = [0] * H
        reg_jobs = defaultdict(list)
        choice = [0] * n
        link_cache = {}

        def leaf():
            tiers = {t: 0 for t in TARGET_IDS}
            jobs = []
            for i, t in enumerate(self.cands):
                o = self.options[t][choice[i]]
                tiers[t] = o["tier"]
                jobs.extend(o["jobs"])
            key = tuple(tiers[t] for t in self.order)
            if key not in static_cache:
                static_cache[key] = static_feasible(tiers, self.plan, self.summary, self.plan["credit_budget"])
            st = static_cache[key]
            if st is None:
                return
            ready = {}
            for j in jobs:
                ready[(self.order[j[1]], j[2])] = j[4]
            for (t, tier, r, rt) in ex["deps"]:
                start = None
                for j in jobs:
                    if self.order[j[1]] == t and j[2] == tier:
                        start = j[0]
                if start is None:
                    continue
                if (r, rt) not in ready or ready[(r, rt)] > start:
                    return
            ch = tuple(choice)
            nets = []
            coefs = []
            for ci in range(self.ncase):
                cf = {t: F(0) for t in TARGET_IDS}
                for i, t in enumerate(self.cands):
                    cf[t] += self.options[t][ch[i]]["coef"][ci]
                for li, link in enumerate(ex["links"]):
                    lk = (li, ci, ch[self.cpos[link[0]]] if link[0] in self.cpos else -1,
                          ch[self.cpos[link[1]]] if link[1] in self.cpos else -1)
                    if lk not in link_cache:
                        link_cache[lk] = self._link_coef(link, ch, ci)
                    cf[link[2]] += link_cache[lk]
                coefs.append(cf)
                nets.append(sum((cf[t] * self.errors[t] for t in TARGET_IDS), F(0)))
            sv = []
            for t in self.order:
                s1 = s2 = H + 1
                if t in self.cpos:
                    for j in self.options[t][ch[self.cpos[t]]]["jobs"]:
                        if j[2] == 1:
                            s1 = j[0]
                        else:
                            s2 = j[0]
                sv.extend([s1, s2])
            schedules.append({"choice": ch, "jobs": tuple(sorted(jobs)), "tiers": tiers,
                              "credits": st[0], "power": st[1], "active_regions": st[2],
                              "nets": nets, "coefs": coefs, "sv": tuple(sv)})

        def rec(i, njobs):
            if i == n:
                leaf()
                return
            t = self.cands[i]
            r = region[t]
            for oi, o in enumerate(self.options[t]):
                jobs = o["jobs"]
                if njobs + len(jobs) > ex["max_jobs"]:
                    continue
                ok = True
                for j in jobs:
                    for s in range(j[0], j[3]):
                        if crews_used[s] + 1 > ex["crews"][s]:
                            ok = False
                    for (a, b) in reg_jobs[r]:
                        if not (j[0] >= b + ex["gap"] or a >= j[3] + ex["gap"]):
                            ok = False
                if not ok:
                    # crews must be checked cumulatively for both jobs of the option
                    continue
                for j in jobs:
                    for s in range(j[0], j[3]):
                        crews_used[s] += 1
                if any(crews_used[s] > ex["crews"][s] for s in range(H)):
                    for j in jobs:
                        for s in range(j[0], j[3]):
                            crews_used[s] -= 1
                    continue
                for j in jobs:
                    reg_jobs[r].append((j[0], j[3]))
                choice[i] = oi
                rec(i + 1, njobs + len(jobs))
                for j in jobs:
                    reg_jobs[r].pop()
                    for s in range(j[0], j[3]):
                        crews_used[s] -= 1
            choice[i] = 0

        rec(0, 0)
        self.schedules = schedules

    # -- policy solver (fixed, full reveal and staged are special cases) --
    def solve(self, coarse, exact, labels, weight):
        scheds = self.schedules
        nc = self.ncase
        label_order = []
        for l in labels:
            if l not in label_order:
                label_order.append(l)
        members = {l: [k for k in range(nc) if labels[k] == l] for l in label_order}

        def pkey(s, b):
            return tuple(j for j in s["jobs"] if j[0] < b)

        groups_c = defaultdict(list)
        for idx, s in enumerate(scheds):
            groups_c[pkey(s, coarse)].append(idx)
        best = None
        for gidx in groups_c.values():
            label_opts = {}
            for l in label_order:
                subs = defaultdict(list)
                for idx in gidx:
                    subs[pkey(scheds[idx], exact)].append(idx)
                opts = []
                for sub in subs.values():
                    pick = {}
                    for k in members[l]:
                        pick[k] = min(sub, key=lambda i: (-scheds[i]["nets"][k], scheds[i]["credits"],
                                                          scheds[i]["power"], scheds[i]["sv"]))
                    nets = [scheds[pick[k]]["nets"][k] for k in members[l]]
                    opts.append({"m": min(nets), "s": sum(nets, F(0)),
                                 "cred": sum((scheds[pick[k]]["credits"] for k in members[l]), F(0)),
                                 "pow": sum((scheds[pick[k]]["power"] for k in members[l]), F(0)),
                                 "sv": tuple(x for k in members[l] for x in scheds[pick[k]]["sv"]),
                                 "pick": pick})
                label_opts[l] = opts
            # threshold search for (value, min, sum)
            prep = {}
            for l, opts in label_opts.items():
                srt = sorted(opts, key=lambda o: -o["m"])
                ms = [-o["m"] for o in srt]
                pmax = []
                cur = None
                for o in srt:
                    cur = o["s"] if cur is None or o["s"] > cur else cur
                    pmax.append(cur)
                prep[l] = (ms, pmax)

            def smax(l, T):
                ms, pmax = prep[l]
                pos = bisect.bisect_right(ms, -T)
                return None if pos == 0 else pmax[pos - 1]

            cand_T = sorted({o["m"] for opts in label_opts.values() for o in opts}, reverse=True)
            bestT = None
            for T in cand_T:
                tot = F(0)
                ok = True
                for l in label_order:
                    v = smax(l, T)
                    if v is None:
                        ok = False
                        break
                    tot += v
                if not ok:
                    continue
                val = T + weight * tot
                if bestT is None or (val, T) > (bestT[0], bestT[1]):
                    bestT = (val, T, tot)
            val, T, tot = bestT
            pick = {}
            cred = F(0)
            pw = F(0)
            for l in label_order:
                target_s = smax(l, T)
                ch = min((o for o in label_opts[l] if o["m"] >= T and o["s"] == target_s),
                         key=lambda o: (o["cred"], o["pow"], o["sv"]))
                pick.update(ch["pick"])
                cred += ch["cred"]
                pw += ch["pow"]
            svc = tuple(x for k in range(nc) for x in scheds[pick[k]]["sv"])
            key = (-val, -T, -tot, cred, pw, svc)
            if best is None or key < best[0]:
                best = (key, pick)
        key, pick = best
        nets = [scheds[pick[k]]["nets"][k] for k in range(nc)]
        return {"pick": [pick[k] for k in range(nc)], "value": -key[0], "worst": min(nets),
                "total": sum(nets, F(0)), "credits": key[3], "power": key[4]}

    # -- output helpers --
    def action_list(self, jobs):
        return [{"target": self.order[j[1]], "tier": j[2], "start": j[0], "finish": j[3], "ready": j[4]}
                for j in sorted(jobs)]

    def case_record(self, idx, ci):
        s = self.schedules[idx]
        lo = F(0)
        hi = F(0)
        for t in TARGET_IDS:
            c = s["coefs"][ci][t]
            elo, ehi = self.summary[t]["error_bounds"]
            if c > 0:
                lo += c * elo
                hi += c * ehi
            elif c < 0:
                lo += c * ehi
                hi += c * elo
        net = s["nets"][ci]
        return {"id": self.ex["cases"][ci]["id"], "baseline": out_num(self.baselines[ci]),
                "net": out_num(net), "net_bounds": [out_num(lo), out_num(hi)],
                "residual": out_num(self.baselines[ci] - net),
                "net_error_coefficients": {t: out_num(s["coefs"][ci][t]) for t in self.order}}

    def schedule_body(self, idx):
        s = self.schedules[idx]
        slots = []
        peak = 0
        for slot in range(self.H):
            occupied = []
            eff = {}
            for t in self.order:
                if t in self.cpos:
                    o = self.options[t][s["choice"][self.cpos[t]]]
                    if o["occ"][slot]:
                        occupied.append(t)
                    eff[t] = o["eff"][slot]
                else:
                    eff[t] = 0
            ready_t = {}
            for t in self.order:
                ready_t[t] = max([j[2] for j in s["jobs"] if self.order[j[1]] == t and j[4] <= slot] or [0])
            peak = max(peak, len(occupied))
            slots.append({"slot": slot, "occupied": occupied, "effective_tiers": eff,
                          "installed_ready_tiers": ready_t})
        return {"actions": self.action_list(s["jobs"]), "slots": slots,
                "final_tiers": {t: s["tiers"][t] for t in self.order},
                "credits": out_num(s["credits"]), "power": out_num(s["power"]),
                "active_regions": s["active_regions"], "peak_crews": peak,
                "start_vector": list(s["sv"])}

    def branches(self, res):
        out = []
        for ci, idx in enumerate(res["pick"]):
            b = self.schedule_body(idx)
            b["case"] = self.case_record(idx, ci)
            out.append(b)
        return out

    def common_actions(self, idxs, bound):
        sets = [set(j for j in self.schedules[i]["jobs"] if j[0] < bound) for i in idxs]
        common = set.intersection(*sets) if sets else set()
        assert all(s == common for s in sets)
        return self.action_list(common)


def execution_output(ex, plan, summary):
    sch = Scheduler(ex, plan, summary)
    nc = sch.ncase
    H = ex["H"]
    fixed = sch.solve(H, H, ["all"] * nc, F(0))
    idx = fixed["pick"][0]
    assert all(i == idx for i in fixed["pick"])
    out = sch.schedule_body(idx)
    out["cases"] = [sch.case_record(idx, ci) for ci in range(nc)]
    out["worst_case_net"] = out_num(fixed["worst"])
    out["total_case_net"] = out_num(fixed["total"])
    out["feasible_schedules"] = len(sch.schedules)
    out["horizon"] = H
    r = ex["reveal"]
    cont = sch.solve(r, r, ["case:%d" % k for k in range(nc)], F(0))
    out["contingency"] = {
        "reveal": r, "prefix": sch.common_actions(cont["pick"], r),
        "branches": sch.branches(cont),
        "worst_case_net": out_num(cont["worst"]), "total_case_net": out_num(cont["total"]),
        "total_credits": out_num(cont["credits"]), "total_power": out_num(cont["power"]),
        "information_value": out_num(cont["worst"] - fixed["worst"]),
    }
    sg = ex["signals"]
    if sg is not None:
        st = sch.solve(sg["coarse_at"], sg["exact_at"], sg["groups"], sg["sum_weight"])
        gp = []
        for label in sorted(set(sg["groups"])):
            ks = [k for k in range(nc) if sg["groups"][k] == label]
            gp.append({"signal": label, "case_ids": [ex["cases"][k]["id"] for k in ks],
                       "actions": sch.common_actions([st["pick"][k] for k in ks], sg["exact_at"])})
        fixed_value = fixed["worst"] + sg["sum_weight"] * fixed["total"]
        out["staged"] = {
            "coarse_at": sg["coarse_at"], "exact_at": sg["exact_at"], "sum_weight": out_num(sg["sum_weight"]),
            "prefix": sch.common_actions(st["pick"], sg["coarse_at"]),
            "group_prefixes": gp, "branches": sch.branches(st),
            "policy_value": out_num(st["value"]), "worst_case_net": out_num(st["worst"]),
            "total_case_net": out_num(st["total"]),
            "total_credits": out_num(st["credits"]), "total_power": out_num(st["power"]),
            "fixed_schedule_policy_value": out_num(fixed_value),
        }
    else:
        out["staged"] = None
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run(args):
    registry = parse_registry(args.registry)
    ops = parse_operations(load_json(args.operations))
    manifest = parse_manifest(load_json(args.manifest))
    planning_raw = load_json(args.planning)
    plan = parse_planning(planning_raw)
    counters, histos = parse_readings(load_json(args.readings), manifest, ops)
    ex = parse_execution(planning_raw, plan)

    intervals = reconstruct(manifest, ops, counters, histos)
    summary = summarize(intervals, plan, ops)
    static, scenarios = plan_static(plan, summary)
    execution = execution_output(ex, plan, summary) if ex is not None else None

    order = plan["order"]
    worder = [w["id"] for w in ops["windows"]]
    intervals.sort(key=lambda r: (order.index(r["target"]), worder.index(r["window"])))
    pages = manifest["pages"]
    inv = {
        "selected": manifest["selected"], "rejected": manifest["rejected"],
        "by_target": {t: manifest["by_target"][t] for t in order},
        "pages": [{"id": p, "kind": pages[p]["kind"], "file": pages[p]["file"], "targets": pages[p]["targets"],
                   "status": "rejected" if p in manifest["rejected"] else "selected",
                   "reason": ("superseded (whole page) by %s per export-manifest.json" %
                              ", ".join(manifest["superseded_by"][p]))
                   if p in manifest["rejected"] else "terminal revision; authoritative"}
                  for p in sorted(pages)],
        "registry": {t: registry[t] for t in order},
    }
    out_intervals = []
    for r in intervals:
        out_intervals.append({
            "target": r["target"], "window": r["window"], "reason": r["reason"],
            "requests": out_iv(r["requests"]), "errors": out_iv(r["errors"]),
            "mean_requests_per_minute": out_num(r["mean_requests_per_minute"]),
            "minutes": out_num(r["minutes"]),
            "counter_page": r["counter_page"], "histogram_page": r["histogram_page"],
            "histogram_available": r["histogram_available"],
            "latency_included": r["latency_included"],
            "bins": None if r["bins"] is None else [out_iv(b) for b in r["bins"]],
            "derivation": r["notes"],
        })
    out_targets = {}
    for t in order:
        s = summary[t]
        out_targets[t] = {
            "region": s["region"],
            "usable_windows": s["usable_windows"], "excluded_windows": s["excluded_windows"],
            "histogram_windows": s["histogram_windows"],
            "requests": out_num(s["requests"]), "errors": out_num(s["errors"]),
            "failure_fraction": out_num(s["failure_fraction"]),
            "error_bounds": [out_num(x) for x in s["error_bounds"]],
            "pooled_bins": [out_num(x) for x in s["pooled_bins"]],
            "pooled_bin_bounds": [[out_num(a), out_num(b)] for a, b in s["pooled_bin_bounds"]],
            "sample_bounds": [out_num(x) for x in s["sample_bounds"]],
            "samples": out_num(s["samples"]),
            "slow_fraction": out_num(s["slow_fraction"]),
            "slow_bounds": [out_num(x) for x in s["slow_bounds"]],
            "p95_bin": s["p95_bin"],
            "latency_eligible": s["latency_eligible"], "eligibility_stable": s["eligibility_stable"],
            "rollout_eligible": s["rollout_eligible"], "block_reason": s["block_reason"],
            "weighted_risk": out_num(s["errors"] * plan["targets"][t]["risk_weight"]),
        }
    freq = sum((summary[t]["requests"] for t in TARGET_IDS), F(0))
    ferr = sum((summary[t]["errors"] for t in TARGET_IDS), F(0))
    fleet = {"requests": out_num(freq), "errors": out_num(ferr), "failure_fraction": out_num(div(ferr, freq))}

    def conv(d):
        if isinstance(d, dict):
            return {k: conv(v) for k, v in d.items()}
        if isinstance(d, list):
            return [conv(v) for v in d]
        if isinstance(d, F):
            return out_num(d)
        return d

    result = {
        "inventory": inv,
        "intervals": out_intervals,
        "targets": out_targets,
        "fleet": fleet,
        "plan": conv(static),
        "scenarios": conv(scenarios),
        "execution": execution,
    }
    text = json.dumps(result, indent=1, allow_nan=False)
    d = os.path.dirname(os.path.abspath(args.out))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("readings", "manifest", "operations", "planning", "registry", "out"):
        ap.add_argument("--" + a, required=True)
    args = ap.parse_args(argv)
    try:
        run(args)
    except InputError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return 2
    except RecursionError as exc:
        sys.stderr.write("ERROR: recursion failure (%s)\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
