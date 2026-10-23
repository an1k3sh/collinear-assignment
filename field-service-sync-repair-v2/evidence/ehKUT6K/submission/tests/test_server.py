"""Server regressions for the work-order sync protocol (run via tests/smoke.py)."""
import json
import multiprocessing
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.codec import SyncError, token, untoken  # noqa: E402
from server.store import Store  # noqa: E402

BODY = {"title": "Inspection", "assignee": None, "visits": 0, "done": False}


def req(mutation, entity, base, kind, data, tenant="north", device="van-7"):
    return {"tenant": tenant, "device": device, "mutation": mutation, "id": entity,
            "base": base, "kind": kind, "data": data}


def dump(path):
    db = sqlite3.connect(path)
    try:
        return {table: sorted(db.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
                for table in ("metadata", "documents", "events", "receipts", "batches")}
    finally:
        db.close()


def drain_snapshot(store, tenant, limit):
    pages, cursor = [], None
    while True:
        page = store.snapshot(tenant, limit, cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


def drain_pull(store, tenant, checkpoint, limit):
    pages, cursor = [], None
    while True:
        page = store.pull(tenant, checkpoint, limit, cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


def _race_worker(path, request, batch, queue):
    store = Store(path)
    try:
        result = store.mutate_batch(request) if batch else store.mutate(request)
        queue.put(("ok", json.dumps(result, sort_keys=True)))
    except SyncError as exc:
        queue.put(("error", exc.code))


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "work.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def error(self, call, *args, **kwargs):
        with self.assertRaises(SyncError) as caught:
            call(*args, **kwargs)
        return caught.exception

    def create(self, entity, mutation=None, tenant="north", device="van-7", **body):
        return self.store.mutate(req(mutation or f"c-{tenant}-{entity}", entity, "0", "create",
                                     {**BODY, **body}, tenant, device))


class Mutations(Base):
    def test_wire_decimals_are_strings(self):
        response = self.create("order")
        self.assertEqual(response["record"]["revision"], "1")
        self.assertIsInstance(response["record"]["seq"], str)
        self.assertEqual(set(response), {"ok", "tenant", "device", "mutation", "record"})

    def test_retry_returns_original_receipt_after_newer_writes(self):
        self.create("pump")
        visit = req("m-9", "pump", "1", "visit", {"amount": 1})
        first = self.store.mutate(visit)
        self.store.mutate(req("m-10", "pump", "2", "patch", {"assignee": "Mira"}))
        reordered = dict(reversed(list(visit.items())))
        self.assertEqual(Store(self.path).mutate(reordered), first)
        snapshot = self.store.snapshot("north", 10)["rows"][0]
        self.assertEqual(snapshot["body"]["visits"], 1)
        self.assertEqual(snapshot["revision"], "3")

    def test_same_mutation_id_other_device_is_independent(self):
        self.create("pump")
        mine = self.store.mutate(req("m-9", "pump", "1", "visit", {"amount": 1}))
        theirs = self.store.mutate(req("m-9", "pump", "2", "patch", {"assignee": "Lee"},
                                       device="van-8"))
        self.assertEqual(mine["device"], "van-7")
        self.assertEqual(theirs["device"], "van-8")
        self.assertEqual(theirs["record"]["revision"], "3")

    def test_key_reuse_and_failed_requests(self):
        self.create("pump")
        conflict = self.error(self.store.mutate, req("k", "pump", "7", "visit", {"amount": 1}))
        self.assertEqual((conflict.status, conflict.code), (409, "conflict"))
        self.assertEqual(conflict.detail["current"]["revision"], "1")
        # Failed request did not consume the key.
        self.store.mutate(req("k", "pump", "1", "visit", {"amount": 1}))
        reuse = self.error(self.store.mutate, req("k", "pump", "1", "visit", {"amount": 2}))
        self.assertEqual((reuse.status, reuse.code), (409, "idempotency_reuse"))

    def test_kind_rules(self):
        self.create("w")
        self.assertEqual(self.error(self.store.mutate, req("x", "w", "0", "create", BODY)).code,
                         "conflict")
        self.store.mutate(req("d", "w", "1", "delete", {}))
        for kind, data in (("patch", {"done": True}), ("visit", {"amount": 1}),
                           ("delete", {})):
            self.assertEqual(self.error(self.store.mutate, req("e", "w", "2", kind, data)).code,
                             "conflict")
        tomb = self.store.snapshot("north", 10)["rows"][0]
        self.assertTrue(tomb["deleted"])
        self.assertEqual(tomb["body"]["title"], "Inspection")
        self.assertEqual(self.error(self.store.mutate,
                                    req("r", "w", "2", "create", BODY)).code, "conflict")
        restored = self.store.mutate(req("r", "w", "2", "restore", {"assignee": None}))
        self.assertFalse(restored["record"]["deleted"])
        self.assertEqual(self.error(self.store.mutate,
                                    req("r2", "w", "3", "restore", {})).code, "conflict")

    def test_invalid_inputs(self):
        self.create("w", visits=9007199254740990)
        bad = [
            req("a", "w", "1", "visit", {"amount": True}),
            req("a", "w", "1", "visit", {"amount": 0}),
            req("a", "w", "1", "visit", {"amount": 1.0}),
            req("a", "w", "1", "patch", {"colour": "red"}),
            req("a", "w", "1", "patch", {"title": ""}),
            req("a", "w", "1", "patch", {"visits": float("inf")}),
            req("a", "w", "01", "patch", {}),
            req("a", "w", 1, "patch", {}),
            req("", "w", "1", "patch", {}),
            req("a", "w", "1", "delete", {"x": 1}),
            req("a", "w", "1", "explode", {}),
            req("a", "w", "1", "patch", {"title": "\ud800"}),
            {**req("a", "w", "1", "patch", {}), "extra": 1},
            req("a", "w", "1", "visit", {"amount": 2}),  # total would exceed 2^53-1
        ]
        for request in bad:
            self.assertEqual(self.error(self.store.mutate, request).status, 400, request)
        self.assertEqual(len(dump(self.path)["events"]), 1)

    def test_unicode_and_null_assignee(self):
        entity, device = "работа-🛠️", "ван-७"
        self.store.mutate(req("ü-1", entity, "0", "create",
                              {**BODY, "title": "Prüfung 🔧", "assignee": "Zoë"}, "nörd", device))
        cleared = self.store.mutate(req("ü-2", entity, "1", "patch", {"assignee": None},
                                        "nörd", device))
        self.assertIsNone(cleared["record"]["body"]["assignee"])
        self.assertEqual(cleared["record"]["body"]["title"], "Prüfung 🔧")
        self.assertEqual(self.store.snapshot("nörd", 5)["rows"][0]["id"], entity)
        self.assertEqual(self.store.snapshot("north", 5)["rows"], [])

    def test_fault_injection_rolls_back_everything(self):
        self.create("pump")
        for point in ("after_document", "after_event"):
            before = dump(self.path)

            def hook(name, point=point):
                if name == point:
                    raise RuntimeError(f"chaos at {name}")

            with self.assertRaises(RuntimeError):
                Store(self.path, fault=hook).mutate(req("v", "pump", "1", "visit", {"amount": 1}))
            self.assertEqual(dump(self.path), before)
        # Key not consumed, entity unchanged.
        self.assertEqual(self.store.mutate(req("v", "pump", "1", "visit",
                                               {"amount": 1}))["record"]["revision"], "2")

    def test_concurrent_writers_single_winner(self):
        self.create("pump")
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=_race_worker, args=(
            str(self.path), req(f"race-{n}", "pump", "1", "visit", {"amount": 1},
                                device=f"van-{n}"), False, queue)) for n in range(6)]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=60) for _ in workers]
        for worker in workers:
            worker.join()
        self.assertEqual(sum(kind == "ok" for kind, _ in results), 1, results)
        self.assertEqual({value for kind, value in results if kind == "error"}, {"conflict"})
        self.assertEqual(self.store.snapshot("north", 5)["rows"][0]["body"]["visits"], 1)


