import json
import sqlite3
import uuid

from server.codec import SyncError, body, canonical, decimal, digest, text, token, untoken


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


def record(row):
    if row is None:
        return None
    return {"id": row["id"], "revision": str(row["revision"]),
            "body": json.loads(row["body"]), "deleted": bool(row["deleted"]),
            "seq": str(row["seq"])}


class Store:
    def __init__(self, path, fault=None):
        self.path = str(path)
        self.fault = fault
        db = self.connect()
        try:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT epoch FROM metadata").fetchone():
                db.execute("INSERT INTO metadata VALUES (?)", (str(uuid.uuid4()),))
            db.commit()
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def mutate(self, request):
        return self._mutate(request)

    def _mutate(self, request, connection=None):
        if not isinstance(request, dict) or set(request) != {
            "tenant", "device", "mutation", "id", "base", "kind", "data"
        }:
            raise SyncError(400, "invalid")
        tenant, device, mutation, entity = [
            text(request[key]) for key in ("tenant", "device", "mutation", "id")
        ]
        base = decimal(request["base"])
        kind, data = request["kind"], request["data"]
        if kind in ("create", "patch", "restore"):
            body(data, partial=kind != "create")
        elif kind == "visit":
            if (not isinstance(data, dict) or set(data) != {"amount"}
                    or type(data["amount"]) is not int or data["amount"] <= 0):
                raise SyncError(400, "invalid")
        elif kind != "delete" or data != {}:
            raise SyncError(400, "invalid")
        fingerprint = digest(request)
        db = connection if connection is not None else self.connect()
        try:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            receipt = db.execute(
                "SELECT * FROM receipts WHERE tenant=? AND device=? AND mutation=?",
                (tenant, device, mutation)).fetchone()
            if receipt:
                if receipt["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(receipt["response"])
            current = record(db.execute(
                "SELECT * FROM events WHERE tenant=? AND id=? ORDER BY seq DESC LIMIT 1",
                (tenant, entity)).fetchone())
            revision = int(current["revision"]) if current else 0
            allowed = (current is None and kind == "create" and base == 0) or (
                current is not None and base == revision and kind != "create"
                and current["deleted"] == (kind == "restore"))
            if not allowed:
                raise SyncError(409, "conflict", {"current": current})
            new_body = dict(data) if kind == "create" else dict(current["body"])
            if kind in ("patch", "restore"):
                new_body.update(data)
            if kind == "visit":
                new_body["visits"] += data["amount"]
            body(new_body)
            if revision == 9223372036854775807:
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
                (tenant, entity, revision, encoded, int(deleted), device, mutation)
            ).lastrowid
            if self.fault:
                self.fault("after_event")
            response = {"ok": True, "tenant": tenant, "device": device,
                        "mutation": mutation,
                        "record": {"id": entity, "revision": str(revision),
                                   "body": new_body, "deleted": deleted, "seq": str(seq)}}
            db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                       (tenant, device, mutation, fingerprint, canonical(response)))
            if connection is None:
                db.commit()
            return response
        finally:
            if connection is None:
                db.close()

    def mutate_batch(self, request):
        if not isinstance(request, dict) or set(request) != {"tenant", "device", "batch", "operations"}:
            raise SyncError(400, "invalid")
        tenant, device, batch = [text(request[k]) for k in ("tenant", "device", "batch")]
        operations = request["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 16:
            raise SyncError(400, "invalid")
        seen = set()
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {"mutation", "id", "base", "kind", "data"}:
                raise SyncError(400, "invalid")
            mutation = text(operation["mutation"])
            if mutation in seen:
                raise SyncError(400, "invalid")
            seen.add(mutation)
        try:
            fingerprint = digest(request)
        except (ValueError, TypeError) as exc:
            raise SyncError(400, "invalid") from exc
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM batches WHERE tenant=? AND device=? AND batch=?",
                (tenant, device, batch)).fetchone()
            if previous:
                if previous["digest"] != fingerprint:
                    raise SyncError(409, "idempotency_reuse")
                return json.loads(previous["response"])
            responses = []
            for index, operation in enumerate(operations):
                try:
                    if db.execute(
                        "SELECT 1 FROM receipts WHERE tenant=? AND device=? AND mutation=?",
                        (tenant, device, operation["mutation"])).fetchone():
                        raise SyncError(409, "batch_conflict")
                    responses.append(self._mutate(
                        {**operation, "tenant": tenant, "device": device}, db))
                except SyncError as exc:
                    raise SyncError(exc.status, exc.code, {**exc.detail, "index": index}) from exc
            response = {"ok": True, "tenant": tenant, "device": device,
                        "batch": batch, "responses": responses}
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (tenant, device, batch, fingerprint, canonical(response)))
            db.commit()
            return response
        finally:
            db.close()

    @staticmethod
    def _confirmation(row):
        return {key: str(row[key]) for key in ("device", "mutation", "id", "seq")}

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
                last = item["last"]
                if cut > head or not isinstance(last, str) or not last:
                    raise SyncError(400, "invalid_cursor")
            rows = db.execute(
                "SELECT e.* FROM events e JOIN "
                "(SELECT id,MAX(seq) seq FROM events WHERE tenant=? AND seq<=? GROUP BY id) h "
                "ON e.seq=h.seq WHERE (? IS NULL OR e.id>?) ORDER BY e.id LIMIT ?",
                (tenant, cut, last, last, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            ids = {row["id"] for row in rows}
            confirmed = [self._confirmation(row) for row in db.execute(
                "SELECT * FROM events WHERE tenant=? AND seq<=? ORDER BY seq", (tenant, cut))
                if row["id"] in ids]
            continuation = token({"mode": "snapshot", "tenant": tenant, "epoch": epoch,
                                  "cut": str(cut), "last": rows[-1]["id"]}) if more else None
            return {"kind": "snapshot", "tenant": tenant, "epoch": epoch,
                    "cut": str(cut), "rows": [record(row) for row in rows], "confirmed": confirmed,
                    "next_cursor": continuation}
        finally:
            db.close()

    def pull(self, tenant, checkpoint, limit, cursor=None):
        original = decimal(checkpoint, "invalid_cursor")
        db = self.connect()
        try:
            db.execute("BEGIN")
            epoch, head, item = self._page(db, tenant, limit, cursor, "events")
            start, until = original, head
            if original > head:
                raise SyncError(400, "invalid_cursor")
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
                    "confirmed": [self._confirmation(row) for row in rows],
                    "next_cursor": continuation}
        finally:
            db.close()

    def repair_projection(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            expected = {(r["tenant"], r["id"]): (r["revision"], r["body"], r["deleted"])
                        for r in db.execute(
                            "SELECT e.* FROM events e JOIN "
                            "(SELECT tenant,id,MAX(seq) seq FROM events GROUP BY tenant,id) h"
                            " ON e.seq=h.seq")}
            actual = {(r["tenant"], r["id"]): (r["revision"], r["body"], r["deleted"])
                      for r in db.execute("SELECT * FROM documents")}
            changed = sum(actual.get(key) != expected.get(key)
                          for key in actual.keys() | expected.keys())
            db.execute("DELETE FROM documents")
            db.executemany("INSERT INTO documents VALUES (?,?,?,?,?)",
                           [(t, i, *values) for (t, i), values in expected.items()])
            db.commit()
            return {"repaired": changed}
        finally:
            db.close()
