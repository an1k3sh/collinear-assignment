"""Regression checks for the incremental projections (`inner`, `outer`)."""
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from runtime import Store

REFERENCE = {
    "inner": """
SELECT 'inner', o.day, t.segment, NULL,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o JOIN tags t ON o.account=t.account
GROUP BY o.day, t.segment
""",
    "outer": """
SELECT 'outer', o.day, t.segment, NULL,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o LEFT JOIN tags t ON o.account=t.account
GROUP BY o.day, t.segment
""",
}
MODES = ("inner", "outer")
BUDGET = 300_000
ROLLUP = ("SELECT mode, day, segment, band, row_count, amount_count, "
          "total_cents, account_count, min_cents, max_cents FROM rollup")


def order(i, account, day, cents):
    return {"table": "orders", "id": i,
            "row": {"id": i, "account": account, "day": day, "cents": cents}}


def tag(i, account, segment):
    return {"table": "tags", "id": i,
            "row": {"id": i, "account": account, "segment": segment}}


def delete(table, i):
    return {"table": table, "id": i, "row": None}


def bag(rows):
    return Counter(tuple(r) for r in rows)


def expected_bag(db, modes):
    out = Counter()
    for mode in modes:
        out += bag(db.execute(REFERENCE[mode]))
    return out


def rows_of(store, mode):
    return {(r["day"], r["segment"]): r for r in store.snapshot()
            if r["mode"] == mode}


class Base(unittest.TestCase):
    modes = MODES

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "board.sqlite"
        self.store = Store(self.path)
        self.store.upgrade(self.modes)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def reopen(self):
        self.store.close()
        self.store = Store(self.path)

    def assertMatchesReference(self):
        db = self.store.db
        self.assertEqual(bag(db.execute(ROLLUP)),
                         expected_bag(db, self.store.modes))


class Corrections(Base):
    def test_release1_incident_shape(self):
        self.store.apply("import", [
            order("o-100", "001", "d", 1200), order("o-101", "001", "d", None),
            order("o-102", "1", "d", -200), order("o-103", "x", None, 300),
            tag("t-a", "001", "retail"), tag("t-b", "001", "retail"),
            tag("t-c", "1", "retail"),
        ])
        self.assertMatchesReference()
        self.store.apply("correct", [
            tag("t-a", "001", "trade"), order("o-102", "1", None, -200),
            delete("orders", "o-101"),
        ])
        self.assertMatchesReference()
        rows = rows_of(self.store, "inner")
        self.assertEqual(set(rows), {("d", "retail"), ("d", "trade"),
                                     (None, "retail")})
        self.assertEqual(rows[("d", "retail")]["min_cents"], 1200)
        outer = rows_of(self.store, "outer")
        self.assertEqual(set(outer), set(rows) | {(None, None)})
        self.assertEqual(outer[(None, None)]["total_cents"], 300)

    def test_null_values_and_sentinel_like_strings(self):
        self.store.apply("seed", [
            order("a", "", None, None), order("b", "NULL", "", 0),
            order("c", "null", None, None), tag("t1", "", None),
            tag("t2", "null", ""), tag("t3", "NULL", None),
        ])
        self.assertMatchesReference()
        null_row = rows_of(self.store, "inner")[(None, None)]
        self.assertIsNone(null_row["total_cents"])
        self.assertEqual(null_row["amount_count"], 0)
        self.store.apply("set", [order("a", "", None, 5)])
        self.assertMatchesReference()

    def test_rekey_and_multiple_writes_same_batch(self):
        self.store.apply("seed", [
            order("o1", "A", "d1", 10), order("o2", "B", "d1", 20),
            tag("t1", "A", "s"), tag("t2", "B", "s"),
        ])
        self.store.apply("churn", [
            order("o1", "B", "d2", 99), order("o1", "A", "d1", 7),
            tag("t1", "B", "s"), delete("tags", "t2"), tag("t2", "B", "s"),
            order("o3", "C", "d1", 1), delete("orders", "o3"),
            delete("orders", "missing"),
        ])
        self.assertMatchesReference()
        self.store.apply("noop", [])
        self.assertMatchesReference()

    def test_duplicate_tag_rows_multiply(self):
        self.store.apply("seed", [
            order("o1", "A", "d", 5), tag("t1", "A", "s"), tag("t2", "A", "s"),
        ])
        row = rows_of(self.store, "inner")[("d", "s")]
        self.assertEqual((row["row_count"], row["total_cents"],
                          row["account_count"]), (2, 10, 1))
        self.store.apply("drop", [delete("tags", "t2")])
        self.assertMatchesReference()

    def test_large_partial_sum_with_offsetting_accounts(self):
        big = (1 << 62)
        self.store.apply("seed", [
            order("o1", "A", "d", big), tag("t1", "A", "s"),
            tag("t2", "A", "s"),  # A's partial sum is 2**63: exceeds int64
            order("o2", "B", "d", -big), tag("t3", "B", "s"),
            tag("t4", "B", "s"),
        ])
        self.assertEqual(rows_of(self.store, "outer")[("d", "s")]["total_cents"], 0)
        self.store.apply("fix", [order("o2", "B", "d", -big + 1)])
        self.assertEqual(rows_of(self.store, "inner")[("d", "s")]["total_cents"], 2)

    def test_failure_rollback_retry_and_reopen(self):
        self.store.apply("seed", [order("o1", "A", "d", 1), tag("t1", "A", "s")])
        batch = [tag("t1", "A", "z"), order("o2", "A", "d", -3)]
        with self.assertRaises(RuntimeError):
            self.store.apply("b", batch, fail_after_hook=True)
        self.assertMatchesReference()
        self.reopen()
        self.assertTrue(self.store.apply("b", batch))
        self.assertFalse(self.store.apply("b", batch))
        self.assertMatchesReference()

    def test_bootstrap_on_existing_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pre.sqlite"
            store = Store(path)
            store.db.execute("INSERT INTO orders VALUES ('o','A','d',4),"
                             "('p','B',NULL,NULL)")
            store.db.execute("INSERT INTO tags VALUES ('t','A','s'),"
                             "('u','B',NULL),('v','B',NULL)")
            store.upgrade(MODES)
            self.store, old = store, self.store
            try:
                self.assertMatchesReference()
                store.apply("x", [delete("tags", "v")])
                self.assertMatchesReference()
            finally:
                self.store = old
                store.close()


