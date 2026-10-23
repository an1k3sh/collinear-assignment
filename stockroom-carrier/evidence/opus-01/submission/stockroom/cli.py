"""Command-line driver: file identity, checkpoints, carrier link and publication."""
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

from .errors import DomainError, PauseExit, StockroomError
from .lang import compile_unit, decode_source
from .runtime import CheckpointMismatch, Interpreter, canonical

FORMAT = "stockroom-continuation"
ENGINE = "stockroom-replay/1"
MAX_CHECKPOINT = 16 * 1024 * 1024
PAUSE_EXIT = 10
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
RECORD_FIELDS = ("receipt", "warehouse", "sku_a", "qty_a", "sku_b", "qty_b")
OPTIONS = ("--inventory", "--out", "--library", "--checkpoint", "--resume", "--carrier")


def io_error(message):
    return StockroomError("IO", message)


def checkpoint_error(message):
    return StockroomError("CHECKPOINT", message)


# ---------------------------------------------------------------- arguments

def parse_args(argv):
    options = {}
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name not in OPTIONS:
                raise io_error("Unknown option %s" % name)
            if not eq:
                i += 1
                if i >= len(argv):
                    raise io_error("Option %s requires a value" % name)
                value = argv[i]
            if name in options:
                raise io_error("Option %s given more than once" % name)
            options[name] = value
        else:
            positional.append(arg)
        i += 1
    if len(positional) != 1:
        raise io_error("Usage: python -m stockroom PROGRAM --inventory INPUT --out OUTPUT "
                       "[--library LIBRARY] [--checkpoint PATH] [--resume PATH] [--carrier DB]")
    for required in ("--inventory", "--out"):
        if not options.get(required):
            raise io_error("Missing required option %s" % required)
    for name, value in options.items():
        if value == "":
            raise io_error("Option %s requires a nonempty path" % name)
    return positional[0], options


def same_file(a, b):
    if a is None or b is None:
        return False
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def check_publication_path(path, what):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise io_error("%s parent directory does not exist: %s" % (what, path))
    if os.path.isdir(path):
        raise io_error("%s path is a directory: %s" % (what, path))
    if not os.access(parent, os.W_OK):
        raise io_error("%s directory is not writable: %s" % (what, path))


def read_bytes(path, what):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise io_error("Cannot read %s %s: %s" % (what, path, exc.strerror or exc)) from None


def publish(path, data):
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(target) + ".", suffix=".tmp",
                                   dir=parent)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        tmp = None
    except OSError as exc:
        raise io_error("Cannot publish %s: %s" % (path, exc.strerror or exc)) from None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def encode_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")


# ---------------------------------------------------------------- strict JSON

class _Reject(Exception):
    pass


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Reject("duplicate key %r" % key)
        out[key] = value
    return out


def _bad_constant(name):
    raise _Reject("non-finite number %s" % name)


def strict_json(data, allow_float=False):
    text = data.decode("utf-8")
    kwargs = {"object_pairs_hook": _pairs, "parse_constant": _bad_constant}
    if not allow_float:
        kwargs["parse_float"] = lambda s: (_ for _ in ()).throw(_Reject("float " + s))
    return json.loads(text, **kwargs)


def is_int(value):
    return type(value) is int


def is_name(value):
    return isinstance(value, str) and value != ""


# ---------------------------------------------------------------- inventory

def parse_inventory(data):
    try:
        doc = strict_json(data)
    except (UnicodeDecodeError, ValueError, _Reject, RecursionError) as exc:
        raise StockroomError("INPUT", "Malformed inventory: %s" % exc) from None
    if not isinstance(doc, dict) or set(doc) != {"warehouses"}:
        raise StockroomError("INPUT", "Inventory must contain exactly 'warehouses'")
    warehouses = doc["warehouses"]
    if not isinstance(warehouses, dict):
        raise StockroomError("INPUT", "'warehouses' must be an object")
    for name, stock in warehouses.items():
        if not is_name(name) or not isinstance(stock, dict):
            raise StockroomError("INPUT", "Invalid warehouse %r" % name)
        for sku, qty in stock.items():
            if not is_name(sku) or not is_int(qty) or qty < 0:
                raise StockroomError("INPUT", "Invalid quantity for %r/%r" % (name, sku))
    return warehouses


# ---------------------------------------------------------------- carrier

