"""Account-local contributions with invertible totals and indexed extrema."""
import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence


def _sql(mode: str, local: bool) -> str:
    join = "JOIN" if mode == "inner" else "LEFT JOIN"
    band = "r.band" if mode == "rated" else "NULL"
    rate = "LEFT JOIN rates r ON t.segment=r.segment" if mode == "rated" else ""
    where = "WHERE o.account=?" if local else ""
    return f"""
        SELECT o.account,o.day,t.segment,{band},
               COUNT(*),COUNT(o.cents),SUM(o.cents),MIN(o.cents),MAX(o.cents)
        FROM orders o {join} tags t ON o.account=t.account {rate}
        {where}
        GROUP BY o.account,o.day,t.segment,{band}
    """


def _key(mode, day, segment, band):
    return json.dumps([mode, day, segment, band], ensure_ascii=True,
                      separators=(",", ":"))


def _insert_part(db, mode, row):
    account, day, segment, band, count, priced, total, low, high = row
    bucket = _key(mode, day, segment, band)
    db.execute(
        "INSERT INTO aux_parts VALUES (?,?,?,?,?,?,?)",
        (account, bucket, count, priced, total, low, high),
    )
    return bucket, (count, priced, total or 0, 1), low, high


def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS aux_parts (
            account TEXT NOT NULL, bucket TEXT NOT NULL,
            row_count INTEGER NOT NULL, amount_count INTEGER NOT NULL,
            total_cents INTEGER, min_cents INTEGER, max_cents INTEGER,
            PRIMARY KEY(account,bucket)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS aux_parts_min
        ON aux_parts(bucket,min_cents)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS aux_parts_max
        ON aux_parts(bucket,max_cents)
    """)
    db.execute("DELETE FROM aux_parts")
    db.execute("DELETE FROM rollup")
    totals = {}
    for mode in modes:
        for row in db.execute(_sql(mode, False)).fetchall():
            bucket, numbers, low, high = _insert_part(db, mode, row)
            state = totals.setdefault(bucket, [0, 0, 0, 0, None, None])
            for index, number in enumerate(numbers):
                state[index] += number
            if low is not None:
                state[4] = low if state[4] is None else min(state[4], low)
                state[5] = high if state[5] is None else max(state[5], high)
    for bucket, (count, priced, total, accounts, low, high) in totals.items():
        db.execute(
            "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*json.loads(bucket), count, priced,
             total if priced else None, accounts, low, high),
        )


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    affected = set()
    segments = set()
    for change in changes:
        for image in (change["before"], change["after"]):
            if image is None:
                continue
            if change["table"] in ("orders", "tags"):
                affected.add(image["account"])
            elif "rated" in modes and image["segment"] is not None:
                segments.add(image["segment"])
    for segment in segments:
        affected.update(
            row[0] for row in db.execute(
                "SELECT DISTINCT account FROM tags WHERE segment=?", (segment,)
            )
        )
    delta = defaultdict(lambda: [0, 0, 0, 0])
    for account in affected:
        old = db.execute(
            "SELECT bucket,row_count,amount_count,total_cents "
            "FROM aux_parts WHERE account=?", (account,)
        ).fetchall()
        for bucket, count, priced, total in old:
            for index, number in enumerate((count, priced, total or 0, 1)):
                delta[bucket][index] -= number
        db.execute("DELETE FROM aux_parts WHERE account=?", (account,))
        for mode in modes:
            for row in db.execute(_sql(mode, True), (account,)).fetchall():
                bucket, numbers, _, _ = _insert_part(db, mode, row)
                for index, number in enumerate(numbers):
                    delta[bucket][index] += number
    for bucket, difference in delta.items():
        key = json.loads(bucket)
        old = db.execute(
            "SELECT row_count,amount_count,total_cents,account_count FROM rollup "
            "WHERE mode=? AND day IS ? AND segment IS ? AND band IS ?", key
        ).fetchone()
        before = (old[0], old[1], old[2] or 0, old[3]) if old else (0, 0, 0, 0)
        count, priced, total, accounts = [
            number + change for number, change in zip(before, difference)
        ]
        db.execute(
            "DELETE FROM rollup WHERE mode=? "
            "AND day IS ? AND segment IS ? AND band IS ?", key
        )
        if count == 0:
            if (priced, total, accounts) != (0, 0, 0):
                raise RuntimeError("Inconsistent empty bucket")
            continue
        low = db.execute(
            "SELECT min_cents FROM aux_parts "
            "WHERE bucket=? AND min_cents IS NOT NULL "
            "ORDER BY min_cents LIMIT 1", (bucket,)
        ).fetchone()
        high = db.execute(
            "SELECT max_cents FROM aux_parts "
            "WHERE bucket=? AND max_cents IS NOT NULL "
            "ORDER BY max_cents DESC LIMIT 1", (bucket,)
        ).fetchone()
        db.execute(
            "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*key, count, priced, total if priced else None, accounts,
             low[0] if low else None, high[0] if high else None),
        )

