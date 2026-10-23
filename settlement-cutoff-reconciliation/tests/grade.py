import csv
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import traceback
from reference import expected

ROOT = Path("/app")
checks = {}


def verify_output(folder, reference):
    for name in ("settlements", "aging"):
        with (folder / f"{name}.csv").open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(reference[name]), f"{name} row count"
        for actual, wanted in zip(rows, reference[name]):
            for field, value in wanted.items():
                found = int(actual[field]) if type(value) is int else actual[field]
                assert found == value, f"{name} {wanted} field {field}: {found} != {value}"
    assert json.loads((folder / "summary.json").read_text()) == reference["summary"]


def delivered():
    ref = expected(ROOT / "data")
    assert ref["summary"]["expected_deposits_cents"] == 36265
    assert ref["summary"]["open_receivables_cents"] == 29500
    assert ref["summary"]["overdue_receivables_cents"] == 12000
    verify_output(ROOT / "submission/close", ref)
    assert (ROOT / "submission/REPAIR_REPORT.md").read_text().strip()


def replay(variant):
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "data"
        output = Path(tmp) / "result"
        shutil.copytree(ROOT / "data", source)
        rng = random.Random(451 + variant)
        for file in source.glob("*.csv"):
            with file.open() as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames
                rows = list(reader)
            if variant >= 2:
                for row in rows:
                    if "merchant" in row:
                        row["merchant"] = {"north": "orchard", "south": "harbor"}[row["merchant"]]
                    if "invoice_id" in row:
                        row["invoice_id"] = "acct-" + row["invoice_id"]
                    for field in ("amount_cents", "opening_cents"):
                        if field in row:
                            row[field] = str(int(row[field]) * (variant + 1))
            if variant == 4 and file.name == "invoices.csv":
                for row in rows:
                    row["terms_days"] = str(int(row["terms_days"]) + 20)
            if variant == 5 and file.name == "events.csv":
                newest = dict(next(row for row in rows if row["event_id"] == "S1" and row["merchant"] == "orchard"))
                newest.update(version="9", effective_at="2026-06-01T00:00:00Z", recorded_at="2026-04-30T22:00:00Z")
                rows.append(newest)
            rng.shuffle(rows)
            with file.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        if variant == 3:
            (source / "cutoff.json").write_text('{"cutoff":"2026-05-03T23:59:59Z"}')
        ref = expected(source)
        for _ in range(2):
            result = subprocess.run(["python", str(ROOT / "submission/reconcile.py"), "--input", str(source),
                                     "--output", str(output)], capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr.decode()
            verify_output(output, ref)


for name, function in [("delivered", delivered)] + [(f"variant_{i}", lambda i=i: replay(i)) for i in range(1, 6)]:
    try:
        function()
        checks[name] = {"passed": True}
    except Exception:
        checks[name] = {"passed": False, "detail": traceback.format_exc()}
out = Path("/logs/verifier")
out.mkdir(parents=True, exist_ok=True)
(out / "details.json").write_text(json.dumps(checks, indent=2))
reward = {k: float(v["passed"]) for k, v in checks.items()}
reward["overall"] = float(all(reward.values()))
(out / "reward.json").write_text(json.dumps(reward, indent=2))
print(json.dumps(reward))
raise SystemExit(0 if reward["overall"] else 1)
