"""Server regressions for PROTOCOL.md v2/v2.1/v2.2 (store, HTTP, tools)."""
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
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.codec import SyncError, token  # noqa: E402
from server.store import Store  # noqa: E402

BIG = 9007199254740993  # 2^53 + 1


def full(title="Order", assignee=None, visits=0, done=False):
    return {"title": title, "assignee": assignee, "visits": visits, "done": done}


def req(mutation, entity, base, kind, data, tenant="north", device="van-7"):
    return {"tenant": tenant, "device": device, "mutation": mutation, "id": entity,
            "base": str(base), "kind": kind, "data": data}


def op(mutation, entity, base, kind, data):
    return {"mutation": mutation, "id": entity, "base": str(base), "kind": kind, "data": data}


def dump(path):
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3").fetchall()
                for table in ("events", "receipts", "batches", "documents", "anchors")} | {
            "meta": db.execute("SELECT * FROM metadata").fetchall(),
            "retention": db.execute("SELECT * FROM retention").fetchall(),
            "sequence": db.execute("SELECT * FROM sqlite_sequence").fetchall()}


def snapshot_all(store, tenant, limit=100):
    pages, cursor = [], None
    while True:
        page = store.snapshot(tenant, limit, cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


def race_worker(path, request, batch, queue):
    store = Store(path)
    try:
        result = store.mutate_batch(request) if batch else store.mutate(request)
        queue.put(("ok", json.dumps(result, sort_keys=True)))
    except SyncError as exc:
        queue.put((exc.code, None))


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "site.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def error(self, call, *args, **kwargs):
        with self.assertRaises(SyncError) as caught:
            call(*args, **kwargs)
        return caught.exception

    def jump(self, seq):
        """Move the global sequence into the beyond-2^53 range."""
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO sqlite_sequence(name,seq) VALUES ('events',?)",
                       (seq,))


