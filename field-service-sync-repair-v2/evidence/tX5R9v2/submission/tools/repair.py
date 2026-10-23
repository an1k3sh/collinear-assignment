"""Rebuild the materialized work-order projection from immutable event history.

Usage: python3 tools/repair.py --db PATH

The repair runs in one write transaction; events, receipts, batches and the
database epoch are never modified. It is idempotent.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    if not Path(args.db).is_file():
        parser.error(f"database does not exist: {args.db}")
    print(json.dumps(Store(args.db).repair_projection()))


if __name__ == "__main__":
    main()
