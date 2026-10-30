# SPDX-License-Identifier: MIT
"""Compiler directives of COBOL 2014 (and their Micro Focus $ forms) that
control which source lines are compiled: >>DEFINE, >>IF / >>ELIF / >>ELSE /
>>END-IF, >>EVALUATE / >>WHEN / >>END-EVALUATE, and >>SET with a compilation
variable. One Directives object is shared by a source file and its copybooks.
"""
import re
from decimal import Decimal, InvalidOperation

from .errors import CompileError, DIAG

_TOKEN = re.compile(r"""\s*(?:
      (?P<str>"(?:[^"]|"")*"|'(?:[^']|'')*')
    | (?P<num>[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+))
    | (?P<op><=|>=|<>|=|<|>|\(|\)|\+|-|\*|/)
    | (?P<word>[A-Za-z0-9][A-Za-z0-9_-]*)
    )""", re.X)

UNSET = object()


class Directives:
    def __init__(self, defines=None):
        # compilation variables: name -> value (str, Decimal or True for "defined")
        self.vars = {}
        for k, v in (defines or {}).items():
            self.vars[k.upper()] = _literal_value(v) if isinstance(v, str) else v
        self.params = dict(self.vars)      # -D values, for AS PARAMETER
        # conditional state: list of [active, taken, kind] per open >>IF / >>EVALUATE
        self.stack = []
        self.dpc_in_data = None
        self.comp1_binary = False   # $SET COMP-1(BINARY): COMP-1 is a binary integer
        # constants in source order: (line, name, value), so a constant used
        # before a later >>DEFINE ... OVERRIDE still sees the earlier value
        self.const_history = []
        self.check = None      # None: unchanged
        self.check_changes = []   # (file, line, on) in source order

    @property
    def active(self):
        return all(e[0] for e in self.stack)

    def _outer_active(self):
        return all(e[0] for e in self.stack[:-1])

    # ------------------------------------------------------------ entry point
    def handle(self, text, loc):
        """Process a directive line. Returns True if it was one of ours."""
        s = text.strip()
        # >>TURN ... CHECKING OFF/ON and the Micro Focus $SET SSRANGE forms
        # switch the bounds checks from this line on
        up = s.upper()
        if 'NOSSRANGE' in up or ('CHECKING' in up and 'OFF' in up):
            self.check = False
            self.check_changes.append((loc.file, loc.line, False))
        elif 'SSRANGE' in up or ('CHECKING' in up and 'ON' in up):
            self.check = True
            self.check_changes.append((loc.file, loc.line, True))
        # a directive may carry a floating comment
        cut = s.find('*>')
        if cut > 0:
            s = s[:cut].rstrip()
        if s.startswith('$'):
            return self._dollar(s[1:], loc)
        if not s.startswith('>>'):
            return False
        body = s[2:].strip()
        word = body.split(None, 1)[0].upper() if body else ''
        rest = body[len(word):].strip() if word else ''
        if word == 'IF':
            on = self.active and self._cond(rest, loc)
            self.stack.append([on, on, 'IF'])
            return True
        if word in ('ELIF', 'ELSE-IF'):
            e = self._top('IF', word, loc)
            on = self._outer_active() and not e[1] and self._cond(rest, loc)
            e[0] = on
            e[1] = e[1] or on
            return True
        if word == 'ELSE':
            e = self._top('IF', word, loc)
            on = self._outer_active() and not e[1]
            e[0] = on
            e[1] = True
            return True
        if word in ('END-IF', 'END'):
            if word == 'END' and rest.upper().startswith('EVALUATE'):
                self._top('EVALUATE', 'END-EVALUATE', loc)
            else:
                self._top('IF', word, loc)
            self.stack.pop()
            return True
        if word == 'EVALUATE':
            subject = rest
            self.stack.append([False, False, 'EVALUATE', subject])
            return True
        if word == 'WHEN':
            e = self._top('EVALUATE', word, loc)
            if e[1] or not self._outer_active():
                e[0] = False
            elif rest.upper() == 'OTHER':
                e[0] = True
                e[1] = True
            else:
                subj = e[3]
                if subj.upper() in ('TRUE', ''):
                    on = self._cond(rest, loc)
                else:
                    on = self._cond(f"{subj} = {rest}", loc)
                e[0] = on
                e[1] = on
            return True
        if word == 'END-EVALUATE':
            self._top('EVALUATE', word, loc)
            self.stack.pop()
            return True
        if not self.active:
            return True                     # other directives in skipped code
        if word == 'DEFINE':
            self._define(rest, loc)
            return True
        if word == 'SET':
            return self._set(rest, loc)
        return False

    def _top(self, kind, word, loc):
        if not self.stack or self.stack[-1][2] != kind:
            raise CompileError(f">>{word} without >>{kind}", loc)
        return self.stack[-1]

    def check_closed(self, loc):
        if self.stack:
            raise CompileError(f">>{self.stack[-1][2]} without >>END-{self.stack[-1][2]}", loc)

    # ------------------------------------------------------------ >>DEFINE / >>SET
    def _define(self, rest, loc):
        toks = _tokens(rest, loc)
        if toks and toks[0][1].upper() == 'CONSTANT':
            toks = toks[1:]
        if not toks or toks[0][0] != 'word':
            raise CompileError(">>DEFINE: compilation variable name expected", loc)
        name = toks[0][1].upper()
        toks = toks[1:]
        override = bool(toks) and toks[-1][0] == 'word' and toks[-1][1].upper() == 'OVERRIDE'
        if override:
            toks = toks[:-1]
        if not toks:
            self.vars[name] = True
            return
        if toks[0][0] == 'word' and toks[0][1].upper() == 'OFF':
            self.vars.pop(name, None)
            return
        if toks[0][0] == 'word' and toks[0][1].upper() == 'AS':
            toks = toks[1:]
        if len(toks) == 1 and toks[0][0] == 'word' and toks[0][1].upper() == 'PARAMETER':
            if name in self.params:
                self.vars[name] = self.params[name]
            else:
                self.vars.pop(name, None)
            return
        if name in self.vars and not override and name in self.params:
            return                          # a -D value wins unless OVERRIDE
        if len(toks) == 1 and toks[0][0] in ('str', 'string'):
            # $SET CONSTANT DOGGY "Barky": a text constant, usable wherever a
            # literal is (VALUE, DISPLAY, comparisons)
            v = toks[0][1]
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            if name in self.vars and not override:
                return      # a constant cannot be redefined without OVERRIDE
            self.vars[name] = v
            if loc is not None:
                self.const_history.append((loc.line, name, v))
            return
        self.vars[name] = _Expr(toks, self, loc).arith()

    def _set(self, rest, loc):
        """>>SET CONSTANT name literal; other >>SET forms are left to the caller."""
        parts = rest.split(None, 1)
        if parts and parts[0].upper() == 'CONSTANT' and len(parts) > 1:
            self._define(parts[1], loc)
            return True
        if parts and parts[0].upper().split('(')[0].replace('_', '-') in ('COMP-1', 'COMP1'):
            # $SET COMP-1(BINARY) / $SET COMP1 "float": what COMP-1 means from
            # here on (Micro Focus; GnuCOBOL honours it too). The argument comes
            # either in parentheses or as a quoted word after a space.
            word = parts[0]
            if '(' in word:
                arg = word[word.index('(') + 1:].rstrip(')')
            else:
                arg = parts[1].strip() if len(parts) > 1 else ''
            arg = arg.strip().strip('"\'').upper()
            if arg == 'BINARY':
                self.comp1_binary = True
                return True
            if arg == 'FLOAT':
                self.comp1_binary = False
                return True
            return False
        if parts and parts[0].upper() == 'DPC-IN-DATA':
            # $SET DPC-IN-DATA "JSON": the decimal comma inside JSON numbers
            val = parts[1].strip().strip('"\'').lower() if len(parts) > 1 else 'all'
            self.dpc_in_data = val if val in ('json', 'xml', 'all', 'none') else 'all'
            return True
        return False

    def _dollar(self, s, loc):
        """Micro Focus $IF / $ELSE / $END / $DISPLAY / $SET name"""
        parts = s.split(None, 1)
        word = parts[0].upper() if parts else ''
        rest = parts[1] if len(parts) > 1 else ''
        if word == 'IF':
            on = self.active and self._cond(rest, loc)
            self.stack.append([on, on, 'IF'])
            return True
        if word == 'ELSE':
            e = self._top('IF', '$ELSE', loc)
            on = self._outer_active() and not e[1]
            e[0] = on
            e[1] = True
            return True
        if word == 'END':
            self._top('IF', '$END', loc)
            self.stack.pop()
            return True
        if word == 'DISPLAY':
            if self.active:
                print(rest.strip())
            return True
        if word == 'SET':
            if not self.active:
                return True             # $SET in skipped code takes no effect
            return self._set(rest, loc)
        return False

    def const_at(self, name, line):
        """The value of a text constant as it stood at `line`."""
        val = None
        for ln, nm, v in self.const_history:
            if nm == name and ln <= line:
                val = v
        return val

    # ------------------------------------------------------------ conditions
    def check_at(self, path, line):
        """Are bounds checks on at this source position? None when the
        directives say nothing, so the compile-wide flag decides."""
        state = None
        for f, l, on in self.check_changes:
            if f == path and l < line:
                state = on
        return state

    def _cond(self, text, loc):
        return _Expr(_tokens(text, loc), self, loc).cond()


