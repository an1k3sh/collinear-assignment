import argparse
import csv
from fractions import Fraction
import itertools
import json
import math
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def interval(value):
    if value is None:
        return
    require(isinstance(value, list) and len(value) == 3, "interval needs three values")
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in value),
            "finite nonnegative readings required")
    require(value[0] <= value[1] <= value[2], "reversed interval")


def source_map(manifest, targets):
    pages = {p["id"]: p for p in manifest["pages"]}
    require(len(pages) == len(manifest["pages"]), "duplicate page ID")
    edges = {}
    for edge in manifest["supersedes"]:
        old, new = edge["old"], edge["new"]
        require(old in pages and new in pages and old != new and old not in edges, "invalid supersession")
        require(pages[old]["kind"] == pages[new]["kind"] and
                set(pages[old]["targets"]) == set(pages[new]["targets"]), "incompatible replacement")
        edges[old] = new
    for node in edges:
        visited = set()
        while node in edges:
            require(node not in visited, "supersession cycle")
            visited.add(node)
            node = edges[node]
    selected = sorted(set(pages)-set(edges))
    by_target = {t: {} for t in targets}
    for page in selected:
        p = pages[page]
        require(p["kind"] in ("counters", "histograms"), "invalid page kind")
        for target in p["targets"]:
            require(target in by_target and p["kind"] not in by_target[target], "ambiguous source coverage")
            by_target[target][p["kind"]] = page
    require(all(set(v) == {"counters", "histograms"} for v in by_target.values()), "missing source")
    return {"selected": selected, "rejected": sorted(edges), "by_target": by_target}, pages


def index_readings(readings, pages, operations):
    require(readings["units"] == "base-counts", "readings must be base-counts")
    counters, histograms = {}, {}
    expected_c, expected_h = set(), set()
    boundaries = [b["id"] for b in operations["boundaries"]]
    windows = [w["id"] for w in operations["windows"]]
    require(len(set(boundaries)) == len(boundaries) and len(set(windows)) == len(windows),
            "duplicate operations coordinate")
    for p in pages.values():
        for target in p["targets"]:
            if p["kind"] == "counters":
                expected_c.update((p["id"], target, b) for b in boundaries)
            else:
                expected_h.update((p["id"], target, w) for w in windows)
    for row in readings["counters"]:
        key = row["page"], row["target"], row["boundary"]
        require(key not in counters, "duplicate counter coordinate")
        for metric in ("requests", "errors"):
            interval(row[metric])
        counters[key] = row
    for row in readings["histograms"]:
        key = row["page"], row["target"], row["window"]
        require(key not in histograms, "duplicate histogram coordinate")
        if row["bins"] is not None:
            require(isinstance(row["bins"], list) and len(row["bins"]) == 4, "four disjoint bins required")
            for value in row["bins"]:
                require(value is not None, "histogram missingness is whole row")
                interval(value)
        histograms[key] = row["bins"]
    require(set(counters) == expected_c and set(histograms) == expected_h,
            "missing, extra or invalid page/reading coordinate")
    return counters, histograms


def subtract(end, start):
    if end is None or start is None:
        return None
    require(end[1] >= start[1], "undocumented negative counter delta")
    return [max(0, end[0]-start[2]), end[1]-start[1], end[2]-start[0]]


