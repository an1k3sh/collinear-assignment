import base64
import json
import multiprocessing
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.codec import SyncError, canonical  # noqa: E402
from server.store import Store  # noqa: E402

BODY = {"title": "Inspection", "assignee": None, "visits": 0, "done": False}
BIG = 9007199254740993  # 2^53 + 1


def req(mutation, entity, base, kind, data, tenant="north", device="van-7"):
    return {"tenant": tenant, "device": device, "mutation": mutation, "id": entity,
            "base": base, "kind": kind, "data": data}


def ascii_token(value):
    """Encode a token with JSON escapes, e.g. to smuggle a lone surrogate."""
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def history(path):
    with sqlite3.connect(path) as db:
        return {table: sorted(db.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
                for table in ("metadata", "events", "receipts", "batches")}


def _race_mutate(path, request, queue):
    try:
        queue.put(("ok", Store(path).mutate(request)))
    except SyncError as exc:
        queue.put((exc.code, None))


def _race_batch(path, request, queue):
    try:
        queue.put(("ok", Store(path).mutate_batch(request)))
    except SyncError as exc:
        queue.put((exc.code, None))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "work.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def assertSync(self, status, code, fn, *args):
        with self.assertRaises(SyncError) as ctx:
            fn(*args)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (status, code))
        return ctx.exception

    def create(self, entity="order", mutation=None, **kw):
        return self.store.mutate(req(mutation or f"c-{entity}", entity, "0", "create",
                                     dict(BODY), **kw))


class Smoke(Base):
    def test_create_and_read(self):
        response = self.create()
        self.assertTrue(response["ok"])
        self.assertEqual(self.store.snapshot("north", 10)["rows"][0]["body"]["title"], "Inspection")
        self.assertEqual(response["record"]["revision"], "1")
        self.assertIsInstance(response["record"]["seq"], str)


