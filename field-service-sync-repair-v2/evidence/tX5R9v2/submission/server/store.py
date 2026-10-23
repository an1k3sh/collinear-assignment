import json
import sqlite3
import uuid

from server.codec import (MAX_INT64, MAX_SAFE, SyncError, body, canonical, decimal,
                          digest, text, token, untoken)


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

MUTATION_KEYS = {"tenant", "device", "mutation", "id", "base", "kind", "data"}
OPERATION_KEYS = MUTATION_KEYS - {"tenant", "device"}
BATCH_KEYS = {"tenant", "device", "batch", "operations"}
MAX_BATCH = 16


def record(row):
    """Convert an events row into a wire record (decimal strings for integers)."""
    if row is None:
        return None
    return {"id": row["id"], "revision": str(row["revision"]),
            "body": json.loads(row["body"]), "deleted": bool(row["deleted"]),
            "seq": str(row["seq"])}


def confirmation(row):
    return {"device": row["device"], "mutation": row["mutation"], "id": row["id"],
            "seq": str(row["seq"])}


def validate_mutation(request):
    """Validate an ordinary mutation request; returns the parsed base revision."""
    if not isinstance(request, dict) or set(request) != MUTATION_KEYS:
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
                or not 0 < data["amount"] <= MAX_SAFE):
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
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def connect(self):
        # Autocommit mode: every transaction is explicit, so nothing is committed
        # implicitly and an exception always rolls the whole operation back.
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _write(self, work):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            result = work(db)
            db.execute("COMMIT")
            return result
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _read(self, work):
        db = self.connect()
        try:
            # One deferred read transaction gives a consistent view for the page.
            db.execute("BEGIN")
            return work(db)
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
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
        if current is None:
            allowed = kind == "create" and base == 0
        else:
            allowed = (kind != "create" and base == revision
                       and current["deleted"] == (kind == "restore"))
        if not allowed:
            raise SyncError(409, "conflict", {"current": current})
        new_body = dict(data) if kind == "create" else dict(current["body"])
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
        if self.fault:
            self.fault("after_document")
        seq = db.execute(
            "INSERT INTO events(tenant,id,revision,body,deleted,device,mutation)"
            " VALUES (?,?,?,?,?,?,?)",
            (tenant, entity, revision, encoded, int(deleted), device, mutation)).lastrowid
        if self.fault:
            self.fault("after_event")
        response = {"ok": True, "tenant": tenant, "device": device, "mutation": mutation,
                    "record": {"id": entity, "revision": str(revision),
                               "body": json.loads(encoded), "deleted": deleted,
                               "seq": str(seq)}}
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                   (tenant, device, mutation, digest(request), canonical(response)))
        return response

    def mutate(self, request):
        base = validate_mutation(request)
        fingerprint = digest(request)

        def work(db):
            receipt = self._receipt(db, request["tenant"], request["device"],
                                    request["mutation"])
            if receipt:
                if receipt["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(receipt["response"])
            return self._apply(db, request, base)

        return self._write(work)

    def mutate_batch(self, request):
        if not isinstance(request, dict) or set(request) != BATCH_KEYS:
            raise SyncError(400, "invalid")
        tenant, device, batch = (text(request[key]) for key in ("tenant", "device", "batch"))
        operations = request["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_BATCH:
            raise SyncError(400, "invalid")
        requests, bases, seen = [], [], set()
        for index, operation in enumerate(operations):
            try:
                if not isinstance(operation, dict) or set(operation) != OPERATION_KEYS:
                    raise SyncError(400, "invalid")
                full = {**operation, "tenant": tenant, "device": device}
                bases.append(validate_mutation(full))
                if operation["mutation"] in seen:
                    raise SyncError(400, "invalid")
            except SyncError as exc:
                raise SyncError(exc.status, exc.code, {**exc.detail, "index": index}) from exc
            seen.add(operation["mutation"])
            requests.append(full)
        fingerprint = digest(request)

        def work(db):
            existing = db.execute(
                "SELECT digest, response FROM batches WHERE tenant=? AND device=? AND batch=?",
                (tenant, device, batch)).fetchone()
            if existing:
                if existing["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(existing["response"])
            for index, full in enumerate(requests):
                if self._receipt(db, tenant, device, full["mutation"]):
                    raise SyncError(409, "batch_conflict", {"index": index})
            responses = []
            for index, (full, base) in enumerate(zip(requests, bases)):
                try:
                    responses.append(self._apply(db, full, base))
                except SyncError as exc:
                    raise SyncError(exc.status, exc.code,
                                    {**exc.detail, "index": index}) from exc
            response = {"ok": True, "tenant": tenant, "device": device, "batch": batch,
                        "responses": responses}
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (tenant, device, batch, fingerprint, canonical(response)))
            return response

        return self._write(work)

    # ------------------------------------------------------------------- reads

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SyncError(400, "invalid")

    @staticmethod
    def _head(db):
        epoch = db.execute("SELECT epoch FROM metadata").fetchone()[0]
        head = db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
        return epoch, head

    @staticmethod
    def _token(cursor, mode, tenant, epoch, keys):
        item = untoken(cursor)
        if (set(item) != keys or item.get("mode") != mode or item.get("tenant") != tenant
                or item.get("epoch") != epoch):
            raise SyncError(400, "invalid_cursor")
        return item

    def snapshot(self, tenant, limit, cursor=None):
        text(tenant)
        self._limit(limit)

        def work(db):
            epoch, head = self._head(db)
            last = None
            cut = head
            if cursor is not None:
                item = self._token(cursor, "snapshot", tenant, epoch,
                                   {"mode", "tenant", "epoch", "cut", "last"})
                cut = decimal(item["cut"], "invalid_cursor")
                last = text(item["last"], "invalid_cursor")
                if cut > head:
                    raise SyncError(400, "invalid_cursor")
                if not db.execute("SELECT 1 FROM events WHERE tenant=? AND id=? AND seq<=? LIMIT 1",
                                  (tenant, last, cut)).fetchone():
                    raise SyncError(400, "invalid_cursor")
            # Latest event per entity at or before the frozen cut (never the projection).
            if last is None:
                heads = db.execute(
                    "SELECT id, MAX(seq) AS seq FROM events WHERE tenant=? AND seq<=? "
                    "GROUP BY id ORDER BY id LIMIT ?", (tenant, cut, limit + 1)).fetchall()
            else:
                heads = db.execute(
                    "SELECT id, MAX(seq) AS seq FROM events WHERE tenant=? AND seq<=? AND id>? "
                    "GROUP BY id ORDER BY id LIMIT ?", (tenant, cut, last, limit + 1)).fetchall()
            more = len(heads) > limit
            heads = heads[:limit]
            rows = [record(db.execute("SELECT * FROM events WHERE seq=?", (h["seq"],)).fetchone())
                    for h in heads]
            confirmed = []
            ids = [row["id"] for row in rows]
            for start in range(0, len(ids), 100):
                chunk = ids[start:start + 100]
                confirmed.extend(db.execute(
                    "SELECT seq, device, mutation, id FROM events WHERE tenant=? AND seq<=? "
                    f"AND id IN ({','.join('?' * len(chunk))})",
                    (tenant, cut, *chunk)).fetchall())
            confirmed.sort(key=lambda row: row["seq"])
            continuation = token({"mode": "snapshot", "tenant": tenant, "epoch": epoch,
                                  "cut": str(cut), "last": rows[-1]["id"]}) if more else None
            return {"kind": "snapshot", "tenant": tenant, "epoch": epoch, "cut": str(cut),
                    "rows": rows, "confirmed": [confirmation(row) for row in confirmed],
                    "next_cursor": continuation}

        return self._read(work)

    def pull(self, tenant, checkpoint, limit, cursor=None):
        text(tenant)
        self._limit(limit)
        original = decimal(checkpoint, "invalid_cursor")

        def work(db):
            epoch, head = self._head(db)
            if original > head:
                raise SyncError(400, "invalid_cursor")
            start, until = original, head
            if cursor is not None:
                item = self._token(cursor, "events", tenant, epoch,
                                   {"mode", "tenant", "epoch", "origin", "after", "until"})
                if item["origin"] != checkpoint:
                    raise SyncError(400, "invalid_cursor")
                start = decimal(item["after"], "invalid_cursor")
                until = decimal(item["until"], "invalid_cursor")
                if not original <= start < until <= head:
                    raise SyncError(400, "invalid_cursor")
                if start > original and not db.execute(
                        "SELECT 1 FROM events WHERE seq=? AND tenant=?", (start, tenant)).fetchone():
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

        return self._read(work)

    # ------------------------------------------------------------------ repair

    def repair_projection(self):
        def work(db):
            expected = {}
            for row in db.execute(
                    "SELECT e.tenant, e.id, e.revision, e.body, e.deleted FROM events e JOIN "
                    "(SELECT MAX(seq) AS seq FROM events GROUP BY tenant, id) h ON e.seq=h.seq"):
                expected[(row["tenant"], row["id"])] = (
                    row["revision"], row["body"], row["deleted"])
            changed = set()
            seen = set()
            for row in db.execute(
                    "SELECT rowid, tenant, id, revision, body, deleted FROM documents").fetchall():
                key = (row["tenant"], row["id"])
                want = expected.get(key)
                if want is None or key in seen:
                    db.execute("DELETE FROM documents WHERE rowid=?", (row["rowid"],))
                    changed.add(key)
                    continue
                seen.add(key)
                have = (row["revision"], row["body"], row["deleted"])
                if any(type(a) is not type(b) or a != b for a, b in zip(have, want)):
                    db.execute("UPDATE documents SET revision=?, body=?, deleted=? WHERE rowid=?",
                               (*want, row["rowid"]))
                    changed.add(key)
            for key, want in expected.items():
                if key not in seen:
                    db.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (*key, *want))
                    changed.add(key)
            return {"repaired": len(changed)}

        return self._write(work)
