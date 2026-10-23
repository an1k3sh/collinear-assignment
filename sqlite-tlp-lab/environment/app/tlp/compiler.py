from __future__ import annotations

from .model import Case, Plan, Rows


def compile_case(case: Case) -> Plan:
    raise NotImplementedError("Compile the bounded AST into a TLP plan")


def compose(plan: Plan, partition_rows: list[Rows]) -> Rows:
    raise NotImplementedError("Compose bags, distinct rows, and aggregate states")


def equivalent(expected: Rows, actual: Rows) -> bool:
    raise NotImplementedError("Compare typed multisets, not sets")
