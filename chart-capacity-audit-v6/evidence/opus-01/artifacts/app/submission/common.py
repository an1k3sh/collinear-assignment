"""Shared helpers for the rollout pipeline (standard library only)."""
import math
from fractions import Fraction


class InputError(Exception):
    """Malformed or inconsistent input; reported with a diagnostic and nonzero exit."""


def is_num(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def F(x):
    """Exact rational from a JSON number, using its decimal representation."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, bool):
        raise InputError("boolean used where a number is required")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        if not math.isfinite(x):
            raise InputError("nonfinite number")
        return Fraction(repr(x))
    raise InputError("number required, got %r" % (x,))


def fnum(x):
    """JSON-friendly number: integers stay integers, others become floats."""
    if x is None:
        return None
    if isinstance(x, Fraction):
        if x.denominator == 1:
            return int(x)
        return float(x)
    return x
