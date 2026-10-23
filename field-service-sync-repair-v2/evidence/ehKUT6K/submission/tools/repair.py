"""Rebuild the materialized documents projection from the immutable event history.

Usage: python3 tools/repair.py --db PATH

The repair runs in one IMMEDIATE transaction: documents are rebuilt from each
tenant/id's latest event; events, receipts, batches and the epoch are untouched.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.store import Store

REQUIRED = {"metadata", "documents", "events", "receipts"}


def repair(path):
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f"repair: database not found: {path}")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        epochs = db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0] \
            if "metadata" in tables else 0
    finally:
        db.close()
    missing = REQUIRED - tables
    if missing:
        raise SystemExit(f"repair: not a work-order database, missing {sorted(missing)}")
    if epochs != 1:
        raise SystemExit("repair: metadata must contain exactly one epoch")
    return Store(path).repair_projection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    print(json.dumps(repair(parser.parse_args().db)))
