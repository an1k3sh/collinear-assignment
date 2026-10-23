"""Independent verifier queries: never import candidate compilation/composition."""
from __future__ import annotations

from collections import Counter
import copy
import json
import random
import sqlite3

AGGREGATES = ("count", "sum", "avg", "min", "max")
MODES = ("rows", "distinct", *AGGREGATES, "group", "having")


def fingerprint(value):
    if isinstance(value, list):
        if value and value[0] == "lit":
            return ["lit", type(value[1]).__name__]
        return [fingerprint(item) for item in value]
    if isinstance(value, dict):
        return {key: fingerprint(item) for key, item in value.items() if key != "tables"}
    return value


def bag(rows):
    return Counter(tuple((type(v).__name__, v) for v in row) for row in rows)


def connect(case):
    db = sqlite3.connect(":memory:")
    for name, rows in case["tables"].items():
        db.execute(f"CREATE TABLE {name}(id INTEGER, k INTEGER, v INTEGER, tag TEXT)")
        db.executemany(f"INSERT INTO {name} VALUES (?,?,?,?)", rows)
    return db


def render(node, bindings):
    op, *children = node
    if op == "lit":
        key = "p" + str(len(bindings))
        bindings[key] = children[0]
        return ":" + key
    if op == "col":
        return ".".join(children)
    if op == "agg":
        argument = "*" if children[1] is None else render(children[1], bindings)
        return f"{children[0]}({argument})"
    args = [render(child, bindings) for child in children]
    if op == "not":
        return f"(NOT ({args[0]}))"
    if op == "isnull":
        return f"(({args[0]}) IS NULL)"
    symbol = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">",
              "ge": ">=", "add": "+", "sub": "-", "and": "AND", "or": "OR"}[op]
    return f"(({args[0]}) {symbol} ({args[1]}))"


def source_sql(case):
    return {"single": "t", "inner": "t JOIN u ON t.k=u.k",
            "left": "t LEFT JOIN u ON t.k=u.k"}[case["source"]]


def reference_rows(db, case, branch=None, stats=False):
    binds = {}
    groups = [render(e, binds) for e in case["group_by"]]
    mode = case["mode"]
    if mode in ("rows", "distinct", "group", "having"):
        terms = [render(e, binds) for e in case["select"]]
    else:
        argument = "*" if case["value"] is None else render(case["value"], binds)
        if stats and mode in ("sum", "avg"):
            terms = groups + [f"sum({argument})", f"count({argument})"]
        else:
            terms = groups + [f"{mode}({argument})"]
    distinct = "DISTINCT " if mode == "distinct" else ""
    sql = f"SELECT {distinct}{','.join(terms)} FROM {source_sql(case)}"
    clauses = []
    if case["where"] is not None:
        clauses.append(render(case["where"], binds))
    if branch is not None and mode != "having":
        pred = render(case["predicate"], binds)
        clauses.append([f"({pred})", f"NOT ({pred})", f"({pred}) IS NULL"][branch])
    if clauses:
        sql += " WHERE " + " AND ".join(f"({x})" for x in clauses)
    if groups:
        sql += " GROUP BY " + ",".join(groups)
    if branch is not None and mode == "having":
        pred = render(case["predicate"], binds)
        sql += " HAVING " + [f"({pred})", f"NOT ({pred})", f"({pred}) IS NULL"][branch]
    return [list(row) for row in db.execute(sql, binds)]


def partition_sizes(db, case):
    binds = {}
    predicate = render(case["predicate"], binds)
    force_aggregate = ", COUNT(*)" if case["mode"] == "having" else ""
    sql = f"SELECT ({predicate}){force_aggregate} FROM {source_sql(case)}"
    if case["where"] is not None:
        sql += " WHERE " + render(case["where"], binds)
    if case["mode"] == "having" and case["group_by"]:
        sql += " GROUP BY " + ",".join(render(e, binds) for e in case["group_by"])
    sizes = [0, 0, 0]
    for row in db.execute(sql, binds):
        truth = row[0]
        sizes[2 if truth is None else 0 if truth else 1] += 1
    return sizes


