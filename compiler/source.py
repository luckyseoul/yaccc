"""Source reading: fixed/free reference formats, continuation lines,
floating comments, compiler directives and comment-entries."""
import re

from .errors import CompileError, DIAG
from .nodes import Loc

ID_COMMENT_PARAS = {'AUTHOR', 'INSTALLATION', 'DATE-WRITTEN', 'DATE-COMPILED',
                    'SECURITY', 'REMARKS'}
ID_PARAS = ID_COMMENT_PARAS | {'PROGRAM-ID', 'IDENTIFICATION', 'ID', 'ENVIRONMENT',
                               'DATA', 'PROCEDURE', 'FUNCTION-ID', 'END'}

TEXT_WIDTH = 65   # columns 8..72


class LogicalLine:
    __slots__ = ('text', 'loc', 'area_a', 'phys_len')

    def __init__(self, text, loc, area_a, phys_len):
        self.text = text
        self.loc = loc
        self.area_a = area_a
        self.phys_len = phys_len


def read_raw(path):
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        raise CompileError(f"cannot read '{path}': {e.strerror}")
    text = data.decode('latin-1')
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    out = []
    for line in lines:
        if line.endswith('\r'):
            line = line[:-1]
        if '\t' in line:
            line = line.expandtabs(8)
        line = line.replace('\x0c', ' ').replace('\x1a', '')
        out.append(line)
    return out


def detect_format(lines):
    for line in lines:
        s = line.rstrip()
        if not s.strip():
            continue
        st = s.lstrip()
        indent = len(s) - len(st)
        up = st.upper()
        if up.startswith('>>SOURCE') or up.startswith('$SET'):
            if 'FREE' in up:
                return 'free'
            if 'FIXED' in up:
                return 'fixed'
            continue
        if indent >= 7:
            return 'fixed'
        if st.startswith('*>'):
            return 'free'
        if len(s) > 6:
            seq = s[:6]
            if (seq.strip() == '' or seq.strip().isdigit()) and s[6] in ' *-/dD$':
                return 'fixed'
        return 'free'
    return 'fixed'


def open_quote(text):
    """Return the quote character if text ends inside an open literal."""
    q = None
    for c in text:
        if q:
            if c == q:
                q = None
        elif c in '"\'':
            q = c
    return q


def strip_floating_comment(text):
    q = None
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if q:
            if c == q:
                q = None
        elif c in '"\'':
            q = c
        elif c == '*' and i + 1 < n and text[i + 1] == '>':
            return text[:i]
        i += 1
    return text


_SOURCE_RE = re.compile(r'>>\s*SOURCE\s+(?:FORMAT\s+)?(?:IS\s+)?(FREE|FIXED|VARIABLE)', re.I)
_SRC_COMPUTER = re.compile(r'^\s*SOURCE-COMPUTER\b', re.I)
_SRC_COMPUTER_END = re.compile(r'\b(OBJECT-COMPUTER|SPECIAL-NAMES|REPOSITORY|INPUT-OUTPUT|FILE-CONTROL|'
                               r'DATA\s+DIVISION|PROCEDURE\s+DIVISION)\b', re.I)
_DEBUGGING_MODE = re.compile(r'\bDEBUGGING\s+MODE\b', re.I)


class DebugSwitch:
    """Compile-time debugging switch: debugging lines are compiled once the
    SOURCE-COMPUTER paragraph says WITH DEBUGGING MODE (or --debugging-mode)."""

    def __init__(self, on):
        self.on = on
        self.scan = None        # text of the SOURCE-COMPUTER paragraph seen so far

    def see(self, text):
        if self.on:
            return
        if self.scan is None:
            m = _SRC_COMPUTER.match(text)
            if not m:
                return
            self.scan = text[m.end():]
        else:
            self.scan += ' ' + text
        end = _SRC_COMPUTER_END.search(self.scan)
        if _DEBUGGING_MODE.search(self.scan[:end.start()] if end else self.scan):
            self.on = True
            self.scan = None
        elif end or len(self.scan) > 2000:
            self.scan = None


