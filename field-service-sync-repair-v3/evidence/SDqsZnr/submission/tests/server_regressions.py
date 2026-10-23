"""Server regression tests: imported and run by tests/smoke.py."""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.codec import SyncError, canonical  # noqa: E402
from server.store import Store  # noqa: E402

BIG = 9007199254740993  # 2^53 + 1


def body(title="Inspection", assignee=None, visits=0, done=False):
    return {"title": title, "assignee": assignee, "visits": visits, "done": done}


def request(mutation, entity, base, kind, data, tenant="north", device="van-7"):
    return {"tenant": tenant, "device": device, "mutation": mutation, "id": entity,
            "base": str(base), "kind": kind, "data": data}


def history(path):
    db = sqlite3.connect(path)
    try:
        return {table: sorted(db.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
                for table in ("metadata", "events", "receipts", "batches", "retention",
                              "anchors", "sqlite_sequence")}
    finally:
        db.close()


def documents(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT * FROM documents ORDER BY tenant,id").fetchall()
    finally:
        db.close()


def snapshot_all(store, tenant, limit=1):
    pages, cursor = [], None
    while True:
        page = store.snapshot(tenant, limit, cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


def pull_all(store, tenant, checkpoint, limit=1):
    pages, cursor = [], None
    while True:
        page = store.pull(tenant, checkpoint, limit, cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


def racing_patch(args):
    path, device, mutation = args
    try:
        return Store(path).mutate(request(mutation, "shared", 1, "patch",
                                          {"assignee": device}, device=device))["ok"]
    except SyncError as exc:
        return exc.code


def racing_batch(path):
    return canonical(Store(path).mutate_batch({
        "tenant": "north", "device": "van-7", "batch": "race",
        "operations": [
            {"mutation": "rb-1", "id": "shared", "base": "1", "kind": "visit", "data": {"amount": 1}},
            {"mutation": "rb-2", "id": "shared", "base": "2", "kind": "patch", "data": {"done": True}},
        ]}))


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = Path(self.directory) / "work.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        shutil.rmtree(self.directory)

    def create(self, entity, mutation=None, tenant="north", device="van-7", **fields):
        return self.store.mutate(request(mutation or f"c-{entity}", entity, 0, "create",
                                         body(**fields), tenant=tenant, device=device))

    def assertSync(self, status, code, function, *args):
        with self.assertRaises(SyncError) as caught:
            function(*args)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))
        return caught.exception


class Mutations(Base):
    def test_wire_decimals_and_receipt_replay_after_newer_writes(self):
        first = self.create("pump")
        self.assertEqual(first["record"]["revision"], "1")
        self.assertIsInstance(first["record"]["seq"], str)
        self.store.mutate(request("v", "pump", 1, "visit", {"amount": 2}))
        retry = dict(reversed(list(request("c-pump", "pump", 0, "create", body()).items())))
        self.assertEqual(self.store.mutate(retry), first)

    def test_idempotency_scope_includes_device(self):
        self.create("pump")
        mine = self.store.mutate(request("m-9", "pump", 1, "visit", {"amount": 1}))
        other = self.store.mutate(request("m-9", "pump", 2, "patch", {"assignee": "Lee"},
                                          device="van-8"))
        self.assertEqual(other["device"], "van-8")
        self.assertEqual(other["record"]["revision"], "3")
        self.assertEqual(self.store.mutate(request("m-9", "pump", 1, "visit", {"amount": 1})), mine)
        self.assertSync(409, "idempotency_reuse", self.store.mutate,
                        request("m-9", "pump", 1, "visit", {"amount": 2}))

    def test_conflicts_report_current_and_do_not_consume_keys(self):
        self.create("pump")
        error = self.assertSync(409, "conflict", self.store.mutate,
                                request("p", "pump", 0, "patch", {"done": True}))
        self.assertEqual(error.detail["current"]["revision"], "1")
        self.assertSync(409, "conflict", self.store.mutate,
                        request("c2", "pump", 0, "create", body()))
        self.assertEqual(self.store.mutate(request("p", "pump", 1, "patch", {"done": True}))
                         ["record"]["body"]["done"], True)
        missing = self.assertSync(409, "conflict", self.store.mutate,
                                  request("x", "ghost", 1, "patch", {"done": True}))
        self.assertIsNone(missing.detail["current"])

    def test_delete_restore_and_tombstone_rules(self):
        self.create("valve", title="Replace valve")
        deleted = self.store.mutate(request("d", "valve", 1, "delete", {}))
        self.assertTrue(deleted["record"]["deleted"])
        self.assertEqual(deleted["record"]["body"]["title"], "Replace valve")
        self.assertSync(409, "conflict", self.store.mutate,
                        request("p", "valve", 2, "patch", {"done": True}))
        self.assertSync(409, "conflict", self.store.mutate,
                        request("re", "valve", 0, "create", body()))
        restored = self.store.mutate(request("r", "valve", 2, "restore", {"assignee": "Ana"}))
        self.assertFalse(restored["record"]["deleted"])
        self.assertEqual(restored["record"]["body"]["assignee"], "Ana")
        self.assertSync(409, "conflict", self.store.mutate,
                        request("r2", "valve", 3, "restore", {}))

    def test_invalid_requests(self):
        self.create("pump", visits=9007199254740990)
        bad = [
            {**request("a", "pump", 1, "patch", {"done": True}), "extra": 1},
            request("a", "pump", 1, "patch", {"colour": "red"}),
            request("a", "pump", 1, "visit", {"amount": True}),
            request("a", "pump", 1, "visit", {"amount": 1.0}),
            request("a", "pump", 1, "visit", {"amount": 0}),
            request("a", "pump", 1, "patch", {"title": ""}),
            request("a", "pump", 1, "patch", {"visits": 9007199254740992}),
            request("a", "pump", "01", "patch", {"done": True}),
            request("a", "", 1, "patch", {"done": True}),
            request("", "pump", 1, "patch", {"done": True}),
            request("a", "pump", 1, "delete", {"x": 1}),
            request("a", "pump", 1, "explode", {}),
            request("a", "new", 0, "create", {"title": "partial"}),
        ]
        for item in bad:
            self.assertSync(400, "invalid", self.store.mutate, item)
        self.assertSync(400, "invalid", self.store.mutate,
                        request("a", "pump", 1, "visit", {"amount": 2}))
        self.assertEqual(self.store.mutate(request("a", "pump", 1, "visit", {"amount": 1}))
                         ["record"]["body"]["visits"], 9007199254740991)

    def test_fault_injection_rolls_back_everything(self):
        for point in ("after_document", "after_event"):
            def hook(name, point=point):
                if name == point:
                    raise RuntimeError(point)
            before = (history(self.path), documents(self.path))
            with self.assertRaises(RuntimeError):
                Store(self.path, fault=hook).mutate(request("f", "pump", 0, "create", body()))
            self.assertEqual((history(self.path), documents(self.path)), before)
        self.assertEqual(self.create("pump", mutation="f")["record"]["revision"], "1")

    def test_unicode_ids_and_payloads(self):
        entity, title = "заказ-🚒", "Überprüfung ✓ 漢字"
        response = self.store.mutate(request("ми-1", entity, 0, "create", body(title=title),
                                             tenant="север", device="фургон"))
        self.assertEqual(response["record"]["body"]["title"], title)
        row = self.store.snapshot("север", 10)["rows"][0]
        self.assertEqual((row["id"], row["body"]["title"]), (entity, title))
        self.assertEqual(self.store.mutate(request("ми-1", entity, 0, "create", body(title=title),
                                                   tenant="север", device="фургон")), response)

    def test_concurrent_writers_single_winner(self):
        self.create("shared")
        jobs = [(str(self.path), f"van-{n}", f"m-{n}") for n in range(8)]
        with ProcessPoolExecutor(4) as pool:
            results = list(pool.map(racing_patch, jobs))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count("conflict"), 7)
        self.assertEqual(len(history(self.path)["events"]), 2)

    def test_sequence_beyond_safe_integer_range(self):
        db = sqlite3.connect(self.path)
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                   (BIG, "north", "old", 1, canonical(body()), 0, "archive", "legacy"))
        db.commit()
        db.close()
        response = self.create("new")
        self.assertEqual(response["record"]["seq"], str(BIG + 1))
        page = self.store.pull("north", str(BIG), 10)
        self.assertEqual([e["seq"] for e in page["events"]], [str(BIG + 1)])
        self.assertEqual(page["until"], str(BIG + 1))


