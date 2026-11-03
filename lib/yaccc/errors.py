# SPDX-License-Identifier: MIT
"""Diagnostics."""
import difflib
import sys

_SOURCE_CACHE = {}

# (path, line) -> the text a fixed-format line has after column 72, which the
# compiler ignores. An error on or just after such a line gets a note: a
# statement that runs past the margin is the usual cause of an error that
# makes no sense for the code as written.
_CUT = {}

MAX_ERRORS = 20

# the statement being compiled, for the report of an internal error
WHERE = None


def note_cut(path, line, text):
    _CUT[(path, line)] = text


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


def did_you_mean(word, candidates):
    """'; did you mean 'X'?' for the candidate closest to word, or ''."""
    if not word:
        return ''
    up = word.upper()
    pool = sorted({c for c in candidates if c and c != up})
    m = difflib.get_close_matches(up, pool, n=1, cutoff=0.75)
    return f"; did you mean '{m[0]}'?" if m else ''


class CompileError(Exception):
    def __init__(self, msg, loc=None):
        super().__init__(msg)
        self.msg = msg
        self.loc = loc

    def render(self, kind='error'):
        if self.loc is None:
            return f"{kind}: {self.msg}"
        head = f"{self.loc}: {kind}: {self.msg}"
        text = source_line(self.loc.file, self.loc.line)
        if text is None:
            return head
        out = f"{head}\n  {self.loc.line} | {text}"
        if kind == 'error':
            for ln in (self.loc.line, self.loc.line - 1):
                cut = _CUT.get((self.loc.file, ln))
                if cut:
                    out += (f"\n  note: line {ln} runs past column 72; in fixed-format source "
                            f"'{cut.strip()}' is outside the program text and ignored")
                    break
        return out

    def __str__(self):
        return self.render()


class ErrorsReported(CompileError):
    """Raised once the errors have been recorded in DIAG: the caller prints
    them and stops."""

    def __init__(self):
        super().__init__('errors reported')


class Diagnostics:
    """Warnings and errors in the order they were found. A phase that can go
    on after an error (the parser at the next sentence, code generation at
    the next statement) records it here instead of raising, so one run
    reports every error it can find."""

    def __init__(self):
        self.items = []         # (kind, CompileError)
        self.nerrors = 0

    def error(self, e, loc=None):
        if not isinstance(e, CompileError):
            e = CompileError(e, loc)
        if isinstance(e, ErrorsReported):
            return
        key = (str(e.loc), e.msg)
        if any(k == 'error' and (str(x.loc), x.msg) == key for k, x in self.items):
            return
        self.items.append(('error', e))
        self.nerrors += 1
        if self.nerrors >= MAX_ERRORS:
            self.items.append(('error', CompileError(f"too many errors ({MAX_ERRORS}); stopping")))
            raise ErrorsReported()

    def warn(self, msg, loc=None):
        self.items.append(('warning', CompileError(msg, loc)))

    def check(self):
        """Stop if an error has been recorded."""
        if self.nerrors:
            raise ErrorsReported()

    def flush(self, stream=sys.stderr):
        for kind, e in self.items:
            print(e.render(kind), file=stream)
        if self.nerrors > 1:
            print(f"{self.nerrors} errors", file=stream)
        self.items.clear()
        self.nerrors = 0


DIAG = Diagnostics()