def example():
    return {
        "version": 1, "source": "single",
        "tables": {"t": [[1, 1, 8, "q'"], [2, 1, 8, "q'"],
                         [3, 2, -3, "z"], [4, None, None, None],
                         [5, 2, None, "z"], [6, 4, 0, "nul\u0000tag"]],
                   "u": [[1, 1, 2, "r"], [2, 1, None, "s"], [3, 2, -4, None]]},
        "predicate": ["gt", ["col", "t", "v"], ["lit", 0]],
        "where": None, "mode": "rows", "select": [["col", "t", "v"]],
        "value": None, "group_by": [],
    }


def fixtures():
    rng = random.Random(83194)
    predicates = [
        ["gt", ["col", "t", "v"], ["lit", 0]],
        ["eq", ["col", "t", "tag"], ["lit", "q'"]],
        ["or", ["lt", ["col", "t", "v"], ["lit", -1]],
         ["isnull", ["col", "t", "k"]]],
        ["and", ["not", ["eq", ["col", "t", "v"], ["lit", 8]]],
         ["le", ["add", ["col", "t", "id"], ["lit", 3]], ["lit", 8]]],
        ["ne", ["sub", ["col", "t", "v"], ["lit", -2]], ["lit", 0]],
        ["isnull", ["eq", ["col", "t", "tag"], ["lit", None]]],
    ]
    for index in range(126):
        case = example()
        case["mode"] = mode = MODES[index % 7]
        case["source"] = ("single", "inner", "left")[(index // 7) % 3]
        case["predicate"] = copy.deepcopy(predicates[(index // 3) % len(predicates)])
        if index % 4 == 0:
            case["where"] = ["ge", ["col", "t", "id"], ["lit", 2]]
        if index % 13 == 0:
            case["tables"]["t"] = []
        if mode not in ("rows", "distinct"):
            case["select"] = []
            case["value"] = ["col", "t", "v"]
            if mode == "count" and index % 2:
                case["value"] = None
            elif index % 5 == 0:
                case["value"] = ["lit", None]
            elif index % 7 == 3:
                case["value"] = ["add", ["col", "t", "v"], ["lit", rng.randint(-8, 8)]]
            if index % 2 == 0:
                case["group_by"] = [["col", "t", "tag"]]
                if index % 4 == 0:
                    case["group_by"].append(["col", "t", "k"])
        elif index % 2:
            case["select"] += [["col", "t", "tag"], ["lit", "o'h\u0000\u2603"]]
        if case["source"] != "single" and index % 3 == 0:
            case["predicate"] = ["lt", ["col", "u", "v"], ["col", "t", "v"]]
        yield case
    yield from grouping_fixtures()


def grouping_fixtures():
    key = ["col", "t", "k"]
    value = ["col", "t", "v"]
    total = ["agg", "sum", value]
    for source in ("single", "inner", "left"):
        for group in ([key], [key, ["col", "t", "tag"]],
                      [["lit", "constant"], key]):
            case = example()
            case.update(source=source, mode="group", select=group, group_by=group)
            case["tables"]["t"] = [[1, 1, 5, "a"], [2, 1, -5, "a"], [3, 1, None, "a"],
                                   [4, None, 7, None], [5, None, -3, None]]
            yield case
            yield dict(case, where=["gt", ["col", "t", "id"], ["lit", 100]])
        predicates = [
            ["gt", total, ["lit", 0]],
            ["eq", ["agg", "count", value], ["lit", 0]],
            ["isnull", ["agg", "avg", value]],
            ["and", ["ge", ["agg", "max", value], ["lit", 1]],
             ["lt", ["agg", "min", value], ["lit", 0]]],
            ["or", ["not", ["eq", total, ["lit", 4]]],
             ["isnull", key]],
        ]
        for index, predicate in enumerate(predicates):
            case = example()
            case["tables"] = {
                "t": [[1, 1, 6, "a"], [2, 1, -2, "a"], [3, 2, -5, "b"],
                      [4, 3, None, "c"], [5, 4, 4, "d"], [6, None, None, None]],
                "u": [[1, 1, 1, "r"], [2, 2, 2, "s"], [3, 3, None, None],
                      [4, 4, 3, "r"]]}
            case.update(mode="having", source=source, select=[total],
                        predicate=predicate, group_by=[key])
            if index % 2:
                case["where"] = ["ge", ["col", "t", "id"], ["lit", 2]]
            yield case
            yield dict(case, select=[key, total, ["agg", "count", None]])
            yield dict(case, where=["lt", ["col", "t", "id"], ["lit", -1]])
        for function in AGGREGATES:
            aggregate = ["agg", function, value]
            for empty in (False, True):
                case = example()
                case.update(mode="having", source=source, select=[aggregate],
                            predicate=["gt", aggregate, ["lit", 0]])
                if empty:
                    case["tables"]["t"] = []
                yield case


def walk(node):
    if not isinstance(node, list) or not node:
        return
    yield node[0]
    for child in node[1:]:
        if isinstance(child, list):
            yield from walk(child)


def depth(node):
    return 1 + max((depth(c) for c in node[1:] if isinstance(c, list)), default=0)


def diversity(cases):
    modes = Counter(c["mode"] for c in cases)
    sources = Counter(c["source"] for c in cases)
    operators = set()
    metrics = Counter()
    grouped_modes = set()
    count_forms = set()
    shapes = set()
    for case in cases:
        operators.update(walk(case["predicate"]))
        shapes.add(json.dumps(fingerprint(case), sort_keys=True))
        metrics["filtered"] += case["where"] is not None
        metrics["deep"] += depth(case["predicate"]) >= 3
        if case["group_by"] and case["mode"] in AGGREGATES:
            metrics["grouped"] += 1
            grouped_modes.add(case["mode"])
        if case["mode"] == "count":
            count_forms.add("star" if case["value"] is None else "value")
        db = connect(case)
        try:
            sizes = partition_sizes(db, case)
            metrics["three_way"] += all(size > 0 for size in sizes)
            metrics["nonempty"] += sum(sizes) > 0
            metrics["empty"] += case["mode"] != "having" and sum(sizes) == 0
            if case["mode"] == "group":
                partitions = [set(bag(reference_rows(db, case, j))) for j in range(3)]
                metrics["shared_groups"] += any(
                    partitions[a] & partitions[b] for a, b in ((0, 1), (0, 2), (1, 2))
                )
                metrics["group_filtered"] += case["where"] is not None
            if case["mode"] == "having":
                metrics["having_three_way"] += all(size > 0 for size in sizes)
                rows = reference_rows(db, case)
                metrics["having_duplicates"] += len(rows) > len(bag(rows))
                metrics["having_ungrouped"] += not case["group_by"]
                metrics["having_filtered"] += case["where"] is not None
            if case["mode"] in ("rows", "distinct"):
                raw = dict(case, mode="rows")
                rows = reference_rows(db, raw)
                metrics["duplicates"] += len(rows) > len(bag(rows))
            elif case["mode"] in AGGREGATES and case["value"] is not None and sum(sizes):
                count_case = dict(case, mode="count", group_by=[])
                metrics["all_null"] += reference_rows(db, count_case) == [[0]]
        finally:
            db.close()
    checks = {
        "modes": all(modes[m] >= 8 for m in MODES),
        "sources_filters": all(sources[s] >= 16 for s in ("single", "inner", "left")) and metrics["filtered"] >= 16,
        "grouping": metrics["grouped"] >= 20 and grouped_modes >= set(AGGREGATES) and count_forms == {"star", "value"},
        "operators": operators >= {"eq", "lt", "and", "or", "not", "isnull"} and metrics["deep"] >= 12,
        "shapes": len(shapes) >= 20,
        "partition_occupancy": metrics["three_way"] >= 24 and metrics["nonempty"] >= 48,
        "edge_data": metrics["empty"] >= 6 and metrics["all_null"] >= 6 and metrics["duplicates"] >= 6,
        "group_oracle": metrics["shared_groups"] >= 6 and metrics["group_filtered"] >= 2,
        "having_oracle": metrics["having_three_way"] >= 6 and metrics["having_duplicates"] >= 4
                         and metrics["having_ungrouped"] >= 2 and metrics["having_filtered"] >= 2,
    }
    return checks, {"modes": dict(modes), "sources": dict(sources),
                    "metrics": dict(metrics), "shapes": len(shapes),
                    "operators": sorted(operators)}
