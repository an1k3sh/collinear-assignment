"""Incremental cohort-board projection for the inner, outer and rated reports.

Design (see REPAIR_REPORT.md):

* Cell layer (``aux_cell``).  Both tag joins are keyed only by account, so an
  account's contribution to every (day, segment) group is a pure function of
  its own orders (aggregated by day) and its tag-segment multiplicity.
  ``aux_cell`` stores that contribution per (cell mode, account, group):
  joined row count, non-NULL amount count, raw sum (0 when no amounts) and
  min/max.  An account owns at most one cell per group, so a group's
  ``account_count`` is its number of cells.  Cell modes: ``inner`` (JOIN) and
  ``outer`` (LEFT JOIN: an untagged account counts once under segment NULL).
* Group layer (``aux_group``).  Exact per-(cell mode, day, segment) totals,
  updated by deltas; MIN/MAX re-read by one index seek on ``aux_cell``.
* Publication (``rollup``).  ``inner``/``outer`` rows copy their group.
  ``rated`` rows are derived from the ``outer`` group: rates join on segment
  only, so every account of group (d, s) meets the same band multiset B(s).
  Group (d, s, b) is the (d, s) group with row/amount counts and sum scaled by
  B(s)[b]; DISTINCT accounts and MIN/MAX are unchanged.  B(s) is {NULL: 1}
  when s is NULL (``=`` never matches NULL) or has no rate rows.
* ``maintain`` recomputes cells only for accounts in before/after images of
  order/tag changes, and for rate changes republishes the (day, segment)
  groups of the old/new segments.  All lookups are index seeks; work is
  proportional to touched accounts and affected output groups, never to the
  number of accounts sharing a group.
* All state lives in the same SQLite database inside the host transaction.
"""
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence

SUPPORTED_MODES = ("inner", "outer", "rated")
LAYOUT = "3"

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_NO_BAND = Counter({None: 1})

