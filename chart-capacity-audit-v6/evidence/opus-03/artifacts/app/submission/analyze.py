#!/usr/bin/env python3
"""Reconcile dashboard readings and compute an admissible capacity rollout.

Standard library only. See /app/policy.md, interfaces.md and
execution-policy.md for the semantics implemented here.
"""
import argparse
import csv
import itertools
import json
import math
import os
import sys
from datetime import datetime

METRICS = ("requests", "errors")
REASONS = ("usable", "maintenance", "missing_traffic")


class InputError(Exception):
    pass


def fail(msg):
    raise InputError(msg)


# ----------------------------------------------------------------- helpers
def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def num(x, where, nonneg=True):
    if not is_num(x):
        fail("%s: expected a finite number, got %r" % (where, x))
    if nonneg and x < 0:
        fail("%s: negative value %r" % (where, x))
    return x


def intval(x, where, lo=None, hi=None):
    if not is_int(x):
        fail("%s: expected an integer, got %r" % (where, x))
    if lo is not None and x < lo:
        fail("%s: %r below minimum %r" % (where, x, lo))
    if hi is not None and x > hi:
        fail("%s: %r above maximum %r" % (where, x, hi))
    return x


def interval(v, where):
    if not isinstance(v, list) or len(v) != 3:
        fail("%s: interval must be a list [low, estimate, high], got %r" % (where, v))
    lo, est, hi = (num(x, where) for x in v)
    if not (lo <= est <= hi):
        fail("%s: reversed or inconsistent interval %r (need low <= estimate <= high)" % (where, v))
    return [lo, est, hi]


def load_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        fail("%s file not found: %s" % (what, path))
    except json.JSONDecodeError as exc:
        fail("%s is not valid JSON (%s): %s" % (what, path, exc))


def clean(x):
    """Round floats for presentation; keep integers exact."""
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15:
            return int(x)
        return round(x, 9)
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def key6(x):
    return round(x, 6)


# ----------------------------------------------------------------- inputs
def load_registry(path, target_order):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except FileNotFoundError:
        fail("registry file not found: %s" % path)
    reg = {}
    for i, row in enumerate(rows):
        t = (row.get("target") or "").strip()
        if not t:
            fail("registry row %d: missing target" % (i + 2))
        if t in reg:
            fail("registry: duplicate target %s" % t)
        reg[t] = {k: (v or "").strip() for k, v in row.items() if k}
    if set(reg) != set(target_order):
        fail("registry targets %s do not match planning target_order %s"
             % (sorted(reg), list(target_order)))
    return reg


def load_planning(path):
    p = load_json(path, "planning")
    if not isinstance(p, dict):
        fail("planning: top level must be an object")
    order = p.get("target_order")
    if not isinstance(order, list) or not order or len(set(order)) != len(order) \
            or not all(isinstance(t, str) for t in order):
        fail("planning.target_order must be a list of distinct target IDs")
    regions = p.get("regions")
    if not isinstance(regions, dict) or not regions:
        fail("planning.regions must be an object")
    for r, cfg in regions.items():
        if not isinstance(cfg, dict):
            fail("planning.regions.%s must be an object" % r)
        num(cfg.get("activation_cost"), "planning.regions.%s.activation_cost" % r)
        intval(cfg.get("max_blocks"), "planning.regions.%s.max_blocks" % r, 0)
        if not isinstance(cfg.get("frozen"), bool):
            fail("planning.regions.%s.frozen must be boolean" % r)
    targets = p.get("targets")
    if not isinstance(targets, dict) or set(targets) != set(order):
        fail("planning.targets must define exactly the target_order IDs")
    for t in order:
        cfg = targets[t]
        if not isinstance(cfg, dict):
            fail("planning.targets.%s must be an object" % t)
        if cfg.get("region") not in regions:
            fail("planning.targets.%s.region %r is not a configured region" % (t, cfg.get("region")))
        w = num(cfg.get("risk_weight"), "planning.targets.%s.risk_weight" % t)
        if w <= 0:
            fail("planning.targets.%s.risk_weight must be positive" % t)
        for k in ("cost", "power", "reduction"):
            arr = cfg.get(k)
            if not isinstance(arr, list) or len(arr) != 3:
                fail("planning.targets.%s.%s must have three entries" % (t, k))
            for i, v in enumerate(arr):
                num(v, "planning.targets.%s.%s[%d]" % (t, k, i))
            if arr[0] != 0 or not (arr[0] <= arr[1] <= arr[2]):
                fail("planning.targets.%s.%s must start at zero and be nondecreasing" % (t, k))
            if k == "reduction" and arr[2] > 1:
                fail("planning.targets.%s.reduction must be <= 1" % t)
    num(p.get("credit_budget"), "planning.credit_budget")
    num(p.get("power_budget"), "planning.power_budget")
    intval(p.get("max_active_regions"), "planning.max_active_regions", 0)
    ms = num(p.get("minimum_latency_samples"), "planning.minimum_latency_samples")
    if ms < 1:
        fail("planning.minimum_latency_samples must be >= 1")
    tr = num(p.get("slow_fraction_trigger"), "planning.slow_fraction_trigger")
    if not (0 < tr < 1):
        fail("planning.slow_fraction_trigger must be in (0,1)")
    labels = p.get("p95_labels", ["<=100", "(100,300]", "(300,1000]", ">1000"])
    if not isinstance(labels, list) or len(labels) != 4:
        fail("planning.p95_labels must have four labels")
    p["p95_labels"] = labels
    return p


