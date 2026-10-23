from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Token:
    text: str
    file: str
    line: int
    column: int


class Fault(Exception):
    def __init__(self, category: str, message: str, token: Token | None = None,
                 code: str | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.token = token
        self.code = code
        self.stack: list[str] | None = None

    def diagnostic(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.category, "message": self.message}
        if self.token:
            result.update(file=self.token.file, line=self.token.line,
                          column=self.token.column)
        if self.code:
            result["code"] = self.code
        if self.stack is not None:
            result["stack"] = self.stack
        return result


@dataclass
class Node:
    op: str
    token: Token
    args: list[Any] = field(default_factory=list)


KEYWORDS = set("""
proc int bool string let set if else while transaction recover break continue
return assert emit receive move reserve release ship true false pause record_delivery
""".split())
TYPES = {"int", "bool", "string"}
BUILTINS: dict[str, tuple[list[str], str]] = {
    "onhand": (["string", "string"], "int"),
    "available": (["string", "string"], "int"),
    "remaining": (["string"], "int"),
    "len": (["string"], "int"),
    "code": (["error"], "string"),
    "carrier_send": (["string", "string", "string", "int", "string", "int"], "string"),
    "carrier_receipt": (["string"], "string"),
    "carrier_warehouse": (["string"], "string"),
    "carrier_matches": (["string", "string", "string", "int", "string", "int"], "bool"),
    "delivered": (["string"], "bool"),
}
OPERATIONS = {
    "receive": ["string", "string", "int"],
    "move": ["string", "string", "string", "int"],
    "reserve": ["string", "string", "string", "int"],
    "release": ["string", "int"],
    "ship": ["string", "int"],
    "record_delivery": ["string", "string"],
}
PATTERN = re.compile(
    r'(?P<space>\s+)|(?P<comment>//[^\n]*)|'
    r'(?P<string>"(?:\\.|[^"\\\n])*")|(?P<int>[0-9]+)|'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)|'
    r'(?P<symbol>==|!=|<=|>=|&&|\|\||[{}(),:;=+\-*/%!<>])'
)


def tokenize(source: str, filename: str) -> list[Token]:
    result: list[Token] = []
    offset, line, column = 0, 1, 1
    while offset < len(source):
        match = PATTERN.match(source, offset)
        if match is None:
            raise Fault("SYNTAX", "Illegal token", Token(source[offset], filename, line, column))
        text = match.group()
        if match.lastgroup not in {"space", "comment"}:
            result.append(Token(text, filename, line, column))
        if "\n" in text:
            line += text.count("\n")
            column = len(text.rsplit("\n", 1)[1]) + 1
        else:
            column += len(text)
        offset = match.end()
    result.append(Token("<eof>", filename, line, column))
    return result


