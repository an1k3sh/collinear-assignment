"""Regression checks for the incremental projections (all four modes)."""
import json
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
    "rated": """
SELECT 'rated', o.day, t.segment, r.band,
       COUNT(*), COUNT(o.cents), SUM(o.cents), COUNT(DISTINCT o.account),
       MIN(o.cents), MAX(o.cents)
FROM orders o
LEFT JOIN tags t ON o.account=t.account
LEFT JOIN rates r ON t.segment=r.segment
GROUP BY o.day, t.segment, r.band
""",
    # households(account, representative) built straight from the contract:
    # reachability over undirected link edges, least label under BINARY.
    "household": """
WITH RECURSIVE
edges(a, b) AS (SELECT left_account, right_account FROM links
                UNION SELECT right_account, left_account FROM links),
nodes(x) AS (SELECT account FROM orders UNION SELECT a FROM edges),
reach(src, dst) AS (SELECT x, x FROM nodes
                    UNION SELECT r.src, e.b FROM reach r
                          JOIN edges e ON e.a = r.dst),
households(account, representative) AS (
    SELECT src, MIN(dst) FROM reach GROUP BY src)
SELECT 'household', o.day, t.segment, r.band,
       COUNT(*), COUNT(o.cents), SUM(o.cents),
       COUNT(DISTINCT h.representative),
       MIN(o.cents), MAX(o.cents)
FROM orders o
LEFT JOIN tags t ON o.account=t.account
LEFT JOIN rates r ON t.segment=r.segment
JOIN households h ON h.account=o.account
GROUP BY o.day, t.segment, r.band
""",
}
MODES = ("inner", "outer", "rated", "household")
BUDGET = 300_000
ROLLUP = ("SELECT mode, day, segment, band, row_count, amount_count, "
          "total_cents, account_count, min_cents, max_cents FROM rollup")


def order(i, account, day, cents):
    return {"table": "orders", "id": i,
            "row": {"id": i, "account": account, "day": day, "cents": cents}}


def tag(i, account, segment):
    return {"table": "tags", "id": i,
            "row": {"id": i, "account": account, "segment": segment}}


def rate(i, segment, band):
    return {"table": "rates", "id": i,
            "row": {"id": i, "segment": segment, "band": band}}


def link(i, left, right):
    return {"table": "links", "id": i,
            "row": {"id": i, "left_account": left, "right_account": right}}


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


