import csv
import importlib.util
import json
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import traceback

ROOT = Path("/app")
spec = importlib.util.spec_from_file_location("candidate", ROOT / "import_payments.py")
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
checks = {}


def check(name, function):
    try:
        function()
        checks[name] = {"passed": True}
    except Exception:
        checks[name] = {"passed": False, "detail": traceback.format_exc()}


def seed(path):
    subprocess.run(["python", str(ROOT / "tools/seed.py"), "--db", str(path)], check=True, capture_output=True)


def rows(path, table):
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()


def payment(key="new", invoice="00123", amount="0.29", tenant="north"):
    return {"tenant": tenant, "payment_id": key, "invoice_id": invoice,
            "paid_at": "2026-04-30T10:00:00Z", "amount": amount}


def expect_error(function):
    try:
        function()
    except Exception:
        return
    raise AssertionError("Expected explicit error")


def cli(path, values, folder):
    source = folder / "input.csv"
    report = folder / "report.json"
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
    process = subprocess.run(["python", str(ROOT / "import_payments.py"), "--db", str(path),
                              "--input", str(source), "--report", str(report)], capture_output=True, timeout=30)
    return process.returncode, json.loads(report.read_text())


def delivered():
    with (ROOT / "data/payments.csv").open() as f:
        inputs = list(csv.DictReader(f))
    expected = {(r["tenant"], r["payment_id"], r["invoice_id"], r["paid_at"],
                 int(r["amount"].replace(".", ""))) for r in inputs}
    assert set(rows(ROOT / "state/payments.sqlite", "payments")) == expected
    report = json.loads((ROOT / "submission/import-report.json").read_text())
    assert report["ok"] == 7 and report["errors"] == 0
    assert len(report["rows"]) == 7
    for i, (actual, original) in enumerate(zip(report["rows"], inputs), 2):
        assert actual["line"] == i and actual["status"] == "ok"
        assert actual["receipt"] == {k: original[k] for k in ("tenant", "payment_id", "invoice_id")} | {
            "cents": int(original["amount"].replace(".", ""))}
    with tempfile.TemporaryDirectory() as tmp:
        original = Path(tmp) / "seed.db"
        seed(original)
        assert rows(original, "invoices") == rows(ROOT / "state/payments.sqlite", "invoices")
        receipt = rows(original, "receipts")[0]
        assert receipt in rows(ROOT / "state/payments.sqlite", "receipts")


def semantics():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        path = folder / "db"
        seed(path)
        values = [payment("a", "00123"), payment("b", "123"), payment("a", tenant="south")]
        for row in values:
            result = candidate.apply_payment(path, row)
            assert result == {k: row[k] for k in ("tenant", "payment_id", "invoice_id")} | {"cents": 29}
            assert candidate.apply_payment(path, dict(reversed(list(row.items())))) == result
        expect_error(lambda: candidate.apply_payment(path, payment("a", amount="0.30")))
        assert len(rows(path, "payments")) == 4


def lost_response():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db"
        seed(path)
        def hook():
            raise RuntimeError("lost response")
        expect_error(lambda: candidate.apply_payment(path, payment(), after_commit=hook))
        assert len(rows(path, "payments")) == len(rows(path, "receipts")) == 2
        result = candidate.apply_payment(path, payment(), after_commit=hook)
        assert result["cents"] == 29
        assert len(rows(path, "payments")) == 2


def invalid_rows():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        path = folder / "db"
        seed(path)
        code, report = cli(path, [payment("good"), payment("bad", "unknown"), payment("last", amount="12.34")], folder)
        assert code == 1 and report["ok"] == 2 and report["errors"] == 1
        assert [r["status"] for r in report["rows"]] == ["ok", "error", "ok"]
        assert report["rows"][1].get("error")
        assert len(rows(path, "payments")) == 3
        assert candidate.apply_payment(path, payment("bad"))["cents"] == 29
        for amount in ("NaN", "-1.00", "0.00", "1.005"):
            expect_error(lambda: candidate.apply_payment(path, payment("invalid", amount=amount)))
        assert len(rows(path, "payments")) == 4
        before = rows(path, "payments")
        code, report = cli(path, [payment("last", amount="12.34"), payment("good")], folder)
        assert code == 0 and report["ok"] == 2
        assert rows(path, "payments") == before


def worker(path, barrier, queue):
    try:
        barrier.wait(timeout=15)
        queue.put(candidate.apply_payment(path, payment("race")))
    except Exception as exc:
        queue.put({"error": repr(exc)})


def concurrent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db"
        seed(path)
        ctx = multiprocessing.get_context("fork")
        barrier, queue = ctx.Barrier(4), ctx.Queue()
        processes = [ctx.Process(target=worker, args=(path, barrier, queue)) for _ in range(4)]
        try:
            for p in processes:
                p.start()
            results = [queue.get(timeout=30) for _ in processes]
            assert all(r == results[0] and "error" not in r for r in results), results
            for p in processes:
                p.join(5)
                assert p.exitcode == 0
            assert len(rows(path, "payments")) == len(rows(path, "receipts")) == 2
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()
                    p.join()
            queue.close()


def artifacts():
    assert (ROOT / "submission/REPAIR_REPORT.md").read_text().strip()
    tests = list((ROOT / "tests").glob("test*.py"))
    assert tests, "Missing regression tests"
    result = subprocess.run(["python", "-m", "unittest", "discover", "-s", str(ROOT / "tests")],
                            cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()


for name, function in [("delivered", delivered), ("identity_and_cents", semantics),
                       ("lost_response", lost_response), ("error_reporting", invalid_rows),
                       ("concurrency", concurrent), ("artifacts", artifacts)]:
    check(name, function)
output = Path("/logs/verifier")
output.mkdir(parents=True, exist_ok=True)
(output / "details.json").write_text(json.dumps(checks, indent=2))
reward = {k: float(v["passed"]) for k, v in checks.items()}
reward["overall"] = float(all(reward.values()))
(output / "reward.json").write_text(json.dumps(reward, indent=2))
print(json.dumps(reward))
raise SystemExit(0 if reward["overall"] else 1)
