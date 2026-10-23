from __future__ import annotations

from collections import Counter

from .model import Case, Cell, Plan, Query, Rows, validate_case


def expression_sql(expr: list, params: list[Cell]) -> str:
    op = expr[0]
    if op == "col":
        return f'"{expr[1]}"."{expr[2]}"'
    if op == "lit":
        params.append(expr[1])
        return "?"
    if op == "agg":
        value = "*" if expr[2] is None else expression_sql(expr[2], params)
        return f"{expr[1].upper()}({value})"
    if op == "not":
        return f"(NOT {expression_sql(expr[1], params)})"
    if op == "isnull":
        return f"({expression_sql(expr[1], params)} IS NULL)"
    operators = {"add": "+", "sub": "-", "eq": "=", "ne": "<>",
                 "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
                 "and": "AND", "or": "OR"}
    left = expression_sql(expr[1], params)
    right = expression_sql(expr[2], params)
    return f"({left} {operators[op]} {right})"


def compile_case(case: Case) -> Plan:
    validate_case(case)
    mode = case["mode"]
    groups = case["group_by"]
    source = '"t"'
    if case["source"] != "single":
        join = "LEFT JOIN" if case["source"] == "left" else "INNER JOIN"
        source += f' {join} "u" ON "t"."k" = "u"."k"'

    def query(branch: int | None) -> Query:
        params: list[Cell] = []
        if mode in ("rows", "distinct", "group", "having"):
            expressions = [expression_sql(e, params) for e in case["select"]]
        else:
            expressions = [expression_sql(e, params) for e in groups]
            functions = ["SUM", "COUNT"] if branch is not None and mode in ("sum", "avg") else [mode.upper()]
            for function in functions:
                value = "*" if case["value"] is None else expression_sql(case["value"], params)
                expressions.append(f"{function}({value})")
        distinct = "DISTINCT " if mode == "distinct" and branch is None else ""
        sql = f"SELECT {distinct}{', '.join(expressions)} FROM {source}"
        conditions = []
        if case["where"] is not None:
            conditions.append(expression_sql(case["where"], params))
        if branch is not None and mode != "having":
            predicate = expression_sql(case["predicate"], params)
            conditions.append((f"({predicate})", f"(NOT ({predicate}))",
                               f"(({predicate}) IS NULL)")[branch])
        if conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in conditions)
        if groups:
            sql += " GROUP BY " + ", ".join(
                "(" + expression_sql(e, params) + ")" for e in groups
            )
        if branch is not None and mode == "having":
            predicate = expression_sql(case["predicate"], params)
            sql += " HAVING " + (
                f"({predicate})", f"(NOT ({predicate}))", f"(({predicate}) IS NULL)"
            )[branch]
        return Query(sql, tuple(params))

    return Plan(query(None), (query(0), query(1), query(2)), mode, len(groups))


def typed_row(row: list[Cell]) -> tuple:
    return tuple((type(value).__name__, value) for value in row)


def equivalent(expected: Rows, actual: Rows) -> bool:
    return Counter(map(typed_row, expected)) == Counter(map(typed_row, actual))


def compose(plan: Plan, partition_rows: list[Rows]) -> Rows:
    if len(partition_rows) != 3:
        raise ValueError("three partition results required")
    rows = [row for partition in partition_rows for row in partition]
    if plan.mode in ("rows", "having"):
        return [list(row) for row in rows]
    if plan.mode in ("distinct", "group"):
        unique = {typed_row(row): list(row) for row in rows}
        return list(unique.values())
    grouped: dict[tuple, tuple[list[Cell], list[list[Cell]]]] = {}
    for row in rows:
        key_values = row[:plan.group_count]
        key = typed_row(key_values)
        if key not in grouped:
            grouped[key] = (key_values, [])
        grouped[key][1].append(row[plan.group_count:])
    result: Rows = []
    for key_values, states in grouped.values():
        if plan.mode == "count":
            value = sum(state[0] for state in states)
        elif plan.mode in ("sum", "avg"):
            count = sum(state[1] for state in states)
            total = sum(state[0] for state in states if state[0] is not None)
            value = None if count == 0 else total if plan.mode == "sum" else total / count
        else:
            present = [state[0] for state in states if state[0] is not None]
            function = min if plan.mode == "min" else max
            value = function(present) if present else None
        result.append([*key_values, value])
    return result
