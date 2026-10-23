"""Command line driver: compile, execute, suspend/resume and publish."""
import json
import os
import sys
import tempfile
import threading

from . import checkpoint
from .compiler import compile_unit
from .errors import EXIT_CODES, SUSPENDED, StockError
from .parser import decode_source, parse
from .vm import VM, BadState, Suspend, load_state

USAGE = ("usage: python -m stockroom PROGRAM --inventory INPUT --out OUTPUT "
         "[--library LIBRARY] [--checkpoint PATH] [--resume PATH]")
OPTIONS = ("--inventory", "--out", "--library", "--checkpoint", "--resume")


def io_error(message):
    return StockError("IO", message)


def parse_args(argv):
    values = {}
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name not in OPTIONS:
                raise io_error("unknown option %s; %s" % (name, USAGE))
            if not eq:
                i += 1
                if i >= len(argv):
                    raise io_error("option %s needs a value; %s" % (name, USAGE))
                value = argv[i]
            if name in values:
                raise io_error("option %s given twice" % name)
            if value == "":
                raise io_error("option %s needs a nonempty path" % name)
            values[name] = value
        else:
            positional.append(arg)
        i += 1
    if len(positional) != 1 or "--inventory" not in values or "--out" not in values:
        raise io_error(USAGE)
    if positional[0] == "":
        raise io_error("PROGRAM path is empty")
    return positional[0], values


def same_file(a, b):
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def read_file(path, what):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise io_error("cannot read %s %s: %s" % (what, path, exc.strerror or exc))


def check_parent(path, what):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise io_error("parent directory of %s %s does not exist" % (what, path))
    if os.path.isdir(path):
        raise io_error("%s %s is a directory" % (what, path))


def publish(path, data):
    """Atomically replace ``path`` with ``data`` via a temporary sibling."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(target) + ".",
                                   suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, target)
        tmp = None
    except OSError as exc:
        raise io_error("cannot publish %s: %s" % (path, exc.strerror or exc))
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def parse_inventory(data):
    def bad(message):
        return StockError("INPUT", message)
    try:
        document = checkpoint.strict_json(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise bad("inventory is not valid JSON: %s" % exc) from None
    if type(document) is not dict or set(document) != {"warehouses"}:
        raise bad("inventory must be an object with exactly 'warehouses'")
    warehouses = document["warehouses"]
    if type(warehouses) is not dict:
        raise bad("'warehouses' must be an object")
    for name, stock in warehouses.items():
        if name == "":
            raise bad("warehouse names must be nonempty")
        if type(stock) is not dict:
            raise bad("warehouse %r must be an object" % name)
        for sku, qty in stock.items():
            if sku == "":
                raise bad("SKU names must be nonempty")
            if type(qty) is not int or qty < 0:
                raise bad("quantity for %r/%r must be a nonnegative integer"
                          % (name, sku))
    return warehouses


def execute(argv):
    program_path, opts = parse_args(argv)
    input_path = opts["--inventory"]
    out_path = opts["--out"]
    library_path = opts.get("--library")
    resume_path = opts.get("--resume")
    durable = "--checkpoint" in opts or resume_path is not None
    checkpoint_path = opts.get("--checkpoint", resume_path)
    files = {"program": program_path, "library": library_path}

    sources = [program_path, input_path] + ([library_path] if library_path else [])
    for other in sources + [p for p in (resume_path, checkpoint_path) if p]:
        if same_file(out_path, other):
            raise io_error("output path aliases %s" % other)
    if checkpoint_path:
        for other in sources:
            if same_file(checkpoint_path, other):
                raise io_error("checkpoint path aliases %s" % other)
    check_parent(out_path, "output")
    if checkpoint_path:
        check_parent(checkpoint_path, "checkpoint")

    program_bytes = read_file(program_path, "program")
    library_bytes = read_file(library_path, "library") if library_path else None
    input_bytes = read_file(input_path, "inventory")
    identity = {
        "program": checkpoint.sha256(program_bytes),
        "inventory": checkpoint.sha256(input_bytes),
        "library": checkpoint.sha256(library_bytes) if library_bytes is not None
        else None,
    }
    envelope = None
    if resume_path is not None:
        envelope = checkpoint.parse(read_file(resume_path, "checkpoint"))
        saved = envelope["identity"]
        for role in ("program", "inventory", "library"):
            if saved[role] != identity[role]:
                raise StockError("CHECKPOINT",
                                 "%s does not match the checkpoint" % role)

    try:
        library_nodes = (parse(decode_source(library_bytes, "library"), "library")
                         if library_bytes is not None else [])
        program_nodes = parse(decode_source(program_bytes, "program"), "program")
        unit = compile_unit(library_nodes, program_nodes)
    except StockError as exc:
        exc.files = files
        raise
    warehouses = parse_inventory(input_bytes)

    if envelope is None:
        vm = VM(unit, warehouses, durable=durable)
    else:
        try:
            vm = load_state(unit, envelope["state"], envelope["label"],
                            envelope["pause_count"])
        except (BadState, KeyError, IndexError, TypeError, ValueError,
                AttributeError) as exc:
            raise StockError("CHECKPOINT",
                             "incompatible checkpoint state: %s" % exc) from None
    try:
        vm.run()
    except Suspend:
        state = vm.dump_state()
        try:
            data = checkpoint.build(identity, vm.label, vm.pause_count, state)
        except (ValueError, TypeError) as exc:
            raise io_error("cannot serialize checkpoint: %s" % exc)
        publish(checkpoint_path, data)
        return SUSPENDED, files
    try:
        data = (json.dumps(vm.result(), ensure_ascii=True, allow_nan=False)
                + "\n").encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise io_error("cannot serialize result: %s" % exc)
    publish(out_path, data)
    return 0, files


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(0)
    sys.setrecursionlimit(1000000)
    outcome = {}

    def worker():
        files = {}
        try:
            code, files = execute(argv)
            outcome["code"] = code
        except StockError as exc:
            files = getattr(exc, "files", None) or files
            if not files:
                files = guess_files(argv)
            report(exc.diagnostic(files))
            outcome["code"] = EXIT_CODES[exc.category]
        except RecursionError:
            report({"error": "RUNTIME", "message": "nesting too deep"})
            outcome["code"] = EXIT_CODES["RUNTIME"]
        except MemoryError:
            report({"error": "RUNTIME", "message": "out of memory"})
            outcome["code"] = EXIT_CODES["RUNTIME"]

    # Deeply nested expressions are evaluated recursively; give them room.
    for size in (512, 256, 64):
        try:
            threading.stack_size(size * 1024 * 1024)
            break
        except (ValueError, RuntimeError):
            continue
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    except RuntimeError:
        threading.stack_size(0)
        sys.setrecursionlimit(20000)
        worker()
    return outcome.get("code", 1)


def guess_files(argv):
    try:
        program, opts = parse_args(argv)
        return {"program": program, "library": opts.get("--library")}
    except StockError:
        return {}


def report(diagnostic):
    try:
        sys.stderr.write(json.dumps(diagnostic, ensure_ascii=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
