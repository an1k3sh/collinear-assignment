"""Account-local contributions with invertible totals and indexed extrema."""
import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence


def _sql(mode: str, local: bool) -> str:
    join = "JOIN" if mode == "inner" else "LEFT JOIN"
    rated = mode in ("rated", "household")
    band = "r.band" if rated else "NULL"
    rate = "LEFT JOIN rates r ON t.segment=r.segment" if rated else ""
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
    return bucket, (count, priced, total or 0), low, high


def _identity(db, account):
    row = db.execute(
        "SELECT component FROM aux_identity WHERE account=?", (account,)
    ).fetchone()
    return row[0] if row else account


def _support(db, bucket, identity, change):
    row = db.execute(
        "SELECT support FROM aux_support WHERE bucket=? AND identity=?",
        (bucket, identity),
    ).fetchone()
    old = row[0] if row else 0
    new = old + change
    if new < 0:
        raise RuntimeError("Negative household support")
    if new:
        db.execute(
            "INSERT OR REPLACE INTO aux_support VALUES (?,?,?)",
            (bucket, identity, new),
        )
    else:
        db.execute(
            "DELETE FROM aux_support WHERE bucket=? AND identity=?",
            (bucket, identity),
        )
    return int(new > 0) - int(old > 0)


def _neighbors(db, account):
    return {
        row[0] for row in db.execute(
            "SELECT right_account FROM links WHERE left_account=? "
            "UNION SELECT left_account FROM links WHERE right_account=?",
            (account, account),
        )
    }


def _components(adjacency):
    remaining = set(adjacency)
    while remaining:
        seed = next(iter(remaining))
        component = {seed}
        pending = [seed]
        while pending:
            node = pending.pop()
            for neighbor in adjacency[node] - component:
                component.add(neighbor)
                pending.append(neighbor)
        remaining.difference_update(component)
        yield component


def _repartition(db, endpoints):
    vertices = set(endpoints)
    old_components = {_identity(db, account) for account in endpoints}
    for component in old_components:
        vertices.update(
            row[0] for row in db.execute(
                "SELECT account FROM aux_identity WHERE component=?", (component,)
            )
        )
    pending = list(vertices)
    adjacency = {}
    while pending:
        node = pending.pop()
        neighbors = _neighbors(db, node)
        adjacency[node] = neighbors
        for neighbor in neighbors - vertices:
            vertices.add(neighbor)
            pending.append(neighbor)
    old = {account: _identity(db, account) for account in vertices}
    for component in _components(adjacency):
        representative = min(component)
        db.executemany(
            "INSERT OR REPLACE INTO aux_identity VALUES (?,?)",
            ((account, representative) for account in component),
        )
    return old


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
    db.execute("""
        CREATE TABLE IF NOT EXISTS aux_support (
            bucket TEXT NOT NULL, identity TEXT NOT NULL,
            support INTEGER NOT NULL CHECK(support > 0),
            PRIMARY KEY(bucket,identity)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS aux_identity (
            account TEXT PRIMARY KEY, component TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS aux_identity_component
        ON aux_identity(component)
    """)
    db.execute("DELETE FROM aux_parts")
    db.execute("DELETE FROM aux_support")
    db.execute("DELETE FROM aux_identity")
    db.execute("DELETE FROM rollup")
    if "household" in modes:
        adjacency = defaultdict(set)
        for account, in db.execute("SELECT DISTINCT account FROM orders"):
            adjacency[account]
        for left, right in db.execute(
            "SELECT left_account,right_account FROM links"
        ):
            adjacency[left].add(right)
            adjacency[right].add(left)
        for component in _components(adjacency):
            representative = min(component)
            db.executemany(
                "INSERT INTO aux_identity VALUES (?,?)",
                ((account, representative) for account in component),
            )
    totals = {}
    for mode in modes:
        for row in db.execute(_sql(mode, False)).fetchall():
            bucket, numbers, low, high = _insert_part(db, mode, row)
            identity = _identity(db, row[0]) if mode == "household" else row[0]
            distinct_change = _support(db, bucket, identity, 1)
            state = totals.setdefault(bucket, [0, 0, 0, 0, None, None])
            for index, number in enumerate((*numbers, distinct_change)):
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
    endpoints = set()
    for change in changes:
        for image in (change["before"], change["after"]):
            if image is None:
                continue
            if change["table"] in ("orders", "tags"):
                affected.add(image["account"])
            elif (change["table"] == "rates"
                  and any(mode in modes for mode in ("rated", "household"))
                  and image["segment"] is not None):
                segments.add(image["segment"])
            elif change["table"] == "links" and "household" in modes:
                endpoints.update((image["left_account"], image["right_account"]))
    for segment in segments:
        affected.update(
            row[0] for row in db.execute(
                "SELECT DISTINCT account FROM tags WHERE segment=?", (segment,)
            )
        )
    old_identities = _repartition(db, endpoints) if endpoints else {}
    affected.update(old_identities)
    if "household" in modes:
        for account in affected:
            db.execute(
                "INSERT OR IGNORE INTO aux_identity VALUES (?,?)",
                (account, account),
            )
    delta = defaultdict(lambda: [0, 0, 0, 0])
    for account in affected:
        old = db.execute(
            "SELECT bucket,row_count,amount_count,total_cents "
            "FROM aux_parts WHERE account=?", (account,)
        ).fetchall()
        for bucket, count, priced, total in old:
            household = json.loads(bucket)[0] == "household"
            identity = (
                old_identities.get(account, _identity(db, account))
                if household else account
            )
            distinct_change = _support(db, bucket, identity, -1)
            for index, number in enumerate((count, priced, total or 0)):
                delta[bucket][index] -= number
            delta[bucket][3] += distinct_change
        db.execute("DELETE FROM aux_parts WHERE account=?", (account,))
        for mode in modes:
            for row in db.execute(_sql(mode, True), (account,)).fetchall():
                bucket, numbers, _, _ = _insert_part(db, mode, row)
                identity = _identity(db, account) if mode == "household" else account
                distinct_change = _support(db, bucket, identity, 1)
                for index, number in enumerate((*numbers, distinct_change)):
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