def load_manifest(path, target_ids):
    m = load_json(path, "manifest")
    if not isinstance(m, dict) or not isinstance(m.get("pages"), list):
        fail("manifest: expected an object with a 'pages' list")
    pages = {}
    for i, pg in enumerate(m["pages"]):
        if not isinstance(pg, dict):
            fail("manifest.pages[%d] must be an object" % i)
        pid = pg.get("id")
        if not isinstance(pid, str) or not pid:
            fail("manifest.pages[%d]: invalid page id %r" % (i, pid))
        if pid in pages:
            fail("manifest: duplicate page id %s" % pid)
        kind = pg.get("kind")
        if kind not in ("counters", "histograms"):
            fail("manifest page %s: invalid kind %r" % (pid, kind))
        tg = pg.get("targets")
        if not isinstance(tg, list) or not tg or len(set(tg)) != len(tg):
            fail("manifest page %s: targets must be a nonempty list of distinct IDs" % pid)
        for t in tg:
            if t not in target_ids:
                fail("manifest page %s: unknown target %r" % (pid, t))
        units = pg.get("series_units")
        need = METRICS if kind == "counters" else ("samples",)
        if not isinstance(units, dict):
            fail("manifest page %s: missing series_units" % pid)
        for k in need:
            u = units.get(k)
            if not is_num(u) or u <= 0:
                fail("manifest page %s: invalid unit multiplier for %s: %r" % (pid, k, u))
        pages[pid] = {"id": pid, "kind": kind, "targets": list(tg), "file": pg.get("file"),
                      "revision": pg.get("revision"), "series_units": units}
    edges = m.get("supersedes", [])
    if not isinstance(edges, list):
        fail("manifest.supersedes must be a list")
    clean_edges = []
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            fail("manifest.supersedes[%d] must be an object" % i)
        new, old = e.get("new"), e.get("old")
        for pid in (new, old):
            if pid not in pages:
                fail("manifest.supersedes[%d]: invalid page id %r" % (i, pid))
        if new == old:
            fail("manifest.supersedes[%d]: supersession cycle (page %s supersedes itself)" % (i, new))
        if pages[new]["kind"] != pages[old]["kind"]:
            fail("manifest.supersedes[%d]: %s and %s are different page kinds" % (i, new, old))
        clean_edges.append((new, old, e.get("scope")))
    # cycle detection over new -> old edges
    adj = {p: [] for p in pages}
    for new, old, _ in clean_edges:
        adj[new].append(old)
    state = {}

    def visit(n, stack):
        state[n] = 1
        for nxt in adj[n]:
            if state.get(nxt) == 1:
                fail("manifest: supersession cycle %s" % " -> ".join(stack + [n, nxt]))
            if state.get(nxt) is None:
                visit(nxt, stack + [n])
        state[n] = 2

    for p in sorted(pages):
        if state.get(p) is None:
            visit(p, [])
    rejected = {old for _, old, _ in clean_edges}
    selected = sorted(p for p in pages if p not in rejected)
    by_target = {}
    for t in sorted(target_ids):
        entry = {}
        for kind in ("counters", "histograms"):
            sel = [p for p in selected if pages[p]["kind"] == kind and t in pages[p]["targets"]]
            if len(sel) != 1:
                fail("manifest: target %s has %d selected %s pages (%s); exactly one required"
                     % (t, len(sel), kind, sel))
            entry[kind] = sel[0]
        by_target[t] = entry
    superseded_by = {}
    for new, old, _ in clean_edges:
        superseded_by.setdefault(old, []).append(new)
    return {"pages": pages, "edges": clean_edges, "selected": selected,
            "rejected": sorted(rejected), "by_target": by_target,
            "superseded_by": {k: sorted(v) for k, v in superseded_by.items()}}


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_operations(path, target_ids, warnings):
    o = load_json(path, "operations")
    if not isinstance(o, dict):
        fail("operations: top level must be an object")
    bl = o.get("boundaries")
    if not isinstance(bl, list) or not bl:
        fail("operations.boundaries must be a nonempty list")
    bounds = {}
    for i, b in enumerate(bl):
        if not isinstance(b, dict) or not isinstance(b.get("id"), str):
            fail("operations.boundaries[%d]: invalid boundary" % i)
        if b["id"] in bounds:
            fail("operations: duplicate boundary %s" % b["id"])
        bounds[b["id"]] = {"id": b["id"], "utc": b.get("utc"), "pos": i,
                           "time": parse_time(b["utc"]) if isinstance(b.get("utc"), str) else None}
    wl = o.get("windows")
    if not isinstance(wl, list) or not wl:
        fail("operations.windows must be a nonempty list")
    windows = []
    seen = set()
    for i, w in enumerate(wl):
        if not isinstance(w, dict) or not isinstance(w.get("id"), str):
            fail("operations.windows[%d]: invalid window" % i)
        wid = w["id"]
        if wid in seen:
            fail("operations: duplicate window %s" % wid)
        seen.add(wid)
        for k in ("start", "end"):
            if w.get(k) not in bounds:
                fail("operations window %s: %s boundary %r is not defined" % (wid, k, w.get(k)))
        if w["start"] == w["end"]:
            fail("operations window %s: start and end boundaries are identical" % wid)
        mins = num(w.get("minutes"), "operations window %s minutes" % wid)
        if mins <= 0:
            fail("operations window %s: minutes must be positive" % wid)
        windows.append({"id": wid, "start": w["start"], "end": w["end"], "minutes": mins, "pos": i})
    all_timed = all(b["time"] is not None for b in bounds.values())

    def bkey(bid):
        b = bounds[bid]
        return (b["time"].timestamp() if all_timed else 0, b["pos"])

    windows.sort(key=lambda w: (bkey(w["start"]), bkey(w["end"]), w["pos"]))
    for a, b in zip(windows, windows[1:]):
        if bkey(b["start"]) < bkey(a["end"]):
            fail("operations: windows %s and %s overlap" % (a["id"], b["id"]))
    for w in windows:
        if bkey(w["end"]) <= bkey(w["start"]):
            fail("operations window %s ends before it starts" % w["id"])
    wids = {w["id"] for w in windows}
    resets = {}
    for i, r in enumerate(o.get("resets", []) or []):
        where = "operations.resets[%d]" % i
        if not isinstance(r, dict):
            fail("%s must be an object" % where)
        if r.get("target") not in target_ids:
            fail("%s: unknown target %r" % (where, r.get("target")))
        if r.get("metric") not in METRICS:
            fail("%s: unknown metric %r" % (where, r.get("metric")))
        base = num(r.get("baseline"), where + ".baseline")
        if r.get("window") not in wids:
            warnings.append("%s references window %r which is not an operations window; ignored"
                            % (where, r.get("window")))
            continue
        k = (r["target"], r["window"], r["metric"])
        if k in resets and resets[k] != base:
            fail("%s: conflicting duplicate reset for %s" % (where, "/".join(k)))
        resets[k] = base
    maint = set()
    for i, m in enumerate(o.get("maintenance", []) or []):
        where = "operations.maintenance[%d]" % i
        if not isinstance(m, dict) or m.get("target") not in target_ids:
            fail("%s: invalid maintenance target" % where)
        if m.get("window") not in wids:
            warnings.append("%s references window %r which is not an operations window; ignored"
                            % (where, m.get("window")))
            continue
        maint.add((m["target"], m["window"]))
    return {"bounds": bounds, "windows": windows, "resets": resets, "maintenance": maint,
            "deployment": o.get("deployment")}


