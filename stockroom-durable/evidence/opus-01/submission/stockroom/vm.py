"""Bytecode interpreter with an explicit, serializable execution state.

Frame block stacks hold three kinds of entries (all plain lists):

* ``["s", {name: value}]``  lexical scope
* ``["l", pc]``             active loop (pc of its LOOP instruction)
* ``["t", pc, jmark, emark]`` active transaction: journal and event marks

Transactions are implemented with an undo journal rather than full copies.
Journal entries are recorded only while a transaction is active:

* ``["w", warehouse, sku, old_onhand_or_None]``
* ``["h", hold_id, old_record_or_None]``
* ``["v", frame_index, block_index, name, old_value]``
"""
from .compiler import (LET, SET, IF, JUMP, ENTER, EXIT, LOOP, WTEST, TX, COMMIT,
                       BRK, CONT, RET, RET0, ASSERT, EMIT, OP, CALL, PAUSE)
from .errors import DomainFailure, ErrorValue, StockError

STEP_LIMIT = 20000
ENGINE = "stockroom-vm"
ENGINE_VERSION = 1


class Suspend(Exception):
    def __init__(self, label):
        super().__init__(label)
        self.label = label


class Frame:
    __slots__ = ("proc", "code", "pc", "blocks")

    def __init__(self, proc, pc, blocks):
        self.proc = proc
        self.code = proc.code
        self.pc = pc
        self.blocks = blocks


