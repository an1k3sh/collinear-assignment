"""Regression checks for the incremental `inner` and `outer` projections."""
import random
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from runtime import Store

REFERENCE_TEMPLATE = """
SELECT '{mode}', o.day, t.segment, NULL,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o {join} tags t ON o.account=t.account
GROUP BY o.day, t.segment
"""
JOINS = {"inner": "JOIN", "outer": "LEFT JOIN"}
REFERENCE = REFERENCE_TEMPLATE.format(mode="inner", join="JOIN")


def reference(db, modes):
    rows = Counter()
    for mode in modes:
        rows += bag(db.execute(
            REFERENCE_TEMPLATE.format(mode=mode, join=JOINS[mode])))
    return rows
COLS = ("mode", "day", "segment", "band", "row_count", "amount_count",
        "total_cents", "account_count", "min_cents", "max_cents")
BUDGET = 300_000


def order(oid, account, day, cents):
    return {"table": "orders", "id": oid,
            "row": {"id": oid, "account": account, "day": day, "cents": cents}}


def tag(tid, account, segment):
    return {"table": "tags", "id": tid,
            "row": {"id": tid, "account": account, "segment": segment}}


def rate(rid, segment, band):
    return {"table": "rates", "id": rid,
            "row": {"id": rid, "segment": segment, "band": band}}


def delete(table, rid):
    return {"table": table, "id": rid, "row": None}


def bag(rows):
    return Counter(tuple(r) for r in rows)


class Base(unittest.TestCase):
    MODES = ("inner",)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "board.sqlite"
        self.store = Store(self.path)
        self.store.upgrade(self.MODES)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def reopen(self):
        self.store.close()
        self.store = Store(self.path)

    def assertMatchesReference(self):
        db = self.store.db
        expected = reference(db, self.store.modes)
        actual = bag(
            tuple(r[c] for c in COLS) for r in self.store.snapshot()
        )
        self.assertEqual(actual, expected)
        # Exactly one row per group.
        keys = Counter((r["mode"], r["day"], r["segment"], r["band"])
                       for r in self.store.snapshot())
        self.assertTrue(all(v == 1 for v in keys.values()), keys)

    def assertMatchesBootstrap(self):
        """Incremental aux state must equal a fresh rebuild."""
        db = self.store.db
        before_cells = bag(db.execute(
            "SELECT mode, account, day, segment, band, n, c, s, mn, mx "
            "FROM aux_cell"))
        before_rollup = bag(db.execute("SELECT * FROM rollup"))
        import maintainer
        db.execute("SAVEPOINT check_rebuild")
        maintainer.bootstrap(db, self.store.modes)
        after_cells = bag(db.execute(
            "SELECT mode, account, day, segment, band, n, c, s, mn, mx "
            "FROM aux_cell"))
        after_rollup = bag(db.execute("SELECT * FROM rollup"))
        db.execute("ROLLBACK TO check_rebuild")
        db.execute("RELEASE check_rebuild")
        self.assertEqual(before_cells, after_cells)
        self.assertEqual(before_rollup, after_rollup)