class Batches(Base):
    def batch(self, name, operations, device="van-7"):
        return {"tenant": "north", "device": device, "batch": name, "operations": operations}

    def op(self, mutation, entity, base, kind, data):
        return {"mutation": mutation, "id": entity, "base": str(base), "kind": kind, "data": data}

    def test_atomic_closeout_with_transaction_local_bases(self):
        self.create("pump")
        self.create("valve")
        response = self.store.mutate_batch(self.batch("close", [
            self.op("v", "pump", 1, "visit", {"amount": 1}),
            self.op("d", "pump", 2, "patch", {"done": True}),
            self.op("x", "valve", 1, "patch", {"done": True}),
        ]))
        self.assertEqual([r["record"]["revision"] for r in response["responses"]], ["2", "3", "2"])
        self.assertEqual(self.store.mutate_batch(self.batch("close", [
            self.op("v", "pump", 1, "visit", {"amount": 1}),
            self.op("d", "pump", 2, "patch", {"done": True}),
            self.op("x", "valve", 1, "patch", {"done": True}),
        ])), response)
        self.assertEqual(self.store.mutate(request("d", "pump", 2, "patch", {"done": True})),
                         response["responses"][1])
        self.assertSync(409, "idempotency_reuse", self.store.mutate_batch,
                        self.batch("close", [self.op("v", "pump", 1, "visit", {"amount": 2})]))
        self.assertSync(409, "idempotency_reuse", self.store.mutate_batch,
                        self.batch("close", [self.op("v", "pump", 1, "visit", {"amount": 0})]))
        self.assertSync(409, "idempotency_reuse", self.store.mutate_batch,
                        self.batch("close", "not a list"))

    def test_partial_failure_commits_nothing(self):
        self.create("pump")
        self.create("valve")
        before = (history(self.path), documents(self.path))
        error = self.assertSync(409, "conflict", self.store.mutate_batch, self.batch("close", [
            self.op("v", "pump", 1, "visit", {"amount": 1}),
            self.op("d", "pump", 2, "patch", {"done": True}),
            self.op("x", "valve", 3, "patch", {"done": True}),
        ]))
        self.assertEqual(error.detail["index"], 2)
        self.assertEqual(error.detail["current"]["revision"], "1")
        self.assertEqual((history(self.path), documents(self.path)), before)
        self.store.mutate(request("v", "pump", 1, "visit", {"amount": 1}))

    def test_batch_conflict_for_independently_committed_operation(self):
        self.create("pump")
        self.store.mutate(request("v", "pump", 1, "visit", {"amount": 1}))
        error = self.assertSync(409, "batch_conflict", self.store.mutate_batch, self.batch("b", [
            self.op("w", "pump", 2, "patch", {"done": True}),
            self.op("v", "pump", 1, "visit", {"amount": 1}),
        ]))
        self.assertEqual(error.detail["index"], 1)
        self.assertEqual(len(history(self.path)["events"]), 2)

    def test_invalid_envelopes(self):
        self.create("pump")
        for item in [
            [], {"tenant": "north"},
            self.batch("b", []),
            self.batch("b", {"0": self.op("a", "pump", 1, "visit", {"amount": 1})}),
            self.batch("b", [self.op("a", "pump", 1, "visit", {"amount": 1})] * 2),
            self.batch("b", [{**self.op("a", "pump", 1, "visit", {"amount": 1}), "tenant": "x"}]),
            self.batch("b", [self.op(f"a{n}", "pump", 1 + n, "visit", {"amount": 1})
                             for n in range(17)]),
            {**self.batch("b", [self.op("a", "pump", 1, "visit", {"amount": 1})]), "x": 1},
        ]:
            self.assertSync(400, "invalid", self.store.mutate_batch, item)

    def test_fault_in_later_operation_rolls_back_batch(self):
        self.create("pump")
        calls = []

        def hook(name):
            calls.append(name)
            if len(calls) == 3:
                raise RuntimeError("disk full")
        before = (history(self.path), documents(self.path))
        with self.assertRaises(RuntimeError):
            Store(self.path, fault=hook).mutate_batch(self.batch("b", [
                self.op("a", "pump", 1, "visit", {"amount": 1}),
                self.op("b", "pump", 2, "visit", {"amount": 1}),
            ]))
        self.assertEqual((history(self.path), documents(self.path)), before)

    def test_racing_processes_share_one_receipt(self):
        self.create("shared")
        with ProcessPoolExecutor(4) as pool:
            results = list(pool.map(racing_batch, [str(self.path)] * 6))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(history(self.path)["events"]), 3)