def process(lines, path, fmt, debugging=False):
    """Turn raw lines into logical lines (continuations joined, comments
    removed). Returns list of LogicalLine. `debugging` is a bool or a
    DebugSwitch shared by a source file and its copybooks."""
    out = []
    mode = fmt
    dbg = debugging if isinstance(debugging, DebugSwitch) else DebugSwitch(debugging)
    for idx, raw in enumerate(lines):
        loc = Loc(path, idx + 1)
        if mode in ('fixed', 'variable'):
            if len(raw) < 7:
                continue
            ind = raw[6]
            text = raw[7:72] if mode == 'fixed' else raw[7:]
            if ind in '*/':
                continue
            st = raw[6:].lstrip() if ind == '>' else text.lstrip()
            if st.startswith('>>') or (ind == '>' and raw[6:8] == '>>'):
                mode = _directive(st, mode, loc)
                continue
            if ind == '$':
                mode = _directive(raw[6:], mode, loc)
                continue
            if ind in 'dD':
                if not dbg.on:
                    continue
                ind = ' '
            if ind not in ' -':
                DIAG.warn(f"invalid indicator '{ind}' in column 7", loc)
            text = strip_floating_comment(text)
            dbg.see(text)
            if ind == '-':
                if not out:
                    raise CompileError("continuation line without a preceding line", loc)
                prev = out[-1]
                q = open_quote(prev.text)
                cs = text.lstrip()
                if not q and prev.phys_len >= TEXT_WIDTH and prev.text[-1:] in ('"', "'") and \
                        cs[:2] == prev.text[-1] * 2:
                    # quote at margin R is the first half of an embedded quote pair
                    prev.text += cs[1:]
                    prev.phys_len = len(text)
                    continue
                if q:
                    pad = TEXT_WIDTH - prev.phys_len
                    if pad > 0:
                        prev.text += ' ' * pad
                    s = text.lstrip()
                    if s and s[0] in '"\'':
                        s = s[1:]
                    prev.text += s
                else:
                    prev.text = prev.text.rstrip() + text.lstrip()
                prev.phys_len = len(text)
                continue
            area_a = text[:4].strip() != ''
            out.append(LogicalLine(text, loc, area_a, len(text)))
        else:
            st = raw.lstrip()
            if st.startswith('>>'):
                if st[2:3].upper() == 'D' and (len(st) == 3 or st[3] == ' '):
                    if not dbg.on:
                        continue
                    raw = st[3:]
                    st = raw.lstrip()
                else:
                    mode = _directive(st, mode, loc)
                    continue
            if st.upper().startswith('$SET'):
                mode = _directive(st, mode, loc)
                continue
            if st.startswith('*>'):
                continue
            text = strip_floating_comment(raw)
            dbg.see(text)
            # free-format literal continuation with '-' as first char
            if out and st.startswith('-') and open_quote(out[-1].text):
                prev = out[-1]
                s = st[1:].lstrip()
                if s and s[0] in '"\'':
                    s = s[1:]
                prev.text = prev.text.rstrip() + s
                continue
            out.append(LogicalLine(text, loc, not raw[:1].isspace() and raw != '', len(text)))
    _strip_comment_entries(out, fmt)
    return out


def _directive(text, mode, loc):
    up = text.upper()
    m = _SOURCE_RE.search(text)
    if m:
        return m.group(1).lower()
    if up.startswith('$SET'):
        if 'SOURCEFORMAT' in up:
            if 'FREE' in up:
                return 'free'
            if 'FIXED' in up:
                return 'fixed'
        return mode
    word = up[2:].strip().split(' ')[0] if up.startswith('>>') else ''
    if word not in ('PAGE', 'LISTING', 'EJECT', 'SKIP1', 'SKIP2', 'SKIP3', 'TITLE', 'CALL-CONVENTION', 'TURN', 'FEATURE'):
        DIAG.warn(f"compiler directive ignored: {text.strip()}", loc)
    return mode


_FIRST_WORD = re.compile(r'\s*([A-Za-z0-9][A-Za-z0-9-]*)')
_ID_END_FREE = re.compile(r'\s*((AUTHOR|INSTALLATION|DATE-WRITTEN|DATE-COMPILED|SECURITY|REMARKS|PROGRAM-ID|'
                          r'FUNCTION-ID)\s*\.|(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION|'
                          r'END\s+(PROGRAM|FUNCTION)\b)', re.I)


def _strip_comment_entries(lines, fmt):
    in_id = False
    skipping = False
    for ll in lines:
        if skipping:
            # a comment-entry runs until the next Area A entry (fixed format)
            # or the next paragraph/division header (free format)
            if fmt in ('fixed', 'variable'):
                stop = ll.area_a
            else:
                stop = bool(_ID_END_FREE.match(ll.text))
            if not stop:
                ll.text = ''
                continue
            skipping = False
        m = _FIRST_WORD.match(ll.text)
        first = m.group(1).upper() if m else ''
        up = ll.text.strip().upper()
        if re.match(r'(IDENTIFICATION|ID)\s+DIVISION', up) or first == 'PROGRAM-ID':
            in_id = True
        elif re.match(r'(ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION', up):
            in_id = False
        if in_id and first in ID_COMMENT_PARAS:
            idx = ll.text.upper().find(first) + len(first)
            ll.text = ll.text[:idx] + '.'
            skipping = True