class MutationTests(Base):
    def test_wire_values_are_decimal_strings_beyond_safe_integers(self):
        self.jump(BIG)
        response = self.store.mutate(req("c", "pump", 0, "create", full()))
        self.assertEqual(response["record"]["seq"], str(BIG + 1))
        self.assertEqual(response["record"]["revision"], "1")
        page = self.store.pull("north", str(BIG), 10)
        self.assertEqual(page["events"][0]["seq"], str(BIG + 1))
        self.assertEqual(page["until"], str(BIG + 1))

    def test_retry_returns_original_receipt_after_newer_writes(self):
        self.store.mutate(req("c", "pump", 0, "create", full(visits=1)))
        first = self.store.mutate(req("m-9", "pump", 1, "visit", {"amount": 1}))
        self.store.mutate(req("m-10", "pump", 2, "patch", {"assignee": "Mira"}))
        reordered = {"data": {"amount": 1}, "kind": "visit", "base": "1", "id": "pump",
                     "mutation": "m-9", "device": "van-7", "tenant": "north"}
        self.assertEqual(self.store.mutate(reordered), first)
        self.assertEqual(len(self.store.pull("north", "0", 100)["events"]), 3)
        error = self.error(self.store.mutate, req("m-9", "pump", 3, "visit", {"amount": 1}))
        self.assertEqual((error.status, error.code), (409, "idempotency_reuse"))

    def test_same_mutation_id_on_other_device_is_independent(self):
        self.store.mutate(req("c", "pump", 0, "create", full()))
        mine = self.store.mutate(req("m-9", "pump", 1, "visit", {"amount": 1}))
        other = self.store.mutate(req("m-9", "pump", 2, "patch", {"assignee": "Lee"},
                                      device="van-8"))
        self.assertEqual(other["device"], "van-8")
        self.assertEqual(other["record"]["revision"], "3")
        self.assertEqual(mine["device"], "van-7")

    def test_conflicts_and_failed_requests_do_not_consume_keys(self):
        self.store.mutate(req("c", "pump", 0, "create", full()))
        error = self.error(self.store.mutate, req("p", "pump", 5, "patch", {"done": True}))
        self.assertEqual((error.status, error.code), (409, "conflict"))
        self.assertEqual(error.detail["current"]["revision"], "1")
        self.assertEqual(self.store.mutate(req("p", "pump", 1, "patch", {"done": True}))
                         ["record"]["body"]["done"], True)
        error = self.error(self.store.mutate, req("again", "pump", 0, "create", full()))
        self.assertEqual(error.code, "conflict")
        error = self.error(self.store.mutate, req("x", "missing", 0, "patch", {"done": True}))
        self.assertEqual((error.code, error.detail["current"]), ("conflict", None))

    def test_delete_restore_and_tombstones(self):
        self.store.mutate(req("c", "valve", 0, "create", full(title="Valve", assignee="Jo")))
        gone = self.store.mutate(req("d", "valve", 1, "delete", {}))
        self.assertTrue(gone["record"]["deleted"])
        self.assertEqual(gone["record"]["body"]["assignee"], "Jo")
        for kind, data in (("patch", {"done": True}), ("visit", {"amount": 1}),
                           ("delete", {})):
            self.assertEqual(self.error(self.store.mutate,
                                        req("e-" + kind, "valve", 2, kind, data)).code,
                             "conflict")
        self.assertEqual(self.error(self.store.mutate,
                                    req("re", "valve", 0, "create", full())).code, "conflict")
        back = self.store.mutate(req("r", "valve", 2, "restore", {"assignee": None}))
        self.assertEqual((back["record"]["deleted"], back["record"]["body"]["assignee"]),
                         (False, None))
        self.assertEqual(self.error(self.store.mutate,
                                    req("r2", "valve", 3, "restore", {})).code, "conflict")

    def test_validation(self):
        self.store.mutate(req("c", "pump", 0, "create", full(visits=9007199254740990)))
        bad = [
            req("v", "pump", 1, "visit", {"amount": True}),
            req("v", "pump", 1, "visit", {"amount": 0}),
            req("v", "pump", 1, "visit", {"amount": 1.0}),
            req("v", "pump", 1, "visit", {"amount": 2}),  # total beyond 2^53-1
            req("v", "pump", 1, "patch", {"visits": True}),
            req("v", "pump", 1, "patch", {"title": ""}),
            req("v", "pump", 1, "patch", {"color": "red"}),
            req("v", "pump", "01", "patch", {}),
            req("v", "pump", 1, "delete", {"x": 1}),
            req("v", "pump", 1, "nope", {}),
            req("", "pump", 1, "patch", {}),
            req("v", "", 1, "patch", {}),
            req("v", "new", 0, "create", {"title": "x"}),
            {**req("v", "pump", 1, "patch", {}), "extra": 1},
        ]
        for request in bad:
            error = self.error(self.store.mutate, request)
            self.assertEqual((error.status, error.code), (400, "invalid"), request)
        self.assertEqual(self.store.mutate(req("v", "pump", 1, "visit", {"amount": 1}))
                         ["record"]["body"]["visits"], 9007199254740991)

    def test_unicode_ids_and_payloads(self):
        entity, tenant = "naïve-泵-🚰", "nörth"
        response = self.store.mutate(req("ü-1", entity, 0, "create",
                                         full(title="Prüfung 🛠", assignee="Zoë"),
                                         tenant=tenant, device="ván"))
        self.assertEqual(response["record"]["id"], entity)
        page = self.store.snapshot(tenant, 5)
        self.assertEqual(page["rows"][0]["body"]["title"], "Prüfung 🛠")
        self.assertEqual(page["confirmed"][0]["device"], "ván")
        self.assertEqual(self.store.snapshot("north", 5)["rows"], [])

    def test_fault_injection_rolls_back_everything(self):
        self.store.mutate(req("c", "pump", 0, "create", full()))
        before = dump(self.path)
        for stage in ("after_document", "after_event"):
            def hook(name, stage=stage):
                if name == stage:
                    raise RuntimeError("chaos")
            with self.assertRaises(RuntimeError):
                Store(self.path, fault=hook).mutate(req("v", "pump", 1, "visit", {"amount": 1}))
            self.assertEqual(dump(self.path), before)
        self.assertEqual(self.store.mutate(req("v", "pump", 1, "visit", {"amount": 1}))
                         ["record"]["revision"], "2")

    def test_concurrent_writers_on_one_revision(self):
        self.store.mutate(req("c", "pump", 0, "create", full()))
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=race_worker, args=(
            str(self.path), req(f"w-{n}", "pump", 1, "patch", {"assignee": f"a{n}"},
                                device=f"van-{n}"), False, queue)) for n in range(6)]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=60)[0] for _ in workers]
        for worker in workers:
            worker.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("conflict"), 5)
        self.assertEqual(len(self.store.pull("north", "0", 100)["events"]), 2)


