"""Static validation and compilation of the AST into per-procedure bytecode.

Expressions are compiled into closures ``fn(vm, frame) -> value``; statements
become a flat instruction list per procedure so the whole execution state is a
handful of integers and dictionaries that serialize cleanly.
"""
from .errors import StockError
from .parser import OPERATIONS

BUILTINS = {
    "onhand": (("string", "string"), "int"),
    "available": (("string", "string"), "int"),
    "remaining": (("string",), "int"),
    "len": (("string",), "int"),
    "code": (("error",), "string"),
}
SCALARS = ("int", "bool", "string")
OPERATION_TYPES = {
    "receive": ("string", "string", "int"),
    "move": ("string", "string", "string", "int"),
    "reserve": ("string", "string", "string", "int"),
    "release": ("string", "int"),
    "ship": ("string", "int"),
}
assert set(OPERATION_TYPES) == set(OPERATIONS)

# opcodes
(LET, SET, IF, JUMP, ENTER, EXIT, LOOP, WTEST, TX, COMMIT, BRK, CONT, RET,
 RET0, ASSERT, EMIT, OP, CALL, PAUSE) = range(19)
OPNAMES = ("LET SET IF JUMP ENTER EXIT LOOP WTEST TX COMMIT BRK CONT RET RET0 "
           "ASSERT EMIT OP CALL PAUSE").split()


class Ins:
    __slots__ = ("op", "pos", "step", "a", "b", "c", "shape")

    def __init__(self, op, pos, step, a=None, b=None, c=None):
        self.op = op
        self.pos = pos
        self.step = step
        self.a = a
        self.b = b
        self.c = c
        self.shape = None

    def __repr__(self):
        return "%s(%r,%r,%r)" % (OPNAMES[self.op], self.a, self.b, self.c)


class Proc:
    def __init__(self, node, role):
        self.name = node.name
        self.node = node
        self.role = role
        self.params = []  # (name, type, has_default, default)
        self.code = []


class Unit:
    def __init__(self, procs):
        self.procs = procs


def static(message, pos):
    return StockError("STATIC", message, pos)


def type_name(value):
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "string"
    return "error"


def tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def compile_unit(library, program):
    """``library``/``program`` are lists of proc nodes (library may be [])."""
    procs = {}
    ordered = []
    for role, nodes in (("library", library), ("program", program)):
        for node in nodes:
            if node.name in BUILTINS:
                raise static("procedure name '%s' is reserved for a builtin"
                             % node.name, node.pos)
            if node.name in procs:
                raise static("duplicate procedure '%s'" % node.name, node.pos)
            proc = Proc(node, role)
            procs[node.name] = proc
            ordered.append(proc)
    for proc in ordered:
        seen = set()
        defaulted = False
        for param in proc.node.params:
            if param.name in seen:
                raise static("duplicate parameter '%s'" % param.name, param.pos)
            seen.add(param.name)
            if param.default is None:
                if defaulted:
                    raise static("required parameter after defaulted parameter",
                                 param.pos)
                proc.params.append((param.name, param.type, False, None))
            else:
                defaulted = True
                if param.default.type != param.type:
                    raise static("default for '%s' must be %s"
                                 % (param.name, param.type), param.default.pos)
                proc.params.append((param.name, param.type, True,
                                    param.default.value))
    if "main" not in procs:
        raise static("program has no 'proc main()'", ("program", 1, 1))
    if procs["main"].role != "program":
        raise static("'main' must be defined by the program, not the library",
                     procs["main"].node.pos)
    if procs["main"].params:
        raise static("main must not declare parameters", procs["main"].node.pos)
    unit = Unit(procs)
    graph = {}
    for proc in ordered:
        compiler = ProcCompiler(unit, proc)
        compiler.compile()
        graph[proc.name] = compiler.calls
    check_recursion(ordered, graph)
    return unit