def _literal_value(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in '"\'' and v[-1] == v[0]:
        q = v[0]
        return v[1:-1].replace(q + q, q)
    try:
        return Decimal(v.replace(',', '.'))
    except InvalidOperation:
        return v


def _tokens(text, loc):
    out = []
    i = 0
    text = text.rstrip().rstrip('.')
    while i < len(text):
        if text[i:].strip() == '':
            break
        m = _TOKEN.match(text, i)
        if not m:
            raise CompileError(f"invalid compiler directive: {text.strip()}", loc)
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


class _Expr:
    """Conditions and arithmetic of compiler directives."""

    def __init__(self, toks, d, loc):
        self.t = toks
        self.i = 0
        self.d = d
        self.loc = loc

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def word(self, *ws):
        kind, v = self.peek()
        return kind == 'word' and v.upper() in ws

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def err(self):
        return CompileError("invalid condition in compiler directive", self.loc)

    # cond := and { OR and }
    def cond(self):
        v = self._and()
        while self.word('OR'):
            self.take()
            r = self._and()
            v = v or r
        if self.i < len(self.t):
            raise self.err()
        return v

    def _and(self):
        v = self._not()
        while self.word('AND'):
            self.take()
            r = self._not()
            v = v and r
        return v

    def _not(self):
        if self.word('NOT'):
            self.take()
            return not self._not()
        return self._simple()

    def _simple(self):
        kind, v = self.peek()
        if kind == 'op' and v == '(':
            save = self.i
            self.take()
            try:
                r = self._or_inner()
                if self.peek() == ('op', ')'):
                    self.take()
                    return r
            except CompileError:
                pass
            self.i = save                   # an arithmetic parenthesis
        if kind == 'word' and not self._is_relop(1):
            name = v.upper()
            k2 = 1
            if self.word_at(k2, 'IS'):
                k2 += 1
            neg = False
            if self.word_at(k2, 'NOT'):
                neg = True
                k2 += 1
            if self.word_at(k2, 'DEFINED'):
                self.i += k2 + 1
                return (name in self.d.vars or name in getattr(self.d, 'constants', ())) != neg
            if self.word_at(k2, 'SET'):
                self.i += k2 + 1
                return (name in self.d.vars) != neg
        left = self.arith()
        if self.word('IS'):
            self.take()
        neg = False
        if self.word('NOT'):
            self.take()
            neg = True
        op = self._relop()
        if op is None:
            raise self.err()
        right = self.arith()
        r = _compare(left, op, right)
        return r != neg

    def _or_inner(self):
        v = self._and()
        while self.word('OR'):
            self.take()
            r = self._and()
            v = v or r
        return v

    def word_at(self, k, w):
        kind, v = self.peek(k)
        return kind == 'word' and v.upper() == w

    def _is_relop(self, k):
        kind, v = self.peek(k)
        return kind == 'op' and v in ('=', '<', '>', '<=', '>=', '<>')

    def _relop(self):
        kind, v = self.peek()
        if kind == 'op' and v in ('=', '<', '>', '<=', '>=', '<>'):
            self.take()
            return v
        if kind == 'word':
            u = v.upper()
            words = {'EQUAL': '=', 'EQUALS': '=', 'GREATER': '>', 'LESS': '<'}
            if u in words:
                self.take()
                op = words[u]
                if self.word('THAN', 'TO'):
                    self.take()
                if self.word('OR'):
                    self.take()
                    self.take()             # EQUAL
                    if self.word('TO'):
                        self.take()
                    op += '='
                return op
        return None

    # arith := term { (+|-) term }
    def arith(self):
        v = self._term()
        while self.peek() in (('op', '+'), ('op', '-')):
            op = self.take()[1]
            r = self._term()
            v = _num(v, self.loc) + _num(r, self.loc) if op == '+' else _num(v, self.loc) - _num(r, self.loc)
        return v

    def _term(self):
        v = self._factor()
        while self.peek() in (('op', '*'), ('op', '/')):
            op = self.take()[1]
            r = self._factor()
            if op == '*':
                v = _num(v, self.loc) * _num(r, self.loc)
            else:
                v = _num(v, self.loc) / _num(r, self.loc)
        return v

    def _factor(self):
        kind, v = self.take()
        if kind == 'num':
            return Decimal(v.replace(',', '.'))
        if kind == 'str':
            q = v[0]
            return v[1:-1].replace(q + q, q)
        if kind == 'op' and v == '(':
            r = self.arith()
            if self.take() != ('op', ')'):
                raise self.err()
            return r
        if kind == 'op' and v == '-':
            return -_num(self._factor(), self.loc)
        if kind == 'word':
            name = v.upper()
            if name in self.d.vars:
                return self.d.vars[name]
            if name in ('TRUE', 'FALSE'):
                return name == 'TRUE'
            # an undefined variable is simply "not set": a conditional such as
            # >>IF VERSION = 3 must work when VERSION is not defined at all
            return UNSET
        raise self.err()


def _num(v, loc):
    if isinstance(v, Decimal):
        return v
    if v is True:
        return Decimal(1)
    raise CompileError("numeric value expected in compiler directive", loc)


def _compare(a, op, b):
    if a is UNSET or b is UNSET:
        return False
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        c = (a > b) - (a < b)
    else:
        sa, sb = str(a), str(b)
        n = max(len(sa), len(sb))
        sa, sb = sa.ljust(n), sb.ljust(n)
        c = (sa > sb) - (sa < sb)
    return {'=': c == 0, '<': c < 0, '>': c > 0, '<=': c <= 0, '>=': c >= 0, '<>': c != 0}[op]
