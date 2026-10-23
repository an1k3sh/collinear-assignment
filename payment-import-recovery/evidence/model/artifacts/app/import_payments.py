import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import traceback

COLUMNS = ("tenant", "payment_id", "invoice_id", "paid_at", "amount")
MAX_CENTS = 9223372036854775807
BUSY_TIMEOUT_SECONDS = 30
AMOUNT_RE = re.compile(r"([0-9]{1,19})\.([0-9]{2})", re.ASCII)
TIMESTAMP_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})"
    r"(?::([0-9]{2})(?:\.([0-9]{1,6}))?)?Z", re.ASCII)


class PaymentError(ValueError):
    """A row that cannot be applied; nothing was written for it."""


class InvalidPayment(PaymentError):
    pass


class UnknownInvoice(PaymentError):
    pass


class PaymentConflict(PaymentError):
    pass


class InputFileError(Exception):
    """The whole input file is malformed."""


def _cents(amount):
    match = AMOUNT_RE.fullmatch(amount)
    if not match:
        raise InvalidPayment(
            f"Invalid amount {amount!r}: expected a positive decimal with exactly two fractional digits")
    cents = int(match.group(1)) * 100 + int(match.group(2))
    if not 0 < cents <= MAX_CENTS:
        raise InvalidPayment(f"Amount {amount!r} outside supported range")
    return cents


def _check_timestamp(paid_at):
    match = TIMESTAMP_RE.fullmatch(paid_at)
    if not match:
        raise InvalidPayment(f"Invalid paid_at {paid_at!r}: expected ISO-8601 UTC timestamp ending in Z")
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0),
                 int((fraction or "0").ljust(6, "0")), tzinfo=timezone.utc)
    except ValueError as exc:
        raise InvalidPayment(f"Invalid paid_at {paid_at!r}: {exc}") from None


def normalized(row):
    if not isinstance(row, dict) or set(row) != set(COLUMNS):
        raise InvalidPayment(f"Incorrect payment columns: expected {', '.join(COLUMNS)}")
    for key in COLUMNS:
        if not isinstance(row[key], str) or not row[key]:
            raise InvalidPayment(f"Missing or empty {key}")
    _check_timestamp(row["paid_at"])
    # IDs are opaque, case-sensitive strings: never strip zeros or change case.
    return {"tenant": row["tenant"], "payment_id": row["payment_id"], "invoice_id": row["invoice_id"],
            "paid_at": row["paid_at"], "cents": _cents(row["amount"])}


def fingerprint_of(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _connect(db_path):
    # mode=rw: never create an empty database for a mistyped path.
    uri = Path(db_path).resolve().as_uri() + "?mode=rw"
    db = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_SECONDS * 1000}")
    return db


def apply_payment(db_path, row, after_commit=None):
    value = normalized(row)
    fingerprint = fingerprint_of(value)
    response = json.dumps({k: value[k] for k in ("tenant", "payment_id", "invoice_id", "cents")}, sort_keys=True)
    receipt = json.loads(response)
    key = (value["tenant"], value["payment_id"])
    db = _connect(db_path)
    try:
        # Take the write lock before reading so racing processes serialize on the key.
        db.execute("BEGIN IMMEDIATE")
        try:
            stored = db.execute("SELECT fingerprint,response FROM receipts WHERE tenant=? AND payment_id=?",
                                key).fetchone()
            payment = db.execute("SELECT invoice_id,paid_at,cents FROM payments WHERE tenant=? AND payment_id=?",
                                 key).fetchone()
            if stored:
                if stored[0] != fingerprint:
                    raise PaymentConflict(
                        f"Payment {value['payment_id']!r} for tenant {value['tenant']!r} was already "
                        "imported with different details")
                if payment is None:
                    raise PaymentConflict(
                        f"Receipt for payment {value['payment_id']!r} has no stored payment; refusing to modify")
                db.execute("ROLLBACK")
                return json.loads(stored[1])
            if payment is not None:
                # Payment without receipt (legacy partial write): adopt only if identical.
                if tuple(payment) != (value["invoice_id"], value["paid_at"], value["cents"]):
                    raise PaymentConflict(
                        f"Payment {value['payment_id']!r} for tenant {value['tenant']!r} was already "
                        "imported with different details")
                db.execute("INSERT INTO receipts VALUES (?,?,?,?)",
                           (*key, fingerprint, response))
                db.execute("COMMIT")
                return receipt
            if not db.execute("SELECT 1 FROM invoices WHERE tenant=? AND invoice_id=?",
                              (value["tenant"], value["invoice_id"])).fetchone():
                raise UnknownInvoice(
                    f"Unknown invoice {value['invoice_id']!r} for tenant {value['tenant']!r}")
            db.execute("INSERT INTO payments VALUES (?,?,?,?,?)",
                       (*key, value["invoice_id"], value["paid_at"], value["cents"]))
            db.execute("INSERT INTO receipts VALUES (?,?,?,?)",
                       (*key, fingerprint, response))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
    finally:
        db.close()
    if after_commit:
        after_commit()
    return receipt


