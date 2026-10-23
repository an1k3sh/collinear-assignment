import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


def normalized(row):
    if set(row) != {"tenant", "payment_id", "invoice_id", "paid_at", "amount"}:
        raise ValueError("Incorrect payment columns")
    if any(not isinstance(value, str) or not value for value in row.values()):
        raise ValueError("Empty or invalid payment field")
    if not re.fullmatch(r"[0-9]+\.[0-9]{2}", row["amount"]):
        raise ValueError("Amount must have two decimal places")
    dollars, pennies = row["amount"].split(".")
    cents = int(dollars) * 100 + int(pennies)
    if not 0 < cents <= 9223372036854775807:
        raise ValueError("Amount outside supported range")
    if not row["paid_at"].endswith("Z"):
        raise ValueError("Timestamp must be UTC")
    datetime.fromisoformat(row["paid_at"].replace("Z", "+00:00"))
    return {key: row[key] for key in ("tenant", "payment_id", "invoice_id", "paid_at")} | {"cents": cents}


def apply_payment(db_path, row, after_commit=None):
    value = normalized(row)
    fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    db = sqlite3.connect(db_path, timeout=20)
    try:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT fingerprint,response FROM receipts WHERE tenant=? AND payment_id=?",
            (value["tenant"], value["payment_id"])).fetchone()
        if previous:
            if previous[0] != fingerprint:
                raise ValueError("Payment ID reused with different content")
            return json.loads(previous[1])
        if not db.execute("SELECT 1 FROM invoices WHERE tenant=? AND invoice_id=?",
                          (value["tenant"], value["invoice_id"])).fetchone():
            raise ValueError("Unknown invoice")
        receipt = {key: value[key] for key in ("tenant", "payment_id", "invoice_id", "cents")}
        db.execute("INSERT INTO payments VALUES (?,?,?,?,?)",
                   tuple(value[key] for key in ("tenant", "payment_id", "invoice_id", "paid_at", "cents")))
        db.execute("INSERT INTO receipts VALUES (?,?,?,?)",
                   (value["tenant"], value["payment_id"], fingerprint, json.dumps(receipt, sort_keys=True)))
        db.commit()
    finally:
        db.close()
    if after_commit:
        after_commit()
    return receipt


def run(db_path, input_path, report_path):
    with open(input_path, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["tenant", "payment_id", "invoice_id", "paid_at", "amount"]:
            raise ValueError("Incorrect CSV header")
        rows = list(reader)

    def process(item):
        line, row = item
        try:
            return {"line": line, "status": "ok", "receipt": apply_payment(db_path, row)}
        except (ValueError, sqlite3.Error) as exc:
            return {"line": line, "status": "error", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=4) as workers:
        outcomes = list(workers.map(process, enumerate(rows, 2)))
    errors = sum(item["status"] == "error" for item in outcomes)
    result = {"rows": outcomes, "ok": len(outcomes) - errors, "errors": errors}
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False, encoding="utf-8") as file:
            name = file.name
            json.dump(result, file, indent=2)
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.db, args.input, args.report))