class Scenarios(Base):
    def test_release1_incident(self):
        self.store.apply("r1/import", [
            order("o-100", "001", "2026-10-01", 1200),
            order("o-101", "001", "2026-10-01", None),
            order("o-102", "1", "2026-10-01", -200),
            order("o-103", "unclassified", None, 300),
            tag("t-a", "001", "retail"),
            tag("t-b", "001", "retail"),
            tag("t-c", "1", "retail"),
        ])
        self.assertMatchesReference()
        self.store.apply("r1/correct", [
            tag("t-a", "001", "trade"),
            order("o-102", "1", None, -200),
            delete("orders", "o-101"),
        ])
        self.assertMatchesReference()
        rows = {(r["day"], r["segment"]): r for r in self.store.snapshot()
                if r["mode"] == "inner"}
        self.assertEqual(set(rows), {("2026-10-01", "retail"),
                                     ("2026-10-01", "trade"),
                                     (None, "retail")})
        self.assertEqual(rows[("2026-10-01", "retail")]["total_cents"], 1200)
        self.assertEqual(rows[(None, "retail")]["min_cents"], -200)

    def test_null_sum_duplicate_tags_and_null_keys(self):
        self.store.apply("b1", [
            order("o1", "A", None, None),
            order("o2", "A", None, None),
            tag("t1", "A", None),
            tag("t2", "A", None),
            tag("t3", "A", "x"),
        ])
        self.assertMatchesReference()
        row = [r for r in self.store.snapshot()
               if r["segment"] is None and r["mode"] == "inner"][0]
        self.assertEqual(row["row_count"], 4)
        self.assertIsNone(row["total_cents"])
        self.assertEqual(row["account_count"], 1)
        self.store.apply("b2", [order("o1", "A", None, 0)])
        self.assertMatchesReference()
        self.store.apply("b3", [order("o1", "A", None, None)])
        self.assertMatchesReference()

    def test_sentinel_like_text_is_not_null(self):
        self.store.apply("b1", [
            order("o1", "", "", 1), order("o2", "null", "NULL", 2),
            order("o3", "None", None, 3),
            tag("t1", "", ""), tag("t2", "null", None),
            tag("t3", "None", "None"), tag("t4", "NULL", "x"),
        ])
        self.assertMatchesReference()
        self.store.apply("b2", [tag("t2", "None", "")])
        self.assertMatchesReference()

    def test_min_max_retract_and_multiple_accounts(self):
        self.store.apply("b1", [
            order("a1", "A", "d", -5), order("a2", "A", "d", 50),
            order("b1", "B", "d", 7), tag("ta", "A", "s"), tag("tb", "B", "s"),
        ])
        self.store.apply("b2", [delete("orders", "a1")])
        self.assertMatchesReference()
        self.store.apply("b3", [delete("orders", "a2")])
        self.assertMatchesReference()
        self.store.apply("b4", [delete("tags", "tb")])
        self.assertMatchesReference()
        self.assertEqual(
            [r for r in self.store.snapshot() if r["mode"] == "inner"], [])

    def test_repeated_writes_and_noops_in_one_batch(self):
        self.store.apply("b1", [order("o1", "A", "d", 1), tag("t1", "A", "s")])
        self.store.apply("b2", [
            order("o1", "B", "e", 2), tag("t1", "B", "z"),
            order("o1", "A", "d", 1), tag("t1", "A", "s"),
            delete("orders", "missing"), order("tmp", "C", "d", 9),
            delete("orders", "tmp"),
        ])
        self.assertMatchesReference()
        self.store.apply("b3", [])
        self.store.apply("b4", [
            order("o1", "C", "f", 3), tag("t9", "C", "q"),
            tag("t1", "C", "s"), delete("tags", "t9"),
        ])
        self.assertMatchesReference()
        self.assertMatchesBootstrap()

    def test_rates_do_not_affect_inner(self):
        self.store.apply("b1", [order("o1", "A", "d", 1), tag("t1", "A", "s")])
        before = self.store.snapshot()
        self.store.apply("b2", [rate("r1", "s", "gold"), rate("r2", None, "x")])
        self.assertEqual(self.store.snapshot(), before)

    def test_rollback_and_retry_after_reopen(self):
        self.store.apply("b1", [order("o1", "A", "d", 1), tag("t1", "A", "s")])
        batch = [tag("t1", "A", "t"), order("o2", "A", None, 4)]
        snap = bag(tuple(r.values()) for r in self.store.snapshot())
        cells = bag(self.store.db.execute("SELECT * FROM aux_cell"))
        with self.assertRaises(RuntimeError):
            self.store.apply("b2", batch, fail_after_hook=True)
        self.assertEqual(bag(tuple(r.values()) for r in self.store.snapshot()),
                         snap)
        self.assertEqual(bag(self.store.db.execute("SELECT * FROM aux_cell")),
                         cells)
        self.reopen()
        self.assertTrue(self.store.apply("b2", batch))
        self.assertFalse(self.store.apply("b2", batch))
        self.assertMatchesReference()

    def test_bootstrap_from_existing_sources(self):
        db = self.store.db
        db.execute("INSERT INTO orders VALUES ('x','A','d',5),('y','B',NULL,NULL)")
        db.execute("INSERT INTO tags VALUES ('t','A','s'),('u','B',NULL)")
        import maintainer
        db.execute("BEGIN")
        maintainer.bootstrap(db, self.store.modes)
        db.execute("COMMIT")
        self.assertMatchesReference()

    def test_large_values_exact(self):
        big = (1 << 62)
        self.store.apply("b1", [
            order("o1", "A", "d", big), order("o2", "B", "d", -big),
            tag("t1", "A", "s"), tag("t2", "B", "s"),
        ])
        self.assertMatchesReference()
        self.store.apply("b2", [order("o1", "A", "d", big - 1)])
        self.assertMatchesReference()