def load_readings(path, manifest, ops, warnings):
    r = load_json(path, "readings")
    if not isinstance(r, dict):
        fail("readings: top level must be an object")
    if r.get("units") != "base-counts":
        fail("readings: invalid units %r; readings must be in 'base-counts'" % r.get("units"))
    pages = manifest["pages"]
    for k in ("counters", "histograms"):
        if not isinstance(r.get(k), list):
            fail("readings.%s must be a list" % k)
    bounds = ops["bounds"]
    wids = {w["id"] for w in ops["windows"]}
    counters, hists = {}, {}
    for i, c in enumerate(r["counters"]):
        where = "readings.counters[%d]" % i
        if not isinstance(c, dict):
            fail("%s must be an object" % where)
        pid, t, b = c.get("page"), c.get("target"), c.get("boundary")
        if pid not in pages:
            fail("%s: invalid page id %r" % (where, pid))
        if pages[pid]["kind"] != "counters":
            fail("%s: page %s is not a counter page" % (where, pid))
        if t not in pages[pid]["targets"]:
            fail("%s: target %r is not on page %s" % (where, t, pid))
        if not isinstance(b, str):
            fail("%s: invalid boundary %r" % (where, b))
        for k in METRICS:
            if k not in c:
                fail("%s: missing '%s' (use null for an unknown metric)" % (where, k))
        key = (pid, t, b)
        if key in counters:
            fail("%s: duplicate reading coordinate %s/%s/%s" % (where, pid, t, b))
        vals = {}
        for k in METRICS:
            vals[k] = None if c[k] is None else interval(c[k], "%s.%s" % (where, k))
        counters[key] = vals
        if b not in bounds:
            warnings.append("%s: boundary %s is not in operations; reading retained but unused" % (where, b))
    for i, h in enumerate(r["histograms"]):
        where = "readings.histograms[%d]" % i
        if not isinstance(h, dict):
            fail("%s must be an object" % where)
        pid, t, w = h.get("page"), h.get("target"), h.get("window")
        if pid not in pages:
            fail("%s: invalid page id %r" % (where, pid))
        if pages[pid]["kind"] != "histograms":
            fail("%s: page %s is not a histogram page" % (where, pid))
        if t not in pages[pid]["targets"]:
            fail("%s: target %r is not on page %s" % (where, t, pid))
        if not isinstance(w, str):
            fail("%s: invalid window %r" % (where, w))
        if "bins" not in h:
            fail("%s: missing 'bins' (use null for an unavailable histogram)" % where)
        key = (pid, t, w)
        if key in hists:
            fail("%s: duplicate reading coordinate %s/%s/%s" % (where, pid, t, w))
        bins = h["bins"]
        if bins is not None:
            if not isinstance(bins, list) or len(bins) != 4:
                fail("%s: malformed bin list; expected four [low,estimate,high] intervals or null" % where)
            bins = [interval(v, "%s.bins[%d]" % (where, j)) for j, v in enumerate(bins)]
        hists[key] = bins
        if w not in wids:
            warnings.append("%s: window %s is not in operations; reading retained but unused" % (where, w))
    need_b = sorted({w["start"] for w in ops["windows"]} | {w["end"] for w in ops["windows"]})
    for pid, pg in sorted(pages.items()):
        for t in pg["targets"]:
            if pg["kind"] == "counters":
                for b in need_b:
                    if (pid, t, b) not in counters:
                        fail("readings: missing counter coordinate %s/%s/%s" % (pid, t, b))
            else:
                for w in ops["windows"]:
                    if (pid, t, w["id"]) not in hists:
                        fail("readings: missing histogram coordinate %s/%s/%s" % (pid, t, w["id"]))
    return counters, hists


# ----------------------------------------------------------------- traffic
def reconstruct(target, window, page, counters, ops):
    out, notes = {}, []
    for m in METRICS:
        start = counters[(page, target, window["start"])][m]
        end = counters[(page, target, window["end"])][m]
        rkey = (target, window["id"], m)
        if rkey in ops["resets"]:
            base = ops["resets"][rkey]
            if end is None:
                out[m] = None
                notes.append("%s: documented reset (baseline %s) but end sample %s is missing"
                             % (m, base, window["end"]))
                continue
            est = end[1] - base
            if est < 0:
                fail("inconsistent counter: %s %s %s end sample %s is below documented reset baseline %s"
                     % (page, target, m, end[1], base))
            out[m] = [max(0, end[0] - base), est, end[2] - base]
            notes.append("%s: documented reset at start of %s; end %s minus baseline %s "
                         "(old-epoch start sample %s ignored)" % (m, window["id"], window["end"], base,
                                                                  window["start"]))
        else:
            if start is None or end is None:
                out[m] = None
                miss = [b for b, v in ((window["start"], start), (window["end"], end)) if v is None]
                notes.append("%s: required endpoint(s) %s UNKNOWN and no reset baseline; not reconstructable"
                             % (m, ",".join(miss)))
                continue
            est = end[1] - start[1]
            if est < 0:
                fail("inconsistent counter: %s %s %s falls from %s at %s to %s at %s in %s without a "
                     "documented reset" % (page, target, m, start[1], window["start"], end[1],
                                           window["end"], window["id"]))
            out[m] = [max(0, end[0] - start[2]), est, end[2] - start[0]]
            notes.append("%s: end %s minus start %s" % (m, window["end"], window["start"]))
    if out["requests"] is not None and out["errors"] is not None \
            and out["errors"][1] > out["requests"][1] + 1e-9:
        fail("inconsistent counter: %s %s %s reconstructs more errors (%s) than requests (%s)"
             % (page, target, window["id"], out["errors"][1], out["requests"][1]))
    return out, notes


