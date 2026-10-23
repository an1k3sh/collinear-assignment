from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from .language import Checker, Fault, Parser
from .durable import Machine
from .checkpoint import digest, envelope, load


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
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    try:
        checkpoint_output = args.checkpoint or args.resume
        sources = [p.resolve() for p in (args.program, args.inventory, args.library) if p]
        protected = sources + [p.resolve() for p in (args.resume, checkpoint_output) if p]
        if (args.out.resolve() in protected
                or (checkpoint_output and checkpoint_output.resolve() in sources)):
            raise Fault("IO", "Input and output paths must not alias")
        program_bytes = args.program.read_bytes()
        input_bytes = args.inventory.read_bytes()
        library_bytes = args.library.read_bytes() if args.library else None
        identity = {"program": digest(program_bytes), "inventory": digest(input_bytes),
                    "library": digest(library_bytes) if library_bytes is not None else None}
        saved = load(args.resume, identity) if args.resume else None
        procedures = []
        for path in [args.library, args.program]:
            if path is not None:
                procedures.extend(Parser(path.read_text(encoding="utf-8"), str(path)).program())
        compiled = Checker(procedures).validate()
        machine = Machine(compiled, inventory(args.inventory))
        if saved is not None:
            machine.restore(saved["state"])
            if machine.pause_count != saved["pause_count"]:
                raise Fault("CHECKPOINT", "Continuation count mismatch")
        result, label = machine.run_until_pause(checkpoint_output is not None)
        if label is not None:
            publish(checkpoint_output, envelope(identity, label, machine.pause_count, machine.export()))
            return 10
        publish(args.out, result)
        return 0
    except Fault as error:
        print(json.dumps(error.diagnostic()), file=sys.stderr)
        return {"SYNTAX": 2, "STATIC": 3, "DOMAIN": 4,
                "RUNTIME": 5, "INPUT": 6, "IO": 7, "CHECKPOINT": 8}[error.category]
    except (OSError, UnicodeError) as error:
        print(json.dumps({"error": "IO", "message": str(error)}), file=sys.stderr)
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