class Randomized(Base):
    def test_random_differential_with_restarts(self):
        rng = random.Random(1234)
        accounts = ["A", "B", "", "null", "1", "001"]
        days = [None, "d1", "d2", "", "NULL"]
        segs = [None, "s1", "s2", "", "None"]
        cents = [None, 0, -3, 5, 5, 100, -100]
        for step in range(250):
            muts = []
            for _ in range(rng.randint(0, 6)):
                kind = rng.random()
                if kind < 0.45:
                    oid = f"o{rng.randint(0, 14)}"
                    muts.append(delete("orders", oid) if rng.random() < 0.2
                                else order(oid, rng.choice(accounts),
                                           rng.choice(days), rng.choice(cents)))
                elif kind < 0.9:
                    tid = f"t{rng.randint(0, 9)}"
                    muts.append(delete("tags", tid) if rng.random() < 0.2
                                else tag(tid, rng.choice(accounts),
                                         rng.choice(segs)))
                else:
                    rid = f"r{rng.randint(0, 3)}"
                    muts.append(rate(rid, rng.choice(segs), "b"))
            if rng.random() < 0.1:
                with self.assertRaises(RuntimeError):
                    self.store.apply(f"b{step}", muts, fail_after_hook=True)
            self.store.apply(f"b{step}", muts)
            self.assertMatchesReference()
            if step % 25 == 0:
                self.reopen()
                self.assertMatchesBootstrap()


class ScenariosBothModes(Scenarios):
    """Every inner scenario again with inner+outer active together."""
    MODES = ("inner", "outer")


class RandomizedBothModes(Randomized):
    MODES = ("inner", "outer")


class OuterScenarios(Base):
    MODES = ("inner", "outer")

    def outer_rows(self):
        return {(r["day"], r["segment"]): r for r in self.store.snapshot()
                if r["mode"] == "outer"}

    def test_release2_incident_after_release1(self):
        Scenarios.test_release1_incident(self)
        self.store.apply("r2/late-classification", [
            tag("t-u", "unclassified", None),
            tag("t-v", "unclassified", None),
            order("o-104", "", None, None),
            order("o-105", "null", None, 0),
        ])
        self.assertMatchesReference()
        # Two NULL-segment tags are real matches: o-103 counted twice.
        row = self.outer_rows()[(None, None)]
        self.assertEqual((row["row_count"], row["account_count"]), (4, 3))
        self.store.apply("r2/withdraw-classification", [
            delete("tags", "t-u"),
            delete("tags", "t-v"),
            order("o-103", "unclassified", "2026-10-01", 300),
            tag("t-c", "null", None),
        ])
        self.assertMatchesReference()
        rows = self.outer_rows()
        self.assertEqual(rows[("2026-10-01", None)]["total_cents"], 300)
        self.assertEqual(rows[(None, None)]["row_count"], 3)
        self.assertEqual(rows[(None, None)]["account_count"], 3)
        self.assertEqual(rows[(None, None)]["total_cents"], -200)

    def test_untagged_orders_visible_only_in_outer(self):
        self.store.apply("b1", [order("o1", "A", "d", 5)])
        self.assertMatchesReference()
        self.assertEqual([r["mode"] for r in self.store.snapshot()], ["outer"])
        self.store.apply("b2", [tag("t1", "A", "s"), tag("t2", "A", "s")])
        self.assertMatchesReference()
        self.assertNotIn(("d", None), self.outer_rows())
        self.assertEqual(self.outer_rows()[("d", "s")]["row_count"], 2)
        self.store.apply("b3", [tag("t1", "A", None), delete("tags", "t2")])
        self.assertMatchesReference()
        self.store.apply("b4", [delete("tags", "t1")])
        self.assertMatchesReference()
        self.assertEqual(self.outer_rows()[("d", None)]["row_count"], 1)
        self.store.apply("b5", [delete("orders", "o1")])
        self.assertEqual(self.store.snapshot(), [])

    def test_tags_without_orders_contribute_nothing(self):
        self.store.apply("b1", [tag("t1", "A", "s"), tag("t2", "B", None)])
        self.assertEqual(self.store.snapshot(), [])
        self.store.apply("b2", [tag("t1", "B", "s")])
        self.assertEqual(self.store.snapshot(), [])

    def test_tagged_null_segment_and_untagged_share_group(self):
        self.store.apply("b1", [
            order("o1", "A", "d", 1), order("o2", "B", "d", 9),
            tag("t1", "A", None),
        ])
        self.assertMatchesReference()
        row = self.outer_rows()[("d", None)]
        self.assertEqual((row["account_count"], row["min_cents"],
                          row["max_cents"]), (2, 1, 9))
        self.store.apply("b2", [tag("t1", "B", None)])
        self.assertMatchesReference()


