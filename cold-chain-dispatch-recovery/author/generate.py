"""Generate the original deterministic operating records."""
import csv
import json
from pathlib import Path
import random

DATA = Path(__file__).resolve().parents[1] / "environment/app/data"
DATA.mkdir(parents=True, exist_ok=True)
RNG = random.Random(93107)
CUTOFF = "2026-06-15T07:50:00Z"


def write(name, rows):
    with (DATA / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


settings = dict(planning_cutoff=CUTOFF, horizon=320, load_base=4,
                load_per_unit=1, budget_cents=79000)
(DATA / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
write("skus.csv", [
    dict(sku="VAX-C", family="chilled", pack_base=4, pack_per_unit=3, max_unrefrigerated=77),
    dict(sku="LAB-F", family="frozen", pack_base=5, pack_per_unit=3, max_unrefrigerated=62),
])
orders = []
for region in range(3):
    for index in range(6):
        n = region * 6 + index
        orders.append(dict(account=["NORTH", "SOUTH", "WEST"][region],
                           order_id=f"{index + 1:03}", recorded_at="2026-06-15T06:10:00Z",
                           effective_at="2026-06-15T06:00:00Z", status="confirmed",
                           sku="VAX-C" if index < 3 else "LAB-F",
                           quantity=[2, 3, 2, 2, 2, 3][index],
                           node=f"N{n+1:02}", open=60 + region * 45,
                           close=135 + region * 45, service=3 + index % 2))
# A cancellation, an effective-later replacement and a post-cutoff amendment.
orders += [
    dict(orders[0], order_id="900", node="N01"),
    dict(orders[0], order_id="900", node="N01", recorded_at="2026-06-15T07:40:00Z", status="cancelled"),
    dict(orders[6], order_id="901", node="N07"),
    dict(orders[6], order_id="901", node="N07", recorded_at="2026-06-15T07:45:00Z",
         effective_at="2026-06-15T09:00:00Z"),
    dict(orders[2], recorded_at="2026-06-15T08:20:00Z", quantity=8),
    dict(orders[7], recorded_at="2026-06-15T07:35:00Z", quantity=2, close=170),
]
RNG.shuffle(orders)
write("order_versions.csv", orders)
lots = []
events = []
quality = []
for sku, prefix in [("VAX-C", "C"), ("LAB-F", "F")]:
    for i, (balance, available, expiry) in enumerate([(8, 0, 140), (8, 65, 205), (10, 115, 320), (30, 0, 320)]):
        lot = f"{prefix}{i+1}"
        lots.append(dict(lot=lot, sku=sku, expiry=expiry))
        event = dict(warehouse="MAIN", event_id=f"{prefix}-receive-{i}", lot=lot,
                     delta=balance+2, recorded_at="2026-06-15T06:30:00Z")
        events += [event, dict(event), dict(warehouse="MAIN", event_id=f"{prefix}-damage-{i}",
                                         lot=lot, delta=-2, recorded_at="2026-06-15T07:15:00Z")]
        quality.append(dict(lot=lot, recorded_at="2026-06-15T06:45:00Z",
                            status="released", available=available))
        if i == 3:
            quality.append(dict(lot=lot, recorded_at="2026-06-15T07:49:00Z",
                                status="quarantined", available=0))
    events.append(dict(warehouse="ANNEX", event_id=f"{prefix}-receive-0", lot=f"{prefix}1",
                       delta=1, recorded_at="2026-06-15T07:00:00Z"))
    events.append(dict(warehouse="MAIN", event_id=f"{prefix}-future", lot=f"{prefix}2",
                       delta=99, recorded_at="2026-06-15T08:30:00Z"))
write("lots.csv", lots)
RNG.shuffle(events)
write("stock_events.csv", events)
RNG.shuffle(quality)
write("quality_versions.csv", quality)
write("benches.csv", [
    dict(bench="P1", families="chilled|frozen", start=0, end=260),
    dict(bench="P2", families="chilled", start=0, end=260),
    dict(bench="P3", families="frozen", start=20, end=260),
])
write("bench_breaks.csv", [
    dict(bench="P1", start=90, end=110),
    dict(bench="P2", start=105, end=125),
    dict(bench="P3", start=120, end=140),
])
write("dock_breaks.csv", [dict(start=96, end=110)])
vehicles = []
for index, families in enumerate(["chilled", "frozen", "chilled|frozen", "chilled", "frozen"]):
    vehicles.append(dict(vehicle=f"V{index+1}", families=families, capacity=8, max_stops=3,
                         max_drive=72, start=0 if index < 3 else 85, end=300,
                         turnaround=15, max_trips=3, hire_cents=11500 if index<3 else 14500,
                         trip_cents=1800, drive_cents_per_minute=70))
write("vehicles.csv", vehicles)
nodes = ["DEPOT"] + [f"N{i:02}" for i in range(1, 19)]
travel = []
for a in nodes:
    for b in nodes:
        if a == b:
            t = 0
        elif a == "DEPOT":
            n = int(b[1:])-1
            t = 14 + n//6 * 4 + n%3
        elif b == "DEPOT":
            n = int(a[1:])-1
            t = 13 + n//6 * 4 + n%4
        else:
            x, y = int(a[1:])-1, int(b[1:])-1
            t = (5 + abs(x%6-y%6) + (x*3+y)%3 if x//6 == y//6
                 else 27 + abs(x//6-y//6)*7 + (x+y)%5)
        travel.append(dict(origin=a, destination=b, minutes=t))
write("travel.csv", travel)
print(f"Generated {len(orders)} order versions and {len(travel)} directed travel entries")
