"""Tokenizer, COPY and REPLACE processing."""
import os
import re

from . import source
from .errors import CompileError, DIAG
from .nodes import Loc


class Tok:
    __slots__ = ('kind', 'val', 'up', 'loc', 'sep')

    def __init__(self, kind, val, loc, up=None):
        self.kind = kind          # WORD NUM STR PIC . ( ) : OP PSEUDO EOF
        self.val = val
        self.loc = loc
        self.up = up if up is not None else val
        self.sep = False          # '(' directly preceded by a comma/semicolon separator

    def __repr__(self):
        return f"Tok({self.kind},{self.val!r})"

    def same(self, other):
        if self.kind != other.kind:
            return False
        if self.kind == 'WORD':
            return self.up == other.up
        return self.val == other.val

    def clone(self, loc=None):
        return Tok(self.kind, self.val, loc or self.loc, self.up)


_WORD_CH = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')


class Lexer:
    def __init__(self, decimal_comma=False):
        self.decimal_comma = decimal_comma
        self.pic_pending = False
        self.pseudo = None        # (raw text, loc) while inside multi-line pseudo text

    def lex_lines(self, lines):
        toks = []
        for ll in lines:
            self.lex_text(ll.text, ll.loc, toks)
        if self.pseudo is not None:
            raise CompileError("unterminated pseudo-text", self.pseudo[1])
        return toks

    def lex_text(self, text, loc, toks):
        n = len(text)
        i = 0
        dp = ',' if self.decimal_comma else '.'
        if self.pseudo is not None:
            end = text.find('==')
            if end < 0:
                self.pseudo = (self.pseudo[0] + ' ' + text, self.pseudo[1])
                return
            toks.append(Tok('PSEUDO', self.pseudo[0] + ' ' + text[:end], self.pseudo[1]))
            self.pseudo = None
            i = end + 2
        while i < n:
            c = text[i]
            if c == ' ':
                i += 1
                continue
            if self.pic_pending:
                j = i
                while j < n and text[j] != ' ':
                    j += 1
                s = text[i:j]
                if s.upper() == 'IS':
                    toks.append(Tok('WORD', s, loc, 'IS'))
                    i = j
                    continue
                period = False
                if len(s) > 1 and s[-1] in '.,;':
                    period = s[-1] == '.'
                    s = s[:-1]
                elif s in ('.',):
                    raise CompileError("missing PICTURE string", loc)
                toks.append(Tok('PIC', s, loc, s.upper()))
                if period:
                    toks.append(Tok('.', '.', loc))
                self.pic_pending = False
                i = j
                continue
            if c in ',;':
                if (c == ',' and self.decimal_comma and i + 1 < n and text[i + 1].isdigit()
                        and i > 0 and text[i - 1] in ' (+-='):
                    pass  # decimal-comma number like ,5 handled below
                else:
                    self.sep_at = len(toks)
                    i += 1
                    continue
            if c in '"\'':
                val, i = self._literal(text, i, loc)
                toks.append(Tok('STR', val, loc))
                continue
            if c in 'XxZzNn' and i + 1 < n and text[i + 1] in '"\'':
                val, i = self._literal(text, i + 1, loc)
                k = c.upper()
                if k == 'X':
                    h = val.decode('latin-1').replace(' ', '')
                    if len(h) % 2 or not re.fullmatch(r'[0-9A-Fa-f]*', h):
                        raise CompileError(f"invalid hexadecimal literal X\"{h}\"", loc)
                    val = bytes.fromhex(h)
                elif k == 'Z':
                    val = val + b'\x00'
                toks.append(Tok('STR', val, loc))
                continue
            # numbers (possibly signed) and words starting with digits
            if c.isdigit() or (c == dp and i + 1 < n and text[i + 1].isdigit()) or (
                    c in '+-' and i + 1 < n and (text[i + 1].isdigit() or
                                                 (text[i + 1] == dp and i + 2 < n and text[i + 2].isdigit()))
                    and (i == 0 or text[i - 1] in ' (=:')):
                j = i
                if text[j] in '+-':
                    j += 1
                k = j
                while k < n and text[k].isdigit():
                    k += 1
                if c not in '+-' and k < n and (text[k].isalpha() or text[k] == '_' or
                                                 (text[k] == '-' and k + 1 < n and (text[k + 1].isalnum() or text[k + 1] == '-'))):
                    # a word beginning with digits (paragraph names like 100-MAIN)
                    k = i
                    while k < n and text[k] in _WORD_CH:
                        k += 1
                    w = text[i:k]
                    toks.append(Tok('WORD', w, loc, w.upper()))
                    i = k
                    continue
                if k < n and text[k] == dp and k + 1 < n and text[k + 1].isdigit():
                    k += 1
                    while k < n and text[k].isdigit():
                        k += 1
                elif k == j and k < n and text[k] == dp:
                    k += 1
                    while k < n and text[k].isdigit():
                        k += 1
                # floating point literal  1.5E+3
                if k < n and text[k] in 'Ee' and k + 1 < n and (text[k + 1] in '+-' or text[k + 1].isdigit()):
                    m = re.match(r'[Ee][+-]?\d+', text[k:])
                    if m and (k + m.end() >= n or text[k + m.end()] in ' .,;)'):
                        lit = text[i:k].replace(',', '.') if self.decimal_comma else text[i:k]
                        expo = int(m.group(0)[1:])
                        toks.append(Tok('NUM', _float_to_fixed(lit, expo), loc))
                        i = k + m.end()
                        continue
                lit = text[i:k]
                if self.decimal_comma:
                    lit = lit.replace(',', '.')
                toks.append(Tok('NUM', lit, loc))
                i = k
                continue
            if c.isalpha() or c == '_':
                k = i + 1
                while k < n and text[k] in _WORD_CH:
                    k += 1
                w = text[i:k]
                up = w.upper()
                toks.append(Tok('WORD', w, loc, up))
                if up in ('PIC', 'PICTURE'):
                    self.pic_pending = True
                i = k
                continue
            if c == '.':
                toks.append(Tok('.', '.', loc))
                i += 1
                continue
            if c in '():':
                t = Tok(c, c, loc)
                if c == '(' and getattr(self, 'sep_at', -1) == len(toks):
                    t.sep = True
                toks.append(t)
                i += 1
                continue
            if c == '=':
                if i + 1 < n and text[i + 1] == '=':
                    end = text.find('==', i + 2)
                    if end < 0:
                        self.pseudo = (text[i + 2:], loc)
                        return
                    toks.append(Tok('PSEUDO', text[i + 2:end], loc))
                    i = end + 2
                    continue
                toks.append(Tok('OP', '=', loc))
                i += 1
                continue
            if c in '<>':
                if i + 1 < n and text[i + 1] == '=':
                    toks.append(Tok('OP', c + '=', loc))
                    i += 2
                elif c == '<' and i + 1 < n and text[i + 1] == '>':
                    toks.append(Tok('OP', '<>', loc))
                    i += 2
                else:
                    toks.append(Tok('OP', c, loc))
                    i += 1
                continue
            if c == '*':
                if i + 1 < n and text[i + 1] == '*':
                    toks.append(Tok('OP', '**', loc))
                    i += 2
                else:
                    toks.append(Tok('OP', '*', loc))
                    i += 1
                continue
            if c in '+-/&':
                toks.append(Tok('OP', c, loc))
                i += 1
                continue
            raise CompileError(f"unexpected character '{c}'", loc)

    @staticmethod
    def _literal(text, i, loc):
        q = text[i]
        i += 1
        n = len(text)
        buf = []
        while True:
            j = text.find(q, i)
            if j < 0:
                raise CompileError("unterminated alphanumeric literal", loc)
            buf.append(text[i:j])
            if j + 1 < n and text[j + 1] == q:
                buf.append(q)
                i = j + 2
                continue
            i = j + 1
            break
        return ''.join(buf).encode('latin-1'), i