# ----------------------------------------------------------------- latency
def latency_summary(bins_list, planning):
    minimum = planning["minimum_latency_samples"]
    trig = planning["slow_fraction_trigger"]
    est = [0.0] * 4
    lo = [0.0] * 4
    hi = [0.0] * 4
    for bins in bins_list:
        for j in range(4):
            lo[j] += bins[j][0]
            est[j] += bins[j][1]
            hi[j] += bins[j][2]
    samples = sum(est)
    if samples > 0:
        slow = (est[2] + est[3]) / samples
        cum, p95 = 0.0, None
        for j in range(4):
            cum += est[j]
            if cum >= 0.95 * samples - 1e-9 * max(1.0, samples):
                p95 = planning["p95_labels"][j]
                break
    else:
        slow, p95 = None, None
    slow_lo, slow_hi = lo[2] + lo[3], hi[2] + hi[3]
    fast_lo, fast_hi = lo[0] + lo[1], hi[0] + hi[1]
    lb = slow_lo / (slow_lo + fast_hi) if (slow_lo + fast_hi) > 0 else 0.0
    ub = slow_hi / (slow_hi + fast_lo) if (slow_hi + fast_lo) > 0 else 1.0
    eligible = samples >= minimum and slow is not None and slow > trig
    s_lo, s_hi = sum(lo), sum(hi)
    if eligible:
        stable = s_lo >= minimum and lb > trig
    else:
        stable = s_hi < minimum or ub <= trig
    return {"pooled_bins": est, "pooled_low": lo, "pooled_high": hi, "sample_bounds": [s_lo, s_hi],
            "samples": samples, "slow_fraction": slow, "slow_bounds": [lb, ub], "p95_bin": p95,
            "latency_eligible": eligible, "eligibility_stable": stable}


# ----------------------------------------------------------------- static plan
def static_metrics(tiers, planning):
    order = planning["target_order"]
    tg, rg = planning["targets"], planning["regions"]
    credits = power = 0
    active = set()
    blocks = {}
    for t, k in zip(order, tiers):
        credits += tg[t]["cost"][k]
        power += tg[t]["power"][k]
        if k > 0:
            r = tg[t]["region"]
            active.add(r)
            blocks[r] = blocks.get(r, 0) + k
    for r in active:
        credits += rg[r]["activation_cost"]
    return credits, power, sorted(active), blocks


def static_feasible(tiers, planning, allowed, budget):
    credits, power, active, blocks = static_metrics(tiers, planning)
    if any(k > 0 and not allowed[t] for t, k in zip(planning["target_order"], tiers)):
        return None
    if credits > budget + 1e-9 or power > planning["power_budget"] + 1e-9:
        return None
    if len(active) > planning["max_active_regions"]:
        return None
    for r, b in blocks.items():
        if b > planning["regions"][r]["max_blocks"]:
            return None
    return credits, power, active


def optimize_static(planning, errors, allowed, budget):
    order = planning["target_order"]
    tg = planning["targets"]
    best = None
    feas = []
    for tiers in itertools.product((0, 1, 2), repeat=len(order)):
        f = static_feasible(tiers, planning, allowed, budget)
        if f is None:
            continue
        obj = sum(errors[t] * tg[t]["risk_weight"] * tg[t]["reduction"][k] for t, k in zip(order, tiers))
        key = (-key6(obj), f[0], f[1], tiers)
        feas.append(tiers)
        if best is None or key < best[0]:
            best = (key, tiers, obj, f)
    _, tiers, obj, (credits, power, active) = best
    return {"tiers": dict(zip(order, tiers)), "credits": credits, "power": power,
            "active_regions": active, "objective": obj, "_vec": tiers, "_feasible": feas}