class Mutations(Base):
    def test_retry_returns_original_receipt_after_newer_writes(self):
        self.create()
        visit = req("m-9", "order", "1", "visit", {"amount": 1})
        first = self.store.mutate(visit)
        self.store.mutate(req("m-10", "order", "2", "patch", {"assignee": "Mira"}))
        retry = self.store.mutate(dict(reversed(list(visit.items()))))
        self.assertEqual(first, retry)
        self.assertEqual(self.store.snapshot("north", 5)["rows"][0]["body"]["visits"], 1)

    def test_same_mutation_id_on_other_device_is_independent(self):
        self.create()
        a = self.store.mutate(req("m-9", "order", "1", "visit", {"amount": 1}))
        b = self.store.mutate(req("m-9", "order", "2", "patch", {"assignee": "Lee"},
                                  device="van-8"))
        self.assertEqual((a["device"], b["device"]), ("van-7", "van-8"))
        self.assertEqual(b["record"]["revision"], "3")

    def test_key_reuse_and_failed_requests(self):
        self.create()
        self.store.mutate(req("k", "order", "1", "visit", {"amount": 1}))
        self.assertSync(409, "idempotency_reuse", self.store.mutate,
                        req("k", "order", "1", "visit", {"amount": 2}))
        err = self.assertSync(409, "conflict", self.store.mutate,
                              req("x", "order", "1", "patch", {"done": True}))
        self.assertEqual(err.detail["current"]["revision"], "2")
        # Failed request did not consume the key.
        self.assertEqual(self.store.mutate(req("x", "order", "2", "patch", {"done": True}))
                         ["record"]["revision"], "3")

    def test_validation(self):
        self.create()
        bad = [
            req("v", "order", "1", "visit", {"amount": True}),
            req("v", "order", "1", "visit", {"amount": 0}),
            req("v", "order", "1", "visit", {"amount": 1.0}),
            req("v", "order", "1", "patch", {"colour": "red"}),
            req("v", "order", "1", "patch", {"visits": False}),
            req("v", "order", "1", "patch", {"title": ""}),
            req("v", "order", "01", "patch", {"done": True}),
            req("v", "order", 1, "patch", {"done": True}),
            req("v", "order", "1", "delete", {"x": 1}),
            req("v", "order", "1", "explode", {}),
            req("", "order", "1", "delete", {}),
            req("v", "order\ud800", "1", "delete", {}),
            {**req("v", "order", "1", "delete", {}), "extra": 1},
        ]
        for request in bad:
            self.assertSync(400, "invalid", self.store.mutate, request)
        self.store.mutate(req("big", "order", "1", "patch", {"visits": 9007199254740990}))
        self.assertSync(400, "invalid", self.store.mutate,
                        req("over", "order", "2", "visit", {"amount": 2}))

    def test_state_transitions(self):
        self.create()
        self.assertSync(409, "conflict", self.store.mutate,
                        req("r", "order", "1", "restore", {}))
        self.store.mutate(req("d", "order", "1", "delete", {}))
        snap = self.store.snapshot("north", 5)["rows"][0]
        self.assertTrue(snap["deleted"])
        self.assertEqual(snap["body"]["title"], "Inspection")
        for kind, data in (("patch", {"done": True}), ("visit", {"amount": 1}),
                           ("delete", {})):
            self.assertSync(409, "conflict", self.store.mutate,
                            req("e", "order", "2", kind, data))
        err = self.assertSync(409, "conflict", self.store.mutate,
                              req("c2", "order", "0", "create", dict(BODY)))
        self.assertTrue(err.detail["current"]["deleted"])
        restored = self.store.mutate(req("r", "order", "2", "restore", {"assignee": None}))
        self.assertFalse(restored["record"]["deleted"])
        err = self.assertSync(409, "conflict", self.store.mutate,
                              req("p", "missing", "0", "patch", {"done": True}))
        self.assertIsNone(err.detail["current"])

    def test_fault_injection_rolls_back_everything(self):
        for point in ("after_document", "after_event"):
            def hook(name, point=point):
                if name == point:
                    raise RuntimeError("chaos")
            faulty = Store(self.path, fault=hook)
            before = history(self.path)
            with self.assertRaises(RuntimeError):
                faulty.mutate(req("f", "ghost", "0", "create", dict(BODY)))
            self.assertEqual(history(self.path), before)
            with sqlite3.connect(self.path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(self.store.mutate(req("f", "ghost", "0", "create", dict(BODY)))
                         ["record"]["revision"], "1")

    def test_unicode_and_large_sequences(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO sqlite_sequence VALUES ('events', ?)", (BIG,))
        entity = "z\u00e9-\U0001f527-\u6c34"
        r = self.store.mutate(req("\u00fc-1", entity, "0", "create",
                                  {**BODY, "title": "B\u00f6hm \U0001f6e0"},
                                  tenant="n\u00f8rd", device="v\u00e4n"))
        self.assertEqual(r["record"]["seq"], str(BIG + 1))
        snap = self.store.snapshot("n\u00f8rd", 5)
        self.assertEqual(snap["rows"][0]["id"], entity)
        self.assertEqual(snap["cut"], str(BIG + 1))
        self.assertEqual(snap["confirmed"], [{"device": "v\u00e4n", "mutation": "\u00fc-1",
                                              "id": entity, "seq": str(BIG + 1)}])

    def test_concurrent_processes_single_winner(self):
        self.create()
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        procs = [ctx.Process(target=_race_mutate, args=(
            str(self.path), req(f"race-{i}", "order", "1", "visit", {"amount": 1},
                                device=f"d{i}"), queue)) for i in range(6)]
        for p in procs:
            p.start()
        results = [queue.get(timeout=60)[0] for _ in procs]
        for p in procs:
            p.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("conflict"), 5)


class Pages(Base):
    def test_snapshot_cut_is_frozen_across_pages(self):
        for name in ("b", "d", "f"):
            self.create(name)
        first = self.store.snapshot("north", 1)
        self.assertEqual([r["id"] for r in first["rows"]], ["b"])
        # Concurrent edits after the cut: delete d, add c (before the next page).
        self.store.mutate(req("del-d", "d", "1", "delete", {}))
        self.create("c")
        self.create("a", tenant="south")
        rows, cursor = list(first["rows"]), first["next_cursor"]
        while cursor:
            page = self.store.snapshot("north", 1, cursor)
            self.assertEqual(page["cut"], first["cut"])
            rows += page["rows"]
            cursor = page["next_cursor"]
        self.assertEqual([r["id"] for r in rows], ["b", "d", "f"])
        self.assertTrue(all(not r["deleted"] for r in rows))

    def test_snapshot_includes_tombstones_and_history_confirmations(self):
        self.create("x")
        self.store.mutate(req("v1", "x", "1", "visit", {"amount": 1}))
        self.store.mutate(req("del", "x", "2", "delete", {}))
        self.create("y")
        page = self.store.snapshot("north", 1)
        self.assertTrue(page["rows"][0]["deleted"])
        self.assertEqual([c["mutation"] for c in page["confirmed"]], ["c-x", "v1", "del"])
        empty = self.store.snapshot("nobody", 10)
        self.assertEqual((empty["rows"], empty["confirmed"], empty["next_cursor"]), ([], [], None))

    def test_projection_drift_does_not_leak_into_snapshot(self):
        self.create("x")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO documents VALUES ('north','phantom',1,?,0)",
                       (canonical(BODY),))
            db.execute("UPDATE documents SET deleted=1 WHERE id='x'")
        rows = self.store.snapshot("north", 10)["rows"]
        self.assertEqual([(r["id"], r["deleted"]) for r in rows], [("x", False)])

    def test_pull_pages_are_contiguous_with_frozen_until(self):
        for i in range(5):
            self.create(f"n{i}")
            self.create(f"s{i}", tenant="south")
        first = self.store.pull("north", "0", 2)
        self.assertEqual(first["from"], "0")
        self.assertEqual(len(first["events"]), 2)
        self.assertEqual(first["after"], first["events"][-1]["seq"])
        until = first["until"]
        self.create("late")
        seen, page = list(first["events"]), first
        while page["next_cursor"]:
            nxt = self.store.pull("north", "0", 2, page["next_cursor"])
            self.assertEqual(nxt["from"], page["after"])
            self.assertEqual(nxt["until"], until)
            seen += nxt["events"]
            page = nxt
        self.assertEqual(page["after"], until)
        self.assertEqual([e["id"] for e in seen], [f"n{i}" for i in range(5)])
        self.assertEqual(len({e["seq"] for e in seen}), 5)
        self.assertEqual([c["seq"] for c in page["confirmed"]], [e["seq"] for e in page["events"]])
        tail = self.store.pull("north", until, 10)
        self.assertEqual([e["id"] for e in tail["events"]], ["late"])

    def test_cursor_and_checkpoint_validation(self):
        self.create("a")
        self.create("b")
        snap = self.store.snapshot("north", 1)
        pull = self.store.pull("north", "0", 1)
        bad = [
            (self.store.snapshot, ("south", 1, snap["next_cursor"])),
            (self.store.snapshot, ("north", 1, pull["next_cursor"])),
            (self.store.snapshot, ("north", 1, "not*base64")),
            (self.store.snapshot, ("north", 1, "e30")),
            (self.store.pull, ("north", "0", 1, snap["next_cursor"])),
            (self.store.pull, ("north", "1", 1, pull["next_cursor"])),
            (self.store.pull, ("north", "999", 1)),
            (self.store.pull, ("north", "00", 1)),
            (self.store.snapshot, ("north", 1, ascii_token({
                "mode": "snapshot", "tenant": "north", "epoch": snap["epoch"],
                "cut": snap["cut"], "last": "\ud800"}))),
        ]
        for fn, args in bad:
            self.assertSync(400, "invalid_cursor", fn, *args)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE metadata SET epoch='other'")
        self.assertSync(400, "invalid_cursor", self.store.snapshot, "north", 1, snap["next_cursor"])
        for limit in (0, 101, True, "5"):
            self.assertSync(400, "invalid", self.store.snapshot, "north", limit)