class Reads(Base):
    def test_snapshot_is_frozen_across_pages(self):
        for entity in ("a", "c", "valve"):
            self.create(entity)
        first = self.store.snapshot("north", 1)
        self.store.mutate(request("del", "valve", 1, "delete", {}))
        self.create("b")
        self.store.mutate(request("p", "c", 1, "patch", {"done": True}))
        pages, cursor = [first], first["next_cursor"]
        while cursor:
            pages.append(self.store.snapshot("north", 1, cursor))
            cursor = pages[-1]["next_cursor"]
        rows = [row for page in pages for row in page["rows"]]
        self.assertEqual([r["id"] for r in rows], ["a", "c", "valve"])
        self.assertEqual({p["cut"] for p in pages}, {first["cut"]})
        self.assertFalse(rows[1]["body"]["done"])
        self.assertFalse(rows[2]["deleted"])
        fresh = [r for p in snapshot_all(self.store, "north", 2) for r in p["rows"]]
        self.assertEqual([r["id"] for r in fresh], ["a", "b", "c", "valve"])
        self.assertTrue(fresh[3]["deleted"])

    def test_snapshot_ignores_drifted_projection(self):
        self.create("pump")
        db = sqlite3.connect(self.path)
        db.execute("UPDATE documents SET revision=7")
        db.execute("INSERT INTO documents VALUES ('north','phantom',1,?,0)", (canonical(body()),))
        db.commit()
        db.close()
        rows = self.store.snapshot("north", 10)["rows"]
        self.assertEqual([(r["id"], r["revision"]) for r in rows], [("pump", "1")])
        self.store.mutate(request("v", "pump", 1, "visit", {"amount": 1}))

    def test_empty_tenant_and_cursor_validation(self):
        self.create("pump")
        page = self.store.snapshot("nobody", 5)
        self.assertEqual((page["rows"], page["confirmed"], page["next_cursor"]), ([], [], None))
        self.create("q")
        cursor = self.store.snapshot("north", 1)["next_cursor"]
        pull_cursor = self.store.pull("north", "0", 1)["next_cursor"]
        self.assertSync(400, "invalid_cursor", self.store.snapshot, "south", 1, cursor)
        self.assertSync(400, "invalid_cursor", self.store.snapshot, "north", 1, "!!")
        self.assertSync(400, "invalid_cursor", self.store.snapshot, "north", 1, "e30")
        self.assertSync(400, "invalid_cursor", self.store.pull, "north", "0", 1, cursor)
        self.assertSync(400, "invalid_cursor", self.store.snapshot, "north", 1, pull_cursor)
        self.assertSync(400, "invalid_cursor", self.store.pull, "north", "1", 1, pull_cursor)
        self.assertSync(400, "invalid_cursor", self.store.pull, "north", "99", 1)
        self.assertSync(400, "invalid_cursor", self.store.pull, "north", "00", 1)
        self.assertSync(400, "invalid", self.store.snapshot, "north", 0)
        self.assertSync(400, "invalid", self.store.snapshot, "north", 101)

    def test_pull_is_exclusive_frozen_and_contiguous(self):
        self.create("a")
        self.create("x", tenant="south")
        self.create("b")
        self.create("y", tenant="south")
        first = self.store.pull("north", "0", 1)
        self.create("c")
        pages, cursor = [first], first["next_cursor"]
        while cursor:
            pages.append(self.store.pull("north", "0", 1, cursor))
            cursor = pages[-1]["next_cursor"]
        seqs = [e["seq"] for p in pages for e in p["events"]]
        self.assertEqual([e["id"] for p in pages for e in p["events"]], ["a", "b"])
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertEqual(pages[-1]["after"], "4")
        self.assertEqual({p["until"] for p in pages}, {"4"})
        for previous, page in zip(pages, pages[1:]):
            self.assertEqual(page["from"], previous["after"])
        for page in pages:
            self.assertEqual([c["seq"] for c in page["confirmed"]],
                             [e["seq"] for e in page["events"]])
        nxt = self.store.pull("north", "4", 10)
        self.assertEqual(([e["id"] for e in nxt["events"]], nxt["after"]), (["c"], "5"))

    def test_snapshot_confirmations_cover_history_of_page_entities(self):
        self.create("a", device="van-1")
        self.store.mutate(request("va", "a", 1, "visit", {"amount": 1}, device="van-2"))
        self.create("b")
        self.create("a", tenant="south")
        first = self.store.snapshot("north", 1)
        self.store.mutate(request("late", "a", 2, "visit", {"amount": 1}))
        self.assertEqual([c["mutation"] for c in first["confirmed"]], ["c-a", "va"])
        self.assertEqual([c["device"] for c in first["confirmed"]], ["van-1", "van-2"])
        second = self.store.snapshot("north", 1, first["next_cursor"])
        self.assertEqual([(c["id"], c["mutation"]) for c in second["confirmed"]], [("b", "c-b")])