_AUX_DDL = (
    """CREATE TABLE IF NOT EXISTS aux_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
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
    """CREATE TABLE IF NOT EXISTS aux_group (
        mode TEXT NOT NULL,
        day TEXT,
        segment TEXT,
        n INTEGER NOT NULL,
        c INTEGER NOT NULL,
        s,
        a INTEGER NOT NULL,
        mn INTEGER,
        mx INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS aux_group_key "
    "ON aux_group(mode, segment, day)",
)


def _enc(value: int):
    # Keep auxiliary sums exact even if an intermediate value (sum times tag
    # multiplicity) leaves the signed 64-bit range.
    return value if _INT64_MIN <= value <= _INT64_MAX else str(value)


def _check_modes(modes: Sequence[str]) -> None:
    unknown = [m for m in modes if m not in SUPPORTED_MODES]
    if unknown:
        raise NotImplementedError(f"Unsupported report modes: {unknown}")


def _cell_modes(modes: Sequence[str]) -> list[str]:
    out = []
    if "inner" in modes:
        out.append("inner")
    if "outer" in modes or "rated" in modes:
        out.append("outer")
    return out


def _ensure_aux(db: sqlite3.Connection) -> None:
    for statement in _AUX_DDL:
        db.execute(statement)


def _layout_tag(modes: Sequence[str]) -> str:
    return json.dumps([LAYOUT, sorted(modes)])


def _layout_current(db: sqlite3.Connection, modes: Sequence[str]) -> bool:
    try:
        row = db.execute(
            "SELECT value FROM aux_meta WHERE key='layout'"
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None and row[0] == _layout_tag(modes)


# ---------------------------------------------------------------- cell layer

def _cross(day_stats, seg_counts):
    """Combine per-day order stats with per-segment tag multiplicity."""
    cells = {}
    for day, (n, c, s, mn, mx) in day_stats.items():
        for segment, m in seg_counts.items():
            cells[(day, segment)] = (n * m, c * m, s * m, mn, mx)
    return cells


def _inner_cells(day_stats: dict, seg_counts: Counter) -> dict:
    return _cross(day_stats, seg_counts)


def _outer_cells(day_stats: dict, seg_counts: Counter) -> dict:
    # LEFT JOIN: an account without any tag row keeps each order once with
    # t.segment NULL.  A tag row whose segment is NULL is a real match.
    return _cross(day_stats, seg_counts or _NO_BAND)


_CELLS = {"inner": _inner_cells, "outer": _outer_cells}


def _account_sources(db: sqlite3.Connection, account: str):
    """Indexed reads of one account's orders (by day) and tag multiplicity."""
    day_stats = {
        day: (n, c, s or 0, mn, mx)
        for day, n, c, s, mn, mx in db.execute(
            "SELECT day, COUNT(*), COUNT(cents), SUM(cents), "
            "MIN(cents), MAX(cents) FROM orders WHERE account=? GROUP BY day",
            (account,),
        )
    }
    if not day_stats:
        return {}, Counter()
    seg_counts = Counter(
        seg for (seg,) in db.execute(
            "SELECT segment FROM tags WHERE account=?", (account,)
        )
    )
    return day_stats, seg_counts


def _all_sources(db: sqlite3.Connection):
    """Full-scan variant used only by bootstrap: account -> sources."""
    orders: dict[str, dict] = {}
    for account, day, n, c, s, mn, mx in db.execute(
        "SELECT account, day, COUNT(*), COUNT(cents), SUM(cents), "
        "MIN(cents), MAX(cents) FROM orders GROUP BY account, day"
    ):
        orders.setdefault(account, {})[day] = (n, c, s or 0, mn, mx)
    tags: dict[str, Counter] = {}
    for account, segment in db.execute("SELECT account, segment FROM tags"):
        tags.setdefault(account, Counter())[segment] += 1
    for account, day_stats in orders.items():
        yield account, day_stats, tags.get(account, Counter())


# --------------------------------------------------------------- publication

def _scaled(agg, k: int) -> tuple:
    n, c, s, a, mn, mx = agg
    return (n * k, c * k, s * k if c else None, a, mn, mx)


def _segment_bands(db, segment, cache: dict) -> Counter:
    if segment is None:
        return _NO_BAND
    bands = cache.get(segment)
    if bands is None:
        bands = Counter(
            band for (band,) in db.execute(
                "SELECT band FROM rates WHERE segment=?", (segment,)
            )
        ) or _NO_BAND
        cache[segment] = bands
    return bands


def _publish_plain(db, mode: str, key: tuple, agg) -> None:
    day, segment = key
    db.execute(
        "DELETE FROM rollup WHERE mode=? AND day IS ? AND segment IS ? "
        "AND band IS NULL",
        (mode, day, segment),
    )
    if agg is not None:
        db.execute(
            "INSERT INTO rollup VALUES (?,?,?,NULL,?,?,?,?,?,?)",
            (mode, day, segment, *_scaled(agg, 1)),
        )


def _publish_rated(db, key: tuple, agg, band_cache: dict) -> None:
    day, segment = key
    db.execute(
        "DELETE FROM rollup WHERE mode='rated' AND day IS ? AND segment IS ?",
        (day, segment),
    )
    if agg is None:
        return
    db.executemany(
        "INSERT INTO rollup VALUES ('rated',?,?,?,?,?,?,?,?,?)",
        [
            (day, segment, band, *_scaled(agg, k))
            for band, k in _segment_bands(db, segment, band_cache).items()
        ],
    )


def _read_group(db, mode: str, key: tuple):
    row = db.execute(
        "SELECT n, c, s, a, mn, mx FROM aux_group "
        "WHERE mode=? AND day IS ? AND segment IS ?",
        (mode, *key),
    ).fetchone()
    if row is None:
        return None
    n, c, s, a, mn, mx = row
    return (n, c, int(s), a, mn, mx)


# ----------------------------------------------------------------- bootstrap

def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    _check_modes(modes)
    _ensure_aux(db)
    db.execute("DELETE FROM aux_cell")
    db.execute("DELETE FROM aux_group")
    db.execute("DELETE FROM rollup")
    sources = list(_all_sources(db))
    groups_by_mode: dict[str, dict] = {}
    for cell_mode in _cell_modes(modes):
        cell_fn = _CELLS[cell_mode]
        groups: dict[tuple, list] = {}
        cell_rows = []
        for account, day_stats, seg_counts in sources:
            for key, (n, c, s, mn, mx) in cell_fn(day_stats, seg_counts).items():
                cell_rows.append(
                    (cell_mode, account, *key, None, n, c, _enc(s), mn, mx)
                )
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
            "INSERT INTO aux_group VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (cell_mode, *key, n, c, _enc(s), a, mn, mx)
                for key, (n, c, s, a, mn, mx) in groups.items()
            ],
        )
        groups_by_mode[cell_mode] = groups
    for mode in ("inner", "outer"):
        if mode in modes:
            db.executemany(
                "INSERT INTO rollup VALUES (?,?,?,NULL,?,?,?,?,?,?)",
                [
                    (mode, *key, *_scaled(g, 1))
                    for key, g in groups_by_mode[mode].items()
                ],
            )
    if "rated" in modes:
        rates: dict[str, Counter] = {}
        for segment, band in db.execute(
            "SELECT segment, band FROM rates WHERE segment IS NOT NULL"
        ):
            rates.setdefault(segment, Counter())[band] += 1
        rows = []
        for (day, segment), g in groups_by_mode["outer"].items():
            bands = rates.get(segment, _NO_BAND) if segment is not None \
                else _NO_BAND
            for band, k in bands.items():
                rows.append((day, segment, band, *_scaled(g, k)))
        db.executemany(
            "INSERT INTO rollup VALUES ('rated',?,?,?,?,?,?,?,?,?)", rows
        )
    db.execute(
        "INSERT OR REPLACE INTO aux_meta VALUES ('layout', ?)",
        (_layout_tag(modes),),
    )


