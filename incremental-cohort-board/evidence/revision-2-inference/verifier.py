"""Black-box differential checks. Expected results use full SQLite queries."""
import hashlib
import json
import os
import random
import sqlite3
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

APP = Path(os.environ.get("BOARD_APP", "/app")).resolve()
LOGS = Path(os.environ.get("BOARD_LOGS", "/logs/verifier")).resolve()
TESTS = Path(__file__).parent
RELEASE = int(os.environ.get("BOARD_RELEASE", "4"))
sys.path.insert(0, str(APP))

import maintainer
from runtime import FIELDS, MODES, Store

ACTIVE = MODES[:RELEASE]
COLUMNS = (
    "mode", "day", "segment", "band", "row_count", "amount_count",
    "total_cents", "account_count", "min_cents", "max_cents",
)
WORK = []
ORIGINAL_BOOTSTRAP = maintainer.bootstrap
ORIGINAL_MAINTAIN = maintainer.maintain


def authorize(action, first, second, database, trigger):
    if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
                  sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
                  sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_CREATE_TRIGGER,
                  sqlite3.SQLITE_CREATE_TEMP_TRIGGER):
        return sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                  sqlite3.SQLITE_DELETE):
        if first not in ("rollup", "sqlite_master", "sqlite_temp_master"):
            if not first.startswith("aux_"):
                return sqlite3.SQLITE_DENY
    if action in (
        sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_VIEW, sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_DROP_VIEW, sqlite3.SQLITE_DROP_TEMP_VIEW,
    ):
        if not (first.startswith("aux_") or (
            first.startswith("sqlite_autoindex_aux_")
            and second and second.startswith("aux_")
        )):
            return sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_CREATE_VTABLE,
                  sqlite3.SQLITE_DROP_VTABLE):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def guarded(function):
    def call(db, *args):
        db.set_authorizer(authorize)
        try:
            return function(db, *args)
        finally:
            db.set_authorizer(None)
    return call


maintainer.bootstrap = guarded(ORIGINAL_BOOTSTRAP)
maintainer.maintain = guarded(ORIGINAL_MAINTAIN)


def put(table, row_id, **values):
    return {"table": table, "id": row_id, "row": {"id": row_id, **values}}


def delete(table, row_id):
    return {"table": table, "id": row_id, "row": None}


def normalized(rows):
    return sorted(
        (tuple(row[column] for column in COLUMNS) for row in rows),
        key=lambda row: json.dumps(row, ensure_ascii=True),
    )


def reference(db, modes):
    if "household" in modes:
        parent = {}

        def find(account):
            parent.setdefault(account, account)
            node = account
            while parent[node] != node:
                node = parent[node]
            while parent[account] != account:
                next_account = parent[account]
                parent[account] = node
                account = next_account
            return node

        for left, right in db.execute(
            "SELECT left_account,right_account FROM links"
        ):
            first, second = find(left), find(right)
            if first != second:
                parent[max(first, second)] = min(first, second)
        db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS reference_households "
            "(account TEXT PRIMARY KEY, representative TEXT NOT NULL)"
        )
        db.execute("DELETE FROM reference_households")
        db.executemany(
            "INSERT INTO reference_households VALUES (?,?)",
            ((row[0], find(row[0])) for row in db.execute(
                "SELECT DISTINCT account FROM orders"
            ).fetchall()),
        )
    rows = []
    for mode in modes:
        tag_join = "JOIN" if mode == "inner" else "LEFT JOIN"
        rated = mode in ("rated", "household")
        band = "r.band" if rated else "NULL"
        rate_join = (
            "LEFT JOIN rates r ON t.segment=r.segment" if rated else ""
        )
        identity = "h.representative" if mode == "household" else "o.account"
        household_join = (
            "JOIN reference_households h ON h.account=o.account"
            if mode == "household" else ""
        )
        sql = f"""
            SELECT ? AS mode, o.day AS day, t.segment AS segment,
                   {band} AS band, COUNT(*) AS row_count,
                   COUNT(o.cents) AS amount_count, SUM(o.cents) AS total_cents,
                   COUNT(DISTINCT {identity}) AS account_count,
                   MIN(o.cents) AS min_cents, MAX(o.cents) AS max_cents
            FROM orders o {tag_join} tags t ON o.account=t.account
            {rate_join} {household_join}
            GROUP BY o.day,t.segment,{band}
        """
        rows.extend(dict(row) for row in db.execute(sql, (mode,)))
    return normalized(rows)


