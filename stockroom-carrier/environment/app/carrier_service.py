"""Immutable, deterministic local stand-in for an independently committed carrier."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid


RECORD_FIELDS = ("receipt", "warehouse", "sku_a", "qty_a", "sku_b", "qty_b")
MODES = {"ack", "accept_then_timeout_once", "timeout_before_once", "reject"}


def accepted_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["qty_a"] = int(record["qty_a"])
    record["qty_b"] = int(record["qty_b"])
    return record


class CarrierFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Carrier:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"Carrier database does not exist: {self.path}")
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE name='service_id'").fetchone()
            if row is None or not isinstance(row[0], str) or not row[0]:
                raise OSError("Carrier database has no service identity")
            self.service_id = row[0]

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def lookup(self, key: str) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT receipt,warehouse,sku_a,qty_a,sku_b,qty_b "
                "FROM accepted WHERE request_key=?", (key,)).fetchone()
            return accepted_record(row) if row is not None else None

    def submit(self, key: str, warehouse: str, sku_a: str, qty_a: int,
               sku_b: str, qty_b: int) -> str:
        if any(not isinstance(value, str) or not value
               for value in (key, warehouse, sku_a, sku_b)):
            raise CarrierFailure("NAME", "Names must be nonempty")
        if any(type(value) is not int or value <= 0 for value in (qty_a, qty_b)):
            raise CarrierFailure("QUANTITY", "Quantities must be positive integers")
        payload = (warehouse, sku_a, qty_a, sku_b, qty_b)
        failure = None
        with closing(self.connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT receipt,warehouse,sku_a,qty_a,sku_b,qty_b "
                    "FROM accepted WHERE request_key=?", (key,)).fetchone()
                if existing is not None:
                    receipt = existing["receipt"]
                    record = accepted_record(existing)
                    if tuple(record[field] for field in RECORD_FIELDS[1:]) == payload:
                        outcome = "replayed"
                    else:
                        outcome = "conflict"
                        failure = CarrierFailure("CARRIER_CONFLICT", "Key already has another payload")
                else:
                    row = connection.execute(
                        "SELECT mode FROM policies WHERE request_key=?", (key,)).fetchone()
                    mode = row[0] if row is not None else "ack"
                    prior = connection.execute(
                        "SELECT COUNT(*) FROM attempts WHERE request_key=?", (key,)).fetchone()[0]
                    receipt = ""
                    if mode == "reject":
                        outcome = "rejected"
                        failure = CarrierFailure("CARRIER_REJECTED", "Carrier rejected shipment")
                    elif mode == "timeout_before_once" and prior == 0:
                        outcome = "timeout_before_accept"
                        failure = CarrierFailure("CARRIER_TIMEOUT", "No transport response")
                    else:
                        receipt = "rcpt-" + uuid.uuid5(
                            uuid.NAMESPACE_URL, self.service_id + "\0" + key).hex
                        connection.execute(
                            "INSERT INTO accepted VALUES (?,?,?,?,?,?,?)",
                            (key, receipt, warehouse, sku_a, str(qty_a), sku_b, str(qty_b)))
                        outcome = "accepted"
                        if mode == "accept_then_timeout_once" and prior == 0:
                            outcome = "timeout_after_accept"
                            failure = CarrierFailure("CARRIER_TIMEOUT", "No transport response")
                connection.execute(
                    "INSERT INTO attempts(request_key,outcome) VALUES (?,?)", (key, outcome))
        if failure is not None:
            raise failure
        return receipt


def initialize(seed: Path, database: Path) -> None:
    data = json.loads(seed.read_text(encoding="utf-8"))
    if database.exists():
        raise FileExistsError(f"Refusing to overwrite carrier: {database}")
    if (not isinstance(data.get("service_id"), str) or not data["service_id"]
            or not isinstance(data.get("policies"), dict)
            or any(mode not in MODES for mode in data["policies"].values())):
        raise ValueError("Invalid carrier seed")
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript("""
                CREATE TABLE metadata(name TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE policies(request_key TEXT PRIMARY KEY,mode TEXT NOT NULL);
                CREATE TABLE accepted(
                    request_key TEXT PRIMARY KEY,receipt TEXT UNIQUE NOT NULL,
                    warehouse TEXT NOT NULL,sku_a TEXT NOT NULL,qty_a TEXT NOT NULL,
                    sku_b TEXT NOT NULL,qty_b TEXT NOT NULL);
                CREATE TABLE attempts(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_key TEXT NOT NULL,outcome TEXT NOT NULL);
            """)
            connection.execute("INSERT INTO metadata VALUES ('service_id',?)", (data["service_id"],))
            connection.executemany("INSERT INTO policies VALUES (?,?)", data["policies"].items())
            for key, record in data.get("accepted", {}).items():
                connection.execute("INSERT INTO accepted VALUES (?,?,?,?,?,?,?)",
                                   (key, record["receipt"], record["warehouse"],
                                    record["sku_a"], str(record["qty_a"]),
                                    record["sku_b"], str(record["qty_b"])))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["initialize"])
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    initialize(args.seed, args.database)


if __name__ == "__main__":
    main()
