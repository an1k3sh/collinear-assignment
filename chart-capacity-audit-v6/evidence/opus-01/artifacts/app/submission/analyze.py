#!/usr/bin/env python3
"""Reconcile dashboard readings and compute an admissible capacity rollout.

Standard library only.  Inputs are the transcribed readings (base counts), the
export manifest, the operations log, planning settings and the registry.  See
/app/policy.md, /app/interfaces.md and /app/execution-policy.md for semantics.
"""
import argparse
import csv
import itertools
import json
import math
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import execution as execmod  # noqa: E402
from common import InputError, F, fnum, is_num, is_int  # noqa: E402

TARGETS = ["AS", "AI", "BS", "BI", "CS", "CI", "DS", "DI"]
REGIONS = ["Alder", "Birch", "Cedar", "Delta"]
METRICS = ("requests", "errors")
KINDS = {"counters", "histograms"}


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh, parse_constant=_bad_constant)
    except FileNotFoundError:
        raise InputError("%s file not found: %s" % (label, path))
    except json.JSONDecodeError as exc:
        raise InputError("%s is not valid JSON: %s" % (label, exc))
    except ValueError as exc:
        raise InputError("%s contains invalid value: %s" % (label, exc))


def _bad_constant(name):
    raise ValueError("nonfinite JSON constant %s" % name)


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

