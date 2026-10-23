from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, NoReturn, Union
import sqlite3

Cell = Union[None, int, float, str]
Rows = list[list[Cell]]
Case = dict
AGGREGATES = ("count", "sum", "avg", "min", "max")
MODES = ("rows", "distinct", *AGGREGATES, "group", "having")
SOURCES = ("single", "inner", "left")
COLUMNS = ("id", "k", "v", "tag")


@dataclass(frozen=True)
class Query:
    sql: str
    params: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class Plan:
    base: Query
    parts: tuple[Query, Query, Query]
    mode: str
    group_count: int


Executor = Callable[[sqlite3.Connection, Query], Rows]


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _cell(value: object, text: bool = False) -> None:
    if value is None:
        return
    if text and isinstance(value, str) and len(value) <= 32:
        return
    if not text and type(value) is int and -1000 <= value <= 1000:
        return
    _fail("invalid bounded cell")


def _expr(expr: object, source: str, depth: int = 1,
          groups: list | None = None) -> str:
    if depth > 6 or not isinstance(expr, list) or not expr:
        _fail("invalid expression/depth")
    if groups is not None and expr in groups:
        return _expr(expr, source, depth)
    op = expr[0]
    if op == "col" and len(expr) == 3:
        if groups is not None:
            _fail("ungrouped column outside aggregate")
        if expr[1] not in ("t", "u") or expr[2] not in COLUMNS:
            _fail("unknown column")
        if source == "single" and expr[1] == "u":
            _fail("u unavailable in single source")
        return "text" if expr[2] == "tag" else "number"
    if op == "lit" and len(expr) == 2:
        _cell(expr[1], isinstance(expr[1], str))
        return "text" if isinstance(expr[1], str) else "number"
    if op == "agg" and len(expr) == 3:
        if groups is None or expr[1] not in AGGREGATES:
            _fail("aggregate node only permitted at HAVING stage")
        if expr[2] is None:
            if expr[1] != "count":
                _fail("only COUNT supports star")
        elif _expr(expr[2], source, depth + 1) != "number":
            _fail("aggregate argument must be numeric")
        return "number"
    if op in ("not", "isnull") and len(expr) == 2:
        kind = _expr(expr[1], source, depth + 1, groups)
        if op == "not" and kind != "predicate":
            _fail("NOT requires predicate")
        return "predicate"
    if op in ("add", "sub", "eq", "ne", "lt", "le", "gt", "ge", "and", "or") and len(expr) == 3:
        kinds = [_expr(e, source, depth + 1, groups) for e in expr[1:]]
        if op in ("add", "sub"):
            if kinds != ["number", "number"]:
                _fail("arithmetic requires numeric scalars")
            return "number"
        if op in ("and", "or"):
            if kinds != ["predicate", "predicate"]:
                _fail("boolean operator requires predicates")
        elif "predicate" in kinds:
            _fail("comparison requires scalars")
        return "predicate"
    _fail("unsupported expression")


def _has_aggregate(expr: list) -> bool:
    return bool(expr) and (expr[0] == "agg" or any(
        _has_aggregate(child) for child in expr[1:] if isinstance(child, list)
    ))


def validate_case(case: Case) -> None:
    keys = {"version", "tables", "source", "predicate", "where", "mode",
            "select", "value", "group_by"}
    if not isinstance(case, dict) or set(case) != keys:
        _fail("invalid case keys")
    if type(case["version"]) is not int or case["version"] != 1:
        _fail("unsupported version")
    if case["source"] not in SOURCES or case["mode"] not in MODES:
        _fail("invalid source/mode")
    tables = case["tables"]
    if not isinstance(tables, dict) or set(tables) != {"t", "u"}:
        _fail("both tables required")
    for rows in tables.values():
        if not isinstance(rows, list) or len(rows) > 32:
            _fail("invalid table")
        for row in rows:
            if not isinstance(row, list) or len(row) != 4:
                _fail("invalid row")
            for i, value in enumerate(row):
                _cell(value, i == 3)
    source = case["source"]
    if case["where"] is not None and _expr(case["where"], source) != "predicate":
        _fail("WHERE predicate required")
    select, groups = case["select"], case["group_by"]
    if not isinstance(select, list) or not isinstance(groups, list):
        _fail("select/group_by must be lists")
    if len(groups) > 2:
        _fail("at most two grouping expressions")
    for expression in groups:
        if _expr(expression, source) == "predicate":
            _fail("group must be scalar")
    stage = groups if case["mode"] == "having" else None
    if _expr(case["predicate"], source, groups=stage) != "predicate":
        _fail("predicate required")
    if case["mode"] in ("rows", "distinct"):
        if not 1 <= len(select) <= 3 or groups or case["value"] is not None:
            _fail("invalid projection")
    elif case["mode"] == "group":
        if not groups or select != groups or case["value"] is not None:
            _fail("group mode projects exactly its nonempty grouping expressions")
    elif case["mode"] == "having":
        if not 1 <= len(select) <= 3 or case["value"] is not None:
            _fail("invalid HAVING projection")
        if not groups and not any(_has_aggregate(e) for e in select if isinstance(e, list) and e):
            _fail("ungrouped HAVING requires an aggregate in SELECT")
    else:
        if select:
            _fail("invalid aggregate")
        value = case["value"]
        if value is None:
            if case["mode"] != "count":
                _fail("aggregate value required")
        elif _expr(value, source) != "number":
            _fail("aggregate value must be numeric")
    for expression in select:
        if _expr(expression, source, groups=stage) == "predicate":
            _fail("projection must be scalar")
