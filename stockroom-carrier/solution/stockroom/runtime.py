from __future__ import annotations

import copy
from typing import Any

from .language import Fault, Node, bind_arguments


class Flow(Exception):
    def __init__(self, kind: str):
        self.kind = kind


class Engine:
    def __init__(self, procedures: dict[str, Node], warehouses: dict[str, dict[str, int]]):
        self.procedures = procedures
        self.warehouses = copy.deepcopy(warehouses)
        self.holds: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.frames: list[list[dict[str, Any]]] = []
        self.stack: list[str] = []
        self.stats = {"steps": 0, "committed": 0, "rolled_back": 0}

    @property
    def scopes(self) -> list[dict[str, Any]]:
        return self.frames[-1]

    def locate(self, name: str) -> dict[str, Any]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope
        raise AssertionError(f"Checker missed variable {name}")

    @staticmethod
    def domain(code: str, message: str) -> None:
        raise Fault("DOMAIN", message, code=code)

    def warehouse(self, name: str) -> dict[str, int]:
        if name not in self.warehouses:
            self.domain("WAREHOUSE", f"Unknown warehouse {name}")
        return self.warehouses[name]

    def hold(self, name: str) -> dict[str, Any]:
        if not name:
            self.domain("NAME", "Empty hold ID")
        if name not in self.holds:
            self.domain("HOLD", f"Unknown hold {name}")
        return self.holds[name]

    def onhand(self, warehouse: str, sku: str) -> int:
        if not sku:
            self.domain("NAME", "Empty SKU")
        return self.warehouse(warehouse).get(sku, 0)

    def available(self, warehouse: str, sku: str) -> int:
        return self.onhand(warehouse, sku) - sum(
            h["remaining"] for h in self.holds.values()
            if h["warehouse"] == warehouse and h["sku"] == sku
        )

    def annotate(self, error: Fault, node: Node) -> None:
        if error.token is None:
            error.token = node.token
        if error.category in {"DOMAIN", "RUNTIME"} and error.stack is None:
            error.stack = list(self.stack)

    def expression(self, node: Node) -> Any:
        try:
            return self.evaluate(node)
        except Fault as error:
            self.annotate(error, node)
            raise

    def evaluate(self, node: Node) -> Any:
        op, a = node.op, node.args
        if op == "literal":
            return a[0]
        if op == "variable":
            return self.locate(a[0])[a[0]]
        if op == "unary":
            value = self.expression(a[1])
            return not value if a[0] == "!" else -value
        if op == "builtin":
            name, args = a
            values = [self.expression(expr) for _, expr in args]
            if name == "onhand":
                return self.onhand(*values)
            if name == "available":
                return self.available(*values)
            if name == "remaining":
                return self.hold(values[0])["remaining"]
            if name == "len":
                return len(values[0])
            if name == "code":
                return values[0].code
            raise AssertionError(name)
        operator, left, right = a
        lv = self.expression(left)
        if operator == "&&":
            return lv and self.expression(right)
        if operator == "||":
            return lv or self.expression(right)
        rv = self.expression(right)
        if operator == "+":
            return lv + rv
        if operator == "-":
            return lv - rv
        if operator == "*":
            return lv * rv
        if operator in {"/", "%"}:
            if rv == 0:
                raise Fault("RUNTIME", "Division by zero")
            quotient = abs(lv) // abs(rv)
            if (lv < 0) != (rv < 0):
                quotient = -quotient
            return quotient if operator == "/" else lv - quotient * rv
        if operator == "==":
            return lv == rv
        if operator == "!=":
            return lv != rv
        if operator == "<":
            return lv < rv
        if operator == "<=":
            return lv <= rv
        if operator == ">":
            return lv > rv
        if operator == ">=":
            return lv >= rv
        raise AssertionError(operator)

    def operation(self, op: str, values: list[Any]) -> None:
        quantity = values[-1]
        if quantity <= 0:
            self.domain("QUANTITY", "Quantity must be positive")
        if op in {"ship", "release"}:
            name = values[0]
            hold = self.hold(name)
            if hold["remaining"] < quantity:
                self.domain("SHORTAGE", "Hold has insufficient remaining units")
            hold["remaining"] -= quantity
            if op == "ship":
                self.warehouses[hold["warehouse"]][hold["sku"]] -= quantity
            return
        if op == "reserve":
            name, warehouse, sku, _ = values
            if not name or not sku:
                self.domain("NAME", "Empty hold ID or SKU")
            if name in self.holds:
                self.domain("DUPLICATE_HOLD", "Hold ID already used")
            if self.available(warehouse, sku) < quantity:
                self.domain("SHORTAGE", "Insufficient free stock")
            self.holds[name] = {"warehouse": warehouse, "sku": sku, "remaining": quantity}
            return
        if op == "receive":
            warehouse, sku, _ = values
            value = self.onhand(warehouse, sku)
            self.warehouses[warehouse][sku] = value + quantity
            return
        source, destination, sku, _ = values
        source_map = self.warehouse(source)
        destination_map = self.warehouse(destination)
        if not sku:
            self.domain("NAME", "Empty SKU")
        if source == destination:
            self.domain("SAME_WAREHOUSE", "Source equals destination")
        if self.available(source, sku) < quantity:
            self.domain("SHORTAGE", "Insufficient free stock")
        source_map[sku] = source_map.get(sku, 0) - quantity
        destination_map[sku] = destination_map.get(sku, 0) + quantity

    def block(self, body: list[Node], initial: dict[str, Any] | None = None,
              fresh: bool = True) -> None:
        if fresh:
            self.scopes.append({} if initial is None else initial)
        try:
            for node in body:
                self.statement(node)
        finally:
            if fresh:
                self.scopes.pop()

    def call(self, name: str, arguments: list[tuple[str | None, Any]]) -> None:
        proc = self.procedures[name]
        bound = bind_arguments(proc.args[1], arguments, proc.token)
        values = {key: value.args[0] if isinstance(value, Node) else value
                  for key, value in bound.items()}
        self.frames.append([values])
        self.stack.append(name)
        try:
            try:
                self.block(proc.args[2], fresh=False)
            except Flow as flow:
                if flow.kind != "return":
                    raise
        finally:
            self.stack.pop()
            self.frames.pop()

    def transaction(self, node: Node) -> None:
        body, error_name, recovery = node.args
        inventory_snapshot = copy.deepcopy(self.warehouses)
        hold_snapshot = copy.deepcopy(self.holds)
        event_length = len(self.events)
        bindings = [(scope, dict(scope)) for frame in self.frames for scope in frame]
        try:
            self.block(body)
        except Fault as error:
            if error.category != "DOMAIN":
                raise
            self.warehouses = inventory_snapshot
            self.holds = hold_snapshot
            del self.events[event_length:]
            for scope, saved in bindings:
                scope.clear()
                scope.update(saved)
            self.stats["rolled_back"] += 1
            if recovery is None:
                raise
            self.block(recovery, {error_name: error})
        except Flow:
            self.stats["committed"] += 1
            raise
        else:
            self.stats["committed"] += 1

    def statement(self, node: Node) -> None:
        try:
            self.execute(node)
        except Fault as error:
            self.annotate(error, node)
            raise

    def execute(self, node: Node) -> None:
        if self.stats["steps"] >= 20000:
            raise Fault("RUNTIME", "Statement limit exceeded")
        self.stats["steps"] += 1
        op, a = node.op, node.args
        if op == "let":
            self.scopes[-1][a[0]] = self.expression(a[2])
        elif op == "set":
            self.locate(a[0])[a[0]] = self.expression(a[1])
        elif op == "if":
            self.block(a[1] if self.expression(a[0]) else a[2])
        elif op == "while":
            while self.expression(a[0]):
                try:
                    self.block(a[1])
                except Flow as flow:
                    if flow.kind == "break":
                        break
                    if flow.kind != "continue":
                        raise
        elif op == "transaction":
            self.transaction(node)
        elif op in {"break", "continue", "return"}:
            raise Flow(op)
        elif op == "assert":
            if not self.expression(a[0]):
                self.domain("ASSERT", "Assertion failed")
        elif op == "emit":
            name = self.expression(a[0])
            data = {key.text: self.expression(expr) for key, expr in a[1]}
            self.events.append({"name": name, "data": data})
        elif op == "call":
            values = [(name, self.expression(expr)) for name, expr in a[1]]
            self.call(a[0], values)
        else:
            self.operation(op, [self.expression(expr) for _, expr in a])

    def run(self) -> dict[str, Any]:
        self.call("main", [])
        events = [dict(event, id=index) for index, event in enumerate(self.events, 1)]
        return {"warehouses": self.warehouses, "holds": self.holds,
                "events": events, "stats": self.stats}