# ----------------------------------------------------------------- execution
def validate_execution(planning, rollout_eligible):
    ex = planning.get("execution")
    if ex is None:
        return None
    if not isinstance(ex, dict):
        fail("planning.execution must be an object")
    order = planning["target_order"]
    H = intval(ex.get("horizon"), "execution.horizon", 1, 24)
    rv = ex.get("reveal")
    if not is_int(rv) or rv < 0 or rv > H:
        fail("execution.reveal must be an integer in 0..horizon (%d), got %r" % (H, rv))
    cands = ex.get("candidates")
    if not isinstance(cands, list) or len(set(map(str, cands))) != len(cands):
        fail("execution.candidates must be a list of distinct target IDs")
    for c in cands:
        if c not in order:
            fail("execution.candidates: invalid candidate ID %r" % (c,))
    maxj = intval(ex.get("max_jobs"), "execution.max_jobs", 0)
    crews = ex.get("crews")
    if not isinstance(crews, list) or len(crews) != H:
        fail("execution.crews must have exactly horizon=%d entries" % H)
    for i, c in enumerate(crews):
        intval(c, "execution.crews[%d]" % i, 0)
    gap = intval(ex.get("region_gap"), "execution.region_gap", 0)
    disr = num(ex.get("disruption"), "execution.disruption")
    if disr > 1:
        fail("execution.disruption must be in [0,1]")
    durs, warms, blk = ex.get("durations"), ex.get("warmups"), ex.get("blackouts", {})
    if not isinstance(durs, dict) or not isinstance(warms, dict) or not isinstance(blk, dict):
        fail("execution.durations/warmups/blackouts must be objects")
    D, Wm, B = {}, {}, {}
    for t in cands:
        d = durs.get(t)
        if not isinstance(d, list) or len(d) != 2:
            fail("execution.durations.%s must list two job durations" % t)
        D[t] = [intval(x, "execution.durations.%s (invalid job duration)" % t, 1) for x in d]
        w = warms.get(t)
        if not isinstance(w, list) or len(w) != 2:
            fail("execution.warmups.%s must list two warmups" % t)
        Wm[t] = [intval(x, "execution.warmups.%s" % t, 0) for x in w]
        b = blk.get(t, [])
        if not isinstance(b, list):
            fail("execution.blackouts.%s must be a list" % t)
        for s in b:
            intval(s, "execution.blackouts.%s (invalid blackout slot)" % t, 0, H - 1)
        B[t] = set(b)
    for t in blk:
        if t not in order:
            fail("execution.blackouts: invalid target %r" % t)
        for s in blk[t] if isinstance(blk[t], list) else []:
            intval(s, "execution.blackouts.%s (invalid blackout slot)" % t, 0, H - 1)
    deps = []
    for i, d in enumerate(ex.get("dependencies", []) or []):
        where = "execution.dependencies[%d]" % i
        if not isinstance(d, dict):
            fail("%s must be an object" % where)
        if d.get("target") not in cands or d.get("requires") not in cands:
            fail("%s: dependency targets must be candidates" % where)
        tier = d.get("tier")
        rt = d.get("requires_tier")
        if tier not in (1, 2) or rt not in (1, 2) or isinstance(tier, bool) or isinstance(rt, bool):
            fail("%s: tiers must be 1 or 2" % where)
        deps.append((d["target"], tier, d["requires"], rt))
    # cycle detection including intrinsic tier1 -> tier2 edges
    nodes = [(t, k) for t in cands for k in (1, 2)]
    adj = {n: [] for n in nodes}
    for t in cands:
        adj[(t, 1)].append((t, 2))
    for t, k, rq, rk in deps:
        adj[(rq, rk)].append((t, k))
    state = {}

    def visit(n):
        state[n] = 1
        for m in adj[n]:
            if state.get(m) == 1:
                fail("execution.dependencies: cyclic dependency involving %s tier %d" % m)
            if state.get(m) is None:
                visit(m)
        state[n] = 2

    for n in nodes:
        if state.get(n) is None:
            visit(n)
    links = []
    for i, l in enumerate(ex.get("links", []) or []):
        where = "execution.links[%d]" % i
        if not isinstance(l, dict):
            fail("%s must be an object" % where)
        for k in ("left", "right", "owner"):
            if l.get(k) not in order:
                fail("%s: invalid %s target %r" % (where, k, l.get(k)))
        f = num(l.get("factor"), where + ".factor")
        links.append((l["left"], l["right"], l["owner"], f))
    cases = ex.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("execution.cases must be a nonempty list")
    cl = []
    ids = set()
    for i, c in enumerate(cases):
        where = "execution.cases[%d]" % i
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
            fail("%s: invalid case id" % where)
        if c["id"] in ids:
            fail("%s: duplicate case id %s" % (where, c["id"]))
        ids.add(c["id"])
        exp = c.get("exposure")
        if not isinstance(exp, dict):
            fail("%s: exposure must be an object" % where)
        E = {}
        for t in order:
            arr = exp.get(t)
            if not isinstance(arr, list) or len(arr) != H:
                fail("%s: exposure for %s must have horizon=%d entries" % (where, t, H))
            E[t] = [num(x, "%s.exposure.%s (negative/nonfinite exposure)" % (where, t)) for x in arr]
        for t in exp:
            if t not in order:
                fail("%s: exposure for unknown target %r" % (where, t))
        cl.append({"id": c["id"], "E": E})
    sig = ex.get("signals")
    signals = None
    if sig is not None:
        if not isinstance(sig, dict):
            fail("execution.signals must be an object")
        ca, ea = sig.get("coarse_at"), sig.get("exact_at")
        if not is_int(ca) or not is_int(ea):
            fail("execution.signals: coarse_at/exact_at must be integers")
        if not (0 <= ca <= ea <= H):
            fail("execution.signals: need 0 <= coarse_at (%r) <= exact_at (%r) <= horizon (%d)" % (ca, ea, H))
        groups = sig.get("groups")
        if not isinstance(groups, list):
            fail("execution.signals.groups must be a list of group labels")
        if len(groups) != len(cl):
            fail("execution.signals.groups has %d labels for %d cases" % (len(groups), len(cl)))
        for g in groups:
            if not isinstance(g, str) or not g:
                fail("execution.signals.groups: labels must be nonempty strings, got %r" % (g,))
        sw = sig.get("sum_weight")
        if not is_num(sw) or not (0 <= sw <= 0.5):
            fail("execution.signals.sum_weight must be a number in [0,0.5], got %r" % (sw,))
        signals = {"coarse_at": ca, "exact_at": ea, "groups": list(groups), "sum_weight": sw}
    return {"H": H, "reveal": rv, "cands": [t for t in order if t in cands and rollout_eligible[t]],
            "all_cands": list(cands), "max_jobs": maxj, "crews": crews, "gap": gap, "disr": disr,
            "D": D, "W": Wm, "B": B, "deps": deps, "links": links, "cases": cl, "signals": signals}


def enumerate_schedules(ex, planning, allowed):
    """All feasible complete schedules. A schedule is a tuple of jobs
    (target, tier, start, finish, ready) sorted canonically."""
    H, gap = ex["H"], ex["gap"]
    order = planning["target_order"]
    region = {t: planning["targets"][t]["region"] for t in order}
    opts = {}
    for t in ex["cands"]:
        d, w, bo = ex["D"][t], ex["W"][t], ex["B"][t]
        lst = [()]

        def ok(s, f):
            return all(x not in bo for x in range(s, f))

        for s1 in range(H):
            f1 = s1 + d[0]
            r1 = f1 + w[0]
            if r1 > H or not ok(s1, f1):
                continue
            j1 = (t, 1, s1, f1, r1)
            lst.append((j1,))
            for s2 in range(max(r1, f1 + gap), H):
                f2 = s2 + d[1]
                r2 = f2 + w[1]
                if r2 > H or not ok(s2, f2):
                    continue
                lst.append((j1, (t, 2, s2, f2, r2)))
        opts[t] = [o for o in lst if len(o) <= ex["max_jobs"]]
    cands = ex["cands"]
    results = []
    crews = ex["crews"]

    def conflict(a, b):
        return not (a[2] >= b[3] + gap or b[2] >= a[3] + gap)

    def rec(i, jobs, usage):
        if i == len(cands):
            if feasible_leaf(jobs):
                results.append(tuple(jobs))
            return
        for o in opts[cands[i]]:
            if len(jobs) + len(o) > ex["max_jobs"]:
                continue
            bad = False
            nu = list(usage)
            for j in o:
                for s in range(j[2], j[3]):
                    nu[s] += 1
                    if nu[s] > crews[s]:
                        bad = True
                        break
                if bad:
                    break
                for k in jobs:
                    if region[k[0]] == region[j[0]] and conflict(j, k):
                        bad = True
                        break
                if bad:
                    break
            if bad:
                continue
            rec(i + 1, jobs + list(o), nu)

    def feasible_leaf(jobs):
        ready = {(j[0], j[1]): j[4] for j in jobs}
        for t, k, rq, rk in ex["deps"]:
            if (t, k) in ready:
                job = [j for j in jobs if j[0] == t and j[1] == k][0]
                if (rq, rk) not in ready or ready[(rq, rk)] > job[2]:
                    return False
        tiers = final_tiers(jobs, order)
        return static_feasible(tiers, planning, allowed, planning["credit_budget"]) is not None

    rec(0, [], [0] * H)
    tidx = {t: i for i, t in enumerate(order)}
    return [tuple(sorted(s, key=lambda j: (j[2], tidx[j[0]], j[1]))) for s in results]


