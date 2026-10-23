import base64
import binascii
import hashlib
import json
import re

MAX_INT64 = 9223372036854775807
MAX_SAFE = 9007199254740991


class SyncError(Exception):
    def __init__(self, status, code, detail=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail or {}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decimal(value, code="invalid"):
    """Parse a canonical nonnegative decimal string within signed 64-bit range."""
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise SyncError(400, code)
    if len(value) > 19:
        raise SyncError(400, code)
    number = int(value)
    if number > MAX_INT64:
        raise SyncError(400, code)
    return number


def unicode_ok(value):
    """Strings must be encodable as UTF-8 (no lone surrogates)."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def token(value):
    return base64.urlsafe_b64encode(canonical(value).encode()).decode().rstrip("=")


def untoken(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("invalid alphabet")
        decoded = json.loads(base64.b64decode(value + "=" * (-len(value) % 4),
                                             altchars=b"-_", validate=True))
        if not isinstance(decoded, dict):
            raise ValueError("token must be an object")
        return decoded
    except (ValueError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise SyncError(400, "invalid_cursor") from exc


def text(value, code="invalid"):
    if not isinstance(value, str) or not value or not unicode_ok(value):
        raise SyncError(400, code)
    return value


def body(value, partial=False):
    fields = {"title", "assignee", "visits", "done"}
    if not isinstance(value, dict) or set(value) - fields:
        raise SyncError(400, "invalid")
    if not partial and set(value) != fields:
        raise SyncError(400, "invalid")
    for key, item in value.items():
        valid = {
            "title": isinstance(item, str) and bool(item) and unicode_ok(item),
            "assignee": item is None or (isinstance(item, str) and unicode_ok(item)),
            "visits": type(item) is int and 0 <= item <= MAX_SAFE,
            "done": type(item) is bool,
        }[key]
        if not valid:
            raise SyncError(400, "invalid")
    return value
