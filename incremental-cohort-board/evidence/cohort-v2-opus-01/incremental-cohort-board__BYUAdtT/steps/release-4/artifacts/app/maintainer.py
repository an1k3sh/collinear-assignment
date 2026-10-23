"""Incremental projection for the cohort board.

Design (see REPAIR_REPORT.md):

* Every report row is a sum of independent per-account *contributions*,
  because all joins hang off ``orders.account`` and every metric except the
  distinct count is additive across accounts (MIN/MAX are handled via an
  index).  ``aux_contrib`` stores one row per (shape, group, account) that
  has at least one joined row.  A *shape* is the join shape of a mode:
  ``household`` has exactly the joined rows of ``rated`` and shares its
  contributions.
* ``maintain`` derives the affected accounts from the change images,
  recomputes only those accounts' contributions from the final source state
  (indexed by account / segment), diffs them against the stored
  contributions and applies deltas to ``rollup``.  Group MIN/MAX are re-read
  from ``aux_contrib`` through (group, value) indexes, so work is
  logarithmic in group size, never a day/group scan.
* Households: ``aux_comp(account, rep)`` holds the connected component
  representative of every account incident to a link (others are their own
  class).  A link change recomputes only the old components of the changed
  edges' endpoints by searching the final link graph.  ``aux_hh`` counts
  contributing accounts per (group, rep); the household distinct count of a
  group is its number of ``aux_hh`` rows.
"""
import json
import sqlite3
from collections import deque
from collections.abc import Sequence

# Version of the aux table layout.  Tables/indexes only used by newly added
# modes do not bump it: adding a mode always runs bootstrap, which creates
# and fills them.
AUX_VERSION = "1"
SUPPORTED_MODES = ("inner", "outer", "rated", "household")
SHAPE_OF = {"inner": "inner", "outer": "outer",
            "rated": "rated", "household": "rated"}
RATE_SHAPES = frozenset({"rated"})  # shapes whose rows depend on `rates`
HH_SHAPE = "rated"
_I64_MIN, _I64_MAX = -(1 << 63), (1 << 63) - 1

