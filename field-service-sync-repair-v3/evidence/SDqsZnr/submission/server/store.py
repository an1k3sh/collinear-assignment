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
CREATE TABLE IF NOT EXISTS retention(through INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS anchors(
 tenant TEXT, id TEXT, revision INTEGER NOT NULL, body TEXT NOT NULL,
 deleted INTEGER NOT NULL, seq INTEGER NOT NULL, PRIMARY KEY(tenant,id));
"""

MAX_INTEGER = 9223372036854775807
MAX_VISITS = 9007199254740991
KINDS = ("create", "patch", "visit", "delete", "restore")
OPERATION_FIELDS = {"mutation", "id", "base", "kind", "data"}
REQUEST_FIELDS = OPERATION_FIELDS | {"tenant", "device"}
BATCH_FIELDS = {"tenant", "device", "batch", "operations"}
MAX_BATCH = 16
ENTITY_COLUMNS = "tenant,id,revision,body,deleted,seq"


def record(row):
    if row is None:
        return None
    return {"id": row["id"], "revision": str(int(row["revision"])),
            "body": json.loads(row["body"]), "deleted": bool(row["deleted"]),
            "seq": str(int(row["seq"]))}


def parse_operation(operation, fields):
    """Validate one mutation (or batch operation) and return its parsed parts."""
    if not isinstance(operation, dict) or set(operation) != fields:
        raise SyncError(400, "invalid")
    mutation, entity = text(operation["mutation"]), text(operation["id"])
    base = decimal(operation["base"])
    kind, data = operation["kind"], operation["data"]
    if kind in ("create", "patch", "restore"):
        body(data, partial=kind != "create")
    elif kind == "visit":
        if (not isinstance(data, dict) or set(data) != {"amount"}
                or type(data["amount"]) is not int
                or not 0 < data["amount"] <= MAX_VISITS):
            raise SyncError(400, "invalid")
    elif kind == "delete":
        if not isinstance(data, dict) or data:
            raise SyncError(400, "invalid")
    else:
        raise SyncError(400, "invalid")
    return mutation, entity, base, kind, data


def fingerprint(value):
    try:
        return digest(value)
    except (TypeError, ValueError) as exc:
        raise SyncError(400, "invalid") from exc


def with_index(error, index):
    detail = dict(error.detail or {})
    detail["index"] = index
    return SyncError(error.status, error.code, detail)


class Store:
    def __init__(self, path, fault=None):
        self.path = str(path)
        self.fault = fault
        db = self.connect()
        try:
            if self._initialized(db):
                return
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            if not db.execute("SELECT epoch FROM metadata").fetchone():
                db.execute("INSERT INTO metadata VALUES (?)", (str(uuid.uuid4()),))
            if not db.execute("SELECT through FROM retention").fetchone():
                db.execute("INSERT INTO retention VALUES (0)")
            db.execute("COMMIT")
        except BaseException:
            self._rollback(db)
            raise
        finally:
            db.close()

    @staticmethod
    def _initialized(db):
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        if not names >= {"metadata", "documents", "events", "receipts", "batches",
                         "retention", "anchors", "event_entity"}:
            return False
        return bool(db.execute("SELECT 1 FROM metadata").fetchone()
                    and db.execute("SELECT 1 FROM retention").fetchone())

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @staticmethod
    def _rollback(db):
        if db.in_transaction:
            db.execute("ROLLBACK")

    def _hook(self, point):
        if self.fault:
            self.fault(point)

    # ----- authoritative history helpers -------------------------------------------

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

    def _next_seq(self, db):
        allocated = db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        high = max(int(allocated[0]) if allocated and allocated[0] is not None else 0,
                   self._head(db))
        if high >= MAX_INTEGER:
            raise RuntimeError("event sequence exhausted")
        return high + 1

    @staticmethod
    def _current(db, tenant, entity, cut=None):
        """Latest authoritative after-image (remaining events, else retained anchor)."""
        if cut is None:
            row = db.execute(
                f"SELECT {ENTITY_COLUMNS} FROM events WHERE tenant=? AND id=? "
                "ORDER BY seq DESC LIMIT 1", (tenant, entity)).fetchone()
        else:
            row = db.execute(
                f"SELECT {ENTITY_COLUMNS} FROM events WHERE tenant=? AND id=? AND seq<=? "
                "ORDER BY seq DESC LIMIT 1", (tenant, entity, cut)).fetchone()
        if row is None:
            row = db.execute(
                f"SELECT {ENTITY_COLUMNS} FROM anchors WHERE tenant=? AND id=?",
                (tenant, entity)).fetchone()
        return row

    @staticmethod
    def _authoritative(db):
        """Every tenant/entity's latest after-image from anchors plus remaining events."""
        latest = {(r["tenant"], r["id"]): r for r in db.execute(
            f"SELECT {ENTITY_COLUMNS} FROM anchors")}
        for r in db.execute(
                f"SELECT e.tenant,e.id,e.revision,e.body,e.deleted,e.seq FROM events e JOIN "
                "(SELECT tenant,id,MAX(seq) seq FROM events GROUP BY tenant,id) h "
                "ON e.seq=h.seq"):
            latest[(r["tenant"], r["id"])] = r
        return latest

    # ----- mutations ---------------------------------------------------------------

    def _apply(self, db, tenant, device, parsed, fingerprint):
        mutation, entity, base, kind, data = parsed
        current = record(self._current(db, tenant, entity))
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
        seq = self._next_seq(db)
        db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                   (tenant, entity, revision, encoded, int(deleted)))
        self._hook("after_document")
        db.execute("INSERT INTO events(seq,tenant,id,revision,body,deleted,device,mutation)"
                   " VALUES (?,?,?,?,?,?,?,?)",
                   (seq, tenant, entity, revision, encoded, int(deleted), device, mutation))
        self._hook("after_event")
        response = {"ok": True, "tenant": tenant, "device": device, "mutation": mutation,
                    "record": {"id": entity, "revision": str(revision), "body": new_body,
                               "deleted": deleted, "seq": str(seq)}}
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                   (tenant, device, mutation, fingerprint, canonical(response)))
        return response

    @staticmethod
    def _receipt(db, tenant, device, mutation):
        return db.execute(
            "SELECT digest,response FROM receipts WHERE tenant=? AND device=? AND mutation=?",
            (tenant, device, mutation)).fetchone()

    def mutate(self, request):
        if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
            raise SyncError(400, "invalid")
        tenant, device, mutation = (text(request[key]) for key in ("tenant", "device", "mutation"))
        key = fingerprint(request)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            receipt = self._receipt(db, tenant, device, mutation)
            if receipt:
                if receipt["digest"] != key:
                    raise SyncError(409, "idempotency_reuse")
                response = json.loads(receipt["response"])
                db.execute("ROLLBACK")
                return response
            parsed = parse_operation(request, REQUEST_FIELDS)
            response = self._apply(db, tenant, device, parsed, key)
            db.execute("COMMIT")
            return response
        except BaseException:
            self._rollback(db)
            raise
        finally:
            db.close()

    @staticmethod
    def _parse_batch(operations):
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_BATCH:
            raise SyncError(400, "invalid")
        parsed, seen = [], set()
        for index, operation in enumerate(operations):
            try:
                item = parse_operation(operation, OPERATION_FIELDS)
            except SyncError as exc:
                raise with_index(exc, index) from exc
            if item[0] in seen:
                raise SyncError(400, "invalid", {"index": index})
            seen.add(item[0])
            parsed.append(item)
        return parsed

    def mutate_batch(self, request):
        if not isinstance(request, dict) or set(request) != BATCH_FIELDS:
            raise SyncError(400, "invalid")
        tenant, device, batch = (text(request[key]) for key in ("tenant", "device", "batch"))
        operations = request["operations"]
        key = fingerprint(request)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            # The batch's own receipt comes first so exact retries always succeed.
            existing = db.execute(
                "SELECT digest,response FROM batches WHERE tenant=? AND device=? AND batch=?",
                (tenant, device, batch)).fetchone()
            if existing:
                if existing["digest"] != key:
                    raise SyncError(409, "idempotency_reuse")
                response = json.loads(existing["response"])
                db.execute("ROLLBACK")
                return response
            parsed = self._parse_batch(operations)
            responses = []
            for index, (operation, item) in enumerate(zip(operations, parsed)):
                if self._receipt(db, tenant, device, item[0]):
                    raise SyncError(409, "batch_conflict", {"index": index})
                single = {**operation, "tenant": tenant, "device": device}
                try:
                    responses.append(self._apply(db, tenant, device, item, digest(single)))
                except SyncError as exc:
                    raise with_index(exc, index) from exc
            response = {"ok": True, "tenant": tenant, "device": device, "batch": batch,
                        "responses": responses}
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (tenant, device, batch, key, canonical(response)))
            db.execute("COMMIT")
            return response
        except BaseException:
            self._rollback(db)
            raise
        finally:
            db.close()

    # ----- retention ---------------------------------------------------------------

    def compact(self, through):
        boundary = decimal(through)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            floor, head = self._floor(db), self._head(db)
            if not floor <= boundary <= head:
                raise SyncError(400, "invalid", {"floor": str(floor), "head": str(head)})
            db.execute(
                f"INSERT OR REPLACE INTO anchors({ENTITY_COLUMNS}) "
                "SELECT e.tenant,e.id,e.revision,e.body,e.deleted,e.seq FROM events e JOIN "
                "(SELECT tenant,id,MAX(seq) seq FROM events WHERE seq<=? GROUP BY tenant,id) h "
                "ON e.seq=h.seq", (boundary,))
            self._hook("after_anchor")
            pruned = db.execute("DELETE FROM events WHERE seq<=?", (boundary,)).rowcount
            self._hook("after_prune")
            db.execute("UPDATE retention SET through=?", (boundary,))
            db.execute("COMMIT")
            return {"through": str(boundary), "pruned": pruned}
        except BaseException:
            self._rollback(db)
            raise
        finally:
            db.close()

    # ----- reads -------------------------------------------------------------------

    def _read(self, db, tenant, limit, cursor, mode, fields):
        text(tenant)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SyncError(400, "invalid")
        epoch = self._epoch(db)
        floor, head = self._floor(db), self._head(db)
        if cursor is None:
            return epoch, floor, head, None
        item = untoken(cursor)
        if (set(item) != fields or item["mode"] != mode or item["tenant"] != tenant
                or item["epoch"] != epoch):
            raise SyncError(400, "invalid_cursor")
        return epoch, floor, head, item

    @staticmethod
    def _expired(epoch, floor):
        return SyncError(410, "resnapshot_required", {"epoch": epoch, "floor": str(floor)})

    def _snapshot_confirmations(self, db, tenant, cut, ids):
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        found = {}
        for row in db.execute(
                f"SELECT device,mutation,id,seq FROM events WHERE tenant=? AND seq<=? "
                f"AND id IN ({marks})", (tenant, cut, *ids)):
            found[int(row["seq"])] = {"device": row["device"], "mutation": row["mutation"],
                                      "id": row["id"], "seq": str(int(row["seq"]))}
        for row in db.execute(
                f"SELECT device,mutation,response FROM receipts WHERE tenant=? "
                f"AND json_extract(response,'$.record.id') IN ({marks})", (tenant, *ids)):
            saved = json.loads(row["response"])["record"]
            seq = int(saved["seq"])
            if seq <= cut and seq not in found:
                found[seq] = {"device": row["device"], "mutation": row["mutation"],
                              "id": saved["id"], "seq": str(seq)}
        return [found[seq] for seq in sorted(found)]

    def snapshot(self, tenant, limit, cursor=None):
        db = self.connect()
        try:
            db.execute("BEGIN")
            epoch, floor, head, item = self._read(
                db, tenant, limit, cursor, "snapshot", {"mode", "tenant", "epoch", "cut", "last"})
            cut, last = head, None
            if item is not None:
                cut, last = decimal(item["cut"], "invalid_cursor"), item["last"]
                if not isinstance(last, str) or not last or cut > head:
                    raise SyncError(400, "invalid_cursor")
                if cut < floor:
                    raise self._expired(epoch, floor)
            ids = [row["id"] for row in db.execute(
                "SELECT id FROM (SELECT id FROM anchors WHERE tenant=? UNION "
                "SELECT id FROM events WHERE tenant=? AND seq<=?) "
                "WHERE (? IS NULL OR id>?) ORDER BY id LIMIT ?",
                (tenant, tenant, cut, last, last, limit + 1))]
            more = len(ids) > limit
            ids = ids[:limit]
            rows = [record(self._current(db, tenant, entity, cut)) for entity in ids]
            confirmed = self._snapshot_confirmations(db, tenant, cut, ids)
            continuation = token({"mode": "snapshot", "tenant": tenant, "epoch": epoch,
                                  "cut": str(cut), "last": ids[-1]}) if more else None
            return {"kind": "snapshot", "tenant": tenant, "epoch": epoch, "cut": str(cut),
                    "rows": rows, "confirmed": confirmed, "next_cursor": continuation}
        finally:
            self._rollback(db)
            db.close()

    def pull(self, tenant, checkpoint, limit, cursor=None):
        original = decimal(checkpoint, "invalid_cursor")
        db = self.connect()
        try:
            db.execute("BEGIN")
            epoch, floor, head, item = self._read(
                db, tenant, limit, cursor, "events",
                {"mode", "tenant", "epoch", "origin", "after", "until"})
            if original > head:
                raise SyncError(400, "invalid_cursor")
            if item is None:
                if original < floor:
                    raise self._expired(epoch, floor)
                start, until = original, head
            else:
                if item["origin"] != checkpoint:
                    raise SyncError(400, "invalid_cursor")
                start = decimal(item["after"], "invalid_cursor")
                until = decimal(item["until"], "invalid_cursor")
                if start < original or until > head:
                    raise SyncError(400, "invalid_cursor")
                if start < floor or until < start:
                    raise self._expired(epoch, floor)
            rows = db.execute(
                "SELECT * FROM events WHERE tenant=? AND seq>? AND seq<=? ORDER BY seq LIMIT ?",
                (tenant, start, until, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            after = int(rows[-1]["seq"]) if more else until
            continuation = token({"mode": "events", "tenant": tenant, "epoch": epoch,
                                  "origin": checkpoint, "after": str(after),
                                  "until": str(until)}) if more else None
            return {"kind": "events", "tenant": tenant, "epoch": epoch,
                    "from": str(start), "after": str(after), "until": str(until),
                    "events": [record(row) for row in rows],
                    "confirmed": [{"device": row["device"], "mutation": row["mutation"],
                                   "id": row["id"], "seq": str(int(row["seq"]))}
                                  for row in rows],
                    "next_cursor": continuation}
        finally:
            self._rollback(db)
            db.close()

    # ----- projection repair -------------------------------------------------------

    @staticmethod
    def _same_document(actual, expected):
        try:
            return (type(actual["revision"]) is int
                    and int(actual["revision"]) == int(expected["revision"])
                    and bool(actual["deleted"]) == bool(expected["deleted"])
                    and type(actual["deleted"]) is int
                    and canonical(json.loads(actual["body"])) == canonical(json.loads(expected["body"]))
                    and actual["body"] == expected["body"])
        except (TypeError, ValueError):
            return False

    def repair_projection(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            expected = self._authoritative(db)
            actual = {(r["tenant"], r["id"]): r for r in db.execute(
                "SELECT tenant,id,revision,body,deleted FROM documents")}
            changed = 0
            for key in actual.keys() - expected.keys():
                db.execute("DELETE FROM documents WHERE tenant IS ? AND id IS ?", key)
                changed += 1
            for key, row in expected.items():
                if key in actual and self._same_document(actual[key], row):
                    continue
                db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                           (*key, int(row["revision"]), row["body"], int(bool(row["deleted"]))))
                changed += 1
            db.execute("COMMIT")
            return {"repaired": changed}
        except BaseException:
            self._rollback(db)
            raise
        finally:
            db.close()
