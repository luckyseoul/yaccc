# SPDX-License-Identifier: MIT
"""Diagnostics."""
import sys

_SOURCE_CACHE = {}


def source_line(path, line):
    """The text of one source line, or None when it cannot be read."""
    if not path or line <= 0:
        return None
    try:
        lines = _SOURCE_CACHE.get(path)
        if lines is None:
            with open(path, 'rb') as fp:
                lines = fp.read().decode('latin-1').splitlines()
            _SOURCE_CACHE[path] = lines
        if line <= len(lines):
            return lines[line - 1].rstrip('\r\n')
    except OSError:
        pass
    return None


class CompileError(Exception):
    def __init__(self, msg, loc=None):
        super().__init__(msg)
        self.msg = msg
        self.loc = loc

    def __str__(self):
        if self.loc is None:
            return f"error: {self.msg}"
        head = f"{self.loc}: error: {self.msg}"
        text = source_line(self.loc.file, self.loc.line)
        if text is None:
            return head
        return f"{head}\n  {self.loc.line} | {text}"


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
            print(str(CompileError(msg, loc)).replace(': error: ', ': warning: ', 1), file=stream)
        for e in self.errors:
            print(str(e), file=stream)
        self.warnings.clear()


DIAG = Diagnostics()
