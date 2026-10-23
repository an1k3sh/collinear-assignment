from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3


def read(data,name):
    with (data/name).open() as f:
        return list(csv.DictReader(f))


class Check:
    def __init__(self,data,topology,plan,reference=None):
        self.data=Path(data)
        self.topology,self.plan=topology,plan
        if reference is None:
            reference=json.loads(Path(__file__).with_name("reference_topology.json").read_text())
        self.edges={r["cable"]:frozenset([r["a"],r["b"]]) for r in reference["links"]}
        self.settings=json.loads((self.data/"settings.json").read_text())
        with sqlite3.connect(":memory:") as db:
            db.row_factory=sqlite3.Row
            db.execute("CREATE TABLE versions (cable TEXT,recorded_at TEXT,status TEXT,capacity INTEGER,risk_group TEXT,activation_cents INTEGER)")
            db.executemany("INSERT INTO versions VALUES (?,?,?,?,?,?)",
                           [tuple(r[k] for k in ("cable","recorded_at","status","capacity","risk_group","activation_cents"))
                            for r in read(self.data,"cable_versions.csv")])
            self.inventory={r["cable"]:dict(r) for r in db.execute("""
                WITH ranked AS (
                    SELECT *,ROW_NUMBER() OVER (PARTITION BY cable ORDER BY recorded_at DESC) AS rn
                    FROM versions WHERE recorded_at<=?
                )
                SELECT cable,status,capacity,risk_group,activation_cents FROM ranked WHERE rn=1
            """,(self.settings["planning_cutoff"],))}
        self.phases={r["phase"] for r in read(self.data,"phases.csv")}
        self.outages={(r["phase"],r["cable"]) for r in read(self.data,"outages.csv")}
        self.services={r["service"]:r for r in read(self.data,"services.csv")}

    def transcription(self):
        links=self.topology["links"]
        assert len(links)==len(self.edges), f"Expected {len(self.edges)} drawn cables"
        actual={r["cable"]:frozenset([r["a"],r["b"]]) for r in links}
        assert len(actual)==len(links), "Duplicate cable"
        assert set(actual)==set(self.edges), "Cable inventory mismatch"
        wrong={c:dict(submitted=sorted(actual[c]),drawn=sorted(self.edges[c])) for c in actual if actual[c]!=self.edges[c]}
        assert not wrong, f"Incorrect cable terminations: {json.dumps(wrong,sort_keys=True)}"

    def coverage(self):
        phases=self.plan["phases"]
        assert Counter(p["phase"] for p in phases)==Counter({p:1 for p in self.phases}), "Phase coverage"
        expected=Counter()
        for service,row in self.services.items():
            expected[service,"primary"]=1
            if row["protection"]=="1+1":
                expected[service,"secondary"]=1
        for phase in phases:
            assert Counter((r["service"],r["role"]) for r in phase["routes"])==expected, f"Service coverage in {phase['phase']}"

    def walk(self,route):
        service=self.services[route["service"]]
        node=service["source"]
        visited={node}
        assert isinstance(route["cables"],list) and route["cables"], "Empty cable path"
        assert len(set(route["cables"]))==len(route["cables"]), "Cable repeated on path"
        for cable in route["cables"]:
            endpoints=self.edges[cable]
            assert node in endpoints, f"{route['service']}/{route['role']}: cable {cable} cannot be reached from {node}; actual endpoints {sorted(endpoints)}"
            node=next(n for n in endpoints if n!=node)
            assert node not in visited, f"Route revisits node {node}"
            visited.add(node)
        assert node==service["target"], f"Route ends at {node}, not {service['target']}"

    def connectivity(self):
        for phase in self.plan["phases"]:
            for route in phase["routes"]:
                self.walk(route)

    def availability(self):
        activated=self.plan["activate"]
        assert isinstance(activated,list) and len(set(activated))==len(activated), "Duplicate activation"
        for cable in activated:
            assert self.inventory[cable]["status"]=="dark", f"Only dark cables may be activated: {cable}"
        for phase in self.plan["phases"]:
            for route in phase["routes"]:
                for cable in route["cables"]:
                    row=self.inventory[cable]
                    assert row["status"]=="lit" or (row["status"]=="dark" and cable in activated), f"Cable unavailable: {cable}"
                    assert (phase["phase"],cable) not in self.outages, f"Outage cable {cable} in {phase['phase']}"

    def protection(self):
        for phase in self.plan["phases"]:
            groups={(r["service"],r["role"]):{self.inventory[c]["risk_group"] for c in r["cables"]}
                    for r in phase["routes"]}
            for service,row in self.services.items():
                if row["protection"]=="1+1":
                    common=groups[service,"primary"] & groups[service,"secondary"]
                    assert not common, f"Shared failure domain: {phase['phase']}/{service}: {sorted(common)}"

    def capacity(self):
        for phase in self.plan["phases"]:
            loads=Counter()
            for route in phase["routes"]:
                for cable in route["cables"]:
                    loads[cable]+=int(self.services[route["service"]]["units"])
            for cable,load in loads.items():
                assert load<=self.inventory[cable]["capacity"], f"Capacity exceeded {phase['phase']}/{cable}: {load}>{self.inventory[cable]['capacity']}"

    def budget(self):
        cost=sum(self.inventory[c]["activation_cents"] for c in self.plan["activate"])
        assert type(self.plan["activation_cents"]) is int and self.plan["activation_cents"]==cost, "Incorrect activation cost"
        assert cost<=self.settings["budget_cents"], f"Activation {cost} exceeds {self.settings['budget_cents']}"
        return cost

    def all(self):
        for name in ("transcription","coverage","connectivity","availability","protection","capacity","budget"):
            getattr(self,name)()
        return self.budget()