class VM:
    def __init__(self, unit, warehouses, durable=False):
        self.unit = unit
        self.durable = durable
        self.wh = warehouses
        self.holds = {}
        self.held = {}
        self.journal = []
        self.events = []
        self.steps = 0
        self.committed = 0
        self.rolled_back = 0
        self.pause_count = 0
        self.tx_depth = 0
        self.label = None
        self.frames = [Frame(unit.procs["main"], 0, [["s", {}]])]

    # -- failures ----------------------------------------------------------
    def stack(self):
        return [frame.proc.name for frame in self.frames]

    def fatal(self, message, pos):
        raise StockError("RUNTIME", message, pos, stack=self.stack())

    def domain(self, code, pos):
        raise DomainFailure(ErrorValue(code, pos, self.stack()))

    # -- inventory primitives ------------------------------------------------
    def _warehouse(self, name, pos):
        stock = self.wh.get(name)
        if stock is None:
            self.domain("WAREHOUSE", pos)
        return stock

    def onhand(self, warehouse, sku, pos):
        return self._warehouse(warehouse, pos).get(sku, 0)

    def available(self, warehouse, sku, pos):
        stock = self._warehouse(warehouse, pos)
        return stock.get(sku, 0) - self.held.get((warehouse, sku), 0)

    def remaining(self, hold_id, pos):
        record = self.holds.get(hold_id)
        if record is None:
            self.domain("HOLD", pos)
        return record[2]

    def set_onhand(self, warehouse, sku, value):
        stock = self.wh[warehouse]
        if self.tx_depth:
            self.journal.append(["w", warehouse, sku, stock.get(sku)])
        stock[sku] = value

    def _put_hold(self, hold_id, record):
        old = self.holds.get(hold_id)
        if old is not None:
            key = (old[0], old[1])
            self.held[key] -= old[2]
        if record is None:
            del self.holds[hold_id]
        else:
            self.holds[hold_id] = record
            key = (record[0], record[1])
            self.held[key] = self.held.get(key, 0) + record[2]
        return old

    def set_hold(self, hold_id, record):
        old = self._put_hold(hold_id, record)
        if self.tx_depth:
            self.journal.append(["h", hold_id, old])

    def operation(self, kind, args, pos):
        if kind == "receive":
            warehouse, sku, qty = args
            if qty <= 0:
                self.domain("QUANTITY", pos)
            if sku == "":
                self.domain("NAME", pos)
            stock = self._warehouse(warehouse, pos)
            self.set_onhand(warehouse, sku, stock.get(sku, 0) + qty)
        elif kind == "move":
            source, target, sku, qty = args
            if qty <= 0:
                self.domain("QUANTITY", pos)
            if sku == "":
                self.domain("NAME", pos)
            src = self._warehouse(source, pos)
            dst = self._warehouse(target, pos)
            if source == target:
                self.domain("SAME_WAREHOUSE", pos)
            if self.available(source, sku, pos) < qty:
                self.domain("SHORTAGE", pos)
            self.set_onhand(source, sku, src.get(sku, 0) - qty)
            self.set_onhand(target, sku, dst.get(sku, 0) + qty)
        elif kind == "reserve":
            hold_id, warehouse, sku, qty = args
            if qty <= 0:
                self.domain("QUANTITY", pos)
            if hold_id == "" or sku == "":
                self.domain("NAME", pos)
            if hold_id in self.holds:
                self.domain("DUPLICATE_HOLD", pos)
            self._warehouse(warehouse, pos)
            if self.available(warehouse, sku, pos) < qty:
                self.domain("SHORTAGE", pos)
            self.set_hold(hold_id, (warehouse, sku, qty))
        else:  # release / ship
            hold_id, qty = args
            if qty <= 0:
                self.domain("QUANTITY", pos)
            if hold_id == "":
                self.domain("NAME", pos)
            record = self.holds.get(hold_id)
            if record is None:
                self.domain("HOLD", pos)
            warehouse, sku, left = record
            if qty > left:
                self.domain("SHORTAGE", pos)
            self.set_hold(hold_id, (warehouse, sku, left - qty))
            if kind == "ship":
                self.set_onhand(warehouse, sku, self.wh[warehouse][sku] - qty)

    # -- transactions --------------------------------------------------------
    def undo(self, mark):
        journal = self.journal
        frames = self.frames
        for i in range(len(journal) - 1, mark - 1, -1):
            entry = journal[i]
            kind = entry[0]
            if kind == "w":
                stock = self.wh[entry[1]]
                if entry[3] is None:
                    stock.pop(entry[2], None)
                else:
                    stock[entry[2]] = entry[3]
            elif kind == "h":
                self._put_hold(entry[1], entry[2])
            else:
                # Entries for scopes created after the restored transaction
                # refer to positions that no longer exist; they are skipped.
                fi, bi, name, old = entry[1], entry[2], entry[3], entry[4]
                if fi < len(frames):
                    blocks = frames[fi].blocks
                    if bi < len(blocks) and blocks[bi][0] == "s" \
                            and name in blocks[bi][1]:
                        blocks[bi][1][name] = old
        del journal[mark:]

    def leave(self, blocks, stop_at_loop):
        """Successful control transfer: drop blocks, committing transactions."""
        while blocks:
            block = blocks[-1]
            if stop_at_loop and block[0] == "l":
                return block
            blocks.pop()
            if block[0] == "t":
                self.commit()
        return None

    def commit(self):
        self.committed += 1
        self.tx_depth -= 1
        if not self.tx_depth:
            self.journal.clear()

    def unwind(self, err):
        frames = self.frames
        while frames:
            frame = frames[-1]
            blocks = frame.blocks
            while blocks:
                block = blocks.pop()
                if block[0] == "t":
                    self.rolled_back += 1
                    self.tx_depth -= 1
                    ins = frame.code[block[1]]
                    if ins.a is not None:
                        self.undo(block[2])
                        del self.events[block[3]:]
                        if not self.tx_depth:
                            self.journal.clear()
                        blocks.append(["s", {ins.c: err}])
                        frame.pc = ins.a
                        return
            frames.pop()
        raise StockError("DOMAIN", "unhandled %s failure" % err.code, err.pos,
                         stack=list(err.stack), code=err.code)

    # -- execution -----------------------------------------------------------
    def run(self):
        frames = self.frames
        while frames:
            frame = frames[-1]
            ins = frame.code[frame.pc]
            frame.pc += 1
            if ins.step:
                if self.steps >= STEP_LIMIT:
                    self.fatal("step limit of %d statements exceeded" % STEP_LIMIT,
                               ins.pos)
                self.steps += 1
            try:
                self.execute(frame, ins)
            except DomainFailure as failure:
                self.unwind(failure.err)

    def execute(self, frame, ins):
        op = ins.op
        if op == LET:
            value = ins.b(self, frame)
            frame.blocks[-1][1][ins.a] = value
        elif op == SET:
            value = ins.b(self, frame)
            name = ins.a
            blocks = frame.blocks
            i = len(blocks) - 1
            while True:
                block = blocks[i]
                if block[0] == "s" and name in block[1]:
                    break
                i -= 1
            if self.tx_depth:
                self.journal.append(["v", len(self.frames) - 1, i, name,
                                     block[1][name]])
            block[1][name] = value
        elif op == IF:
            if not ins.a(self, frame):
                frame.pc = ins.b
        elif op == JUMP:
            frame.pc = ins.a
        elif op == ENTER:
            frame.blocks.append(["s", {}])
        elif op == EXIT:
            frame.blocks.pop()
        elif op == LOOP:
            frame.blocks.append(["l", frame.pc - 1])
        elif op == WTEST:
            if not ins.a(self, frame):
                frame.blocks.pop()
                frame.pc = ins.b
        elif op == TX:
            frame.blocks.append(["t", frame.pc - 1, len(self.journal),
                                 len(self.events)])
            self.tx_depth += 1
        elif op == COMMIT:
            frame.blocks.pop()
            self.commit()
        elif op == BRK:
            loop = self.leave(frame.blocks, True)
            frame.blocks.pop()
            frame.pc = frame.code[loop[1]].a
        elif op == CONT:
            loop = self.leave(frame.blocks, True)
            frame.pc = frame.code[loop[1]].b
        elif op == RET or op == RET0:
            self.leave(frame.blocks, False)
            self.frames.pop()
        elif op == ASSERT:
            if not ins.a(self, frame):
                self.domain("ASSERT", ins.pos)
        elif op == EMIT:
            name = ins.a(self, frame)
            data = {}
            for key, fn in ins.b:
                data[key] = fn(self, frame)
            self.events.append([name, data])
        elif op == OP:
            args = [fn(self, frame) for fn in ins.b]
            self.operation(ins.a, args, ins.pos)
        elif op == CALL:
            values = [fn(self, frame) for fn in ins.b]
            scope = {}
            for pname, from_arg, ref in ins.c:
                scope[pname] = values[ref] if from_arg else ref
            self.frames.append(Frame(self.unit.procs[ins.a], 0, [["s", scope]]))
        elif op == PAUSE:
            label = ins.a(self, frame)
            self.pause_count += 1
            if self.durable:
                self.label = label
                raise Suspend(label)
        else:  # pragma: no cover
            raise AssertionError("bad opcode %r" % op)

    # -- results -------------------------------------------------------------
    def result(self):
        return {
            "warehouses": self.wh,
            "holds": {hid: {"warehouse": r[0], "sku": r[1], "remaining": r[2]}
                      for hid, r in self.holds.items()},
            "events": [{"id": i + 1, "name": name, "data": data}
                       for i, (name, data) in enumerate(self.events)],
            "stats": {"steps": self.steps, "committed": self.committed,
                      "rolled_back": self.rolled_back},
        }

    # -- durable state -------------------------------------------------------
    def dump_state(self):
        frames = []
        for frame in self.frames:
            blocks = []
            for block in frame.blocks:
                if block[0] == "s":
                    blocks.append({"kind": "scope", "vars": {
                        name: encode_value(value) for name, value in block[1].items()}})
                elif block[0] == "l":
                    blocks.append({"kind": "loop", "at": block[1]})
                else:
                    blocks.append({"kind": "transaction", "at": block[1],
                                   "journal": block[2], "events": block[3]})
            frames.append({"proc": frame.proc.name, "pc": frame.pc,
                           "blocks": blocks})
        journal = []
        for entry in self.journal:
            if entry[0] == "h":
                old = entry[2]
                journal.append(["h", entry[1], None if old is None else list(old)])
            elif entry[0] == "v":
                journal.append(entry[:4] + [encode_value(entry[4])])
            else:
                journal.append(list(entry))
        return {
            "engine": ENGINE,
            "engine_version": ENGINE_VERSION,
            "label": self.label,
            "pause_count": self.pause_count,
            "frames": frames,
            "warehouses": self.wh,
            "holds": {hid: {"warehouse": r[0], "sku": r[1], "remaining": r[2]}
                      for hid, r in self.holds.items()},
            "journal": journal,
            "events": [{"name": name, "data": data} for name, data in self.events],
            "stats": {"steps": self.steps, "committed": self.committed,
                      "rolled_back": self.rolled_back},
        }


