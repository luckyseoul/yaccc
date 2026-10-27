"""Diagnostics."""
import sys


class CompileError(Exception):
    def __init__(self, msg, loc=None):
        super().__init__(msg)
        self.msg = msg
        self.loc = loc

    def __str__(self):
        if self.loc is not None:
            return f"{self.loc}: error: {self.msg}"
        return f"error: {self.msg}"


class Diagnostics:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, msg, loc=None):
        self.errors.append(CompileError(msg, loc))

    def warn(self, msg, loc=None):
        self.warnings.append((msg, loc))

    def flush(self, stream=sys.stderr):
        for msg, loc in self.warnings:
            prefix = f"{loc}: " if loc is not None else ""
            print(f"{prefix}warning: {msg}", file=stream)
        for e in self.errors:
            print(str(e), file=stream)
        self.warnings.clear()


DIAG = Diagnostics()
