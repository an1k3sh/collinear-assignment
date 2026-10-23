"""Independent verifier calculations; no imports from candidate or solution."""
from decimal import Decimal
import math

WIDTH = {"requests": 2000, "errors": 40, "bins": 20}
D = lambda x: Decimal(str(x))


def number(x):
    return type(x) in (int, float) and math.isfinite(x)


def close(got, wanted):
    if isinstance(wanted, dict):
        return isinstance(got, dict) and all(k in got and close(got[k], v) for k, v in wanted.items())
    if isinstance(wanted, list):
        return isinstance(got, list) and len(got) == len(wanted) and all(close(a, b) for a, b in zip(got, wanted))
    if type(wanted) in (int, float):
        return number(got) and abs(got-wanted) <= 1e-5+abs(wanted)*1e-6
    return type(got) == type(wanted) and got == wanted


def convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: convert(v) for k, v in value.items()}
    if isinstance(value, list):
        return [convert(v) for v in value]
    return value


def intervals_from_truth(truth, fraction=.25):
    import copy
    answer = copy.deepcopy(truth)
    for row in answer["counters"]:
        for field in ("requests", "errors"):
            value = row[field]
            radius = WIDTH[field]*fraction
            row[field] = None if value is None else [max(0, value-radius), value, value+radius]
    for row in answer["histograms"]:
        if row["bins"] is not None:
            radius = WIDTH["bins"]*fraction
            row["bins"] = [[max(0, v-radius), v, v+radius] for v in row["bins"]]
    return answer


def resolve(manifest, order):
    pages = {p["id"]: p for p in manifest["pages"]}
    assert len(pages) == len(manifest["pages"])
    links = {e["old"]: e["new"] for e in manifest["supersedes"]}
    assert len(links) == len(manifest["supersedes"])
    for start in links:
        visited = set()
        node = start
        while node in links:
            assert node not in visited and node in pages and links[node] in pages
            visited.add(node)
            node = links[node]
    selected = sorted(p for p in pages if p not in links)
    mapping = {}
    for t in order:
        mapping[t] = {}
        for kind in ("counters", "histograms"):
            candidates = [p for p in selected if pages[p]["kind"] == kind and t in pages[p]["targets"]]
            assert len(candidates) == 1
            mapping[t][kind] = candidates[0]
    return {"selected": selected, "rejected": sorted(links), "by_target": mapping}


def reading_index(readings, manifest, operations):
    assert readings["units"] == "base-counts"
    indices = []
    for kind, coordinate in (("counters", "boundary"), ("histograms", "window")):
        expected_keys = {(p["id"], t, item["id"]) for p in manifest["pages"] if p["kind"] == kind
                         for t in p["targets"]
                         for item in operations["boundaries" if kind == "counters" else "windows"]}
        index = {}
        for row in readings[kind]:
            key = row["page"], row["target"], row[coordinate]
            assert key not in index
            values = [row["requests"], row["errors"]] if kind == "counters" else row["bins"]
            if values is not None:
                assert len(values) == (2 if kind == "counters" else 4)
                for value in values:
                    if value is None:
                        assert kind == "counters"
                        continue
                    assert isinstance(value, list) and len(value) == 3
                    assert all(number(v) and v >= 0 for v in value)
                    assert value[0] <= value[1] <= value[2]
            index[key] = row
        assert set(index) == expected_keys
        indices.append(index)
    return indices


def reconstruction(readings, manifest, operations, planning):
    order = planning["target_order"]
    inventory = resolve(manifest, order)
    counters, histograms = reading_index(readings, manifest, operations)
    resets = {(e["target"], e["window"], e["metric"]): e["baseline"] for e in operations["resets"]}
    maintenance = {(e["target"], e["window"]) for e in operations["maintenance"]}
    output = []
    for t in order:
        cp, hp = (inventory["by_target"][t][k] for k in ("counters", "histograms"))
        for window in operations["windows"]:
            row = {"target": t, "window": window["id"], "counter_page": cp, "histogram_page": hp}
            for metric in ("requests", "errors"):
                event = t, window["id"], metric
                begin = ([resets[event]]*3 if event in resets else counters[cp, t, window["start"]][metric])
                end = counters[cp, t, window["end"]][metric]
                if begin is None or end is None:
                    row[metric] = None
                else:
                    lo, estimate, hi = D(end[0])-D(begin[2]), D(end[1])-D(begin[1]), D(end[2])-D(begin[0])
                    assert estimate >= 0
                    row[metric] = [max(D(0), lo), estimate, hi]
            row["reason"] = ("maintenance" if (t, window["id"]) in maintenance else
                             "missing_traffic" if row["requests"] is None or row["errors"] is None else "usable")
            row["mean_requests_per_minute"] = None if row["requests"] is None else row["requests"][1]/D(window["minutes"])
            row["latency_included"] = row["reason"] == "usable" and histograms[hp, t, window["id"]]["bins"] is not None
            output.append(row)
    return inventory, output, histograms


