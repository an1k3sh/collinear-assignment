from __future__ import annotations

import random

from .model import AGGREGATES, Case, MODES, SOURCES


def generate(seed: int, count: int) -> list[Case]:
    if type(seed) is not int or not -(2**63) <= seed < 2**63:
        raise ValueError("seed must be signed 64-bit integer")
    if type(count) is not int or not 0 <= count <= 4096:
        raise ValueError("count must be in [0, 4096]")
    rng = random.Random(seed)
    cases = []
    for i in range(count):
        mode = MODES[i % len(MODES)]
        cycle = i // len(MODES)
        source = SOURCES[cycle % 3]
        value_col = ["col", "t", "v"]
        cut = rng.randint(-20, 20)
        low, high = cut - rng.randint(1, 9), cut + rng.randint(1, 9)
        tag = rng.choice(["a'b", "snow-\u2603", "", "nul\u0000tag"])
        rows = [[1, 1, low, tag], [2, 1, low, tag], [3, 1, high, "z"],
                [4, 2, None, None], [5, None, high, tag], [6, 3, None, "z"]]
        rng.shuffle(rows)
        other = [[11, 1, 4, "r"], [12, 1, -3, "r"], [13, 2, None, None]]
        basic = ["lt", value_col, ["lit", cut]]
        predicates = [
            basic,
            ["not", ["ge", value_col, ["lit", cut]]],
            ["and", basic, ["eq", ["col", "t", "k"], ["lit", 1]]],
            ["or", basic, ["eq", ["col", "t", "id"], ["lit", -99]]],
            ["eq", value_col, ["lit", low]],
            ["isnull", value_col],
            ["le", ["add", value_col, ["lit", 1]], ["lit", cut]],
            ["and", ["not", ["gt", value_col, ["lit", cut]]],
             ["ne", ["col", "t", "id"], ["lit", -1]]],
        ]
        where = None
        if cycle % 4 == 0:
            where = ["ge", ["col", "t", "id"], ["lit", 0]]
        if cycle % 8 == 7:
            where = ["lt", ["col", "t", "id"], ["lit", -100]]
        aggregate = mode in AGGREGATES
        groups = []
        if aggregate and cycle % 2 == 0:
            groups = [["col", "t", "tag"]]
            if cycle % 4 == 0:
                groups.append(["col", "t", "k"])
        value = value_col if aggregate else None
        if aggregate and cycle in (2, 5, 10):
            value = ["lit", None]
        if mode == "count" and cycle % 3 == 0:
            value = None
        select = [value_col] if not aggregate else []
        if not aggregate and cycle % 2:
            select.append(["col", "t", "tag"])
        predicate = predicates[cycle % len(predicates)]
        if mode == "group":
            groups = [["col", "t", "k"]]
            if cycle % 3 == 0:
                groups.append(["col", "t", "tag"])
            select = list(groups)
            predicate = ["lt", value_col, ["lit", 0]]
            rows = [[1, 1, -3, tag], [2, 1, 5, tag], [3, 1, None, tag],
                    [4, 2, -1, "b"], [5, 2, 2, "b"], [6, 2, None, "b"]]
            if where is not None and cycle % 8 != 7:
                where = ["gt", ["col", "t", "id"], ["lit", 0]]
        if mode == "having":
            groups = [["col", "t", "k"]]
            rows = [[1, 1, 6, tag], [2, 1, -2, tag], [3, 2, -5, "b"],
                    [4, 3, None, None], [5, 4, 4, "d"]]
            other = [[11, 1, 4, "r"], [12, 2, -3, "r"], [13, 3, None, None],
                     [14, 4, 2, "r"]]
            total = ["agg", "sum", value_col]
            select = [total]  # Groups 1 and 4 deliberately have identical projections.
            predicate = ["gt", total, ["lit", 0]]
            if cycle % 4 == 2:
                groups = []  # SQLite implicit single aggregate group.
            if cycle % 4 == 3:
                select = [total, ["agg", "count", value_col]]
                predicate = ["and", ["gt", total, ["lit", 0]],
                             ["ge", ["agg", "count", None], ["lit", 1]]]
        cases.append({
            "version": 1, "tables": {"t": rows, "u": other}, "source": source,
            "predicate": predicate, "where": where,
            "mode": mode, "select": select, "value": value, "group_by": groups,
        })
    return cases