class Batches(Base):
    def closeout(self, batch="closeout-3", done_base="2", **kw):
        return {"tenant": "north", "device": "van-7", "batch": batch, "operations": [
            {"mutation": "visit-3", "id": "pump", "base": "1", "kind": "visit",
             "data": {"amount": 1}},
            {"mutation": "done-3", "id": "pump", "base": done_base, "kind": "patch",
             "data": {"done": True}},
            {"mutation": "valve-3", "id": "valve", "base": "1", "kind": "patch",
             "data": {"done": True}}], **kw}

    def setUp(self):
        super().setUp()
        self.create("pump")
        self.create("valve")

    def test_atomic_success_and_exact_retry(self):
        response = self.store.mutate_batch(self.closeout())
        self.assertEqual([r["record"]["revision"] for r in response["responses"]], ["2", "3", "2"])
        self.assertEqual(self.store.mutate_batch(self.closeout()), response)
        # Ordinary namespace shares the operation receipts.
        single = req("done-3", "pump", "2", "patch", {"done": True})
        self.assertEqual(self.store.mutate(single), response["responses"][1])
        changed = self.closeout()
        changed["operations"] = changed["operations"][:1]
        self.assertSync(409, "idempotency_reuse", self.store.mutate_batch, changed)

    def test_failure_rolls_back_all_operations(self):
        self.store.mutate(req("bump", "valve", "1", "patch", {"assignee": "X"}))
        before = history(self.path)
        err = self.assertSync(409, "conflict", self.store.mutate_batch, self.closeout())
        self.assertEqual(err.detail["index"], 2)
        self.assertEqual(err.detail["current"]["revision"], "2")
        self.assertEqual(history(self.path), before)
        # Neither batch nor operation IDs were consumed.
        fixed = self.closeout()
        fixed["operations"][2]["base"] = "2"
        self.assertTrue(self.store.mutate_batch(fixed)["ok"])

    def test_fault_in_later_operation_rolls_back_earlier(self):
        calls = []

        def hook(name):
            calls.append(name)
            if len(calls) == 5:
                raise RuntimeError("chaos")
        before = history(self.path)
        with self.assertRaises(RuntimeError):
            Store(self.path, fault=hook).mutate_batch(self.closeout())
        self.assertEqual(history(self.path), before)

    def test_operation_committed_elsewhere_is_batch_conflict(self):
        self.store.mutate(req("visit-3", "pump", "1", "visit", {"amount": 1}))
        err = self.assertSync(409, "batch_conflict", self.store.mutate_batch, self.closeout())
        self.assertEqual(err.detail["index"], 0)

    def test_invalid_envelopes(self):
        dup = self.closeout()
        dup["operations"][1]["mutation"] = "visit-3"
        bad = [dup, {**self.closeout(), "extra": 1}, {**self.closeout(), "operations": {}},
               {**self.closeout(), "operations": []},
               {**self.closeout(), "operations": self.closeout()["operations"] * 6},
               {**self.closeout(), "batch": ""}]
        nested = self.closeout()
        nested["operations"][0]["tenant"] = "north"
        bad.append(nested)
        for request in bad:
            self.assertSync(400, "invalid", self.store.mutate_batch, request)

    def test_concurrent_identical_batches(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        procs = [ctx.Process(target=_race_batch, args=(str(self.path), self.closeout(), queue))
                 for _ in range(4)]
        for p in procs:
            p.start()
        results = [queue.get(timeout=60) for _ in procs]
        for p in procs:
            p.join()
        self.assertTrue(all(code == "ok" for code, _ in results))
        self.assertTrue(all(r == results[0][1] for _, r in results))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 5)

    def test_pull_boundary_inside_closeout(self):
        self.store.mutate_batch(self.closeout())
        checkpoint = self.store.pull("north", "0", 100)["after"]
        page = self.store.pull("north", "0", 3)
        self.assertEqual([c["mutation"] for c in page["confirmed"]],
                         ["c-pump", "c-valve", "visit-3"])
        self.assertNotEqual(page["after"], checkpoint)