class Retention(Base):
    def populate(self):
        self.create("pump")                                             # 1
        self.create("valve")                                            # 2
        self.store.mutate(request("v1", "pump", 1, "visit", {"amount": 1}))  # 3
        self.store.mutate(request("dv", "valve", 1, "delete", {}))      # 4
        self.create("other", tenant="south")                            # 5

    def test_compaction_retains_baseline_and_sequence(self):
        self.populate()
        self.assertEqual(self.store.compact("3"), {"through": "3", "pruned": 3})
        self.assertEqual(self.store.compact("3"), {"through": "3", "pruned": 0})
        self.assertEqual(self.store.compact("5"), {"through": "5", "pruned": 2})
        for bad in ("4", "6", "x", "05", 5):
            self.assertSync(400, "invalid", self.store.compact, bad)
        rows = [r for p in snapshot_all(self.store, "north") for r in p["rows"]]
        self.assertEqual([(r["id"], r["revision"], r["deleted"]) for r in rows],
                         [("pump", "2", False), ("valve", "2", True)])
        error = self.assertSync(409, "conflict", self.store.mutate,
                                request("p", "pump", 1, "patch", {"done": True}))
        self.assertEqual(error.detail["current"]["revision"], "2")
        self.assertSync(409, "conflict", self.store.mutate,
                        request("again", "valve", 0, "create", body()))
        nxt = self.store.mutate(request("p", "pump", 2, "patch", {"done": True}))
        self.assertEqual(nxt["record"]["seq"], "6")
        restored = self.store.mutate(request("r", "valve", 2, "restore", {}))
        self.assertEqual(restored["record"]["revision"], "3")

    def test_sequence_never_reused_after_pruning_everything(self):
        self.populate()
        self.store.compact("5")
        self.assertEqual(self.create("fresh")["record"]["seq"], "6")
        page = self.store.snapshot("north", 10)
        self.assertEqual(page["cut"], "6")

    def test_expired_reads(self):
        self.populate()
        cursor = self.store.snapshot("north", 1)["next_cursor"]
        pull = self.store.pull("north", "0", 1)
        self.create("late")                                             # 6
        self.store.compact("6")
        error = self.assertSync(410, "resnapshot_required", self.store.pull, "north", "5", 10)
        self.assertEqual(error.detail, {"epoch": history(self.path)["metadata"][0][0], "floor": "6"})
        self.assertSync(410, "resnapshot_required", self.store.snapshot, "north", 1, cursor)
        self.assertSync(410, "resnapshot_required", self.store.pull, "north", "0", 1,
                        pull["next_cursor"])
        self.assertSync(400, "invalid_cursor", self.store.pull, "south", "0", 1,
                        pull["next_cursor"])
        page = self.store.pull("north", "6", 10)
        self.assertEqual((page["events"], page["confirmed"], page["after"]), ([], [], "6"))
        rows = [r for p in snapshot_all(self.store, "north") for r in p["rows"]]
        self.assertEqual([r["id"] for r in rows], ["late", "pump", "valve"])

    def test_serviceable_continuation_crosses_compaction(self):
        self.populate()
        first = self.store.pull("north", "0", 2)
        self.assertEqual(first["after"], "2")
        self.store.compact("2")
        self.assertSync(410, "resnapshot_required", self.store.pull, "north", "0", 1)
        resumed = self.store.pull("north", "0", 2, first["next_cursor"])
        self.assertEqual(resumed["from"], "2")
        self.assertEqual([e["seq"] for e in resumed["events"]], ["3", "4"])
        self.assertEqual(resumed["until"], first["until"])

    def test_snapshot_confirmations_survive_pruning(self):
        self.populate()
        self.store.compact("5")
        page = self.store.snapshot("north", 10)
        self.assertEqual([c["mutation"] for c in page["confirmed"]], ["c-pump", "c-valve", "v1", "dv"])

    def test_compaction_faults_roll_back(self):
        self.populate()
        for point in ("after_anchor", "after_prune"):
            def hook(name, point=point):
                if name == point:
                    raise RuntimeError(point)
            before = history(self.path)
            with self.assertRaises(RuntimeError):
                Store(self.path, fault=hook).compact("4")
            self.assertEqual(history(self.path), before)

    def test_repair_after_compaction_keeps_tombstones(self):
        self.populate()
        self.store.compact("5")
        db = sqlite3.connect(self.path)
        db.execute("DELETE FROM documents")
        db.commit()
        db.close()
        before = history(self.path)
        self.assertEqual(self.store.repair_projection(), {"repaired": 3})
        self.assertEqual(history(self.path), before)
        self.assertEqual([(r[1], r[4]) for r in documents(self.path)],
                         [("pump", 0), ("valve", 1), ("other", 0)])

    def test_compact_cli(self):
        self.populate()
        script = [sys.executable, str(ROOT / "tools/compact.py"), "--db", str(self.path)]
        ok = subprocess.run(script + ["--through", "4"], capture_output=True, text=True)
        self.assertEqual((ok.returncode, json.loads(ok.stdout)), (0, {"through": "4", "pruned": 4}))
        bad = subprocess.run(script + ["--through", "3"], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("invalid", bad.stderr)


class Repair(unittest.TestCase):
    def test_seeded_incident_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incident.sqlite"
            subprocess.run([sys.executable, str(ROOT / "tools/seed.py"), "--db", str(path)],
                           check=True, capture_output=True)
            before = history(path)
            run = lambda: subprocess.run(  # noqa: E731
                [sys.executable, str(ROOT / "tools/repair.py"), "--db", str(path)],
                check=True, capture_output=True, text=True).stdout
            self.assertEqual(json.loads(run()), {"repaired": 4})
            self.assertEqual(json.loads(run()), {"repaired": 0})
            self.assertEqual(history(path), before)
            self.assertEqual([(t, i, r, d) for t, i, r, _, d in documents(path)],
                             [("north", "pump-17", 43, 0), ("north", "valve-4", 2, 1),
                              ("south", "pump-17", 6, 0)])
            store = Store(path)
            self.assertEqual(store.mutate(request("m-9", "pump-17", 43, "visit", {"amount": 1}))
                             ["record"]["seq"], "9007199254740999")

    def test_working_state_is_repaired(self):
        path = ROOT / "state/site.sqlite"
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "copy.sqlite"
            shutil.copy(path, copy)
            self.assertEqual(Store(copy).repair_projection(), {"repaired": 0})
            self.assertEqual(history(copy)["metadata"], [("dispatch-2026-04",)])


class Http(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = subprocess.Popen(
            [sys.executable, "-m", "server.http", "--db", str(self.path), "--port", str(self.port)],
            cwd=ROOT, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url("/health"))
                break
            except OSError:
                time.sleep(0.05)

    def tearDown(self):
        self.server.terminate()
        self.server.wait()
        self.server.stderr.close()
        super().tearDown()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def call(self, path, payload=None):
        data = None if payload is None else (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url(path), data=data)) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_http_surface(self):
        status, created = self.call("/mutate", request("ü", "pump", 0, "create", body(title="Pumpe ✓")))
        self.assertEqual((status, created["record"]["body"]["title"]), (200, "Pumpe ✓"))
        status, error = self.call("/mutate", request("x", "pump", 0, "create", body()))
        self.assertEqual((status, error["code"], error["detail"]["current"]["revision"]),
                         (409, "conflict", "1"))
        self.assertEqual(self.call("/mutate", b"{nope")[0], 400)
        self.assertEqual(self.call("/mutate", b'{"amount": NaN}')[0], 400)
        self.assertEqual(self.call("/batch", [])[0], 400)
        status, page = self.call("/snapshot?tenant=north&limit=10")
        self.assertEqual((status, page["rows"][0]["id"]), (200, "pump"))
        self.assertEqual(self.call("/pull?tenant=north&limit=10&checkpoint=0")[1]["after"], "1")
        self.assertEqual(self.call("/pull?tenant=north&limit=1.5&checkpoint=0")[0], 400)
        self.assertEqual(self.call("/pull?tenant=north&limit=10&checkpoint=9")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("/nowhere")[0], 404)
        self.assertEqual(self.call("/snapshot?tenant=north&limit=10&cursor=")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("/pull?tenant=north&limit=10&checkpoint=0&cursor=")[1]["code"],
                         "invalid_cursor")
        self.store.compact("1")
        status, error = self.call("/pull?tenant=north&limit=10&checkpoint=0")
        self.assertEqual((status, error["code"], error["detail"]["floor"]),
                         (410, "resnapshot_required", "1"))


if __name__ == "__main__":
    unittest.main()
