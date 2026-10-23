from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from .language import Checker, Fault, Parser
from .runtime import Engine


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key {key}")
        obj[key] = value
    return obj


def inventory(path: Path) -> dict[str, dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    try:
        obj = json.loads(text, object_pairs_hook=unique_object,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(obj, dict) or set(obj) != {"warehouses"}:
            raise ValueError("Expected only a warehouses object")
        warehouses = obj["warehouses"]
        if not isinstance(warehouses, dict):
            raise ValueError("Warehouses must be an object")
        for name, skus in warehouses.items():
            if not name or not isinstance(skus, dict):
                raise ValueError("Invalid warehouse")
            for sku, quantity in skus.items():
                if not sku or type(quantity) is not int or quantity < 0:
                    raise ValueError("Invalid SKU quantity")
        return warehouses
    except ValueError as exc:
        raise Fault("INPUT", str(exc)) from exc


def publish(path: Path, result: dict[str, Any]) -> None:
    content = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".stockroom-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    sys.set_int_max_str_digits(0)
    parser = argparse.ArgumentParser()
    parser.add_argument("program", type=Path)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        procedures = []
        for path in [args.library, args.program]:
            if path is not None:
                procedures.extend(Parser(path.read_text(encoding="utf-8"), str(path)).program())
        compiled = Checker(procedures).validate()
        result = Engine(compiled, inventory(args.inventory)).run()
        publish(args.out, result)
        return 0
    except Fault as error:
        print(json.dumps(error.diagnostic()), file=sys.stderr)
        return {"SYNTAX": 2, "STATIC": 3, "DOMAIN": 4,
                "RUNTIME": 5, "INPUT": 6, "IO": 7}[error.category]
    except (OSError, UnicodeError) as error:
        print(json.dumps({"error": "IO", "message": str(error)}), file=sys.stderr)
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