class Repair(Base):
    def test_repair_restores_projection_without_touching_history(self):
        self.create("a")
        self.create("b")
        self.store.mutate(req("d", "b", "1", "delete", {}))
        self.create("c", tenant="south")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE documents SET revision=7 WHERE id='a'")
            db.execute("UPDATE documents SET deleted=0 WHERE id='b'")
            db.execute("DELETE FROM documents WHERE tenant='south'")
            db.execute("INSERT INTO documents VALUES ('north','phantom',1,?,0)", (canonical(BODY),))
        before = history(self.path)
        self.assertEqual(self.store.repair_projection(), {"repaired": 4})
        self.assertEqual(self.store.repair_projection(), {"repaired": 0})
        self.assertEqual(history(self.path), before)
        with sqlite3.connect(self.path) as db:
            docs = db.execute("SELECT tenant,id,revision,deleted FROM documents ORDER BY 1,2").fetchall()
        self.assertEqual(docs, [("north", "a", 1, 0), ("north", "b", 2, 1), ("south", "c", 1, 0)])

    def test_repair_command_on_incident_seed(self):
        seeded = Path(self.tmp.name) / "seed.sqlite"
        subprocess.run([sys.executable, str(ROOT / "tools/seed.py"), "--db", str(seeded)],
                       check=True, capture_output=True)
        before = history(seeded)
        out = subprocess.run([sys.executable, str(ROOT / "tools/repair.py"), "--db", str(seeded)],
                             check=True, capture_output=True, text=True).stdout
        self.assertEqual(json.loads(out), {"repaired": 4})
        self.assertEqual(history(seeded), before)
        missing = subprocess.run([sys.executable, str(ROOT / "tools/repair.py"), "--db",
                                  str(Path(self.tmp.name) / "absent.sqlite")], capture_output=True)
        self.assertNotEqual(missing.returncode, 0)

    def test_working_state_is_repaired(self):
        copy = Path(self.tmp.name) / "site.sqlite"
        shutil.copy(ROOT / "state/site.sqlite", copy)
        self.assertEqual(Store(copy).repair_projection(), {"repaired": 0})
        with sqlite3.connect(copy) as db:
            self.assertEqual(db.execute("SELECT epoch FROM metadata").fetchall(),
                             [("dispatch-2026-04",)])


