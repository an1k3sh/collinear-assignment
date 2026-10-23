"""Independent, solver-free verification of operating outcomes."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sqlite3


def table(folder, name):
    with (folder / (name + ".csv")).open() as f:
        return list(csv.DictReader(f))


def integer(value):
    assert type(value) is int, f"Expected integer, received {value!r}"
    return value


def key(row):
    assert isinstance(row["account"], str) and isinstance(row["order_id"], str)
    return row["account"], row["order_id"]


def overlap(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def disjoint(intervals, label):
    for left, right in zip(sorted(intervals), sorted(intervals)[1:]):
        assert not overlap(left, right), f"{label}: overlapping {left} and {right}"


class CheckPlan:
    def __init__(self, folder, plan):
        self.folder, self.plan = Path(folder), plan
        self.settings = json.loads((self.folder / "settings.json").read_text())
        cutoff = self.settings["planning_cutoff"]
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            for name in ("order_versions", "stock_events", "quality_versions"):
                rows = table(self.folder, name)
                fields = list(rows[0])
                db.execute(f"CREATE TABLE {name} ({', '.join(f'[{c}] TEXT' for c in fields)})")
                db.executemany(f"INSERT INTO {name} VALUES ({','.join('?' for _ in fields)})",
                               [tuple(r.values()) for r in rows])
            selected = db.execute("""
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY account,order_id ORDER BY recorded_at DESC) AS rn
                    FROM order_versions WHERE recorded_at <= ?
                )
                SELECT account,order_id,sku,CAST(quantity AS INTEGER) AS quantity,node,
                       CAST(open AS INTEGER) AS open,CAST(close AS INTEGER) AS close,
                       CAST(service AS INTEGER) AS service
                FROM ranked WHERE rn=1 AND status='confirmed' AND effective_at <= ?
            """, (cutoff, cutoff)).fetchall()
            self.orders = {key(r):dict(r) for r in selected}
            self.balances = dict(db.execute("""
                WITH movements AS (
                    SELECT warehouse,event_id,lot,delta FROM stock_events
                    WHERE recorded_at <= ? GROUP BY warehouse,event_id,lot,delta
                )
                SELECT lot,SUM(CAST(delta AS INTEGER)) FROM movements GROUP BY lot
            """, (cutoff,)).fetchall())
            self.quality = {r["lot"]:dict(r) for r in db.execute("""
                WITH ranked AS (
                    SELECT *,ROW_NUMBER() OVER (PARTITION BY lot ORDER BY recorded_at DESC) AS rn
                    FROM quality_versions WHERE recorded_at <= ?
                )
                SELECT lot,status,CAST(available AS INTEGER) AS available FROM ranked WHERE rn=1
            """, (cutoff,))}
        self.skus = {r["sku"]:r for r in table(self.folder, "skus")}
        self.lots = {r["lot"]:r for r in table(self.folder, "lots")}
        self.benches = {r["bench"]:r for r in table(self.folder, "benches")}
        self.vehicles = {r["vehicle"]:r for r in table(self.folder, "vehicles")}
        self.travel = {(r["origin"],r["destination"]):int(r["minutes"]) for r in table(self.folder, "travel")}

    def roster(self):
        rows = self.plan["roster"]
        assert len(rows) == len(self.orders), f"Expected {len(self.orders)} dispatchable orders"
        assert len({key(r) for r in rows}) == len(rows), "Duplicate roster key"
        for row in rows:
            expected = self.orders[key(row)]
            for field, value in expected.items():
                assert type(row[field]) is type(value) and row[field] == value, f"Roster {key(row)} {field}"

    def allocations(self):
        used = Counter()
        allocated = Counter()
        for row in self.plan["allocations"]:
            order = self.orders[key(row)]
            lot = self.lots[row["lot"]]
            qty = integer(row["quantity"])
            assert qty > 0, "Nonpositive allocation"
            assert lot["sku"] == order["sku"], f"SKU mismatch {key(row)}"
            assert self.quality[row["lot"]]["status"] == "released", f"Quarantined lot {row['lot']}"
            used[row["lot"]] += qty
            allocated[key(row)] += qty
        assert allocated == Counter({k:o["quantity"] for k,o in self.orders.items()}), "Order allocation totals"
        for lot, qty in used.items():
            assert qty <= self.balances[lot], f"Stock exceeded: {lot}, allocated {qty}, available {self.balances[lot]}"

    def packing(self):
        jobs = self.plan["packing"]
        assert Counter(key(r) for r in jobs) == Counter({k:1 for k in self.orders}), "Packing coverage"
        intervals = defaultdict(list)
        for row in jobs:
            order = self.orders[key(row)]
            sku = self.skus[order["sku"]]
            bench = self.benches[row["bench"]]
            start, end = integer(row["start"]), integer(row["end"])
            assert 0 <= start < end <= self.settings["horizon"], "Packing outside horizon"
            assert sku["family"] in bench["families"].split("|"), "Bench family mismatch"
            assert int(bench["start"]) <= start and end <= int(bench["end"]), "Bench shift violation"
            assert end-start == int(sku["pack_base"])+order["quantity"]*int(sku["pack_per_unit"]), "Packing duration"
            intervals[row["bench"]].append((start,end))
        for row in table(self.folder, "bench_breaks"):
            intervals[row["bench"]].append((int(row["start"]),int(row["end"])))
        for bench, values in intervals.items():
            disjoint(values, "Bench "+bench)
        by_key = {key(r):r for r in jobs}
        for row in self.plan["allocations"]:
            assert by_key[key(row)]["start"] >= self.quality[row["lot"]]["available"], f"Lot not available {row['lot']}"

    def trips(self):
        trips = self.plan["trips"]
        assert all(isinstance(t["trip_id"],str) and t["trip_id"] for t in trips)
        assert len({t["trip_id"] for t in trips}) == len(trips), "Duplicate trip identifier"
        assert Counter(key(s) for t in trips for s in t["stops"]) == Counter({k:1 for k in self.orders}), "Trip coverage"
        by_key = {key(r):r for r in self.plan["packing"]}
        dock = [(int(r["start"]),int(r["end"])) for r in table(self.folder, "dock_breaks")]
        vehicle_times = defaultdict(list)
        for trip in trips:
            vehicle = self.vehicles[trip["vehicle"]]
            load, depart, returned = (integer(trip[f]) for f in ("load_start","depart","return"))
            assert 0 <= load < depart < returned <= self.settings["horizon"], "Trip timeline"
            assert int(vehicle["start"]) <= load and returned <= int(vehicle["end"]), "Vehicle shift"
            stops = trip["stops"]
            assert 1 <= len(stops) <= int(vehicle["max_stops"]), "Stop limit"
            units = sum(self.orders[key(s)]["quantity"] for s in stops)
            assert units <= int(vehicle["capacity"]), "Vehicle capacity"
            assert depart-load == self.settings["load_base"]+self.settings["load_per_unit"]*units, "Loading duration"
            clock, previous, drive = depart, "DEPOT", 0
            for stop in stops:
                k = key(stop)
                order = self.orders[k]
                assert self.skus[order["sku"]]["family"] in vehicle["families"].split("|"), "Vehicle family"
                assert by_key[k]["end"] <= load, f"Loading precedes packing completion: {k}"
                duration = self.travel[previous,order["node"]]
                drive += duration
                arrival = clock + duration
                start = integer(stop["service_start"])
                assert start >= arrival, f"Impossible travel to {k}: earliest {arrival}, reported {start}"
                clock = start + order["service"]
                assert order["open"] <= start and clock <= order["close"], f"Customer window: {k}"
                previous = order["node"]
            drive += self.travel[previous,"DEPOT"]
            assert returned == clock + self.travel[previous,"DEPOT"], "Incorrect depot return"
            assert drive <= int(vehicle["max_drive"]), "Vehicle driving limit"
            dock.append((load,depart))
            vehicle_times[trip["vehicle"]].append((load,returned))
        disjoint(dock,"Loading dock")
        for v, times in vehicle_times.items():
            vehicle = self.vehicles[v]
            assert len(times) <= int(vehicle["max_trips"]), "Vehicle trip count"
            for first, second in zip(sorted(times),sorted(times)[1:]):
                assert second[0] >= first[1]+int(vehicle["turnaround"]), f"Vehicle turnaround: {v}"

    def cold_chain(self):
        packing = {key(r):r for r in self.plan["packing"]}
        delivered = {}
        for trip in self.plan["trips"]:
            for stop in trip["stops"]:
                k = key(stop)
                order = self.orders[k]
                end = integer(stop["service_start"])+order["service"]
                delivered[k] = end
                allowance = int(self.skus[order["sku"]]["max_unrefrigerated"])
                exposure = end-packing[k]["end"]
                assert 0 <= exposure <= allowance, f"Thermal exposure {k}: {exposure} > {allowance}"
        for allocation in self.plan["allocations"]:
            assert delivered[key(allocation)] <= int(self.lots[allocation["lot"]]["expiry"]), \
                f"Lot expired at customer handover: {allocation['lot']}, order {key(allocation)}"

    def cost(self):
        trips = self.plan["trips"]
        cost = sum(int(self.vehicles[v]["hire_cents"]) for v in {t["vehicle"] for t in trips})
        for trip in trips:
            vehicle = self.vehicles[trip["vehicle"]]
            nodes = ["DEPOT"]+[self.orders[key(s)]["node"] for s in trip["stops"]]+["DEPOT"]
            drive = sum(self.travel[a,b] for a,b in zip(nodes,nodes[1:]))
            cost += int(vehicle["trip_cents"])+drive*int(vehicle["drive_cents_per_minute"])
        assert integer(self.plan["cost_cents"]) == cost, f"Spend declared {self.plan['cost_cents']}, actual {cost}"
        assert cost <= self.settings["budget_cents"], f"Spend {cost} exceeds authorized {self.settings['budget_cents']}"
        return cost

    def all(self):
        for name in ("roster","allocations","packing","trips","cold_chain","cost"):
            getattr(self,name)()
        return self.cost()