def apply_reference(db, mutations):
    for mutation in mutations:
        table, row_id, row = (
            mutation["table"], mutation["id"], mutation["row"]
        )
        if row is None:
            db.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
        else:
            fields = FIELDS[table]
            db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES "
                f"({','.join('?' for _ in fields)})",
                tuple(row[f] for f in fields),
            )


class Fixture:
    def __init__(self, modes=ACTIVE, initial=()):
        self.folder = tempfile.TemporaryDirectory(prefix="cohort-check-")
        self.path = Path(self.folder.name) / "board.sqlite"
        self.store = Store(self.path)
        self.ref = sqlite3.connect(":memory:")
        self.ref.row_factory = sqlite3.Row
        self.ref.executescript((APP / "schema.sql").read_text())
        apply_reference(self.ref, initial)
        self.store.db.execute("BEGIN")
        apply_reference(self.store.db, initial)
        self.store.db.execute("COMMIT")
        self.store.upgrade(modes)
        self.counter = 0

    def close(self):
        self.store.close()
        self.ref.close()
        self.folder.cleanup()

    def reopen(self):
        self.store.close()
        self.store = Store(self.path)

    def check(self):
        actual = normalized(self.store.snapshot())
        expected = reference(self.ref, self.store.modes)
        if actual != expected:
            missing = [row for row in expected if row not in actual][:5]
            extra = [row for row in actual if row not in expected][:5]
            raise AssertionError(
                f"Projection mismatch after batch {self.counter}; "
                f"missing/wrong={missing!r}; extra/wrong={extra!r}; "
                f"row counts actual={len(actual)} expected={len(expected)}"
            )
        for table in FIELDS:
            actual_source = [
                tuple(row) for row in self.store.db.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                )
            ]
            expected_source = [
                tuple(row) for row in self.ref.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                )
            ]
            if actual_source != expected_source:
                raise AssertionError(f"Source data changed unexpectedly: {table}")

    def apply(self, mutations, *, batch_id=None, budget=None):
        self.counter += 1
        ticks = 0

        def progress():
            nonlocal ticks
            ticks += 1
            return int(ticks > budget) if budget is not None else 0

        if budget is not None:
            self.store.db.set_progress_handler(progress, 1)
        try:
            self.store.apply(batch_id or f"batch-{self.counter}", mutations)
        finally:
            if budget is not None:
                self.store.db.set_progress_handler(None, 0)
                WORK.append({"batch": batch_id, "vm_instructions": ticks,
                             "limit": budget, "release": RELEASE})
        apply_reference(self.ref, mutations)
        self.check()