def final_tiers(jobs, order):
    ft = {t: 0 for t in order}
    for j in jobs:
        ft[j[0]] = max(ft[j[0]], j[1])
    return tuple(ft[t] for t in order)


def slot_state(jobs, order, H):
    slots = []
    for s in range(H):
        occ = set()
        ready_tier = {t: 0 for t in order}
        for j in jobs:
            if j[2] <= s < j[3]:
                occ.add(j[0])
            if j[4] <= s:
                ready_tier[j[0]] = max(ready_tier[j[0]], j[1])
        eff = {t: (0 if t in occ else ready_tier[t]) for t in order}
        slots.append((occ, eff, ready_tier))
    return slots


def case_coefficients(jobs, ex, planning, case, slots=None):
    order = planning["target_order"]
    tg = planning["targets"]
    H = ex["H"]
    if slots is None:
        slots = slot_state(jobs, order, H)
    E = case["E"]
    k = {t: 0.0 for t in order}
    for s in range(H):
        occ, eff, _ = slots[s]
        for t in order:
            w = tg[t]["risk_weight"]
            red = tg[t]["reduction"][eff[t]]
            k[t] += w * E[t][s] * (red - (ex["disr"] if t in occ else 0.0))
        for left, right, owner, f in ex["links"]:
            m = min(tg[left]["reduction"][eff[left]], tg[right]["reduction"][eff[right]])
            k[owner] += tg[owner]["risk_weight"] * E[owner][s] * f * m
    return k


def schedule_record(jobs, ex, planning, errors, err_bounds, allowed):
    order = planning["target_order"]
    H = ex["H"]
    slots = slot_state(jobs, order, H)
    tiers = final_tiers(jobs, order)
    credits, power, active = static_feasible(tiers, planning, allowed, planning["credit_budget"])
    sv = []
    for t in order:
        for k in (1, 2):
            st = [j[2] for j in jobs if j[0] == t and j[1] == k]
            sv.append(st[0] if st else H + 1)
    cases = []
    for c in ex["cases"]:
        coef = case_coefficients(jobs, ex, planning, c, slots)
        net = sum(coef[t] * errors[t] for t in order)
        lo = sum(coef[t] * (err_bounds[t][0] if coef[t] > 0 else err_bounds[t][1]) for t in order)
        hi = sum(coef[t] * (err_bounds[t][1] if coef[t] > 0 else err_bounds[t][0]) for t in order)
        base = sum(planning["targets"][t]["risk_weight"] * errors[t] * sum(c["E"][t]) for t in order)
        cases.append({"id": c["id"], "baseline": base, "net": net, "net_bounds": [lo, hi],
                      "residual": base - net, "coefficients": coef})
    return {"jobs": jobs, "slots": slots, "tiers": tiers, "credits": credits, "power": power,
            "active": active, "sv": tuple(sv), "cases": cases,
            "peak": max([len(s[0]) for s in slots] or [0])}


def render_schedule(rec, planning, H):
    order = planning["target_order"]
    actions = [{"target": j[0], "tier": j[1], "start": j[2], "finish": j[3], "ready": j[4]}
               for j in rec["jobs"]]
    slots = []
    for s, (occ, eff, rt) in enumerate(rec["slots"]):
        slots.append({"slot": s, "occupied": [t for t in order if t in occ],
                      "effective_tiers": dict(eff), "ready_tiers": dict(rt)})
    return {"actions": actions, "slots": slots, "final_tiers": dict(zip(order, rec["tiers"])),
            "credits": rec["credits"], "power": rec["power"], "active_regions": rec["active"],
            "peak_crews": rec["peak"], "start_vector": list(rec["sv"])}


def render_case(c):
    return {"id": c["id"], "baseline": c["baseline"], "net": c["net"], "net_bounds": c["net_bounds"],
            "residual": c["residual"],
            "error_coefficients": c["coefficients"]}


def prefix_key(jobs, b):
    return tuple(j[:3] for j in jobs if j[2] < b)


