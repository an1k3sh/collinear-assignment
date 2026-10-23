"""Regression checks for the incremental inner/outer/rated projections."""
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
RATED_REFERENCE = """
SELECT 'rated', o.day, t.segment, r.band,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o
LEFT JOIN tags t ON o.account=t.account
LEFT JOIN rates r ON t.segment=r.segment
GROUP BY o.day, t.segment, r.band
"""


def reference(db, modes):
    rows = Counter()
    for mode in modes:
        sql = RATED_REFERENCE if mode == "rated" else \
            REFERENCE_TEMPLATE.format(mode=mode, join=JOINS[mode])
        rows += bag(db.execute(sql))
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
        aux_sql = ("SELECT mode, account, day, segment, band, n, c, s, mn, mx "
                   "FROM aux_cell UNION ALL SELECT 'g:' || mode, a, day, "
                   "segment, NULL, n, c, s, mn, mx FROM aux_group")
        before_cells = bag(db.execute(aux_sql))
        before_rollup = bag(db.execute("SELECT * FROM rollup"))
        import maintainer
        db.execute("SAVEPOINT check_rebuild")
        maintainer.bootstrap(db, self.store.modes)
        after_cells = bag(db.execute(aux_sql))
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
        before = [r for r in self.store.snapshot() if r["mode"] != "rated"]
        self.store.apply("b2", [rate("r1", "s", "gold"), rate("r2", None, "x")])
        self.assertEqual(
            [r for r in self.store.snapshot() if r["mode"] != "rated"], before)
        self.assertMatchesReference()

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
        bands = [None, "b1", "b2", "", "null"]
        for step in range(250):
            muts = []
            for _ in range(rng.randint(0, 6)):
                kind = rng.random() * 1.15
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
                    rid = f"r{rng.randint(0, 5)}"
                    muts.append(delete("rates", rid) if rng.random() < 0.25
                                else rate(rid, rng.choice(segs),
                                          rng.choice(bands)))
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


class ScenariosAllModes(Scenarios):
    MODES = ("inner", "outer", "rated")


class RandomizedAllModes(Randomized):
    MODES = ("inner", "outer", "rated")


class RandomizedRatedOnly(Randomized):
    """`rated` alone still needs the hidden outer base layer."""
    MODES = ("rated",)


class RandomizedInnerRated(Randomized):
    MODES = ("inner", "rated")


