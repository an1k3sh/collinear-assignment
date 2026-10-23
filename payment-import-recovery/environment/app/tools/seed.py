import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3


def seed(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    source = Path(__file__).resolve().parents[1] / "data"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE invoices(tenant TEXT,invoice_id TEXT,due_cents INTEGER,PRIMARY KEY(tenant,invoice_id));
        CREATE TABLE payments(tenant TEXT,payment_id TEXT,invoice_id TEXT,paid_at TEXT,cents INTEGER,PRIMARY KEY(tenant,payment_id));
        CREATE TABLE receipts(tenant TEXT,payment_id TEXT,fingerprint TEXT,response TEXT,PRIMARY KEY(tenant,payment_id));
        """)
        with (source / "invoices.csv").open() as f:
            for row in csv.DictReader(f):
                db.execute("INSERT INTO invoices VALUES (?,?,?)",
                           (row["tenant"], row["invoice_id"], int(row["due_cents"])))
        value = {"tenant": "north", "payment_id": "P-001", "invoice_id": "00123",
                 "paid_at": "2026-04-30T09:00:00Z", "cents": 2500}
        response = {key: value[key] for key in ("tenant", "payment_id", "invoice_id", "cents")}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        db.execute("INSERT INTO payments VALUES (?,?,?,?,?)", tuple(value.values()))
        db.execute("INSERT INTO receipts VALUES (?,?,?,?)",
                   ("north", "P-001", digest, json.dumps(response, sort_keys=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    seed(parser.parse_args().db)
