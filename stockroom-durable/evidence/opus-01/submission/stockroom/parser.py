"""Lexer and recursive-descent parser producing a small AST."""
import bisect
import json
import re

from .errors import StockError

KEYWORDS = frozenset({
    "proc", "int", "bool", "string", "let", "set", "if", "else", "while",
    "transaction", "recover", "break", "continue", "return", "assert", "emit",
    "receive", "move", "reserve", "release", "ship", "true", "false", "pause",
})
TYPES = ("int", "bool", "string")
OPERATIONS = {"receive": 3, "move": 4, "reserve": 4, "release": 2, "ship": 2}

_TOKEN = re.compile(r'''
  (?P<ws>[ \t\r\n]+)
| (?P<comment>//[^\n]*)
| (?P<id>[A-Za-z_][A-Za-z0-9_]*)
| (?P<int>[0-9]+)
| (?P<str>"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*")
| (?P<op>==|!=|<=|>=|&&|\|\||[(){},;:=<>+\-*/%!])
''', re.X)


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def is_op(self, value):
        return self.kind == "op" and self.value == value

    def is_kw(self, value):
        return self.kind == "kw" and self.value == value


class Node:
    """Generic AST node: ``kind``, ``pos`` and keyword fields."""

    def __init__(self, kind, pos, **fields):
        self.kind = kind
        self.pos = pos
        self.__dict__.update(fields)


def decode_source(data, role):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        prefix = data[:exc.start].decode("utf-8", errors="replace")
        line = prefix.count("\n") + 1
        col = len(prefix) - (prefix.rfind("\n") + 1) + 1
        raise StockError("SYNTAX", "source is not valid UTF-8",
                         (role, line, col)) from None


def tokenize(text, role):
    starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def position(offset):
        index = bisect.bisect_right(starts, offset) - 1
        return (role, index + 1, offset - starts[index] + 1)

    tokens = []
    offset = 0
    length = len(text)
    while offset < length:
        match = _TOKEN.match(text, offset)
        if match is None:
            if text[offset] == '"':
                raise StockError("SYNTAX", "unterminated or invalid string literal",
                                 position(offset))
            raise StockError("SYNTAX", "illegal character %r" % text[offset],
                             position(offset))
        kind = match.lastgroup
        lexeme = match.group()
        if kind == "id":
            tokens.append(Token("kw" if lexeme in KEYWORDS else "id", lexeme,
                                position(offset)))
        elif kind == "int":
            tokens.append(Token("int", int(lexeme), position(offset)))
        elif kind == "str":
            tokens.append(Token("str", json.loads(lexeme), position(offset)))
        elif kind == "op":
            tokens.append(Token("op", lexeme, position(offset)))
        offset = match.end()
    tokens.append(Token("eof", None, position(length)))
    return tokens