class ProjectionTests(unittest.TestCase):
    def fixture(self, *args, **kwargs):
        fixture = Fixture(*args, **kwargs)
        self.addCleanup(fixture.close)
        return fixture

    def seed(self):
        return [
            put("orders", "o1", account="a", day="day", cents=10),
            put("orders", "o2", account="a", day="day", cents=None),
            put("orders", "o3", account="b", day="day", cents=-10),
            put("orders", "o4", account="c", day=None, cents=0),
            put("orders", "o5", account="d", day=None, cents=None),
            put("tags", "t1", account="a", segment="x"),
            put("tags", "t2", account="a", segment="x"),
            put("tags", "t3", account="b", segment="x"),
            put("tags", "t4", account="c", segment=None),
            put("tags", "t5", account="c", segment=None),
            put("rates", "r1", segment="x", band="band"),
            put("rates", "r2", segment="x", band="band"),
            put("rates", "r3", segment=None, band="not-a-match"),
        ]

    def test_functional_day_account_rekeys_and_deletes(self):
        f = self.fixture()
        f.apply(self.seed())
        f.apply([
            put("orders", "o1", account="b", day=None, cents=15),
            delete("orders", "o2"),
            put("tags", "t3", account="c", segment="y"),
        ])
        f.apply([delete("tags", "t1"), delete("tags", "t2")])
        f.apply([delete("orders", "o3"), delete("orders", "o4"),
                 delete("orders", "o5"), delete("orders", "o1")])
        self.assertEqual(f.store.snapshot(), [])

    def test_functional_bags_distinct_and_retractable_extrema(self):
        f = self.fixture(initial=self.seed())
        f.check()
        f.apply([put("orders", "o6", account="b", day="day", cents=10)])
        f.apply([delete("orders", "o1")])
        f.apply([delete("orders", "o3")])
        f.apply([put("orders", "o6", account="b", day="day", cents=None)])
        f.apply([put("orders", "o2", account="a", day="day", cents=0)])
        f.apply([delete("tags", "t2")])

    def test_functional_collision_free_group_keys(self):
        f = self.fixture()
        keys = [None, "", "null", "None", "[]", '["x",null]', "a|b",
                "a\x1fb", "__NULL__", "0", "001", "1", "\u03bb"]
        changes = []
        for index, key in enumerate(keys):
            account = f"a{index}"
            changes.extend([
                put("orders", f"o{index}", account=account, day=key,
                    cents=None if index % 3 == 0 else index - 4),
                put("tags", f"t{index}", account=account, segment=key),
                put("rates", f"r{index}", segment=key,
                    band=keys[(index + 2) % len(keys)]),
            ])
        f.apply(changes)
        f.reopen()
        f.apply([delete("orders", f"o{i}") for i in range(0, len(keys), 2)])
        f.apply([put("tags", "t1", account="a12", segment=None)])

    @unittest.skipIf(RELEASE < 2, "outer not released")
    def test_functional_left_join_support_transitions(self):
        f = self.fixture(initial=[
            put("orders", "o", account="a", day=None, cents=7),
            put("orders", "p", account="b", day=None, cents=None),
        ])
        f.check()
        f.apply([put("tags", "t", account="a", segment=None)])
        f.apply([put("tags", "u", account="a", segment=None)])
        f.apply([delete("tags", "t")])
        f.apply([delete("tags", "u")])
        f.apply([put("tags", "v", account="a", segment="")])
        f.apply([put("tags", "v", account="b", segment="")])

    @unittest.skipIf(RELEASE < 3, "rated not released")
    def test_functional_rate_fanout_and_null_nonmatches(self):
        f = self.fixture(initial=self.seed())
        f.check()
        f.apply([put("rates", "r1", segment="x", band=None)])
        f.apply([put("rates", "r2", segment="y", band=None)])
        f.apply([delete("rates", "r1")])
        f.apply([put("rates", "r3", segment=None, band="changed-no-match")])
        f.apply([put("tags", "t4", account="c", segment="y")])
        f.apply([delete("rates", "r2")])

    def test_functional_transaction_cross_terms(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("orders", "o1", account="z", day=None, cents=-5),
            put("orders", "o3", account="a", day="other", cents=33),
            put("tags", "t1", account="b", segment="y"),
            put("tags", "t2", account="z", segment="z"),
            put("tags", "t3", account="a", segment="z"),
            put("rates", "r1", segment="z", band=None),
            put("rates", "r2", segment="y", band="new"),
        ])
        f.reopen()
        f.apply([
            delete("orders", "o1"), delete("tags", "t1"),
            put("tags", "t2", account="c", segment=None),
            delete("rates", "r1"),
            put("rates", "r2", segment="z", band="last"),
        ])

    def test_robustness_coalesced_writes_and_change_order(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("orders", "o1", account="q", day="discard", cents=999),
            delete("orders", "o1"),
            put("orders", "o1", account="b", day=None, cents=-3),
            delete("tags", "t1"),
            put("tags", "t1", account="b", segment="new"),
            put("rates", "r1", segment="new", band="new"),
            delete("orders", "absent"),
        ])
        original = maintainer.maintain
        try:
            maintainer.maintain = lambda db, modes, changes: original(
                db, modes, list(reversed(changes))
            )
            f.apply([
                put("orders", "o1", account="a", day="day", cents=10),
                put("tags", "t1", account="a", segment="x"),
                put("rates", "r1", segment="x", band="band"),
            ])
        finally:
            maintainer.maintain = original
        f.apply([])
        f.apply([delete("orders", "absent")])

    def test_robustness_rollback_retry_reopen(self):
        f = self.fixture(initial=self.seed())
        changes = [
            put("orders", "o1", account="b", day=None, cents=-900),
            delete("tags", "t1"),
            put("rates", "r1", segment="z", band=None),
        ]
        with self.assertRaisesRegex(RuntimeError, "Injected power loss"):
            f.store.apply("recover", changes, fail_after_hook=True)
        f.check()
        f.reopen()
        f.apply(changes, batch_id="recover")
        before = normalized(f.store.snapshot())
        self.assertFalse(f.store.apply("recover", changes))
        self.assertEqual(before, normalized(f.store.snapshot()))
        with self.assertRaisesRegex(ValueError, "different payload"):
            f.store.apply("recover", [])
        f.check()
        f.reopen()
        f.apply([delete("orders", "o1")])

    def test_robustness_upgrade_from_populated_prior_release(self):
        f = self.fixture(modes=("inner",), initial=self.seed())
        f.check()
        for release in range(2, RELEASE + 1):
            f.store.upgrade(MODES[:release])
            f.check()
            f.reopen()
            f.apply([put("orders", "o1", account="d", day=None,
                         cents=release * -101)])

    def test_robustness_generated_state_machine(self):
        for seed in (171, 908):
            with self.subTest(seed=seed):
                f = self.fixture()
                rng = random.Random(seed)
                values = [None, "", "x", "y", "null", "x|y", "__NULL__"]
                for batch in range(140):
                    changes = []
                    for _ in range(rng.randint(0, 8)):
                        tables = tuple(FIELDS) if RELEASE >= 4 else (
                            "orders", "tags", "rates"
                        )
                        table = rng.choice(tables)
                        row_id = f"{table}/{rng.randrange(16)}"
                        if rng.random() < .26:
                            changes.append(delete(table, row_id))
                        elif table == "orders":
                            changes.append(put(
                                table, row_id, account=rng.choice(
                                    ["", "a", "b", "001", "1", "null"]
                                ), day=rng.choice(values),
                                cents=rng.choice([None, None, -19, -1, 0, 1, 19]),
                            ))
                        elif table == "tags":
                            changes.append(put(
                                table, row_id, account=rng.choice(
                                    ["", "a", "b", "001", "1", "null"]
                                ), segment=rng.choice(values),
                            ))
                        elif table == "rates":
                            changes.append(put(
                                table, row_id, segment=rng.choice(values),
                                band=rng.choice(values),
                            ))
                        else:
                            changes.append(put(
                                table, row_id,
                                left_account=rng.choice(
                                    ["", "a", "b", "001", "1", "null", "dormant"]
                                ),
                                right_account=rng.choice(
                                    ["", "a", "b", "001", "1", "null", "bridge"]
                                ),
                            ))
                    f.apply(changes)
                    if batch % 17 == 0:
                        f.reopen()
                        f.check()

    def test_constraint_incremental_locality(self):
        initial = []
        for index in range(80000):
            account = f"archive/{index}"
            initial.extend([
                put("orders", f"archive/o{index}", account=account,
                    day="busy", cents=(index % 101) - 50),
                put("tags", f"archive/t{index}", account=account, segment="bulk"),
            ])
        initial.extend([
            put("orders", "target/o", account="target", day="busy", cents=501),
            put("orders", "target/null", account="target", day="busy", cents=None),
            put("tags", "target/t", account="target", segment="bulk"),
            put("rates", "bulk/r", segment="bulk", band="base"),
            put("rates", "rare/r", segment="rare", band=None),
        ])
        if RELEASE >= 4:
            initial.extend([
                put("orders", "shadow/o", account="shadow", day="busy", cents=8),
                put("tags", "shadow/t", account="shadow", segment="bulk"),
                put("links", "identity/one",
                    left_account="target", right_account="dormant"),
                put("links", "identity/two",
                    left_account="dormant", right_account="shadow"),
            ])
        f = self.fixture(initial=initial)
        f.check()
        f.apply([put("orders", "target/o", account="target", day="busy", cents=-501)],
                batch_id="local/order-extrema", budget=300000)
        f.reopen()
        f.apply([delete("tags", "target/t")],
                batch_id="local/delete-last-tag", budget=300000)
        f.apply([put("tags", "target/t", account="target", segment="rare")],
                batch_id="local/insert-first-tag", budget=300000)
        f.reopen()
        f.apply([put("rates", "rare/r", segment="rare", band="rare-band")],
                batch_id="local/sparse-rate", budget=300000)
        f.apply([
            put("orders", "target/o", account="target", day=None, cents=None),
            put("tags", "target/t", account="target", segment="new"),
            put("rates", "rare/r", segment="new", band="new-band"),
        ], batch_id="local/three-table-rekey", budget=300000)
        f.apply([], batch_id="local/noop", budget=300000)
        if RELEASE >= 4:
            f.apply([delete("links", "identity/one")],
                    batch_id="local/household-split", budget=300000)
            f.reopen()
            f.apply([
                put("links", "identity/one",
                    left_account="target", right_account="shadow"),
                put("tags", "target/t", account="target", segment="bulk"),
                put("orders", "target/o", account="target", day="busy", cents=3),
            ], batch_id="local/household-merge-and-reclassify", budget=300000)
            f.apply([
                put("links", "identity/two", left_account="", right_account="shadow"),
                delete("links", "identity/one"),
                put("links", "identity/three",
                    left_account="target", right_account="dormant"),
            ], batch_id="local/household-split-rekey-merge", budget=300000)

    @unittest.skipIf(RELEASE < 4, "household not released")
    def test_functional_household_parallel_cycle_and_dormant_bridge(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("links", "ab1", left_account="a", right_account="bridge"),
            put("links", "ab2", left_account="bridge", right_account="b"),
            put("links", "parallel", left_account="b", right_account="bridge"),
            put("links", "self", left_account="c", right_account="c"),
        ])
        f.apply([delete("links", "ab2")])
        f.apply([delete("links", "parallel")])
        f.apply([
            put("links", "cycle1", left_account="a", right_account="b"),
            put("links", "cycle2", left_account="b", right_account="c"),
            put("links", "cycle3", left_account="c", right_account="a"),
        ])
        f.apply([delete("links", "cycle1")])
        f.apply([delete("links", "cycle2")])
        f.reopen()
        f.apply([delete("links", "ab1"), delete("links", "cycle3")])

    @unittest.skipIf(RELEASE < 4, "household not released")
    def test_functional_household_membership_is_per_group(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("links", "ab", left_account="a", right_account="b"),
            put("links", "bc", left_account="b", right_account="c"),
        ])
        f.apply([
            delete("tags", "t1"),
            put("tags", "t2", account="a", segment="other"),
            put("tags", "t4", account="c", segment="x"),
        ])
        f.apply([delete("orders", "o3")])
        f.apply([delete("links", "bc")])
        f.apply([
            put("orders", "o3", account="b", day="day", cents=-10),
            put("orders", "o4", account="c", day="day", cents=0),
        ])
        f.apply([put("links", "bc", left_account="b", right_account="c")])

    @unittest.skipIf(RELEASE < 4, "household not released")
    def test_functional_household_simultaneous_repartition_and_sources(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("links", "ab", left_account="a", right_account="b"),
            put("links", "cd", left_account="c", right_account="d"),
        ])
        f.apply([
            put("links", "ab", left_account="a", right_account="c"),
            delete("links", "cd"),
            put("links", "bd", left_account="b", right_account="d"),
            put("orders", "o1", account="c", day=None, cents=-91),
            put("tags", "t4", account="c", segment="x"),
            put("tags", "t3", account="b", segment=None),
            put("rates", "r1", segment="x", band=None),
        ])
        f.reopen()
        f.apply([
            delete("links", "ab"), delete("links", "bd"),
            put("links", "new", left_account="", right_account="a"),
        ])
        f.apply([
            put("links", "new", left_account="", right_account="b"),
            put("orders", "fresh", account="", day="day", cents=None),
            put("tags", "fresh", account="", segment="x"),
        ])

    @unittest.skipIf(RELEASE < 4, "household not released")
    def test_robustness_household_rollback_then_split(self):
        f = self.fixture(initial=self.seed())
        f.apply([
            put("links", "ab", left_account="a", right_account="b"),
            put("links", "bc", left_account="b", right_account="c"),
        ])
        changes = [
            delete("links", "ab"),
            put("links", "bc", left_account="b", right_account="d"),
            put("tags", "t2", account="a", segment="new"),
        ]
        with self.assertRaisesRegex(RuntimeError, "Injected power loss"):
            f.store.apply("alias-recovery", changes, fail_after_hook=True)
        f.check()
        f.reopen()
        f.apply(changes, batch_id="alias-recovery")
        f.apply([put("links", "ab", left_account="a", right_account="b")])

    def test_constraint_other_group_cardinality(self):
        initial = []
        for index in range(12000):
            account = f"separate/{index}"
            initial.extend([
                put("orders", f"o{index}", account=account,
                    day=f"d{index}", cents=index),
                put("tags", f"t{index}", account=account, segment=f"s{index}"),
            ])
        f = self.fixture(initial=initial)
        f.apply([put("orders", "o1", account="separate/1", day=None, cents=-1)],
                batch_id="local/many-groups", budget=300000)
        f.reopen()
        f.apply([delete("tags", "t1")],
                batch_id="local/many-groups-reopen", budget=300000)

    def test_constraint_immutable_host_and_inputs(self):
        manifest = json.loads((TESTS / "immutable.json").read_text())
        for relative, expected in manifest.items():
            with self.subTest(path=relative):
                actual = hashlib.sha256((APP / relative).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, f"Protected file edited: {relative}")

    def test_artifact_durable_incident_state(self):
        path = APP / "state" / "demo.sqlite"
        self.assertTrue(path.is_file(), "Missing durable incident replay database")
        report = APP / "REPAIR_REPORT.md"
        self.assertTrue(report.is_file(), "Missing engineering handover")
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        ref = sqlite3.connect(":memory:")
        ref.row_factory = sqlite3.Row
        ref.executescript((APP / "schema.sql").read_text())
        self.addCleanup(ref.close)
        wanted_receipts = {}
        for release in range(1, RELEASE + 1):
            batches = json.loads(
                (APP / "incidents" / f"release-{release}.json").read_text()
            )
            for batch in batches:
                apply_reference(ref, batch["mutations"])
                wanted_receipts[batch["id"]] = json.dumps(
                    batch["mutations"], sort_keys=True, separators=(",", ":")
                )
        self.assertEqual(
            dict(db.execute("SELECT id,payload FROM receipts")), wanted_receipts,
            "Incident receipts must be retained, not reconstructed incompletely",
        )
        for table in FIELDS:
            actual = [tuple(row) for row in db.execute(
                f"SELECT * FROM {table} ORDER BY id"
            )]
            expected = [tuple(row) for row in ref.execute(
                f"SELECT * FROM {table} ORDER BY id"
            )]
            self.assertEqual(actual, expected, f"Incident sources differ: {table}")
        modes = json.loads(db.execute(
            "SELECT value FROM settings WHERE key='modes'"
        ).fetchone()[0])
        self.assertEqual(tuple(modes), ACTIVE)
        self.assertEqual(
            normalized([dict(row) for row in db.execute("SELECT * FROM rollup")]),
            reference(ref, ACTIVE),
        )
        # Reopen without bootstrap, then update the submitted auxiliary state.
        fixture = self.fixture(initial=[])
        fixture.store.close()
        target = sqlite3.connect(fixture.path)
        try:
            db.backup(target)
        finally:
            target.close()
        fixture.store = Store(fixture.path)
        for table in FIELDS:
            fixture.ref.execute(f"DELETE FROM {table}")
            fields = FIELDS[table]
            fixture.ref.executemany(
                f"INSERT INTO {table} VALUES ({','.join('?' for _ in fields)})",
                [tuple(row) for row in ref.execute(f"SELECT * FROM {table}")],
            )
        fixture.check()
        fixture.apply([
            put("orders", "o-100", account="audit", day=None, cents=-77),
            put("tags", "audit/t", account="audit", segment="trade"),
            put("rates", "audit/r", segment="trade", band=None),
        ])


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records[test.id()] = {"status": "passed"}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records[test.id()] = {
            "status": "failed", "detail": self._exc_info_to_string(err, test)
        }

    def addError(self, test, err):
        super().addError(test, err)
        self.records[test.id()] = {
            "status": "error", "detail": self._exc_info_to_string(err, test)
        }

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records[test.id()] = {"status": "skipped", "reason": reason}

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.records[test.id()] = {
                "status": "failed", "detail": self._exc_info_to_string(err, test)
            }


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProjectionTests)
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=RecordingResult
    ).run(suite)
    categories = {
        "functional_correctness": "test_functional_",
        "constraint_satisfaction": "test_constraint_",
        "robustness": "test_robustness_",
        "artifact_quality": "test_artifact_",
    }
    reward = {"overall": float(result.wasSuccessful())}
    for key, prefix in categories.items():
        relevant = [
            record for name, record in result.records.items()
            if name.split(".")[-1].startswith(prefix)
            and record["status"] != "skipped"
        ]
        reward[key] = (
            sum(record["status"] == "passed" for record in relevant) / len(relevant)
            if relevant else 0.0
        )
    (LOGS / "checks.json").write_text(json.dumps({
        "release": RELEASE, "tests": result.records, "work": WORK,
        "tests_run": result.testsRun,
    }, indent=2))
    (LOGS / "reward.json").write_text(json.dumps(reward, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
