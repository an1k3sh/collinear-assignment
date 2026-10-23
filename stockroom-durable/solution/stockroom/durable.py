from __future__ import annotations

import copy
from typing import Any

from .language import Fault, Node, Token, bind_arguments
from .runtime import Engine


class Machine(Engine):
    """A JSON-serializable control stack; no live Python frame is durable state."""

    STATE_KEYS = {"warehouses", "holds", "events", "stats", "frames", "stack",
                  "scope_store", "next_scope", "tasks", "pause_count"}

    def __init__(self, procedures: dict[str, Node], warehouses: dict[str, dict[str, int]]):
        super().__init__(procedures, warehouses)
        self.nodes: list[Node] = []
        self.node_ids: dict[int, int] = {}
        self.scope_store: dict[str, dict[str, Any]] = {}
        self.next_scope = 0
        self.tasks: list[dict[str, Any]] = []
        self.pause_count = 0
        self.durable_frames: list[list[str]] = []
        for proc in procedures.values():
            self.register(proc.args[2])
        self.enter_call("main", [])

    def register(self, body: list[Node]) -> None:
        for node in body:
            self.node_ids[id(node)] = len(self.nodes)
            self.nodes.append(node)
            if node.op in {"if", "while"}:
                self.register(node.args[1])
                self.register(node.args[2])
            elif node.op == "transaction":
                self.register(node.args[0])
                if node.args[2] is not None:
                    self.register(node.args[2])

    @property
    def scopes(self) -> list[dict[str, Any]]:
        return [self.scope_store[key] for key in self.durable_frames[-1]]

    def new_scope(self, values: dict[str, Any]) -> str:
        key = str(self.next_scope)
        self.next_scope += 1
        self.scope_store[key] = values
        return key

    def schedule(self, body: list[Node], values: dict[str, Any] | None = None,
                 fresh: bool = True) -> None:
        if fresh:
            self.durable_frames[-1].append(self.new_scope({} if values is None else values))
            self.tasks.append({"kind": "scope_exit"})
        self.tasks.extend({"kind": "statement", "node": self.node_ids[id(node)]}
                          for node in reversed(body))

    def enter_call(self, name: str, arguments: list[tuple[str | None, Any]]) -> None:
        proc = self.procedures[name]
        bound = bind_arguments(proc.args[1], arguments, proc.token)
        values = {key: value.args[0] if isinstance(value, Node) else value
                  for key, value in bound.items()}
        self.durable_frames.append([self.new_scope(values)])
        self.stack.append(name)
        self.tasks.append({"kind": "call_exit"})
        self.schedule(proc.args[2], fresh=False)

    def clean_scope(self) -> None:
        key = self.durable_frames[-1].pop()
        del self.scope_store[key]

    def clean_call(self) -> None:
        for key in self.durable_frames.pop():
            del self.scope_store[key]
        self.stack.pop()

    def snapshot(self) -> dict[str, Any]:
        return {
            "warehouses": copy.deepcopy(self.warehouses),
            "holds": copy.deepcopy(self.holds),
            "event_length": len(self.events),
            "bindings": {key: dict(scope) for key, scope in self.scope_store.items()},
        }

    def rollback(self, snapshot: dict[str, Any]) -> None:
        self.warehouses = snapshot["warehouses"]
        self.holds = snapshot["holds"]
        del self.events[snapshot["event_length"]:]
        for key, values in snapshot["bindings"].items():
            self.scope_store[key].clear()
            self.scope_store[key].update(values)
        self.stats["rolled_back"] += 1

    def unwind(self, flow: str | None = None, error: Fault | None = None) -> None:
        while self.tasks:
            task = self.tasks.pop()
            kind = task["kind"]
            if kind == "scope_exit":
                self.clean_scope()
            elif kind == "call_exit":
                self.clean_call()
                if flow == "return":
                    return
            elif kind == "loop_boundary" and flow in {"break", "continue"}:
                if flow == "continue":
                    self.tasks.append({"kind": "loop", "node": task["node"]})
                return
            elif kind == "transaction_exit":
                if error is None:
                    self.stats["committed"] += 1
                else:
                    self.rollback(task["snapshot"])
                    node = self.nodes[task["node"]]
                    if node.args[2] is not None:
                        self.schedule(node.args[2], {node.args[1]: error})
                        return
        if error is not None:
            raise error
        raise AssertionError(f"Control target missing: {flow}")

    def step(self, node: Node, stop_on_pause: bool) -> str | None:
        if self.stats["steps"] >= 20000:
            raise Fault("RUNTIME", "Statement limit exceeded")
        self.stats["steps"] += 1
        op, a = node.op, node.args
        if op == "pause":
            label = self.expression(a[0])
            self.pause_count += 1
            return label if stop_on_pause else None
        if op == "let":
            self.scopes[-1][a[0]] = self.expression(a[2])
        elif op == "set":
            self.locate(a[0])[a[0]] = self.expression(a[1])
        elif op == "if":
            self.schedule(a[1] if self.expression(a[0]) else a[2])
        elif op == "while":
            self.tasks.append({"kind": "loop", "node": self.node_ids[id(node)]})
        elif op == "transaction":
            self.tasks.append({"kind": "transaction_exit", "node": self.node_ids[id(node)],
                               "snapshot": self.snapshot()})
            self.schedule(a[0])
        elif op in {"break", "continue", "return"}:
            self.unwind(flow=op)
        elif op == "assert":
            if not self.expression(a[0]):
                self.domain("ASSERT", "Assertion failed")
        elif op == "emit":
            name = self.expression(a[0])
            data = {key.text: self.expression(expr) for key, expr in a[1]}
            self.events.append({"name": name, "data": data})
        elif op == "call":
            values = [(name, self.expression(expr)) for name, expr in a[1]]
            self.enter_call(a[0], values)
        else:
            self.operation(op, [self.expression(expr) for _, expr in a])
        return None

    def run_until_pause(self, stop_on_pause: bool) -> tuple[dict[str, Any] | None, str | None]:
        while self.tasks:
            task = self.tasks.pop()
            kind = task["kind"]
            node = self.nodes[task["node"]] if "node" in task else None
            try:
                if kind == "statement":
                    label = self.step(node, stop_on_pause)
                    if label is not None:
                        return None, label
                elif kind == "scope_exit":
                    self.clean_scope()
                elif kind == "call_exit":
                    self.clean_call()
                elif kind == "transaction_exit":
                    self.stats["committed"] += 1
                elif kind == "loop":
                    if self.expression(node.args[0]):
                        self.tasks.append({"kind": "loop_boundary", "node": task["node"]})
                        self.schedule(node.args[1])
                elif kind == "loop_boundary":
                    self.tasks.append({"kind": "loop", "node": task["node"]})
                else:
                    raise AssertionError(kind)
            except Fault as error:
                if node is not None:
                    self.annotate(error, node)
                if error.category != "DOMAIN":
                    raise
                self.unwind(error=error)
        events = [dict(event, id=index) for index, event in enumerate(self.events, 1)]
        return {"warehouses": self.warehouses, "holds": self.holds,
                "events": events, "stats": self.stats}, None

    @staticmethod
    def encode(value: Any) -> Any:
        if isinstance(value, Fault):
            token = value.token
            return ["error", value.diagnostic(), None if token is None else
                    [token.text, token.file, token.line, token.column]]
        if isinstance(value, dict):
            return ["mapping", [[key, Machine.encode(item)] for key, item in value.items()]]
        if isinstance(value, list):
            return ["sequence", [Machine.encode(item) for item in value]]
        return ["scalar", value]

    @staticmethod
    def decode(value: Any) -> Any:
        if not isinstance(value, list) or not value:
            raise ValueError("Missing typed value")
        if value[0] == "scalar" and len(value) == 2 and type(value[1]) in {str, int, bool, type(None)}:
            return value[1]
        if value[0] == "mapping" and len(value) == 2:
            return {key: Machine.decode(item) for key, item in value[1]}
        if value[0] == "sequence" and len(value) == 2:
            return [Machine.decode(item) for item in value[1]]
        if value[0] == "error" and len(value) == 3:
            diagnostic = value[1]
            token = Token(*value[2]) if value[2] else None
            error = Fault(diagnostic["error"], diagnostic["message"], token, diagnostic.get("code"))
            error.stack = diagnostic.get("stack")
            return error
        raise ValueError("Invalid typed value")

    def export(self) -> dict[str, Any]:
        state = {key: getattr(self, key) for key in self.STATE_KEYS - {"frames"}}
        state["frames"] = self.durable_frames
        return {"encoding": "typed-values-v1", "machine": self.encode(state)}

    def restore(self, raw: dict[str, Any]) -> None:
        try:
            if set(raw) != {"encoding", "machine"} or raw["encoding"] != "typed-values-v1":
                raise ValueError("Unsupported execution state")
            state = self.decode(raw["machine"])
            if not isinstance(state, dict) or set(state) != self.STATE_KEYS:
                raise ValueError("Invalid machine fields")
            for key in ("warehouses", "holds", "stats", "scope_store"):
                if not isinstance(state[key], dict):
                    raise ValueError(f"Invalid state {key}")
            for key in ("events", "frames", "stack", "tasks"):
                if not isinstance(state[key], list):
                    raise ValueError(f"Invalid state {key}")
            if (type(state["next_scope"]) is not int or state["next_scope"] < 0
                    or type(state["pause_count"]) is not int or state["pause_count"] < 1):
                raise ValueError("Invalid continuation counters")
            if len(state["frames"]) != len(state["stack"]) or not state["tasks"]:
                raise ValueError("Invalid continuation frames")
            for frame in state["frames"]:
                if not isinstance(frame, list) or not frame:
                    raise ValueError("Invalid lexical frame")
                for key in frame:
                    if key not in state["scope_store"]:
                        raise ValueError("Missing lexical scope")
            kinds = {"statement", "scope_exit", "call_exit", "transaction_exit",
                     "loop", "loop_boundary"}
            for task in state["tasks"]:
                if not isinstance(task, dict) or task.get("kind") not in kinds:
                    raise ValueError("Invalid continuation task")
                if "node" in task and (type(task["node"]) is not int
                                       or not 0 <= task["node"] < len(self.nodes)):
                    raise ValueError("Invalid instruction reference")
            for key in ("steps", "committed", "rolled_back"):
                if type(state["stats"].get(key)) is not int or state["stats"][key] < 0:
                    raise ValueError("Invalid execution counters")
            self.durable_frames = state.pop("frames")
            for key, value in state.items():
                setattr(self, key, value)
        except (KeyError, TypeError, ValueError) as error:
            raise Fault("CHECKPOINT", f"Incompatible execution state: {error}") from error