def _float_to_fixed(mant, expo):
    neg = mant.startswith('-')
    mant = mant.lstrip('+-')
    if '.' in mant:
        ip, fp = mant.split('.')
    else:
        ip, fp = mant, ''
    digits = ip + fp
    point = len(ip) + expo
    if point <= 0:
        s = '0.' + '0' * (-point) + digits
    elif point >= len(digits):
        s = digits + '0' * (point - len(digits))
    else:
        s = digits[:point] + '.' + digits[point:]
    return ('-' if neg else '') + s


# ---------------------------------------------------------------- driver

class SourceSet:
    """Loads a source file, expands COPY / REPLACE, returns tokens."""

    COPY_EXTS = ['', '.cpy', '.CPY', '.cbl', '.CBL', '.cob', '.COB', '.copy', '.COPY', '.cbx']

    def __init__(self, include_dirs=(), fmt='auto', debugging=False):
        self.include_dirs = list(include_dirs)
        env = os.environ.get('COBCPY')
        if env:
            self.include_dirs.extend(p for p in env.split(os.pathsep) if p)
        self.fmt = fmt
        self.debugging = debugging
        self.decimal_comma = False

    def load(self, path):
        raw = source.read_raw(path)
        if re.search(r'DECIMAL-POINT\s+IS\s+COMMA|DECIMAL-POINT\s+COMMA', '\n'.join(raw), re.I):
            self.decimal_comma = True
        toks = self._tokenize(path, raw, 0)
        toks = _concat_literals(toks)
        toks = _apply_replace_stmts(toks)
        last = toks[-1].loc if toks else Loc(path, 1)
        toks.append(Tok('EOF', '', last))
        return toks

    def _tokenize(self, path, raw, depth, text_repl=None):
        if depth > 40:
            raise CompileError("COPY nesting too deep (recursive COPY?)", Loc(path, 1))
        if text_repl:
            new = []
            for line in raw:
                for a, b in text_repl:
                    line = line.replace(a, b)
                new.append(line)
            raw = new
        fmt = self.fmt if self.fmt != 'auto' else source.detect_format(raw)
        lines = source.process(raw, path, fmt, self.debugging)
        lx = Lexer(self.decimal_comma)
        toks = lx.lex_lines(lines)
        return self._expand_copy(toks, path, depth)

    def _expand_copy(self, toks, path, depth):
        out = []
        i = 0
        n = len(toks)
        while i < n:
            t = toks[i]
            if not (t.kind == 'WORD' and t.up == 'COPY'):
                out.append(t)
                i += 1
                continue
            loc = t.loc
            j = i + 1
            if j >= n or toks[j].kind not in ('WORD', 'STR'):
                raise CompileError("COPY: copybook name expected", loc)
            nt = toks[j]
            name = nt.val.decode('latin-1') if nt.kind == 'STR' else nt.val
            j += 1
            lib = None
            if j < n and toks[j].kind == 'WORD' and toks[j].up in ('OF', 'IN'):
                lt = toks[j + 1]
                lib = lt.val.decode('latin-1') if lt.kind == 'STR' else lt.val
                j += 2
            if j < n and toks[j].kind == 'WORD' and toks[j].up == 'SUPPRESS':
                j += 1
                if j < n and toks[j].kind == 'WORD' and toks[j].up == 'PRINTING':
                    j += 1
            repl = []
            text_repl = []
            if j < n and toks[j].kind == 'WORD' and toks[j].up == 'REPLACING':
                j += 1
                while j < n and toks[j].kind != '.':
                    mode = ''
                    if toks[j].kind == 'WORD' and toks[j].up in ('LEADING', 'TRAILING'):
                        mode = toks[j].up
                        j += 1
                    a, j, a_raw = _repl_operand(toks, j, loc)
                    if not (j < n and toks[j].kind == 'WORD' and toks[j].up == 'BY'):
                        raise CompileError("COPY REPLACING: BY expected", loc)
                    j += 1
                    b, j, b_raw = _repl_operand(toks, j, loc)
                    if a_raw is not None and a_raw.strip()[:1] in (':', '(') and not mode:
                        text_repl.append((a_raw.strip(), (b_raw or '').strip()))
                    else:
                        repl.append((a, b, mode))
            if j >= n or toks[j].kind != '.':
                raise CompileError("COPY statement must end with a period", loc)
            j += 1
            cpath = self._find(name, lib, path, loc)
            sub = self._tokenize(cpath, source.read_raw(cpath), depth + 1, text_repl)
            if repl:
                sub = _apply_replacing(sub, repl)
            out.extend(sub)
            i = j
        return out

    def _find(self, name, lib, from_path, loc):
        dirs = [os.path.dirname(os.path.abspath(from_path))] + self.include_dirs + ['.']
        names = [name]
        if name.upper() != name:
            names.append(name.upper())
        if name.lower() != name:
            names.append(name.lower())
        for d in dirs:
            bases = [d]
            if lib:
                bases.insert(0, os.path.join(d, lib))
            for b in bases:
                for nm in names:
                    for ext in self.COPY_EXTS:
                        p = os.path.join(b, nm + ext)
                        if os.path.isfile(p):
                            return p
        raise CompileError(f"copybook '{name}' not found", loc)


