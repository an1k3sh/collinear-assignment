import copy
import hashlib
import importlib
import json
import multiprocessing
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

APP = Path(os.environ.get("APP_ROOT", "/app"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from server.store import Store
from server.codec import SyncError


def request(entity="work", mutation="m1", device="van-7", tenant="north",
            kind="create", base="0", data=None):
    return {"tenant": tenant, "device": device, "mutation": mutation, "id": entity,
            "kind": kind, "base": base,
            "data": data if data is not None else {
                "title": "Check pump", "assignee": None, "visits": 0, "done": False}}


def race_worker(path, barrier, queue, index):
    store = Store(path)
    barrier.wait(timeout=20)
    try:
        value = store.mutate(request(kind="visit", base="1", mutation=f"race-{index}",
                                     data={"amount": 1}))
        queue.put(("ok", value["record"]))
    except SyncError as exc:
        queue.put((exc.code, exc.status))
    except Exception as exc:
        queue.put(("unexpected", repr(exc)))


def bundle(*operations, name="closeout", device="van-7", tenant="north"):
    return {"tenant": tenant, "device": device, "batch": name,
            "operations": [{k: v for k, v in op.items() if k not in ("tenant", "device")}
                           for op in operations]}


def batch_worker(path, barrier, queue, value):
    store = Store(path)
    barrier.wait(timeout=20)
    try:
        queue.put(("ok", store.mutate_batch(value)))
    except Exception as exc:
        queue.put(("error", repr(exc)))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "store.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with sqlite3.connect(self.path) as db:
            return db.execute(statement, params).fetchall()

    def immutable(self, path=None):
        with sqlite3.connect(path or self.path) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in ("events", "receipts", "metadata", "batches")}

    def expect_error(self, code, callback):
        with self.assertRaises(SyncError) as context:
            callback()
        self.assertEqual(context.exception.code, code)
        return context.exception

    def js(self, case, *args):
        completed = subprocess.run(
            ["node", str(HERE / "client_checks.mjs"), case, str(APP), *args],
            text=True, capture_output=True, timeout=90)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_transactions_receipt_identity_and_digest(self):
        first = request()
        receipt = self.store.mutate(first)
        self.store.mutate(request(kind="visit", base="1", mutation="visit", data={"amount": 3}))
        reordered = dict(reversed(list(first.items())))
        reordered["data"] = dict(reversed(list(first["data"].items())))
        self.assertEqual(Store(self.path).mutate(reordered), receipt)
        self.expect_error("idempotency_reuse", lambda: self.store.mutate(
            {**first, "data": {**first["data"], "title": "Different"}}))
        other = self.store.mutate(request(entity="other", device="van-8"))
        self.assertEqual(other["device"], "van-8")
        self.assertEqual(other["record"]["id"], "other")
        tenant = self.store.mutate(request(tenant="south"))
        self.assertEqual(tenant["tenant"], "south")
        self.assertEqual(len(self.sql("SELECT * FROM events")), 4)

    def test_transactions_rollback_both_fault_boundaries(self):
        self.store.mutate(request())
        before = self.immutable()
        documents = self.sql("SELECT * FROM documents")
        for phase in ("after_document", "after_event"):
            def fault(current):
                if current == phase:
                    raise RuntimeError("injected storage failure")
            broken = Store(self.path, fault=fault)
            with self.assertRaisesRegex(RuntimeError, "injected storage failure"):
                broken.mutate(request(kind="visit", base="1", mutation="fault", data={"amount": 1}))
            self.assertEqual(self.immutable(), before)
            self.assertEqual(self.sql("SELECT * FROM documents"), documents)
        result = Store(self.path).mutate(
            request(kind="visit", base="1", mutation="fault", data={"amount": 1}))
        self.assertEqual(result["record"]["body"]["visits"], 1)
        self.assertEqual(len(self.sql("SELECT * FROM events")), 2)

    def test_transactions_process_race(self):
        self.store.mutate(request())
        context = multiprocessing.get_context("fork")
        barrier, queue = context.Barrier(6), context.Queue()
        processes = [context.Process(target=race_worker, args=(str(self.path), barrier, queue, i))
                     for i in range(6)]
        try:
            for process in processes:
                process.start()
            results = [queue.get(timeout=40) for _ in processes]
            for process in processes:
                process.join(5)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual([kind for kind, _ in results].count("ok"), 1, results)
            self.assertEqual([kind for kind, _ in results].count("conflict"), 5, results)
            self.assertEqual(len(self.sql("SELECT * FROM events")), 2)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
            queue.close()

    def test_transactions_conflicts_do_not_consume_keys(self):
        current = self.store.mutate(request())["record"]
        failed = request(kind="patch", base="0", mutation="retry", data={"assignee": "A"})
        error = self.expect_error("conflict", lambda: self.store.mutate(failed))
        self.assertEqual(error.status, 409)
        self.assertEqual(error.detail["current"], current)
        result = self.store.mutate({**failed, "base": "1"})
        self.assertEqual(result["record"]["body"]["assignee"], "A")
        self.assertEqual(result["record"]["revision"], "2")

    def test_transactions_validation_and_lifecycle(self):
        self.store.mutate(request())
        for data in ({"visits": True}, {"visits": -1}, {"done": 1},
                     {"title": ""}, {"unknown": 1}, {"visits": 1.5}):
            before = self.immutable()
            self.expect_error("invalid", lambda: self.store.mutate(
                request(kind="patch", base="1", mutation="bad", data=data)))
            self.assertEqual(before, self.immutable())
        self.expect_error("invalid", lambda: self.store.mutate(
            request(kind="visit", base="1", mutation="bad", data={"amount": True})))
        assigned = self.store.mutate(request(kind="patch", base="1", mutation="set",
                                            data={"assignee": "A"}))
        cleared = self.store.mutate(request(kind="patch", base="2", mutation="clear",
                                           data={"assignee": None}))
        self.assertIsNone(cleared["record"]["body"]["assignee"])
        self.assertEqual(assigned["record"]["body"]["title"], "Check pump")
        deleted = self.store.mutate(request(kind="delete", base="3", mutation="del", data={}))
        self.assertTrue(deleted["record"]["deleted"])
        self.expect_error("conflict", lambda: self.store.mutate(
            request(kind="patch", base="4", mutation="bad", data={"title": "Revive"})))
        restored = self.store.mutate(request(kind="restore", base="4", mutation="restore",
                                             data={"title": "Restored"}))
        self.assertFalse(restored["record"]["deleted"])
        self.assertEqual(restored["record"]["revision"], "5")

    def test_sync_snapshot_frozen_history(self):
        originals = [self.store.mutate(request(entity=e, mutation=e))["record"]
                     for e in ("b", "d", "f", "h")]
        first = self.store.snapshot("north", 1)
        self.store.mutate(request(entity="d", mutation="d2", kind="patch", base="1",
                                  data={"title": "Changed after cut"}))
        self.store.mutate(request(entity="f", mutation="f2", kind="delete", base="1", data={}))
        self.store.mutate(request(entity="a", mutation="a"))
        self.store.mutate(request(entity="z", mutation="z"))
        rows, page = list(first["rows"]), first
        for _ in range(10):
            if page["next_cursor"] is None:
                break
            page = self.store.snapshot("north", 1, page["next_cursor"])
            self.assertEqual(page["cut"], first["cut"])
            rows.extend(page["rows"])
        self.assertIsNone(page["next_cursor"], "snapshot did not terminate")
        self.assertEqual(rows, originals)

    def test_sync_pull_exclusive_frozen_and_gaps(self):
        for i in range(6):
            self.store.mutate(request(entity=str(i), mutation=str(i),
                                      tenant="north" if i % 2 else "south"))
        first = self.store.pull("north", "0", 1)
        self.store.mutate(request(entity="later", mutation="later"))
        pages, page = [first], first
        for _ in range(10):
            if page["next_cursor"] is None:
                break
            page = self.store.pull("north", "0", 1, page["next_cursor"])
            self.assertEqual(page["until"], first["until"])
            self.assertEqual(page["from"], pages[-1]["after"])
            pages.append(page)
        self.assertIsNone(page["next_cursor"], "pull did not terminate")
        self.assertEqual([r["id"] for p in pages for r in p["events"]], ["1", "3", "5"])
        self.assertEqual(page["after"], "6")
        tail = self.store.pull("north", page["after"], 100)
        self.assertEqual([r["id"] for r in tail["events"]], ["later"])
        empty = self.store.pull("absent", "0", 10)
        self.assertEqual(empty["events"], [])
        self.assertEqual(empty["after"], "7")

    def test_sync_cursor_scope_and_invalid_values(self):
        for entity in ("a", "b", "c"):
            self.store.mutate(request(entity=entity, mutation=entity))
        snap = self.store.snapshot("north", 1)["next_cursor"]
        pull = self.store.pull("north", "0", 1)["next_cursor"]
        for cursor in ("*", "e30", snap):
            self.expect_error("invalid_cursor", lambda: self.store.pull("north", "0", 1, cursor))
        self.expect_error("invalid_cursor", lambda: self.store.snapshot("south", 1, snap))
        self.expect_error("invalid_cursor", lambda: self.store.snapshot("north", 1, pull))
        self.expect_error("invalid_cursor", lambda: self.store.pull("north", "1", 1, pull))
        for checkpoint in ("00", "-1", "1.0", "99999999999999999999", 0, "999"):
            self.expect_error("invalid_cursor",
                              lambda: self.store.pull("north", checkpoint, 10))
        for limit in (True, 0, 101, 1.5):
            self.expect_error("invalid", lambda: self.store.snapshot("north", limit))
        self.sql("UPDATE metadata SET epoch='replacement'")
        self.expect_error("invalid_cursor", lambda: self.store.snapshot("north", 1, snap))

    def test_sync_large_wire_values(self):
        self.store.mutate(request())
        self.sql("UPDATE events SET revision=?", (9007199254740992,))
        self.sql("UPDATE documents SET revision=?", (9007199254740992,))
        self.sql("UPDATE sqlite_sequence SET seq=? WHERE name='events'", (9007199254740992,))
        a = self.store.mutate(request(kind="visit", base="9007199254740992",
                                      mutation="large1", data={"amount": 1}))
        b = self.store.mutate(request(kind="visit", base="9007199254740993",
                                      mutation="large2", data={"amount": 1}))
        self.assertEqual(a["record"]["revision"], "9007199254740993")
        self.assertEqual(b["record"]["revision"], "9007199254740994")
        self.assertEqual(a["record"]["seq"], "9007199254740993")
        self.assertEqual(b["record"]["seq"], "9007199254740994")
        self.assertEqual(self.store.snapshot("north", 100)["rows"], [b["record"]])
        self.assertEqual(self.store.pull("north", "9007199254740992", 100)["events"],
                         [a["record"], b["record"]])

    def test_transactions_generated_reference_replay(self):
        rng = random.Random(48191)
        expected = {}
        requests, receipts = [], []
        for i in range(100):
            tenant, entity = rng.choice(["north", "south"]), rng.choice(["A", "B", "C", "D"])
            key = (tenant, entity)
            old = expected.get(key)
            kind = "create" if old is None else (
                "restore" if old["deleted"] else rng.choice(["patch", "visit", "delete"]))
            if kind == "create":
                data = {"title": f"Inspection {i}", "assignee": None, "visits": 0, "done": False}
                new_body = copy.deepcopy(data)
            else:
                new_body = copy.deepcopy(old["body"])
                if kind == "visit":
                    data = {"amount": rng.randint(1, 4)}
                    new_body["visits"] += data["amount"]
                elif kind in ("patch", "restore"):
                    data = {"assignee": rng.choice(["crew-a", "crew-b", None]), "done": bool(i % 2)}
                    new_body.update(data)
                else:
                    data = {}
            req = request(entity, f"generated-{i}", rng.choice(["v1", "v2"]), tenant,
                          kind, old["revision"] if old else "0", data)
            expected[key] = {"id": entity, "body": new_body, "deleted": kind == "delete",
                             "revision": str(int(old["revision"]) + 1 if old else 1),
                             "seq": str(i + 1)}
            result = Store(self.path).mutate(req)
            self.assertEqual(result["record"], expected[key])
            requests.append(req)
            receipts.append(result)
            if i % 7 == 0:
                j = rng.randrange(len(requests))
                self.assertEqual(Store(self.path).mutate(requests[j]), receipts[j])
        for tenant in ("north", "south"):
            actual = self.store.snapshot(tenant, 100)["rows"]
            self.assertEqual(actual, [v for (t, _), v in sorted(expected.items()) if t == tenant])
        self.assertEqual(len(self.sql("SELECT * FROM events")), 100)

    def test_recovery_alternate_database_and_idempotence(self):
        expected = {}
        for tenant in ("north", "south"):
            for entity in ("same", "lost", "deleted"):
                created = self.store.mutate(request(entity, entity, tenant=tenant))["record"]
                if entity == "deleted":
                    created = self.store.mutate(request(entity, "del", tenant=tenant,
                                                        kind="delete", base="1", data={}))["record"]
                expected[(tenant, entity)] = created
        before = self.immutable()
        self.sql("UPDATE documents SET revision=0, deleted=0")
        self.sql("DELETE FROM documents WHERE id='lost'")
        self.sql("INSERT INTO documents VALUES ('extra','ghost',1,'{}',0)")
        result = subprocess.run(["python3", str(APP / "tools/repair.py"), "--db", str(self.path)],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["repaired"], 7)
        self.assertEqual(before, self.immutable())
        rows = self.sql("SELECT tenant,id,revision,body,deleted FROM documents")
        actual = {(t, i): (str(r), json.loads(b), bool(d)) for t, i, r, b, d in rows}
        self.assertEqual(actual, {k: (v["revision"], v["body"], v["deleted"])
                                  for k, v in expected.items()})
        self.assertEqual(self.store.repair_projection(), {"repaired": 0})

    def test_recovery_delivered_incident_state(self):
        seed = Path(self.temp.name) / "incident.sqlite"
        completed = subprocess.run(["python3", str(APP / "tools/seed.py"), "--db", str(seed)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        actual_path = APP / "state/site.sqlite"
        self.assertEqual(self.immutable(seed), self.immutable(actual_path))
        with sqlite3.connect(actual_path) as db:
            rows = db.execute("SELECT tenant,id,revision,body,deleted FROM documents").fetchall()
        expected = {
            ("north", "pump-17"): (43, {"title": "Inspect east pump", "assignee": None,
                                       "visits": 9, "done": True}, False),
            ("north", "valve-4"): (2, {"title": "Replace valve", "assignee": None,
                                      "visits": 0, "done": False}, True),
            ("south", "pump-17"): (6, {"title": "Check backup pump", "assignee": "Jo",
                                      "visits": 2, "done": False}, False),
        }
        self.assertEqual({(t, i): (r, json.loads(b), bool(d)) for t, i, r, b, d in rows}, expected)

    def test_client_ack_and_pending(self):
        self.js("ack")

    def test_client_integer_precision_and_immutability(self):
        self.js("precision")

    def test_client_snapshot_staging_and_interleaving(self):
        self.js("snapshot")

    def test_client_checkpoint_and_gap_handling(self):
        self.js("checkpoint")

    def test_client_conflict_resolution_and_frozen_request(self):
        self.js("conflict")

    def test_client_tombstones_and_optimistic_replay(self):
        self.js("tombstone")

    def test_client_generated_delivery_permutations(self):
        self.js("generated")

    def test_durability_atomic_replace(self):
        self.js("atomic", self.temp.name)

    def test_durability_persist_before_exchange(self):
        self.js("durable", self.temp.name)

    def test_integration_http_restart_lost_response(self):
        module = importlib.import_module("server.http")
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        server.database = str(self.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(url + "/health", timeout=10) as response:
                self.assertEqual(response.status, 200)
            self.js("http", self.temp.name, url)
            self.assertEqual(len(self.sql("SELECT * FROM events")), 3)
            self.assertEqual(len(self.sql("SELECT * FROM receipts")), 3)
        finally:
            server.shutdown()
            thread.join(10)
            server.server_close()

    def test_artifacts_report_and_regressions(self):
        report = APP / "REPAIR_REPORT.md"
        self.assertTrue(report.is_file(), "Missing repair report")
        self.assertTrue(report.read_text().strip(), "Empty repair report")
        python = subprocess.run(["python3", "-m", "unittest", "discover", "-s", str(APP / "tests"),
                                 "-p", "*.py"], text=True, capture_output=True, timeout=90)
        self.assertEqual(python.returncode, 0, python.stdout + python.stderr)
        files = sorted(str(p) for p in (APP / "tests").glob("*.mjs"))
        node = subprocess.run(["node", "--test", *files], text=True,
                              capture_output=True, timeout=90)
        self.assertEqual(node.returncode, 0, node.stdout + node.stderr)

    def test_artifacts_protected_inputs(self):
        expected = json.loads((HERE / "protected.json").read_text())
        for relative, sha in expected.items():
            self.assertEqual(hashlib.sha256((APP / relative).read_bytes()).hexdigest(), sha,
                             f"Protected input changed: {relative}")

    def test_batches_sequential_same_entity_and_retry(self):
        self.store.mutate(request())
        value = bundle(request(kind="visit", base="1", mutation="visit", data={"amount": 2}),
                       request(kind="patch", base="2", mutation="done", data={"done": True}),
                       request(entity="other", mutation="create-other"))
        receipt = self.store.mutate_batch(value)
        self.assertEqual([r["record"]["revision"] for r in receipt["responses"]], ["2", "3", "1"])
        self.assertEqual([r["record"]["seq"] for r in receipt["responses"]], ["2", "3", "4"])
        self.assertEqual(receipt["responses"][1]["record"]["body"]["visits"], 2)
        self.store.mutate(request(kind="patch", base="3", mutation="newer", data={"title": "Newer"}))
        self.assertEqual(Store(self.path).mutate_batch(copy.deepcopy(value)), receipt)
        changed = copy.deepcopy(value)
        changed["operations"][0]["data"]["amount"] = 3
        self.expect_error("idempotency_reuse", lambda: self.store.mutate_batch(changed))
        self.assertEqual(len(self.sql("SELECT * FROM batches")), 1)
        self.assertEqual(len(self.sql("SELECT * FROM events")), 5)

    def test_batches_conflict_and_fault_rollback(self):
        self.store.mutate(request())
        good = request(kind="visit", base="1", mutation="visit", data={"amount": 2})
        bad = request(kind="patch", base="1", mutation="done", data={"done": True})
        before = self.immutable()
        documents = self.sql("SELECT * FROM documents")
        error = self.expect_error("conflict", lambda: self.store.mutate_batch(bundle(good, bad)))
        self.assertEqual(error.detail["index"], 1)
        self.assertEqual(before, self.immutable())
        self.assertEqual(documents, self.sql("SELECT * FROM documents"))
        value = bundle(good, {**bad, "base": "2"})
        for phase in ("after_document", "after_event"):
            seen = []
            def fault(label):
                seen.append(label)
                if label == phase and seen.count(label) == 2:
                    raise RuntimeError("second operation crash")
            with self.assertRaisesRegex(RuntimeError, "second operation crash"):
                Store(self.path, fault=fault).mutate_batch(value)
            self.assertEqual(before, self.immutable())
            self.assertEqual(documents, self.sql("SELECT * FROM documents"))
        self.assertEqual(len(Store(self.path).mutate_batch(value)["responses"]), 2)

    def test_batches_precommitted_member_not_atomic(self):
        self.store.mutate(request())
        committed = request(kind="visit", base="1", mutation="visit", data={"amount": 2})
        self.store.mutate(committed)
        before = self.immutable()
        first = request(entity="new", mutation="new")
        error = self.expect_error("batch_conflict",
                                  lambda: self.store.mutate_batch(bundle(first, committed)))
        self.assertEqual(error.detail["index"], 1)
        self.assertEqual(before, self.immutable())
        self.assertEqual(self.sql("SELECT * FROM documents WHERE id='new'"), [])
        value = bundle(first, {**committed, "mutation": "another", "base": "2"})
        self.store.mutate_batch(value)
        self.assertEqual(len(self.sql("SELECT * FROM batches")), 1)

    def test_batches_concurrent_duplicate_and_namespace(self):
        value = bundle(request(), request(kind="visit", base="1", mutation="visit", data={"amount": 3}))
        context = multiprocessing.get_context("fork")
        barrier, queue = context.Barrier(4), context.Queue()
        processes = [context.Process(target=batch_worker, args=(str(self.path), barrier, queue, value))
                     for _ in range(4)]
        try:
            for process in processes:
                process.start()
            results = [queue.get(timeout=40) for _ in processes]
            for process in processes:
                process.join(5)
                self.assertEqual(process.exitcode, 0)
            self.assertTrue(all(result == results[0] for result in results), results)
            self.assertEqual(results[0][0], "ok", results)
            self.assertEqual(len(self.sql("SELECT * FROM events")), 2)
            other = bundle(request(entity="other"), name="closeout", device="van-8")
            self.assertEqual(self.store.mutate_batch(other)["device"], "van-8")
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
            queue.close()

    def test_batches_invalid_and_preserved_by_repair(self):
        for value in (bundle(), {**bundle(request()), "extra": 1},
                      bundle(request(), request()), {**bundle(request()), "operations": {}},
                      {**bundle(request()), "operations": [request()]}):
            self.expect_error("invalid", lambda: self.store.mutate_batch(value))
        valid = bundle(request())
        self.store.mutate_batch(valid)
        before = self.immutable()
        self.sql("DELETE FROM documents")
        self.assertEqual(self.store.repair_projection(), {"repaired": 1})
        self.assertEqual(before, self.immutable())
        self.assertEqual(self.store.mutate_batch(valid)["responses"][0]["record"]["revision"], "1")

    def test_confirmations_snapshot_history_and_cut(self):
        values = [request(entity="a", mutation="a1"),
                  request(entity="a", mutation="a2", base="1", kind="visit", data={"amount": 2}),
                  request(entity="a", mutation="a3", base="2", kind="patch", data={"done": True}),
                  request(entity="b", mutation="b1"),
                  request(entity="a", mutation="other", tenant="south")]
        for value in values:
            self.store.mutate(value)
        first = self.store.snapshot("north", 1)
        self.assertEqual(first["confirmed"], [
            {"device": "van-7", "mutation": f"a{i}", "id": "a", "seq": str(i)}
            for i in range(1, 4)])
        self.store.mutate(request(entity="b", mutation="b2", base="1", kind="delete", data={}))
        second = self.store.snapshot("north", 1, first["next_cursor"])
        self.assertEqual(second["confirmed"], [
            {"device": "van-7", "mutation": "b1", "id": "b", "seq": "4"}])
        self.assertEqual(self.store.snapshot("empty", 1)["confirmed"], [])
        pull = self.store.pull("north", "2", 1)
        self.assertEqual(pull["confirmed"], [
            {"device": "van-7", "mutation": "a3", "id": "a", "seq": "3"}])

    def test_confirmations_client_pull_before_ack(self):
        self.js("confirm-pull")

    def test_confirmations_client_snapshot_staging(self):
        self.js("confirm-snapshot")

    def test_batches_client_base_prediction_and_ack(self):
        self.js("batch")

    def test_batches_client_partial_confirmation_restart(self):
        self.js("batch-durable", self.temp.name)

    def test_integration_atomic_batch_http_confirmation(self):
        module = importlib.import_module("server.http")
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        server.database = str(self.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.js("batch-http", self.temp.name, f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(len(self.sql("SELECT * FROM events")), 5)
            self.assertEqual(len(self.sql("SELECT * FROM batches")), 1)
        finally:
            server.shutdown()
            thread.join(10)
            server.server_close()
