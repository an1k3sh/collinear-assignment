import argparse
from collections import defaultdict
import csv
from itertools import permutations
import json
from pathlib import Path

from ortools.sat.python import cp_model


def read(folder, name):
    with (folder / name).open() as f:
        return list(csv.DictReader(f))


def plan(folder):
    settings = json.loads((folder / "settings.json").read_text())
    cutoff, horizon = settings["planning_cutoff"], settings["horizon"]
    latest = {}
    for row in read(folder, "order_versions.csv"):
        key = row["account"], row["order_id"]
        if row["recorded_at"] <= cutoff and (
            key not in latest or latest[key]["recorded_at"] < row["recorded_at"]
        ):
            latest[key] = row
    orders = []
    for key, row in sorted(latest.items()):
        if row["status"] == "confirmed" and row["effective_at"] <= cutoff:
            orders.append({k: int(row[k]) if k in ("quantity", "open", "close", "service") else row[k]
                           for k in ("account", "order_id", "sku", "quantity", "node", "open", "close", "service")})
    skus = {r["sku"]: r for r in read(folder, "skus.csv")}
    quality = {}
    for row in read(folder, "quality_versions.csv"):
        if row["recorded_at"] <= cutoff and (
            row["lot"] not in quality or quality[row["lot"]]["recorded_at"] < row["recorded_at"]
        ):
            quality[row["lot"]] = row
    balances, seen = defaultdict(int), set()
    for row in read(folder, "stock_events.csv"):
        key = row["warehouse"], row["event_id"]
        if row["recorded_at"] <= cutoff and key not in seen:
            seen.add(key)
            balances[row["lot"]] += int(row["delta"])
    lots = [dict(r, available=int(quality[r["lot"]]["available"]), balance=balances[r["lot"]])
            for r in read(folder, "lots.csv") if quality[r["lot"]]["status"] == "released"]
    travel = {(r["origin"], r["destination"]): int(r["minutes"]) for r in read(folder, "travel.csv")}
    benches = read(folder, "benches.csv")
    vehicles = read(folder, "vehicles.csv")
    model = cp_model.CpModel()
    pack_starts, pack_ends, delivered, bench_choices = [], [], [], []
    bench_intervals = defaultdict(list)
    for i, order in enumerate(orders):
        sku = skus[order["sku"]]
        duration = int(sku["pack_base"]) + order["quantity"] * int(sku["pack_per_unit"])
        start = model.new_int_var(0, horizon, f"pack_{i}")
        end = model.new_int_var(0, horizon, f"packed_{i}")
        model.add(end == start + duration)
        delivery = model.new_int_var(0, horizon, f"delivery_end_{i}")
        model.add(delivery - end <= int(sku["max_unrefrigerated"]))
        options = []
        for bench in benches:
            if sku["family"] in bench["families"].split("|"):
                choice = model.new_bool_var(f"bench_{i}_{bench['bench']}")
                interval = model.new_optional_interval_var(start, duration, end, choice, f"work_{i}_{bench['bench']}")
                model.add(start >= int(bench["start"])).only_enforce_if(choice)
                model.add(end <= int(bench["end"])).only_enforce_if(choice)
                bench_intervals[bench["bench"]].append(interval)
                options.append((choice, bench["bench"]))
        model.add_exactly_one(c for c, _ in options)
        pack_starts.append(start)
        pack_ends.append(end)
        delivered.append(delivery)
        bench_choices.append(options)
    for row in read(folder, "bench_breaks.csv"):
        start, end = int(row["start"]), int(row["end"])
        bench_intervals[row["bench"]].append(model.new_fixed_size_interval_var(start, end-start, "break"))
    for intervals in bench_intervals.values():
        model.add_no_overlap(intervals)

    allocation_vars = []
    stock_vars = defaultdict(list)
    for i, order in enumerate(orders):
        quantities = []
        for lot in lots:
            if lot["sku"] != order["sku"]:
                continue
            quantity = model.new_int_var(0, order["quantity"], f"qty_{i}_{lot['lot']}")
            used = model.new_bool_var(f"lot_{i}_{lot['lot']}")
            model.add(quantity >= 1).only_enforce_if(used)
            model.add(quantity == 0).only_enforce_if(used.Not())
            model.add(pack_starts[i] >= lot["available"]).only_enforce_if(used)
            model.add(delivered[i] <= int(lot["expiry"])).only_enforce_if(used)
            quantities.append(quantity)
            stock_vars[lot["lot"]].append(quantity)
            allocation_vars.append((i, lot["lot"], quantity))
        model.add(sum(quantities) == order["quantity"])
    for lot in lots:
        model.add(sum(stock_vars[lot["lot"]]) <= lot["balance"])

    dock_intervals = []
    for row in read(folder, "dock_breaks.csv"):
        start, end = int(row["start"]), int(row["end"])
        dock_intervals.append(model.new_fixed_size_interval_var(start, end-start, "dock_break"))
    choices_by_order = defaultdict(list)
    choices_by_vehicle = defaultdict(list)
    vehicle_intervals = defaultdict(list)
    choices = []
    costs = []
    for vehicle in vehicles:
        supported = [i for i, o in enumerate(orders) if skus[o["sku"]]["family"] in vehicle["families"].split("|")]
        for size in range(1, int(vehicle["max_stops"])+1):
            for route in permutations(supported, size):
                units = sum(orders[i]["quantity"] for i in route)
                if units > int(vehicle["capacity"]):
                    continue
                load = settings["load_base"] + units * settings["load_per_unit"]
                elapsed, drive, previous = load, 0, "DEPOT"
                offsets = []
                low = int(vehicle["start"])
                high = horizon
                for i in route:
                    order = orders[i]
                    leg = travel[previous, order["node"]]
                    drive += leg
                    elapsed += leg
                    low = max(low, order["open"] - elapsed)
                    elapsed += order["service"]
                    high = min(high, order["close"] - elapsed)
                    offsets.append(elapsed)
                    previous = order["node"]
                drive += travel[previous, "DEPOT"]
                elapsed += travel[previous, "DEPOT"]
                high = min(high, int(vehicle["end"]) - elapsed, horizon - elapsed)
                if drive > int(vehicle["max_drive"]) or low > high:
                    continue
                if any(offset > int(skus[orders[i]["sku"]]["max_unrefrigerated"])
                       for i, offset in zip(route, offsets)):
                    continue
                n = len(choices)
                used = model.new_bool_var(f"route_{n}")
                start = model.new_int_var(low, high, f"load_{n}")
                dock_intervals.append(model.new_optional_fixed_size_interval_var(start, load, used, f"dock_{n}"))
                # Adding turnaround to every trip also adds it after the final one;
                # that extension is only a non-overlap reservation, not a shift bound.
                vehicle_intervals[vehicle["vehicle"]].append(model.new_optional_fixed_size_interval_var(
                    start, elapsed + int(vehicle["turnaround"]), used, f"vehicle_{n}"))
                for i, offset in zip(route, offsets):
                    choices_by_order[i].append(used)
                    model.add(pack_ends[i] <= start).only_enforce_if(used)
                    model.add(delivered[i] == start + offset).only_enforce_if(used)
                choices_by_vehicle[vehicle["vehicle"]].append(used)
                cost = int(vehicle["trip_cents"]) + drive * int(vehicle["drive_cents_per_minute"])
                costs.append(used * cost)
                choices.append((used, start, vehicle, route, offsets, load, elapsed))
        used_vehicle = model.new_bool_var(f"hire_{vehicle['vehicle']}")
        options = choices_by_vehicle[vehicle["vehicle"]]
        model.add(sum(options) <= int(vehicle["max_trips"]) * used_vehicle)
        model.add(sum(options) >= used_vehicle)
        costs.append(used_vehicle * int(vehicle["hire_cents"]))
        model.add_no_overlap(vehicle_intervals[vehicle["vehicle"]])
    model.add_no_overlap(dock_intervals)
    for i in range(len(orders)):
        model.add_exactly_one(choices_by_order[i])
    model.add(sum(costs) <= settings["budget_cents"])
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 4
    solver.parameters.max_time_in_seconds = 140
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"No verified dispatch found: {solver.status_name(status)}")
    result = dict(roster=orders, allocations=[], packing=[], trips=[], cost_cents=solver.value(sum(costs)))
    for i, order in enumerate(orders):
        key = {k: order[k] for k in ("account", "order_id")}
        result["packing"].append(dict(key, bench=next(b for c, b in bench_choices[i] if solver.value(c)),
                                      start=solver.value(pack_starts[i]), end=solver.value(pack_ends[i])))
    for i, lot, quantity in allocation_vars:
        if solver.value(quantity):
            result["allocations"].append(dict(account=orders[i]["account"], order_id=orders[i]["order_id"],
                                              lot=lot, quantity=solver.value(quantity)))
    for used, start, vehicle, route, offsets, load, elapsed in choices:
        if not solver.value(used):
            continue
        begin = solver.value(start)
        result["trips"].append(dict(
            trip_id=f"T{len(result['trips'])+1}", vehicle=vehicle["vehicle"], load_start=begin,
            depart=begin+load, **{"return":begin+elapsed},
            stops=[dict(account=orders[i]["account"], order_id=orders[i]["order_id"],
                        service_start=begin+offset-orders[i]["service"]) for i, offset in zip(route, offsets)]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = plan(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Dispatched {len(result['roster'])} orders in {len(result['trips'])} trips, {result['cost_cents']} cents")