class RatedScenarios(Base):
    MODES = ("inner", "outer", "rated")

    def outer_rows(self):
        return OuterScenarios.outer_rows(self)

    def rated_rows(self):
        return {(r["day"], r["segment"], r["band"]): r
                for r in self.store.snapshot() if r["mode"] == "rated"}

    def test_release3_incident_after_releases_1_and_2(self):
        OuterScenarios.test_release2_incident_after_release1(self)
        self.store.apply("r3/rate-import", [
            rate("r-a", "retail", "standard"),
            rate("r-b", "retail", "standard"),
            rate("r-c", "trade", None),
            rate("r-null", None, "must-not-join"),
        ])
        self.assertMatchesReference()
        rows = self.rated_rows()
        self.assertNotIn("must-not-join", {k[2] for k in rows})
        std = rows[("2026-10-01", "retail", "standard")]
        self.assertEqual((std["row_count"], std["total_cents"],
                          std["account_count"]), (2, 2400, 1))
        self.store.apply("r3/same-transaction-rekey", [
            order("o-100", "001", None, -1200),
            tag("t-a", "1", "retail"),
            tag("t-b", "001", "trade"),
            rate("r-c", "retail", "priority"),
            delete("rates", "r-a"),
        ])
        self.assertMatchesReference()
        self.store.apply("r3/delete-last-rate", [
            delete("rates", "r-b"), delete("rates", "r-c"),
        ])
        self.assertMatchesReference()
        self.assertEqual({k[2] for k in self.rated_rows()}, {None})

    def test_band_multiplicity_null_band_and_no_rates(self):
        self.store.apply("b1", [
            order("o1", "A", "d", 4), order("o2", "B", "d", None),
            tag("t1", "A", "s"), tag("t2", "B", "s"),
        ])
        self.assertMatchesReference()
        self.assertEqual(set(self.rated_rows()), {("d", "s", None)})
        self.store.apply("b2", [rate("r1", "s", None), rate("r2", "s", None),
                                rate("r3", "s", "x")])
        self.assertMatchesReference()
        null_band = self.rated_rows()[("d", "s", None)]
        self.assertEqual((null_band["row_count"], null_band["total_cents"],
                          null_band["account_count"]), (4, 8, 2))
        self.store.apply("b3", [rate("r1", "s", "x"), delete("rates", "r2")])
        self.assertMatchesReference()
        self.store.apply("b4", [delete("rates", "r1"), delete("rates", "r3")])
        self.assertMatchesReference()
        self.assertEqual(self.rated_rows()[("d", "s", None)]["row_count"], 2)

    def test_null_segment_rates_never_join(self):
        self.store.apply("b1", [
            order("o1", "A", "d", 1), order("o2", "B", "d", 2),
            tag("t1", "A", None), rate("r1", None, "x"), rate("r2", "", "y"),
        ])
        self.assertMatchesReference()
        self.assertEqual(set(self.rated_rows()), {("d", None, None)})
        self.store.apply("b2", [tag("t1", "A", "")])
        self.assertMatchesReference()
        self.assertIn(("d", "", "y"), self.rated_rows())

    def test_rates_and_classification_in_same_batch(self):
        self.store.apply("b1", [
            order("o1", "A", "d", 1), order("o2", "B", "e", 7),
            tag("t1", "A", "s"), tag("t2", "B", "u"),
            rate("r1", "s", "gold"), rate("r2", "u", "tin"),
        ])
        self.store.apply("b2", [
            rate("r1", "u", "gold"), rate("r2", "s", "tin"),
            tag("t1", "A", "u"), tag("t2", "B", "s"), tag("t3", "B", "s"),
            order("o3", "A", "e", -1),
        ])
        self.assertMatchesReference()
        self.store.apply("b3", [
            rate("r1", "s", "gold"), rate("r1", "u", "gold"),
            tag("t3", "B", "u"), delete("tags", "t3"),
        ])
        self.assertMatchesReference()
        self.assertMatchesBootstrap()

    def test_rate_change_for_segment_without_orders(self):
        self.store.apply("b1", [tag("t1", "A", "s"), rate("r1", "s", "x")])
        self.assertEqual(self.store.snapshot(), [])
        self.store.apply("b2", [order("o1", "A", None, None)])
        self.assertMatchesReference()

    def test_legacy_aux_layout_is_migrated(self):
        self.store.apply("b1", [order("o1", "A", "d", 1), tag("t1", "A", "s"),
                                rate("r1", "s", "x")])
        db = self.store.db
        db.execute("BEGIN")
        db.execute("DROP TABLE aux_meta")
        db.execute("DROP TABLE aux_group")
        db.execute("DELETE FROM rollup WHERE mode='rated'")
        db.execute("COMMIT")
        self.reopen()
        self.store.apply("b2", [order("o2", "A", "d", 5)])
        self.assertMatchesReference()
        self.store.apply("b3", [rate("r1", "s", "y")])
        self.assertMatchesReference()


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
        self.assertEqual(sorted(r["mode"] for r in self.store.snapshot()),
                         ["outer", "rated"][:len(self.MODES) - 1])
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

    def test_release_sequence_upgrades_preserve_earlier_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "v.sqlite"
            store = Store(path)
            try:
                store.upgrade(("inner",))
                store.apply("a", [order("o1", "A", "d", 3), tag("t", "A", "s"),
                                  order("o2", "B", None, -2),
                                  rate("r", "s", "x"), rate("r2", "s", "x")])
                inner = bag(tuple(r.values()) for r in store.snapshot())
                store.upgrade(("inner", "outer"))
                store.close()
                store = Store(path)
                store.apply("b", [tag("t2", "B", None)])
                both = bag(tuple(r.values()) for r in store.snapshot())
                store.close()
                store = Store(path)
                store.upgrade(("inner", "outer", "rated"))
                self.assertEqual(
                    bag(tuple(r.values()) for r in store.snapshot()
                        if r["mode"] != "rated"), both)
                self.assertEqual(bag(store.db.execute("SELECT * FROM rollup")),
                                 reference(store.db, store.modes))
                store.close()
                store = Store(path)
                store.apply("c", [rate("r", "s", None), tag("t", "B", "s")])
                self.assertEqual(bag(store.db.execute("SELECT * FROM rollup")),
                                 reference(store.db, store.modes))
            finally:
                store.close()

    def test_failed_upgrade_rolls_back(self):
        import maintainer
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "w.sqlite")
            try:
                store.upgrade(("inner",))
                store.apply("a", [order("o1", "A", "d", 3), tag("t", "A", "s")])
                snap = store.snapshot()
                original = maintainer._CELLS["outer"]
                maintainer._CELLS["outer"] = None  # force bootstrap failure
                try:
                    with self.assertRaises(TypeError):
                        store.upgrade(("inner", "outer", "rated"))
                finally:
                    maintainer._CELLS["outer"] = original
                self.assertEqual(store.modes, ("inner",))
                self.assertEqual(store.snapshot(), snap)
                store.apply("b", [order("o2", "A", "d", 4)])
                self.assertEqual(bag(store.db.execute("SELECT * FROM rollup")),
                                 reference(store.db, store.modes))
            finally:
                store.close()


