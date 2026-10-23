"""Incremental projection for the cohort board.

Design (see REPAIR_REPORT.md):

* Every report row is a sum of independent per-account *contributions*,
  because joins are on ``account`` and every metric except
  ``account_count`` is additive across accounts (MIN/MAX are handled via
  an index).  ``aux_contrib`` stores one row per (mode, group, account)
  that has at least one joined row.
* ``maintain`` derives the set of affected accounts from the change
  images, recomputes only those accounts' contributions from the final
  source state (indexed by account), diffs them against the stored
  contributions, and applies the deltas to ``rollup``.  Group MIN/MAX are
  re-read from ``aux_contrib`` through (group, value) indexes, so work is
  logarithmic in group size, never a day/group scan.
"""
import json
import sqlite3
from collections.abc import Sequence

AUX_VERSION = "1"
SUPPORTED_MODES = ("inner", "outer")
_I64_MIN, _I64_MAX = -(1 << 63), (1 << 63) - 1

_AUX_DDL = (
    """CREATE TABLE IF NOT EXISTS aux_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    # sm has no declared type: per-account partial sums that do not fit in
    # 64 bits are stored as decimal TEXT (the reported group sums do fit).
    """CREATE TABLE IF NOT EXISTS aux_contrib (
        mode TEXT NOT NULL, day TEXT, segment TEXT, band TEXT,
        account TEXT NOT NULL,
        rows INTEGER NOT NULL, nn INTEGER NOT NULL, sm,
        mn INTEGER, mx INTEGER)""",
    "CREATE INDEX IF NOT EXISTS aux_contrib_account "
    "ON aux_contrib(account, mode)",
    "CREATE INDEX IF NOT EXISTS aux_contrib_min "
    "ON aux_contrib(mode, day, segment, band, mn)",
    "CREATE INDEX IF NOT EXISTS aux_contrib_max "
    "ON aux_contrib(mode, day, segment, band, mx)",
)

_GROUP = "mode=? AND day IS ? AND segment IS ? AND band IS ?"


def _check_modes(modes: Sequence[str]) -> tuple[str, ...]:
    modes = tuple(modes)
    unknown = [m for m in modes if m not in SUPPORTED_MODES]
    if unknown:
        raise NotImplementedError(f"Report modes not implemented: {unknown}")
    return modes


def _to_db(value: int):
    return value if _I64_MIN <= value <= _I64_MAX else str(value)


def _from_db(value) -> int:
    return 0 if value is None else int(value)


# --------------------------------------------------------------------------
# Per-account contribution model
# --------------------------------------------------------------------------

def _day_stats(rows):
    """[(day, cents)] -> {day: [n, nn, sum, min, max]}"""
    stats = {}
    for day, cents in rows:
        s = stats.get(day)
        if s is None:
            s = stats[day] = [0, 0, 0, None, None]
        s[0] += 1
        if cents is not None:
            s[1] += 1
            s[2] += cents
            s[3] = cents if s[3] is None or cents < s[3] else s[3]
            s[4] = cents if s[4] is None or cents > s[4] else s[4]
    return stats


def _contribs(mode, day_stats, seg_counts):
    """Contribution of one account: {(day, segment, band): (rows, nn, sm, mn, mx)}.

    For ``inner`` an account's joined rows in group (d, s) are its orders on
    day d crossed with its tags of segment s.  ``outer`` (LEFT JOIN tags) is
    identical except that an account with no tag rows keeps each order once
    with t.segment NULL; it shares the NULL-segment group with accounts whose
    tags have a NULL segment, exactly as SQL GROUP BY does.
    """
    out = {}
    if mode == "outer" and not seg_counts:
        seg_counts = {None: 1}
    if mode in ("inner", "outer"):
        for day, (n, nn, sm, mn, mx) in day_stats.items():
            for seg, m in seg_counts.items():
                out[(day, seg, None)] = (n * m, nn * m, sm * m, mn, mx)
        return out
    raise NotImplementedError(mode)


def _account_contribs(db, mode, account):
    day_stats = _day_stats(
        db.execute("SELECT day, cents FROM orders WHERE account=?", (account,))
    )
    if not day_stats:
        return {}
    seg_counts = dict(db.execute(
        "SELECT segment, COUNT(*) FROM tags WHERE account=? GROUP BY segment",
        (account,),
    ))
    return _contribs(mode, day_stats, seg_counts)


# --------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------

def _ensure_aux(db):
    for ddl in _AUX_DDL:
        db.execute(ddl)


def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    modes = _check_modes(modes)
    _ensure_aux(db)
    db.execute("DELETE FROM rollup")
    db.execute("DELETE FROM aux_contrib")

    orders = {}
    for account, day, cents in db.execute(
        "SELECT account, day, cents FROM orders"
    ):
        orders.setdefault(account, []).append((day, cents))
    tags = {}
    for account, segment, m in db.execute(
        "SELECT account, segment, COUNT(*) FROM tags GROUP BY account, segment"
    ):
        tags.setdefault(account, {})[segment] = m

    for mode in modes:
        groups = {}
        contrib_rows = []
        for account, rows in orders.items():
            contribs = _contribs(mode, _day_stats(rows), tags.get(account, {}))
            for key, (n, nn, sm, mn, mx) in contribs.items():
                contrib_rows.append(
                    (mode, *key, account, n, nn, _to_db(sm), mn, mx))
                g = groups.get(key)
                if g is None:
                    g = groups[key] = [0, 0, 0, 0, None, None]
                g[0] += n
                g[1] += nn
                g[2] += sm
                g[3] += 1
                if mn is not None and (g[4] is None or mn < g[4]):
                    g[4] = mn
                if mx is not None and (g[5] is None or mx > g[5]):
                    g[5] = mx
        db.executemany(
            "INSERT INTO aux_contrib (mode, day, segment, band, account, "
            "rows, nn, sm, mn, mx) VALUES (?,?,?,?,?,?,?,?,?,?)",
            contrib_rows,
        )
        db.executemany(
            "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (mode, *key, n, nn, sm if nn else None, acc, mn, mx)
                for key, (n, nn, sm, acc, mn, mx) in groups.items()
            ],
        )

    db.execute(
        "INSERT OR REPLACE INTO aux_meta VALUES ('state', ?)",
        (json.dumps({"version": AUX_VERSION, "modes": list(modes)}),),
    )


def _aux_current(db, modes) -> bool:
    try:
        row = db.execute("SELECT value FROM aux_meta WHERE key='state'").fetchone()
    except sqlite3.OperationalError:  # aux schema absent (pre-repair database)
        return False
    return row is not None and json.loads(row[0]) == {
        "version": AUX_VERSION, "modes": list(modes)}


def _affected_accounts(changes):
    accounts = set()
    for change in changes:
        if change["table"] in ("orders", "tags"):
            for image in (change["before"], change["after"]):
                if image is not None:
                    accounts.add(image["account"])
    return accounts


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    modes = _check_modes(modes)
    if not _aux_current(db, modes):
        # One-time migration of a database whose auxiliary state predates
        # this implementation; never taken on an already-repaired database.
        bootstrap(db, modes)
        return
    accounts = _affected_accounts(changes)
    if not accounts:
        return
    for mode in modes:
        _maintain_mode(db, mode, accounts)


def _maintain_mode(db, mode, accounts):
    deltas = {}  # group key -> [d_rows, d_nn, d_sum, d_accounts]
    for account in accounts:
        new = _account_contribs(db, mode, account)
        old = {}
        for rowid, day, seg, band, n, nn, sm, mn, mx in db.execute(
            "SELECT rowid, day, segment, band, rows, nn, sm, mn, mx "
            "FROM aux_contrib WHERE account=? AND mode=?",
            (account, mode),
        ):
            old[(day, seg, band)] = (rowid, (n, nn, _from_db(sm), mn, mx))
        for key in old.keys() | new.keys():
            before = old.get(key)
            after = new.get(key)
            if before is not None and before[1] == after:
                continue
            d = deltas.setdefault(key, [0, 0, 0, 0])
            if before is not None:
                rowid, (n, nn, sm, _, _) = before
                d[0] -= n
                d[1] -= nn
                d[2] -= sm
                d[3] -= 1
                if after is None:
                    db.execute("DELETE FROM aux_contrib WHERE rowid=?", (rowid,))
            if after is not None:
                n, nn, sm, mn, mx = after
                d[0] += n
                d[1] += nn
                d[2] += sm
                d[3] += 1
                if before is None:
                    db.execute(
                        "INSERT INTO aux_contrib (mode, day, segment, band, "
                        "account, rows, nn, sm, mn, mx) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (mode, *key, account, n, nn, _to_db(sm), mn, mx),
                    )
                else:
                    db.execute(
                        "UPDATE aux_contrib SET rows=?, nn=?, sm=?, mn=?, mx=? "
                        "WHERE rowid=?",
                        (n, nn, _to_db(sm), mn, mx, before[0]),
                    )
    for key, d in deltas.items():
        _apply_group(db, mode, key, d)


def _apply_group(db, mode, key, delta):
    params = (mode, *key)
    row = db.execute(
        f"SELECT rowid, row_count, amount_count, total_cents, account_count "
        f"FROM rollup WHERE {_GROUP}",
        params,
    ).fetchone()
    if row is None:
        rowid, n, nn, sm, acc = None, 0, 0, 0, 0
    else:
        rowid, n, nn, sm, acc = row
    n += delta[0]
    nn += delta[1]
    sm = _from_db(sm) + delta[2]
    acc += delta[3]
    if n == 0:
        if rowid is not None:
            db.execute("DELETE FROM rollup WHERE rowid=?", (rowid,))
        return
    mn = db.execute(
        f"SELECT MIN(mn) FROM aux_contrib WHERE {_GROUP}", params
    ).fetchone()[0]
    mx = db.execute(
        f"SELECT MAX(mx) FROM aux_contrib WHERE {_GROUP}", params
    ).fetchone()[0]
    values = (n, nn, sm if nn else None, acc, mn, mx)
    if rowid is None:
        db.execute("INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (*params, *values))
    else:
        db.execute(
            "UPDATE rollup SET row_count=?, amount_count=?, total_cents=?, "
            "account_count=?, min_cents=?, max_cents=? WHERE rowid=?",
            (*values, rowid),
        )