class ReadTests(Base):
    def test_snapshot_is_frozen_at_its_cut(self):
        for entity in ("b", "c", "d"):
            self.store.mutate(req("c-" + entity, entity, 0, "create", full(title=entity)))
        first = self.store.snapshot("north", 1)
        self.store.mutate(req("del-c", "c", 1, "delete", {}))
        self.store.mutate(req("new-a", "a", 0, "create", full(title="urgent")))
        self.store.mutate(req("new-bb", "bb", 0, "create", full(title="urgent")))
        self.store.mutate(req("p-d", "d", 1, "patch", {"done": True}))
        second = self.store.snapshot("north", 1, first["next_cursor"])
        third = self.store.snapshot("north", 5, second["next_cursor"])
        rows = first["rows"] + second["rows"] + third["rows"]
        self.assertEqual([r["id"] for r in rows], ["b", "c", "d"])
        self.assertTrue(all(r["revision"] == "1" and not r["deleted"] for r in rows))
        self.assertEqual({first["cut"], second["cut"], third["cut"]}, {"3"})
        self.assertIsNone(third["next_cursor"])
        fresh = snapshot_all(self.store, "north")
        latest = {r["id"]: r for p in fresh for r in p["rows"]}
        self.assertTrue(latest["c"]["deleted"])
        self.assertEqual(sorted(latest), ["a", "b", "bb", "c", "d"])

    def test_snapshot_confirmations_include_history_for_page_ids_only(self):
        self.store.mutate(req("c1", "a", 0, "create", full()))
        self.store.mutate(req("c2", "b", 0, "create", full()))
        self.store.mutate(req("v1", "a", 1, "visit", {"amount": 1}, device="van-8"))
        self.store.mutate(req("o", "a", 0, "create", full(), tenant="south"))
        page = self.store.snapshot("north", 1)
        self.assertEqual(page["confirmed"], [
            {"device": "van-7", "mutation": "c1", "id": "a", "seq": "1"},
            {"device": "van-8", "mutation": "v1", "id": "a", "seq": "3"}])
        self.store.mutate(req("v2", "b", 1, "visit", {"amount": 1}))
        page2 = self.store.snapshot("north", 1, page["next_cursor"])
        self.assertEqual(page2["confirmed"],
                         [{"device": "van-7", "mutation": "c2", "id": "b", "seq": "2"}])
        empty = self.store.snapshot("west", 3)
        self.assertEqual((empty["rows"], empty["confirmed"], empty["next_cursor"]),
                         ([], [], None))

    def test_pull_pages_are_exclusive_and_frozen(self):
        self.jump(BIG)
        for n in range(5):
            self.store.mutate(req(f"c{n}", f"e{n}", 0, "create", full()))
            self.store.mutate(req(f"s{n}", f"e{n}", 0, "create", full(), tenant="south"))
        start = str(BIG + 2)
        page = self.store.pull("north", start, 2)
        self.assertEqual(page["from"], start)
        self.assertEqual([e["seq"] for e in page["events"]], [str(BIG + 3), str(BIG + 5)])
        self.assertEqual(page["after"], str(BIG + 5))
        self.assertEqual([c["mutation"] for c in page["confirmed"]], ["c1", "c2"])
        until = page["until"]
        self.store.mutate(req("late", "late", 0, "create", full()))
        seen = list(page["events"])
        while page["next_cursor"]:
            page = self.store.pull("north", start, 2, page["next_cursor"])
            self.assertEqual(page["until"], until)
            seen += page["events"]
        self.assertEqual(page["after"], until)
        self.assertEqual(len({e["seq"] for e in seen}), len(seen))
        self.assertEqual([e["id"] for e in seen], ["e1", "e2", "e3", "e4"])
        final = self.store.pull("south", until, 10)
        self.assertEqual((final["events"], final["after"], final["confirmed"]),
                         ([], final["until"], []))

    def test_invalid_cursors(self):
        self.store.mutate(req("c1", "a", 0, "create", full()))
        self.store.mutate(req("c2", "b", 0, "create", full()))
        snap = self.store.snapshot("north", 1)["next_cursor"]
        pull = self.store.pull("north", "0", 1)["next_cursor"]
        epoch = self.store.snapshot("north", 1)["epoch"]
        cases = [
            lambda: self.store.snapshot("north", 1, "!!!"),
            lambda: self.store.snapshot("north", 1, pull),
            lambda: self.store.snapshot("south", 1, snap),
            lambda: self.store.snapshot("north", 1, token({"mode": "snapshot", "tenant": "north",
                                                           "epoch": "other", "cut": "2",
                                                           "last": "a"})),
            lambda: self.store.snapshot("north", 1, token({"mode": "snapshot", "tenant": "north",
                                                           "epoch": epoch, "cut": "99",
                                                           "last": "a"})),
            lambda: self.store.pull("north", "0", 1, snap),
            lambda: self.store.pull("north", "1", 1, pull),
            lambda: self.store.pull("north", "3", 1),
            lambda: self.store.pull("north", "0", 1, token({
                "mode": "events", "tenant": "north", "epoch": epoch, "origin": "0",
                "after": "2", "until": "1"})),
        ]
        cases += [
            lambda: self.store.snapshot("north", 1, token({"mode": "snapshot", "tenant": "north",
                                                           "epoch": epoch, "cut": "2",
                                                           "last": "aa"})),
            lambda: self.store.pull("north", "0", 1, token({
                "mode": "events", "tenant": "north", "epoch": epoch, "origin": "0",
                "after": "0", "until": "2"})),
            lambda: self.store.pull("south", "0", 1, token({
                "mode": "events", "tenant": "south", "epoch": epoch, "origin": "0",
                "after": "1", "until": "2"})),
        ]
        for case in cases:
            error = self.error(case)
            self.assertEqual((error.status, error.code), (400, "invalid_cursor"))
        for bad in (0, 101, True, "5"):
            self.assertEqual(self.error(self.store.snapshot, "north", bad).code, "invalid")


