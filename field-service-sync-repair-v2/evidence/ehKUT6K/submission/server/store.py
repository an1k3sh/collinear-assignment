import json
import sqlite3
import uuid

from server.codec import (MAX_VISITS, SyncError, body, canonical, decimal, digest, text,
                          token, untoken)


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(epoch TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
 tenant TEXT, id TEXT, revision INTEGER NOT NULL, body TEXT NOT NULL,
 deleted INTEGER NOT NULL, PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, id TEXT NOT NULL,
 revision INTEGER NOT NULL, body TEXT NOT NULL, deleted INTEGER NOT NULL,
 device TEXT NOT NULL, mutation TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_entity ON events(tenant,id,seq);
CREATE TABLE IF NOT EXISTS receipts(
 tenant TEXT, device TEXT, mutation TEXT, digest TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(tenant,device,mutation));
CREATE TABLE IF NOT EXISTS batches(
 tenant TEXT, device TEXT, batch TEXT, digest TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(tenant,device,batch));
"""

MAX_INTEGER = 9223372036854775807
REQUEST_FIELDS = {"tenant", "device", "mutation", "id", "base", "kind", "data"}
OPERATION_FIELDS = REQUEST_FIELDS - {"tenant", "device"}
BATCH_FIELDS = {"tenant", "device", "batch", "operations"}
MAX_BATCH = 16


def record(row):
    """Wire record from an events row; revision and seq are decimal strings."""
    if row is None:
        return None
    return {"id": row["id"], "revision": str(row["revision"]),
            "body": json.loads(row["body"]), "deleted": bool(row["deleted"]),
            "seq": str(row["seq"])}


def confirmation(row):
    return {"device": row["device"], "mutation": row["mutation"], "id": row["id"],
            "seq": str(row["seq"])}


def validate(request):
    """Validate an ordinary mutation request; returns the parsed base revision."""
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise SyncError(400, "invalid")
    for key in ("tenant", "device", "mutation", "id"):
        text(request[key])
    base = decimal(request["base"])
    kind, data = request["kind"], request["data"]
    if not isinstance(kind, str):
        raise SyncError(400, "invalid")
    if kind in ("create", "patch", "restore"):
        body(data, partial=kind != "create")
    elif kind == "visit":
        if (not isinstance(data, dict) or set(data) != {"amount"}
                or type(data["amount"]) is not int
                or not 0 < data["amount"] <= MAX_VISITS):
            raise SyncError(400, "invalid")
    elif kind != "delete" or not isinstance(data, dict) or data:
        raise SyncError(400, "invalid")
    return base


class Store:
    def __init__(self, path, fault=None):
        self.path = str(path)
        self.fault = fault
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            if not db.execute("SELECT epoch FROM metadata").fetchone():
                db.execute("INSERT INTO metadata VALUES (?)", (str(uuid.uuid4()),))
            db.execute("COMMIT")
        finally:
            self.close(db)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def close(db):
        try:
            if db.in_transaction:
                db.execute("ROLLBACK")
        finally:
            db.close()

    # ------------------------------------------------------------------ writes

    def _receipt(self, db, tenant, device, mutation):
        return db.execute(
            "SELECT digest, response FROM receipts WHERE tenant=? AND device=? AND mutation=?",
            (tenant, device, mutation)).fetchone()

    def _apply(self, db, request, base):
        """Apply one validated mutation inside the caller's write transaction."""
        tenant, device, mutation, entity = (
            request["tenant"], request["device"], request["mutation"], request["id"])
        kind, data = request["kind"], request["data"]
        current = record(db.execute(
            "SELECT * FROM events WHERE tenant=? AND id=? ORDER BY seq DESC LIMIT 1",
            (tenant, entity)).fetchone())
        revision = int(current["revision"]) if current else 0
        if kind == "create":
            allowed = current is None and base == 0
        else:
            allowed = (current is not None and base == revision
                       and current["deleted"] == (kind == "restore"))
        if not allowed:
            raise SyncError(409, "conflict", {"current": current})
        new_body = dict(data) if kind == "create" else dict(current["body"])
        if kind in ("patch", "restore"):
            new_body.update(data)
        elif kind == "visit":
            new_body["visits"] += data["amount"]
        body(new_body)
        if revision >= MAX_INTEGER:
            raise SyncError(400, "invalid")
        revision += 1
        deleted = kind == "delete"
        encoded = canonical(new_body)
        db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                   (tenant, entity, revision, encoded, int(deleted)))
        if self.fault:
            self.fault("after_document")
        seq = db.execute(
            "INSERT INTO events(tenant,id,revision,body,deleted,device,mutation)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant, entity, revision, encoded, int(deleted), device, mutation)).lastrowid
        if self.fault:
            self.fault("after_event")
        response = {"ok": True, "tenant": tenant, "device": device, "mutation": mutation,
                    "record": {"id": entity, "revision": str(revision), "body": new_body,
                               "deleted": deleted, "seq": str(seq)}}
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                   (tenant, device, mutation, digest(request), canonical(response)))
        return response

    def mutate(self, request):
        base = validate(request)
        fingerprint = digest(request)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            receipt = self._receipt(db, request["tenant"], request["device"],
                                    request["mutation"])
            if receipt:
                if receipt["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(receipt["response"])
            response = self._apply(db, request, base)
            db.execute("COMMIT")
            return response
        finally:
            self.close(db)

    def mutate_batch(self, request):
        if not isinstance(request, dict) or set(request) != BATCH_FIELDS:
            raise SyncError(400, "invalid")
        tenant, device, batch = (text(request[key]) for key in ("tenant", "device", "batch"))
        operations = request["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_BATCH:
            raise SyncError(400, "invalid")
        prepared, seen = [], set()
        for index, operation in enumerate(operations):
            try:
                if not isinstance(operation, dict) or set(operation) != OPERATION_FIELDS:
                    raise SyncError(400, "invalid")
                full = {**operation, "tenant": tenant, "device": device}
                base = validate(full)
            except SyncError as exc:
                raise SyncError(exc.status, exc.code, {**exc.detail, "index": index}) from exc
            if full["mutation"] in seen:
                raise SyncError(400, "invalid", {"index": index})
            seen.add(full["mutation"])
            prepared.append((full, base))
        fingerprint = digest(request)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT digest, response FROM batches WHERE tenant=? AND device=? AND batch=?",
                (tenant, device, batch)).fetchone()
            if existing:
                if existing["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(existing["response"])
            responses = []
            for index, (full, base) in enumerate(prepared):
                try:
                    if self._receipt(db, tenant, device, full["mutation"]):
                        raise SyncError(409, "batch_conflict")
                    responses.append(self._apply(db, full, base))
                except SyncError as exc:
                    raise SyncError(exc.status, exc.code,
                                    {**exc.detail, "index": index}) from exc
            response = {"ok": True, "tenant": tenant, "device": device, "batch": batch,
                        "responses": responses}
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (tenant, device, batch, fingerprint, canonical(response)))
            db.execute("COMMIT")
            return response
        finally:
            self.close(db)

    # ------------------------------------------------------------------- reads

    def _page(self, db, tenant, limit, cursor, mode):
        text(tenant)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SyncError(400, "invalid")
        epoch = db.execute("SELECT epoch FROM metadata").fetchone()[0]
        head = db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
        if cursor is None:
            return epoch, head, None
        item = untoken(cursor)
        if item.get("mode") != mode or item.get("tenant") != tenant or item.get("epoch") != epoch:
            raise SyncError(400, "invalid_cursor")
        return epoch, head, item

    def snapshot(self, tenant, limit, cursor=None):
        db = self.connect()
        try:
            db.execute("BEGIN")
            epoch, head, item = self._page(db, tenant, limit, cursor, "snapshot")
            cut, last = head, None
            if item is not None:
                if set(item) != {"mode", "tenant", "epoch", "cut", "last"}:
                    raise SyncError(400, "invalid_cursor")
                cut = decimal(item["cut"], "invalid_cursor")
                last = text(item["last"], "invalid_cursor")
                if cut > head:
                    raise SyncError(400, "invalid_cursor")
            rows = db.execute(
                "SELECT e.* FROM events e JOIN ("
                " SELECT id, MAX(seq) AS seq FROM events"
                " WHERE tenant=? AND seq<=? AND (? IS NULL OR id>?)"
                " GROUP BY id ORDER BY id LIMIT ?) h ON e.seq=h.seq"
                " ORDER BY e.id",
                (tenant, cut, last, last, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            confirmed = []
            ids = [row["id"] for row in rows]
            for start in range(0, len(ids), 100):
                chunk = ids[start:start + 100]
                confirmed.extend(db.execute(
                    "SELECT seq, device, mutation, id FROM events WHERE tenant=? AND seq<=?"
                    f" AND id IN ({','.join('?' * len(chunk))})",
                    (tenant, cut, *chunk)).fetchall())
            confirmed.sort(key=lambda row: row["seq"])
            continuation = token({"mode": "snapshot", "tenant": tenant, "epoch": epoch,
                                  "cut": str(cut), "last": rows[-1]["id"]}) if more else None
            return {"kind": "snapshot", "tenant": tenant, "epoch": epoch,
                    "cut": str(cut), "rows": [record(row) for row in rows],
                    "confirmed": [confirmation(row) for row in confirmed],
                    "next_cursor": continuation}
        finally:
            self.close(db)

    def pull(self, tenant, checkpoint, limit, cursor=None):
        original = decimal(checkpoint, "invalid_cursor")
        db = self.connect()
        try:
            db.execute("BEGIN")
            epoch, head, item = self._page(db, tenant, limit, cursor, "events")
            if original > head:
                raise SyncError(400, "invalid_cursor")
            start, until = original, head
            if item is not None:
                if set(item) != {"mode", "tenant", "epoch", "origin", "after", "until"}:
                    raise SyncError(400, "invalid_cursor")
                if item["origin"] != checkpoint:
                    raise SyncError(400, "invalid_cursor")
                start = decimal(item["after"], "invalid_cursor")
                until = decimal(item["until"], "invalid_cursor")
                if not original <= start <= until <= head:
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
                    "confirmed": [confirmation(row) for row in rows],
                    "next_cursor": continuation}
        finally:
            self.close(db)

    # ------------------------------------------------------------------ repair

    def repair_projection(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            repaired = repair_documents(db)
            db.execute("COMMIT")
            return {"repaired": repaired}
        finally:
            self.close(db)


def repair_documents(db):
    """Rebuild documents from each tenant/id's last event within an open transaction.

    Only the documents table is written; events, receipts, batches and metadata
    are read-only here. Returns the number of entity keys that changed.
    """
    expected = {(r["tenant"], r["id"]): (r["revision"], r["body"], r["deleted"])
                for r in db.execute(
                    "SELECT e.tenant, e.id, e.revision, e.body, e.deleted FROM events e JOIN"
                    " (SELECT MAX(seq) AS seq FROM events GROUP BY tenant, id) h"
                    " ON e.seq=h.seq")}
    actual = {(r["tenant"], r["id"]): (r["revision"], r["body"], r["deleted"])
              for r in db.execute("SELECT tenant, id, revision, body, deleted FROM documents")}
    changed = 0
    for key in actual.keys() | expected.keys():
        want, have = expected.get(key), actual.get(key)
        if want is None:
            db.execute("DELETE FROM documents WHERE tenant IS ? AND id IS ?", key)
        elif have is None or type(have[0]) is not int or have[0] != want[0] \
                or have[1] != want[1] or have[2] not in (0, 1) \
                or bool(have[2]) != bool(want[2]):
            db.execute("DELETE FROM documents WHERE tenant IS ? AND id IS ?", key)
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?)",
                       (*key, want[0], want[1], int(bool(want[2]))))
        else:
            continue
        changed += 1
    return changed