class Reads(Base):
    def test_snapshot_pages_freeze_cut(self):
        for name in ("b", "d", "f"):
            self.create(name)
        self.store.mutate(req("del-d", "d", "1", "delete", {}))
        first = self.store.snapshot("north", 2)
        self.assertEqual([r["id"] for r in first["rows"]], ["b", "d"])
        self.assertTrue(first["rows"][1]["deleted"])
        # Concurrent writes after the cut must not leak into later pages.
        self.create("e")
        self.store.mutate(req("p-f", "f", "1", "patch", {"done": True}))
        self.store.mutate(req("del-b", "b", "1", "delete", {}))
        second = self.store.snapshot("north", 2, first["next_cursor"])
        self.assertEqual(second["cut"], first["cut"])
        self.assertEqual([r["id"] for r in second["rows"]], ["f"])
        self.assertEqual(second["rows"][0]["revision"], "1")
        self.assertIsNone(second["next_cursor"])

    def test_snapshot_uses_history_not_projection(self):
        self.create("a")
        sqlite3.connect(self.path).executescript(
            "UPDATE documents SET revision=99; INSERT INTO documents VALUES"
            " ('north','ghost',1,'{}',0);")
        rows = self.store.snapshot("north", 10)["rows"]
        self.assertEqual([(r["id"], r["revision"]) for r in rows], [("a", "1")])

    def test_empty_tenant_snapshot_completes(self):
        page = self.store.snapshot("nobody", 3)
        self.assertEqual((page["rows"], page["confirmed"], page["next_cursor"]), ([], [], None))

    def test_snapshot_confirmations(self):
        self.create("a", device="van-1")
        self.store.mutate(req("v-a", "a", "1", "visit", {"amount": 1}, device="van-2"))
        self.create("b")
        self.store.mutate(req("del-b", "b", "1", "delete", {}))
        self.create("a", tenant="south", mutation="south-a")
        first = self.store.snapshot("north", 1)
        self.store.mutate(req("late", "a", "2", "visit", {"amount": 1}))
        self.assertEqual([(c["device"], c["mutation"], c["id"]) for c in first["confirmed"]],
                         [("van-1", "c-north-a", "a"), ("van-2", "v-a", "a")])
        second = self.store.snapshot("north", 1, first["next_cursor"])
        self.assertEqual([c["mutation"] for c in second["confirmed"]], ["c-north-b", "del-b"])
        seqs = [int(c["seq"]) for c in second["confirmed"]]
        self.assertEqual(seqs, sorted(seqs))

    def test_cursor_validation(self):
        for name in "abc":
            self.create(name)
        page = self.store.snapshot("north", 1)
        cursor = page["next_cursor"]
        pull = self.store.pull("north", "0", 1)
        item = untoken(cursor)
        bad = ["", "!!!", "e30", token([1]), token({**item, "tenant": "south"}),
               token({**item, "epoch": "other"}), token({**item, "cut": "999"}),
               token({**item, "cut": 1}), token({**item, "last": ""}),
               token({**item, "extra": 1}), pull["next_cursor"]]
        for value in bad:
            self.assertEqual(self.error(self.store.snapshot, "north", 1, value).code,
                             "invalid_cursor", value)
        self.assertEqual(self.error(self.store.snapshot, "south", 1, cursor).code,
                         "invalid_cursor")
        self.assertEqual(self.error(self.store.pull, "north", "0", 1, cursor).code,
                         "invalid_cursor")
        # Resuming a pull requires the same original checkpoint.
        self.assertEqual(self.error(self.store.pull, "north", "1", 1,
                                    pull["next_cursor"]).code, "invalid_cursor")
        self.assertEqual(self.error(self.store.pull, "north", "4", 1).code, "invalid_cursor")
        self.assertEqual(self.error(self.store.pull, "north", "00", 1).code, "invalid_cursor")
        self.assertEqual(self.error(self.store.snapshot, "north", 0).code, "invalid")
        self.assertEqual(self.error(self.store.snapshot, "north", 101).code, "invalid")

    def test_pull_exclusive_frozen_until(self):
        self.create("a")                       # seq 1
        self.create("x", tenant="south")       # seq 2 (other tenant gap)
        self.create("b")                       # seq 3
        self.create("c")                       # seq 4
        first = self.store.pull("north", "1", 1)
        self.assertEqual((first["from"], first["after"], first["until"]), ("1", "3", "4"))
        self.assertEqual([e["seq"] for e in first["events"]], ["3"])
        self.create("d")                       # seq 5 after until is frozen
        second = self.store.pull("north", "1", 1, first["next_cursor"])
        self.assertEqual((second["from"], second["after"], second["until"]), ("3", "4", "4"))
        self.assertEqual([e["seq"] for e in second["events"]], ["4"])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual([c["mutation"] for c in second["confirmed"]], ["c-north-c"])
        tail = self.store.pull("north", "4", 10)
        self.assertEqual([e["id"] for e in tail["events"]], ["d"])
        empty = self.store.pull("south", "4", 10)
        self.assertEqual((empty["events"], empty["after"], empty["confirmed"]), ([], "5", []))

    def test_large_sequence_values(self):
        db = sqlite3.connect(self.path)
        db.execute("INSERT INTO events VALUES (9007199254740993,'north','big',1,?,0,'d','m')",
                   (json.dumps(BODY),))
        db.commit()
        db.close()
        response = self.create("next")
        self.assertEqual(response["record"]["seq"], "9007199254740994")
        page = self.store.pull("north", "9007199254740992", 1)
        self.assertEqual(page["events"][0]["seq"], "9007199254740993")
        self.assertEqual(page["after"], "9007199254740993")
        rest = self.store.pull("north", "9007199254740992", 1, page["next_cursor"])
        self.assertEqual(rest["from"], "9007199254740993")
        self.assertEqual(rest["after"], "9007199254740994")