def _lex_snippet(text, loc):
    lx = Lexer()
    toks = []
    lx.lex_text(text, loc, toks)
    return toks


def _repl_operand(toks, j, loc):
    t = toks[j]
    if t.kind == 'PSEUDO':
        return _lex_snippet(t.val, t.loc), j + 1, t.val
    if t.kind == 'WORD':
        # identifier: qualifiers, subscripts and reference modification
        out = [t]
        j += 1
        n = len(toks)
        while j + 1 < n and toks[j].kind == 'WORD' and toks[j].up in ('IN', 'OF') and toks[j + 1].kind == 'WORD':
            out.extend(toks[j:j + 2])
            j += 2
        while j < n and toks[j].kind == '(':
            depth = 0
            while j < n:
                out.append(toks[j])
                if toks[j].kind == '(':
                    depth += 1
                elif toks[j].kind == ')':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
        return out, j, None
    if t.kind in ('STR', 'NUM'):
        return [t], j + 1, None
    raise CompileError("COPY REPLACING: invalid operand", loc)


def _apply_replacing(toks, repl):
    out = []
    i = 0
    n = len(toks)
    while i < n:
        done = False
        for a, b, mode in repl:
            if mode:
                t = toks[i]
                if t.kind == 'WORD' and len(a) == 1 and a[0].kind == 'WORD':
                    pat = a[0].up
                    rep = b[0].val if b else ''
                    if mode == 'LEADING' and t.up.startswith(pat):
                        w = rep + t.val[len(pat):]
                        out.append(Tok('WORD', w, t.loc, w.upper()))
                        i += 1
                        done = True
                        break
                    if mode == 'TRAILING' and t.up.endswith(pat):
                        w = t.val[:len(t.val) - len(pat)] + rep
                        out.append(Tok('WORD', w, t.loc, w.upper()))
                        i += 1
                        done = True
                        break
                continue
            la = len(a)
            if la == 0 or i + la > n:
                continue
            if all(toks[i + k].same(a[k]) for k in range(la)):
                for bt in b:
                    out.append(bt.clone(toks[i].loc))
                i += la
                done = True
                break
        if not done:
            out.append(toks[i])
            i += 1
    return out


