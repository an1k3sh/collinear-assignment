"""Prune event history at/before a sequence boundary, retaining anchors."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cli import run  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    sys.exit(run(args.db, lambda store: store.compact(args.through)))