def load_registry(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except FileNotFoundError:
        raise InputError("registry file not found: %s" % path)
    reg = {}
    for row in rows:
        t = (row.get("target") or "").strip()
        if t not in TARGETS:
            raise InputError("registry: unknown target id %r" % t)
        if t in reg:
            raise InputError("registry: duplicate target %s" % t)
        reg[t] = {k: (v or "").strip() for k, v in row.items()}
    missing = [t for t in TARGETS if t not in reg]
    if missing:
        raise InputError("registry: missing targets %s" % missing)
    return reg


def validate_manifest(man):
    if not isinstance(man, dict) or not isinstance(man.get("pages"), list):
        raise InputError("manifest: 'pages' list required")
    pages = {}
    for p in man["pages"]:
        if not isinstance(p, dict):
            raise InputError("manifest: page entry must be an object")
        pid = p.get("id")
        if not isinstance(pid, str) or not pid:
            raise InputError("manifest: page id must be a nonempty string")
        if pid in pages:
            raise InputError("manifest: duplicate page id %s" % pid)
        kind = p.get("kind")
        if kind not in KINDS:
            raise InputError("manifest: page %s has invalid kind %r" % (pid, kind))
        tg = p.get("targets")
        if not isinstance(tg, list) or not tg:
            raise InputError("manifest: page %s needs a target list" % pid)
        for t in tg:
            if t not in TARGETS:
                raise InputError("manifest: page %s lists unknown target %r" % (pid, t))
        if len(set(tg)) != len(tg):
            raise InputError("manifest: page %s repeats a target" % pid)
        units = p.get("series_units")
        if units is not None:
            if not isinstance(units, dict):
                raise InputError("manifest: page %s series_units must be an object" % pid)
            for k, v in units.items():
                if not is_num(v) or v <= 0:
                    raise InputError("manifest: page %s has invalid unit multiplier %s=%r" % (pid, k, v))
            need = METRICS if kind == "counters" else ("samples",)
            for k in need:
                if k not in units:
                    raise InputError("manifest: page %s lacks unit for %s" % (pid, k))
        pages[pid] = {"id": pid, "kind": kind, "targets": list(tg),
                      "revision": p.get("revision"), "file": p.get("file")}
    edges = man.get("supersedes", []) or []
    if not isinstance(edges, list):
        raise InputError("manifest: 'supersedes' must be a list")
    succ = {}
    clean_edges = []
    for e in edges:
        if not isinstance(e, dict):
            raise InputError("manifest: supersession edge must be an object")
        new, old = e.get("new"), e.get("old")
        if new not in pages or old not in pages:
            raise InputError("manifest: supersession edge references unknown page (%r -> %r)" % (new, old))
        if new == old:
            raise InputError("manifest: supersession cycle: page %s supersedes itself" % new)
        if pages[new]["kind"] != pages[old]["kind"]:
            raise InputError("manifest: supersession %s -> %s mixes page kinds" % (new, old))
        succ.setdefault(old, set()).add(new)
        clean_edges.append({"new": new, "old": old, "scope": e.get("scope", "whole page")})
    # cycle detection on old -> new graph
    state = {}

    def dfs(n, stack):
        state[n] = 1
        for m in sorted(succ.get(n, ())):
            if state.get(m) == 1:
                raise InputError("manifest: supersession cycle involving %s" % " -> ".join(stack + [n, m]))
            if state.get(m) is None:
                dfs(m, stack + [n])
        state[n] = 2

    for n in sorted(pages):
        if state.get(n) is None:
            dfs(n, [])
    superseded = {e["old"] for e in clean_edges}
    selected = sorted(p for p in pages if p not in superseded)
    rejected = sorted(superseded)
    by_target = {t: {} for t in TARGETS}
    for pid in selected:
        pg = pages[pid]
        for t in pg["targets"]:
            if pg["kind"] in by_target[t]:
                raise InputError("manifest: ambiguous coverage, target %s has two authoritative %s pages (%s, %s)"
                                 % (t, pg["kind"], by_target[t][pg["kind"]], pid))
            by_target[t][pg["kind"]] = pid
    for t in TARGETS:
        for k in ("counters", "histograms"):
            if k not in by_target[t]:
                raise InputError("manifest: target %s has no authoritative %s page" % (t, k))
    superseded_by = {}
    for e in clean_edges:
        superseded_by.setdefault(e["old"], []).append(e["new"])
    return pages, clean_edges, selected, rejected, by_target, superseded_by


def validate_operations(ops):
    if not isinstance(ops, dict):
        raise InputError("operations: object required")
    bl = ops.get("boundaries")
    if not isinstance(bl, list) or not bl:
        raise InputError("operations: 'boundaries' list required")
    boundaries = []
    for b in bl:
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not b["id"]:
            raise InputError("operations: boundary needs a string id")
        if b["id"] in boundaries:
            raise InputError("operations: duplicate boundary %s" % b["id"])
        boundaries.append(b["id"])
    wl = ops.get("windows")
    if not isinstance(wl, list) or not (1 <= len(wl) <= 4):
        raise InputError("operations: 1..4 windows required")
    windows = []
    seen = set()
    for w in wl:
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not w["id"]:
            raise InputError("operations: window needs a string id")
        wid = w["id"]
        if wid in seen:
            raise InputError("operations: duplicate window %s" % wid)
        seen.add(wid)
        if w.get("start") not in boundaries or w.get("end") not in boundaries:
            raise InputError("operations: window %s references unknown boundary" % wid)
        if boundaries.index(w["end"]) <= boundaries.index(w["start"]):
            raise InputError("operations: window %s ends before it starts" % wid)
        m = w.get("minutes")
        if not is_num(m) or m <= 0:
            raise InputError("operations: window %s needs positive finite minutes" % wid)
        windows.append({"id": wid, "start": w["start"], "end": w["end"], "minutes": m})
    wids = [w["id"] for w in windows]
    resets = {}
    for r in ops.get("resets", []) or []:
        if not isinstance(r, dict):
            raise InputError("operations: reset entry must be an object")
        t, wi, me = r.get("target"), r.get("window"), r.get("metric")
        if t not in TARGETS:
            raise InputError("operations: reset has unknown target %r" % t)
        if wi not in wids:
            raise InputError("operations: reset references unknown window %r" % wi)
        if me not in METRICS:
            raise InputError("operations: reset has invalid metric %r" % me)
        base = r.get("baseline")
        if not is_num(base) or base < 0:
            raise InputError("operations: reset %s/%s/%s needs finite nonnegative baseline" % (t, wi, me))
        key = (t, wi, me)
        if key in resets:
            raise InputError("operations: duplicate reset %s/%s/%s" % key)
        resets[key] = base
    maint = set()
    for m in ops.get("maintenance", []) or []:
        if not isinstance(m, dict) or m.get("target") not in TARGETS or m.get("window") not in wids:
            raise InputError("operations: invalid maintenance entry %r" % (m,))
        maint.add((m["target"], m["window"]))
    return boundaries, windows, resets, maint


def check_interval(v, where):
    if v is None:
        return None
    if not isinstance(v, list) or len(v) != 3:
        raise InputError("readings: %s must be [low, estimate, high] or null" % where)
    for x in v:
        if not is_num(x):
            raise InputError("readings: %s has non-numeric or nonfinite value %r" % (where, x))
        if x < 0:
            raise InputError("readings: %s has negative value %r" % (where, x))
    lo, est, hi = v
    if not (lo <= est <= hi):
        raise InputError("readings: %s has reversed interval or estimate outside bounds %r" % (where, v))
    return [lo, est, hi]


def validate_readings(rd, pages, boundaries, windows):
    if not isinstance(rd, dict):
        raise InputError("readings: object required")
    if rd.get("units") != "base-counts":
        raise InputError("readings: units must be 'base-counts', got %r" % rd.get("units"))
    if not isinstance(rd.get("counters"), list) or not isinstance(rd.get("histograms"), list):
        raise InputError("readings: 'counters' and 'histograms' lists required")
    wids = [w["id"] for w in windows]
    used_b = set()
    for w in windows:
        used_b.add(w["start"])
        used_b.add(w["end"])
    counters = {}
    extra_counters = {}
    extra_hists = set()
    warnings = []
    for i, c in enumerate(rd["counters"]):
        if not isinstance(c, dict):
            raise InputError("readings: counters[%d] must be an object" % i)
        pid, t, b = c.get("page"), c.get("target"), c.get("boundary")
        if pid not in pages:
            raise InputError("readings: counters[%d] has invalid page id %r" % (i, pid))
        if pages[pid]["kind"] != "counters":
            raise InputError("readings: counters[%d] cites non-counter page %s" % (i, pid))
        if t not in pages[pid]["targets"]:
            raise InputError("readings: counters[%d] target %r not on page %s" % (i, t, pid))
        if not isinstance(b, str) or not b:
            raise InputError("readings: counters[%d] has invalid boundary %r" % (i, b))
        key = (pid, t, b)
        if key in counters or key in extra_counters:
            raise InputError("readings: duplicate counter coordinate %s/%s/%s" % key)
        for m in METRICS:
            if m not in c:
                raise InputError("readings: counter %s/%s/%s lacks %s (use null for UNKNOWN)" % (key + (m,)))
        vals = {m: check_interval(c[m], "counter %s/%s/%s %s" % (key + (m,))) for m in METRICS}
        if b not in boundaries:
            extra_counters[key] = vals
            warnings.append("counter reading %s/%s/%s refers to a boundary absent from operations; not used" % key)
            continue
        counters[key] = vals
    hists = {}
    for i, h in enumerate(rd["histograms"]):
        if not isinstance(h, dict):
            raise InputError("readings: histograms[%d] must be an object" % i)
        pid, t, w = h.get("page"), h.get("target"), h.get("window")
        if pid not in pages:
            raise InputError("readings: histograms[%d] has invalid page id %r" % (i, pid))
        if pages[pid]["kind"] != "histograms":
            raise InputError("readings: histograms[%d] cites non-histogram page %s" % (i, pid))
        if t not in pages[pid]["targets"]:
            raise InputError("readings: histograms[%d] target %r not on page %s" % (i, t, pid))
        if not isinstance(w, str):
            raise InputError("readings: histograms[%d] has invalid window %r" % (i, w))
        key = (pid, t, w)
        if key in hists or key in extra_hists:
            raise InputError("readings: duplicate histogram coordinate %s/%s/%s" % key)
        if "bins" not in h:
            raise InputError("readings: histogram %s/%s/%s lacks bins (use null for UNKNOWN)" % key)
        bins = h["bins"]
        if bins is not None:
            if not isinstance(bins, list) or len(bins) != 4:
                raise InputError("readings: histogram %s/%s/%s must have exactly four bin intervals" % key)
            bins = [check_interval(x, "histogram %s/%s/%s bin %d" % (key + (k,))) for k, x in enumerate(bins)]
            if any(x is None for x in bins):
                raise InputError("readings: histogram %s/%s/%s has a partially missing bin list" % key)
        if w not in wids:
            extra_hists.add(key)
            warnings.append("histogram reading %s/%s/%s refers to a window absent from operations; not used" % key)
            continue
        hists[key] = bins
    # coverage
    for pid, pg in pages.items():
        for t in pg["targets"]:
            if pg["kind"] == "counters":
                for b in boundaries:
                    if b in used_b and (pid, t, b) not in counters:
                        raise InputError("readings: missing counter coordinate %s/%s/%s" % (pid, t, b))
            else:
                for w in wids:
                    if (pid, t, w) not in hists:
                        raise InputError("readings: missing histogram coordinate %s/%s/%s" % (pid, t, w))
    for key in counters:
        if key[2] not in used_b:
            warnings.append("counter reading %s/%s/%s is at a boundary used by no window" % key)
    return counters, hists, warnings


def validate_planning(pl):
    if not isinstance(pl, dict):
        raise InputError("planning: object required")
    order = pl.get("target_order", TARGETS)
    if not isinstance(order, list) or sorted(order) != sorted(TARGETS) or len(set(order)) != 8:
        raise InputError("planning: target_order must list the eight targets once")
    tg = pl.get("targets")
    if not isinstance(tg, dict):
        raise InputError("planning: targets object required")
    regions = pl.get("regions")
    if not isinstance(regions, dict):
        raise InputError("planning: regions object required")
    for r, cfg in regions.items():
        if not isinstance(cfg, dict):
            raise InputError("planning: region %s must be an object" % r)
        ac = cfg.get("activation_cost")
        if not is_num(ac) or ac < 0:
            raise InputError("planning: region %s activation_cost invalid" % r)
        mb = cfg.get("max_blocks")
        if not is_int(mb) or not (0 <= mb <= 4):
            raise InputError("planning: region %s max_blocks must be integer 0..4" % r)
        if not isinstance(cfg.get("frozen", False), bool):
            raise InputError("planning: region %s frozen must be boolean" % r)
    for t in TARGETS:
        c = tg.get(t)
        if not isinstance(c, dict):
            raise InputError("planning: target %s missing" % t)
        if c.get("region") not in regions:
            raise InputError("planning: target %s has unknown region %r" % (t, c.get("region")))
        w = c.get("risk_weight")
        if not is_num(w) or w <= 0:
            raise InputError("planning: target %s risk_weight must be positive" % t)
        for k in ("cost", "power", "reduction"):
            arr = c.get(k)
            if not isinstance(arr, list) or len(arr) != 3 or not all(is_num(x) for x in arr):
                raise InputError("planning: target %s %s must be three finite numbers" % (t, k))
            if arr[0] != 0 or any(x < 0 for x in arr) or not (arr[0] <= arr[1] <= arr[2]):
                raise InputError("planning: target %s %s must start at zero and be nondecreasing" % (t, k))
            if k == "reduction" and arr[2] > 1:
                raise InputError("planning: target %s reduction must be <= 1" % t)
    for k, lo, hi in (("credit_budget", 0, 30), ("power_budget", 0, 20), ("max_active_regions", 0, 4)):
        v = pl.get(k)
        if not is_int(v) or not (lo <= v <= hi):
            raise InputError("planning: %s must be an integer in %d..%d" % (k, lo, hi))
    ms = pl.get("minimum_latency_samples")
    if not is_num(ms) or ms < 1:
        raise InputError("planning: minimum_latency_samples must be >= 1")
    tr = pl.get("slow_fraction_trigger")
    if not is_num(tr) or not (0 < tr < 1):
        raise InputError("planning: slow_fraction_trigger must be in (0,1)")
    labels = pl.get("p95_labels", ["<=100", "(100,300]", "(300,1000]", ">1000"])
    if not isinstance(labels, list) or len(labels) != 4:
        raise InputError("planning: p95_labels must have four entries")
    return order


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------

def reconstruct(metric, target, window, start_iv, end_iv, reset_base):
    """Return interval [low, est, high] or None for one target/window metric."""
    if end_iv is None:
        return None, "end boundary %s unknown" % window["end"]
    if reset_base is not None:
        est = end_iv[1] - reset_base
        lo = max(0, end_iv[0] - reset_base)
        hi = end_iv[2] - reset_base
        if est < 0 or hi < 0:
            raise InputError("inconsistent counters: %s %s %s end level below documented reset baseline"
                             % (target, window["id"], metric))
        return [lo, est, hi], "reset baseline %s replaces start sample" % reset_base
    if start_iv is None:
        return None, "start boundary %s unknown" % window["start"]
    est = end_iv[1] - start_iv[1]
    if est < 0:
        raise InputError("inconsistent counters: %s %s %s falls by %s without a documented reset"
                         % (target, window["id"], metric, -est))
    lo = max(0, end_iv[0] - start_iv[2])
    hi = end_iv[2] - start_iv[0]
    return [lo, est, hi], "end minus start"


def analyze_telemetry(counters, hists, pages, by_target, windows, resets, maint, pl, order):
    intervals = []
    per_target = {}
    min_samples = pl["minimum_latency_samples"]
    trigger = pl["slow_fraction_trigger"]
    labels = pl.get("p95_labels", ["<=100", "(100,300]", "(300,1000]", ">1000"])
    for t in order:
        cp = by_target[t]["counters"]
        hp = by_target[t]["histograms"]
        usable, hwin = [], []
        req_sum = err_sum = 0
        err_lo = err_hi = 0
        bins_est = [0, 0, 0, 0]
        bins_lo = [0, 0, 0, 0]
        bins_hi = [0, 0, 0, 0]
        for w in windows:
            s = counters.get((cp, t, w["start"]), {"requests": None, "errors": None})
            e = counters.get((cp, t, w["end"]), {"requests": None, "errors": None})
            vals, notes = {}, {}
            for m in METRICS:
                vals[m], notes[m] = reconstruct(m, t, w, s[m], e[m], resets.get((t, w["id"], m)))
            if vals["requests"] is not None and vals["errors"] is not None:
                if vals["errors"][1] > vals["requests"][1]:
                    raise InputError("inconsistent counters: %s %s errors (%s) exceed requests (%s)"
                                     % (t, w["id"], vals["errors"][1], vals["requests"][1]))
            if (t, w["id"]) in maint:
                reason = "maintenance"
            elif vals["requests"] is None or vals["errors"] is None:
                reason = "missing_traffic"
            else:
                reason = "usable"
            hb = hists.get((hp, t, w["id"]))
            included = reason == "usable" and hb is not None
            rec = {
                "target": t, "window": w["id"], "reason": reason,
                "requests": vals["requests"], "errors": vals["errors"],
                "mean_requests_per_minute": (vals["requests"][1] / w["minutes"]) if vals["requests"] else None,
                "counter_page": cp, "histogram_page": hp, "latency_included": included,
                "start_boundary": w["start"], "end_boundary": w["end"], "minutes": w["minutes"],
                "resets": {m: resets.get((t, w["id"], m)) for m in METRICS},
                "method": notes,
                "histogram_available": hb is not None,
                "histogram_bins": hb,
                "citations": [cp, hp, t, w["start"], w["end"], w["id"]],
            }
            intervals.append(rec)
            if reason == "usable":
                usable.append(w["id"])
                req_sum += vals["requests"][1]
                err_sum += vals["errors"][1]
                err_lo += vals["errors"][0]
                err_hi += vals["errors"][2]
            if included:
                hwin.append(w["id"])
                for k in range(4):
                    bins_lo[k] += hb[k][0]
                    bins_est[k] += hb[k][1]
                    bins_hi[k] += hb[k][2]
        samples = sum(bins_est)
        if samples > 0:
            slow = (bins_est[2] + bins_est[3]) / samples
            cum = 0
            p95 = None
            for k in range(4):
                cum += bins_est[k]
                if cum >= 0.95 * samples - 1e-9 * samples:
                    p95 = labels[k]
                    break
        else:
            slow = None
            p95 = None
        slow_lo_n, slow_hi_n = bins_lo[2] + bins_lo[3], bins_hi[2] + bins_hi[3]
        fast_lo_n, fast_hi_n = bins_lo[0] + bins_lo[1], bins_hi[0] + bins_hi[1]
        lb = slow_lo_n / (slow_lo_n + fast_hi_n) if (slow_lo_n + fast_hi_n) > 0 else 0.0
        ub = slow_hi_n / (slow_hi_n + fast_lo_n) if (slow_hi_n + fast_lo_n) > 0 else 1.0
        s_lo, s_hi = sum(bins_lo), sum(bins_hi)
        elig = samples >= min_samples and slow is not None and slow > trigger
        if elig:
            stable = s_lo >= min_samples and lb > trigger
        else:
            stable = s_hi < min_samples or ub <= trigger
        per_target[t] = {
            "usable_windows": usable, "histogram_windows": hwin,
            "requests": req_sum, "errors": err_sum,
            "failure_fraction": (err_sum / req_sum) if req_sum > 0 else None,
            "error_bounds": [err_lo, err_hi],
            "pooled_bins": bins_est, "pooled_bin_bounds": [[bins_lo[k], bins_hi[k]] for k in range(4)],
            "sample_bounds": [s_lo, s_hi], "samples": samples,
            "slow_fraction": slow, "slow_bounds": [lb, ub], "p95_bin": p95,
            "latency_eligible": bool(elig), "eligibility_stable": bool(stable),
            "counter_page": cp, "histogram_page": hp,
        }
    return intervals, per_target


# --------------------------------------------------------------------------
# Static plan
# --------------------------------------------------------------------------

def tier_resources(pl, order, tiers):
    credits = Fraction(0)
    power = Fraction(0)
    active = set()
    blocks = {}
    for t in order:
        k = tiers[t]
        c = pl["targets"][t]
        credits += F(c["cost"][k])
        power += F(c["power"][k])
        if k > 0:
            active.add(c["region"])
        blocks[c["region"]] = blocks.get(c["region"], 0) + k
    for r in active:
        credits += F(pl["regions"][r]["activation_cost"])
    return credits, power, sorted(active), blocks


def static_feasible(pl, order, tiers, eligible, credit_budget):
    credits, power, active, blocks = tier_resources(pl, order, tiers)
    if credits > F(credit_budget):
        return False, "credit budget"
    if power > F(pl["power_budget"]):
        return False, "power budget"
    if len(active) > pl["max_active_regions"]:
        return False, "active-region cap"
    for r, b in blocks.items():
        if b > pl["regions"][r]["max_blocks"]:
            return False, "regional block cap (%s)" % r
    for t in order:
        if tiers[t] > 0 and not eligible[t]:
            return False, "ineligible target"
    return True, None


def plan_objective(pl, order, tiers, errors):
    return sum((F(errors[t]) * F(pl["targets"][t]["risk_weight"]) * F(pl["targets"][t]["reduction"][tiers[t]])
                for t in order), Fraction(0))


def optimize_static(pl, order, eligible, errors, credit_budget):
    choices = [range(3) if eligible[t] else range(1) for t in order]
    feasible = []
    for vec in itertools.product(*choices):
        tiers = dict(zip(order, vec))
        ok, _ = static_feasible(pl, order, tiers, eligible, credit_budget)
        if not ok:
            continue
        credits, power, active, _ = tier_resources(pl, order, tiers)
        obj = plan_objective(pl, order, tiers, errors)
        feasible.append((obj, credits, power, vec, active))
    feasible.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))
    return feasible


