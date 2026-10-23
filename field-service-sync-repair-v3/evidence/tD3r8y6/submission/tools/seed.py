"""Generate the immutable incident history and a drifted working projection."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.codec import canonical, digest
from server.store import Store


def seed(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to replace existing state: {path}")
    Store(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE metadata SET epoch='dispatch-2026-04'")
        events = [
            (9007199254740993, "north", "pump-17", 41, "Inspect east pump", "Mira", 8, False, False),
            (9007199254740994, "north", "pump-17", 42, "Inspect east pump", "Mira", 9, False, False),
            (9007199254740995, "north", "valve-4", 1, "Replace valve", None, 0, False, False),
            (9007199254740996, "north", "pump-17", 43, "Inspect east pump", None, 9, True, False),
            (9007199254740997, "north", "valve-4", 2, "Replace valve", None, 0, False, True),
            (9007199254740998, "south", "pump-17", 6, "Check backup pump", "Jo", 2, False, False),
        ]
        for seq, tenant, entity, rev, title, assignee, visits, done, deleted in events:
            body = {"title": title, "assignee": assignee, "visits": visits, "done": done}
            mutation = f"legacy-{seq}"
            row = {"id": entity, "revision": str(rev), "body": body,
                   "deleted": deleted, "seq": str(seq)}
            response = {"ok": True, "tenant": tenant, "device": "archive",
                        "mutation": mutation, "record": row}
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                       (seq, tenant, entity, rev, canonical(body), int(deleted), "archive", mutation))
            db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                       (tenant, entity, rev, canonical(body), int(deleted)))
            db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                       (tenant, "archive", mutation, digest({"archived": mutation}), canonical(response)))
        db.execute("UPDATE documents SET revision=41,body=? WHERE tenant='north' AND id='pump-17'",
                   (canonical({"title": "Inspect east pump", "assignee": "Mira",
                               "visits": 8, "done": False}),))
        db.execute("UPDATE documents SET deleted=0 WHERE id='valve-4'")
        db.execute("DELETE FROM documents WHERE tenant='south'")
        db.execute("INSERT INTO documents VALUES ('north','phantom',1,?,0)",
                   (canonical({"title": "Uncommitted work", "assignee": None,
                               "visits": 0, "done": False}),))
    print(json.dumps({"database": str(path), "events": len(events), "projection_drift": 4}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    seed(parser.parse_args().db)