class Parser:
    PRECEDENCE = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4,
                  ">": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}

    def __init__(self, text: str, filename: str):
        self.tokens = tokenize(text, filename)
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def take(self, expected: str | None = None) -> Token:
        token = self.current
        if expected is not None and token.text != expected:
            raise Fault("SYNTAX", f"Expected {expected}, found {token.text}", token)
        self.pos += 1
        return token

    def accept(self, text: str) -> bool:
        if self.current.text == text:
            self.take()
            return True
        return False

    def name(self) -> Token:
        token = self.current
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token.text) or token.text in KEYWORDS:
            raise Fault("SYNTAX", "Expected identifier", token)
        return self.take()

    def type_name(self) -> str:
        token = self.current
        if token.text not in TYPES:
            raise Fault("SYNTAX", "Expected scalar type", token)
        return self.take().text

    def literal(self) -> Node:
        token = self.current
        negative = self.accept("-")
        if negative:
            digits = self.take()
            if not digits.text.isdigit():
                raise Fault("SYNTAX", "Default must be a literal", token)
            return Node("literal", token, [-int(digits.text)])
        if token.text.isdigit():
            self.take()
            return Node("literal", token, [int(token.text)])
        if token.text in {"true", "false"}:
            self.take()
            return Node("literal", token, [token.text == "true"])
        if token.text.startswith('"'):
            self.take()
            try:
                value = json.loads(token.text)
            except ValueError as exc:
                raise Fault("SYNTAX", "Invalid string literal", token) from exc
            return Node("literal", token, [value])
        raise Fault("SYNTAX", "Expected literal", token)

    def arguments(self) -> list[tuple[str | None, Node]]:
        self.take("(")
        args: list[tuple[str | None, Node]] = []
        if not self.accept(")"):
            while True:
                name = None
                if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].text == "=":
                    name = self.name().text
                    self.take("=")
                args.append((name, self.expression()))
                if self.accept(")"):
                    break
                self.take(",")
        return args

    def expression(self, minimum: int = 1) -> Node:
        token = self.current
        if token.text in {"!", "-"}:
            self.take()
            left = Node("unary", token, [token.text, self.expression(7)])
        elif self.accept("("):
            left = self.expression()
            self.take(")")
        elif token.text.isdigit() or token.text.startswith('"') or token.text in {"true", "false"}:
            left = self.literal()
        else:
            name = self.name()
            left = (Node("builtin", name, [name.text, self.arguments()])
                    if self.current.text == "(" else Node("variable", name, [name.text]))
        while self.PRECEDENCE.get(self.current.text, 0) >= minimum:
            operator = self.take()
            right = self.expression(self.PRECEDENCE[operator.text] + 1)
            left = Node("binary", operator, [operator.text, left, right])
        return left

    def block(self) -> list[Node]:
        self.take("{")
        result = []
        while not self.accept("}"):
            if self.current.text == "<eof>":
                raise Fault("SYNTAX", "Unclosed block", self.current)
            result.append(self.statement())
        return result

    def statement(self) -> Node:
        token = self.take()
        op = token.text
        if op == "let":
            name = self.name().text
            self.take(":")
            typ = self.type_name()
            self.take("=")
            args = [name, typ, self.expression()]
        elif op == "set":
            name = self.name().text
            self.take("=")
            args = [name, self.expression()]
        elif op in {"if", "while"}:
            self.take("(")
            condition = self.expression()
            self.take(")")
            body = self.block()
            otherwise = self.block() if op == "if" and self.accept("else") else []
            return Node(op, token, [condition, body, otherwise])
        elif op == "transaction":
            body = self.block()
            name, recovery = None, None
            if self.accept("recover"):
                self.take("(")
                name = self.name().text
                self.take(")")
                recovery = self.block()
            return Node(op, token, [body, name, recovery])
        elif op in {"break", "continue", "return"}:
            args = []
        elif op in {"assert", "pause"}:
            args = [self.expression()]
        elif op == "emit":
            name_expr = self.expression()
            self.take("{")
            pairs = []
            if not self.accept("}"):
                while True:
                    name_token = self.name()
                    self.take(":")
                    pairs.append((name_token, self.expression()))
                    if self.accept("}"):
                        break
                    self.take(";")
                    if self.accept("}"):
                        break
            args = [name_expr, pairs]
        elif op in OPERATIONS:
            args = self.arguments()
        else:
            if op in KEYWORDS or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", op):
                raise Fault("SYNTAX", "Expected statement", token)
            args = [op, self.arguments()]
            op = "call"
        self.take(";")
        return Node(op, token, args)

    def program(self) -> list[Node]:
        procedures = []
        while self.current.text != "<eof>":
            token = self.take("proc")
            name = self.name().text
            self.take("(")
            params = []
            if not self.accept(")"):
                while True:
                    parameter = self.name()
                    self.take(":")
                    typ = self.type_name()
                    default = self.literal() if self.accept("=") else None
                    params.append((parameter, typ, default))
                    if self.accept(")"):
                        break
                    self.take(",")
            procedures.append(Node("proc", token, [name, params, self.block()]))
        return procedures


def scalar_type(value: Any) -> str:
    return {int: "int", bool: "bool", str: "string"}[type(value)]


def bind_arguments(params: list[Any], args: list[tuple[str | None, Any]],
                   token: Token) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    names = [p[0].text for p in params]
    named = False
    for index, (name, value) in enumerate(args):
        if name is None:
            if named or index >= len(names):
                raise Fault("STATIC", "Invalid positional argument", token)
            name = names[index]
        else:
            named = True
        if name not in names or name in bound:
            raise Fault("STATIC", "Unknown or duplicate argument", token)
        bound[name] = value
    for name, _, default in params:
        if name.text not in bound:
            if default is None:
                raise Fault("STATIC", "Missing argument", token)
            bound[name.text] = default
    return bound


