import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "tests"))
from check_plan import CheckPlan


def controls(plan):
    data = TASK / "environment/app/data"
    CheckPlan(data,plan).all()
    results = {"oracle":{"accepted":True}}

    def assess(name, value, expected, method="all"):
        try:
            getattr(CheckPlan(data,value),method)()
            accepted, error = True, None
        except AssertionError as exc:
            accepted, error = False, str(exc)
        results[name] = dict(accepted=accepted, expected=expected, error=error)
        assert accepted == expected, f"Control {name} misclassified: {results[name]}"

    alternate = deepcopy(plan)
    for field in ("roster","allocations","packing","trips"):
        alternate[field].reverse()
    row = next(r for r in alternate["allocations"] if r["quantity"] > 1)
    row["quantity"] -= 1
    alternate["allocations"].append(dict(row, quantity=1))
    assess("valid_reordered_split_allocations",alternate,True)

    waiting = None
    for t, trip in enumerate(plan["trips"]):
        trial = deepcopy(plan)
        for stop in trial["trips"][t]["stops"]:
            stop["service_start"] += 1
        trial["trips"][t]["return"] += 1
        try:
            CheckPlan(data,trial).all()
        except AssertionError:
            continue
        waiting = trial
        break
    assert waiting is not None, "No valid waiting alternative found in oracle plan"
    assess("valid_customer_waiting",waiting,True)

    bad = deepcopy(plan)
    bad["roster"].append(dict(bad["roster"][0],order_id="900"))
    assess("cancelled_order_in_roster",bad,False,"roster")
    bad = deepcopy(plan)
    bad["roster"][0]["order_id"] = int(bad["roster"][0]["order_id"])
    assess("leading_zero_identity_lost",bad,False,"roster")
    bad = deepcopy(plan)
    bad["allocations"][0]["lot"] = bad["allocations"][0]["lot"][0]+"4"
    assess("quarantined_stock",bad,False,"allocations")
    bad = deepcopy(plan)
    for row in bad["allocations"]:
        row["lot"] = row["lot"][0]+"1"
    assess("duplicate_feed_inflates_stock",bad,False,"allocations")
    bad = deepcopy(plan)
    bad["packing"][0]["end"] -= 1
    assess("packing_duration_shortened",bad,False,"packing")
    bad = deepcopy(plan)
    row = next(r for r in bad["packing"] if r["bench"] == "P1")
    duration = row["end"]-row["start"]
    row["start"],row["end"] = 90,90+duration
    assess("bench_break_ignored",bad,False,"packing")
    bad = deepcopy(plan)
    first = bad["trips"][0]
    order = next(o for o in bad["roster"] if all(o[k] == first["stops"][0][k] for k in ("account","order_id")))
    checker = CheckPlan(data,bad)
    first["stops"][0]["service_start"] = first["depart"]+checker.travel["DEPOT",order["node"]]-1
    assess("travel_undershot",bad,False,"trips")
    bad = deepcopy(plan)
    first = bad["trips"][0]
    first["depart"] -= 1
    assess("loading_time_shortened",bad,False,"trips")
    bad = deepcopy(plan)
    for row in bad["packing"]:
        row["end"] = 0
    assess("thermal_clock_at_departure",bad,False,"cold_chain")
    bad = deepcopy(plan)
    for row in bad["allocations"]:
        if row["account"] == "WEST":
            row["lot"] = row["lot"][0]+"1"
    assess("expiry_checked_before_delivery",bad,False,"cold_chain")
    bad = deepcopy(plan)
    bad["cost_cents"] -= 11500
    assess("hire_cost_omitted",bad,False,"cost")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    results = controls(json.loads(args.plan.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+"\n")
    print(f"{len(results)} controls classified as expected")
