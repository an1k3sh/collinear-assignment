import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import import_payments  # noqa: E402
from import_payments import (  # noqa: E402
    InvalidPayment, PaymentConflict, PaymentError, UnknownInvoice, apply_payment)
from seed import seed  # noqa: E402

HEADER = "tenant,payment_id,invoice_id,paid_at,amount\n"
T = "2026-04-30T09:00:00Z"


def row(payment_id="P-100", invoice_id="00123", paid_at=T, amount="25.00", tenant="north"):
    return {"tenant": tenant, "payment_id": payment_id, "invoice_id": invoice_id,
            "paid_at": paid_at, "amount": amount}


def _race_worker(db_path, counter_path, barrier, queue):
    def hook():
        with open(counter_path, "a") as f:
            f.write("x")
    barrier.wait()
    try:
        queue.put(("ok", apply_payment(db_path, row("P-RACE", amount="12.34"), hook)))
    except Exception as exc:
        queue.put(("error", repr(exc)))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "state" / "payments.sqlite"
        seed(self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def query(self, sql, args=()):
        db = sqlite3.connect(self.db)
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def payments(self):
        return sorted(self.query("SELECT tenant,payment_id,invoice_id,paid_at,cents FROM payments"))

    def snapshot(self):
        return (self.payments(), sorted(self.query("SELECT * FROM receipts")),
                sorted(self.query("SELECT * FROM invoices")))

    def cli(self, csv_text=None, input_path=None, report=None, db=None):
        if input_path is None:
            input_path = self.tmp / "input.csv"
            input_path.write_bytes(csv_text.encode() if isinstance(csv_text, str) else csv_text)
        report = report or self.tmp / "out" / "nested" / "report.json"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "import_payments.py"), "--db", str(db or self.db),
             "--input", str(input_path), "--report", str(report)],
            capture_output=True, text=True, timeout=120)
        data = json.loads(report.read_text()) if report.exists() else None
        return proc, data


class AmountAndValidationTests(Base):
    def test_amounts_are_exact_integer_cents(self):
        for i, (amount, cents) in enumerate([("0.29", 29), ("19.99", 1999), ("100.01", 10001),
                                             ("1.10", 110), ("0.01", 1), ("0.57", 57),
                                             ("92233720368547758.07", 9223372036854775807)]):
            receipt = apply_payment(self.db, row(f"A-{i}", amount=amount))
            self.assertEqual(receipt["cents"], cents, amount)
        self.assertEqual(self.query("SELECT cents FROM payments WHERE payment_id='A-0'"), [(29,)])

    def test_invalid_amounts_rejected(self):
        before = self.snapshot()
        for amount in ["0.00", "1", "1.5", "1.000", "-1.00", "+1.00", "1e2", " 1.00", "1,000.00",
                       "\uff11.00", ".50", "92233720368547758.08", ""]:
            with self.assertRaises(InvalidPayment, msg=amount):
                apply_payment(self.db, row("BAD", amount=amount))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_timestamps_rejected(self):
        for paid_at in ["2026-04-30T09:00:00", "2026-04-30T09:00:00+00:00", "2026-04-30T09:00:00z",
                        "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-04-30T25:00:00Z",
                        "2026-04-30Z", "not a dateZ", "2026-04-30 09:00:00Z"]:
            with self.assertRaises(InvalidPayment, msg=paid_at):
                apply_payment(self.db, row("BAD", paid_at=paid_at))
        apply_payment(self.db, row("FRAC", paid_at="2026-04-30T09:00:00.123Z"))

    def test_missing_or_extra_fields_rejected(self):
        bad = row()
        del bad["amount"]
        with self.assertRaises(InvalidPayment):
            apply_payment(self.db, bad)
        with self.assertRaises(InvalidPayment):
            apply_payment(self.db, row() | {"extra": "x"})
        with self.assertRaises(InvalidPayment):
            apply_payment(self.db, row(payment_id=""))