class OuterSemantics(Base):
    def test_unclassified_vs_null_segment_share_group(self):
        self.store.apply("seed", [
            order("o1", "U", "d", 4), order("o2", "N", "d", None),
            tag("t1", "N", None), tag("t2", "N", None),
        ])
        self.assertMatchesReference()
        row = rows_of(self.store, "outer")[("d", None)]
        self.assertEqual((row["row_count"], row["amount_count"],
                          row["total_cents"], row["account_count"]),
                         (3, 1, 4, 2))
        self.assertEqual(set(rows_of(self.store, "inner")), {("d", None)})

    def test_classify_and_withdraw_classification(self):
        self.store.apply("seed", [order("o1", "U", None, 3)])
        self.assertEqual(set(rows_of(self.store, "outer")), {(None, None)})
        self.assertEqual(rows_of(self.store, "inner"), {})
        self.store.apply("tag", [tag("t1", "U", "s"), tag("t2", "U", "s")])
        self.assertMatchesReference()
        self.assertEqual(set(rows_of(self.store, "outer")), {(None, "s")})
        self.store.apply("move-tag", [tag("t1", "V", "s"),
                                      delete("tags", "t2")])
        self.assertMatchesReference()
        self.assertEqual(set(rows_of(self.store, "outer")), {(None, None)})
        self.store.apply("orphan-tag-only", [tag("t9", "nobody", "x")])
        self.assertMatchesReference()


class Upgrade(unittest.TestCase):
    def test_inner_database_upgraded_to_outer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "u.sqlite"
            store = Store(path)
            try:
                store.upgrade(("inner",))
                store.apply("a", [order("o1", "A", "d", 1),
                                  order("o2", "B", "d", 2),
                                  tag("t1", "A", "s")])
                inner_before = bag(store.db.execute(ROLLUP))
                store.close()
                store = Store(path)
                store.upgrade(MODES)
                after = bag(store.db.execute(ROLLUP))
                self.assertEqual(after, expected_bag(store.db, MODES))
                self.assertEqual(Counter({k: v for k, v in after.items()
                                          if k[0] == "inner"}), inner_before)
                store.apply("b", [tag("t2", "B", None)])
                self.assertEqual(bag(store.db.execute(ROLLUP)),
                                 expected_bag(store.db, MODES))
                with self.assertRaises(ValueError):
                    store.upgrade(("outer",))  # host refuses mode removal
            finally:
                store.close()