class OuterScenariosAllModes(OuterScenarios):
    MODES = ("inner", "outer", "rated")


class WorkBound(unittest.TestCase):
    """SQLite VM instruction budget on a large shared group."""
    MODES = ("inner",)
    TAGGED = True
    OTHER_GROUPS = 0

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
        db.executemany("INSERT INTO rates VALUES (?,?,?)",
                       [("fr1", "seg", "std"), ("fr2", "seg", "std"),
                        ("fr3", "seg", None), ("fr4", "other0", "x")])
        # Unrelated accounts each in their own (day, segment) group.
        db.executemany("INSERT INTO orders VALUES (?,?,?,?)",
                       ((f"go{i}", f"g{i}", f"gday{i}", i)
                        for i in range(cls.OTHER_GROUPS)))
        db.executemany("INSERT INTO tags VALUES (?,?,?)",
                       ((f"gt{i}", f"g{i}", f"other{i}")
                        for i in range(cls.OTHER_GROUPS)))
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
                # Segment-rate corrections (fanout: one shared day group).
                ("w11", [rate("fr1", "seg", "gold")]),
                ("w12", [rate("fr2", "nosuch", "std"),
                         rate("nr9", None, "x")]),
                ("w13", [delete("rates", "fr1"), delete("rates", "fr3")]),
                ("w14", [rate(f"fr{i}", "seg", f"v{i}") for i in range(1, 5)]),
                # Classification and rate rekey in one transaction.
                ("w15", [order("n1", "small", "day", 5),
                         tag("nt1", "small", "seg"),
                         rate("fr4", "seg", "z"),
                         rate("fr2", "seg", None)]),
                ("w16", [tag("nt1", "small", "solo"),
                         rate("fr4", "solo", "z")]),
            ]
            for batch_id, muts in batches:
                store.close()
                store = Store(self.path)
                used = self.measure(store, batch_id, muts)
                self.assertLessEqual(used, BUDGET, (batch_id, used))
                print(f"\n  {self.MODES} tagged={self.TAGGED} "
                      f"others={self.OTHER_GROUPS} "
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


class WorkBoundAllModes(WorkBound):
    MODES = ("inner", "outer", "rated")


class WorkBoundAllModesUntagged(WorkBound):
    MODES = ("inner", "outer", "rated")
    TAGGED = False


class WorkBoundAllModesManyGroups(WorkBound):
    MODES = ("inner", "outer", "rated")
    OTHER_GROUPS = 40_000


class WorkBoundRatedOnly(WorkBound):
    MODES = ("rated",)


if __name__ == "__main__":
    unittest.main()
