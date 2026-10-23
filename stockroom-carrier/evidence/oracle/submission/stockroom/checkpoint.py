from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .language import Fault


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key {key}")
        obj[key] = value
    return obj


def invalid_constant(value: str) -> None:
    raise ValueError(f"Non-JSON constant {value}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def envelope(identity: dict[str, Any], label: str, count: int,
             state: dict[str, Any]) -> dict[str, Any]:
    body = {"format": "stockroom-continuation", "version": 1,
            "identity": identity, "label": label, "pause_count": count, "state": state}
    return dict(body, checksum=digest(canonical(body)))


def load(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    content = path.read_bytes()
    try:
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("Checkpoint too large")
        obj = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object,
                         parse_constant=invalid_constant)
        keys = {"format", "version", "identity", "label", "pause_count", "state", "checksum"}
        if not isinstance(obj, dict) or set(obj) != keys:
            raise ValueError("Invalid checkpoint envelope")
        if obj["format"] != "stockroom-continuation" or type(obj["version"]) is not int or obj["version"] != 1:
            raise ValueError("Unsupported checkpoint format/version")
        if (not isinstance(obj["label"], str) or type(obj["pause_count"]) is not int
                or obj["pause_count"] < 1 or not isinstance(obj["state"], dict)):
            raise ValueError("Invalid checkpoint fields")
        checksum = obj.pop("checksum")
        if not isinstance(checksum, str) or re.fullmatch("[0-9a-f]{64}", checksum) is None:
            raise ValueError("Invalid checkpoint checksum")
        if checksum != digest(canonical(obj)):
            raise ValueError("Checkpoint checksum mismatch")
        if obj["identity"] != identity:
            raise ValueError("Program/library/inventory identity mismatch")
        return obj
    except (ValueError, UnicodeError) as error:
        raise Fault("CHECKPOINT", str(error)) from error
