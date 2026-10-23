"""Diagnostics and exit codes."""

EXIT_CODES = {
    "SYNTAX": 2,
    "STATIC": 3,
    "DOMAIN": 4,
    "RUNTIME": 5,
    "INPUT": 6,
    "IO": 7,
    "CHECKPOINT": 8,
}

SUSPENDED = 10


class StockError(Exception):
    """A diagnosable failure. ``pos`` is (role, line, column)."""

    def __init__(self, category, message, pos=None, stack=None, code=None):
        super().__init__(message)
        self.category = category
        self.message = message or category
        self.pos = pos
        self.stack = stack
        self.code = code

    def diagnostic(self, files):
        out = {"error": self.category, "message": self.message}
        if self.pos is not None:
            role, line, col = self.pos
            out["file"] = files.get(role, role)
            out["line"] = line
            out["column"] = col
        if self.stack is not None:
            out["stack"] = list(self.stack)
        if self.code is not None:
            out["code"] = self.code
        return out


class DomainFailure(Exception):
    """Recoverable inventory/assert failure carrying an error value."""

    def __init__(self, err):
        super().__init__(err.code)
        self.err = err


class ErrorValue:
    """Value bound by ``recover (name)``; immutable."""

    __slots__ = ("code", "pos", "stack")

    def __init__(self, code, pos, stack):
        self.code = code
        self.pos = tuple(pos)
        self.stack = tuple(stack)

    def __eq__(self, other):
        return (isinstance(other, ErrorValue) and self.code == other.code
                and self.pos == other.pos and self.stack == other.stack)

    def __hash__(self):
        return hash((self.code, self.pos, self.stack))