def rated_rows(store, mode="rated"):
    return {(r["day"], r["segment"], r["band"]): r for r in store.snapshot()
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


class RatedSemantics(Base):
    def test_versioned_rates_multiply_and_null_rules(self):
        self.store.apply("seed", [
            order("o1", "A", "d", 10), order("o2", "A", "d", None),
            tag("t1", "A", "retail"), tag("t2", "A", "retail"),
            order("o3", "U", "d", 5),                       # untagged
            order("o4", "N", "d", 1), tag("t3", "N", None),  # NULL segment
            rate("r1", "retail", "std"), rate("r2", "retail", "std"),
            rate("r3", "retail", None), rate("rn", None, "never"),
        ])
        self.assertMatchesReference()
        rows = rated_rows(self.store)
        self.assertEqual(rows[("d", "retail", "std")]["row_count"], 8)
        self.assertEqual(rows[("d", "retail", "std")]["total_cents"], 40)
        self.assertEqual(rows[("d", "retail", None)]["row_count"], 4)
        null_group = rows[("d", None, None)]
        self.assertEqual((null_group["row_count"], null_group["account_count"]),
                         (2, 2))
        self.assertNotIn("never", {k[2] for k in rows})

    def test_rate_import_with_classification_correction_same_batch(self):
        self.store.apply("seed", [
            order("o1", "A", "d", 10), tag("t1", "A", "retail"),
            order("o2", "B", "d", 3), tag("t2", "B", "trade"),
            rate("r1", "retail", "std"),
        ])
        self.store.apply("mixed", [
            tag("t1", "A", "trade"), rate("r1", "trade", "priority"),
            rate("r2", "retail", "std"), rate("r3", "trade", "priority"),
            order("o2", "B", None, -3),
        ])
        self.assertMatchesReference()
        self.store.apply("delete-last-rates", [
            delete("rates", "r1"), delete("rates", "r3"),
        ])
        self.assertMatchesReference()
        self.assertEqual(set(rated_rows(self.store)),
                         {("d", "trade", None), (None, "trade", None)})

    def test_rate_change_reaches_untouched_accounts_only_with_orders(self):
        self.store.apply("seed", [
            order("o1", "A", "d", 10), tag("t1", "A", "s"),
            tag("t2", "Z", "s"),  # tag-only account: contributes nothing
        ])
        self.reopen()
        self.store.apply("rate", [rate("r1", "s", "b")])
        self.assertMatchesReference()
        self.store.apply("rerate", [rate("r1", "s", None),
                                    rate("r2", "s", "")])
        self.assertMatchesReference()
        self.store.apply("move-rate", [rate("r1", "other", "x"),
                                       rate("r2", None, "")])
        self.assertMatchesReference()


class IncidentReplay(unittest.TestCase):
    """Replay incidents/release-N.json, upgrading as demo.py does, and
    check every active mode after every batch, failure, retry and reopen."""

    def test_incidents_batch_by_batch(self):
        root = Path(__file__).resolve().parent.parent / "incidents"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "replay.sqlite"
            store = Store(path)
            try:
                for release in range(1, len(MODES) + 1):
                    store.upgrade(MODES[:release])
                    self.check(store)
                    batches = json.loads(
                        (root / f"release-{release}.json").read_text())
                    for batch in batches:
                        with self.assertRaises(RuntimeError):
                            store.apply(batch["id"], batch["mutations"],
                                        fail_after_hook=True)
                        self.check(store)
                        store.close()
                        store = Store(path)
                        self.assertTrue(
                            store.apply(batch["id"], batch["mutations"]))
                        self.check(store)
                        self.assertFalse(
                            store.apply(batch["id"], batch["mutations"]))
            finally:
                store.close()

    def check(self, store):
        self.assertEqual(bag(store.db.execute(ROLLUP)),
                         expected_bag(store.db, store.modes))


def random_batch(rng, size, accounts, link_ids=8, link_weight=0.2):
    days = ["d1", "d2", None, ""]
    segs = ["s1", "s2", None, "NULL", ""]
    bands = ["b1", "b2", None, ""]
    cents = [None, 0, -5, 7, 7, 100, -(1 << 40)]
    link_accounts = accounts + ["dormant", "ghost", "z"]
    batch = []
    for _ in range(rng.randint(0, size)):
        kind = rng.random()
        if kind < link_weight:
            i = f"l{rng.randint(0, link_ids)}"
            batch.append(delete("links", i) if rng.random() < 0.3 else
                         link(i, rng.choice(link_accounts),
                              rng.choice(link_accounts)))
        elif kind < link_weight + 0.15:
            i = f"r{rng.randint(0, 8)}"
            batch.append(delete("rates", i) if rng.random() < 0.25 else
                         rate(i, rng.choice(segs), rng.choice(bands)))
        elif kind < link_weight + 0.55:
            i = f"o{rng.randint(0, 25)}"
            batch.append(delete("orders", i) if rng.random() < 0.2 else
                         order(i, rng.choice(accounts), rng.choice(days),
                               rng.choice(cents)))
        else:
            i = f"t{rng.randint(0, 15)}"
            batch.append(delete("tags", i) if rng.random() < 0.2 else
                         tag(i, rng.choice(accounts), rng.choice(segs)))
    return batch


class Randomized(Base):
    def run_random(self, seed, steps, **kw):
        rng = random.Random(seed)
        accounts = ["A", "B", "", "1", "001", "null", "a"]
        for step in range(steps):
            batch = random_batch(rng, 6, accounts, **kw)
            if rng.random() < 0.1:
                with self.assertRaises(RuntimeError):
                    self.store.apply(f"b{step}", batch, fail_after_hook=True)
                self.assertMatchesReference()
            self.store.apply(f"b{step}", batch)
            if rng.random() < 0.1:
                self.reopen()
            self.assertMatchesReference()

    def test_random_batches_against_reference(self):
        self.run_random(1234, 400)

    def test_random_alias_heavy_batches(self):
        self.run_random(99, 400, link_ids=12, link_weight=0.6)


class RandomizedModeSubsets(unittest.TestCase):
    """Released mode sets, and household without rated, stay exact."""

    def test_subsets_and_upgrades(self):
        for seed, plan in enumerate([
            [("household",)],
            [("inner", "household")],
            [("inner",), ("inner", "outer"), ("inner", "outer", "rated"),
             MODES],
        ]):
            rng = random.Random(seed)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "s.sqlite"
                store = Store(path)
                try:
                    for stage, modes in enumerate(plan):
                        store.upgrade(modes)
                        self.check(store)
                        for step in range(60):
                            store.apply(f"{stage}/{step}", random_batch(
                                rng, 6, ["A", "B", "C", "", "1"],
                                link_weight=0.4))
                            if rng.random() < 0.1:
                                store.close()
                                store = Store(path)
                            self.check(store)
                finally:
                    store.close()

    def check(self, store):
        self.assertEqual(bag(store.db.execute(ROLLUP)),
                         expected_bag(store.db, store.modes))


class HouseholdSemantics(Base):
    def counts(self):
        return {k: r["account_count"]
                for k, r in rated_rows(self.store, "household").items()}

    def seed(self):
        self.store.apply("seed", [
            order("o1", "A", "d", 10), order("o2", "B", "d", 20),
            order("o3", "C", "d", None), order("o4", "C", "d", 5),
            tag("t1", "A", "s"), tag("t2", "B", "s"), tag("t3", "C", "s"),
            rate("r1", "s", "b"), rate("r2", "s", "b"),
        ])
        self.assertEqual(self.counts(), {("d", "s", "b"): 3})

    def test_dormant_bridge_merge_then_split(self):
        self.seed()
        self.store.apply("bridge", [link("l1", "A", "dormant"),
                                    link("l2", "dormant", "B")])
        self.assertMatchesReference()
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        # amounts and the three older reports are untouched by links
        hh = rated_rows(self.store, "household")[("d", "s", "b")]
        rated = rated_rows(self.store)[("d", "s", "b")]
        self.assertEqual(rated["account_count"], 3)
        for col in ("row_count", "amount_count", "total_cents",
                    "min_cents", "max_cents"):
            self.assertEqual(hh[col], rated[col])
        self.reopen()
        self.store.apply("cut", [delete("links", "l2")])
        self.assertMatchesReference()
        self.assertEqual(self.counts(), {("d", "s", "b"): 3})

    def test_parallel_edges_cycles_and_self_links(self):
        self.seed()
        self.store.apply("links", [
            link("p1", "A", "B"), link("p2", "B", "A"), link("self", "C", "C"),
            link("c1", "B", "x"), link("c2", "x", "A"),
        ])
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        self.store.apply("drop-one-parallel", [delete("links", "p1")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        self.store.apply("break-cycle", [delete("links", "c1")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        self.store.apply("last-edge", [delete("links", "p2")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 3})
        self.store.apply("self-gone", [delete("links", "self")])
        self.assertMatchesReference()

    def test_rekey_merges_and_splits_same_batch_with_source_edits(self):
        self.seed()
        self.store.apply("ab", [link("l1", "A", "B")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        self.store.apply("rekey", [
            link("l1", "B", "C"),            # split A from B, merge B with C
            tag("t1", "A", "q"), rate("r3", "q", None),
            order("o5", "D", "d", 1), tag("t4", "D", "s"),
            link("l2", "D", "A"), link("l2", "D", "B"),  # coalesced rewrite
        ])
        self.assertMatchesReference()
        self.assertEqual(self.counts(),
                         {("d", "s", "b"): 1, ("d", "q", None): 1})

    def test_label_change_without_output_effect_is_durable(self):
        self.seed()
        # links among accounts without orders: no output change
        before = self.store.snapshot()
        self.store.apply("dormant", [link("l1", "y", "z"),
                                     link("l2", "z", "w")])
        self.assertEqual(bag(map(dict.values, self.store.snapshot())),
                         bag(map(dict.values, before)))
        self.reopen()
        # later edits must use the stored dormant component
        self.store.apply("join", [link("l3", "A", "w"), link("l4", "y", "B")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 2})
        self.store.apply("relabel", [link("l5", "", "z")])
        self.assertMatchesReference()
        self.store.apply("split", [delete("links", "l2")])
        self.assertEqual(self.counts(), {("d", "s", "b"): 3})
        self.assertMatchesReference()

    def test_failed_alias_batch_rolls_back_component_state(self):
        self.seed()
        batch = [link("l1", "A", "B"), link("l2", "B", "C")]
        with self.assertRaises(RuntimeError):
            self.store.apply("merge", batch, fail_after_hook=True)
        self.reopen()
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM aux_comp").fetchone()[0], 0)
        self.assertEqual(self.counts(), {("d", "s", "b"): 3})
        self.store.apply("merge", batch)
        self.assertEqual(self.counts(), {("d", "s", "b"): 1})
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
        db.executemany("INSERT INTO rates VALUES (?,?,?)", [
            ("bs1", "S", "gold"), ("bs2", "S", "gold"), ("bs3", "S", None),
            ("bs4", "S", "base")])
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
            # an account in its own segments with four versioned rates
            used.append(self.measure(store, "rated-seed",
                [order(f"y{i}", "rated", "D" if i % 2 else f"D{i}", i - 4)
                 for i in range(8)]
                + [tag(f"yt{i}", "rated", ["S", "P", "Q", None][i])
                   for i in range(4)]
                + [rate(f"yr{i}", "P", f"b{i % 2}") for i in range(4)]))
            # segment-rate correction with small account fanout
            used.append(self.measure(store, "rate-fix", [
                rate("yr0", "Q", "b9"), rate("yr1", "P", None),
                delete("rates", "yr2"), rate("yr4", "Q", "b9")]))
            # rate correction and classification correction together
            used.append(self.measure(store, "rate-and-class", [
                rate("yr3", "Q", None), tag("yt1", "rated", "Q"),
                tag("yt3", "rated", "P"), order("y0", "rated", "D", 77)]))
            used.append(self.measure(store, "rated-cleanup",
                [delete("orders", f"y{i}") for i in range(8)]
                + [delete("tags", f"yt{i}") for i in range(4)]
                + [delete("rates", f"yr{i}") for i in range(5)]))
            used.append(self.measure(store, "empty", []))
            used.append(self.measure(store, "noop", [delete("orders", "nope")]))
            print("VM instructions per batch:", used)
            for n in used:
                self.assertLessEqual(n, BUDGET, used)
            self.check_reference(store)
        finally:
            store.close()

    def test_alias_edits_on_busy_groups_stay_within_budget(self):
        """Up to eight accounts in the old+final components, eight orders and
        four tags each, four rate rows per segment, sharing groups with the
        80,000-account archive."""
        store = Store(self.path)
        accts = [f"h{i}" for i in range(8)]
        segs = ["S", "P", "Q", "R"]

        def sources(days, tagset):
            out = []
            for a in accts:
                out += [order(f"{a}o{j}", a, days[j], j * 3 - 7)
                        for j in range(8)]
                out += [tag(f"{a}t{j}", a, tagset[j]) for j in range(4)]
            return out

        used = {}
        try:
            used["rates"] = self.measure(store, "h/rates", [
                rate(f"hr{sg}{j}", sg, f"b{j}") for sg in "PQR"
                for j in range(4)])
            used["seed"] = self.measure(store, "h/seed", sources(
                ["D"] * 4 + [f"D{j}" for j in range(4, 8)], segs))
            store.close()
            store = Store(self.path)
            used["chain-merge"] = self.measure(store, "h/merge", [
                link(f"L{i}", accts[i], accts[i + 1]) for i in range(7)])
            used["split"] = self.measure(store, "h/split",
                                         [delete("links", "L3")])
            used["parallel-delete"] = self.measure(store, "h/par", [
                link("P1", accts[0], accts[1])])
            used["rekey-merge-split"] = self.measure(store, "h/rekey", [
                link("L1", accts[0], accts[5]),
                link("L5", "dormant", accts[2]),
                link("L3", accts[3], "dormant"), delete("links", "P1")])
            used["dormant-relabel"] = self.measure(store, "h/dormant", [
                link("L9", "", "dormant")])
            store.close()
            store = Store(self.path)
            used["links+all-sources"] = self.measure(store, "h/all", sources(
                [f"E{j}" for j in range(8)], segs[::-1])
                + [link("L0", accts[7], accts[0]), delete("links", "L4")])
            used["segment-rate-fix"] = self.measure(store, "h/rate", [
                rate(f"hrP{j}", "P", f"c{j}") for j in range(4)])
            used["unlink-all"] = self.measure(store, "h/unlink", [
                delete("links", f"L{i}") for i in (0, 1, 2, 3, 5, 6, 9)])
            used["delete-all"] = self.measure(
                store, "h/delete",
                [delete("orders", f"{a}o{j}") for a in accts
                 for j in range(8)]
                + [delete("tags", f"{a}t{j}") for a in accts
                   for j in range(4)])
            print("household VM instructions:", used)
            for name, n in used.items():
                self.assertLessEqual(n, BUDGET, (name, used))
            self.check_reference(store)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
