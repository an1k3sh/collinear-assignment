"""Current projection: a day-based invalidation implementation."""
import sqlite3
from collections.abc import Sequence


def query(mode: str) -> str:
    join = "JOIN" if mode == "inner" else "LEFT JOIN"
    return f"""
        SELECT ?, o.day, t.segment, NULL,
               COUNT(*), COUNT(o.cents), SUM(o.cents),
               COUNT(DISTINCT o.account), MIN(o.cents), MAX(o.cents)
        FROM orders o {join} tags t ON o.account=t.account
        WHERE o.day IS ?
        GROUP BY o.day,t.segment
    """


def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    db.execute("DELETE FROM rollup")
    days = [r[0] for r in db.execute("SELECT DISTINCT day FROM orders")]
    for mode in modes:
        for day in days:
            db.execute("INSERT INTO rollup " + query(mode), (mode, day))


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    days = {
        c["after"]["day"] for c in changes
        if c["table"] == "orders" and c["after"] is not None
    }
    for mode in modes:
        for day in days:
            db.execute("DELETE FROM rollup WHERE mode=? AND day IS ?", (mode, day))
            db.execute("INSERT INTO rollup " + query(mode), (mode, day))

