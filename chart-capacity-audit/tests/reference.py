"""Independent decimal calculations, with no import of candidate or oracle code."""
from decimal import Decimal
from itertools import product
import math

METRICS = {"rate": 100, "failure_pct": .5, "p95_ms": 10}
SOURCES = {"rate": "P1", "failure_pct": "P2", "p95_ms": "P3", "status": "P4"}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def records_by_key(observations, policy):
    rows = observations["records"]
    assert isinstance(rows, list)
    result = {}
    for rec in rows:
        key = rec["region"], rec["window"]
        assert key not in result, "duplicate observation"
        assert rec["status"] in ("normal", "maintenance", "unknown")
        for name in METRICS:
            interval = rec[name]
            if rec["status"] == "unknown":
                assert interval is None, "unknown is not zero"
            else:
                assert isinstance(interval, list) and len(interval) == 3
                assert all(finite(v) and v >= 0 for v in interval)
                assert interval[0] <= interval[1] <= interval[2]
                if name == "failure_pct":
                    assert interval[2] <= 100
        result[key] = rec
    assert set(result) == set(product(policy["regions"], [w["id"] for w in policy["windows"]]))
    return result


def expected(observations, policy):
    records = records_by_key(observations, policy)
    d = lambda v: Decimal(str(v))
    summaries = {}
    for region in policy["regions"]:
        selected = [w for w in policy["windows"] if records[region, w["id"]]["status"] == "normal"]
        total = Decimal(0)
        failure = [Decimal(0)] * 3
        for window in selected:
            rec = records[region, window["id"]]
            duration = d(window["minutes"])
            total += duration * d(rec["rate"][1])
            for i in range(3):
                failure[i] += duration * d(rec["rate"][i]) * d(rec["failure_pct"][i]) / 100
        last = [w["id"] for w in selected[-2:]]
        summaries[region] = {
            "included_windows": [w["id"] for w in selected], "latency_windows": last,
            "requests": total, "failed_requests": failure[1],
            "failure_pct": 100 * failure[1] / total if total else None,
            "failed_bounds": [failure[0], failure[2]],
            "eligible": len(last) == 2 and min(records[region, w]["p95_ms"][1] for w in last)
                        > policy["latency_trigger_ms"]}
    names = policy["regions"]
    fractions = list(map(d, policy["benefit_fraction"]))
    choices = []
    for vector in product(range(policy["max_blocks_per_region"] + 1), repeat=len(names)):
        if sum(vector) > policy["budget_blocks"]:
            continue
        if any(n and not summaries[r]["eligible"] for r, n in zip(names, vector)):
            continue
        score = sum((fractions[n] * summaries[r]["failed_requests"] for r, n in zip(names, vector)), Decimal(0))
        choices.append((score, vector))
    best, vector = sorted(choices, key=lambda entry: (-entry[0], sum(entry[1]), entry[1]))[0]
    margin = None
    for _, rival in choices:
        if rival == vector:
            continue
        lower = Decimal(0)
        for r, a, b in zip(names, vector, rival):
            difference = fractions[a] - fractions[b]
            lo, hi = summaries[r]["failed_bounds"]
            lower += difference * (lo if difference >= 0 else hi)
        margin = lower if margin is None else min(margin, lower)
    bounds = [sum((fractions[n]*summaries[r]["failed_bounds"][i] for r, n in zip(names, vector)),
                  Decimal(0)) for i in (0, 1)]
    total = sum(s["requests"] for s in summaries.values())
    failures = sum(s["failed_requests"] for s in summaries.values())
    result = {
        "regions": summaries,
        "fleet": {"requests": total, "failed_requests": failures,
                  "failure_pct": failures*100/total if total else None},
        "allocation": dict(zip(names, vector)), "expected_benefit": best,
        "benefit_bounds": bounds, "robust_margin": margin,
        "robust": margin is None or margin > 0}

    def floats(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {k: floats(v) for k, v in value.items()}
        if isinstance(value, list):
            return list(map(floats, value))
        return value
    return floats(result)


def equivalent(actual, want):
    if isinstance(want, dict):
        return isinstance(actual, dict) and all(k in actual and equivalent(actual[k], v) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(actual, list) and len(actual) == len(want) and all(map(
            lambda pair: equivalent(*pair), zip(actual, want)))
    if type(want) in (int, float):
        return finite(actual) and abs(actual-want) <= 1e-6 + 1e-6*abs(want)
    return type(actual) is type(want) and actual == want


def truth_observations(truth, widths=None):
    widths = widths or dict.fromkeys(METRICS, 0)
    rows = []
    for src in truth["records"]:
        row = dict(src)
        for name in METRICS:
            value = src[name]
            delta = widths[name]
            row[name] = None if value is None else [max(0, value-delta), value, value+delta]
        rows.append(row)
    return {"records": rows}
