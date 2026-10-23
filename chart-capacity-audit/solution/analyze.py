import argparse
import itertools
import json
import math
from pathlib import Path
import sys


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(observations, policy):
    regions = policy["regions"]
    windows = [w["id"] for w in policy["windows"]]
    if len(set(regions)) != 4 or not 1 <= len(windows) <= 8 or len(set(windows)) != len(windows):
        raise ValueError("invalid regions/windows")
    if any(not number(w["minutes"]) or w["minutes"] <= 0 for w in policy["windows"]):
        raise ValueError("invalid durations")
    if type(policy["budget_blocks"]) is not int or not 0 <= policy["budget_blocks"] <= 6:
        raise ValueError("invalid budget")
    limit = policy["max_blocks_per_region"]
    if type(limit) is not int or limit not in (1, 2):
        raise ValueError("invalid block limit")
    fractions = policy["benefit_fraction"]
    if (len(fractions) != limit + 1 or fractions[0] != 0 or
            any(not number(v) or v < 0 for v in fractions) or
            any(b <= a for a, b in zip(fractions, fractions[1:]))):
        raise ValueError("invalid benefit fractions")
    if not number(policy["latency_trigger_ms"]) or not 250 <= policy["latency_trigger_ms"] <= 450:
        raise ValueError("invalid trigger")
    records = {}
    for rec in observations["records"]:
        key = (rec["region"], rec["window"])
        if key in records or key[0] not in regions or key[1] not in windows:
            raise ValueError("duplicate or unknown observation")
        if rec["status"] not in ("normal", "maintenance", "unknown"):
            raise ValueError("invalid status")
        for metric in ("rate", "failure_pct", "p95_ms"):
            values = rec[metric]
            if rec["status"] == "unknown":
                if values is not None:
                    raise ValueError("unknown observation must have null metrics")
            elif (not isinstance(values, list) or len(values) != 3 or
                  any(not number(v) or v < 0 for v in values) or
                  not values[0] <= values[1] <= values[2] or
                  (metric == "failure_pct" and values[2] > 100)):
                raise ValueError("invalid metric interval")
        records[key] = rec
    if set(records) != set(itertools.product(regions, windows)):
        raise ValueError("missing observations")
    return records


def analyze(observations, policy):
    records = validate(observations, policy)
    regions = policy["regions"]
    summaries = {}
    for region in regions:
        normal = [(w, records[region, w["id"]]) for w in policy["windows"]
                  if records[region, w["id"]]["status"] == "normal"]
        requests = sum(w["minutes"] * rec["rate"][1] for w, rec in normal)
        failed = [sum(w["minutes"] * rec["rate"][i] * rec["failure_pct"][i] / 100
                      for w, rec in normal) for i in range(3)]
        tail = normal[-2:]
        summaries[region] = {
            "included_windows": [w["id"] for w, _ in normal],
            "latency_windows": [w["id"] for w, _ in tail],
            "requests": requests, "failed_requests": failed[1],
            "failure_pct": 100 * failed[1] / requests if requests else None,
            "failed_bounds": [failed[0], failed[2]],
            "eligible": len(tail) == 2 and all(
                rec["p95_ms"][1] > policy["latency_trigger_ms"] for _, rec in tail)}
    fractions = policy["benefit_fraction"]
    feasible = [counts for counts in itertools.product(range(policy["max_blocks_per_region"] + 1), repeat=4)
                if sum(counts) <= policy["budget_blocks"] and
                all(k == 0 or summaries[r]["eligible"] for r, k in zip(regions, counts))]

    def benefit(counts):
        return sum(fractions[k] * summaries[r]["failed_requests"] for r, k in zip(regions, counts))

    winner = min(feasible, key=lambda counts: (-benefit(counts), sum(counts), counts))
    margins = []
    for other in feasible:
        if other == winner:
            continue
        margin = 0
        for region, chosen, alternative in zip(regions, winner, other):
            difference = fractions[chosen] - fractions[alternative]
            margin += difference * summaries[region]["failed_bounds"][0 if difference >= 0 else 1]
        margins.append(margin)
    bounds = [sum(fractions[k] * summaries[r]["failed_bounds"][i] for r, k in zip(regions, winner))
              for i in range(2)]
    requests = sum(v["requests"] for v in summaries.values())
    failures = sum(v["failed_requests"] for v in summaries.values())
    return {"regions": summaries,
            "fleet": {"requests": requests, "failed_requests": failures,
                      "failure_pct": 100*failures/requests if requests else None},
            "allocation": dict(zip(regions, winner)),
            "expected_benefit": benefit(winner), "benefit_bounds": bounds,
            "robust_margin": min(margins) if margins else None,
            "robust": not margins or min(margins) > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = analyze(json.loads(args.observations.read_text()), json.loads(args.policy.read_text()))
        args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        print(f"analysis error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