def _concat_literals(toks):
    out = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if (t.kind == 'OP' and t.val == '&' and out and out[-1].kind == 'STR'
                and i + 1 < n and toks[i + 1].kind == 'STR'):
            prev = out.pop()
            out.append(Tok('STR', prev.val + toks[i + 1].val, prev.loc))
            i += 2
            continue
        out.append(t)
        i += 1
    return out


def _apply_replace_stmts(toks):
    if not any(t.kind == 'WORD' and t.up == 'REPLACE' for t in toks):
        return toks
    out = []
    active = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.kind == 'WORD' and t.up == 'REPLACE':
            j = i + 1
            if j < n and toks[j].kind == 'WORD' and toks[j].up == 'OFF':
                active = []
                j += 1
            else:
                rules = []
                if j < n and toks[j].kind == 'WORD' and toks[j].up == 'ALSO':
                    rules = list(active)
                    j += 1
                while j < n and toks[j].kind != '.':
                    mode = ''
                    if toks[j].kind == 'WORD' and toks[j].up in ('LEADING', 'TRAILING'):
                        mode = toks[j].up
                        j += 1
                    a, j, _ = _repl_operand(toks, j, t.loc)
                    if not (toks[j].kind == 'WORD' and toks[j].up == 'BY'):
                        raise CompileError("REPLACE: BY expected", t.loc)
                    b, j, _ = _repl_operand(toks, j + 1, t.loc)
                    rules.append((a, b, mode))
                active = rules
            if j < n and toks[j].kind == '.':
                j += 1
            i = j
            continue
        # find end of current run (until next REPLACE)
        j = i
        while j < n and not (toks[j].kind == 'WORD' and toks[j].up == 'REPLACE'):
            j += 1
        seg = toks[i:j]
        out.extend(_apply_replacing(seg, active) if active else seg)
        i = j
    return out
