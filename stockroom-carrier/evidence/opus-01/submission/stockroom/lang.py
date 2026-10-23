"""Lexer, parser and static checker for the Stockroom language."""
import json

from .errors import StockroomError


class SourceFile:
    def __init__(self, display, role, text):
        self.display = display
        self.role = role
        self.text = text


KEYWORDS = frozenset((
    "proc", "let", "set", "if", "else", "while", "transaction", "recover",
    "break", "continue", "return", "assert", "emit", "receive", "move",
    "reserve", "release", "ship", "int", "bool", "string", "true", "false",
    "pause", "record_delivery",
))

TYPES = ("int", "bool", "string")

# name -> (parameter types, result type)
BUILTINS = {
    "onhand": (("string", "string"), "int"),
    "available": (("string", "string"), "int"),
    "remaining": (("string",), "int"),
    "len": (("string",), "int"),
    "code": (("error",), "string"),
    "carrier_send": (("string", "string", "string", "int", "string", "int"), "string"),
    "carrier_receipt": (("string",), "string"),
    "carrier_warehouse": (("string",), "string"),
    "carrier_matches": (("string", "string", "string", "int", "string", "int"), "bool"),
    "delivered": (("string",), "bool"),
}

TWO_CHAR_OPS = ("==", "!=", "<=", ">=", "&&", "||")
ONE_CHAR_OPS = "(){},;:=<>+-*/%!"
WHITESPACE = " \t\r\n\f\v"


def syntax(source, line, col, message):
    return StockroomError("SYNTAX", message, (source, line, col))


def static(loc, message):
    return StockroomError("STATIC", message, loc)


class Token:
    __slots__ = ("kind", "value", "loc")

    def __init__(self, kind, value, loc):
        self.kind = kind      # name, kw, int, str, op, eof
        self.value = value
        self.loc = loc