def check_recursion(ordered, graph):
    state = {}
    for root in ordered:
        if root.name in state:
            continue
        state[root.name] = 1
        stack = [(root.name, iter(graph[root.name]))]
        while stack:
            name, edges = stack[-1]
            advanced = False
            for callee, pos in edges:
                mark = state.get(callee)
                if mark == 1:
                    raise static("recursive call to '%s'" % callee, pos)
                if mark is None:
                    state[callee] = 1
                    stack.append((callee, iter(graph[callee])))
                    advanced = True
                    break
            if not advanced:
                state[name] = 2
                stack.pop()


class ProcCompiler:
    def __init__(self, unit, proc):
        self.unit = unit
        self.proc = proc
        self.code = proc.code
        self.shape = [["s", {name: ptype for name, ptype, _, _ in proc.params}]]
        self.loops = 0
        self.calls = []

    def emit(self, op, pos, step, a=None, b=None, c=None):
        self.code.append(Ins(op, pos, step, a, b, c))
        return len(self.code) - 1

    def snapshot(self):
        out = []
        for entry in self.shape:
            if entry[0] == "s":
                out.append(("s", dict(entry[1])))
            else:
                out.append((entry[0], entry[1]))
        return tuple(out)

    def lookup(self, name):
        for entry in reversed(self.shape):
            if entry[0] == "s" and name in entry[1]:
                return entry[1][name]
        return None

    def compile(self):
        for stmt in self.proc.node.body.stmts:
            self.statement(stmt)
        self.emit(RET0, self.proc.node.pos, False)

    def block(self, block, preset=None):
        self.emit(ENTER, block.pos, False)
        self.shape.append(["s", dict(preset or {})])
        for stmt in block.stmts:
            self.statement(stmt)
        self.shape.pop()
        self.emit(EXIT, block.pos, False)

    def expect(self, node, wanted, what):
        etype, fn = self.expr(node)
        if etype != wanted:
            raise static("%s must be %s, not %s" % (what, wanted, etype), node.pos)
        return fn

    # -- statements --------------------------------------------------------
    def statement(self, stmt):
        kind = stmt.kind
        pos = stmt.pos
        if kind == "let":
            scope = self.shape[-1][1]
            if stmt.name in scope:
                raise static("'%s' is already declared in this block" % stmt.name,
                             stmt.name_pos)
            fn = self.expect(stmt.expr, stmt.type, "initializer of '%s'" % stmt.name)
            self.emit(LET, pos, True, stmt.name, fn)
            scope[stmt.name] = stmt.type
        elif kind == "set":
            vtype = self.lookup(stmt.name)
            if vtype is None:
                raise static("assignment to undeclared '%s'" % stmt.name,
                             stmt.name_pos)
            if vtype == "error":
                raise static("recovery binding '%s' cannot be assigned" % stmt.name,
                             stmt.name_pos)
            fn = self.expect(stmt.expr, vtype, "value assigned to '%s'" % stmt.name)
            self.emit(SET, pos, True, stmt.name, fn)
        elif kind == "if":
            fn = self.expect(stmt.cond, "bool", "condition")
            at = self.emit(IF, pos, True, fn)
            self.block(stmt.then)
            if stmt.other is not None:
                jump = self.emit(JUMP, pos, False)
                self.code[at].b = len(self.code)
                self.block(stmt.other)
                self.code[jump].a = len(self.code)
            else:
                self.code[at].b = len(self.code)
        elif kind == "while":
            at = self.emit(LOOP, pos, True)
            self.shape.append(["l", at])
            fn = self.expect(stmt.cond, "bool", "condition")
            test = self.emit(WTEST, pos, False, fn)
            self.loops += 1
            self.block(stmt.body)
            self.loops -= 1
            self.emit(JUMP, pos, False, test)
            self.shape.pop()
            end = len(self.code)
            self.code[at].a = end
            self.code[at].b = test
            self.code[test].b = end
        elif kind == "tx":
            at = self.emit(TX, pos, True)
            self.shape.append(["t", at])
            self.block(stmt.body)
            self.shape.pop()
            self.emit(COMMIT, pos, False)
            if stmt.handler is not None:
                jump = self.emit(JUMP, pos, False)
                self.code[at].a = len(self.code)
                self.code[at].c = stmt.errname
                self.shape.append(["s", {stmt.errname: "error"}])
                for inner in stmt.handler.stmts:
                    self.statement(inner)
                self.shape.pop()
                self.emit(EXIT, stmt.handler.pos, False)
                self.code[jump].a = len(self.code)
        elif kind in ("break", "continue"):
            if not self.loops:
                raise static("'%s' outside a loop" % kind, pos)
            self.emit(BRK if kind == "break" else CONT, pos, True)
        elif kind == "return":
            self.emit(RET, pos, True)
        elif kind == "assert":
            self.emit(ASSERT, pos, True, self.expect(stmt.expr, "bool", "assertion"))
        elif kind == "pause":
            fn = self.expect(stmt.expr, "string", "pause label")
            self.emit(PAUSE, pos, True, fn)
            self.code[-1].shape = self.snapshot()
        elif kind == "emit":
            name = self.expect(stmt.name, "string", "event name")
            fields = []
            seen = set()
            for key, key_pos, node in stmt.fields:
                if key in seen:
                    raise static("duplicate event field '%s'" % key, key_pos)
                seen.add(key)
                etype, fn = self.expr(node)
                if etype not in SCALARS:
                    raise static("event field must be int, bool or string", node.pos)
                fields.append((key, fn))
            self.emit(EMIT, pos, True, name, tuple(fields))
        elif kind == "op":
            fns = []
            for node, wanted in zip(stmt.args, OPERATION_TYPES[stmt.op]):
                fns.append(self.expect(node, wanted, "%s operand" % stmt.op))
            self.emit(OP, pos, True, stmt.op, tuple(fns))
        elif kind == "call":
            self.call(stmt)
        else:  # pragma: no cover - parser produces only the kinds above
            raise static("unsupported statement", pos)

    def call(self, stmt):
        name = stmt.name
        if name in BUILTINS:
            raise static("builtin '%s' cannot be used as a statement" % name, stmt.pos)
        target = self.unit.procs.get(name)
        if target is None:
            raise static("unknown procedure '%s'" % name, stmt.pos)
        params = target.params
        index = {p[0]: i for i, p in enumerate(params)}
        bound = [None] * len(params)
        fns = []
        named_seen = False
        for position, (argname, argpos, node) in enumerate(stmt.args):
            if argname is None:
                if named_seen:
                    raise static("positional argument after named argument", argpos)
                if position >= len(params):
                    raise static("too many arguments for '%s'" % name, argpos)
                slot = position
            else:
                named_seen = True
                if argname not in index:
                    raise static("'%s' has no parameter '%s'" % (name, argname),
                                 argpos)
                slot = index[argname]
                if bound[slot] is not None:
                    raise static("parameter '%s' bound more than once" % argname,
                                 argpos)
            pname, ptype = params[slot][0], params[slot][1]
            fns.append(self.expect(node, ptype, "argument '%s'" % pname))
            bound[slot] = ("arg", len(fns) - 1)
        plan = []
        for slot, (pname, _ptype, has_default, default) in enumerate(params):
            if bound[slot] is None:
                if not has_default:
                    raise static("missing argument '%s' for '%s'" % (pname, name),
                                 stmt.pos)
                plan.append((pname, False, default))
            else:
                plan.append((pname, True, bound[slot][1]))
        self.calls.append((name, stmt.pos))
        self.emit(CALL, stmt.pos, True, name, tuple(fns), tuple(plan))
        self.code[-1].shape = self.snapshot()

    # -- expressions -------------------------------------------------------
    def expr(self, node, allow_error=False):
        kind = node.kind
        if kind == "lit":
            value = node.value
            return node.type, (lambda vm, fr: value)
        if kind == "var":
            name = node.name
            vtype = self.lookup(name)
            if vtype is None:
                raise static("undeclared variable '%s'" % name, node.pos)
            if vtype == "error" and not allow_error:
                raise static("recovery binding '%s' can only be used with code()"
                             % name, node.pos)

            def load(vm, fr):
                blocks = fr.blocks
                i = len(blocks) - 1
                while True:
                    block = blocks[i]
                    if block[0] == "s":
                        scope = block[1]
                        if name in scope:
                            return scope[name]
                    i -= 1
            return vtype, load
        if kind == "un":
            if node.op == "!":
                fn = self.expect(node.operand, "bool", "operand of '!'")
                return "bool", (lambda vm, fr: not fn(vm, fr))
            fn = self.expect(node.operand, "int", "operand of unary '-'")
            return "int", (lambda vm, fr: -fn(vm, fr))
        if kind == "bin":
            return self.binary(node)
        if kind == "fcall":
            return self.builtin(node)
        raise static("unsupported expression", node.pos)  # pragma: no cover

    def binary(self, node):
        op = node.op
        ltype, left = self.expr(node.left)
        rtype, right = self.expr(node.right)
        pos = node.pos

        def mismatch():
            return static("operator '%s' cannot combine %s and %s"
                          % (op, ltype, rtype), pos)
        if op in ("&&", "||"):
            if ltype != "bool" or rtype != "bool":
                raise mismatch()
            if op == "&&":
                return "bool", (lambda vm, fr: left(vm, fr) and right(vm, fr))
            return "bool", (lambda vm, fr: left(vm, fr) or right(vm, fr))
        if op in ("==", "!="):
            if ltype != rtype or ltype not in SCALARS:
                raise mismatch()
            if op == "==":
                return "bool", (lambda vm, fr: left(vm, fr) == right(vm, fr))
            return "bool", (lambda vm, fr: left(vm, fr) != right(vm, fr))
        if op in ("<", "<=", ">", ">="):
            if ltype != rtype or ltype not in ("int", "string"):
                raise mismatch()
            if op == "<":
                return "bool", (lambda vm, fr: left(vm, fr) < right(vm, fr))
            if op == "<=":
                return "bool", (lambda vm, fr: left(vm, fr) <= right(vm, fr))
            if op == ">":
                return "bool", (lambda vm, fr: left(vm, fr) > right(vm, fr))
            return "bool", (lambda vm, fr: left(vm, fr) >= right(vm, fr))
        if op == "+":
            if ltype != rtype or ltype not in ("int", "string"):
                raise mismatch()
            return ltype, (lambda vm, fr: left(vm, fr) + right(vm, fr))
        if ltype != "int" or rtype != "int":
            raise mismatch()
        if op == "-":
            return "int", (lambda vm, fr: left(vm, fr) - right(vm, fr))
        if op == "*":
            return "int", (lambda vm, fr: left(vm, fr) * right(vm, fr))

        def divide(vm, fr):
            a = left(vm, fr)
            b = right(vm, fr)
            if b == 0:
                vm.fatal("division by zero", pos)
            q = tdiv(a, b)
            return q if op == "/" else a - q * b
        return "int", divide

    def builtin(self, node):
        name = node.name
        if name not in BUILTINS:
            if name in self.unit.procs:
                raise static("procedure '%s' cannot be used as an expression"
                             % name, node.pos)
            raise static("unknown function '%s'" % name, node.pos)
        ptypes, rtype = BUILTINS[name]
        if len(node.args) != len(ptypes):
            raise static("'%s' expects %d argument(s)" % (name, len(ptypes)),
                         node.pos)
        fns = []
        for (argname, argpos, arg), wanted in zip(node.args, ptypes):
            if argname is not None:
                raise static("builtins accept positional arguments only", argpos)
            atype, fn = self.expr(arg, allow_error=(wanted == "error"))
            if atype != wanted:
                raise static("'%s' argument must be %s, not %s"
                             % (name, "a recovery error" if wanted == "error"
                                else wanted, atype), arg.pos)
            fns.append(fn)
        pos = node.pos
        if name == "len":
            f0 = fns[0]
            return rtype, (lambda vm, fr: len(f0(vm, fr)))
        if name == "code":
            f0 = fns[0]
            return rtype, (lambda vm, fr: f0(vm, fr).code)
        if name == "remaining":
            f0 = fns[0]
            return rtype, (lambda vm, fr: vm.remaining(f0(vm, fr), pos))
        f0, f1 = fns
        if name == "onhand":
            return rtype, (lambda vm, fr: vm.onhand(f0(vm, fr), f1(vm, fr), pos))
        return rtype, (lambda vm, fr: vm.available(f0(vm, fr), f1(vm, fr), pos))