def encode_value(value):
    if isinstance(value, ErrorValue):
        role, line, column = value.pos
        return {"code": value.code, "file": role, "line": line, "column": column,
                "stack": list(value.stack)}
    return value


class BadState(Exception):
    pass


def need(condition, message):
    if not condition:
        raise BadState(message)


def is_int(value):
    return type(value) is int


def is_name(value):
    return type(value) is str and value != ""


def exact_keys(obj, keys, what):
    need(type(obj) is dict and set(obj) == set(keys), "malformed %s" % what)


def decode_value(raw, vtype, unit):
    if vtype == "int":
        need(is_int(raw), "int binding expected")
        return raw
    if vtype == "bool":
        need(type(raw) is bool, "bool binding expected")
        return raw
    if vtype == "string":
        need(type(raw) is str, "string binding expected")
        return raw
    exact_keys(raw, ("code", "file", "line", "column", "stack"), "error value")
    need(type(raw["code"]) is str and raw["code"] != "", "bad error code")
    need(raw["file"] in ("program", "library"), "bad error file role")
    need(is_int(raw["line"]) and raw["line"] >= 1, "bad error line")
    need(is_int(raw["column"]) and raw["column"] >= 1, "bad error column")
    need(type(raw["stack"]) is list and raw["stack"]
         and all(name in unit.procs for name in raw["stack"])
         and raw["stack"][0] == "main", "bad error stack")
    return ErrorValue(raw["code"], (raw["file"], raw["line"], raw["column"]),
                      raw["stack"])