def read_rows(input_path):
    """Return [(line, fields_dict, field_count)]; raise InputFileError for a malformed file."""
    try:
        with open(input_path, newline="", encoding="utf-8-sig") as source:
            text = source.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputFileError(str(exc)) from exc
    if "\0" in text:
        raise InputFileError("file contains NUL bytes; not a text CSV export")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise InputFileError("file is empty; expected header " + ",".join(COLUMNS))
        if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
            raise InputFileError(f"incorrect CSV header {header!r}; expected " + ",".join(COLUMNS))
        rows = []
        while True:
            line = reader.line_num + 1  # physical line where this record starts
            fields = next(reader, None)
            if fields is None:
                return rows
            if not fields:
                continue  # blank line, not a record
            row = {name: (fields[index] if index < len(fields) else None) for index, name in enumerate(header)}
            rows.append((line, row, len(fields)))
    except csv.Error as exc:
        raise InputFileError(f"line {reader.line_num}: {exc}") from exc


def _check_database(db_path):
    db = _connect(db_path)
    try:
        for table in ("invoices", "payments", "receipts"):
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchall()
    finally:
        db.close()


def _process(db_path, line, row, field_count, attempts=5):
    if field_count != len(COLUMNS):
        return {"line": line, "status": "error",
                "error": f"Expected {len(COLUMNS)} fields, found {field_count}"}
    for attempt in range(attempts):
        try:
            return {"line": line, "status": "ok", "receipt": apply_payment(db_path, row)}
        except PaymentError as exc:
            return {"line": line, "status": "error", "error": str(exc)}
        except sqlite3.OperationalError as exc:
            # apply_payment is idempotent, so retrying also recovers an ambiguous commit.
            if attempt + 1 < attempts:
                time.sleep(0.05 * (attempt + 1))
                continue
            return {"line": line, "status": "error", "error": f"Database error: {exc}"}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return {"line": line, "status": "error",
                    "error": f"Unexpected {type(exc).__name__}: {exc or 'no detail'}"}


def write_report(report_path, result):
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, prefix=f".{target.name}.",
                                         suffix=".tmp", delete=False, encoding="utf-8") as file:
            name = file.name
            json.dump(result, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        # NamedTemporaryFile is 0600; give the report ordinary file permissions.
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(name, 0o666 & ~umask)
        os.replace(name, target)
        name = None
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def run(db_path, input_path, report_path, max_workers=4):
    try:
        rows = read_rows(input_path)
    except InputFileError as exc:
        print(f"import_payments: malformed input {input_path}: {exc}", file=sys.stderr)
        return 2
    try:
        _check_database(db_path)
    except sqlite3.Error as exc:
        print(f"import_payments: cannot use database {db_path}: {exc}", file=sys.stderr)
        return 2

    # Rows sharing a key run sequentially in input order (first valid row wins);
    # distinct keys run concurrently.
    groups = {}
    for item in rows:
        groups.setdefault((item[1].get("tenant"), item[1].get("payment_id")), []).append(item)

    def process_group(items):
        return [_process(db_path, *item) for item in items]

    outcomes = []
    with ThreadPoolExecutor(max_workers=max_workers) as workers:
        futures = [workers.submit(process_group, items) for items in groups.values()]
        for future in futures:
            outcomes.extend(future.result())
    outcomes.sort(key=lambda item: item["line"])
    errors = sum(item["status"] == "error" for item in outcomes)
    result = {"rows": outcomes, "ok": len(outcomes) - errors, "errors": errors}
    write_report(report_path, result)
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.db, args.input, args.report))