def optimize_execution(ex, planning, errors, err_bounds, allowed):
    order = planning["target_order"]
    H = ex["H"]
    scheds = enumerate_schedules(ex, planning, allowed)
    recs = [schedule_record(s, ex, planning, errors, err_bounds, allowed) for s in scheds]
    ncase = len(ex["cases"])
    nets = [tuple(key6(c["net"]) for c in r["cases"]) for r in recs]

    # ---- fixed schedule: max-min, then sum, credits, power, start vector
    def fkey(i):
        n = nets[i]
        return (-min(n), -key6(sum(n)), recs[i]["credits"], recs[i]["power"], recs[i]["sv"])

    fi = min(range(len(recs)), key=fkey)
    fixed = render_schedule(recs[fi], planning, H)
    fixed["cases"] = [render_case(c) for c in recs[fi]["cases"]]
    fixed["worst_case_net"] = min(c["net"] for c in recs[fi]["cases"])
    fixed["total_case_net"] = sum(c["net"] for c in recs[fi]["cases"])
    fixed["feasible_schedules_searched"] = len(recs)

    # per-case best branch within groups of schedules sharing a prefix key
    def case_key(i, c):
        return (-nets[i][c], recs[i]["credits"], recs[i]["power"], recs[i]["sv"])

    def best_by_prefix(b):
        groups = {}
        for i, r in enumerate(recs):
            pk = prefix_key(r["jobs"], b)
            g = groups.get(pk)
            if g is None:
                groups[pk] = [i] * ncase
            else:
                for c in range(ncase):
                    if case_key(i, c) < case_key(g[c], c):
                        g[c] = i
        return groups

    def render_branches(choice):
        out = []
        for c, i in enumerate(choice):
            b = render_schedule(recs[i], planning, H)
            b["case"] = render_case(recs[i]["cases"][c])
            out.append(b)
        return out

    def totals(choice):
        ns = [recs[i]["cases"][c]["net"] for c, i in enumerate(choice)]
        return {"worst_case_net": min(ns), "total_case_net": sum(ns),
                "total_credits": sum(recs[i]["credits"] for i in choice),
                "total_power": sum(recs[i]["power"] for i in choice)}

    def render_prefix(i, b):
        return [{"target": j[0], "tier": j[1], "start": j[2], "finish": j[3], "ready": j[4]}
                for j in recs[i]["jobs"] if j[2] < b]

    # ---- contingency (full reveal)
    rv = ex["reveal"]
    groups = best_by_prefix(rv)

    def ckey(choice):
        n = [nets[i][c] for c, i in enumerate(choice)]
        return (-min(n), -key6(sum(n)), sum(recs[i]["credits"] for i in choice),
                sum(recs[i]["power"] for i in choice), tuple(itertools.chain(*(recs[i]["sv"] for i in choice))))

    cchoice = min((tuple(g) for g in groups.values()), key=ckey)
    contingency = {"reveal": rv, "prefix": render_prefix(cchoice[0], rv),
                   "branches": render_branches(cchoice)}
    contingency.update(totals(cchoice))
    contingency["information_value"] = contingency["worst_case_net"] - fixed["worst_case_net"]

    staged = None
    if ex["signals"] is not None:
        staged = optimize_staged(ex, recs, nets, case_key, ncase)
        sg = ex["signals"]
        choice = staged["choice"]
        labels = sg["groups"]
        gp = []
        for lab in sorted(set(labels)):
            members = [c for c in range(ncase) if labels[c] == lab]
            gp.append({"signal": lab, "case_ids": [ex["cases"][c]["id"] for c in members],
                       "actions": render_prefix(choice[members[0]], sg["exact_at"])})
        out = {"coarse_at": sg["coarse_at"], "exact_at": sg["exact_at"], "sum_weight": sg["sum_weight"],
               "prefix": render_prefix(choice[0], sg["coarse_at"]), "group_prefixes": gp,
               "branches": render_branches(choice)}
        t = totals(choice)
        out["policy_value"] = t["worst_case_net"] + sg["sum_weight"] * t["total_case_net"]
        out.update(t)
        staged = out
    return fixed, contingency, staged


def optimize_staged(ex, recs, nets, case_key, ncase):
    sg = ex["signals"]
    a, b, labels, wsum = sg["coarse_at"], sg["exact_at"], sg["groups"], sg["sum_weight"]
    # best branch per case for every exact-boundary prefix Q
    byQ = {}
    for i, r in enumerate(recs):
        q = prefix_key(r["jobs"], b)
        g = byQ.get(q)
        if g is None:
            byQ[q] = [i] * ncase
        else:
            for c in range(ncase):
                if case_key(i, c) < case_key(g[c], c):
                    g[c] = i
    byP = {}
    for q, g in byQ.items():
        p = tuple(j for j in q if j[2] < a)
        byP.setdefault(p, []).append(g)
    glabels = sorted(set(labels))
    members = {lab: [c for c in range(ncase) if labels[c] == lab] for lab in glabels}

    def tb(choice_part, cs):
        return (sum(recs[choice_part[c]]["credits"] for c in cs),
                sum(recs[choice_part[c]]["power"] for c in cs),
                tuple(itertools.chain(*(recs[choice_part[c]]["sv"] for c in cs))))

    best = None
    for p, glist in byP.items():
        per_group = []
        for lab in glabels:
            cs = members[lab]
            options = {}
            for g in glist:
                nv = tuple(nets[g[c]][c] for c in cs)
                cand = {c: g[c] for c in cs}
                cur = options.get(nv)
                if cur is None or tb(cand, cs) < tb(cur, cs):
                    options[nv] = cand
            items = list(options.items())
            if len(glabels) > 1:
                items = pareto(items)
            per_group.append(items)
        for combo in itertools.product(*per_group):
            choice = [None] * ncase
            for nv, cand in combo:
                for c, i in cand.items():
                    choice[c] = i
            n = [nets[choice[c]][c] for c in range(ncase)]
            mn, sm = min(n), key6(sum(n))
            val = key6(mn + wsum * sm)
            key = (-val, -mn, -sm, sum(recs[i]["credits"] for i in choice),
                   sum(recs[i]["power"] for i in choice),
                   tuple(itertools.chain(*(recs[i]["sv"] for i in choice))))
            if best is None or key < best[0]:
                best = (key, choice)
    return {"choice": best[1]}


def pareto(items):
    """Keep options whose net vectors are not dominated (weakly everywhere,
    strictly somewhere) by another option."""
    items = sorted(items, key=lambda it: tuple(-x for x in it[0]))
    kept = []
    for nv, cand in items:
        dom = False
        for kv, _ in kept:
            if all(k >= v for k, v in zip(kv, nv)) and any(k > v for k, v in zip(kv, nv)):
                dom = True
                break
        if not dom:
            kept.append((nv, cand))
    return kept