# ------------------------------------------------------------------ maintain

def _touched(changes: Iterable[dict]) -> tuple[set, set]:
    accounts, rate_segments = set(), set()
    for change in changes:
        for image in (change["before"], change["after"]):
            if image is None:
                continue
            if change["table"] == "rates":
                if image["segment"] is not None:
                    rate_segments.add(image["segment"])
            else:
                accounts.add(image["account"])
    return accounts, rate_segments


def _refresh_cells(db, cell_mode: str, sources: dict) -> dict:
    """Replace touched accounts' cells; return {group key: new aggregate}."""
    cell_fn = _CELLS[cell_mode]
    # group key -> [d_rows, d_amounts, d_sum, d_accounts]
    deltas: dict[tuple, list] = {}
    for account, (day_stats, seg_counts) in sources.items():
        old = {
            (day, seg): (rowid, (n, c, int(s), mn, mx))
            for rowid, day, seg, n, c, s, mn, mx in db.execute(
                "SELECT rowid, day, segment, n, c, s, mn, mx "
                "FROM aux_cell WHERE mode=? AND account=?",
                (cell_mode, account),
            )
        }
        new = cell_fn(day_stats, seg_counts)
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
                    "INSERT INTO aux_cell VALUES (?,?,?,?,NULL,?,?,?,?,?)",
                    (cell_mode, account, *key, n, c, _enc(s), mn, mx),
                )
            else:
                n, c, s, mn, mx = after
                db.execute(
                    "UPDATE aux_cell SET n=?, c=?, s=?, mn=?, mx=? "
                    "WHERE rowid=?",
                    (n, c, _enc(s), mn, mx, rowid),
                )
    return {
        key: _apply_group(db, cell_mode, key, delta)
        for key, delta in deltas.items()
    }


def _apply_group(db, cell_mode: str, key: tuple, delta: list):
    day, segment = key
    params = (cell_mode, day, segment)
    row = db.execute(
        "SELECT rowid, n, c, s, a FROM aux_group "
        "WHERE mode=? AND day IS ? AND segment IS ?",
        params,
    ).fetchone()
    if row is None:
        rowid, n, c, s, a = None, 0, 0, 0, 0
    else:
        rowid, n, c, s, a = row
        s = int(s)
    dn, dc, ds, da = delta
    n, c, s, a = n + dn, c + dc, s + ds, a + da
    if a <= 0 or n <= 0:
        if rowid is not None:
            db.execute("DELETE FROM aux_group WHERE rowid=?", (rowid,))
        return None
    where = "mode=? AND day IS ? AND segment IS ? AND band IS NULL"
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
    agg = (n, c, s, a, mn[0] if mn else None, mx[0] if mx else None)
    if rowid is None:
        db.execute(
            "INSERT INTO aux_group VALUES (?,?,?,?,?,?,?,?,?)",
            (*params, n, c, _enc(s), a, agg[4], agg[5]),
        )
    else:
        db.execute(
            "UPDATE aux_group SET n=?, c=?, s=?, a=?, mn=?, mx=? "
            "WHERE rowid=?",
            (n, c, _enc(s), a, agg[4], agg[5], rowid),
        )
    return agg


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    _check_modes(modes)
    if not changes:
        return
    if not _layout_current(db, modes):
        # One-time migration of auxiliary state written by an older layout
        # (never taken on a database upgraded by this module).
        bootstrap(db, modes)
        return
    accounts, rate_segments = _touched(changes)
    sources = {a: _account_sources(db, a) for a in sorted(accounts)}
    changed = {
        cell_mode: _refresh_cells(db, cell_mode, sources) if sources else {}
        for cell_mode in _cell_modes(modes)
    }
    for mode in ("inner", "outer"):
        if mode in modes:
            for key, agg in changed[mode].items():
                _publish_plain(db, mode, key, agg)
    if "rated" not in modes:
        return
    groups = dict(changed["outer"])
    for segment in sorted(rate_segments):
        for (day,) in db.execute(
            "SELECT day FROM aux_group WHERE mode='outer' AND segment=?",
            (segment,),
        ).fetchall():
            if (day, segment) not in groups:
                groups[(day, segment)] = _read_group(
                    db, "outer", (day, segment)
                )
    band_cache: dict = {}
    for key, agg in groups.items():
        _publish_rated(db, key, agg, band_cache)
