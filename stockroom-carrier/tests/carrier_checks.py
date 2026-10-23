"""Independent black-box witnesses for separate local and carrier authorities."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import traceback

from durable_checks import SENTINEL, diagnostic, digest, seal, status
from test_semantics import APP, equal, event, successful_structure

sys.path.insert(0, str(APP))
from carrier_service import Carrier, initialize

STOCK = {"east": {"gear": 20, "seal": 20}, "west": {"gear": 20, "seal": 20}}
SEND = 'let r:string=carrier_send("x","east","gear",2,"seal",1);'


class Fixture:
    def __init__(self, root, *, policies=None, accepted=None, stock=None, workflow=False):
        self.root = root
        self.program = root / "run.stock"
        self.incoming = root / "inventory.json"
        self.database = root / "carrier.sqlite"
        self.output = root / "result.json"
        self.saved = root / "checkpoint.json"
        self.library = APP / "workflows/dispatch.stock" if workflow else None
        self.incoming.write_text(json.dumps({"warehouses": stock or STOCK}))
        self.output.write_bytes(SENTINEL)
        seed = root / "seed.json"
        seed.write_text(json.dumps(dict(service_id="fixture-history",
                                       policies=policies or {}, accepted=accepted or {})))
        initialize(seed, self.database)
        self.carrier = Carrier(self.database)

    def run(self, source=None, *, save=False, resume=False, output=None, carrier=True):
        if source is not None:
            self.program.write_text(source)
        command = [sys.executable, "-m", "stockroom", str(self.program),
                   "--inventory", str(self.incoming), "--out", str(output or self.output)]
        if carrier:
            command += ["--carrier", str(self.database)]
        if self.library:
            command += ["--library", str(self.library)]
        if save:
            command += ["--checkpoint", str(self.saved)]
        if resume:
            command += ["--resume", str(self.saved)]
        return subprocess.run(command, cwd=APP, capture_output=True, text=True, timeout=15)

    def checkpoint(self):
        obj = json.loads(self.saved.read_text())
        equal(obj["checksum"], seal(obj)["checksum"], "carrier checkpoint checksum")
        equal(obj["identity"], dict(program=digest(self.program.read_bytes()),
                                    inventory=digest(self.incoming.read_bytes()),
                                    library=digest(self.library.read_bytes()) if self.library else None,
                                    carrier=self.carrier.service_id), "carrier checkpoint identity")
        return obj

    def finish(self, source=None, *, resume=False):
        process = self.run(source, save=True, resume=resume)
        labels = []
        for _ in range(200):
            if process.returncode != 10:
                status(process, 0)
                result = json.loads(self.output.read_text())
                successful_structure(result)
                return result, labels
            status(process, 10)
            obj = self.checkpoint()
            labels.append(obj["label"])
            before = self.saved.read_bytes()
            process = self.run(resume=True)
            if process.returncode == 0:
                equal(self.saved.read_bytes().hex(), before.hex(), "completion preserves checkpoint")
        raise AssertionError("Continuation did not terminate within 200 documented boundaries")

    def accepted(self):
        with sqlite3.connect(self.database) as connection:
            keys = [row[0] for row in connection.execute("SELECT request_key FROM accepted")]
        return {key: self.carrier.lookup(key) for key in keys}

    def attempts(self):
        with sqlite3.connect(self.database) as connection:
            return connection.execute(
                "SELECT request_key,outcome FROM attempts ORDER BY seq").fetchall()


@contextmanager
def fixture(**kwargs):
    with tempfile.TemporaryDirectory(prefix="stockroom-carrier-") as directory:
        yield Fixture(Path(directory), **kwargs)


def events(result, expected):
    equal(result["events"], [dict(value, id=i) for i, value in enumerate(expected, 1)], "events")


def timeout_witness(mode):
    with fixture(policies={"x": mode}) as f:
        status(f.run('proc main(){transaction {' + SEND + ''' assert false;}
recover(e){emit "caught" {reason:code(e);};}
emit "observed" {found:len(carrier_receipt("x"))>0;};}'''), 0)
        result = json.loads(f.output.read_text())
        accepted = mode in {"ack", "accept_then_timeout_once"}
        code = {"ack":"ASSERT", "reject":"CARRIER_REJECTED"}.get(mode, "CARRIER_TIMEOUT")
        events(result, [event("caught", reason=code), event("observed", found=accepted)])
        equal(result["warehouses"], STOCK, "rollback inventory")
        equal(result["deliveries"], {}, "rollback local ledger")
        equal(sorted(f.accepted()), ["x"] if accepted else [], "external acceptance")
        equal(len(f.attempts()), 1, "external attempt survives rollback")


def idempotency():
    with fixture() as f:
        source = '''proc main(){''' + SEND + '''
let again:string=carrier_send("x","east","gear",2,"seal",1);
emit "same" {ok:r==again; payload:carrier_matches("x","east","gear",2,"seal",1);};
transaction {let bad:string=carrier_send("x","west","gear",2,"seal",1);}
recover(e){emit "conflict" {reason:code(e);};}
emit "original" {warehouse:carrier_warehouse("x");};
}'''
        status(f.run(source), 0)
        events(json.loads(f.output.read_text()),
               [event("same", ok=True, payload=True), event("conflict", reason="CARRIER_CONFLICT"),
                event("original", warehouse="east")])
        equal(len(f.accepted()), 1, "one physical acceptance")
        equal([row[1] for row in f.attempts()], ["accepted", "replayed", "conflict"], "attempt audit")


def validation(expression, expected):
    with fixture() as f:
        source = ('proc main(){transaction {let value:string=' + expression +
                  ';} recover(e){emit "error" {reason:code(e);};}}')
        status(f.run(source), 0)
        events(json.loads(f.output.read_text()), [event("error", reason=expected)])
        equal(f.attempts(), [], "invalid input must not call service")


def record_validation(body, expected):
    with fixture() as f:
        status(f.run('proc main(){' + SEND + 'transaction {' + body +
                     '} recover(e){emit "error" {reason:code(e);};}}'), 0)
        result = json.loads(f.output.read_text())
        events(result, [event("error", reason=expected)])
        equal(result["deliveries"], {}, "validation has no partial delivery")
        equal(result["warehouses"], STOCK, "failed bookkeeping transaction rollback")
        equal(result["holds"], {}, "failed bookkeeping holds rollback")
        equal(sorted(f.accepted()), ["x"], "failed bookkeeping preserves external record")


CLOSE = '''reserve("x.a","east","gear",2);reserve("x.b","east","seal",1);
ship("x.a",2);ship("x.b",1);'''


def local_ledger():
    with fixture() as f:
        result, labels = f.finish('proc main(){' + SEND + '''
transaction {''' + CLOSE + '''record_delivery("x",r);pause "posted";
assert delivered("x");assert false;
} recover(e){emit "undone" {local:delivered("x");remote:len(carrier_receipt("x"))>0;};}
''' + CLOSE + '''record_delivery("x",r);pause "reapplied";
transaction {record_delivery("x",r);} recover(e){emit "duplicate" {reason:code(e);};}
}''')
        equal(labels, ["posted", "reapplied"], "ledger boundaries")
        equal(result["deliveries"], f.accepted(), "restored local records")
        equal(result["warehouses"]["east"], {"gear":18, "seal":19}, "single local debit")
        events(result, [event("undone", local=False, remote=True),
                        event("duplicate", reason="ALREADY_POSTED")])
        equal(len(f.attempts()), 1, "reapplication uses existing acceptance")


def fault_after_send(kind):
    with fixture() as f:
        f.saved.write_bytes(SENTINEL)
        source = 'proc main(){' + SEND + ('let zero:int=1/0;' if kind == "runtime" else '') + '}'
        output = f.root / "missing" / "result.json" if kind == "publication" else f.output
        process = f.run(source, save=True, output=output)
        diagnostic(process, "RUNTIME" if kind == "runtime" else "IO", 5 if kind == "runtime" else 7)
        equal(f.saved.read_bytes().hex(), SENTINEL.hex(), "failure preserves checkpoint")
        equal(f.output.read_bytes().hex(), SENTINEL.hex(), "failure preserves output")
        if kind == "publication" and not f.attempts():
            equal(f.accepted(), {}, "output-path preflight has no external effect")
            return
        equal(sorted(f.accepted()), ["x"], "external effect survives fatal failure")
        equal(len(f.attempts()), 1, "fatal failure retains attempt audit")


def static_before_send():
    with fixture() as f:
        diagnostic(f.run('proc main(){' + SEND + 'let invalid:int=true;}'), "STATIC", 3)
        equal(f.accepted(), {}, "static validation before execution")
        equal(f.attempts(), [], "static validation before carrier call")
        equal(f.output.read_bytes().hex(), SENTINEL.hex(), "static error preserves output")


def carrier_io(kind):
    with fixture() as f:
        source = 'proc main(){' + SEND + '}'
        before = f.database.read_bytes()
        if kind == "missing":
            f.database = f.root / "absent.sqlite"
        elif kind == "corrupt":
            f.database.write_bytes(b"not a SQLite database")
        elif kind == "no-identity":
            f.database = f.root / "empty.sqlite"
            with sqlite3.connect(f.database) as connection:
                connection.execute("CREATE TABLE metadata(name TEXT,value TEXT)")
        if kind == "alias-output":
            process = f.run(source, output=f.database)
        elif kind == "alias-checkpoint":
            f.saved = f.database
            process = f.run(source, save=True)
        else:
            process = f.run(source, carrier=kind != "unspecified")
        diagnostic(process, "IO", 7)
        equal(f.output.read_bytes().hex(), SENTINEL.hex(), "IO preserves output")
        if kind.startswith("alias"):
            equal(f.database.read_bytes().hex(), before.hex(), "alias cannot overwrite service")
            equal(f.attempts(), [], "alias rejected before execution")


def service_identity(changed):
    with fixture() as f:
        status(f.run('proc main(){pause "observe";emit "receipt" {found:len(carrier_receipt("x"))>0;};}',
                     save=True), 10)
        before = f.saved.read_bytes()
        f.checkpoint()
        if changed:
            alternate = f.root / "other.sqlite"
            seed = f.root / "alternate.json"
            seed.write_text('{"service_id":"different-history","policies":{}}')
            initialize(seed, alternate)
            f.database = alternate
            diagnostic(f.run(resume=True), "CHECKPOINT", 8)
            equal(f.output.read_bytes().hex(), SENTINEL.hex(), "identity mismatch output atomicity")
        else:
            f.carrier.submit("x", "west", "gear", 2, "seal", 1)
            old = f.root / "relocated"
            old.mkdir()
            for attribute in ("program", "incoming", "saved", "database"):
                path = getattr(f, attribute)
                target = old / path.name
                shutil.move(path, target)
                setattr(f, attribute, target)
            f.carrier = Carrier(f.database)
            status(f.run(resume=True), 0)
            events(json.loads(f.output.read_text()), [event("receipt", found=True)])
            equal(sorted(f.accepted()), ["x"], "resume does not rewind advanced service")
        equal(f.saved.read_bytes().hex(), before.hex(), "resume preserves saved envelope")


def call(order):
    return "dispatch_order(" + ",".join(json.dumps(value) for value in order) + ");"


def stale_replay():
    with fixture(workflow=True, policies={"x":"accept_then_timeout_once"}) as f:
        source = 'proc main(){' + call(("x","gear",2,"seal",1,"east","west")) + '}'
        status(f.run(source, save=True), 10)
        equal(f.checkpoint()["label"], "x:reserved", "first operational boundary")
        archived = f.saved.read_bytes()
        first, labels = f.finish(resume=True)
        equal(labels[-1], "x:posted", "posting boundary")
        accepted = f.accepted()
        history = f.attempts()
        f.saved.write_bytes(archived)
        f.output.write_bytes(SENTINEL)
        replayed, labels = f.finish(resume=True)
        for key in ("warehouses", "holds", "events", "deliveries"):
            equal(replayed[key], first[key], "stale replay local " + key)
        equal(f.accepted(), accepted, "stale replay preserves physical acceptance")
        equal(len(accepted), 1, "stale replay must not use a fresh idempotency key")
        equal(f.attempts()[:len(history)], history, "replay preserves old attempt history")
        equal(sum(outcome in {"accepted","timeout_after_accept"} for _,outcome in f.attempts()),
              1, "one physical acceptance across stale replay")


def evaluation_order():
    with fixture() as f:
        source = '''proc main(){let r:string=carrier_send(
carrier_send("inner","east","gear",2,"seal",1),"east","gear",1/0,"seal",1);}'''
        diagnostic(f.run(source), "RUNTIME", 5)
        equal(sorted(f.accepted()), ["inner"], "left operand effect precedes right operand failure")
        equal(len(f.attempts()), 1, "outer call must not execute after argument failure")


def lookup_and_short_circuit():
    with fixture() as f:
        source = '''proc main(){
assert true || len(carrier_send("skipped","east","gear",2,"seal",1))>0;
let ignored:bool=false && len(carrier_send("skipped-too","east","gear",2,"seal",1))>0;
emit "unknown" {receipt:carrier_receipt("missing");warehouse:carrier_warehouse("missing");
matches:carrier_matches("missing","east","gear",2,"seal",1);local:delivered("missing");};
}'''
        status(f.run(source), 0)
        events(json.loads(f.output.read_text()),
               [event("unknown",receipt="",warehouse="",matches=False,local=False)])
        equal(f.attempts(), [], "short-circuited external expressions must not execute")


def large_carrier_quantity():
    with fixture() as f:
        n = 10**90
        status(f.run('proc main(){let r:string=carrier_send("x","east","gear",'
                     +str(n)+',"seal",1);assert carrier_matches("x","east","gear",'
                     +str(n)+',"seal",1);}'), 0)
        equal(f.carrier.lookup("x")["qty_a"], n, "carrier quantities exceed machine integer width")


def existing_holds():
    with fixture(workflow=True) as f:
        result, labels = f.finish('proc main(){reserve("safety","east","gear",19);'
                                 +call(("x","gear",2,"seal",1,"east","west"))+'}')
        equal(result["deliveries"]["x"]["warehouse"], "west", "routing uses free stock")
        equal(result["holds"]["safety"]["remaining"], 19, "unrelated reservation preserved")
        equal(result["warehouses"]["east"], STOCK["east"], "reserved source not debited")
        equal(labels, ["x:reserved","x:posted"], "normal operational boundaries")


def same_sku_routing():
    stock = {"east":{"gear":3},"west":{"gear":4}}
    with fixture(workflow=True, stock=stock) as f:
        result, labels = f.finish('proc main(){'+call(
            ("x","gear",2,"gear",2,"east","west"))+'}')
        equal(result["warehouses"], {"east":{"gear":3},"west":{"gear":0}}, "aggregate same-SKU demand")
        equal(result["deliveries"]["x"]["warehouse"], "west", "same-SKU fallback routing")
        equal(labels, ["x:reserved","x:posted"], "same-SKU operational boundaries")


def mismatched_import():
    record = dict(receipt="opaque",warehouse="west",sku_a="gear",qty_a=3,sku_b="seal",qty_b=2)
    with fixture(workflow=True, accepted={"x":record}) as f:
        process = f.run('proc main(){'+call(("x","gear",4,"seal",2,"east","west"))+'}')
        diagnostic(process, "DOMAIN", 4)
        equal(f.output.read_bytes().hex(), SENTINEL.hex(), "mismatched import cannot publish success")
        equal(f.carrier.lookup("x"), record, "mismatched import leaves authoritative payload")
        equal(f.attempts(), [], "mismatched import is not resent")


def workflow_reference(stock, orders, policies, preaccepted):
    inventory = copy.deepcopy(stock)
    local = {}
    accepted = copy.deepcopy(preaccepted)
    holds, expected_events, submissions = {}, [], {}
    for key, a, qa, b, qb, preferred, fallback in orders:
        if key in local:
            continue
        record = accepted.get(key)
        chosen = record["warehouse"] if record else None
        if chosen is None:
            needs = {a:qa}
            needs[b] = needs.get(b, 0) + qb
            chosen = next((w for w in (preferred, fallback)
                           if all(inventory[w].get(s, 0) >= q for s,q in needs.items())), None)
        if chosen is None:
            expected_events.append(event("deferred", order=key, reason="SHORTAGE"))
            continue
        if record is None:
            mode = policies.get(key, "ack")
            submissions[key] = submissions.get(key, 0) + (2 if mode == "timeout_before_once" else 1)
            if mode == "reject":
                expected_events.append(event("rejected", order=key, reason="CARRIER_REJECTED"))
                continue
            record = dict(warehouse=chosen, sku_a=a, qty_a=qa, sku_b=b, qty_b=qb)
            accepted[key] = record
        local[key] = record
        for suffix, sku, qty in ((".a",a,qa),(".b",b,qb)):
            inventory[chosen][sku] = inventory[chosen].get(sku, 0) - qty
            holds[key+suffix] = dict(warehouse=chosen, sku=sku, remaining=0)
        expected_events.append(event("fulfilled", order=key, warehouse=chosen, units=qa+qb))
    return inventory, holds, local, accepted, expected_events, submissions


def workflow_batch(seed):
    rng = random.Random(77103+seed)
    stock = {w:{s:rng.randrange(8,35) for s in ("gear","seal","bolt")} for w in ("east","west")}
    orders, policies = [], {}
    for index in range(10):
        key = f"job-{seed}-{index}"
        a,b = rng.choice(["gear","seal","bolt"]),rng.choice(["gear","seal","bolt"])
        preferences = ("east","west") if rng.randrange(2) else ("west","east")
        order = (key,a,rng.randrange(1,7),b,rng.randrange(1,7),*preferences)
        orders.append(order)
        policies[key] = ["ack","accept_then_timeout_once","timeout_before_once","reject"][index%4]
        if index%3 == 0:
            orders.append((*order[:5],*reversed(preferences)))
    expected_stock, holds, local, accepted, expected_events, submissions = workflow_reference(
        stock, orders, policies, {})
    with fixture(workflow=True, policies=policies, stock=stock) as f:
        source = "proc main(){" + "".join(call(order) for order in orders) + "}"
        result, labels = f.finish(source)
        equal(result["warehouses"], expected_stock, "generated inventory")
        equal(result["holds"], holds, "generated holds")
        actual_remote = f.accepted()
        equal(sorted(actual_remote), sorted(accepted), "generated physical acceptance keys")
        for key, record in accepted.items():
            equal({k:v for k,v in actual_remote[key].items() if k != "receipt"},
                  {k:v for k,v in record.items() if k != "receipt"}, "generated payload")
        equal(result["deliveries"], {key:actual_remote[key] for key in local}, "generated local ledger")
        for item in expected_events:
            if item["name"] == "fulfilled":
                item["data"]["receipt"] = actual_remote[item["data"]["order"]]["receipt"]
        events(result, expected_events)
        for key in local:
            if key+":reserved" not in labels or labels.count(key+":posted") != 1:
                raise AssertionError(f"Missing/duplicate operational boundaries for {key}")
        for key in {order[0] for order in orders}:
            count = sum(attempt_key == key for attempt_key,_ in f.attempts())
            upper = submissions.get(key, 0)
            # An accepted-then-timeout may be reconciled by lookup or one same-key retry.
            if policies[key] == "accept_then_timeout_once" and upper:
                upper += 1
            if count > upper:
                raise AssertionError(f"Excess carrier submissions for {key}: {count}>{upper}")


def enclosing_rollback():
    record = dict(receipt="imported-not-a-generated-id", warehouse="west",
                  sku_a="gear", qty_a=3, sku_b="seal", qty_b=2)
    with fixture(workflow=True, accepted={"imported":record}) as f:
        source = 'proc main(){transaction {' + call(("x","gear",2,"seal",1,"east","west")) + '''
pause "abandon";assert false;} recover(e){emit "undo" {local:delivered("x");};}
''' + call(("x","gear",2,"seal",1,"west","east")) + call(
            ("imported","gear",3,"seal",2,"east","west")) + '}'
        result, labels = f.finish(source)
        equal(result["warehouses"], {"east":{"gear":18,"seal":19},"west":{"gear":17,"seal":18}},
              "accepted routing after enclosing rollback")
        equal(result["deliveries"], f.accepted(), "import and reapplication")
        events(result, [event("undo", local=False),
                        event("fulfilled", order="x", warehouse="east", units=3,
                              receipt=f.carrier.lookup("x")["receipt"]),
                        event("fulfilled", order="imported", warehouse="west", units=5,
                              receipt=record["receipt"])])
        equal(f.attempts(), [("x","accepted")], "no resubmission of known acceptances")
        equal(labels.count("x:posted"), 2, "tentative post then reconciled post")


def reference_regression(kind):
    with fixture() as f:
        if kind == "marker-keys":
            f.incoming.write_text('{"warehouses":{"east":{"$fault":7,"$token":8},"west":{}}}')
            source = '''proc main(){pause "marker";
emit "stock" {a:onhand("east","$fault");b:onhand("east","$token");};}'''
            result, _ = f.finish(source)
            events(result, [event("stock", a=7, b=8)])
        else:
            source = ('proc main(){let n:int=' + "9"*5000 +
                      ';pause "integer";emit "big" {valid:n>0;unchanged:(n+1)-n==1;};}')
            # The checkpoint is opaque here; avoid the verifier's own decimal-input ceiling.
            status(f.run(source, save=True), 10)
            status(f.run(resume=True), 0)
            events(json.loads(f.output.read_text()), [event("big", valid=True, unchanged=True)])


def incident():
    result = json.loads((APP/"deliverable/carrier-result.json").read_text())
    successful_structure(result)
    carrier = Carrier(APP/"carrier/state.sqlite")
    accepted = {key:carrier.lookup(key) for key in ("drill","alpha","beta","orphan")}
    equal(result["warehouses"], {"east":{"gear":17,"seal":12},"west":{"gear":17,"seal":28}},
          "incident local inventory")
    equal(result["deliveries"], accepted, "incident local ledger")
    holds = {}
    expected = [event("rehearsal_reverted", reason="ASSERT")]
    for key in ("drill","alpha","beta","orphan"):
        record = accepted[key]
        if record is None:
            raise AssertionError("Missing authoritative acceptance for " + key)
        warehouse,qa,qb = {"drill":("east",2,1),"alpha":("east",6,4),
                           "beta":("east",5,3),"orphan":("west",3,2)}[key]
        equal({k:v for k,v in record.items() if k != "receipt"},
              dict(warehouse=warehouse,sku_a="gear",qty_a=qa,sku_b="seal",qty_b=qb),
              "incident authoritative ordered payload for "+key)
        for suffix, field in ((".a","sku_a"),(".b","sku_b")):
            holds[key+suffix] = dict(warehouse=record["warehouse"],sku=record[field],remaining=0)
        expected.append(event("fulfilled", order=key, warehouse=record["warehouse"],
                              units=record["qty_a"]+record["qty_b"],receipt=record["receipt"]))
    equal(result["holds"], holds, "incident closed holds")
    expected += [event("rejected",order="blocked",reason="CARRIER_REJECTED"),
                 event("deferred",order="gamma",reason="SHORTAGE"),
                 event("closing",east_gear=17,west_gear=17)]
    events(result, expected)
    equal(accepted["orphan"], dict(receipt="receipt-imported-z9",warehouse="west",
                                  sku_a="gear",qty_a=3,sku_b="seal",qty_b=2), "preserve imported receipt")
    equal(accepted["drill"]["warehouse"], "east", "carrier determines rehearsal routing")
    with sqlite3.connect(APP/"carrier/state.sqlite") as connection:
        equal(sorted(row[0] for row in connection.execute("SELECT request_key FROM accepted")),
              sorted(accepted), "incident acceptance keys")
        attempts = connection.execute("SELECT request_key,outcome FROM attempts ORDER BY seq").fetchall()
    equal(sum(key == "gamma" for key,_ in attempts), 0, "shortage has no submission")
    if len(attempts) > 8 or ("alpha","timeout_after_accept") not in attempts or (
            "beta","timeout_before_accept") not in attempts:
        raise AssertionError("Missing/excess incident request history")
    saved = json.loads((APP/"deliverable/carrier-checkpoint.json").read_text())
    equal(saved["identity"]["carrier"], carrier.service_id, "incident durable identity")
    equal(saved["checksum"], seal(saved)["checksum"], "incident checkpoint checksum")
    if saved["pause_count"] < 10:
        raise AssertionError("Incident was not driven through required pause boundaries")


def immutable_service():
    equal(hashlib.sha256((APP/"carrier_service.py").read_bytes()).hexdigest(),
          "08485d8917c0a2b11403fc533d638195bd74f0066e3c561a818413d948a9db33",
          "immutable supplied carrier API")


def run_all():
    cases = []
    for mode in ("ack","accept_then_timeout_once","timeout_before_once","reject"):
        cases.append(("authority-"+mode, lambda mode=mode: timeout_witness(mode)))
    cases += [("idempotency-and-conflict",idempotency),
              ("local-ledger-rollback-and-resume",local_ledger),
              ("runtime-preserves-external-effect",lambda:fault_after_send("runtime")),
              ("publication-preserves-external-effect",lambda:fault_after_send("publication")),
              ("static-validation-before-effect",static_before_send),
              ("external-argument-evaluation-order",evaluation_order),
              ("lookup-and-external-short-circuit",lookup_and_short_circuit),
              ("arbitrary-precision-carrier-quantity",large_carrier_quantity),
              ("workflow-respects-existing-reservations",existing_holds),
              ("workflow-aggregates-same-sku-lines",same_sku_routing),
              ("workflow-rejects-mismatched-import",mismatched_import),
              ("advanced-relocated-service",lambda:service_identity(False)),
              ("different-service-identity",lambda:service_identity(True)),
              ("stale-checkpoint-replay",stale_replay),
              ("enclosing-rollback-and-imported-routing",enclosing_rollback),
              ("marker-key-regression",lambda:reference_regression("marker-keys")),
              ("large-integer-regression",lambda:reference_regression("large-integer"))]
    for name in ("missing","corrupt","no-identity","unspecified","alias-output","alias-checkpoint"):
        cases.append(("carrier-io-"+name,lambda name=name:carrier_io(name)))
    for index, (expr, code) in enumerate([
            ('carrier_send("","east","gear",2,"seal",1)',"NAME"),
            ('carrier_send("x","","gear",2,"seal",1)',"NAME"),
            ('carrier_send("x","elsewhere","gear",2,"seal",1)',"WAREHOUSE"),
            ('carrier_send("x","east","",2,"seal",1)',"NAME"),
            ('carrier_send("x","east","gear",0,"seal",1)',"QUANTITY"),
            ('carrier_send("x","east","gear",2,"seal",-1)',"QUANTITY"),
            ('carrier_receipt("")',"NAME"),
            ('carrier_warehouse("")',"NAME")]):
        cases.append((f"carrier-validation-{index}",lambda expr=expr,code=code:validation(expr,code)))
    for index, (body, code) in enumerate([
            ('record_delivery("x","wrong");',"CARRIER_CONFLICT"),
            ('record_delivery("absent",r);',"CARRIER_CONFLICT"),
            ('record_delivery("x",r);',"HOLD"),
            ('reserve("x.a","east","gear",2);reserve("x.b","east","seal",1);record_delivery("x",r);',"HOLD"),
            ('reserve("x.a","west","gear",2);ship("x.a",2);reserve("x.b","west","seal",1);ship("x.b",1);record_delivery("x",r);',"HOLD"),
            ('record_delivery("",r);',"NAME")]):
        cases.append((f"delivery-validation-{index}",lambda body=body,code=code:record_validation(body,code)))
    for seed in range(12):
        cases.append((f"generated-carrier-stream-{seed}",lambda seed=seed:workflow_batch(seed)))
    cases += [("carrier-incident-deliverable",incident),("immutable-carrier-service",immutable_service)]
    records = []
    for name, check in cases:
        try:
            check()
            records.append(dict(name=name,group="carrier",passed=True))
        except (AssertionError,OSError,ValueError,KeyError,TypeError,sqlite3.Error,
                subprocess.TimeoutExpired):
            records.append(dict(name=name,group="carrier",passed=False,detail=traceback.format_exc()))
    return records
