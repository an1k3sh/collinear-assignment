import json
import sqlite3
import uuid

from server.codec import SyncError, body, canonical, decimal, digest, text, token, untoken


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS metadata(epoch TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS documents(
 tenant TEXT, id TEXT, revision INTEGER NOT NULL, body TEXT NOT NULL,
 deleted INTEGER NOT NULL, PRIMARY KEY(tenant,id))""",
    """CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, id TEXT NOT NULL,
 revision INTEGER NOT NULL, body TEXT NOT NULL, deleted INTEGER NOT NULL,
 device TEXT NOT NULL, mutation TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS event_entity ON events(tenant,id,seq)""",
    """CREATE TABLE IF NOT EXISTS receipts(
 tenant TEXT, device TEXT, mutation TEXT, digest TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(tenant,device,mutation))""",
    """CREATE TABLE IF NOT EXISTS batches(
 tenant TEXT, device TEXT, batch TEXT, digest TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(tenant,device,batch))""",
    """CREATE TABLE IF NOT EXISTS retention(through INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS anchors(
 tenant TEXT, id TEXT, revision INTEGER NOT NULL, body TEXT NOT NULL,
 deleted INTEGER NOT NULL, seq INTEGER NOT NULL, PRIMARY KEY(tenant,id))""",
]

TABLES = {"metadata", "documents", "events", "receipts", "batches", "retention", "anchors"}
MUTATION_FIELDS = {"tenant", "device", "mutation", "id", "base", "kind", "data"}
OPERATION_FIELDS = {"mutation", "id", "base", "kind", "data"}
BATCH_FIELDS = {"tenant", "device", "batch", "operations"}
MAX_SAFE = 9007199254740991
MAX_INT64 = 9223372036854775807
MAX_OPERATIONS = 16

# Latest authoritative after-image per entity: retained anchors plus remaining
# events. Anchors always precede remaining events, so the highest seq wins.
HISTORY = """
SELECT tenant, id, revision, body, deleted, seq FROM events
 WHERE tenant=:tenant AND seq<=:cut
UNION ALL
SELECT tenant, id, revision, body, deleted, seq FROM anchors
 WHERE tenant=:tenant AND seq<=:cut
"""


def record(row):
    if row is None:
        return None
    return {"id": row["id"], "revision": str(int(row["revision"])),
            "body": json.loads(row["body"]), "deleted": bool(row["deleted"]),
            "seq": str(int(row["seq"]))}


def validate_operation(request):
    """Validate the per-operation part of a mutation; returns parsed values."""
    entity = text(request["id"])
    text(request["mutation"])
    base = decimal(request["base"])
    kind, data = request["kind"], request["data"]
    if kind in ("create", "patch", "restore"):
        body(data, partial=kind != "create")
    elif kind == "visit":
        if (not isinstance(data, dict) or set(data) != {"amount"}
                or type(data["amount"]) is not int
                or not 0 < data["amount"] <= MAX_SAFE):
            raise SyncError(400, "invalid")
    elif kind == "delete":
        if not isinstance(data, dict) or data:
            raise SyncError(400, "invalid")
    else:
        raise SyncError(400, "invalid")
    return entity, base, kind, data


def with_index(exc, index):
    detail = dict(exc.detail or {})
    detail["index"] = index
    return SyncError(exc.status, exc.code, detail)


class Store:
    def __init__(self, path, fault=None):
        self.path = str(path)
        self.fault = fault
        db = self.connect()
        try:
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if TABLES <= names and db.execute("SELECT 1 FROM metadata").fetchone() \
                    and db.execute("SELECT 1 FROM retention").fetchone():
                return
            db.execute("BEGIN IMMEDIATE")
            try:
                for statement in SCHEMA:
                    db.execute(statement)
                if not db.execute("SELECT epoch FROM metadata").fetchone():
                    db.execute("INSERT INTO metadata VALUES (?)", (str(uuid.uuid4()),))
                if not db.execute("SELECT through FROM retention").fetchone():
                    db.execute("INSERT INTO retention VALUES (0)")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _transaction(self, mode, work):
        db = self.connect()
        try:
            db.execute(mode)
            try:
                result = work(db)
                db.execute("COMMIT")
                return result
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    def _hook(self, stage):
        if self.fault:
            self.fault(stage)

    # ---- authoritative history helpers -------------------------------------

    @staticmethod
    def _epoch(db):
        return db.execute("SELECT epoch FROM metadata").fetchone()[0]

    @staticmethod
    def _floor(db):
        row = db.execute("SELECT MAX(through) FROM retention").fetchone()
        return int(row[0] or 0)

    def _head(self, db):
        latest = db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
        return max(self._floor(db), int(latest))

    @staticmethod
    def _current(db, tenant, entity):
        row = db.execute(
            "SELECT tenant,id,revision,body,deleted,seq FROM events "
            "WHERE tenant=? AND id=? ORDER BY seq DESC LIMIT 1", (tenant, entity)).fetchone()
        if row is None:
            row = db.execute(
                "SELECT tenant,id,revision,body,deleted,seq FROM anchors "
                "WHERE tenant=? AND id=?", (tenant, entity)).fetchone()
        return record(row)

    # ---- mutations ---------------------------------------------------------

    def _apply(self, db, tenant, device, mutation, entity, base, kind, data, fingerprint):
        current = self._current(db, tenant, entity)
        revision = int(current["revision"]) if current else 0
        if kind == "create":
            allowed = current is None and base == 0
        else:
            allowed = (current is not None and base == revision
                       and current["deleted"] == (kind == "restore"))
        if not allowed:
            raise SyncError(409, "conflict", {"current": current})
        if kind == "create":
            new_body = dict(data)
        else:
            new_body = dict(current["body"])
            if kind in ("patch", "restore"):
                new_body.update(data)
            elif kind == "visit":
                new_body["visits"] += data["amount"]
        body(new_body)
        if revision >= MAX_INT64:
            raise SyncError(400, "invalid")
        revision += 1
        deleted = kind == "delete"
        encoded = canonical(new_body)
        db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                   (tenant, entity, revision, encoded, int(deleted)))
        self._hook("after_document")
        seq = db.execute(
            "INSERT INTO events(tenant,id,revision,body,deleted,device,mutation)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant, entity, revision, encoded, int(deleted), device, mutation)).lastrowid
        if seq <= self._floor(db):
            raise RuntimeError("Event sequence allocation fell below the retention floor")
        self._hook("after_event")
        response = {"ok": True, "tenant": tenant, "device": device, "mutation": mutation,
                    "record": {"id": entity, "revision": str(revision), "body": new_body,
                               "deleted": deleted, "seq": str(seq)}}
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                   (tenant, device, mutation, fingerprint, canonical(response)))
        return response

    def mutate(self, request):
        if not isinstance(request, dict) or set(request) != MUTATION_FIELDS:
            raise SyncError(400, "invalid")
        tenant, device, mutation = (text(request[key]) for key in ("tenant", "device", "mutation"))
        entity, base, kind, data = validate_operation(request)
        fingerprint = digest(request)

        def work(db):
            receipt = db.execute(
                "SELECT digest,response FROM receipts WHERE tenant=? AND device=? AND mutation=?",
                (tenant, device, mutation)).fetchone()
            if receipt:
                if receipt["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(receipt["response"])
            return self._apply(db, tenant, device, mutation, entity, base, kind, data,
                               fingerprint)

        return self._transaction("BEGIN IMMEDIATE", work)

    def mutate_batch(self, request):
        if not isinstance(request, dict) or set(request) != BATCH_FIELDS:
            raise SyncError(400, "invalid")
        tenant, device, batch = (text(request[key]) for key in ("tenant", "device", "batch"))
        operations = request["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise SyncError(400, "invalid")
        parsed, seen = [], set()
        for index, operation in enumerate(operations):
            try:
                if not isinstance(operation, dict) or set(operation) != OPERATION_FIELDS:
                    raise SyncError(400, "invalid")
                values = validate_operation(operation)
                if operation["mutation"] in seen:
                    raise SyncError(400, "invalid")
            except SyncError as exc:
                raise with_index(exc, index) from exc
            seen.add(operation["mutation"])
            full = {**operation, "tenant": tenant, "device": device}
            parsed.append((operation["mutation"], values, digest(full)))
        fingerprint = digest(request)

        def work(db):
            stored = db.execute(
                "SELECT digest,response FROM batches WHERE tenant=? AND device=? AND batch=?",
                (tenant, device, batch)).fetchone()
            if stored:
                if stored["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(stored["response"])
            responses = []
            for index, (mutation, values, op_digest) in enumerate(parsed):
                try:
                    if db.execute(
                            "SELECT 1 FROM receipts WHERE tenant=? AND device=? AND mutation=?",
                            (tenant, device, mutation)).fetchone():
                        raise SyncError(409, "batch_conflict")
                    responses.append(self._apply(db, tenant, device, mutation, *values,
                                                 op_digest))
                except SyncError as exc:
                    raise with_index(exc, index) from exc
            response = {"ok": True, "tenant": tenant, "device": device, "batch": batch,
                        "responses": responses}
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (tenant, device, batch, fingerprint, canonical(response)))
            return response

        return self._transaction("BEGIN IMMEDIATE", work)

    # ---- retention ---------------------------------------------------------

    def compact(self, through):
        boundary = decimal(through)

        def work(db):
            floor, head = self._floor(db), self._head(db)
            if not floor <= boundary <= head:
                raise SyncError(400, "invalid", {"floor": str(floor), "head": str(head)})
            db.execute(
                "INSERT OR REPLACE INTO anchors(tenant,id,revision,body,deleted,seq) "
                "SELECT e.tenant,e.id,e.revision,e.body,e.deleted,e.seq FROM events e "
                "WHERE e.seq<=:through AND e.seq=(SELECT MAX(x.seq) FROM events x "
                " WHERE x.tenant=e.tenant AND x.id=e.id AND x.seq<=:through) "
                "AND e.seq>COALESCE((SELECT a.seq FROM anchors a "
                " WHERE a.tenant=e.tenant AND a.id=e.id),-1)",
                {"through": boundary})
            self._hook("after_anchor")
            pruned = db.execute("DELETE FROM events WHERE seq<=?", (boundary,)).rowcount
            self._hook("after_prune")
            db.execute("UPDATE retention SET through=?", (boundary,))
            return {"through": str(boundary), "pruned": pruned}

        return self._transaction("BEGIN IMMEDIATE", work)

    # ---- reads -------------------------------------------------------------

    @staticmethod
    def _limit(tenant, limit):
        text(tenant)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SyncError(400, "invalid")

    def _cursor(self, cursor, mode, tenant, epoch, fields):
        if cursor is None:
            return None
        item = untoken(cursor)
        if (set(item) != fields or item.get("mode") != mode
                or item.get("tenant") != tenant or item.get("epoch") != epoch):
            raise SyncError(400, "invalid_cursor")
        return item

    def snapshot(self, tenant, limit, cursor=None):
        self._limit(tenant, limit)

        def work(db):
            epoch, floor, head = self._epoch(db), self._floor(db), self._head(db)
            item = self._cursor(cursor, "snapshot", tenant, epoch,
                                {"mode", "tenant", "epoch", "cut", "last"})
            cut, last = head, None
            if item is not None:
                cut = decimal(item["cut"], "invalid_cursor")
                last = item["last"]
                if cut > head or not isinstance(last, str) or not last:
                    raise SyncError(400, "invalid_cursor")
                if cut < floor:
                    raise SyncError(410, "resnapshot_required",
                                    {"epoch": epoch, "floor": str(floor)})
                if not db.execute("SELECT 1 FROM (" + HISTORY + ") WHERE id=:last LIMIT 1",
                                  {"tenant": tenant, "cut": cut, "last": last}).fetchone():
                    raise SyncError(400, "invalid_cursor")
            rows = db.execute(
                "SELECT id,revision,body,deleted,seq FROM ("
                " SELECT h.*, ROW_NUMBER() OVER (PARTITION BY h.id ORDER BY h.seq DESC) rn"
                " FROM (" + HISTORY + ") h WHERE (:last IS NULL OR h.id>:last)"
                ") WHERE rn=1 ORDER BY id LIMIT :limit",
                {"tenant": tenant, "cut": cut, "last": last, "limit": limit + 1}).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            continuation = token({"mode": "snapshot", "tenant": tenant, "epoch": epoch,
                                  "cut": str(cut), "last": rows[-1]["id"]}) if more else None
            return {"kind": "snapshot", "tenant": tenant, "epoch": epoch, "cut": str(cut),
                    "rows": [record(row) for row in rows],
                    "confirmed": self._confirmations(db, tenant, [r["id"] for r in rows], cut),
                    "next_cursor": continuation}

        return self._transaction("BEGIN", work)

    @staticmethod
    def _confirmations(db, tenant, ids, cut):
        """All committed operations at/before cut for these entities.

        Receipts are immutable and survive event pruning; remaining events are
        consulted as well so that history without a receipt is not lost."""
        if not ids:
            return []
        found = {}
        wanted = set(ids)
        marks = ",".join("?" * len(ids))
        for row in db.execute(
                "SELECT device,mutation,id,seq FROM events WHERE tenant=? AND seq<=? "
                f"AND id IN ({marks})", (tenant, cut, *ids)):
            found[int(row["seq"])] = {"device": row["device"], "mutation": row["mutation"],
                                      "id": row["id"], "seq": str(int(row["seq"]))}
        for row in db.execute(
                "SELECT device,mutation,json_extract(response,'$.record.id') entity,"
                " CAST(json_extract(response,'$.record.seq') AS INTEGER) seq FROM receipts"
                f" WHERE tenant=? AND json_extract(response,'$.record.id') IN ({marks})",
                (tenant, *ids)):
            seq = row["seq"]
            if seq is None or seq > cut or row["entity"] not in wanted:
                continue
            found.setdefault(int(seq), {"device": row["device"], "mutation": row["mutation"],
                                        "id": row["entity"], "seq": str(int(seq))})
        return [found[seq] for seq in sorted(found)]

    def pull(self, tenant, checkpoint, limit, cursor=None):
        original = decimal(checkpoint, "invalid_cursor")
        self._limit(tenant, limit)

        def work(db):
            epoch, floor, head = self._epoch(db), self._floor(db), self._head(db)
            if original > head:
                raise SyncError(400, "invalid_cursor")
            item = self._cursor(cursor, "events", tenant, epoch,
                                {"mode", "tenant", "epoch", "origin", "after", "until"})
            if item is None:
                if original < floor:
                    raise SyncError(410, "resnapshot_required",
                                    {"epoch": epoch, "floor": str(floor)})
                start, until = original, head
            else:
                if item["origin"] != checkpoint:
                    raise SyncError(400, "invalid_cursor")
                start = decimal(item["after"], "invalid_cursor")
                until = decimal(item["until"], "invalid_cursor")
                if not original <= start <= until <= head:
                    raise SyncError(400, "invalid_cursor")
                if start == original:
                    raise SyncError(400, "invalid_cursor")
                if start < floor:
                    raise SyncError(410, "resnapshot_required",
                                    {"epoch": epoch, "floor": str(floor)})
                # A continuation resumes after a returned tenant event (unless
                # that event has since been pruned exactly at the floor).
                if start > floor and not db.execute(
                        "SELECT 1 FROM events WHERE tenant=? AND seq=?",
                        (tenant, start)).fetchone():
                    raise SyncError(400, "invalid_cursor")
            rows = db.execute(
                "SELECT * FROM events WHERE tenant=? AND seq>? AND seq<=? ORDER BY seq LIMIT ?",
                (tenant, start, until, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            after = rows[-1]["seq"] if more else until
            continuation = token({"mode": "events", "tenant": tenant, "epoch": epoch,
                                  "origin": checkpoint, "after": str(after),
                                  "until": str(until)}) if more else None
            return {"kind": "events", "tenant": tenant, "epoch": epoch,
                    "from": str(start), "after": str(after), "until": str(until),
                    "events": [record(row) for row in rows],
                    "confirmed": [{"device": row["device"], "mutation": row["mutation"],
                                   "id": row["id"], "seq": str(row["seq"])} for row in rows],
                    "next_cursor": continuation}

        return self._transaction("BEGIN", work)

    # ---- projection repair -------------------------------------------------

    def repair_projection(self):
        def work(db):
            expected = {}
            for row in db.execute(
                    "SELECT tenant,id,revision,body,deleted,seq FROM anchors "
                    "UNION ALL SELECT tenant,id,revision,body,deleted,seq FROM events "
                    "ORDER BY seq"):
                expected[(row["tenant"], row["id"])] = (
                    int(row["revision"]), row["body"], int(bool(row["deleted"])))
            actual = {(row["tenant"], row["id"]): (row["revision"], row["body"], row["deleted"])
                      for row in db.execute(
                          "SELECT tenant,id,revision,body,deleted FROM documents")}
            changed = 0
            for key in actual.keys() | expected.keys():
                want, have = expected.get(key), actual.get(key)
                if want == have:
                    continue
                changed += 1
                if want is None:
                    db.execute("DELETE FROM documents WHERE tenant=? AND id=?", key)
                else:
                    db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                               (*key, *want))
            return {"repaired": changed}

        return self._transaction("BEGIN IMMEDIATE", work)