class ApplyPaymentTests(Base):
    def test_invoice_ids_are_not_numerically_normalized(self):
        a = apply_payment(self.db, row("P-A", invoice_id="00123"))
        b = apply_payment(self.db, row("P-B", invoice_id="123"))
        self.assertEqual((a["invoice_id"], b["invoice_id"]), ("00123", "123"))
        self.assertEqual(self.query("SELECT invoice_id FROM payments WHERE payment_id IN ('P-A','P-B') "
                                    "ORDER BY payment_id"), [("00123",), ("123",)])
        with self.assertRaises(UnknownInvoice):
            apply_payment(self.db, row("P-C", invoice_id="0123"))
        with self.assertRaises(UnknownInvoice):
            apply_payment(self.db, row("P-D", invoice_id="inv-9"))

    def test_same_time_and_amount_is_not_a_duplicate(self):
        apply_payment(self.db, row("P-002", invoice_id="123"))
        self.assertIn(("north", "P-002", "123", T, 2500), self.payments())
        self.assertEqual(len(self.payments()), 2)

    def test_tenant_is_part_of_the_key(self):
        receipt = apply_payment(self.db, row("P-001", tenant="south"))
        self.assertEqual(receipt["tenant"], "south")
        self.assertEqual(len(self.payments()), 2)

    def test_exact_retry_returns_original_receipt_without_hook(self):
        calls = []
        first = apply_payment(self.db, row(), lambda: calls.append(1))
        again = apply_payment(self.db, row(), lambda: calls.append(2))
        self.assertEqual(first, again)
        self.assertEqual(first, {"tenant": "north", "payment_id": "P-100", "invoice_id": "00123", "cents": 2500})
        self.assertEqual(calls, [1])
        seeded = apply_payment(self.db, row("P-001"), lambda: calls.append(3))
        self.assertEqual(seeded, {"tenant": "north", "payment_id": "P-001", "invoice_id": "00123", "cents": 2500})
        self.assertEqual(calls, [1])

    def test_key_reuse_with_different_row_is_error(self):
        apply_payment(self.db, row())
        before = self.snapshot()
        for changed in [row(amount="25.01"), row(invoice_id="123"), row(paid_at="2026-04-30T09:00:01Z")]:
            with self.assertRaises(PaymentConflict):
                apply_payment(self.db, changed)
        with self.assertRaises(PaymentConflict):
            apply_payment(self.db, row("P-001", amount="1.00"))
        self.assertEqual(self.snapshot(), before)

    def test_failed_row_consumes_no_id(self):
        with self.assertRaises(UnknownInvoice):
            apply_payment(self.db, row("P-200", invoice_id="NOPE"))
        with self.assertRaises(InvalidPayment):
            apply_payment(self.db, row("P-200", amount="0.00"))
        self.assertEqual(self.query("SELECT * FROM receipts WHERE payment_id='P-200'"), [])
        self.assertEqual(self.query("SELECT * FROM payments WHERE payment_id='P-200'"), [])
        self.assertEqual(apply_payment(self.db, row("P-200"))["payment_id"], "P-200")

    def test_hook_runs_after_payment_and_receipt_commit(self):
        seen = []

        def hook():
            other = sqlite3.connect(self.db)
            try:
                seen.append(other.execute(
                    "SELECT (SELECT count(*) FROM payments WHERE payment_id='P-100'),"
                    "(SELECT count(*) FROM receipts WHERE payment_id='P-100')").fetchone())
            finally:
                other.close()
        apply_payment(self.db, row(), hook)
        self.assertEqual(seen, [(1, 1)])

    def test_hook_failure_propagates_and_retry_recovers(self):
        def boom():
            raise RuntimeError("connection reset")
        p3 = row("P-003", invoice_id="INV-9", amount="19.99")
        with self.assertRaisesRegex(RuntimeError, "connection reset"):
            apply_payment(self.db, p3, boom)
        self.assertEqual(self.query("SELECT count(*) FROM payments WHERE payment_id='P-003'"), [(1,)])
        self.assertEqual(self.query("SELECT count(*) FROM receipts WHERE payment_id='P-003'"), [(1,)])
        calls = []
        receipt = apply_payment(self.db, p3, lambda: calls.append(1))
        self.assertEqual(receipt, {"tenant": "north", "payment_id": "P-003", "invoice_id": "INV-9", "cents": 1999})
        self.assertEqual(calls, [])

    def test_legacy_payment_without_receipt_is_recovered_only_if_identical(self):
        db = sqlite3.connect(self.db)
        with db:
            db.execute("INSERT INTO payments VALUES ('north','P-ORPHAN','INV-9',?,500)", (T,))
            db.execute("INSERT INTO payments VALUES ('north','P-OTHER','INV-9',?,500)", (T,))
        db.close()
        receipt = apply_payment(self.db, row("P-ORPHAN", invoice_id="INV-9", amount="5.00"))
        self.assertEqual(receipt["cents"], 500)
        self.assertEqual(self.query("SELECT count(*) FROM receipts WHERE payment_id='P-ORPHAN'"), [(1,)])
        with self.assertRaises(PaymentConflict):
            apply_payment(self.db, row("P-OTHER", invoice_id="INV-9", amount="5.01"))
        self.assertEqual(self.query("SELECT cents FROM payments WHERE payment_id='P-OTHER'"), [(500,)])
        self.assertEqual(self.query("SELECT count(*) FROM receipts WHERE payment_id='P-OTHER'"), [(0,)])

    def test_missing_database_is_not_created(self):
        missing = self.tmp / "nope.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            apply_payment(missing, row())
        self.assertFalse(missing.exists())

    def test_waits_for_busy_writer(self):
        blocker = sqlite3.connect(self.db, isolation_level=None, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")
        timer = threading.Timer(0.5, lambda: blocker.execute("COMMIT"))
        timer.start()
        try:
            apply_payment(self.db, row("P-BUSY"))
        finally:
            timer.join()
            blocker.close()
        self.assertEqual(self.query("SELECT count(*) FROM receipts WHERE payment_id='P-BUSY'"), [(1,)])

    def test_independent_processes_racing_same_key(self):
        ctx = multiprocessing.get_context("spawn")
        n = 8
        barrier, queue = ctx.Barrier(n), ctx.Queue()
        counter = self.tmp / "hook-count"
        procs = [ctx.Process(target=_race_worker, args=(str(self.db), str(counter), barrier, queue))
                 for _ in range(n)]
        for p in procs:
            p.start()
        results = [queue.get(timeout=120) for _ in range(n)]
        for p in procs:
            p.join(60)
        self.assertTrue(all(status == "ok" for status, _ in results), results)
        self.assertEqual(len({json.dumps(r, sort_keys=True) for _, r in results}), 1)
        self.assertEqual(self.query("SELECT count(*) FROM payments WHERE payment_id='P-RACE'"), [(1,)])
        self.assertEqual(self.query("SELECT count(*) FROM receipts WHERE payment_id='P-RACE'"), [(1,)])
        self.assertEqual(counter.read_text(), "x")


class CliTests(Base):
    def test_supplied_export(self):
        before_receipt = self.query("SELECT * FROM receipts WHERE tenant='north' AND payment_id='P-001'")
        proc, report = self.cli(input_path=ROOT / "data" / "payments.csv")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([r["line"] for r in report["rows"]], list(range(2, 9)))
        self.assertEqual((report["ok"], report["errors"]), (7, 0))
        self.assertEqual([r["receipt"]["cents"] for r in report["rows"]], [2500, 2500, 1999, 2500, 2500, 29, 10001])
        self.assertEqual(self.payments(), sorted([
            ("north", "P-001", "00123", T, 2500), ("north", "P-002", "123", T, 2500),
            ("north", "P-003", "INV-9", "2026-04-30T09:01:00Z", 1999),
            ("south", "P-001", "00123", T, 2500),
            ("north", "P-004", "00123", "2026-04-30T09:02:00Z", 29),
            ("north", "P-005", "INV-9", "2026-04-30T09:03:00Z", 10001)]))
        self.assertEqual(self.query("SELECT * FROM receipts WHERE tenant='north' AND payment_id='P-001'"),
                         before_receipt)
        snapshot = self.snapshot()
        proc2, report2 = self.cli(input_path=ROOT / "data" / "payments.csv")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(report2, report)
        self.assertEqual(self.snapshot(), snapshot)

    def test_error_rows_are_reported_in_order_and_nothing_skipped(self):
        text = HEADER + "".join([
            f"north,E-1,00123,{T},1.00\n",
            f"north,E-2,MISSING,{T},1.00\n",
            f"north,E-3,00123,{T},1.0\n",
            f"north,E-4,00123,2026-04-30T09:00:00,1.00\n",
            f"north,E-1,00123,{T},2.00\n",
            f"north,P-001,123,{T},25.00\n",
            f"north,E-5,00123,{T}\n",
            f"north,E-6,00123,{T},1.00,extra\n",
            f"north,E-2,00123,{T},3.00\n",
        ])
        proc, report = self.cli(text)
        self.assertEqual(proc.returncode, 1)
        statuses = [(r["line"], r["status"]) for r in report["rows"]]
        self.assertEqual(statuses, [(2, "ok"), (3, "error"), (4, "error"), (5, "error"), (6, "error"),
                                    (7, "error"), (8, "error"), (9, "error"), (10, "ok")])
        self.assertEqual((report["ok"], report["errors"]), (2, 7))
        for r in report["rows"]:
            if r["status"] == "error":
                self.assertNotIn("receipt", r)
                self.assertIsInstance(r["error"], str)
                self.assertTrue(r["error"].strip())
            else:
                self.assertIn("receipt", r)
        self.assertEqual(self.query("SELECT payment_id,cents FROM payments WHERE payment_id LIKE 'E-%' "
                                    "ORDER BY payment_id"), [("E-1", 100), ("E-2", 300)])

    def test_first_row_in_input_order_wins_for_duplicate_keys(self):
        lines = "".join(f"north,K-{i},00123,{T},{i}.00\n" for i in range(1, 30))
        lines += "".join(f"north,K-{i},00123,{T},{i}.99\n" for i in range(1, 30))
        proc, report = self.cli(HEADER + lines)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual([r["line"] for r in report["rows"]], list(range(2, 2 + 58)))
        self.assertTrue(all(r["status"] == "ok" for r in report["rows"][:29]))
        self.assertTrue(all(r["status"] == "error" for r in report["rows"][29:]))
        self.assertEqual(self.query("SELECT cents FROM payments WHERE payment_id='K-7'"), [(700,)])

    def test_line_numbers_follow_physical_lines(self):
        text = HEADER + f'north,"Q-1",00123,{T},1.00\n\nnorth,Q-2,MISSING,{T},1.00\n'
        proc, report = self.cli(text)
        self.assertEqual([(r["line"], r["status"]) for r in report["rows"]], [(2, "ok"), (4, "error")])

    def test_reordered_header_and_bom_accepted(self):
        proc, report = self.cli("\ufeffamount,tenant,payment_id,invoice_id,paid_at\n"
                                f"5.00,north,H-1,INV-9,{T}\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(report["rows"][0]["receipt"], {"tenant": "north", "payment_id": "H-1",
                                                       "invoice_id": "INV-9", "cents": 500})

    def test_malformed_files_fail_with_diagnostic_and_change_nothing(self):
        before = self.snapshot()
        cases = {
            "empty": "",
            "bad header": f"tenant,payment,invoice,paid_at,amount\nnorth,X,00123,{T},1.00\n",
            "missing column": f"tenant,payment_id,invoice_id,paid_at\nnorth,X,00123,{T}\n",
            "duplicate column": "tenant,payment_id,invoice_id,paid_at,amount,amount\n",
            "bad quoting": HEADER + f'north,"X"y,00123,{T},1.00\n',
            "nul byte": HEADER + f"north,X\0,00123,{T},1.00\n",
            "not utf8": (HEADER + f"north,X\xff,00123,{T},1.00\n").encode("latin-1"),
        }
        for name, text in cases.items():
            report = self.tmp / f"r-{name}.json"
            proc, data = self.cli(text, report=report)
            self.assertNotEqual(proc.returncode, 0, name)
            self.assertTrue(proc.stderr.strip(), name)
            self.assertNotIn("Traceback", proc.stderr, name)
            self.assertIsNone(data, name)
        proc, _ = self.cli(input_path=self.tmp / "does-not-exist.csv")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(proc.stderr.strip())
        self.assertEqual(self.snapshot(), before)

    def test_missing_database_fails_without_creating_it(self):
        missing = self.tmp / "missing.sqlite"
        proc, data = self.cli(HEADER + f"north,X,00123,{T},1.00\n", db=missing)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(proc.stderr.strip())
        self.assertFalse(missing.exists())

    def test_report_written_atomically_without_temp_leftovers(self):
        report = self.tmp / "a" / "b" / "report.json"
        proc, data = self.cli(HEADER + f"north,R-1,00123,{T},1.00\n", report=report)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(os.listdir(report.parent), ["report.json"])
        self.assertEqual(data, {"rows": [{"line": 2, "status": "ok", "receipt": {
            "cents": 100, "invoice_id": "00123", "payment_id": "R-1", "tenant": "north"}}], "ok": 1, "errors": 0})

    def test_worker_exceptions_are_reported_not_swallowed(self):
        input_path = self.tmp / "in.csv"
        input_path.write_text(HEADER + f"north,W-1,00123,{T},1.00\nnorth,W-2,00123,{T},1.00\n")
        original = import_payments.apply_payment

        def flaky(db_path, row, after_commit=None):
            if row["payment_id"] == "W-2":
                raise RuntimeError("worker exploded")
            return original(db_path, row, after_commit)
        import_payments.apply_payment = flaky
        report = self.tmp / "w.json"
        stderr = sys.stderr
        try:
            with open(os.devnull, "w") as devnull:
                sys.stderr = devnull
                code = import_payments.run(self.db, input_path, report)
        finally:
            sys.stderr = stderr
            import_payments.apply_payment = original
        data = json.loads(report.read_text())
        self.assertEqual(code, 1)
        self.assertEqual((data["ok"], data["errors"]), (1, 1))
        self.assertIn("worker exploded", data["rows"][1]["error"])

    def test_concurrent_cli_processes_and_rerun_after_partial_success(self):
        apply_payment(self.db, row("P-003", invoice_id="INV-9", paid_at="2026-04-30T09:01:00Z", amount="19.99"))
        cmd = [sys.executable, str(ROOT / "import_payments.py"), "--db", str(self.db),
               "--input", str(ROOT / "data" / "payments.csv")]
        procs = [subprocess.Popen(cmd + ["--report", str(self.tmp / f"c{i}.json")],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
        for p in procs:
            p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0)
        self.assertEqual(len(self.payments()), 6)
        self.assertEqual(self.query("SELECT count(*) FROM receipts"), [(6,)])
        reports = [json.loads((self.tmp / f"c{i}.json").read_text()) for i in range(4)]
        self.assertTrue(all(r == reports[0] for r in reports))


class CompatibilityTests(unittest.TestCase):
    def test_existing_receipt_fingerprint_matches_importer(self):
        value = {"tenant": "north", "payment_id": "P-001", "invoice_id": "00123", "paid_at": T, "cents": 2500}
        self.assertEqual(import_payments.fingerprint_of(value),
                         "e858e1e5f2860efd2213aa39228cb99d754ab2d12d142f5f751a80c7c66f7147")
        self.assertTrue(issubclass(PaymentConflict, PaymentError) and issubclass(PaymentError, ValueError))


if __name__ == "__main__":
    unittest.main()