class Parser:
    def __init__(self, text, role):
        self.role = role
        self.tokens = tokenize(text, role)
        self.index = 0

    # -- helpers -----------------------------------------------------------
    @property
    def tok(self):
        return self.tokens[self.index]

    def peek(self, distance=1):
        return self.tokens[min(self.index + distance, len(self.tokens) - 1)]

    def advance(self):
        token = self.tokens[self.index]
        if token.kind != "eof":
            self.index += 1
        return token

    def fail(self, expected, token=None):
        token = token or self.tok
        if token.kind == "eof":
            found = "end of file"
        else:
            found = repr(token.value) if token.kind != "str" else "string"
        raise StockError("SYNTAX", "expected %s, found %s" % (expected, found),
                         token.pos)

    def expect_op(self, value):
        if not self.tok.is_op(value):
            self.fail("'%s'" % value)
        return self.advance()

    def expect_kw(self, value):
        if not self.tok.is_kw(value):
            self.fail("'%s'" % value)
        return self.advance()

    def expect_name(self):
        if self.tok.kind != "id":
            self.fail("identifier")
        return self.advance()

    def expect_type(self):
        if self.tok.kind == "kw" and self.tok.value in TYPES:
            return self.advance().value
        self.fail("type")

    # -- declarations ------------------------------------------------------
    def parse_program(self):
        procs = []
        while self.tok.kind != "eof":
            procs.append(self.parse_proc())
        return procs

    def parse_proc(self):
        start = self.expect_kw("proc")
        name = self.expect_name()
        self.expect_op("(")
        params = []
        if not self.tok.is_op(")"):
            params.append(self.parse_param())
            while self.tok.is_op(","):
                self.advance()
                params.append(self.parse_param())
        self.expect_op(")")
        body = self.parse_block()
        return Node("proc", name.pos, name=name.value, params=params, body=body,
                    start=start.pos)

    def parse_param(self):
        name = self.expect_name()
        self.expect_op(":")
        ptype = self.expect_type()
        default = None
        if self.tok.is_op("="):
            self.advance()
            default = self.parse_literal()
        return Node("param", name.pos, name=name.value, type=ptype, default=default)

    def parse_literal(self):
        token = self.tok
        if token.kind == "int":
            self.advance()
            return Node("lit", token.pos, type="int", value=token.value)
        if token.is_op("-") and self.peek().kind == "int":
            self.advance()
            value = self.advance().value
            return Node("lit", token.pos, type="int", value=-value)
        if token.kind == "str":
            self.advance()
            return Node("lit", token.pos, type="string", value=token.value)
        if token.is_kw("true") or token.is_kw("false"):
            self.advance()
            return Node("lit", token.pos, type="bool", value=token.value == "true")
        self.fail("literal")

    # -- statements --------------------------------------------------------
    def parse_block(self):
        start = self.expect_op("{")
        stmts = []
        while not self.tok.is_op("}"):
            if self.tok.kind == "eof":
                self.fail("'}'")
            stmts.append(self.parse_statement())
        self.advance()
        return Node("block", start.pos, stmts=stmts)

    def parse_statement(self):
        token = self.tok
        pos = token.pos
        if token.kind == "kw":
            word = token.value
            if word == "let":
                self.advance()
                name = self.expect_name()
                self.expect_op(":")
                vtype = self.expect_type()
                self.expect_op("=")
                expr = self.parse_expr()
                self.expect_op(";")
                return Node("let", pos, name=name.value, name_pos=name.pos,
                            type=vtype, expr=expr)
            if word == "set":
                self.advance()
                name = self.expect_name()
                self.expect_op("=")
                expr = self.parse_expr()
                self.expect_op(";")
                return Node("set", pos, name=name.value, name_pos=name.pos, expr=expr)
            if word == "if":
                self.advance()
                self.expect_op("(")
                cond = self.parse_expr()
                self.expect_op(")")
                then = self.parse_block()
                other = None
                if self.tok.is_kw("else"):
                    self.advance()
                    other = self.parse_block()
                return Node("if", pos, cond=cond, then=then, other=other)
            if word == "while":
                self.advance()
                self.expect_op("(")
                cond = self.parse_expr()
                self.expect_op(")")
                body = self.parse_block()
                return Node("while", pos, cond=cond, body=body)
            if word == "transaction":
                self.advance()
                body = self.parse_block()
                errname = None
                handler = None
                errpos = None
                if self.tok.is_kw("recover"):
                    self.advance()
                    self.expect_op("(")
                    name = self.expect_name()
                    errname, errpos = name.value, name.pos
                    self.expect_op(")")
                    handler = self.parse_block()
                return Node("tx", pos, body=body, errname=errname, errpos=errpos,
                            handler=handler)
            if word in ("break", "continue", "return"):
                self.advance()
                self.expect_op(";")
                return Node(word, pos)
            if word in ("assert", "pause"):
                self.advance()
                expr = self.parse_expr()
                self.expect_op(";")
                return Node(word, pos, expr=expr)
            if word == "emit":
                self.advance()
                name = self.parse_expr()
                self.expect_op("{")
                fields = []
                if not self.tok.is_op("}"):
                    while True:
                        key = self.expect_name()
                        self.expect_op(":")
                        fields.append((key.value, key.pos, self.parse_expr()))
                        if self.tok.is_op(";"):
                            self.advance()
                            if self.tok.is_op("}"):
                                break
                            continue
                        break
                self.expect_op("}")
                self.expect_op(";")
                return Node("emit", pos, name=name, fields=fields)
            if word in OPERATIONS:
                self.advance()
                self.expect_op("(")
                args = [self.parse_expr()]
                for _ in range(OPERATIONS[word] - 1):
                    self.expect_op(",")
                    args.append(self.parse_expr())
                self.expect_op(")")
                self.expect_op(";")
                return Node("op", pos, op=word, args=args)
            self.fail("statement")
        if token.kind == "id" and self.peek().is_op("("):
            self.advance()
            self.advance()
            args = []
            if not self.tok.is_op(")"):
                args.append(self.parse_argument())
                while self.tok.is_op(","):
                    self.advance()
                    args.append(self.parse_argument())
            self.expect_op(")")
            self.expect_op(";")
            return Node("call", pos, name=token.value, args=args)
        self.fail("statement")

    def parse_argument(self):
        if self.tok.kind == "id" and self.peek().is_op("="):
            name = self.advance()
            self.advance()
            return (name.value, name.pos, self.parse_expr())
        token = self.tok
        return (None, token.pos, self.parse_expr())

    # -- expressions -------------------------------------------------------
    _LEVELS = (("||",), ("&&",), ("==", "!="), ("<", "<=", ">", ">="),
               ("+", "-"), ("*", "/", "%"))

    def parse_expr(self, level=0):
        if level == len(self._LEVELS):
            return self.parse_unary()
        ops = self._LEVELS[level]
        left = self.parse_expr(level + 1)
        while self.tok.kind == "op" and self.tok.value in ops:
            op = self.advance()
            right = self.parse_expr(level + 1)
            left = Node("bin", op.pos, op=op.value, left=left, right=right)
        return left

    def parse_unary(self):
        token = self.tok
        if token.is_op("!") or token.is_op("-"):
            ops = []
            while self.tok.is_op("!") or self.tok.is_op("-"):
                ops.append(self.advance())
            node = self.parse_primary()
            for op in reversed(ops):
                node = Node("un", op.pos, op=op.value, operand=node)
            return node
        return self.parse_primary()

    def parse_primary(self):
        token = self.tok
        if token.kind == "int":
            self.advance()
            return Node("lit", token.pos, type="int", value=token.value)
        if token.kind == "str":
            self.advance()
            return Node("lit", token.pos, type="string", value=token.value)
        if token.is_kw("true") or token.is_kw("false"):
            self.advance()
            return Node("lit", token.pos, type="bool", value=token.value == "true")
        if token.is_op("("):
            self.advance()
            node = self.parse_expr()
            self.expect_op(")")
            return node
        if token.kind == "id":
            self.advance()
            if self.tok.is_op("("):
                self.advance()
                args = []
                if not self.tok.is_op(")"):
                    args.append(self.parse_argument())
                    while self.tok.is_op(","):
                        self.advance()
                        args.append(self.parse_argument())
                self.expect_op(")")
                return Node("fcall", token.pos, name=token.value, args=args)
            return Node("var", token.pos, name=token.value)
        self.fail("expression")


def parse(text, role):
    return Parser(text, role).parse_program()
