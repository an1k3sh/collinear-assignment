"""Incremental cohort-board projection.

Design (see REPAIR_REPORT.md):

* ``aux_cell`` holds, per (mode, account, output group), that account's exact
  contribution to the group: joined row count, non-NULL amount count, raw sum
  of non-NULL amounts (0 when none), and min/max non-NULL amount.  An account
  owns at most one cell per group, so a group's ``account_count`` is its
  number of cells.
* ``maintain`` recomputes the cells of every account touched by the batch
  (both before and after images), using the ``orders_account`` and
  ``tags_account`` indexes.  The per-group difference between old and new
  cells is applied to the stored ``rollup`` row as an exact delta, and the
  group's MIN/MAX is re-read with one index seek each.  Work is proportional
  to the touched accounts' rows and groups, never to group or day size.
* All state lives in the same SQLite database inside the host transaction.
"""
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence

SUPPORTED_MODES = ("inner",)

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1

_AUX_DDL = (
    """CREATE TABLE IF NOT EXISTS aux_cell (
        mode TEXT NOT NULL,
        account TEXT NOT NULL,
        day TEXT,
        segment TEXT,
        band TEXT,
        n INTEGER NOT NULL,
        c INTEGER NOT NULL,
        s,
        mn INTEGER,
        mx INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS aux_cell_account ON aux_cell(mode, account)",
    "CREATE INDEX IF NOT EXISTS aux_cell_min "
    "ON aux_cell(mode, day, segment, band, mn)",
    "CREATE INDEX IF NOT EXISTS aux_cell_max "
    "ON aux_cell(mode, day, segment, band, mx)",
)


def _enc(value: int):
    # Per-cell sums are multiplied by tag multiplicity in Python; keep them
    # exact even if an intermediate value leaves the signed 64-bit range.
    return value if _INT64_MIN <= value <= _INT64_MAX else str(value)


def _check_modes(modes: Sequence[str]) -> None:
    unknown = [m for m in modes if m not in SUPPORTED_MODES]
    if unknown:
        raise NotImplementedError(f"Unsupported report modes: {unknown}")


def _ensure_aux(db: sqlite3.Connection) -> None:
    for statement in _AUX_DDL:
        db.execute(statement)


def _cross(day_stats, seg_counts):
    """Combine per-day order stats with per-segment tag multiplicity."""
    cells = {}
    for day, (n, c, s, mn, mx) in day_stats.items():
        for segment, m in seg_counts.items():
            cells[(day, segment, None)] = (n * m, c * m, s * m, mn, mx)
    return cells


def _inner_cells_for_account(db: sqlite3.Connection, account: str) -> dict:
    day_stats = {
        day: (n, c, s or 0, mn, mx)
        for day, n, c, s, mn, mx in db.execute(
            "SELECT day, COUNT(*), COUNT(cents), SUM(cents), "
            "MIN(cents), MAX(cents) FROM orders WHERE account=? GROUP BY day",
            (account,),
        )
    }
    if not day_stats:
        return {}
    seg_counts = Counter(
        seg for (seg,) in db.execute(
            "SELECT segment FROM tags WHERE account=?", (account,)
        )
    )
    return _cross(day_stats, seg_counts)


def _inner_cells_all(db: sqlite3.Connection) -> dict:
    """Full-scan variant used only by bootstrap: account -> cells."""
    orders: dict[str, dict] = {}
    for account, day, n, c, s, mn, mx in db.execute(
        "SELECT account, day, COUNT(*), COUNT(cents), SUM(cents), "
        "MIN(cents), MAX(cents) FROM orders GROUP BY account, day"
    ):
        orders.setdefault(account, {})[day] = (n, c, s or 0, mn, mx)
    tags: dict[str, Counter] = {}
    for account, segment in db.execute("SELECT account, segment FROM tags"):
        tags.setdefault(account, Counter())[segment] += 1
    return {
        account: _cross(day_stats, tags[account])
        for account, day_stats in orders.items()
        if account in tags
    }


_ACCOUNT_CELLS = {"inner": _inner_cells_for_account}
_ALL_CELLS = {"inner": _inner_cells_all}


def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    _check_modes(modes)
    _ensure_aux(db)
    db.execute("DELETE FROM aux_cell")
    db.execute("DELETE FROM rollup")
    for mode in modes:
        groups: dict[tuple, list] = {}
        cell_rows = []
        for account, cells in _ALL_CELLS[mode](db).items():
            for key, (n, c, s, mn, mx) in cells.items():
                cell_rows.append((mode, account, *key, n, c, _enc(s), mn, mx))
                g = groups.get(key)
                if g is None:
                    groups[key] = [n, c, s, 1, mn, mx]
                    continue
                g[0] += n
                g[1] += c
                g[2] += s
                g[3] += 1
                if mn is not None and (g[4] is None or mn < g[4]):
                    g[4] = mn
                if mx is not None and (g[5] is None or mx > g[5]):
                    g[5] = mx
        db.executemany(
            "INSERT INTO aux_cell VALUES (?,?,?,?,?,?,?,?,?,?)", cell_rows
        )
        db.executemany(
            "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (mode, *key, n, c, s if c else None, a, mn, mx)
                for key, (n, c, s, a, mn, mx) in groups.items()
            ],
        )


def _touched_accounts(changes: Iterable[dict]) -> set[str]:
    accounts = set()
    for change in changes:
        if change["table"] not in ("orders", "tags"):
            continue
        for image in (change["before"], change["after"]):
            if image is not None:
                accounts.add(image["account"])
    return accounts


def _refresh_accounts(db, mode: str, accounts: Iterable[str]) -> None:
    compute = _ACCOUNT_CELLS[mode]
    # group key -> [d_rows, d_amounts, d_sum, d_accounts]
    deltas: dict[tuple, list] = {}
    for account in sorted(accounts):
        old = {
            (day, seg, band): (rowid, (n, c, int(s), mn, mx))
            for rowid, day, seg, band, n, c, s, mn, mx in db.execute(
                "SELECT rowid, day, segment, band, n, c, s, mn, mx "
                "FROM aux_cell WHERE mode=? AND account=?",
                (mode, account),
            )
        }
        new = compute(db, account)
        for key in old.keys() | new.keys():
            rowid, before = old.get(key, (None, None))
            after = new.get(key)
            if before == after:
                continue
            d = deltas.setdefault(key, [0, 0, 0, 0])
            if before is not None:
                d[0] -= before[0]
                d[1] -= before[1]
                d[2] -= before[2]
                d[3] -= 1
            if after is not None:
                d[0] += after[0]
                d[1] += after[1]
                d[2] += after[2]
                d[3] += 1
            if after is None:
                db.execute("DELETE FROM aux_cell WHERE rowid=?", (rowid,))
            elif before is None:
                n, c, s, mn, mx = after
                db.execute(
                    "INSERT INTO aux_cell VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (mode, account, *key, n, c, _enc(s), mn, mx),
                )
            else:
                n, c, s, mn, mx = after
                db.execute(
                    "UPDATE aux_cell SET n=?, c=?, s=?, mn=?, mx=? "
                    "WHERE rowid=?",
                    (n, c, _enc(s), mn, mx, rowid),
                )
    for key, (dn, dc, ds, da) in deltas.items():
        _apply_group(db, mode, key, dn, dc, ds, da)


def _apply_group(db, mode, key, dn, dc, ds, da) -> None:
    day, segment, band = key
    where = "mode=? AND day IS ? AND segment IS ? AND band IS ?"
    params = (mode, day, segment, band)
    row = db.execute(
        "SELECT rowid, row_count, amount_count, total_cents, account_count "
        f"FROM rollup WHERE {where}",
        params,
    ).fetchone()
    if row is None:
        rowid, n, c, s, a = None, 0, 0, 0, 0
    else:
        rowid, n, c, s, a = row
    n, c, s, a = n + dn, c + dc, (s or 0) + ds, a + da
    if a <= 0 or n <= 0:
        if rowid is not None:
            db.execute("DELETE FROM rollup WHERE rowid=?", (rowid,))
        return
    mn = db.execute(
        f"SELECT mn FROM aux_cell WHERE {where} AND mn IS NOT NULL "
        "ORDER BY mn LIMIT 1",
        params,
    ).fetchone()
    mx = db.execute(
        f"SELECT mx FROM aux_cell WHERE {where} AND mx IS NOT NULL "
        "ORDER BY mx DESC LIMIT 1",
        params,
    ).fetchone()
    values = (
        n, c, s if c else None, a,
        mn[0] if mn else None, mx[0] if mx else None,
    )
    if rowid is None:
        db.execute(
            "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*params, *values),
        )
    else:
        db.execute(
            "UPDATE rollup SET row_count=?, amount_count=?, total_cents=?, "
            "account_count=?, min_cents=?, max_cents=? WHERE rowid=?",
            (*values, rowid),
        )


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    _check_modes(modes)
    accounts = _touched_accounts(changes)
    if not accounts:
        return
    for mode in modes:
        _refresh_accounts(db, mode, accounts)
