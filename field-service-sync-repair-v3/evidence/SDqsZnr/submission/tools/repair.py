"""Transactionally rebuild the documents projection from anchors plus events."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.codec import SyncError
from server.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    if not Path(args.db).is_file():
        print(f"repair: database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        result = Store(args.db).repair_projection()
    except SyncError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
