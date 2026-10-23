import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.store import Store


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    print(json.dumps(Store(args.db).compact(args.through)))
