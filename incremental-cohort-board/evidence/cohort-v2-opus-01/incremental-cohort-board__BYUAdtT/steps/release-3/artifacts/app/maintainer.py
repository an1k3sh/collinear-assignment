"""Incremental projection for the cohort board.

Design (see REPAIR_REPORT.md):

* Every report row is a sum of independent per-account *contributions*,
  because all joins hang off ``orders.account`` and every metric except
  ``account_count`` is additive across accounts (MIN/MAX are handled via
  an index).  ``aux_contrib`` stores one row per (mode, group, account)
  that has at least one joined row.
* ``maintain`` derives the set of affected accounts from the change
  images, recomputes only those accounts' contributions from the final
  source state (indexed by account / segment), diffs them against the
  stored contributions, and applies the deltas to ``rollup``.  Group
  MIN/MAX are re-read from ``aux_contrib`` through (group, value) indexes,
  so work is logarithmic in group size, never a day/group scan.
"""
import json
import sqlite3
from collections.abc import Sequence

# Version of the aux table layout.  Index additions that are only used by
# newly added modes do not bump it: adding a mode always runs bootstrap,
# which creates them.
AUX_VERSION = "1"
SUPPORTED_MODES = ("inner", "outer", "rated")
RATE_MODES = frozenset({"rated"})  # modes whose rows depend on `rates`
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
    # release 3: accounts currently contributing under a segment, used to
    # find the (order-bearing) accounts affected by a rate change.
    "CREATE INDEX IF NOT EXISTS aux_contrib_segment "
    "ON aux_contrib(segment, account)",
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


def _multipliers(mode, seg_counts, seg_bands):
    """{(segment, band): joined rows per order} for one account.

    * ``inner``: one entry per tag segment, multiplicity = tag rows.
    * ``outer``: as inner, but an untagged account keeps each order once
      with t.segment NULL (it shares that group with NULL-segment tags).
    * ``rated``: outer, then LEFT JOIN rates on ``t.segment=r.segment``.
      Multiplicity = tag rows * rate rows per band.  A NULL segment never
      matches (``=`` is not NULL-safe) and a segment without rate rows
      keeps its rows with band NULL; both share the band-NULL group with
      rate rows whose band is NULL.
    """
    if mode != "inner" and not seg_counts:
        seg_counts = {None: 1}
    if mode in ("inner", "outer"):
        return {(seg, None): m for seg, m in seg_counts.items()}
    if mode == "rated":
        out = {}
        for seg, m in seg_counts.items():
            bands = seg_bands.get(seg) if seg is not None else None
            if bands:
                for band, k in bands.items():
                    out[(seg, band)] = m * k
            else:
                out[(seg, None)] = m
        return out
    raise NotImplementedError(mode)


def _contribs(mode, day_stats, seg_counts, seg_bands):
    """Contribution of one account: {(day, segment, band): (rows, nn, sm, mn, mx)}."""
    mult = _multipliers(mode, seg_counts, seg_bands)
    return {
        (day, seg, band): (n * m, nn * m, sm * m, mn, mx)
        for day, (n, nn, sm, mn, mx) in day_stats.items()
        for (seg, band), m in mult.items()
    }


def _load_account(db, account, need_rates):
    day_stats = _day_stats(
        db.execute("SELECT day, cents FROM orders WHERE account=?", (account,))
    )
    if not day_stats:
        return None
    seg_counts = dict(db.execute(
        "SELECT segment, COUNT(*) FROM tags WHERE account=? GROUP BY segment",
        (account,),
    ))
    seg_bands = {}
    if need_rates:
        for seg in seg_counts:
            if seg is not None:
                seg_bands[seg] = dict(db.execute(
                    "SELECT band, COUNT(*) FROM rates WHERE segment=? "
                    "GROUP BY band", (seg,)))
    return day_stats, seg_counts, seg_bands


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
    seg_bands = {}
    for segment, band, k in db.execute(
        "SELECT segment, band, COUNT(*) FROM rates "
        "WHERE segment IS NOT NULL GROUP BY segment, band"
    ):
        seg_bands.setdefault(segment, {})[band] = k

    for mode in modes:
        groups = {}
        contrib_rows = []
        for account, rows in orders.items():
            contribs = _contribs(
                mode, _day_stats(rows), tags.get(account, {}), seg_bands)
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


def _affected(db, modes, changes):
    """-> (accounts needing all modes, accounts needing only rate modes)."""
    accounts = set()
    segments = set()
    for change in changes:
        table = change["table"]
        for image in (change["before"], change["after"]):
            if image is None:
                continue
            if table in ("orders", "tags"):
                accounts.add(image["account"])
            elif table == "rates" and image["segment"] is not None:
                segments.add(image["segment"])
    rate_accounts = set()
    if segments and RATE_MODES.intersection(modes):
        # Accounts not touched by order/tag changes have up-to-date
        # contributions, which exist under segment s exactly when the
        # account has orders and a tag with segment s.
        for seg in segments:
            rate_accounts.update(r[0] for r in db.execute(
                "SELECT DISTINCT account FROM aux_contrib WHERE segment=?",
                (seg,)))
    return accounts, rate_accounts - accounts


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    modes = _check_modes(modes)
    if not _aux_current(db, modes):
        # One-time migration of a database whose auxiliary state predates
        # this implementation; never taken on an already-repaired database.
        bootstrap(db, modes)
        return
    accounts, rate_accounts = _affected(db, modes, changes)
    if not accounts and not rate_accounts:
        return
    rate_modes = tuple(m for m in modes if m in RATE_MODES)
    need_rates = bool(rate_modes)
    deltas = {mode: {} for mode in modes}
    for account in accounts:
        _refresh_account(db, account, modes, need_rates, deltas)
    for account in rate_accounts:
        _refresh_account(db, account, rate_modes, True, deltas)
    for mode in modes:
        for key, d in deltas[mode].items():
            _apply_group(db, mode, key, d)


def _refresh_account(db, account, modes, need_rates, deltas):
    loaded = _load_account(db, account, need_rates)
    for mode in modes:
        new = _contribs(mode, *loaded) if loaded is not None else {}
        old = {}
        for rowid, day, seg, band, n, nn, sm, mn, mx in db.execute(
            "SELECT rowid, day, segment, band, rows, nn, sm, mn, mx "
            "FROM aux_contrib WHERE account=? AND mode=?",
            (account, mode),
        ):
            old[(day, seg, band)] = (rowid, (n, nn, _from_db(sm), mn, mx))
        mode_deltas = deltas[mode]
        for key in old.keys() | new.keys():
            before = old.get(key)
            after = new.get(key)
            if before is not None and before[1] == after:
                continue
            d = mode_deltas.setdefault(key, [0, 0, 0, 0])
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