def decode_any(raw, unit):
    if type(raw) in (int, bool, str):
        return raw
    return decode_value(raw, "error", unit)


def load_state(unit, state, label, pause_count):
    """Rebuild a VM from checkpoint state, validating it against the program."""
    from .compiler import CALL as CALL_OP, PAUSE as PAUSE_OP
    exact_keys(state, ("engine", "engine_version", "label", "pause_count",
                       "frames", "warehouses", "holds", "journal", "events",
                       "stats"), "state")
    need(state["engine"] == ENGINE and is_int(state["engine_version"])
         and state["engine_version"] == ENGINE_VERSION, "unsupported engine state")
    need(state["label"] == label and type(state["label"]) is str,
         "label does not match state")
    need(is_int(state["pause_count"]) and state["pause_count"] == pause_count,
         "pause_count does not match state")

    # inventory
    warehouses = state["warehouses"]
    need(type(warehouses) is dict, "bad warehouses")
    for wname, stock in warehouses.items():
        need(is_name(wname) and type(stock) is dict, "bad warehouse")
        for sku, qty in stock.items():
            need(is_name(sku) and is_int(qty) and qty >= 0, "bad stock entry")
    vm = VM(unit, warehouses, durable=True)
    holds = state["holds"]
    need(type(holds) is dict, "bad holds")
    for hid, rec in holds.items():
        exact_keys(rec, ("warehouse", "sku", "remaining"), "hold")
        need(is_name(hid) and rec["warehouse"] in warehouses and is_name(rec["sku"])
             and is_int(rec["remaining"]) and rec["remaining"] >= 0, "bad hold")
        vm._put_hold(hid, (rec["warehouse"], rec["sku"], rec["remaining"]))
    for (wname, sku), total in vm.held.items():
        need(total <= warehouses[wname].get(sku, 0), "holds exceed on-hand stock")

    events = state["events"]
    need(type(events) is list, "bad events")
    for event in events:
        exact_keys(event, ("name", "data"), "event")
        need(type(event["name"]) is str and type(event["data"]) is dict, "bad event")
        for key, value in event["data"].items():
            need(type(key) is str and type(value) in (int, bool, str),
                 "bad event payload")
        vm.events.append([event["name"], event["data"]])

    stats = state["stats"]
    exact_keys(stats, ("steps", "committed", "rolled_back"), "stats")
    for key in ("steps", "committed", "rolled_back"):
        need(is_int(stats[key]) and stats[key] >= 0, "bad counter")
    need(pause_count <= stats["steps"] <= STEP_LIMIT, "bad step counter")
    vm.steps = stats["steps"]
    vm.committed = stats["committed"]
    vm.rolled_back = stats["rolled_back"]
    vm.pause_count = pause_count
    vm.label = label

    # control state
    raw_frames = state["frames"]
    need(type(raw_frames) is list and 1 <= len(raw_frames) <= 64, "bad frames")
    frames = []
    tx_marks = []
    for depth, raw in enumerate(raw_frames):
        exact_keys(raw, ("proc", "pc", "blocks"), "frame")
        proc = unit.procs.get(raw["proc"]) if type(raw["proc"]) is str else None
        need(proc is not None, "unknown procedure in state")
        need(depth > 0 or proc.name == "main", "first frame must be main")
        pc = raw["pc"]
        need(is_int(pc) and 1 <= pc < len(proc.code), "bad program counter")
        site = proc.code[pc - 1]
        if depth == len(raw_frames) - 1:
            need(site.op == PAUSE_OP, "top frame is not after a pause")
        else:
            need(site.op == CALL_OP and site.a == raw_frames[depth + 1].get("proc"),
                 "caller frame is not after a matching call")
        shape = site.shape
        blocks = raw["blocks"]
        need(type(blocks) is list and len(blocks) == len(shape),
             "block structure does not match program")
        decoded = []
        for raw_block, expected in zip(blocks, shape):
            need(type(raw_block) is dict, "bad block")
            kind = raw_block.get("kind")
            if expected[0] == "s":
                exact_keys(raw_block, ("kind", "vars"), "scope")
                need(kind == "scope" and type(raw_block["vars"]) is dict
                     and set(raw_block["vars"]) == set(expected[1]),
                     "scope does not match program")
                decoded.append(["s", {name: decode_value(raw_block["vars"][name],
                                                         vtype, unit)
                                      for name, vtype in expected[1].items()}])
            elif expected[0] == "l":
                exact_keys(raw_block, ("kind", "at"), "loop")
                need(kind == "loop" and raw_block["at"] == expected[1]
                     and is_int(raw_block["at"]), "loop does not match program")
                decoded.append(["l", expected[1]])
            else:
                exact_keys(raw_block, ("kind", "at", "journal", "events"),
                           "transaction")
                need(kind == "transaction" and raw_block["at"] == expected[1]
                     and is_int(raw_block["at"]), "transaction does not match program")
                jmark, emark = raw_block["journal"], raw_block["events"]
                need(is_int(jmark) and is_int(emark) and jmark >= 0 and emark >= 0,
                     "bad transaction marks")
                tx_marks.append((jmark, emark))
                decoded.append(["t", expected[1], jmark, emark])
        frames.append(Frame(proc, pc, decoded))
    vm.frames = frames
    vm.tx_depth = len(tx_marks)

    journal = state["journal"]
    need(type(journal) is list, "bad journal")
    need(tx_marks or not journal, "journal without active transaction")
    previous = (0, 0)
    for index, marks in enumerate(tx_marks):
        need(marks[0] >= previous[0] and marks[1] >= previous[1]
             and (index or marks[0] == 0), "transaction marks out of order")
        previous = marks
    need(previous[0] <= len(journal) and previous[1] <= len(events),
         "transaction marks beyond journal/events")
    for entry in journal:
        need(type(entry) is list and entry, "bad journal entry")
        kind = entry[0]
        if kind == "w":
            need(len(entry) == 4 and entry[1] in warehouses and is_name(entry[2])
                 and (entry[3] is None or (is_int(entry[3]) and entry[3] >= 0)),
                 "bad stock journal entry")
            vm.journal.append(list(entry))
        elif kind == "h":
            need(len(entry) == 3 and is_name(entry[1]), "bad hold journal entry")
            old = entry[2]
            if old is not None:
                need(type(old) is list and len(old) == 3 and old[0] in warehouses
                     and is_name(old[1]) and is_int(old[2]) and old[2] >= 0,
                     "bad hold journal record")
                old = tuple(old)
            vm.journal.append(["h", entry[1], old])
        elif kind == "v":
            need(len(entry) == 5 and is_int(entry[1]) and is_int(entry[2])
                 and entry[1] >= 0 and entry[2] >= 0 and type(entry[3]) is str,
                 "bad variable journal entry")
            vm.journal.append(["v", entry[1], entry[2], entry[3],
                               decode_any(entry[4], unit)])
        else:
            raise BadState("unknown journal entry")
    return vm