class Checker:
    def __init__(self, procedures: list[Node]):
        self.procedures: dict[str, Node] = {}
        self.scopes: list[dict[str, str]] = []
        self.calls: dict[str, list[str]] = {}
        self.owner = ""
        for proc in procedures:
            name, params, _ = proc.args
            if name in self.procedures or name in BUILTINS:
                raise Fault("STATIC", "Duplicate/reserved procedure", proc.token)
            self.procedures[name] = proc
            seen, optional = set(), False
            for token, typ, default in params:
                if token.text in seen:
                    raise Fault("STATIC", "Duplicate parameter", token)
                seen.add(token.text)
                if default is not None:
                    optional = True
                    self.require(self.expr_literal(default), typ, default.token)
                elif optional:
                    raise Fault("STATIC", "Required parameter after default", token)
        if "main" not in self.procedures:
            token = procedures[0].token if procedures else Token("", "<program>", 1, 1)
            raise Fault("STATIC", "Missing main", token)
        if self.procedures["main"].args[1]:
            raise Fault("STATIC", "Main cannot have parameters", self.procedures["main"].token)

    @staticmethod
    def require(actual: str, wanted: str, token: Token) -> None:
        if actual != wanted:
            raise Fault("STATIC", f"Expected {wanted}, found {actual}", token)

    @staticmethod
    def expr_literal(node: Node) -> str:
        return scalar_type(node.args[0])

    def lookup(self, name: str, token: Token) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise Fault("STATIC", f"Undefined name {name}", token)

    def declare(self, name: str, typ: str, token: Token) -> None:
        if name in self.scopes[-1]:
            raise Fault("STATIC", "Duplicate local", token)
        self.scopes[-1][name] = typ

    def expression(self, node: Node) -> str:
        op, a, token = node.op, node.args, node.token
        if op == "literal":
            return self.expr_literal(node)
        if op == "variable":
            return self.lookup(a[0], token)
        if op == "builtin":
            name, args = a
            if name not in BUILTINS:
                raise Fault("STATIC", "Unknown expression function", token)
            wanted, result = BUILTINS[name]
            self.check_args(args, wanted, token)
            return result
        if op == "unary":
            wanted = "bool" if a[0] == "!" else "int"
            self.require(self.expression(a[1]), wanted, token)
            return wanted
        operator, left, right = a
        lt, rt = self.expression(left), self.expression(right)
        self.require(rt, lt, token)
        if operator in {"&&", "||"}:
            self.require(lt, "bool", token)
            return "bool"
        if operator in {"==", "!="}:
            if lt == "error":
                raise Fault("STATIC", "Error is not comparable", token)
            return "bool"
        if operator in {"<", "<=", ">", ">="}:
            if lt not in {"int", "string"}:
                raise Fault("STATIC", "Invalid ordering", token)
            return "bool"
        if operator == "+" and lt == "string":
            return "string"
        self.require(lt, "int", token)
        return "int"

    def check_args(self, args: list[Any], wanted: list[str], token: Token) -> None:
        if len(args) != len(wanted) or any(name is not None for name, _ in args):
            raise Fault("STATIC", "Invalid builtin/operation arguments", token)
        for (_, expr), typ in zip(args, wanted):
            self.require(self.expression(expr), typ, expr.token)

    def block(self, statements: list[Node], loops: int, fresh: bool = True) -> None:
        if fresh:
            self.scopes.append({})
        for node in statements:
            op, a, token = node.op, node.args, node.token
            if op == "let":
                self.require(self.expression(a[2]), a[1], token)
                self.declare(a[0], a[1], token)
            elif op == "set":
                typ = self.lookup(a[0], token)
                if typ == "error":
                    raise Fault("STATIC", "Recovery bindings are immutable", token)
                self.require(self.expression(a[1]), typ, token)
            elif op in {"if", "while"}:
                self.require(self.expression(a[0]), "bool", token)
                self.block(a[1], loops + (op == "while"))
                self.block(a[2], loops)
            elif op == "transaction":
                self.block(a[0], loops)
                if a[2] is not None:
                    self.scopes.append({a[1]: "error"})
                    self.block(a[2], loops, fresh=False)
                    self.scopes.pop()
            elif op in {"break", "continue"}:
                if not loops:
                    raise Fault("STATIC", "Loop control outside loop", token)
            elif op == "return":
                pass
            elif op == "assert":
                self.require(self.expression(a[0]), "bool", token)
            elif op == "pause":
                self.require(self.expression(a[0]), "string", token)
            elif op == "emit":
                self.require(self.expression(a[0]), "string", token)
                keys = set()
                for key, expr in a[1]:
                    if key.text in keys:
                        raise Fault("STATIC", "Duplicate emit key", key)
                    keys.add(key.text)
                    if self.expression(expr) == "error":
                        raise Fault("STATIC", "Cannot emit error binding", expr.token)
            elif op in OPERATIONS:
                self.check_args(a, OPERATIONS[op], token)
            elif op == "call":
                name, args = a
                if name not in self.procedures:
                    raise Fault("STATIC", "Undefined procedure", token)
                bound = bind_arguments(self.procedures[name].args[1], args, token)
                for param, typ, _ in self.procedures[name].args[1]:
                    self.require(self.expression(bound[param.text]), typ, token)
                self.calls[self.owner].append(name)
        if fresh:
            self.scopes.pop()

    def validate(self) -> dict[str, Node]:
        for name, proc in self.procedures.items():
            self.owner = name
            self.calls[name] = []
            self.scopes = [{p.text: typ for p, typ, _ in proc.args[1]}]
            self.block(proc.args[2], 0, fresh=False)
        visited, active = set(), set()

        def visit(name: str) -> None:
            if name in active:
                raise Fault("STATIC", "Recursive call graph", self.procedures[name].token)
            if name in visited:
                return
            active.add(name)
            for child in self.calls[name]:
                visit(child)
            active.remove(name)
            visited.add(name)

        for name in self.procedures:
            visit(name)
        return self.procedures