class BatchTests(Base):
    def closeout(self, batch="close-1", device="van-7"):
        return {"tenant": "north", "device": device, "batch": batch, "operations": [
            op("v", "pump", 1, "visit", {"amount": 1}),
            op("d", "pump", 2, "patch", {"done": True}),
            op("x", "valve", 1, "patch", {"done": True})]}

    def setUp(self):
        super().setUp()
        self.store.mutate(req("c1", "pump", 0, "create", full()))
        self.store.mutate(req("c2", "valve", 0, "create", full()))

    def test_atomic_success_and_exact_retry(self):
        result = self.store.mutate_batch(self.closeout())
        self.assertEqual([r["record"]["revision"] for r in result["responses"]], ["2", "3", "2"])
        self.assertEqual(self.store.mutate_batch(self.closeout()), result)
        self.assertEqual(self.store.mutate(req("d", "pump", 2, "patch", {"done": True})),
                         result["responses"][1])
        changed = self.closeout()
        changed["operations"][0]["data"] = {"amount": 2}
        self.assertEqual(self.error(self.store.mutate_batch, changed).code, "idempotency_reuse")

    def test_failure_commits_nothing(self):
        before = dump(self.path)
        request = self.closeout()
        request["operations"][2]["base"] = "7"
        error = self.error(self.store.mutate_batch, request)
        self.assertEqual((error.code, error.detail["index"]), ("conflict", 2))
        self.assertEqual(error.detail["current"]["id"], "valve")
        self.assertEqual(dump(self.path), before)
        self.assertEqual(len(self.store.mutate_batch(self.closeout())["responses"]), 3)

    def test_fault_in_later_operation_rolls_back_earlier_ones(self):
        before = dump(self.path)
        calls = []

        def hook(stage):
            calls.append(stage)
            if len(calls) == 5:
                raise RuntimeError("chaos")
        with self.assertRaises(RuntimeError):
            Store(self.path, fault=hook).mutate_batch(self.closeout())
        self.assertEqual(dump(self.path), before)

    def test_batch_conflict_for_independent_committed_operation(self):
        self.store.mutate(req("v", "pump", 1, "visit", {"amount": 1}))
        error = self.error(self.store.mutate_batch, self.closeout())
        self.assertEqual((error.status, error.code, error.detail["index"]),
                         (409, "batch_conflict", 0))

    def test_invalid_envelopes(self):
        good = self.closeout()
        cases = [dict(good, operations=[]), dict(good, operations={}),
                 dict(good, operations=[good["operations"][0]] * 2),
                 dict(good, operations=[dict(good["operations"][0], tenant="north")]),
                 dict(good, extra=1), dict(good, batch=""),
                 dict(good, operations=[op(f"m{n}", "pump", 1, "visit", {"amount": 1})
                                        for n in range(17)])]
        for case in cases:
            self.assertEqual(self.error(self.store.mutate_batch, case).code, "invalid")

    def test_racing_processes_share_one_receipt(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=race_worker,
                                   args=(str(self.path), self.closeout(), True, queue))
                   for _ in range(5)]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=60) for _ in workers]
        for worker in workers:
            worker.join()
        self.assertEqual({r[0] for r in results}, {"ok"})
        self.assertEqual(len({r[1] for r in results}), 1)
        self.assertEqual(len(self.store.pull("north", "0", 100)["events"]), 5)


