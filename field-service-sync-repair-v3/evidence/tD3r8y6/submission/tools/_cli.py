"""Shared command-line plumbing for maintenance tools."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.codec import SyncError  # noqa: E402
from server.store import Store  # noqa: E402


def run(path, action):
    """Open an EXISTING database, run action(store) and print its JSON result."""
    try:
        if not Path(path).is_file():
            raise FileNotFoundError(f"database not found: {path}")
        result = action(Store(path))
    except SyncError as exc:
        print(f"error: {exc.code} {json.dumps(exc.detail, ensure_ascii=False)}", file=sys.stderr)
        return 2
    except Exception as exc:  # report every other failure as a diagnostic
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0