def summarize_plan(rec, order):
    obj, credits, power, vec, active = rec
    return {"tiers": dict(zip(order, vec)), "credits": fnum(credits), "power": fnum(power),
            "active_regions": active, "objective": fnum(obj)}


def counterexample_r7(pl, order, eligible):
    """Find a tier vector within the credit budget that breaks another rule."""
    out = []
    for vec in itertools.product(range(3), repeat=8):
        tiers = dict(zip(order, vec))
        credits, power, active, blocks = tier_resources(pl, order, tiers)
        if credits > F(pl["credit_budget"]):
            continue
        if any(tiers[t] > 0 and pl["regions"][pl["targets"][t]["region"]].get("frozen") for t in order):
            continue
        if any(tiers[t] > 0 and not eligible[t] for t in order):
            continue
        reasons = []
        if power > F(pl["power_budget"]):
            reasons.append("power %s > %s" % (fnum(power), pl["power_budget"]))
        if len(active) > pl["max_active_regions"]:
            reasons.append("%d active regions > %d" % (len(active), pl["max_active_regions"]))
        for r, b in blocks.items():
            if b > pl["regions"][r]["max_blocks"]:
                reasons.append("%s blocks %d > %d" % (r, b, pl["regions"][r]["max_blocks"]))
        if reasons:
            out.append({"tiers": tiers, "credits": fnum(credits), "violations": reasons})
            if len(out) >= 3:
                break
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run(args):
    reg = load_registry(args.registry)
    man = load_json(args.manifest, "manifest")
    ops = load_json(args.operations, "operations")
    pl = load_json(args.planning, "planning")
    rd = load_json(args.readings, "readings")

    pages, edges, selected, rejected, by_target, superseded_by = validate_manifest(man)
    boundaries, windows, resets, maint = validate_operations(ops)
    order = validate_planning(pl)
    counters, hists, warnings = validate_readings(rd, pages, boundaries, windows)
    exec_cfg = execmod.validate_execution(pl, order) if "execution" in pl else None

    intervals, targets = analyze_telemetry(counters, hists, pages, by_target, windows, resets, maint, pl, order)

    eligible = {}
    for t in order:
        info = targets[t]
        frozen = bool(pl["regions"][pl["targets"][t]["region"]].get("frozen", False))
        info["region"] = pl["targets"][t]["region"]
        info["display_name"] = reg[t].get("display_name")
        info["region_frozen"] = frozen
        if not info["latency_eligible"]:
            info["block_reason"] = "latency"
        elif frozen:
            info["block_reason"] = "region_freeze"
        else:
            info["block_reason"] = None
        info["rollout_eligible"] = info["block_reason"] is None
        eligible[t] = info["rollout_eligible"]

    errors = {t: targets[t]["errors"] for t in order}
    err_lo = {t: targets[t]["error_bounds"][0] for t in order}
    err_hi = {t: targets[t]["error_bounds"][1] for t in order}

    feas = optimize_static(pl, order, eligible, errors, pl["credit_budget"])
    best = feas[0]
    plan = summarize_plan(best, order)
    wvec = best[3]
    w_tiers = dict(zip(order, wvec))
    obj_lo = sum(F(err_lo[t]) * F(pl["targets"][t]["risk_weight"]) * F(pl["targets"][t]["reduction"][w_tiers[t]]) for t in order)
    obj_hi = sum(F(err_hi[t]) * F(pl["targets"][t]["risk_weight"]) * F(pl["targets"][t]["reduction"][w_tiers[t]]) for t in order)
    total_risk = sum((F(errors[t]) * F(pl["targets"][t]["risk_weight"]) for t in order), Fraction(0))
    margin = None
    closest = None
    for rec in feas[1:]:
        rvec = rec[3]
        m = Fraction(0)
        for i, t in enumerate(order):
            coef = F(pl["targets"][t]["risk_weight"]) * (F(pl["targets"][t]["reduction"][wvec[i]]) -
                                                         F(pl["targets"][t]["reduction"][rvec[i]]))
            if coef > 0:
                m += coef * F(err_lo[t])
            elif coef < 0:
                m += coef * F(err_hi[t])
        if margin is None or m < margin:
            margin = m
            closest = dict(zip(order, rvec))
    all_stable = all(targets[t]["eligibility_stable"] for t in order)
    robust = (margin is not None and margin > 0 and all_stable) if margin is not None else all_stable
    plan.update({
        "objective_bounds": [fnum(obj_lo), fnum(obj_hi)],
        "residual_risk": fnum(total_risk - best[0]),
        "total_weighted_risk": fnum(total_risk),
        "robust_margin": fnum(margin) if margin is not None else None,
        "robust": bool(robust),
        "closest_rival": closest,
        "feasible_vectors": len(feas),
        "blocked": {t: targets[t]["block_reason"] for t in order if targets[t]["block_reason"]},
        "unserved_risk_by_target": {t: fnum(F(errors[t]) * F(pl["targets"][t]["risk_weight"]) *
                                            (1 - F(pl["targets"][t]["reduction"][w_tiers[t]]))) for t in order},
    })
    _, _, _, blocks = tier_resources(pl, order, w_tiers)
    plan["region_blocks"] = blocks
    plan["binding"] = {
        "credits": [fnum(best[1]), pl["credit_budget"]],
        "power": [fnum(best[2]), pl["power_budget"]],
        "active_regions": [len(best[4]), pl["max_active_regions"]],
    }

    scenarios = []
    for b in (max(0, pl["credit_budget"] - 2), pl["credit_budget"] + 2):
        f2 = optimize_static(pl, order, eligible, errors, b)
        s = summarize_plan(f2[0], order)
        s = {"credit_budget": b, **s}
        scenarios.append(s)

    fleet_req = sum(targets[t]["requests"] for t in order)
    fleet_err = sum(targets[t]["errors"] for t in order)
    out = {
        "inventory": {
            "selected": selected, "rejected": rejected,
            "by_target": {t: {"counters": by_target[t]["counters"], "histograms": by_target[t]["histograms"]} for t in order},
            "supersedes": edges,
            "rejection_reasons": {p: "superseded (whole page) by %s; revisions are replacements, not additive"
                                  % ", ".join(sorted(superseded_by[p])) for p in rejected},
        },
        "intervals": intervals,
        "targets": targets,
        "fleet": {"requests": fleet_req, "errors": fleet_err,
                  "failure_fraction": (fleet_err / fleet_req) if fleet_req > 0 else None},
        "plan": plan,
        "scenarios": scenarios,
        "r7_counterexamples": counterexample_r7(pl, order, eligible),
        "warnings": warnings,
    }
    if exec_cfg is not None:
        out["execution"] = execmod.solve(exec_cfg, pl, order, targets, eligible)
    return out


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
        sys.stderr.write("ERROR: %s\n" % exc)
        return 2
    for w in out.get("warnings", []):
        sys.stderr.write("warning: %s\n" % w)
    text = json.dumps(out, indent=1, allow_nan=False)
    d = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