class Upgrade(unittest.TestCase):
    def test_inner_to_outer_preserves_inner_and_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "u.sqlite"
            store = Store(path)
            try:
                store.upgrade(("inner",))
                store.apply("a", [order("o1", "A", "d", 3),
                                  order("o2", "B", None, None),
                                  tag("t1", "A", "s")])
                inner_before = bag(tuple(r.values()) for r in store.snapshot())
                store.close()
                store = Store(path)
                store.upgrade(("inner", "outer"))
                self.assertEqual(store.modes, ("inner", "outer"))
                inner_after = bag(tuple(r.values()) for r in store.snapshot()
                                  if r["mode"] == "inner")
                self.assertEqual(inner_before, inner_after)
                self.assertEqual(bag(store.db.execute("SELECT * FROM rollup")),
                                 reference(store.db, store.modes))
                self.assertFalse(store.apply("a", [order("o1", "A", "d", 3),
                                                   order("o2", "B", None, None),
                                                   tag("t1", "A", "s")]))
                store.close()
                store = Store(path)
                store.apply("b", [delete("tags", "t1"), tag("t2", "B", "s")])
                self.assertEqual(bag(store.db.execute("SELECT * FROM rollup")),
                                 reference(store.db, store.modes))
            finally:
                store.close()

    def test_unsupported_mode_upgrade_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "v.sqlite")
            try:
                store.upgrade(("inner",))
                store.apply("a", [order("o1", "A", "d", 3), tag("t", "A", "s")])
                snap = store.snapshot()
                with self.assertRaises(NotImplementedError):
                    store.upgrade(("inner", "outer", "rated"))
                self.assertEqual(store.modes, ("inner",))
                self.assertEqual(store.snapshot(), snap)
            finally:
                store.close()


class WorkBound(unittest.TestCase):
    """SQLite VM instruction budget on a large shared group."""
    MODES = ("inner",)
    TAGGED = True

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls._tmp.name) / "big.sqlite"
        store = Store(cls.path)
        db = store.db
        db.execute("BEGIN")
        db.executemany("INSERT INTO orders VALUES (?,?,?,?)",
                       ((f"bo{i}", f"acct{i}", "day", i % 1000 - 500)
                        for i in range(80_000)))
        if cls.TAGGED:
            db.executemany("INSERT INTO tags VALUES (?,?,?)",
                           ((f"bt{i}", f"acct{i}", "seg")
                            for i in range(80_000)))
        db.execute("COMMIT")
        # Upgrade one mode at a time, as releases do.
        for n in range(1, len(cls.MODES) + 1):
            store.upgrade(cls.MODES[:n])
        store.close()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def measure(self, store, batch_id, muts):
        count = [0]

        def tick():
            count[0] += 1
            return 0
        store.db.set_progress_handler(tick, 1)
        try:
            store.apply(batch_id, muts)
        finally:
            store.db.set_progress_handler(None, 1)
        return count[0]

    def check(self, store):
        expected = reference(store.db, store.modes)
        actual = bag(tuple(r[c] for c in COLS) for r in store.snapshot())
        self.assertEqual(actual, expected)

    def test_small_account_batches_within_budget(self):
        store = Store(self.path)
        try:
            batches = [
                ("w0", [order(f"n{i}", "small", "day", i) for i in range(8)]),
                ("w1", [order(f"n{i}", "small", "day" if i % 2 else f"d{i}",
                              -10_000 + i) for i in range(8)]
                 + [tag(f"nt{i}", "small", "seg" if i % 2 else f"s{i}")
                    for i in range(4)]
                 + [rate(f"nr{i}", "seg", f"b{i}") for i in range(4)]),
                ("w2", [tag(f"nt{i}", "small", "seg") for i in range(4)]
                 + [order(f"n{i}", "small", "day", 10_000 + i)
                    for i in range(8)]),
                ("w2b", [tag(f"nt{i}", "small", None) for i in range(4)]),
                ("w2c", [delete("tags", f"nt{i}") for i in range(4)]),
                ("w3", [delete("orders", f"n{i}") for i in range(8)]),
                ("w4", []),
                ("w5", [delete("orders", "never-existed")]),
                ("w6", [order("bo7", "acct7", None, None)]),
                ("w7", [tag("bt7", "acct7", None)]),
                ("w8", [delete("tags", "bt8"), order("bo8", "acct8", "day", 9)]),
                ("w9", [order("bo500", "acct500", "day", 10**6)]),
                ("w10", [order("bo500", "acct500", "day", 0)]),
            ]
            for batch_id, muts in batches:
                store.close()
                store = Store(self.path)
                used = self.measure(store, batch_id, muts)
                self.assertLessEqual(used, BUDGET, (batch_id, used))
                print(f"\n  {self.MODES} tagged={self.TAGGED} "
                      f"{batch_id}: {used} VM instructions", end="")
            self.check(store)
        finally:
            store.close()


class WorkBoundBothModes(WorkBound):
    MODES = ("inner", "outer")


class WorkBoundBothModesUntagged(WorkBound):
    """80k untagged accounts all share the outer (day, NULL) group."""
    MODES = ("inner", "outer")
    TAGGED = False


if __name__ == "__main__":
    unittest.main()
