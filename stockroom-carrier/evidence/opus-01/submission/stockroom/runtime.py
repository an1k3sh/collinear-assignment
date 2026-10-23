"""Tree-walking evaluator with journaled transactions and deterministic replay."""
import hashlib
import json

from .errors import DomainError, PauseExit, StockroomError

STEP_LIMIT = 20000
CALL_LIMIT = 32
TXN_LIMIT = 32

BREAK, CONTINUE, RETURN = 1, 2, 3
_MISSING = object()


class CheckpointMismatch(Exception):
    """Replay diverged from the recorded continuation."""


class ErrorValue:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


class Frame:
    __slots__ = ("name", "scopes")

    def __init__(self, name, scope):
        self.name = name
        self.scopes = [scope]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


class Interpreter:
    """Executes a checked compilation unit.

    Durable mode replays the program from main using the checkpoint's log of
    carrier observations until `target` pauses have been passed, then continues
    live. Local state is therefore reconstructed deterministically; the carrier
    is never contacted during the replayed prefix.
    """

    def __init__(self, procs, warehouses, carrier=None, durable=False,
                 target=0, observations=None, expected=None):
        self.procs = procs
        self.warehouses = warehouses
        self.holds = {}
        self.held_totals = {}
        self.events = []
        self.deliveries = {}
        self.steps = 0
        self.committed = 0
        self.rolled_back = 0
        self.journal = []
        self.txn_depth = 0
        self.frames = []
        self.carrier = carrier          # CarrierLink or None
        self.durable = durable
        self.target = target
        self.pause_count = 0
        self.expected = expected        # verification data for the target pause
        self.observations = list(observations or [])
        self.replay_index = 0
        self.replaying = target > 0
        self.dispatch = {
            "let": self.s_let, "set": self.s_set, "if": self.s_if,
            "while": self.s_while, "transaction": self.s_transaction,
            "break": self.s_break, "continue": self.s_continue,
            "return": self.s_return, "assert": self.s_assert, "emit": self.s_emit,
            "receive": self.s_receive, "move": self.s_move, "reserve": self.s_reserve,
            "release": self.s_release, "ship": self.s_ship, "call": self.s_call,
            "pause": self.s_pause, "record_delivery": self.s_record_delivery,
        }

    # ------------------------------------------------------------ helpers
    def stack(self):
        return [frame.name for frame in self.frames]

    def domain(self, code, message, loc):
        return DomainError(code, message, loc, self.stack())

    def fatal(self, category, message, loc):
        return StockroomError(category, message, loc, self.stack())

    def log(self, entry):
        if self.txn_depth:
            self.journal.append(entry)

    def lookup_scope(self, name):
        for scope in reversed(self.frames[-1].scopes):
            if name in scope:
                return scope
        raise AssertionError("unresolved variable " + name)  # checker guarantees

    # ------------------------------------------------------------ run
    def run(self):
        main = self.procs["main"]
        self.frames.append(Frame("main", {}))
        try:
            self.exec_stmts(main.body.stmts)
        finally:
            self.frames.pop()
        if self.replaying:
            raise CheckpointMismatch("execution finished before the saved pause")

    def result(self):
        return {
            "warehouses": self.warehouses,
            "holds": self.holds,
            "events": [{"id": i, "name": name, "data": data}
                       for i, (name, data) in enumerate(self.events, 1)],
            "stats": {"steps": self.steps, "committed": self.committed,
                      "rolled_back": self.rolled_back},
            "deliveries": self.deliveries,
        }

    def digest(self, label):
        body = self.result()
        body["pause"] = [self.pause_count, label, self.txn_depth,
                         len(self.frames), self.replay_index]
        return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------ statements
    def exec_stmts(self, stmts):
        for stmt in stmts:
            if self.steps >= STEP_LIMIT:
                raise self.fatal("RUNTIME", "Step limit exceeded", stmt.loc)
            self.steps += 1
            signal = self.dispatch[stmt.kind](stmt)
            if signal:
                return signal
        return None

    def exec_block(self, block, scope=None):
        scopes = self.frames[-1].scopes
        scopes.append({} if scope is None else scope)
        try:
            return self.exec_stmts(block.stmts)
        finally:
            scopes.pop()

    def s_let(self, s):
        value = self.eval(s.a[0])
        self.frames[-1].scopes[-1][s.extra[0]] = value

    def s_set(self, s):
        value = self.eval(s.a[0])
        name = s.extra[0]
        scope = self.lookup_scope(name)
        if self.txn_depth:
            self.journal.append(("var", scope, name, scope[name]))
        scope[name] = value

    def s_if(self, s):
        then, other = s.extra
        if self.eval(s.a[0]):
            return self.exec_block(then)
        if other is not None:
            return self.exec_block(other)
        return None

    def s_while(self, s):
        cond = s.a[0]
        while self.eval(cond):
            signal = self.exec_block(s.extra)
            if signal == BREAK:
                break
            if signal == RETURN:
                return RETURN
        return None

    def s_break(self, s):
        return BREAK

    def s_continue(self, s):
        return CONTINUE

    def s_return(self, s):
        return RETURN

    def s_transaction(self, s):
        body, rec_name, rec_block, _ = s.extra
        if self.txn_depth >= TXN_LIMIT:
            raise self.fatal("RUNTIME", "Transaction nesting limit exceeded", s.loc)
        mark = len(self.journal)
        scope_depth = len(self.frames[-1].scopes)
        frame_depth = len(self.frames)
        self.txn_depth += 1
        try:
            signal = self.exec_block(body)
        except DomainError as error:
            self.txn_depth -= 1
            self.rollback(mark)
            del self.frames[frame_depth:]
            del self.frames[-1].scopes[scope_depth:]
            self.rolled_back += 1
            if rec_block is None:
                raise
            return self.exec_block(rec_block, {rec_name: ErrorValue(error.code)})
        except BaseException:
            self.txn_depth -= 1
            raise
        self.txn_depth -= 1
        self.committed += 1
        if not self.txn_depth:
            self.journal.clear()
        return signal

    def rollback(self, mark):
        journal = self.journal
        while len(journal) > mark:
            entry = journal.pop()
            kind = entry[0]
            if kind == "var":
                entry[1][entry[2]] = entry[3]
            elif kind == "stock":
                _, warehouse, sku, old = entry
                if old is _MISSING:
                    del self.warehouses[warehouse][sku]
                else:
                    self.warehouses[warehouse][sku] = old
            elif kind == "hold_new":
                record = self.holds.pop(entry[1])
                self.adjust_held(record, -record["remaining"])
            elif kind == "hold_rem":
                record = self.holds[entry[1]]
                self.adjust_held(record, entry[2] - record["remaining"])
                record["remaining"] = entry[2]
            elif kind == "event":
                self.events.pop()
            elif kind == "delivery":
                del self.deliveries[entry[1]]

    def s_assert(self, s):
        if not self.eval(s.a[0]):
            raise self.domain("ASSERT", "Assertion failed", s.loc)

    def s_emit(self, s):
        name = self.eval(s.a[0])
        data = {}
        for key, expr, _ in s.extra:
            data[key] = self.eval(expr)
        self.events.append((name, data))
        self.log(("event",))

    def s_call(self, s):
        proc = self.procs[s.extra]
        params = proc.params
        scope = {}
        index = 0
        for arg in s.a:
            value = self.eval(arg.expr)
            if arg.name is None:
                scope[params[index].name] = value
                index += 1
            else:
                scope[arg.name] = value
        bound = {}
        for param in params:
            bound[param.name] = scope[param.name] if param.name in scope else param.default
        if len(self.frames) >= CALL_LIMIT:
            raise self.fatal("RUNTIME", "Call depth limit exceeded", s.loc)
        self.frames.append(Frame(proc.name, bound))
        try:
            self.exec_stmts(proc.body.stmts)
        finally:
            self.frames.pop()
        return None

    def s_pause(self, s):
        label = self.eval(s.a[0])
        if not self.durable:
            return None
        self.pause_count += 1
        if self.replaying:
            if self.pause_count < self.target:
                return None
            expected = self.expected
            if (label != expected["label"] or self.steps != expected["steps"]
                    or self.digest(label) != expected["digest"]
                    or self.replay_index != len(self.observations)):
                raise CheckpointMismatch("replayed state does not match the checkpoint")
            self.replaying = False
            return None
        self.pause_digest = self.digest(label)
        raise PauseExit(label)

    # ------------------------------------------------------------ inventory ops
    def qty(self, value, loc):
        if value <= 0:
            raise self.domain("QUANTITY", "Quantity must be positive", loc)

    def name(self, value, what, loc):
        if value == "":
            raise self.domain("NAME", "%s must be nonempty" % what, loc)

    def warehouse(self, name, loc):
        stock = self.warehouses.get(name)
        if stock is None:
            raise self.domain("WAREHOUSE", "Unknown warehouse %r" % name, loc)
        return stock

    def hold(self, hold_id, loc):
        record = self.holds.get(hold_id)
        if record is None:
            raise self.domain("HOLD", "Unknown hold %r" % hold_id, loc)
        return record

    def adjust_held(self, record, delta):
        key = (record["warehouse"], record["sku"])
        self.held_totals[key] = self.held_totals.get(key, 0) + delta

    def available_of(self, warehouse, sku):
        return (self.warehouses[warehouse].get(sku, 0)
                - self.held_totals.get((warehouse, sku), 0))

    def set_stock(self, warehouse, sku, value):
        stock = self.warehouses[warehouse]
        if self.txn_depth:
            self.journal.append(("stock", warehouse, sku, stock.get(sku, _MISSING)))
        stock[sku] = value

    def s_receive(self, s):
        warehouse, sku, qty = [self.eval(e) for e in s.a]
        self.qty(qty, s.loc)
        self.name(sku, "SKU", s.loc)
        stock = self.warehouse(warehouse, s.loc)
        self.set_stock(warehouse, sku, stock.get(sku, 0) + qty)

    def s_move(self, s):
        source, dest, sku, qty = [self.eval(e) for e in s.a]
        self.qty(qty, s.loc)
        self.name(sku, "SKU", s.loc)
        src = self.warehouse(source, s.loc)
        dst = self.warehouse(dest, s.loc)
        if source == dest:
            raise self.domain("SAME_WAREHOUSE", "Source and destination are equal", s.loc)
        if self.available_of(source, sku) < qty:
            raise self.domain("SHORTAGE", "Insufficient available stock", s.loc)
        self.set_stock(source, sku, src.get(sku, 0) - qty)
        self.set_stock(dest, sku, dst.get(sku, 0) + qty)

    def s_reserve(self, s):
        hold_id, warehouse, sku, qty = [self.eval(e) for e in s.a]
        self.qty(qty, s.loc)
        self.name(hold_id, "Hold ID", s.loc)
        self.name(sku, "SKU", s.loc)
        self.warehouse(warehouse, s.loc)
        if hold_id in self.holds:
            raise self.domain("DUPLICATE_HOLD", "Hold %r already exists" % hold_id, s.loc)
        if self.available_of(warehouse, sku) < qty:
            raise self.domain("SHORTAGE", "Insufficient available stock", s.loc)
        self.holds[hold_id] = {"warehouse": warehouse, "sku": sku, "remaining": qty}
        self.adjust_held(self.holds[hold_id], qty)
        self.log(("hold_new", hold_id))

    def reduce_hold(self, s, ship):
        hold_id, qty = [self.eval(e) for e in s.a]
        self.qty(qty, s.loc)
        self.name(hold_id, "Hold ID", s.loc)
        record = self.hold(hold_id, s.loc)
        if qty > record["remaining"]:
            raise self.domain("SHORTAGE", "Quantity exceeds hold remaining", s.loc)
        if self.txn_depth:
            self.journal.append(("hold_rem", hold_id, record["remaining"]))
        record["remaining"] -= qty
        self.adjust_held(record, -qty)
        if ship:
            stock = self.warehouses[record["warehouse"]]
            self.set_stock(record["warehouse"], record["sku"],
                           stock.get(record["sku"], 0) - qty)

    def s_release(self, s):
        self.reduce_hold(s, False)

    def s_ship(self, s):
        self.reduce_hold(s, True)

    def s_record_delivery(self, s):
        key, receipt = [self.eval(e) for e in s.a]
        self.name(key, "Delivery key", s.loc)
        self.name(receipt, "Receipt", s.loc)
        if key in self.deliveries:
            raise self.domain("ALREADY_POSTED", "Delivery %r already recorded" % key, s.loc)
        record = self.carrier_lookup(key, s.loc)
        if record is None or record["receipt"] != receipt:
            raise self.domain("CARRIER_CONFLICT", "No carrier acceptance with that receipt", s.loc)
        for suffix, sku_field in ((".a", "sku_a"), (".b", "sku_b")):
            hold = self.holds.get(key + suffix)
            if (hold is None or hold["remaining"] != 0
                    or hold["warehouse"] != record["warehouse"]
                    or hold["sku"] != record[sku_field]):
                raise self.domain("HOLD", "Hold %r does not match the carrier record"
                                  % (key + suffix), s.loc)
        self.deliveries[key] = {field: record[field] for field in
                                ("receipt", "warehouse", "sku_a", "qty_a", "sku_b", "qty_b")}
        self.log(("delivery", key))

    # ------------------------------------------------------------ carrier
    def observe(self, request, loc, perform):
        """Return a recorded observation during replay, else perform and record."""
        if self.replaying:
            if self.replay_index >= len(self.observations):
                raise CheckpointMismatch("checkpoint carrier log is exhausted")
            entry = self.observations[self.replay_index]
            if entry.get("request") != request:
                raise CheckpointMismatch("carrier request diverged during replay")
            self.replay_index += 1
        else:
            if self.carrier is None:
                raise self.fatal("IO", "Carrier access requires --carrier", loc)
            entry = perform()
            entry["request"] = request
            self.observations.append(entry)
            self.replay_index = len(self.observations)
        if "failure" in entry:
            code, message = entry["failure"]
            raise self.domain(code, message, loc)
        return entry["response"]

    def carrier_lookup(self, key, loc):
        return self.observe(["lookup", key], loc,
                            lambda: {"response": self.carrier.lookup(key, self, loc)})

    def carrier_send(self, args, loc):
        return self.observe(["submit"] + list(args), loc,
                            lambda: self.carrier.submit(args, self, loc))

    # ------------------------------------------------------------ expressions
    def eval(self, e):
        kind = e.kind
        if kind == "lit":
            return e.value
        if kind == "var":
            name = e.value
            for scope in reversed(self.frames[-1].scopes):
                if name in scope:
                    return scope[name]
            raise AssertionError(name)
        if kind == "binary":
            op = e.value
            if op == "&&":
                return self.eval(e.args[0]) and self.eval(e.args[1])
            if op == "||":
                return self.eval(e.args[0]) or self.eval(e.args[1])
            left = self.eval(e.args[0])
            right = self.eval(e.args[1])
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == ">=":
                return left >= right
            if right == 0:
                raise self.fatal("RUNTIME", "Division by zero", e.loc)
            quotient = abs(left) // abs(right)
            if (left < 0) != (right < 0):
                quotient = -quotient
            if op == "/":
                return quotient
            return left - quotient * right
        if kind == "unary":
            value = self.eval(e.args[0])
            return (not value) if e.value == "!" else -value
        if kind == "call":
            return self.builtin(e)
        raise AssertionError(kind)

    def builtin(self, e):
        name = e.value
        if name == "code":
            return self.eval(e.args[0].expr).code
        args = [self.eval(arg.expr) for arg in e.args]
        loc = e.loc
        if name in ("onhand", "available"):
            warehouse, sku = args
            stock = self.warehouse(warehouse, loc)
            self.name(sku, "SKU", loc)
            if name == "onhand":
                return stock.get(sku, 0)
            return self.available_of(warehouse, sku)
        if name == "remaining":
            self.name(args[0], "Hold ID", loc)
            return self.hold(args[0], loc)["remaining"]
        if name == "len":
            return len(args[0])
        if name == "delivered":
            self.name(args[0], "Delivery key", loc)
            return args[0] in self.deliveries
        if name == "carrier_send":
            key, warehouse, sku_a, qty_a, sku_b, qty_b = args
            for value, what in ((key, "Key"), (warehouse, "Warehouse"),
                                (sku_a, "SKU"), (sku_b, "SKU")):
                self.name(value, what, loc)
            self.qty(qty_a, loc)
            self.qty(qty_b, loc)
            self.warehouse(warehouse, loc)
            return self.carrier_send(args, loc)
        key = args[0]
        self.name(key, "Carrier key", loc)
        record = self.carrier_lookup(key, loc)
        if name == "carrier_receipt":
            return "" if record is None else record["receipt"]
        if name == "carrier_warehouse":
            return "" if record is None else record["warehouse"]
        if name == "carrier_matches":
            return record is not None and [
                record["warehouse"], record["sku_a"], record["qty_a"],
                record["sku_b"], record["qty_b"]] == args[1:]
        raise AssertionError(name)