def summarize(readings, manifest, operations, planning):
    inventory, rows, histograms = reconstruction(readings, manifest, operations, planning)
    summaries = {}
    for target in planning["target_order"]:
        usable = [r for r in rows if r["target"] == target and r["reason"] == "usable"]
        joined = [r for r in usable if r["latency_included"]]
        requests = sum((r["requests"][1] for r in usable), D(0))
        errors = [sum((r["errors"][i] for r in usable), D(0)) for i in range(3)]
        bins = [[sum((D(histograms[r["histogram_page"], target, r["window"]]["bins"][b][i])
                      for r in joined), D(0)) for i in range(3)] for b in range(4)]
        sums = [sum((b[i] for b in bins), D(0)) for i in range(3)]
        slow = [bins[2][i]+bins[3][i] for i in range(3)]
        fast = [bins[0][i]+bins[1][i] for i in range(3)]
        lower = slow[0]/(slow[0]+fast[2]) if slow[0]+fast[2] else D(0)
        upper = slow[2]/(slow[2]+fast[0]) if slow[2]+fast[0] else D(1)
        fraction = slow[1]/sums[1] if sums[1] else None
        eligible = sums[1] >= planning["minimum_latency_samples"] and fraction is not None and fraction > D(planning["slow_fraction_trigger"])
        stable = ((sums[0] >= planning["minimum_latency_samples"] and lower > D(planning["slow_fraction_trigger"]))
                  if eligible else (sums[2] < planning["minimum_latency_samples"] or upper <= D(planning["slow_fraction_trigger"])))
        cumulative, quantile = D(0), None
        for i in range(4):
            cumulative += bins[i][1]
            if sums[1] and quantile is None and cumulative*100 >= sums[1]*95:
                quantile = planning["p95_labels"][i]
        frozen = planning["regions"][planning["targets"][target]["region"]]["frozen"]
        summaries[target] = {
            "usable_windows": [r["window"] for r in usable],
            "histogram_windows": [r["window"] for r in joined],
            "requests": requests, "errors": errors[1], "failure_fraction": errors[1]/requests if requests else None,
            "error_bounds": [errors[0], errors[2]], "pooled_bins": [b[1] for b in bins],
            "sample_bounds": [sums[0], sums[2]], "samples": sums[1], "slow_fraction": fraction,
            "slow_bounds": [lower, upper], "p95_bin": quantile, "latency_eligible": eligible,
            "eligibility_stable": stable, "rollout_eligible": eligible and not frozen,
            "block_reason": "latency" if not eligible else "region_freeze" if frozen else None}
    requests = sum(s["requests"] for s in summaries.values())
    errors = sum(s["errors"] for s in summaries.values())
    return {"inventory": inventory, "intervals": rows, "targets": summaries,
            "fleet": {"requests": requests, "errors": errors,
                      "failure_fraction": errors/requests if requests else None}}


def feasible_plans(summaries, planning, budget):
    order = planning["target_order"]
    def walk(i, tiers, region_blocks, credits, power, objective):
        if i == len(order):
            yield {"tiers": dict(zip(order, tiers)), "credits": credits, "power": power,
                   "active_regions": sorted(region_blocks), "objective": objective}
            return
        target = order[i]
        spec = planning["targets"][target]
        region = spec["region"]
        for k in range(3):
            if k and not summaries[target]["rollout_eligible"]:
                continue
            active = dict(region_blocks)
            activation = 0
            if k:
                activation = 0 if region in active else planning["regions"][region]["activation_cost"]
                active[region] = active.get(region, 0)+k
                if active[region] > planning["regions"][region]["max_blocks"]:
                    continue
            cost = credits+spec["cost"][k]+activation
            watts = power+spec["power"][k]
            if cost > budget or watts > planning["power_budget"] or len(active) > planning["max_active_regions"]:
                continue
            benefit = D(spec["risk_weight"])*D(spec["reduction"][k])*D(summaries[target]["errors"])
            yield from walk(i+1, tiers+[k], active, cost, watts, objective+benefit)
    yield from walk(0, [], {}, 0, 0, D(0))


def optimize(summaries, planning, budget, certificate=True):
    order = planning["target_order"]
    candidates = list(feasible_plans(summaries, planning, budget))
    result = min(candidates, key=lambda p: (-p["objective"], p["credits"], p["power"],
                                          tuple(p["tiers"][t] for t in order))).copy()
    if not certificate:
        return result
    diffs = []
    for candidate in candidates:
        if candidate["tiers"] == result["tiers"]:
            continue
        bound = D(0)
        for t in order:
            spec = planning["targets"][t]
            delta = D(spec["risk_weight"])*(D(spec["reduction"][result["tiers"][t]])-
                                            D(spec["reduction"][candidate["tiers"][t]]))
            bound += delta*D(summaries[t]["error_bounds"][0 if delta >= 0 else 1])
        diffs.append(bound)
    bounds = []
    for i in (0, 1):
        bounds.append(sum(D(planning["targets"][t]["risk_weight"])*
                          D(planning["targets"][t]["reduction"][result["tiers"][t]])*
                          D(summaries[t]["error_bounds"][i]) for t in order))
    risk = sum(D(planning["targets"][t]["risk_weight"])*D(summaries[t]["errors"]) for t in order)
    result.update(objective_bounds=bounds, residual_risk=risk-result["objective"],
                  robust_margin=min(diffs) if diffs else None,
                  robust=(not diffs or min(diffs)>0) and all(s["eligibility_stable"] for s in summaries.values()))
    return result


def expected(readings, manifest, operations, planning):
    result = summarize(readings, manifest, operations, planning)
    result["plan"] = optimize(result["targets"], planning, planning["credit_budget"])
    result["scenarios"] = [
        {"credit_budget": b, **optimize(result["targets"], planning, b, False)}
        for b in (max(0, planning["credit_budget"]-2), planning["credit_budget"]+2)]
    return convert(result)
