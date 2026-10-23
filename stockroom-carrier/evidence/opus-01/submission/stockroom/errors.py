"""Diagnostics and control-flow exceptions."""

EXIT_CODES = {
    "SYNTAX": 2, "STATIC": 3, "DOMAIN": 4, "RUNTIME": 5,
    "INPUT": 6, "IO": 7, "CHECKPOINT": 8,
}


class StockroomError(Exception):
    """A reportable failure. DOMAIN instances use the DomainError subclass."""

    def __init__(self, category, message, loc=None, stack=None, code=None):
        super().__init__(message)
        self.category = category
        self.message = message or category
        self.loc = loc
        self.stack = list(stack) if stack is not None else None
        self.code = code

    def diagnostic(self):
        out = {"error": self.category, "message": self.message}
        if self.loc is not None:
            source, line, column = self.loc
            out["file"] = source.display
            out["line"] = line
            out["column"] = column
        if self.stack is not None:
            out["stack"] = self.stack
        if self.code is not None:
            out["code"] = self.code
        return out

    @property
    def exit_code(self):
        return EXIT_CODES[self.category]


class DomainError(StockroomError):
    """Recoverable inventory/assert/carrier failure."""

    def __init__(self, code, message, loc, stack):
        super().__init__("DOMAIN", message, loc, stack, code)


class PauseExit(BaseException):
    """Successful durable suspension; never caught by `recover`."""

    def __init__(self, label):
        super().__init__(label)
        self.label = label