def summarize(readings, manifest, operations, planning, registry):
    order = planning["target_order"]
    require(set(order) == set(registry) and len(order) == len(set(order)), "registry/target mismatch")
    require(all(registry[t]["region"] == planning["targets"][t]["region"] for t in order),
            "registry region mismatch")
    inventory, pages = source_map(manifest, order)
    counters, histograms = index_readings(readings, pages, operations)
    resets = {}
    for reset in operations["resets"]:
        key = reset["target"], reset["window"], reset["metric"]
        require(key not in resets, "duplicate reset")
        interval([reset["baseline"]]*3)
        resets[key] = reset["baseline"]
    maintenance = {(r["target"], r["window"]) for r in operations["maintenance"]}
    intervals, summaries = [], {}
    for target in order:
        source = inventory["by_target"][target]
        usable, joined = [], []
        request_total = 0
        error_total = [0, 0, 0]
        bins = [[0, 0, 0] for _ in range(4)]
        for w in operations["windows"]:
            require(type(w["minutes"]) in (int, float) and w["minutes"] > 0, "invalid duration")
            values = {}
            for metric in ("requests", "errors"):
                end = counters[source["counters"], target, w["end"]][metric]
                key = target, w["id"], metric
                start = [resets[key]]*3 if key in resets else counters[source["counters"], target, w["start"]][metric]
                values[metric] = subtract(end, start)
            if all(v is not None for v in values.values()):
                require(values["errors"][1] <= values["requests"][1], "errors exceed requests")
            reason = ("maintenance" if (target, w["id"]) in maintenance else
                      "missing_traffic" if any(v is None for v in values.values()) else "usable")
            histogram = histograms[source["histograms"], target, w["id"]]
            included = reason == "usable" and histogram is not None
            intervals.append({
                "target": target, "window": w["id"], "reason": reason, **values,
                "mean_requests_per_minute": None if values["requests"] is None else values["requests"][1]/w["minutes"],
                "counter_page": source["counters"], "histogram_page": source["histograms"],
                "latency_included": included})
            if reason == "usable":
                usable.append(w["id"])
                request_total += values["requests"][1]
                for i in range(3):
                    error_total[i] += values["errors"][i]
            if included:
                joined.append(w["id"])
                for b in range(4):
                    for i in range(3):
                        bins[b][i] += histogram[b][i]
        pooled = [b[1] for b in bins]
        samples = sum(pooled)
        sample_bounds = [sum(b[i] for b in bins) for i in (0, 2)]
        fast_low, fast_high = (sum(b[i] for b in bins[:2]) for i in (0, 2))
        slow_low, slow_high = (sum(b[i] for b in bins[2:]) for i in (0, 2))
        slow_bounds = [slow_low/(slow_low+fast_high) if slow_low+fast_high else 0,
                       slow_high/(slow_high+fast_low) if slow_high+fast_low else 1]
        slow = sum(pooled[2:])/samples if samples else None
        eligible = samples >= planning["minimum_latency_samples"] and slow is not None and slow > planning["slow_fraction_trigger"]
        stable = (sample_bounds[0] >= planning["minimum_latency_samples"] and
                  slow_bounds[0] > planning["slow_fraction_trigger"]) if eligible else (
                  sample_bounds[1] < planning["minimum_latency_samples"] or
                  slow_bounds[1] <= planning["slow_fraction_trigger"])
        cumulative, p95 = 0, None
        for index, count in enumerate(pooled):
            cumulative += count
            if samples and p95 is None and cumulative >= .95*samples:
                p95 = planning["p95_labels"][index]
        frozen = planning["regions"][planning["targets"][target]["region"]]["frozen"]
        summaries[target] = {
            "usable_windows": usable, "histogram_windows": joined,
            "requests": request_total, "errors": error_total[1],
            "failure_fraction": error_total[1]/request_total if request_total else None,
            "error_bounds": [error_total[0], error_total[2]],
            "pooled_bins": pooled, "sample_bounds": sample_bounds, "samples": samples,
            "slow_fraction": slow, "slow_bounds": slow_bounds, "p95_bin": p95,
            "latency_eligible": eligible, "eligibility_stable": stable,
            "rollout_eligible": eligible and not frozen,
            "block_reason": "latency" if not eligible else "region_freeze" if frozen else None}
    total = sum(t["requests"] for t in summaries.values())
    failed = sum(t["errors"] for t in summaries.values())
    return {"inventory": inventory, "intervals": intervals, "targets": summaries,
            "fleet": {"requests": total, "errors": failed, "failure_fraction": failed/total if total else None}}


def optimize(summaries, planning, budget, certificate):
    order = planning["target_order"]
    f = lambda value: Fraction(str(value))
    options = [range(3) if summaries[t]["rollout_eligible"] else (0,) for t in order]
    plans = []
    for vector in itertools.product(*options):
        active = sorted({planning["targets"][t]["region"] for t, k in zip(order, vector) if k})
        if len(active) > planning["max_active_regions"]:
            continue
        if any(sum(k for t, k in zip(order, vector) if planning["targets"][t]["region"] == r)
               > spec["max_blocks"] for r, spec in planning["regions"].items()):
            continue
        credits = sum(planning["targets"][t]["cost"][k] for t, k in zip(order, vector))
        credits += sum(planning["regions"][r]["activation_cost"] for r in active)
        power = sum(planning["targets"][t]["power"][k] for t, k in zip(order, vector))
        if credits > budget or power > planning["power_budget"]:
            continue
        coefficients = [f(planning["targets"][t]["risk_weight"])*f(planning["targets"][t]["reduction"][k])
                        for t, k in zip(order, vector)]
        value = sum(c*f(summaries[t]["errors"]) for t, c in zip(order, coefficients))
        plans.append((value, credits, power, vector, active, coefficients))
    best = min(plans, key=lambda p: (-p[0], p[1], p[2], p[3]))
    value, credits, power, vector, active, coefficients = best
    answer = {"tiers": dict(zip(order, vector)), "credits": credits, "power": power,
              "active_regions": active, "objective": float(value)}
    if not certificate:
        return answer
    margins = []
    for plan in plans:
        if plan[3] == vector:
            continue
        diffs = [a-b for a, b in zip(coefficients, plan[5])]
        margins.append(sum(c*f(summaries[t]["error_bounds"][0 if c >= 0 else 1]) for t, c in zip(order, diffs)))
    bounds = [float(sum(c*f(summaries[t]["error_bounds"][i]) for t, c in zip(order, coefficients))) for i in (0, 1)]
    total_risk = sum(f(planning["targets"][t]["risk_weight"])*f(summaries[t]["errors"]) for t in order)
    answer.update(objective_bounds=bounds, residual_risk=float(total_risk-value),
                  robust_margin=float(min(margins)) if margins else None,
                  robust=(not margins or min(margins) > 0) and all(s["eligibility_stable"] for s in summaries.values()))
    return answer


def analyze(readings, manifest, operations, planning, registry):
    result = summarize(readings, manifest, operations, planning, registry)
    result["plan"] = optimize(result["targets"], planning, planning["credit_budget"], True)
    result["scenarios"] = [
        {"credit_budget": budget, **optimize(result["targets"], planning, budget, False)}
        for budget in (max(0, planning["credit_budget"]-2), planning["credit_budget"]+2)]
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ("readings", "manifest", "operations", "planning", "registry", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        registry = {row["target"]: row for row in csv.DictReader(args.registry.open())}
        result = analyze(*(json.loads(getattr(args, n).read_text()) for n in
                           ("readings", "manifest", "operations", "planning")), registry)
        args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    except (ValueError, TypeError, KeyError, IndexError, OSError) as error:
        print(f"analysis error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