class RetentionTests(Base):
    def setUp(self):
        super().setUp()
        self.jump(BIG)
        s = self.store
        s.mutate(req("c-pump", "pump", 0, "create", full(title="Pump")))     # +1
        s.mutate(req("c-valve", "valve", 0, "create", full(title="Valve")))  # +2
        s.mutate(req("v-pump", "pump", 1, "visit", {"amount": 1}))           # +3
        s.mutate(req("d-valve", "valve", 1, "delete", {}))                   # +4
        s.mutate(req("c-south", "pump", 0, "create", full(), tenant="south"))  # +5

    def test_full_prune_keeps_baseline_and_sequence(self):
        documents = dump(self.path)["documents"]
        result = self.store.compact(str(BIG + 5))
        self.assertEqual(result, {"through": str(BIG + 5), "pruned": 5})
        self.assertEqual(self.store.compact(str(BIG + 5))["pruned"], 0)
        self.assertEqual(dump(self.path)["documents"], documents)
        page = self.store.snapshot("north", 10)
        self.assertEqual(page["cut"], str(BIG + 5))
        rows = {r["id"]: r for r in page["rows"]}
        self.assertTrue(rows["valve"]["deleted"])
        self.assertEqual(rows["pump"]["body"]["visits"], 1)
        self.assertEqual([c["mutation"] for c in page["confirmed"]],
                         ["c-pump", "c-valve", "v-pump", "d-valve"])
        restarted = Store(self.path)
        conflict = self.error(restarted.mutate, req("x", "valve", 2, "patch", {"done": True}))
        self.assertEqual(conflict.detail["current"]["revision"], "2")
        self.assertEqual(self.error(restarted.mutate,
                                    req("y", "valve", 0, "create", full())).code, "conflict")
        back = restarted.mutate(req("r", "valve", 2, "restore", {}))
        self.assertEqual(back["record"]["seq"], str(BIG + 6))
        self.assertEqual(restarted.mutate(req("v-pump", "pump", 1, "visit", {"amount": 1})),
                         json.loads(json.dumps(restarted.mutate(
                             req("v-pump", "pump", 1, "visit", {"amount": 1})))))

    def test_boundaries_and_reads_after_compaction(self):
        self.assertEqual(self.error(self.store.compact, str(BIG + 9)).code, "invalid")
        self.assertEqual(self.error(self.store.compact, "007").code, "invalid")
        self.store.compact(str(BIG + 2))
        self.assertEqual(self.error(self.store.compact, str(BIG + 1)).code, "invalid")
        error = self.error(self.store.pull, "north", str(BIG + 1), 10)
        self.assertEqual((error.status, error.code, error.detail["floor"]),
                         (410, "resnapshot_required", str(BIG + 2)))
        page = self.store.pull("north", str(BIG + 2), 10)
        self.assertEqual([e["seq"] for e in page["events"]], [str(BIG + 3), str(BIG + 4)])

    def test_open_snapshot_and_pull_continuations(self):
        snap = self.store.snapshot("north", 1)
        pull = self.store.pull("north", str(BIG), 1)
        self.assertEqual(pull["after"], str(BIG + 1))
        self.store.compact(str(BIG + 1))
        resumed = self.store.pull("north", str(BIG), 1, pull["next_cursor"])
        self.assertEqual((resumed["from"], resumed["until"]), (str(BIG + 1), pull["until"]))
        self.assertEqual(self.store.snapshot("north", 1, snap["next_cursor"])["rows"][0]["id"],
                         "valve")
        self.store.mutate(req("later", "later", 0, "create", full()))
        self.store.compact(str(BIG + 6))
        for call in (lambda: self.store.pull("north", str(BIG), 1, resumed["next_cursor"]),
                     lambda: self.store.snapshot("north", 1, snap["next_cursor"])):
            error = self.error(call)
            self.assertEqual((error.status, error.code), (410, "resnapshot_required"))
        error = self.error(self.store.pull, "north", str(BIG), 1, "garbage!")
        self.assertEqual(error.code, "invalid_cursor")

    def test_compaction_faults_roll_back(self):
        before = dump(self.path)
        for stage in ("after_anchor", "after_prune"):
            def hook(name, stage=stage):
                if name == stage:
                    raise RuntimeError("chaos")
            with self.assertRaises(RuntimeError):
                Store(self.path, fault=hook).compact(str(BIG + 3))
            self.assertEqual(dump(self.path), before)

    def test_repair_uses_anchors(self):
        self.store.compact(str(BIG + 4))
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM documents WHERE id='pump' AND tenant='north'")
            db.execute("UPDATE documents SET deleted=0 WHERE id='valve'")
            db.execute("INSERT INTO documents VALUES ('north','ghost',1,'{}',0)")
        before = dump(self.path)
        self.assertEqual(self.store.repair_projection(), {"repaired": 3})
        self.assertEqual(self.store.repair_projection(), {"repaired": 0})
        after = dump(self.path)
        for key in ("events", "receipts", "batches", "anchors", "meta", "retention", "sequence"):
            self.assertEqual(after[key], before[key], key)
        docs = {(t, i): (rev, deleted) for t, i, rev, _, deleted in after["documents"]}
        self.assertEqual(docs, {("north", "pump"): (2, 0), ("north", "valve"): (2, 1),
                                ("south", "pump"): (1, 0)})