# ----------------------------------------------------------------- main
def run(args):
    warnings = []
    planning = load_planning(args.planning)
    order = planning["target_order"]
    registry = load_registry(args.registry, order)
    manifest = load_manifest(args.manifest, set(order))
    ops = load_operations(args.operations, set(order), warnings)
    counters, hists = load_readings(args.readings, manifest, ops, warnings)
    windows = ops["windows"]
    tg, rg = planning["targets"], planning["regions"]

    intervals = []
    per_target = {}
    for t in order:
        cp = manifest["by_target"][t]["counters"]
        hp = manifest["by_target"][t]["histograms"]
        rows = []
        for w in windows:
            rec, notes = reconstruct(t, w, cp, counters, ops)
            bins = hists.get((hp, t, w["id"]))
            if (t, w["id"]) in ops["maintenance"]:
                reason = "maintenance"
                notes.append("listed as maintenance in operations.json; excluded from demand and latency")
            elif rec["requests"] is None or rec["errors"] is None:
                reason = "missing_traffic"
                notes.append("traffic not reconstructable; not treated as zero; histogram cannot substitute")
            else:
                reason = "usable"
            inc = reason == "usable" and bins is not None
            if reason == "usable" and bins is None:
                notes.append("histogram unavailable; traffic still usable but no latency samples joined")
            row = {"target": t, "window": w["id"], "start_boundary": w["start"], "end_boundary": w["end"],
                   "minutes": w["minutes"], "reason": reason,
                   "requests": rec["requests"], "errors": rec["errors"],
                   "mean_requests_per_minute": (None if rec["requests"] is None
                                                else rec["requests"][1] / w["minutes"]),
                   "counter_page": cp, "histogram_page": hp, "latency_included": inc,
                   "histogram_bins": bins,
                   "resets": [m for m in METRICS if (t, w["id"], m) in ops["resets"]],
                   "notes": notes}
            rows.append(row)
            intervals.append(row)
        usable = [r for r in rows if r["reason"] == "usable"]
        req = sum(r["requests"][1] for r in usable)
        err = sum(r["errors"][1] for r in usable)
        eb = [sum(r["errors"][0] for r in usable), sum(r["errors"][2] for r in usable)]
        hrows = [r for r in rows if r["latency_included"]]
        lat = latency_summary([r["histogram_bins"] for r in hrows], planning)
        frozen = rg[tg[t]["region"]]["frozen"]
        roll = lat["latency_eligible"] and not frozen
        block = "latency" if not lat["latency_eligible"] else ("region_freeze" if frozen else None)
        per_target[t] = {
            "display_name": registry[t].get("display_name"), "region": tg[t]["region"],
            "usable_windows": [r["window"] for r in usable],
            "histogram_windows": [r["window"] for r in hrows],
            "requests": req, "errors": err,
            "failure_fraction": (err / req) if req > 0 else None,
            "error_bounds": eb,
            "pooled_bins": lat["pooled_bins"],
            "pooled_bin_bounds": [[lat["pooled_low"][j], lat["pooled_high"][j]] for j in range(4)],
            "sample_bounds": lat["sample_bounds"], "samples": lat["samples"],
            "slow_fraction": lat["slow_fraction"], "slow_bounds": lat["slow_bounds"],
            "p95_bin": lat["p95_bin"], "latency_eligible": lat["latency_eligible"],
            "eligibility_stable": lat["eligibility_stable"], "rollout_eligible": roll,
            "block_reason": block, "risk_weight": tg[t]["risk_weight"],
            "weighted_risk": tg[t]["risk_weight"] * err,
        }
    freq = sum(per_target[t]["requests"] for t in order)
    ferr = sum(per_target[t]["errors"] for t in order)
    fleet = {"requests": freq, "errors": ferr, "failure_fraction": (ferr / freq) if freq > 0 else None}

    errors = {t: per_target[t]["errors"] for t in order}
    ebounds = {t: per_target[t]["error_bounds"] for t in order}
    allowed = {t: per_target[t]["rollout_eligible"] for t in order}
    budget = planning["credit_budget"]
    nominal = optimize_static(planning, errors, allowed, budget)
    vec = nominal["_vec"]
    obj_lo = sum(ebounds[t][0] * tg[t]["risk_weight"] * tg[t]["reduction"][k] for t, k in zip(order, vec))
    obj_hi = sum(ebounds[t][1] * tg[t]["risk_weight"] * tg[t]["reduction"][k] for t, k in zip(order, vec))
    total_risk = sum(tg[t]["risk_weight"] * errors[t] for t in order)
    margin, closest = None, None
    for rv in nominal["_feasible"]:
        if rv == vec:
            continue
        m = 0.0
        for t, kw, kr in zip(order, vec, rv):
            coef = tg[t]["risk_weight"] * (tg[t]["reduction"][kw] - tg[t]["reduction"][kr])
            m += coef * (ebounds[t][0] if coef > 0 else ebounds[t][1])
        if margin is None or m < margin:
            margin, closest = m, rv
    all_stable = all(per_target[t]["eligibility_stable"] for t in order)
    robust = all_stable if margin is None else (margin > 0 and all_stable)
    plan = {"tiers": nominal["tiers"], "credits": nominal["credits"], "power": nominal["power"],
            "active_regions": nominal["active_regions"], "objective": nominal["objective"],
            "objective_bounds": [obj_lo, obj_hi], "residual_risk": total_risk - nominal["objective"],
            "total_weighted_risk": total_risk, "robust_margin": margin, "robust": robust,
            "closest_rival": None if closest is None else dict(zip(order, closest)),
            "credit_budget": budget, "power_budget": planning["power_budget"],
            "blocked_targets": {t: per_target[t]["block_reason"] for t in order
                                if per_target[t]["block_reason"]},
            "unserved_risk_by_target": {t: tg[t]["risk_weight"] * errors[t] *
                                        (1 - tg[t]["reduction"][nominal["tiers"][t]]) for t in order}}
    scenarios = []
    for b in (max(0, budget - 2), budget + 2):
        s = optimize_static(planning, errors, allowed, b)
        scenarios.append({"credit_budget": b, "tiers": s["tiers"], "credits": s["credits"],
                          "power": s["power"], "active_regions": s["active_regions"],
                          "objective": s["objective"]})

    execution = None
    ex = validate_execution(planning, allowed)
    if ex is not None:
        fixed, contingency, staged = optimize_execution(ex, planning, errors, ebounds, allowed)
        execution = fixed
        execution["eligible_candidates"] = ex["cands"]
        execution["contingency"] = contingency
        if staged is not None:
            execution["staged"] = staged

    inv = manifest
    out = {
        "inventory": {
            "selected": inv["selected"], "rejected": inv["rejected"], "by_target": inv["by_target"],
            "pages": [{"id": p, "kind": pg["kind"], "file": pg["file"], "targets": pg["targets"],
                       "status": "selected" if p in inv["selected"] else "rejected",
                       "superseded_by": inv["superseded_by"].get(p, [])}
                      for p, pg in sorted(inv["pages"].items())],
            "supersedes": [{"new": n, "old": o, "scope": s} for n, o, s in inv["edges"]],
        },
        "intervals": intervals,
        "targets": per_target,
        "fleet": fleet,
        "plan": plan,
        "scenarios": scenarios,
        "execution": execution,
        "warnings": warnings,
    }
    return clean(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--readings", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--operations", required=True)
    ap.add_argument("--planning", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        out = run(args)
    except InputError as exc:
        sys.stderr.write("analyze.py: input error: %s\n" % exc)
        return 2
    text = json.dumps(out, indent=1, allow_nan=False)
    d = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    for w in out.get("warnings", []):
        sys.stderr.write("analyze.py: warning: %s\n" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
