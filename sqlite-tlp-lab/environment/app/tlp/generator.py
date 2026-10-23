from __future__ import annotations

from .model import Case


def generate(seed: int, count: int) -> list[Case]:
    raise NotImplementedError("Generate reproducible, semantically diverse cases")