class ToolTests(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=60)

    def test_seeded_incident_repair_and_compact_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incident.sqlite"
            self.assertEqual(self.run_tool("tools/seed.py", "--db", str(path)).returncode, 0)
            before = dump(path)
            result = self.run_tool("tools/repair.py", "--db", str(path))
            self.assertEqual((result.returncode, json.loads(result.stdout)), (0, {"repaired": 4}))
            after = dump(path)
            for key in ("events", "receipts", "meta", "sequence"):
                self.assertEqual(after[key], before[key])
            self.assertEqual([row[:3] + row[4:] for row in after["documents"]], [
                ("north", "pump-17", 43, 0), ("north", "valve-4", 2, 1), ("south", "pump-17", 6, 0)])
            result = self.run_tool("tools/compact.py", "--db", str(path), "--through",
                                   "9007199254740997")
            self.assertEqual(json.loads(result.stdout),
                             {"through": "9007199254740997", "pruned": 5})
            result = self.run_tool("tools/compact.py", "--db", str(path), "--through", "1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid", result.stderr)
            self.assertNotEqual(self.run_tool("tools/repair.py", "--db",
                                              str(Path(directory) / "none")).returncode, 0)
            store = Store(path)
            rows = {r["id"]: r for r in store.snapshot("north", 10)["rows"]}
            self.assertEqual(rows["pump-17"]["revision"], "43")
            self.assertTrue(rows["valve-4"]["deleted"])
            self.assertEqual(store.mutate(req("m-9", "pump-17", 43, "visit", {"amount": 1}))
                             ["record"]["seq"], "9007199254740999")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "server.http", "--db",
             str(Path(self.directory.name) / "h.sqlite"), "--port", str(self.port)],
            cwd=ROOT, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if self.call("GET", "/health")[0] == 200:
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
            None if payload is None else json.dumps(payload).encode())
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_routes_and_errors(self):
        status, body = self.call("POST", "/mutate", req("ü", "泵", 0, "create",
                                                        full(title="Prüfung")))
        self.assertEqual((status, body["record"]["body"]["title"]), (200, "Prüfung"))
        status, body = self.call("POST", "/mutate", req("x", "泵", 9, "patch", {}))
        self.assertEqual((status, body["code"], body["detail"]["current"]["revision"]),
                         (409, "conflict", "1"))
        self.assertEqual(self.call("POST", "/mutate", raw=b'{"tenant":NaN}')[0], 400)
        self.assertEqual(self.call("POST", "/batch", raw=b"[1]")[1]["code"], "invalid")
        query = urllib.parse.urlencode({"tenant": "north", "limit": "5"})
        status, body = self.call("GET", f"/snapshot?{query}")
        self.assertEqual((status, body["rows"][0]["id"], body["confirmed"][0]["mutation"]),
                         (200, "泵", "ü"))
        status, body = self.call("GET", f"/pull?{query}&checkpoint=0")
        self.assertEqual((status, body["after"]), (200, "1"))
        self.assertEqual(self.call("GET", f"/pull?{query}&checkpoint=7")[1]["code"],
                         "invalid_cursor")
        self.assertEqual(self.call("GET", "/snapshot?tenant=north&limit=x")[0], 400)
        self.assertEqual(self.call("GET", "/nowhere")[0], 404)


if __name__ == "__main__":
    unittest.main()
