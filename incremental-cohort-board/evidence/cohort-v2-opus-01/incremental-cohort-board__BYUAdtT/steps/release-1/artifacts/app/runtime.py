"""Trusted transaction host. Projection hooks live in maintainer.py."""
import json
import sqlite3
from pathlib import Path
from collections.abc import Sequence

import maintainer

FIELDS = {
    "orders": ("id", "account", "day", "cents"),
    "tags": ("id", "account", "segment"),
    "rates": ("id", "segment", "band"),
    "links": ("id", "left_account", "right_account"),
}
MODES = ("inner", "outer", "rated", "household")
SCHEMA = Path(__file__).with_name("schema.sql")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())
        self.db.execute("PRAGMA journal_mode=WAL")
        row = self.db.execute(
            "SELECT value FROM settings WHERE key='modes'"
        ).fetchone()
        self.modes = tuple(json.loads(row[0])) if row else ()

    def close(self):
        self.db.close()

    def upgrade(self, modes: Sequence[str]):
        modes = tuple(modes)
        if not modes or any(m not in MODES for m in modes):
            raise ValueError("Unknown or empty modes")
        if len(set(modes)) != len(modes) or not set(self.modes) <= set(modes):
            raise ValueError("Upgrades cannot remove or duplicate modes")
        if self.modes == modes:
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            maintainer.bootstrap(self.db, modes)
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES ('modes',?)",
                (json.dumps(modes),),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.modes = modes

    def apply(self, batch_id: str, mutations: list[dict], *, fail_after_hook=False):
        if not self.modes:
            raise ValueError("Call upgrade first")
        payload = json.dumps(mutations, sort_keys=True, separators=(",", ":"))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            receipt = self.db.execute(
                "SELECT payload FROM receipts WHERE id=?", (batch_id,)
            ).fetchone()
            if receipt:
                if receipt[0] != payload:
                    raise ValueError("Batch ID reused with different payload")
                self.db.execute("COMMIT")
                return False
            first = {}
            for mutation in mutations:
                table = mutation["table"]
                fields = FIELDS[table]
                row_id = mutation["id"]
                key = (table, row_id)
                if key not in first:
                    old = self.db.execute(
                        f"SELECT * FROM {table} WHERE id=?", (row_id,)
                    ).fetchone()
                    first[key] = dict(old) if old else None
                after = mutation["row"]
                if after is None:
                    self.db.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
                else:
                    if set(after) != set(fields) or after["id"] != row_id:
                        raise ValueError("Full row with matching ID required")
                    self.db.execute(
                        f"INSERT OR REPLACE INTO {table} VALUES "
                        f"({','.join('?' for _ in fields)})",
                        tuple(after[f] for f in fields),
                    )
            changes = []
            for (table, row_id), before in first.items():
                row = self.db.execute(
                    f"SELECT * FROM {table} WHERE id=?", (row_id,)
                ).fetchone()
                after = dict(row) if row else None
                if before != after:
                    changes.append({
                        "table": table, "id": row_id,
                        "before": before, "after": after,
                    })
            maintainer.maintain(self.db, self.modes, changes)
            if fail_after_hook:
                raise RuntimeError("Injected power loss before commit")
            self.db.execute(
                "INSERT INTO receipts VALUES (?,?)", (batch_id, payload)
            )
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def snapshot(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM rollup")]