_AUX_DDL = (
    """CREATE TABLE IF NOT EXISTS aux_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    # `mode` holds the shape.  sm has no declared type: per-account partial
    # sums that do not fit in 64 bits are stored as decimal TEXT (the
    # reported group sums do fit).
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
    # release 4: household components and per-group household counters.
    """CREATE TABLE IF NOT EXISTS aux_comp (
        account TEXT PRIMARY KEY, rep TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS aux_comp_rep ON aux_comp(rep)",
    """CREATE TABLE IF NOT EXISTS aux_hh (
        day TEXT, segment TEXT, band TEXT, rep TEXT NOT NULL,
        n INTEGER NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS aux_hh_key "
    "ON aux_hh(day, segment, band, rep)",
)

_GROUP = "mode=? AND day IS ? AND segment IS ? AND band IS ?"
_HH_KEY = "day IS ? AND segment IS ? AND band IS ? AND rep=?"


def _check_modes(modes: Sequence[str]) -> tuple[str, ...]:
    modes = tuple(modes)
    unknown = [m for m in modes if m not in SUPPORTED_MODES]
    if unknown:
        raise NotImplementedError(f"Report modes not implemented: {unknown}")
    return modes


def _shapes(modes):
    out = []
    for mode in modes:
        if SHAPE_OF[mode] not in out:
            out.append(SHAPE_OF[mode])
    return tuple(out)


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


def _multipliers(shape, seg_counts, seg_bands):
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
    if shape != "inner" and not seg_counts:
        seg_counts = {None: 1}
    if shape in ("inner", "outer"):
        return {(seg, None): m for seg, m in seg_counts.items()}
    if shape == "rated":
        out = {}
        for seg, m in seg_counts.items():
            bands = seg_bands.get(seg) if seg is not None else None
            if bands:
                for band, k in bands.items():
                    out[(seg, band)] = m * k
            else:
                out[(seg, None)] = m
        return out
    raise NotImplementedError(shape)


def _contribs(shape, day_stats, seg_counts, seg_bands):
    """Contribution of one account: {(day, segment, band): (rows, nn, sm, mn, mx)}."""
    mult = _multipliers(shape, seg_counts, seg_bands)
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
# Household components
# --------------------------------------------------------------------------

def _all_components(db):
    """Union-find over all links -> {account: rep} for linked accounts."""
    parent = {}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in db.execute("SELECT left_account, right_account FROM links"):
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra  # the root is always the component's least label
    return {x: find(x) for x in parent}


def _update_components(db, changes):
    """Bring aux_comp up to date; -> {account: (old_rep, new_rep)} for
    every account whose class representative changed."""
    pending = deque()
    for change in changes:
        if change["table"] != "links":
            continue
        for image in (change["before"], change["after"]):
            if image is not None:
                pending.append(image["left_account"])
                pending.append(image["right_account"])
    if not pending:
        return {}

    old = {}  # account -> (old rep, had a row in aux_comp)

    def load_old_component(x):
        row = db.execute(
            "SELECT rep FROM aux_comp WHERE account=?", (x,)).fetchone()
        if row is None:
            old[x] = (x, False)
            return
        for (member,) in db.execute(
                "SELECT account FROM aux_comp WHERE rep=?", (row[0],)):
            if member not in old:
                old[member] = (row[0], True)
                pending.append(member)
        old.setdefault(x, (row[0], True))

    for x in list(pending):
        if x not in old:
            load_old_component(x)

    # Final components of every account in the union of old components.
    # A path leaving that union would need an unchanged edge (whose ends
    # share an old component) or a changed edge (whose ends are loaded), so
    # the search stays inside it; loading on demand is only a safeguard.
    new = {}
    linked = {}
    while pending:
        start = pending.popleft()
        if start in new:
            continue
        comp = [start]
        new[start] = None
        stack = [start]
        while stack:
            x = stack.pop()
            neighbours = db.execute(
                "SELECT right_account FROM links WHERE left_account=? "
                "UNION ALL SELECT left_account FROM links WHERE right_account=?",
                (x, x)).fetchall()
            linked[x] = bool(neighbours)
            for (y,) in neighbours:
                if y not in new:
                    if y not in old:
                        load_old_component(y)
                    new[y] = None
                    comp.append(y)
                    stack.append(y)
        rep = min(comp)
        for x in comp:
            new[x] = rep

    moved = {}
    for x, rep in new.items():
        old_rep, had_row = old[x]
        if linked[x]:
            if not had_row:
                db.execute("INSERT INTO aux_comp VALUES (?,?)", (x, rep))
            elif old_rep != rep:
                db.execute("UPDATE aux_comp SET rep=? WHERE account=?",
                           (rep, x))
        elif had_row:
            db.execute("DELETE FROM aux_comp WHERE account=?", (x,))
        if old_rep != rep:
            moved[x] = (old_rep, rep)
    return moved


def _rep(db, account):
    row = db.execute(
        "SELECT rep FROM aux_comp WHERE account=?", (account,)).fetchone()
    return account if row is None else row[0]


# --------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------

def _ensure_aux(db):
    for ddl in _AUX_DDL:
        db.execute(ddl)


def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:
    modes = _check_modes(modes)
    _ensure_aux(db)
    for table in ("rollup", "aux_contrib", "aux_comp", "aux_hh"):
        db.execute(f"DELETE FROM {table}")

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

    household = "household" in modes
    comps = {}
    if household:
        comps = _all_components(db)
        db.executemany("INSERT INTO aux_comp VALUES (?,?)", comps.items())

    for shape in _shapes(modes):
        groups = {}
        contrib_rows = []
        hh = {}  # group -> {rep: accounts}
        for account, rows in orders.items():
            contribs = _contribs(
                shape, _day_stats(rows), tags.get(account, {}), seg_bands)
            rep = comps.get(account, account)
            for key, (n, nn, sm, mn, mx) in contribs.items():
                contrib_rows.append(
                    (shape, *key, account, n, nn, _to_db(sm), mn, mx))
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
                if household and shape == HH_SHAPE:
                    reps = hh.setdefault(key, {})
                    reps[rep] = reps.get(rep, 0) + 1
        db.executemany(
            "INSERT INTO aux_contrib (mode, day, segment, band, account, "
            "rows, nn, sm, mn, mx) VALUES (?,?,?,?,?,?,?,?,?,?)",
            contrib_rows,
        )
        if household and shape == HH_SHAPE:
            db.executemany(
                "INSERT INTO aux_hh VALUES (?,?,?,?,?)",
                [(*key, rep, n) for key, reps in hh.items()
                 for rep, n in reps.items()])
        for mode in modes:
            if SHAPE_OF[mode] != shape:
                continue
            db.executemany(
                "INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (mode, *key, n, nn, sm if nn else None,
                     len(hh[key]) if mode == "household" else acc, mn, mx)
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


def _affected(db, shapes, changes):
    """-> (accounts needing all shapes, accounts needing only rate shapes)."""
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
    if segments and RATE_SHAPES.intersection(shapes):
        # Accounts not touched by order/tag changes have up-to-date
        # contributions, which exist under segment s exactly when the
        # account has orders and a tag with segment s.
        for seg in segments:
            rate_accounts.update(r[0] for r in db.execute(
                "SELECT DISTINCT account FROM aux_contrib WHERE segment=?",
                (seg,)))
    return accounts, rate_accounts - accounts


class _Batch:
    """Accumulated per-group deltas of one maintain call."""

    def __init__(self, shapes, household, moved):
        self.deltas = {shape: {} for shape in shapes}
        self.household = household
        self.moved = moved
        self.hh = {}  # group -> {rep: delta accounts}

    def household_keys(self, db, account, old_keys, new_keys):
        if not self.household:
            return
        if account in self.moved:
            old_rep, new_rep = self.moved[account]
        else:
            if old_keys == new_keys:
                return
            old_rep = new_rep = _rep(db, account)
        if old_rep == new_rep:
            old_keys, new_keys = old_keys - new_keys, new_keys - old_keys
        for keys, rep, sign in ((old_keys, old_rep, -1),
                                (new_keys, new_rep, 1)):
            for key in keys:
                reps = self.hh.setdefault(key, {})
                reps[rep] = reps.get(rep, 0) + sign


def maintain(
    db: sqlite3.Connection, modes: Sequence[str], changes: list[dict]
) -> None:
    modes = _check_modes(modes)
    if not _aux_current(db, modes):
        # One-time migration of a database whose auxiliary state predates
        # this implementation; never taken on an already-repaired database.
        bootstrap(db, modes)
        return
    shapes = _shapes(modes)
    household = "household" in modes
    moved = _update_components(db, changes) if household else {}
    accounts, rate_accounts = _affected(db, shapes, changes)
    if not accounts and not rate_accounts and not moved:
        return
    rate_shapes = tuple(s for s in shapes if s in RATE_SHAPES)
    batch = _Batch(shapes, household, moved)
    for account in accounts:
        _refresh_account(db, account, shapes, bool(rate_shapes), batch)
    for account in rate_accounts:
        _refresh_account(db, account, rate_shapes, True, batch)
    for account in moved:
        if account not in accounts and account not in rate_accounts:
            keys = {tuple(r) for r in db.execute(
                "SELECT day, segment, band FROM aux_contrib "
                "WHERE account=? AND mode=?", (account, HH_SHAPE))}
            batch.household_keys(db, account, keys, keys)
    hh_acc = _apply_households(db, batch.hh)
    for shape in shapes:
        shape_modes = [m for m in modes if SHAPE_OF[m] == shape]
        deltas = batch.deltas[shape]
        for key, d in deltas.items():
            _apply_group(db, shape, shape_modes, key, d, hh_acc.get(key, 0))
        if household and shape == HH_SHAPE:
            for key, acc in hh_acc.items():
                if acc and key not in deltas:
                    db.execute(
                        "UPDATE rollup SET account_count=account_count+? "
                        f"WHERE {_GROUP}", (acc, "household", *key))


def _refresh_account(db, account, shapes, need_rates, batch):
    loaded = _load_account(db, account, need_rates)
    for shape in shapes:
        new = _contribs(shape, *loaded) if loaded is not None else {}
        old = {}
        for rowid, day, seg, band, n, nn, sm, mn, mx in db.execute(
            "SELECT rowid, day, segment, band, rows, nn, sm, mn, mx "
            "FROM aux_contrib WHERE account=? AND mode=?",
            (account, shape),
        ):
            old[(day, seg, band)] = (rowid, (n, nn, _from_db(sm), mn, mx))
        if shape == HH_SHAPE:
            batch.household_keys(db, account, set(old), set(new))
        shape_deltas = batch.deltas[shape]
        for key in old.keys() | new.keys():
            before = old.get(key)
            after = new.get(key)
            if before is not None and before[1] == after:
                continue
            d = shape_deltas.setdefault(key, [0, 0, 0, 0])
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
                        (shape, *key, account, n, nn, _to_db(sm), mn, mx),
                    )
                else:
                    db.execute(
                        "UPDATE aux_contrib SET rows=?, nn=?, sm=?, mn=?, mx=? "
                        "WHERE rowid=?",
                        (n, nn, _to_db(sm), mn, mx, before[0]),
                    )


def _apply_households(db, hh):
    """Apply (group, rep) account deltas; -> {group: distinct-rep delta}."""
    out = {}
    for key, reps in hh.items():
        acc = 0
        for rep, d in reps.items():
            if d == 0:
                continue
            row = db.execute(
                f"SELECT rowid, n FROM aux_hh WHERE {_HH_KEY}",
                (*key, rep)).fetchone()
            n = row[1] if row else 0
            if n + d == 0:
                db.execute("DELETE FROM aux_hh WHERE rowid=?", (row[0],))
                acc -= 1
            elif row is None:
                db.execute("INSERT INTO aux_hh VALUES (?,?,?,?,?)",
                           (*key, rep, d))
                acc += 1
            else:
                db.execute("UPDATE aux_hh SET n=? WHERE rowid=?",
                           (n + d, row[0]))
        out[key] = acc
    return out


def _apply_group(db, shape, modes, key, delta, hh_acc):
    minmax = None
    for mode in modes:
        params = (mode, *key)
        row = db.execute(
            f"SELECT rowid, row_count, amount_count, total_cents, "
            f"account_count FROM rollup WHERE {_GROUP}",
            params,
        ).fetchone()
        if row is None:
            rowid, n, nn, sm, acc = None, 0, 0, 0, 0
        else:
            rowid, n, nn, sm, acc = row
        n += delta[0]
        nn += delta[1]
        sm = _from_db(sm) + delta[2]
        acc += hh_acc if mode == "household" else delta[3]
        if n == 0:
            if rowid is not None:
                db.execute("DELETE FROM rollup WHERE rowid=?", (rowid,))
            continue
        if minmax is None:
            gparams = (shape, *key)
            minmax = (
                db.execute(f"SELECT MIN(mn) FROM aux_contrib WHERE {_GROUP}",
                           gparams).fetchone()[0],
                db.execute(f"SELECT MAX(mx) FROM aux_contrib WHERE {_GROUP}",
                           gparams).fetchone()[0],
            )
        values = (n, nn, sm if nn else None, acc, *minmax)
        if rowid is None:
            db.execute("INSERT INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (*params, *values))
        else:
            db.execute(
                "UPDATE rollup SET row_count=?, amount_count=?, "
                "total_cents=?, account_count=?, min_cents=?, max_cents=? "
                "WHERE rowid=?",
                (*values, rowid),
            )