class Batches(Base):
    def batch(self, name, operations, device="van-7"):
        return {"tenant": "north", "device": device, "batch": name, "operations": operations}

    def op(self, mutation, entity, base, kind, data):
        return {"mutation": mutation, "id": entity, "base": base, "kind": kind, "data": data}

    def test_closeout_success_and_retry(self):
        self.create("pump")
        request = self.batch("close-1", [self.op("v", "pump", "1", "visit", {"amount": 1}),
                                         self.op("d", "pump", "2", "patch", {"done": True})])
        response = self.store.mutate_batch(request)
        self.assertEqual([r["record"]["revision"] for r in response["responses"]], ["2", "3"])
        self.assertEqual(self.store.mutate_batch(request), response)
        self.assertEqual(self.store.mutate(req("v", "pump", "1", "visit", {"amount": 1})),
                         response["responses"][0])
        other = self.batch("close-1", [self.op("v", "pump", "1", "visit", {"amount": 2})])
        self.assertEqual(self.error(self.store.mutate_batch, other).code, "idempotency_reuse")

    def test_failed_closeout_is_atomic(self):
        self.create("pump")
        self.create("valve")
        self.store.mutate(req("v-old", "valve", "1", "patch", {"assignee": "Ann"}))
        before = dump(self.path)
        request = self.batch("close-2", [self.op("pv", "pump", "1", "visit", {"amount": 1}),
                                         self.op("vd", "valve", "1", "patch", {"done": True})])
        exc = self.error(self.store.mutate_batch, request)
        self.assertEqual((exc.code, exc.detail["index"]), ("conflict", 1))
        self.assertEqual(exc.detail["current"]["revision"], "2")
        self.assertEqual(dump(self.path), before)
        fixed = self.batch("close-2", [self.op("pv", "pump", "1", "visit", {"amount": 1}),
                                       self.op("vd", "valve", "2", "patch", {"done": True})])
        self.assertTrue(self.store.mutate_batch(fixed)["ok"])

    def test_batch_conflict_for_independent_key(self):
        self.create("pump")
        single = self.store.mutate(req("v", "pump", "1", "visit", {"amount": 1}))
        request = self.batch("b", [self.op("p", "pump", "2", "patch", {"done": True}),
                                   self.op("v", "pump", "1", "visit", {"amount": 1})])
        exc = self.error(self.store.mutate_batch, request)
        self.assertEqual((exc.status, exc.code, exc.detail["index"]), (409, "batch_conflict", 1))
        self.assertEqual(self.store.snapshot("north", 5)["rows"][0]["revision"],
                         single["record"]["revision"])

    def test_batch_invalid_envelopes(self):
        good = self.op("a", "w", "0", "create", BODY)
        for request in (
            [], self.batch("b", []), self.batch("b", good),
            self.batch("b", [good] * 2), self.batch("b", [{**good, "tenant": "north"}]),
            {**self.batch("b", [good]), "extra": 1}, self.batch("", [good]),
            self.batch("b", [self.op(f"m{n}", f"w{n}", "0", "create", BODY) for n in range(17)]),
        ):
            self.assertEqual(self.error(self.store.mutate_batch, request).code, "invalid")
        self.assertEqual(dump(self.path)["events"], [])

    def test_batch_fault_rolls_back_earlier_operations(self):
        self.create("pump")
        before = dump(self.path)
        calls = []

        def hook(name):
            calls.append(name)
            if len(calls) == 3:
                raise RuntimeError("storage failure")

        request = self.batch("b", [self.op("1", "pump", "1", "visit", {"amount": 1}),
                                   self.op("2", "pump", "2", "visit", {"amount": 1})])
        with self.assertRaises(RuntimeError):
            Store(self.path, fault=hook).mutate_batch(request)
        self.assertEqual(dump(self.path), before)

    def test_racing_batches_share_one_commit(self):
        self.create("pump")
        request = self.batch("race", [self.op("rv", "pump", "1", "visit", {"amount": 1}),
                                      self.op("rd", "pump", "2", "patch", {"done": True})])
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=_race_worker, args=(str(self.path), request, True, queue))
                   for _ in range(5)]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=60) for _ in workers]
        for worker in workers:
            worker.join()
        self.assertEqual({kind for kind, _ in results}, {"ok"})
        self.assertEqual(len({value for _, value in results}), 1)
        self.assertEqual(len(dump(self.path)["events"]), 3)


