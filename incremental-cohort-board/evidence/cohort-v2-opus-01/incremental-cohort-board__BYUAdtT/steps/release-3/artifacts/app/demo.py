"""Repeatable incident replay; do not edit."""
import argparse
import json
from pathlib import Path

from runtime import MODES, Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", required=True, type=int, choices=(1, 2, 3, 4))
    args = parser.parse_args()
    root = Path(__file__).parent
    (root / "state").mkdir(exist_ok=True)
    store = Store(root / "state" / "demo.sqlite")
    try:
        # Only add modes, including when an older release is replayed again.
        wanted = MODES[: max(args.through, len(store.modes))]
        store.upgrade(wanted)
        for release in range(1, args.through + 1):
            batches = json.loads(
                (root / "incidents" / f"release-{release}.json").read_text()
            )
            for batch in batches:
                store.apply(batch["id"], batch["mutations"])
        print(json.dumps(store.snapshot(), indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
