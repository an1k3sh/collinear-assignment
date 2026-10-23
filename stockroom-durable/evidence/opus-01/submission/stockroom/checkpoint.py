"""Portable checkpoint envelope: encoding, checksum and validation."""
import hashlib
import json
import re

from .errors import StockError

FORMAT = "stockroom-continuation"
VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = ("format", "version", "identity", "label", "pause_count", "state",
          "checksum")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def bad(message):
    return StockError("CHECKPOINT", message)


def build(identity, label, pause_count, state):
    body = {
        "format": FORMAT,
        "version": VERSION,
        "identity": identity,
        "label": label,
        "pause_count": pause_count,
        "state": state,
    }
    body["checksum"] = sha256(canonical(body))
    return (json.dumps(body, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key %r" % key)
        out[key] = value
    return out


def _constant(name):
    raise ValueError("non-finite number %s" % name)


def strict_json(text):
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


def parse(data):
    """Validate the envelope (not the state); return the decoded object."""
    if len(data) > MAX_BYTES:
        raise bad("checkpoint exceeds 16 MiB")
    try:
        text = data.decode("utf-8")
        envelope = strict_json(text)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise bad("checkpoint is not valid JSON: %s" % exc) from None
    if type(envelope) is not dict:
        raise bad("checkpoint must be a JSON object")
    if set(envelope) != set(FIELDS):
        raise bad("checkpoint fields must be exactly %s" % ", ".join(FIELDS))
    if envelope["format"] != FORMAT:
        raise bad("unsupported checkpoint format")
    if type(envelope["version"]) is not int or envelope["version"] != VERSION:
        raise bad("unsupported checkpoint version")
    identity = envelope["identity"]
    if type(identity) is not dict or set(identity) != {"program", "inventory",
                                                       "library"}:
        raise bad("malformed identity")
    for key in ("program", "inventory"):
        if type(identity[key]) is not str or not _HEX64.match(identity[key]):
            raise bad("malformed identity.%s" % key)
    library = identity["library"]
    if library is not None and (type(library) is not str
                                or not _HEX64.match(library)):
        raise bad("malformed identity.library")
    if type(envelope["label"]) is not str:
        raise bad("label must be a string")
    count = envelope["pause_count"]
    if type(count) is not int or count < 1:
        raise bad("pause_count must be a positive integer")
    if type(envelope["state"]) is not dict:
        raise bad("state must be an object")
    checksum = envelope["checksum"]
    if type(checksum) is not str or not _HEX64.match(checksum):
        raise bad("malformed checksum")
    body = {key: value for key, value in envelope.items() if key != "checksum"}
    try:
        expected = sha256(canonical(body))
    except (ValueError, TypeError, RecursionError):
        raise bad("checkpoint cannot be canonicalized") from None
    if expected != checksum:
        raise bad("checkpoint checksum mismatch")
    return envelope
