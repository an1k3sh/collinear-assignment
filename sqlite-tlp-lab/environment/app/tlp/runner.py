from __future__ import annotations

from pathlib import Path

from .model import Case, Executor


def run_case(case: Case, executor: Executor | None = None) -> dict:
    raise NotImplementedError("Execute baseline and all three partitions")


def save_failure(path: str | Path, case: Case, result: dict) -> None:
    raise NotImplementedError("Save portable mismatch evidence")


def replay(path: str | Path, executor: Executor | None = None) -> dict:
    raise NotImplementedError("Rebuild state and rerun, do not trust saved claims")