class InnerOnly(Base):
    """Released inner-only behavior is unchanged."""
    modes = ("inner",)

    def test_inner_only_database(self):
        self.store.apply("seed", [order("o1", "U", "d", 4),
                                  order("o2", "A", "d", 1),
                                  tag("t1", "A", "s")])
        self.assertMatchesReference()
        self.assertEqual({r["mode"] for r in self.store.snapshot()}, {"inner"})
        self.store.apply("drop", [delete("tags", "t1")])
        self.assertEqual(self.store.snapshot(), [])


class Randomized(Base):
    def test_random_batches_against_reference(self):
        rng = random.Random(1234)
        accounts = ["A", "B", "", "1", "001", "null", "a"]
        days = ["d1", "d2", None, ""]
        segs = ["s1", "s2", None, "NULL"]
        cents = [None, 0, -5, 7, 7, 100, -(1 << 40)]
        for step in range(250):
            batch = []
            for _ in range(rng.randint(0, 6)):
                if rng.random() < 0.55:
                    i = f"o{rng.randint(0, 25)}"
                    batch.append(delete("orders", i) if rng.random() < 0.2 else
                                 order(i, rng.choice(accounts), rng.choice(days),
                                       rng.choice(cents)))
                else:
                    i = f"t{rng.randint(0, 15)}"
                    batch.append(delete("tags", i) if rng.random() < 0.2 else
                                 tag(i, rng.choice(accounts), rng.choice(segs)))
            fail = rng.random() < 0.1
            if fail:
                with self.assertRaises(RuntimeError):
                    self.store.apply(f"b{step}", batch, fail_after_hook=True)
            self.store.apply(f"b{step}", batch)
            if rng.random() < 0.1:
                self.reopen()
            self.assertMatchesReference()


class WorkBound(unittest.TestCase):
    """Machine-independent bound: SQLite VM instructions during apply."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "big.sqlite"
        store = Store(cls.path)
        db = store.db
        db.execute("BEGIN")
        db.executemany("INSERT INTO orders VALUES (?,?,?,?)",
                       ((f"bo{i}", f"acct{i}", "D", i % 1000 - 500)
                        for i in range(80_000)))
        db.executemany("INSERT INTO tags VALUES (?,?,?)",
                       ((f"bt{i}", f"acct{i}", "S") for i in range(80_000)))
        db.execute("COMMIT")
        store.upgrade(MODES)
        store.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def measure(self, store, batch_id, batch):
        count = [0]

        def tick():
            count[0] += 1
            return 0

        store.db.set_progress_handler(tick, 1)
        try:
            store.apply(batch_id, batch)
        finally:
            store.db.set_progress_handler(None, 1)
        return count[0]

    def check_reference(self, store):
        self.assertEqual(bag(store.db.execute(ROLLUP)),
                         expected_bag(store.db, store.modes))

    def test_small_account_batches_stay_within_budget(self):
        store = Store(self.path)
        try:
            seed = [order(f"x{i}", "small", "D" if i % 2 else f"D{i}",
                          -10_000 + i) for i in range(8)]
            seed += [tag(f"xt{i}", "small", "S" if i % 2 else f"S{i}")
                     for i in range(4)]
            used = [self.measure(store, "seed", seed)]
            store.close()
            store = Store(self.path)  # reopen: no startup rebuild
            used.append(self.measure(store, "reclass", [
                tag("xt1", "small", "T"), tag("xt3", "small", None)]))
            used.append(self.measure(store, "unclassify", [
                delete("tags", f"xt{i}") for i in range(4)]))
            used.append(self.measure(store, "reclassify-again", [
                tag(f"xt{i}", "small", "S") for i in range(4)]))
            used.append(self.measure(store, "move", [
                order(f"x{i}", "small", None, None) for i in range(8)]))
            # removing the group minimum forces an indexed MIN refresh
            used.append(self.measure(store, "drop-min", [
                delete("orders", "bo0"), delete("tags", "bt500")]))
            used.append(self.measure(store, "cleanup", [
                delete("orders", f"x{i}") for i in range(8)]
                + [delete("tags", f"xt{i}") for i in range(4)]))
            used.append(self.measure(store, "empty", []))
            used.append(self.measure(store, "noop", [delete("orders", "nope")]))
            print("VM instructions per batch:", used)
            for n in used:
                self.assertLessEqual(n, BUDGET, used)
            self.check_reference(store)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