def load_carrier_module():
    """Load the supplied service module that sits beside this package."""
    module = sys.modules.get("carrier_service")
    if module is not None:
        return module
    path = Path(__file__).resolve().parent.parent / "carrier_service.py"
    try:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("carrier_service", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["carrier_service"] = module
            spec.loader.exec_module(module)
            return module
        return importlib.import_module("carrier_service")
    except Exception as exc:
        sys.modules.pop("carrier_service", None)
        raise io_error("The supplied carrier_service module is unavailable: %s" % exc) from None


class CarrierLink:
    """Adapter around the supplied service; transport/storage faults are fatal IO."""

    def __init__(self, path):
        self.module = load_carrier_module()
        try:
            self.service = self.module.Carrier(path)
            self.service_id = self.service.service_id
        except Exception as exc:  # missing, unreadable or not a carrier database
            raise io_error("Cannot open carrier %s: %s" % (path, exc)) from None

    def lookup(self, key, interp, loc):
        try:
            record = self.service.lookup(key)
        except Exception as exc:
            raise interp.fatal("IO", "Carrier lookup failed: %s" % exc, loc) from None
        if record is None:
            return None
        return {field: record[field] for field in RECORD_FIELDS}

    def submit(self, args, interp, loc):
        try:
            return {"response": self.service.submit(*args)}
        except self.module.CarrierFailure as failure:
            return {"failure": [failure.code, str(failure) or failure.code]}
        except Exception as exc:
            raise interp.fatal("IO", "Carrier submission failed: %s" % exc, loc) from None


# ---------------------------------------------------------------- checkpoints

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checksum_of(body):
    return sha256(canonical(body).encode("utf-8"))


def valid_record(record):
    return (isinstance(record, dict) and set(record) == set(RECORD_FIELDS)
            and all(is_name(record[f]) for f in ("receipt", "warehouse", "sku_a", "sku_b"))
            and is_int(record["qty_a"]) and is_int(record["qty_b"]))


def valid_observation(entry):
    if not isinstance(entry, dict):
        return False
    request = entry.get("request")
    if not isinstance(request, list) or not request:
        return False
    if request[0] == "lookup":
        if len(request) != 2 or not isinstance(request[1], str):
            return False
        return (set(entry) == {"request", "response"}
                and (entry["response"] is None or valid_record(entry["response"])))
    if request[0] == "submit":
        if len(request) != 7 or not all(isinstance(request[i], str) for i in (1, 2, 3, 5)):
            return False
        if not (is_int(request[4]) and is_int(request[6])):
            return False
        if set(entry) == {"request", "response"}:
            return isinstance(entry["response"], str)
        if set(entry) == {"request", "failure"}:
            failure = entry["failure"]
            return (isinstance(failure, list) and len(failure) == 2
                    and all(isinstance(x, str) and x for x in failure))
    return False


def load_checkpoint(data):
    if len(data) > MAX_CHECKPOINT:
        raise checkpoint_error("Checkpoint exceeds 16 MiB")
    try:
        doc = strict_json(data, allow_float=True)
    except (UnicodeDecodeError, ValueError, _Reject, RecursionError) as exc:
        raise checkpoint_error("Checkpoint is not valid JSON: %s" % exc) from None
    fields = {"format", "version", "identity", "label", "pause_count", "state", "checksum"}
    if not isinstance(doc, dict) or set(doc) != fields:
        raise checkpoint_error("Checkpoint envelope has missing or unexpected fields")
    if doc["format"] != FORMAT:
        raise checkpoint_error("Unsupported checkpoint format")
    if not is_int(doc["version"]) or doc["version"] != 1:
        raise checkpoint_error("Unsupported checkpoint version")
    if not is_int(doc["pause_count"]) or doc["pause_count"] < 1:
        raise checkpoint_error("Invalid pause_count")
    if not isinstance(doc["label"], str):
        raise checkpoint_error("Invalid label")
    if not isinstance(doc["state"], dict):
        raise checkpoint_error("Invalid state")
    if not isinstance(doc["checksum"], str) or not HEX64.match(doc["checksum"]):
        raise checkpoint_error("Invalid checksum field")
    identity = doc["identity"]
    if (not isinstance(identity, dict)
            or set(identity) != {"program", "inventory", "library", "carrier"}
            or not isinstance(identity["program"], str) or not HEX64.match(identity["program"])
            or not isinstance(identity["inventory"], str) or not HEX64.match(identity["inventory"])
            or not (identity["library"] is None
                    or (isinstance(identity["library"], str) and HEX64.match(identity["library"])))
            or not (identity["carrier"] is None or is_name(identity["carrier"]))):
        raise checkpoint_error("Invalid checkpoint identity")
    body = {k: v for k, v in doc.items() if k != "checksum"}
    try:
        expected = checksum_of(body)
    except ValueError:
        raise checkpoint_error("Checkpoint contains non-finite numbers") from None
    if expected != doc["checksum"]:
        raise checkpoint_error("Checkpoint checksum mismatch")
    state = doc["state"]
    if (set(state) != {"engine", "pauses", "steps", "digest", "observations"}
            or state["engine"] != ENGINE
            or not is_int(state["pauses"]) or state["pauses"] != doc["pause_count"]
            or not is_int(state["steps"]) or not 1 <= state["steps"] <= 20000
            or not isinstance(state["digest"], str) or not HEX64.match(state["digest"])
            or not isinstance(state["observations"], list)
            or not all(valid_observation(o) for o in state["observations"])):
        raise checkpoint_error("Incompatible checkpoint execution state")
    return doc


def build_checkpoint(identity, interp, label):
    body = {
        "format": FORMAT,
        "version": 1,
        "identity": identity,
        "label": label,
        "pause_count": interp.pause_count,
        "state": {
            "engine": ENGINE,
            "pauses": interp.pause_count,
            "steps": interp.steps,
            "digest": interp.pause_digest,
            "observations": interp.observations,
        },
    }
    body["checksum"] = checksum_of(body)
    return canonical(body).encode("utf-8")


# ---------------------------------------------------------------- main flow

def execute(argv):
    program_path, opts = parse_args(argv)
    inventory_path = opts["--inventory"]
    out_path = opts["--out"]
    library_path = opts.get("--library")
    resume_path = opts.get("--resume")
    carrier_path = opts.get("--carrier")
    durable = "--checkpoint" in opts or resume_path is not None
    checkpoint_out = opts.get("--checkpoint", resume_path)

    # Path aliases and publication targets are validated before anything runs.
    for other in (program_path, inventory_path, library_path, resume_path,
                  checkpoint_out, carrier_path):
        if same_file(out_path, other):
            raise io_error("Output path aliases another input or output")
    if durable:
        for other in (program_path, inventory_path, library_path, carrier_path):
            if same_file(checkpoint_out, other):
                raise io_error("Checkpoint path aliases a source, input or carrier")
    check_publication_path(out_path, "Output")
    if durable:
        check_publication_path(checkpoint_out, "Checkpoint")

    program_bytes = read_bytes(program_path, "program")
    library_bytes = read_bytes(library_path, "library") if library_path is not None else None
    inventory_bytes = read_bytes(inventory_path, "inventory")
    checkpoint_bytes = read_bytes(resume_path, "checkpoint") if resume_path is not None else None
    carrier = CarrierLink(carrier_path) if carrier_path is not None else None

    identity = {
        "program": sha256(program_bytes),
        "inventory": sha256(inventory_bytes),
        "library": sha256(library_bytes) if library_bytes is not None else None,
        "carrier": carrier.service_id if carrier is not None else None,
    }

    target, observations, expected = 0, [], None
    if checkpoint_bytes is not None:
        saved = load_checkpoint(checkpoint_bytes)
        for field in ("program", "inventory", "library"):
            if saved["identity"][field] != identity[field]:
                raise checkpoint_error("Checkpoint %s identity does not match" % field)
        if saved["identity"]["carrier"] != identity["carrier"]:
            raise checkpoint_error("Checkpoint carrier service identity does not match")
        state = saved["state"]
        target = saved["pause_count"]
        observations = state["observations"]
        expected = {"label": saved["label"], "steps": state["steps"], "digest": state["digest"]}

    program = decode_source(program_path, "program", program_bytes)
    library = (decode_source(library_path, "library", library_bytes)
               if library_bytes is not None else None)
    procs = compile_unit(program, library)
    warehouses = parse_inventory(inventory_bytes)

    interp = Interpreter(procs, warehouses, carrier=carrier, durable=durable,
                         target=target, observations=observations, expected=expected)
    try:
        interp.run()
    except PauseExit as pause:
        publish(checkpoint_out, build_checkpoint(identity, interp, pause.label))
        return PAUSE_EXIT
    except CheckpointMismatch as exc:
        raise checkpoint_error("Incompatible checkpoint execution state: %s" % exc) from None
    except StockroomError:
        if interp.replaying:
            raise checkpoint_error("Checkpoint replay failed before reaching its pause") from None
        raise
    publish(out_path, encode_json(interp.result()))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    outcome = {}

    def target():
        try:
            outcome["code"] = execute(argv)
        except StockroomError as error:
            sys.stderr.write(json.dumps(error.diagnostic()) + "\n")
            outcome["code"] = error.exit_code
        except RecursionError:
            sys.stderr.write(json.dumps({"error": "RUNTIME",
                                         "message": "Nesting too deep"}) + "\n")
            outcome["code"] = 5
        except MemoryError:
            sys.stderr.write(json.dumps({"error": "RUNTIME",
                                         "message": "Out of memory"}) + "\n")
            outcome["code"] = 5

    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(0)
    sys.setrecursionlimit(1000000)
    threading.stack_size(512 * 1024 * 1024)
    worker = threading.Thread(target=target)
    worker.start()
    worker.join()
    sys.stderr.flush()
    return outcome.get("code", 1)