class Repair(unittest.TestCase):
    def test_seed_repair_is_transactional_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seed.sqlite"
            subprocess.run([sys.executable, str(ROOT / "tools/seed.py"), "--db", str(path)],
                           check=True, capture_output=True)
            before = dump(path)
            out = subprocess.run([sys.executable, str(ROOT / "tools/repair.py"), "--db", str(path)],
                                 check=True, capture_output=True, text=True).stdout
            self.assertEqual(json.loads(out), {"repaired": 4})
            after = dump(path)
            for table in ("metadata", "events", "receipts", "batches"):
                self.assertEqual(after[table], before[table], table)
            self.assertEqual([row[:3] + (row[4],) for row in after["documents"]], [
                ("north", "pump-17", 43, 0), ("north", "valve-4", 2, 1),
                ("south", "pump-17", 6, 0)])
            self.assertEqual(Store(path).repair_projection(), {"repaired": 0})
            # A fresh snapshot after repair still reads history.
            rows = Store(path).snapshot("north", 10)["rows"]
            self.assertEqual([(r["id"], r["revision"], r["seq"]) for r in rows],
                             [("pump-17", "43", "9007199254740996"),
                              ("valve-4", "2", "9007199254740997")])

    def test_repair_cli_rejects_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite"
            result = subprocess.run([sys.executable, str(ROOT / "tools/repair.py"), "--db",
                                     str(path)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(path.exists())

    def test_working_state_database_is_consistent(self):
        path = ROOT / "state/site.sqlite"
        if not path.exists():
            self.skipTest("no working state database")
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            expected = sorted(db.execute(
                "SELECT e.tenant,e.id,e.revision,e.body,e.deleted FROM events e JOIN"
                " (SELECT MAX(seq) s FROM events GROUP BY tenant,id) h ON e.seq=h.s").fetchall())
            actual = sorted(db.execute("SELECT * FROM documents").fetchall())
            epoch = db.execute("SELECT epoch FROM metadata").fetchall()
        finally:
            db.close()
        self.assertEqual(actual, expected)
        self.assertEqual(epoch, [("dispatch-2026-04",)])


class Http(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name) / "http.sqlite"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "server.http", "--db", str(self.db), "--port", str(self.port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                self.call("GET", "/health")
                break
            except OSError:
                time.sleep(0.05)

    def tearDown(self):
        self.process.terminate()
        self.process.wait()
        self.process.stderr.close()
        self.directory.cleanup()

    def call(self, method, path, payload=None, raw=None):
        data = raw if raw is not None else (
            json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None)
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_http_surface(self):
        self.assertEqual(self.call("GET", "/health"), (200, {"ok": True}))
        status, body = self.call("POST", "/mutate", req("é", "naïve", "0", "create",
                                                        {**BODY, "title": "日本"}))
        self.assertEqual((status, body["record"]["body"]["title"]), (200, "日本"))
        status, body = self.call("POST", "/mutate", req("x", "naïve", "5", "visit", {"amount": 1}))
        self.assertEqual((status, body["code"], body["detail"]["current"]["revision"]),
                         (409, "conflict", "1"))
        self.assertEqual(self.call("POST", "/mutate", raw=b"{nope")[0], 400)
        self.assertEqual(self.call("POST", "/mutate", raw=b'{"amount": NaN}')[0], 400)
        status, body = self.call("POST", "/batch", {
            "tenant": "north", "device": "van-7", "batch": "b",
            "operations": [{"mutation": "v", "id": "naïve", "base": "1", "kind": "visit",
                            "data": {"amount": 1}}]})
        self.assertEqual((status, body["responses"][0]["record"]["revision"]), (200, "2"))
        status, page = self.call("GET", "/snapshot?tenant=north&limit=10")
        self.assertEqual((status, page["rows"][0]["id"], len(page["confirmed"])), (200, "naïve", 2))
        status, page = self.call("GET", "/pull?tenant=north&checkpoint=0&limit=1")
        self.assertEqual((status, page["after"], page["until"]), (200, "1", "2"))
        status, page = self.call("GET", "/pull?tenant=north&checkpoint=0&limit=1&cursor="
                                 + page["next_cursor"])
        self.assertEqual((status, [e["seq"] for e in page["events"]]), (200, ["2"]))
        self.assertEqual(self.call("GET", "/pull?tenant=north&checkpoint=9&limit=1")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("GET", "/snapshot?tenant=north&limit=10&cursor=")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("GET", "/snapshot?tenant=north&limit=x")[0], 400)
        self.assertEqual(self.call("GET", "/nowhere")[0], 404)

    def test_unexpected_failure_is_500(self):
        db = sqlite3.connect(self.db)
        db.execute("DROP TABLE events")
        db.commit()
        db.close()
        status, body = self.call("GET", "/pull?tenant=north&checkpoint=0&limit=1")
        self.assertEqual((status, body), (500, {"ok": False, "code": "internal"}))


if __name__ == "__main__":
    unittest.main()