class Http(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen([sys.executable, "-m", "server.http", "--db", str(self.path),
                                      "--port", str(self.port)], cwd=ROOT,
                                     stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                self.call("GET", "/health")
                break
            except OSError:
                time.sleep(0.05)

    def tearDown(self):
        self.proc.terminate()
        self.proc.communicate(timeout=10)
        super().tearDown()

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

    def test_http_round_trip(self):
        self.assertEqual(self.call("GET", "/health"), (200, {"ok": True}))
        status, body = self.call("POST", "/mutate", req("h", "\u00e9t\u00e9", "0", "create", BODY))
        self.assertEqual(status, 200)
        self.assertEqual(body["record"]["id"], "\u00e9t\u00e9")
        status, body = self.call("POST", "/mutate", req("h2", "x", "1", "patch", {"done": True}))
        self.assertEqual((status, body["code"], body["detail"]), (409, "conflict", {"current": None}))
        self.assertEqual(self.call("POST", "/mutate", raw=b'{"a": NaN}')[0], 400)
        self.assertEqual(self.call("POST", "/mutate", raw=b'not json')[0], 400)
        tenant = urllib.parse.quote("north")
        status, snap = self.call("GET", f"/snapshot?tenant={tenant}&limit=10")
        self.assertEqual((status, len(snap["rows"])), (200, 1))
        status, pull = self.call("GET", f"/pull?tenant=north&limit=10&checkpoint=0")
        self.assertEqual((status, pull["after"]), (200, snap["cut"]))
        self.assertEqual(self.call("GET", "/pull?tenant=north&limit=10&checkpoint=99")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("GET", "/snapshot?tenant=north&limit=x")[0], 400)
        self.assertEqual(self.call("GET", "/snapshot?tenant=north&limit=5&cursor=")[1]["code"],
                         "invalid_cursor")
        status, batch = self.call("POST", "/batch", {
            "tenant": "north", "device": "van-7", "batch": "b1", "operations": [
                {"mutation": "b1-1", "id": "\u00e9t\u00e9", "base": "1", "kind": "visit",
                 "data": {"amount": 2}}]})
        self.assertEqual((status, batch["responses"][0]["record"]["body"]["visits"]), (200, 2))
        self.assertEqual(self.call("GET", "/nowhere")[0], 404)


if __name__ == "__main__":
    unittest.main()