def decode_source(source_display, role, data):
    try:
        return SourceFile(source_display, role, data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        prefix = data[:exc.start].decode("utf-8", "replace")
        line = prefix.count("\n") + 1
        col = len(prefix) - (prefix.rfind("\n") + 1) + 1
        raise syntax(SourceFile(source_display, role, ""), line, col,
                     "Source is not valid UTF-8") from None


def tokenize(source):
    text = source.text
    n = len(text)
    i = 0
    line = 1
    line_start = 0
    tokens = []
    while True:
        while i < n:
            c = text[i]
            if c in WHITESPACE:
                if c == "\n":
                    line += 1
                    line_start = i + 1
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
            else:
                break
        col = i - line_start + 1
        loc = (source, line, col)
        if i >= n:
            tokens.append(Token("eof", None, loc))
            return tokens
        c = text[i]
        if c.isascii() and (c.isalpha() or c == "_"):
            j = i + 1
            while j < n and text[j].isascii() and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            tokens.append(Token("kw" if word in KEYWORDS else "name", word, loc))
            i = j
        elif "0" <= c <= "9":
            j = i + 1
            while j < n and "0" <= text[j] <= "9":
                j += 1
            tokens.append(Token("int", int(text[i:j]), loc))
            i = j
        elif c == '"':
            j = i + 1
            while True:
                if j >= n:
                    raise syntax(source, line, col, "Unterminated string")
                d = text[j]
                if d == '"':
                    break
                if d == "\\":
                    if j + 1 >= n:
                        raise syntax(source, line, col, "Unterminated string")
                    e = text[j + 1]
                    if e in '"\\/bfnrt':
                        j += 2
                    elif e == "u":
                        digits = text[j + 2:j + 6]
                        if len(digits) != 4 or any(h not in "0123456789abcdefABCDEF" for h in digits):
                            raise syntax(source, line, j - line_start + 1, "Invalid unicode escape")
                        j += 6
                    else:
                        raise syntax(source, line, j - line_start + 1, "Invalid string escape")
                elif ord(d) < 0x20:
                    raise syntax(source, line, j - line_start + 1, "Control character in string")
                else:
                    j += 1
            try:
                value = json.loads(text[i:j + 1])
            except ValueError:
                raise syntax(source, line, col, "Invalid string literal") from None
            tokens.append(Token("str", value, loc))
            i = j + 1
        else:
            two = text[i:i + 2]
            if two in TWO_CHAR_OPS:
                tokens.append(Token("op", two, loc))
                i += 2
            elif c in ONE_CHAR_OPS:
                tokens.append(Token("op", c, loc))
                i += 1
            else:
                raise syntax(source, line, col, "Illegal token %r" % c)


# ---------------------------------------------------------------- AST

class Node:
    __slots__ = ()


class Proc(Node):
    __slots__ = ("name", "params", "body", "loc")

    def __init__(self, name, params, body, loc):
        self.name, self.params, self.body, self.loc = name, params, body, loc


class Param(Node):
    __slots__ = ("name", "type", "default", "has_default", "loc")

    def __init__(self, name, type_, default, has_default, loc):
        self.name, self.type, self.default, self.has_default, self.loc = (
            name, type_, default, has_default, loc)


class Block(Node):
    __slots__ = ("stmts", "loc")

    def __init__(self, stmts, loc):
        self.stmts, self.loc = stmts, loc


class Stmt(Node):
    """Generic statement: `kind` selects semantics; `a` holds operands."""
    __slots__ = ("kind", "loc", "a", "extra")

    def __init__(self, kind, loc, a=(), extra=None):
        self.kind, self.loc, self.a, self.extra = kind, loc, a, extra


class Expr(Node):
    __slots__ = ("kind", "loc", "value", "args", "type")

    def __init__(self, kind, loc, value=None, args=()):
        self.kind, self.loc, self.value, self.args = kind, loc, value, args
        self.type = None


class Arg(Node):
    __slots__ = ("name", "expr", "loc")

    def __init__(self, name, expr, loc):
        self.name, self.expr, self.loc = name, expr, loc


# ---------------------------------------------------------------- parser

OPERAND_COUNTS = {"receive": 3, "move": 4, "reserve": 4, "release": 2, "ship": 2,
                  "record_delivery": 2}

BINARY_LEVELS = (("||",), ("&&",), ("==", "!="), ("<", "<=", ">", ">="),
                 ("+", "-"), ("*", "/", "%"))


class Parser:
    def __init__(self, source):
        self.source = source
        self.tokens = tokenize(source)
        self.pos = 0

    def peek(self, offset=0):
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def fail(self, tok, message):
        _, line, col = tok.loc
        if tok.kind == "eof":
            message += " (found end of file)"
        else:
            message += " (found %r)" % (tok.value,)
        raise syntax(self.source, line, col, message)

    def is_op(self, value, offset=0):
        tok = self.peek(offset)
        return tok.kind == "op" and tok.value == value

    def is_kw(self, value, offset=0):
        tok = self.peek(offset)
        return tok.kind == "kw" and tok.value == value

    def expect_op(self, value):
        tok = self.peek()
        if tok.kind != "op" or tok.value != value:
            self.fail(tok, "Expected %r" % value)
        return self.advance()

    def expect_kw(self, value):
        tok = self.peek()
        if tok.kind != "kw" or tok.value != value:
            self.fail(tok, "Expected %r" % value)
        return self.advance()

    def expect_name(self):
        tok = self.peek()
        if tok.kind != "name":
            self.fail(tok, "Expected identifier")
        return self.advance()

    def expect_type(self):
        tok = self.peek()
        if tok.kind != "kw" or tok.value not in TYPES:
            self.fail(tok, "Expected type")
        return self.advance().value

    def parse_program(self):
        procs = []
        while self.peek().kind != "eof":
            procs.append(self.parse_proc())
        return procs

    def parse_proc(self):
        self.expect_kw("proc")
        name_tok = self.expect_name()
        self.expect_op("(")
        params = []
        if not self.is_op(")"):
            while True:
                params.append(self.parse_param())
                if self.is_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        body = self.parse_block()
        return Proc(name_tok.value, params, body, name_tok.loc)

    def parse_param(self):
        name_tok = self.expect_name()
        self.expect_op(":")
        type_ = self.expect_type()
        if self.is_op("="):
            self.advance()
            return Param(name_tok.value, type_, self.parse_literal(), True, name_tok.loc)
        return Param(name_tok.value, type_, None, False, name_tok.loc)

    def parse_literal(self):
        tok = self.peek()
        if tok.kind == "int":
            self.advance()
            return tok.value
        if tok.kind == "op" and tok.value == "-" and self.peek(1).kind == "int":
            self.advance()
            return -self.advance().value
        if tok.kind == "str":
            self.advance()
            return tok.value
        if tok.kind == "kw" and tok.value in ("true", "false"):
            self.advance()
            return tok.value == "true"
        self.fail(tok, "Expected literal")

    def parse_block(self):
        open_tok = self.expect_op("{")
        stmts = []
        while not self.is_op("}"):
            if self.peek().kind == "eof":
                self.fail(self.peek(), "Expected '}'")
            stmts.append(self.parse_stmt())
        self.advance()
        return Block(stmts, open_tok.loc)

    def parse_operands(self, count):
        self.expect_op("(")
        operands = [self.parse_expr()]
        for _ in range(count - 1):
            self.expect_op(",")
            operands.append(self.parse_expr())
        self.expect_op(")")
        self.expect_op(";")
        return tuple(operands)

    def parse_stmt(self):
        tok = self.peek()
        loc = tok.loc
        if tok.kind == "name":
            name_tok = self.advance()
            args = self.parse_args()
            self.expect_op(";")
            return Stmt("call", loc, args, name_tok.value)
        if tok.kind != "kw":
            self.fail(tok, "Expected statement")
        kw = tok.value
        if kw == "let":
            self.advance()
            name_tok = self.expect_name()
            self.expect_op(":")
            type_ = self.expect_type()
            self.expect_op("=")
            expr = self.parse_expr()
            self.expect_op(";")
            return Stmt("let", loc, (expr,), (name_tok.value, type_, name_tok.loc))
        if kw == "set":
            self.advance()
            name_tok = self.expect_name()
            self.expect_op("=")
            expr = self.parse_expr()
            self.expect_op(";")
            return Stmt("set", loc, (expr,), (name_tok.value, name_tok.loc))
        if kw == "if":
            self.advance()
            self.expect_op("(")
            cond = self.parse_expr()
            self.expect_op(")")
            then = self.parse_block()
            other = None
            if self.is_kw("else"):
                self.advance()
                other = self.parse_block()
            return Stmt("if", loc, (cond,), (then, other))
        if kw == "while":
            self.advance()
            self.expect_op("(")
            cond = self.parse_expr()
            self.expect_op(")")
            return Stmt("while", loc, (cond,), self.parse_block())
        if kw == "transaction":
            self.advance()
            body = self.parse_block()
            rec_name = rec_block = rec_loc = None
            if self.is_kw("recover"):
                self.advance()
                self.expect_op("(")
                name_tok = self.expect_name()
                rec_name, rec_loc = name_tok.value, name_tok.loc
                self.expect_op(")")
                rec_block = self.parse_block()
            return Stmt("transaction", loc, (), (body, rec_name, rec_block, rec_loc))
        if kw in ("break", "continue", "return"):
            self.advance()
            self.expect_op(";")
            return Stmt(kw, loc)
        if kw in ("assert", "pause"):
            self.advance()
            expr = self.parse_expr()
            self.expect_op(";")
            return Stmt(kw, loc, (expr,))
        if kw == "emit":
            self.advance()
            name = self.parse_expr()
            self.expect_op("{")
            fields = []
            if not self.is_op("}"):
                while True:
                    key_tok = self.expect_name()
                    self.expect_op(":")
                    fields.append((key_tok.value, self.parse_expr(), key_tok.loc))
                    if self.is_op(";"):
                        self.advance()
                        if self.is_op("}"):
                            break
                        continue
                    break
            self.expect_op("}")
            self.expect_op(";")
            return Stmt("emit", loc, (name,), fields)
        if kw in OPERAND_COUNTS:
            self.advance()
            return Stmt(kw, loc, self.parse_operands(OPERAND_COUNTS[kw]))
        self.fail(tok, "Expected statement")

    def parse_args(self):
        self.expect_op("(")
        args = []
        if not self.is_op(")"):
            while True:
                tok = self.peek()
                if tok.kind == "name" and self.is_op("=", 1):
                    self.advance()
                    self.advance()
                    args.append(Arg(tok.value, self.parse_expr(), tok.loc))
                else:
                    args.append(Arg(None, self.parse_expr(), tok.loc))
                if self.is_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        return args

    def parse_expr(self, level=0):
        if level == len(BINARY_LEVELS):
            return self.parse_unary()
        ops = BINARY_LEVELS[level]
        left = self.parse_expr(level + 1)
        while self.peek().kind == "op" and self.peek().value in ops:
            op_tok = self.advance()
            right = self.parse_expr(level + 1)
            left = Expr("binary", op_tok.loc, op_tok.value, (left, right))
        return left

    def parse_unary(self):
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("!", "-"):
            self.advance()
            return Expr("unary", tok.loc, tok.value, (self.parse_unary(),))
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "int":
            self.advance()
            return Expr("lit", tok.loc, tok.value)
        if tok.kind == "str":
            self.advance()
            return Expr("lit", tok.loc, tok.value)
        if tok.kind == "kw" and tok.value in ("true", "false"):
            self.advance()
            return Expr("lit", tok.loc, tok.value == "true")
        if tok.kind == "name":
            self.advance()
            if self.is_op("("):
                return Expr("call", tok.loc, tok.value, self.parse_args())
            return Expr("var", tok.loc, tok.value)
        if tok.kind == "op" and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        self.fail(tok, "Expected expression")


# ---------------------------------------------------------------- checker

def literal_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    return "string"


class Checker:
    def __init__(self, procs, program_source):
        self.proc_list = procs
        self.program_source = program_source
        self.procs = {}
        self.edges = {}

    def check(self):
        for proc in self.proc_list:
            if proc.name in BUILTINS:
                raise static(proc.loc, "Procedure name %r is a reserved builtin" % proc.name)
            if proc.name in self.procs:
                raise static(proc.loc, "Duplicate procedure %r" % proc.name)
            self.procs[proc.name] = proc
            seen = set()
            defaulted = False
            for param in proc.params:
                if param.name in seen:
                    raise static(param.loc, "Duplicate parameter %r" % param.name)
                seen.add(param.name)
                if param.has_default:
                    defaulted = True
                    if literal_type(param.default) != param.type:
                        raise static(param.loc, "Default value type mismatch for %r" % param.name)
                elif defaulted:
                    raise static(param.loc, "Required parameter after defaulted parameter")
        main = self.procs.get("main")
        if main is None or main.loc[0] is not self.program_source:
            raise static((self.program_source, 1, 1), "Program has no main procedure")
        if main.params:
            raise static(main.loc, "main cannot have parameters")
        for proc in self.proc_list:
            self.check_proc(proc)
        self.check_recursion()
        return self.procs

    # -- scopes
    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def check_proc(self, proc):
        self.edges[proc.name] = []
        self.current = proc
        self.loops = 0
        self.scopes = [{p.name: p.type for p in proc.params}]
        for stmt in proc.body.stmts:
            self.stmt(stmt)

    def block(self, block, scope=None):
        self.scopes.append(scope if scope is not None else {})
        for stmt in block.stmts:
            self.stmt(stmt)
        self.scopes.pop()

    def want(self, expr, type_, what):
        actual = self.expr(expr)
        if actual != type_:
            raise static(expr.loc, "%s must be %s, not %s" % (what, type_, actual))

    def stmt(self, s):
        kind = s.kind
        if kind == "let":
            name, type_, name_loc = s.extra
            actual = self.expr(s.a[0])
            if name in self.scopes[-1]:
                raise static(name_loc, "Duplicate declaration of %r" % name)
            if actual != type_:
                raise static(s.a[0].loc, "Cannot initialize %s %r with %s" % (type_, name, actual))
            self.scopes[-1][name] = type_
        elif kind == "set":
            name, name_loc = s.extra
            target = self.lookup(name)
            if target is None:
                raise static(name_loc, "Unknown variable %r" % name)
            if target == "error":
                raise static(name_loc, "Cannot assign recovery binding %r" % name)
            actual = self.expr(s.a[0])
            if actual != target:
                raise static(s.a[0].loc, "Cannot assign %s to %s %r" % (actual, target, name))
        elif kind == "if":
            self.want(s.a[0], "bool", "Condition")
            then, other = s.extra
            self.block(then)
            if other is not None:
                self.block(other)
        elif kind == "while":
            self.want(s.a[0], "bool", "Condition")
            self.loops += 1
            self.block(s.extra)
            self.loops -= 1
        elif kind == "transaction":
            body, rec_name, rec_block, _ = s.extra
            self.block(body)
            if rec_block is not None:
                self.block(rec_block, {rec_name: "error"})
        elif kind in ("break", "continue"):
            if self.loops == 0:
                raise static(s.loc, "%s outside loop" % kind)
        elif kind == "return":
            pass
        elif kind == "assert":
            self.want(s.a[0], "bool", "Assertion")
        elif kind == "pause":
            self.want(s.a[0], "string", "Pause label")
        elif kind == "emit":
            self.want(s.a[0], "string", "Event name")
            seen = set()
            for key, value, key_loc in s.extra:
                if key in seen:
                    raise static(key_loc, "Duplicate emit key %r" % key)
                seen.add(key)
                if self.expr(value) not in TYPES:
                    raise static(value.loc, "Emit payload must be int, bool or string")
        elif kind in OPERAND_COUNTS:
            signature = {
                "receive": ("string", "string", "int"),
                "move": ("string", "string", "string", "int"),
                "reserve": ("string", "string", "string", "int"),
                "release": ("string", "int"),
                "ship": ("string", "int"),
                "record_delivery": ("string", "string"),
            }[kind]
            for operand, type_ in zip(s.a, signature):
                self.want(operand, type_, "%s operand" % kind)
        elif kind == "call":
            self.call_stmt(s)
        else:  # pragma: no cover
            raise AssertionError(kind)

    def call_stmt(self, s):
        name = s.extra
        if name in BUILTINS:
            raise static(s.loc, "Builtin %r cannot be used as a statement" % name)
        proc = self.procs.get(name)
        if proc is None:
            raise static(s.loc, "Unknown procedure %r" % name)
        params = {p.name: p for p in proc.params}
        bound = set()
        named_seen = False
        positional = 0
        for arg in s.a:
            if arg.name is None:
                if named_seen:
                    raise static(arg.loc, "Positional argument after named argument")
                if positional >= len(proc.params):
                    raise static(arg.loc, "Too many arguments to %r" % name)
                param = proc.params[positional]
                positional += 1
            else:
                named_seen = True
                param = params.get(arg.name)
                if param is None:
                    raise static(arg.loc, "Unknown argument %r for %r" % (arg.name, name))
                if param.name in bound:
                    raise static(arg.loc, "Argument %r bound more than once" % arg.name)
            bound.add(param.name)
            actual = self.expr(arg.expr)
            if actual != param.type:
                raise static(arg.expr.loc, "Argument %r must be %s, not %s"
                             % (param.name, param.type, actual))
        for param in proc.params:
            if param.name not in bound and not param.has_default:
                raise static(s.loc, "Missing argument %r for %r" % (param.name, name))
        self.edges[self.current.name].append((name, s.loc))

    def expr(self, e):
        e.type = self._expr(e)
        return e.type

    def _expr(self, e):
        kind = e.kind
        if kind == "lit":
            return literal_type(e.value)
        if kind == "var":
            type_ = self.lookup(e.value)
            if type_ is None:
                raise static(e.loc, "Unknown variable %r" % e.value)
            if type_ == "error":
                raise static(e.loc, "Recovery binding %r can only be used with code()" % e.value)
            return type_
        if kind == "unary":
            operand = self.expr(e.args[0])
            want = "bool" if e.value == "!" else "int"
            if operand != want:
                raise static(e.loc, "Operator %s requires %s" % (e.value, want))
            return want
        if kind == "binary":
            op = e.value
            left = self.expr(e.args[0])
            right = self.expr(e.args[1])
            if op in ("&&", "||"):
                if left != "bool" or right != "bool":
                    raise static(e.loc, "Operator %s requires bool operands" % op)
                return "bool"
            if op in ("==", "!="):
                if left != right:
                    raise static(e.loc, "Equality requires identical types")
                return "bool"
            if op in ("<", "<=", ">", ">="):
                if left != right or left not in ("int", "string"):
                    raise static(e.loc, "Ordering requires int/int or string/string")
                return "bool"
            if op == "+":
                if left != right or left not in ("int", "string"):
                    raise static(e.loc, "+ requires int/int or string/string")
                return left
            if left != "int" or right != "int":
                raise static(e.loc, "Operator %s requires int operands" % op)
            return "int"
        if kind == "call":
            name = e.value
            if name not in BUILTINS:
                if name in self.procs:
                    raise static(e.loc, "Procedure %r cannot be used as an expression" % name)
                raise static(e.loc, "Unknown builtin %r" % name)
            params, result = BUILTINS[name]
            for arg in e.args:
                if arg.name is not None:
                    raise static(arg.loc, "Builtin %r accepts positional arguments only" % name)
            if len(e.args) != len(params):
                raise static(e.loc, "Builtin %r expects %d arguments" % (name, len(params)))
            if name == "code":
                target = e.args[0].expr
                if target.kind != "var" or self.lookup(target.value) != "error":
                    raise static(target.loc, "code() requires a recovery binding")
                target.type = "error"
                return result
            for arg, type_ in zip(e.args, params):
                actual = self.expr(arg.expr)
                if actual != type_:
                    raise static(arg.expr.loc, "Builtin %r argument must be %s, not %s"
                                 % (name, type_, actual))
            return result
        raise AssertionError(kind)  # pragma: no cover

    def check_recursion(self):
        state = {}

        def visit(name):
            state[name] = 1
            for callee, loc in self.edges.get(name, ()):
                mark = state.get(callee, 0)
                if mark == 1:
                    raise static(loc, "Recursive call to %r" % callee)
                if mark == 0:
                    visit(callee)
            state[name] = 2

        for proc in self.proc_list:
            if state.get(proc.name, 0) == 0:
                visit(proc.name)


def compile_unit(program, library):
    """Parse library (if any) then program, and validate them as one unit."""
    procs = []
    if library is not None:
        procs.extend(Parser(library).parse_program())
    procs.extend(Parser(program).parse_program())
    return Checker(procs, program).check()
