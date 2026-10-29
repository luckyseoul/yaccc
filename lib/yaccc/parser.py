# SPDX-License-Identifier: MIT
"""Recursive-descent parser for COBOL."""
import re
from decimal import Decimal

from .data import DataItem, Occurs, Picture
from .errors import CompileError, DIAG
from .nodes import *
from .words import (FIGURATIVES, FIG_BYTES, FUNCTIONS, RESERVED, USAGES, VERBS,
                    CONTEXT_WORDS)

SPECIAL_REGISTERS = {'RETURN-CODE', 'TALLY', 'SORT-RETURN', 'WHEN-COMPILED',
                     'NUMBER-OF-CALL-PARAMETERS', 'LINE-COUNTER', 'PAGE-COUNTER'}

# words that begin a clause in a REPORT SECTION entry (never a data-name there)
RW_CLAUSE_WORDS = {'LINE', 'LINES', 'NEXT', 'TYPE', 'COLUMN', 'COL', 'SOURCE', 'SUM', 'GROUP',
                   'RESET', 'UPON', 'PIC', 'PICTURE', 'VALUE', 'USAGE', 'SIGN', 'JUST',
                   'JUSTIFIED', 'BLANK', 'IS', 'DISPLAY', 'PRESENT'}
RW_TYPES = {'RH': 'RH', 'PH': 'PH', 'CH': 'CH', 'DE': 'DE', 'CF': 'CF', 'PF': 'PF', 'RF': 'RF',
            'DETAIL': 'DE'}

RELOP_SYM = {'=': 'EQ', '<': 'LT', '>': 'GT', '<=': 'LE', '>=': 'GE', '<>': 'NE'}
NEGATE = {'EQ': 'NE', 'NE': 'EQ', 'LT': 'GE', 'GE': 'LT', 'GT': 'LE', 'LE': 'GT'}

CLASS_WORDS = {'NUMERIC', 'ALPHABETIC', 'ALPHABETIC-LOWER', 'ALPHABETIC-UPPER', 'ALPHANUMERIC'}
SIGN_WORDS = {'POSITIVE': 'POSITIVE', 'NEGATIVE': 'NEGATIVE', 'ZERO': 'ZERO',
              'ZEROS': 'ZERO', 'ZEROES': 'ZERO'}

DIVISION_STARTS = {'IDENTIFICATION', 'ID', 'ENVIRONMENT', 'DATA', 'PROCEDURE'}


class ParseError(CompileError):
    pass


class Backtrack(Exception):
    pass


def make_numlit(text, loc=None):
    t = text
    neg = t.startswith('-')
    t = t.lstrip('+-')
    if '.' in t:
        ip, fp = t.split('.', 1)
    else:
        ip, fp = t, ''
    digits = (ip + fp).lstrip('0') or '0'
    full = ip + fp
    if len(full.lstrip('0')) > 38:
        raise CompileError(f"numeric literal '{text}' has too many digits", loc)
    return NumLit(text=text, digits=(ip + fp) if (ip + fp) else '0', scale=len(fp), neg=neg)


def fold_constant(e, sizes=None):
    """A constant expression as a literal when it can be computed now:
    arithmetic of numeric literals and LENGTH OF a literal. Otherwise the
    expression itself (LENGTH OF a data item is computed where it is used).
    As in GnuCOBOL (and Micro Focus level 78), the value of an expression is
    an integer: each division and the final result are truncated toward zero."""
    from decimal import Decimal, getcontext, ROUND_DOWN
    getcontext().prec = 60

    def trunc(v):
        return v.quantize(Decimal(1), rounding=ROUND_DOWN)

    def val(x):
        if isinstance(x, NumLit):
            return Decimal(x.text)
        if isinstance(x, LengthOf) and isinstance(x.ref, StrLit):
            return Decimal(len(x.ref.value))
        if isinstance(x, LengthOf) and isinstance(x.ref, DataRef):
            # LENGTH OF an item already declared: its PICTURE fixes the size
            n = getattr(getattr(x.ref, 'item', None), 'decl_size', None)
            if n is None and sizes is not None:
                n = sizes.get(x.ref.name)
            return None if n is None else Decimal(n)
        if isinstance(x, Neg):
            v = val(x.e)
            return None if v is None else -v
        if isinstance(x, BinOp):
            a, b = val(x.left), val(x.right)
            if a is None or b is None:
                return None
            if x.op == '+':
                return a + b
            if x.op == '-':
                return a - b
            if x.op == '*':
                return a * b
            if x.op == '/':
                return trunc(a / b) if b else None
            if x.op == '**':
                return a ** b if b == int(b) else None
        return None
    if isinstance(e, (NumLit, StrLit, Figurative, AllLit)):
        return e
    v = val(e)
    if v is None:
        return e
    v = trunc(v).normalize()
    t = format(v, 'f')
    if '.' in t:
        t = t.rstrip('0').rstrip('.')
    return make_numlit(t)


SELECT_CLAUSE_WORDS = {'ORGANIZATION', 'ACCESS', 'RECORD', 'ALTERNATE', 'RELATIVE', 'FILE', 'STATUS',
                       'LOCK', 'RESERVE', 'PADDING', 'SHARING', 'COLLATING', 'INDEXED', 'SEQUENTIAL',
                       'LINE', 'OPTIONAL'}

ROUNDING_MODES = ('AWAY-FROM-ZERO', 'NEAREST-AWAY-FROM-ZERO', 'NEAREST-EVEN', 'NEAREST-TOWARD-ZERO',
                  'PROHIBITED', 'TOWARD-GREATER', 'TOWARD-LESSER', 'TRUNCATION')


class Parser:
    def __init__(self, toks, compile_vars=None):
        self.toks = toks
        self.compile_vars = compile_vars if compile_vars is not None else {}
        self.pos = 0
        self.udfs = set()
        self.decl_sizes = {}
        self.prog = None
        self.subj = None
        self.relop = None
        self.class_names = set()
        self.mnemonics = {}

    # ---------------------------------------------------------- token helpers
    def peek(self, k=0):
        p = self.pos + k
        if p < len(self.toks):
            return self.toks[p]
        return self.toks[-1]

    def next(self):
        t = self.toks[self.pos]
        if t.kind != 'EOF':
            self.pos += 1
        return t

    def is_word(self, *ws, k=0):
        t = self.peek(k)
        return t.kind == 'WORD' and (not ws or t.up in ws)

    def accept(self, *ws):
        if self.is_word(*ws):
            return self.next()
        return None

    def expect(self, *ws):
        t = self.peek()
        if t.kind == 'WORD' and t.up in ws:
            return self.next()
        raise self.err(f"expected {' or '.join(ws)}")

    def is_kind(self, kind, k=0):
        return self.peek(k).kind == kind

    def accept_kind(self, kind):
        if self.peek().kind == kind:
            return self.next()
        return None

    def accept_op(self, op):
        t = self.peek()
        if t.kind == 'OP' and t.val == op:
            return self.next()
        return None

    def expect_kind(self, kind, what=None):
        t = self.peek()
        if t.kind == kind:
            return self.next()
        raise self.err(f"expected {what or repr(kind)}")

    def expect_period(self):
        if self.peek().kind == '.':
            self.next()
            return
        if getattr(self, 'missing_period', False) and self.peek().kind != 'EOF':
            return                          # -fmissing-period / a lenient dialect
        raise self.err("expected '.'")

    def skip_periods(self):
        while self.peek().kind == '.':
            self.next()

    def desc(self, t):
        if t.kind == 'EOF':
            return 'end of file'
        if t.kind == 'STR':
            return '"' + t.val.decode('latin-1') + '"'
        return str(t.val)

    def err(self, msg, t=None):
        t = t or self.peek()
        return ParseError(f"{msg}, found '{self.desc(t)}'", t.loc)

    def is_user_word(self, k=0):
        t = self.peek(k)
        return t.kind == 'WORD' and (t.up not in RESERVED or t.up in SPECIAL_REGISTERS)

    def user_word(self, what='name'):
        t = self.peek()
        if t.kind == 'WORD' and t.up not in RESERVED:
            self.next()
            return t.up
        raise self.err(f"{what} expected")

    def skip_to_period(self):
        while self.peek().kind not in ('.', 'EOF'):
            self.next()
        self.accept_kind('.')

    # ---------------------------------------------------------- program
    def parse_unit(self):
        progs = []
        while self.peek().kind != 'EOF':
            if self.peek().kind == '.':
                self.next()
                continue
            progs.append(self.parse_program(None))
        if not progs:
            raise CompileError("no program found")
        return progs

    def parse_program(self, parent):
        loc = self.peek().loc
        if self.accept('IDENTIFICATION', 'ID'):
            self.expect('DIVISION')
            self.expect_period()
        is_function = False
        if self.is_word('FUNCTION-ID'):
            self.next()
            is_function = True
        else:
            self.expect('PROGRAM-ID')
        self.accept_kind('.')
        t = self.next()
        if t.kind == 'STR':
            name = ext = t.val.decode('latin-1').strip()
        elif t.kind == 'WORD':
            name, ext = t.up, t.val     # CALL matches the name as written first
        else:
            raise self.err("program name expected", t)
        prog = Program(name=name, loc=loc)
        prog.is_function = is_function
        prog.ext_name = ext
        prog.parent = parent
        self.prog = prog
        self.class_names = set()
        self.mnemonics = {}
        if self.accept('AS'):
            t = self.next()
            if t.kind != 'STR':
                raise self.err("literal expected after AS", t)
            prog.ext_name = t.val.decode('latin-1').strip()
        self.accept('IS')
        while self.is_word('INITIAL', 'RECURSIVE', 'COMMON'):
            w = self.next().up
            if w == 'INITIAL':
                prog.is_initial = True
            elif w == 'RECURSIVE':
                prog.is_recursive = True
            else:
                prog.is_common = True
        self.accept('PROGRAM')
        self.accept_kind('.')
        while self.is_word('AUTHOR', 'INSTALLATION', 'DATE-WRITTEN', 'DATE-COMPILED',
                           'SECURITY', 'REMARKS'):
            self.next()
            self.accept_kind('.')
        if self.is_word('OPTIONS') and self.peek(1).kind == '.':
            self._options_paragraph(prog)
        if self.is_word('ENVIRONMENT'):
            self.parse_environment(prog)
        if self.is_word('DATA'):
            self.parse_data(prog)
        if self.is_word('PROCEDURE'):
            self.parse_procedure(prog)
        # nested programs: only if our END PROGRAM appears later
        while self.is_word('IDENTIFICATION', 'ID', 'PROGRAM-ID', 'FUNCTION-ID') and \
                self._end_program_ahead(name):
            prog.nested.append(self.parse_program(prog))
            self.prog = prog
        if self.is_word('END') and (self.is_word('PROGRAM', k=1) or self.is_word('FUNCTION', k=1)):
            self.next()
            self.next()
            t = self.next()
            ename = t.val.decode('latin-1').strip() if t.kind == 'STR' else t.up
            if ename.upper() != name.upper():
                DIAG.warn(f"END PROGRAM name '{ename}' does not match '{name}'", t.loc)
            self.accept_kind('.')
        return prog

    def _options_paragraph(self, prog):
        """OPTIONS paragraph (COBOL 2014): DEFAULT ROUNDED MODE; other entries
        are accepted and ignored."""
        self.next()
        self.next()
        while self.peek().kind != 'EOF' and not (self.is_word('ENVIRONMENT', 'DATA', 'PROCEDURE')
                                                 and self.is_word('DIVISION', k=1)):
            if self.is_word('DEFAULT') and self.is_word('ROUNDED', k=1):
                self.next()
                self.next()
                self.accept('MODE')
                self.accept('IS')
                t = self.next()
                if t.up not in ROUNDING_MODES:
                    raise ParseError(f"invalid rounding mode '{t.val}'", t.loc)
                prog.default_rounded = t.up
            else:
                self.next()

    def _end_program_ahead(self, name):
        depth = 0
        for i in range(self.pos, len(self.toks) - 2):
            t = self.toks[i]
            if t.kind == 'WORD' and t.up == 'END' and self.toks[i + 1].kind == 'WORD' and \
                    self.toks[i + 1].up in ('PROGRAM', 'FUNCTION'):
                nt = self.toks[i + 2]
                nm = nt.val.decode('latin-1').strip() if nt.kind == 'STR' else nt.up
                if nm.upper() == name.upper():
                    return True
        return False

    # ---------------------------------------------------------- environment
    def parse_environment(self, prog):
        self.expect('ENVIRONMENT')
        self.expect('DIVISION')
        self.expect_period()
        while True:
            if self.is_word('CONFIGURATION') and self.is_word('SECTION', k=1):
                self.next(); self.next(); self.expect_period()
            elif self.is_word('INPUT-OUTPUT') and self.is_word('SECTION', k=1):
                self.next(); self.next(); self.expect_period()
            elif self.accept('SOURCE-COMPUTER'):
                self.accept_kind('.')
                if not self._para_start():
                    while self.peek().kind not in ('.', 'EOF'):
                        if self.accept('DEBUGGING'):
                            prog.debugging = True
                        else:
                            self.next()
                    self.accept_kind('.')
            elif self.accept('OBJECT-COMPUTER'):
                self.accept_kind('.')
                if not self._para_start():
                    while self.peek().kind not in ('.', 'EOF'):
                        if self.is_word('PROGRAM') and self.is_word('COLLATING', k=1):
                            self.next(); self.next()
                            self.accept('SEQUENCE')
                            self.accept('IS')
                            prog.collating = self.next().up
                        elif self.is_word('COLLATING') and self.is_word('SEQUENCE', k=1):
                            self.next(); self.next()
                            self.accept('IS')
                            prog.collating = self.next().up
                        else:
                            self.next()
                    self.accept_kind('.')
            elif self.accept('SPECIAL-NAMES'):
                self.accept_kind('.')
                self.parse_special_names(prog)
            elif self.accept('REPOSITORY'):
                self.accept_kind('.')
                # REPOSITORY. FUNCTION f1 f2. PROGRAM p1 p2: names a program
                # may use as functions
                while not self._para_start() and self.peek().kind != 'EOF':
                    if self.is_word('FUNCTION', 'PROGRAM', 'CLASS'):
                        kind = self.next().up
                        if kind == 'FUNCTION':
                            while self.is_user_word():
                                self.udfs.add(self.next().up)
                            continue
                    self.skip_to_period()
            elif self.accept('FILE-CONTROL'):
                self.accept_kind('.')
                while self.is_word('SELECT'):
                    prog.file_controls.append(self.parse_select())
            elif self.accept('I-O-CONTROL'):
                self.accept_kind('.')
                while not self._para_start() and self.peek().kind != 'EOF':
                    if self.accept('SAME'):
                        rec = bool(self.accept('RECORD'))
                        if not rec:
                            self.accept('SORT', 'SORT-MERGE')
                        self.accept('AREA')
                        self.accept('FOR')
                        names = []
                        while self.is_user_word():
                            names.append(self.next().up)
                        if rec:
                            prog.same_record.append(names)
                    else:
                        self.next()
            else:
                break

    def _para_start(self):
        return self.is_word('SOURCE-COMPUTER', 'OBJECT-COMPUTER', 'SPECIAL-NAMES', 'REPOSITORY',
                            'FILE-CONTROL', 'I-O-CONTROL', 'DATA', 'PROCEDURE', 'CONFIGURATION',
                            'INPUT-OUTPUT', 'ENVIRONMENT', 'END') or self.peek().kind == 'EOF'

    # entries of SPECIAL-NAMES that may each end with a period
    SN_ENTRIES = {'ALPHABET', 'CLASS', 'CURRENCY', 'DECIMAL-POINT', 'SYMBOLIC',
                  'SWITCH', 'ALPHABETIC', 'MNEMONIC'}

    def parse_special_names(self, prog):
        while True:
            while self.peek().kind == '.':
                # a period ends an entry, not necessarily the paragraph: another
                # entry may follow (ALPHABET A IS ASCII. ALPHABET B IS EBCDIC.)
                nxt = self.peek(1)
                if nxt.kind == 'WORD' and (nxt.up in self.SN_ENTRIES or nxt.up.startswith('SWITCH')):
                    self.next()
                    continue
                break
            if self.peek().kind in ('.', 'EOF') or self._para_start():
                break
            if self.accept('DECIMAL-POINT'):
                self.accept('IS')
                self.expect('COMMA')
                prog.decimal_comma = True
            elif self.accept('CURRENCY'):
                self.accept('SIGN')
                self.accept('IS')
                t = self.expect_kind('STR', 'currency literal')
                cur = t.val.decode('latin-1')
                if len(cur) != 1:
                    raise CompileError("only single-character currency signs are supported", t.loc)
                prog.currency = cur
                if self.accept('WITH'):
                    self.expect('PICTURE')
                    self.next()
                    self.next()
            elif self.accept('CLASS'):
                name = self.user_word('class name')
                self.accept('IS')
                ranges = []
                while self.peek().kind in ('STR', 'NUM'):
                    lo = self._class_val(self.next())
                    hi = lo
                    if self.accept('THRU', 'THROUGH'):
                        hi = self._class_val(self.next())
                    ranges.append((lo, hi))
                prog.classes[name] = ranges
                self.class_names.add(name)
            elif self.accept('SYMBOLIC'):
                self.accept('CHARACTERS')
                names = []
                defined = []
                while True:
                    if self.is_user_word():
                        names.append(self.next().up)
                    elif self.accept('IS', 'ARE'):
                        pass
                    elif self.peek().kind == 'NUM':
                        vals = []
                        while self.peek().kind == 'NUM':
                            vals.append(int(self.next().val))
                        for nm, v in zip(names, vals):
                            prog.symbolic[nm] = v - 1
                            defined.append(nm)
                        names = []
                    else:
                        break
                if self.accept('IN'):
                    # ordinal positions in that alphabet: the native character
                    # with that code in it
                    spec = prog.alphabets.get(self.next().up)
                    if spec == 'EBCDIC':
                        for nm in defined:
                            prog.symbolic[nm] = bytes([prog.symbolic[nm]]).decode('cp037').encode('latin-1')[0]
            elif self.accept('ALPHABET'):
                aname = self.next().up
                self.accept('IS')
                spec = []
                if self.is_word('NATIVE', 'STANDARD-1', 'STANDARD-2', 'ASCII', 'EBCDIC'):
                    spec = self.next().up
                else:
                    while self.peek().kind in ('STR', 'NUM') or self.is_word(*FIGURATIVES.keys()):
                        group = [self._alpha_val()]
                        if self.accept('THRU', 'THROUGH'):
                            spec.append(('RANGE', group[0], self._alpha_val()))
                            continue
                        while self.accept('ALSO'):
                            group.append(self._alpha_val())
                        spec.append(('ALSO', group))
                prog.alphabets[aname] = spec
            elif self.is_word('CONSOLE', 'CRT', 'CURSOR'):
                self.next()
                self.accept('IS')
                self.accept('STATUS')
                self.accept('IS')
                self.next()
            elif self.peek().kind == 'WORD':
                env = self.next().up
                m = re.match(r'(?:SWITCH|UPSI)-?(\d+)$', env)
                if env in ('SWITCH', 'UPSI') and self.peek().kind == 'NUM':
                    m = re.match(r'(\d+)$', self.next().val)
                swno = int(m.group(1)) if m else None
                if self.accept('IS'):
                    mn = self.next().up
                    self.mnemonics[mn] = env
                    prog.mnemonics[mn] = env
                    if swno is not None:
                        prog.switches[mn] = swno
                while self.is_word('ON', 'OFF'):
                    on = self.next().up == 'ON'
                    self.accept('STATUS')
                    self.accept('IS')
                    cn = self.next().up
                    if swno is not None:
                        prog.switch_conds[cn] = (swno, on)
            else:
                raise self.err("unexpected entry in SPECIAL-NAMES")
        self.accept_kind('.')

    def _alpha_val(self):
        t = self.next()
        if t.kind == 'STR':
            return t.val
        if t.kind == 'NUM':
            return bytes([int(t.val) - 1])
        k = FIGURATIVES.get(t.up)
        return FIG_BYTES[k] if k else b' '

    @staticmethod
    def _class_val(t):
        if t.kind == 'STR':
            return t.val
        return bytes([int(t.val) - 1])

    def parse_select(self):
        loc = self.expect('SELECT').loc
        optional = bool(self.accept('OPTIONAL'))
        name = self.user_word('file name')
        fc = FileControl(name=name, assign=None, loc=loc, optional=optional)
        while self.peek().kind not in ('.', 'EOF'):
            if self.accept('ASSIGN'):
                self.accept('TO', 'USING')
                while self.is_word('DISK', 'PRINTER', 'KEYBOARD', 'DISPLAY', 'EXTERNAL', 'DYNAMIC',
                                   'TAPE', 'LINE', 'SEQUENTIAL', 'ADVANCING', 'MULTIPLE', 'REEL', 'UNIT') and \
                        not (self.is_word('LINE') and self.is_word('SEQUENTIAL', k=1)):
                    w = self.next().up
                    if w in ('KEYBOARD', 'DISPLAY'):
                        fc.assign_kind = w
                    elif w == 'PRINTER':
                        fc.assign_kind = 'PRINTER'
                    elif w == 'ADVANCING':
                        fc.organization = 'LINE SEQUENTIAL'      # LINE ADVANCING: a print file
                t = self.peek()
                if t.kind == 'STR':
                    self.next()
                    fc.assign = StrLit(t.val)
                elif t.kind == 'WORD' and t.up not in RESERVED and t.up not in SELECT_CLAUSE_WORDS:
                    fc.assign = self.parse_identifier()
            elif self.accept('ORGANIZATION', 'ORGANISATION'):
                self.accept('IS')
                self._parse_org(fc)
            elif (self.is_word('LINE', 'SEQUENTIAL', 'RELATIVE', 'INDEXED') and
                  not (self.is_word('RELATIVE') and (self.is_word('KEY', 'IS', k=1) or self.is_user_word(1)))) or (
                    self.is_word('RECORD') and self.is_word('SEQUENTIAL', 'BINARY', k=1)):
                self._parse_org(fc)
            elif self.accept('ACCESS'):
                self.accept('MODE')
                self.accept('IS')
                fc.access = self.expect('SEQUENTIAL', 'RANDOM', 'DYNAMIC').up
            elif self.is_word('RECORD') and self.is_word('DELIMITER', k=1):
                self.next(); self.next(); self.accept('IS'); self.next()
            elif self.accept('RECORD'):
                self.accept('KEY')
                self.accept('IS')
                fc.record_key = self.parse_identifier()
                # RECORD KEY IS key-name = data-name: the key's own name, then
                # the item that holds it
                if self.peek().kind == 'OP' and self.peek().val == '=':
                    self.next()
                    fc.key_name = fc.record_key
                    fc.record_key = self.parse_identifier()
                if self.is_word('SOURCE'):
                    raise self.err("split keys are not supported")
            elif self.accept('ALTERNATE'):
                self.accept('RECORD')
                self.accept('KEY')
                self.accept('IS')
                k = self.parse_identifier()
                dups = False
                if self.accept('WITH'):
                    self.expect('DUPLICATES')
                    dups = True
                elif self.accept('DUPLICATES'):
                    dups = True
                fc.alt_keys.append((k, dups))
            elif self.accept('RELATIVE'):
                self.accept('KEY')
                self.accept('IS')
                fc.relative_key = self.parse_identifier()
            elif self.accept('FILE'):
                self.expect('STATUS')
                self.accept('IS')
                fc.status = self.parse_identifier()
                if self.is_user_word():
                    self.parse_identifier()
            elif self.accept('STATUS'):
                self.accept('IS')
                fc.status = self.parse_identifier()
            elif self.accept('LOCK'):
                self.accept('MODE')
                self.accept('IS')
                while self.is_word('MANUAL', 'AUTOMATIC', 'EXCLUSIVE', 'WITH', 'LOCK', 'ON', 'MULTIPLE',
                                   'RECORD', 'RECORDS', 'ROLLBACK'):
                    self.next()
            elif self.accept('RESERVE'):
                self.next()
                self.accept('AREA', 'AREAS')
            elif self.accept('PADDING'):
                self.accept('CHARACTER')
                self.accept('IS')
                self.next()
            elif self.accept('SHARING'):
                self.accept('WITH')
                while self.is_word('ALL', 'OTHER', 'NO', 'READ', 'ONLY', 'OTHERS'):
                    self.next()
            elif self.accept('COLLATING'):
                self.accept('SEQUENCE')
                self.accept('IS')
                self.next()
            else:
                raise self.err("unexpected clause in SELECT")
        self.expect_period()
        return fc

    def _parse_org(self, fc):
        if self.accept('LINE'):
            self.expect('SEQUENTIAL')
            fc.organization = 'LINE SEQUENTIAL'
        elif self.accept('RECORD'):
            self.accept('BINARY')
            self.expect('SEQUENTIAL')
            fc.organization = 'SEQUENTIAL'
        else:
            fc.organization = self.expect('SEQUENTIAL', 'RELATIVE', 'INDEXED').up

    # ---------------------------------------------------------- data division
    def parse_data(self, prog):
        self.expect('DATA')
        self.expect('DIVISION')
        self.expect_period()
        while True:
            if self.is_word('FILE') and self.is_word('SECTION', k=1):
                self.next(); self.next(); self.expect_period()
                while self.is_word('FD', 'SD'):
                    prog.file_descs.append(self.parse_fd())
            elif self.is_word('WORKING-STORAGE'):
                self.next(); self.expect('SECTION'); self.expect_period()
                prog.working.extend(self.parse_entries())
            elif self.is_word('LOCAL-STORAGE'):
                self.next(); self.expect('SECTION'); self.expect_period()
                prog.local.extend(self.parse_entries())
            elif self.is_word('LINKAGE'):
                self.next(); self.expect('SECTION'); self.expect_period()
                prog.linkage.extend(self.parse_entries())
            elif self.is_word('REPORT') and self.is_word('SECTION', k=1):
                self.next(); self.next(); self.expect_period()
                while self.is_word('RD'):
                    prog.reports.append(self.parse_rd())
            elif self.is_word('SCREEN', 'COMMUNICATION') and self.is_word('SECTION', k=1):
                raise self.err(f"{self.peek().up} SECTION is not supported")
            else:
                break

    def parse_fd(self):
        kind = self.next().up
        loc = self.peek().loc
        name = self.user_word('file name')
        fd = FileDesc(name=name, kind=kind, records=[], loc=loc)
        while self.peek().kind not in ('.', 'EOF'):
            if self.accept('RECORD'):
                if self.accept('IS'):
                    pass
                if self.accept('VARYING'):
                    self.accept('IN')
                    self.accept('SIZE')
                    if self.accept('FROM') or self.peek().kind == 'NUM':
                        fd.rec_min = int(self.expect_kind('NUM').val)
                    if self.accept('TO'):
                        fd.rec_max = int(self.expect_kind('NUM').val)
                    self.accept('CHARACTERS')
                    if self.accept('DEPENDING'):
                        self.accept('ON')
                        fd.depending = self.parse_identifier()
                else:
                    self.accept('CONTAINS')
                    a = int(self.expect_kind('NUM').val)
                    if self.accept('TO'):
                        fd.rec_min = a
                        fd.rec_max = int(self.expect_kind('NUM').val)
                    else:
                        fd.rec_max = a
                    self.accept('CHARACTERS')
            elif self.accept('BLOCK'):
                self.accept('CONTAINS')
                self.next()
                if self.accept('TO'):
                    self.next()
                self.accept('RECORDS', 'CHARACTERS')
            elif self.accept('LABEL', 'DATA'):
                self.accept('RECORD', 'RECORDS')
                self.accept('IS', 'ARE')
                while self.peek().kind == 'WORD' and (self.is_user_word() or self.is_word('STANDARD', 'OMITTED')) \
                        and not self.is_word('REPORT', 'REPORTS', 'RECORD', 'BLOCK', 'LABEL', 'DATA', 'VALUE',
                                             'CODE-SET', 'LINAGE', 'RECORDING', 'EXTERNAL', 'GLOBAL'):
                    self.next()
            elif self.accept('VALUE'):
                self.accept('OF')
                while self.peek().kind not in ('.', 'EOF') and not self.is_word('RECORD', 'BLOCK', 'LABEL', 'DATA', 'RECORDING', 'CODE-SET'):
                    self.next()
            elif self.accept('RECORDING'):
                self.accept('MODE')
                self.accept('IS')
                self.next()
            elif self.accept('CODE-SET'):
                self.accept('IS')
                self.next()
            elif self.accept('LINAGE'):
                self.accept('IS')
                fd.linage = self.parse_operand()
                self.accept('LINES')
                while True:
                    if self.is_word('WITH') and self.is_word('FOOTING', k=1):
                        self.next()
                    if self.accept('FOOTING'):
                        self.accept('AT')
                        fd.footing = self.parse_operand()
                        continue
                    if self.is_word('LINES') and self.is_word('AT', k=1):
                        self.next()
                    if self.is_word('AT') and self.is_word('TOP', 'BOTTOM', k=1):
                        self.next()
                    if self.accept('TOP'):
                        fd.top = self.parse_operand()
                        continue
                    if self.accept('BOTTOM'):
                        fd.bottom = self.parse_operand()
                        continue
                    break
            elif self.is_word('REPORT', 'REPORTS'):
                self.next()
                self.accept('IS', 'ARE')
                while self.is_user_word():
                    fd.reports.append(self.next().up)
            elif self.accept('IS'):
                pass
            elif self.accept('EXTERNAL'):
                if self.accept('AS'):
                    self.next()         # the external name; the item's own name suffices
                    self.external = True
                    continue
                fd.external = True
            elif self.accept('GLOBAL'):
                fd.is_global = True
            else:
                raise self.err("unexpected clause in file description")
        self.expect_period()
        fd.records = self.parse_entries()
        return fd

    def parse_rd(self):
        loc = self.expect('RD').loc
        rd = ReportDesc(name=self.user_word('report name'), loc=loc)
        while self.peek().kind not in ('.', 'EOF'):
            if self.accept('IS'):
                continue
            if self.accept('GLOBAL'):
                rd.is_global = True
            elif self.accept('CODE'):
                self.accept('IS')
                rd.code = self.expect_kind('STR', 'CODE literal').val
            elif self.accept('CONTROL', 'CONTROLS'):
                self.accept('IS', 'ARE')
                while True:
                    if self.accept('FINAL'):
                        rd.has_final = True
                    elif self.is_user_word():
                        rd.controls.append(self.parse_identifier())
                    else:
                        break
            elif self.accept('PAGE'):
                self.accept('LIMIT', 'LIMITS')
                self.accept('IS', 'ARE')
                rd.page_limit = int(self.expect_kind('NUM', 'page limit').val)
                self.accept('LINE', 'LINES')
                if self.is_kind('NUM') and self.is_word('COLUMNS', 'COLS', k=1):
                    rd.line_limit = int(self.next().val)
                    self.next()
                while True:
                    if self.accept('HEADING'):
                        self.accept('IS')
                        rd.heading = int(self.expect_kind('NUM', 'integer').val)
                    elif self.is_word('FIRST') and self.is_word('DETAIL', k=1):
                        self.next(); self.next(); self.accept('IS')
                        rd.first_detail = int(self.expect_kind('NUM', 'integer').val)
                    elif self.is_word('LAST') and self.is_word('DETAIL', k=1):
                        self.next(); self.next(); self.accept('IS')
                        rd.last_detail = int(self.expect_kind('NUM', 'integer').val)
                    elif self.accept('FOOTING'):
                        self.accept('IS')
                        rd.footing = int(self.expect_kind('NUM', 'integer').val)
                    else:
                        break
            elif self.is_word('LINE') and self.is_word('LIMIT', 'LIMITS', k=1):
                self.next(); self.next()
                self.accept('IS', 'ARE')
                rd.line_limit = int(self.expect_kind('NUM', 'line limit').val)
            elif self.accept('HEADING'):
                # the page clauses may also follow LINE LIMIT, not only PAGE LIMIT
                self.accept('IS')
                rd.heading = int(self.expect_kind('NUM', 'integer').val)
            elif self.is_word('FIRST') and self.is_word('DETAIL', k=1):
                self.next(); self.next(); self.accept('IS')
                rd.first_detail = int(self.expect_kind('NUM', 'integer').val)
            elif self.is_word('LAST') and self.is_word('DETAIL', k=1):
                self.next(); self.next(); self.accept('IS')
                rd.last_detail = int(self.expect_kind('NUM', 'integer').val)
            elif self.accept('FOOTING'):
                self.accept('IS')
                rd.footing = int(self.expect_kind('NUM', 'integer').val)
            else:
                raise self.err("unexpected clause in report description")
        self.expect_period()
        self.in_report = True
        try:
            rd.groups = self._rw_split_groups(self.parse_entries())
        finally:
            self.in_report = False
        return rd

    @staticmethod
    def _rw_split_groups(groups):
        """GnuCOBOL extension: an 01 entry without TYPE whose subordinate entries
        have TYPE clauses describes several report groups. Consecutive entries
        with the same TYPE (other than DETAIL) form one group of several lines."""
        out = []
        for g in groups:
            if g.rw_type is not None or not g.children or any(c.rw_type is None for c in g.children):
                out.append(g)
                continue
            runs = []
            for c in g.children:
                if runs and runs[-1][-1].rw_type == c.rw_type and c.rw_type[0] != 'DE':
                    runs[-1].append(c)
                else:
                    runs.append([c])
            for run in runs:
                if len(run) == 1:
                    grp = run[0]
                    grp.level = 1
                    grp.parent = None
                else:
                    grp = DataItem(1, None, run[0].loc)
                    grp.rw_type = run[0].rw_type
                    grp.children = run
                    for c in run:
                        c.parent = grp
                out.append(grp)
        return out

    def _rw_clause(self, item, w):
        """Report Writer clauses of a REPORT SECTION entry; returns False if w is not one."""
        if w in ('PRESENT', 'ABSENT'):
            # PRESENT WHEN cond / ABSENT WHEN cond: is the group (or item)
            # presented? PRESENT/ABSENT AFTER NEW/COMPLETE <control> are the
            # page-or-control forms, which this accepts but does not act on.
            self.next()
            if self.accept('WHEN'):
                cond = self.parse_condition()
                item.rw_present = (cond, w == 'ABSENT')
                return True
            if self.accept('AFTER'):
                self.accept('NEW', 'COMPLETE')
                self.parse_identifier()
                while self.accept('OR'):
                    self.accept('PAGE') or self.parse_identifier()
                return True
            return False
        if w in ('LINE', 'LINES'):
            self.next()
            self.accept('NUMBER')
            self.accept('IS', 'ARE')
            if self.is_word('NEXT') and self.is_word('PAGE', k=1):
                self.next(); self.next()
                item.rw_line = ('NP', 0)
            elif self.accept('PLUS') or self.accept_op('+'):
                item.rw_line = ('REL', int(self.expect_kind('NUM', 'integer').val))
            else:
                t = self.expect_kind('NUM', 'line number')
                if t.val.startswith('+'):
                    item.rw_line = ('REL', int(t.val))
                elif self.is_word('ON') or (self.is_word('NEXT') and self.is_word('PAGE', k=1)):
                    self.accept('ON')
                    self.expect('NEXT')
                    self.expect('PAGE')
                    item.rw_line = ('ABSNP', int(t.val))
                else:
                    item.rw_line = ('ABS', int(t.val))
        elif w == 'NEXT':
            self.next()
            self.expect('GROUP')
            self.accept('IS')
            if self.accept('NEXT'):
                self.expect('PAGE')
                item.rw_next_group = ('NP', 0)
            elif self.accept('PLUS') or self.accept_op('+'):
                item.rw_next_group = ('REL', int(self.expect_kind('NUM', 'integer').val))
            else:
                t = self.expect_kind('NUM', 'line number')
                item.rw_next_group = ('REL' if t.val.startswith('+') else 'ABS', int(t.val))
        elif w == 'TYPE':
            self.next()
            self.accept('IS')
            t = self.next()
            u = t.up
            kind = None
            if u in RW_TYPES:
                kind = RW_TYPES[u]
            elif u in ('REPORT', 'PAGE', 'CONTROL'):
                h = self.expect('HEADING', 'FOOTING').up
                kind = {('REPORT', 'HEADING'): 'RH', ('REPORT', 'FOOTING'): 'RF',
                        ('PAGE', 'HEADING'): 'PH', ('PAGE', 'FOOTING'): 'PF',
                        ('CONTROL', 'HEADING'): 'CH', ('CONTROL', 'FOOTING'): 'CF'}[(u, h)]
            else:
                raise ParseError(f"invalid report group TYPE '{t.up}'", t.loc)
            ctl = None
            if kind in ('CH', 'CF'):
                self.accept('ON', 'FOR')
                if self.accept('FINAL'):
                    ctl = 'FINAL'
                else:
                    ctl = self.user_word('control name')
            item.rw_type = (kind, ctl)
        elif w in ('COLUMN', 'COL', 'COLUMNS', 'COLS'):
            # COLUMN [NUMBER IS] [LEFT | RIGHT | CENTER] [PLUS | +] integer
            self.next()
            self.accept('NUMBER', 'NUMBERS')
            self.accept('IS', 'ARE')
            j = self.accept('LEFT', 'RIGHT', 'CENTER', 'CENTRE')
            if j:
                item.rw_just = j.up[0]
            rel = bool(self.accept('PLUS') or self.accept_op('+'))
            t = self.expect_kind('NUM', 'column number')
            if t.val.startswith('+'):
                rel = True
            n = int(t.val.lstrip('+'))
            item.rw_column = ('REL', n) if rel else n
        elif w == 'SOURCE':
            self.next()
            self.accept('IS')
            item.rw_source = self.parse_operand()
        elif w == 'SUM':
            self.next()
            ops = []
            while self.is_operand_start() and self.peek().up not in RW_CLAUSE_WORDS:
                ops.append(self.parse_identifier())
            upon = []
            if self.accept('UPON'):
                while self.is_user_word() and self.peek().up not in RW_CLAUSE_WORDS:
                    upon.append(self.next().up)
            item.rw_sums.append((ops, upon))
        elif w == 'RESET':
            self.next()
            self.accept('ON')
            item.rw_reset = 'FINAL' if self.accept('FINAL') else self.user_word('control name')
        elif w == 'GROUP':
            self.next()
            self.accept('INDICATE')
            item.rw_group_indicate = True
        else:
            return False
        return True

    def parse_entries(self):
        flat = []
        while self.peek().kind == 'NUM' and '.' not in self.peek().val and self.peek().val[0] not in '+-':
            flat.append(self.parse_entry())
        return self.build_tree(flat)

    def parse_entry(self):
        lt = self.next()
        level = int(lt.val)
        loc = lt.loc
        if not (1 <= level <= 49 or level in (66, 77, 78, 88)):
            raise CompileError(f"invalid level number {lt.val}", loc)
        name = None
        src_name = None
        in_report = getattr(self, 'in_report', False)
        if self.accept('FILLER'):
            name = None
        elif (self.is_user_word() or (self.peek().kind == 'WORD'
                                      and self.peek().up in CONTEXT_WORDS)) and \
                self.peek().kind == 'WORD' and \
                not (in_report and self.peek().up in RW_CLAUSE_WORDS):
            nt = self.next()
            name = nt.up
            src_name = nt.val          # as written: JSON GENERATE uses this case
        item = DataItem(level, name, loc)
        item.src_name = src_name
        prog = self.prog
        while self.peek().kind not in ('.', 'EOF'):
            t = self.peek()
            if t.kind == 'PIC':
                self.next()
                item.pic = Picture(t.val, t.loc, prog.currency, prog.decimal_comma, prog.constants)
                continue
            if t.kind != 'WORD':
                raise self.err("unexpected token in data description")
            w = t.up
            if in_report and w not in ('PIC', 'PICTURE', 'VALUE', 'VALUES', 'IS', 'USAGE') \
                    and self._rw_clause(item, w):
                continue
            if w in ('PIC', 'PICTURE'):
                self.next()
                self.accept('IS')
                pt = self.expect_kind('PIC', 'PICTURE string')
                item.pic = Picture(pt.val, pt.loc, prog.currency, prog.decimal_comma, prog.constants)
            elif w == 'REDEFINES':
                self.next()
                item.redefines_name = self.user_word('data name')
            elif w == 'IS':
                self.next()
            elif w == 'EXTERNAL':
                self.next()
                item.external = True
                if self.accept('AS'):
                    # EXTERNAL AS "name": the storage is shared under that
                    # name, not under the item's own
                    t = self.peek()
                    if t.kind != 'STR':
                        raise self.err("EXTERNAL AS needs a literal name")
                    self.next()
                    item.external_name = t.val.decode('latin-1')
            elif w == 'GLOBAL':
                self.next()
                item.is_global = True
            elif w == 'USAGE':
                self.next()
                self.accept('IS')
                self._usage(item)
            elif w in USAGES:
                self._usage(item)
            elif w == 'SIGN':
                self.next()
                self.accept('IS')
                self._sign(item)
            elif w in ('LEADING', 'TRAILING'):
                self._sign(item)
            elif w == 'OCCURS':
                self.next()
                self._occurs(item)
            elif w in ('SYNC', 'SYNCHRONIZED'):
                self.next()
                self.accept('LEFT', 'RIGHT')
            elif w in ('JUST', 'JUSTIFIED'):
                self.next()
                self.accept('RIGHT')
                item.justified = True
            elif w == 'BLANK':
                self.next()
                self.accept('WHEN')
                self.expect('ZERO', 'ZEROS', 'ZEROES')
                item.blank_zero = True
            elif w in ('VALUE', 'VALUES'):
                self.next()
                self.accept('IS', 'ARE')
                if level == 88:
                    self._cond_values(item)
                elif level == 78:
                    item.value = self.parse_constant_value()
                else:
                    item.value = self.parse_value_literal()
            elif w == 'CONSTANT' and level == 1 and item.name:
                # 01 name CONSTANT [IS GLOBAL] AS expression (COBOL 2002)
                self.next()
                self.accept('IS')
                if self.accept('GLOBAL'):
                    item.is_global = True
                self.accept('AS')
                if self.accept('FROM'):
                    vt = self.next()
                    v = self.compile_vars.get(vt.up)
                    if v is None or v is True:
                        raise CompileError(f"'{vt.val}' is not a compilation variable with a value", vt.loc)
                    if isinstance(v, str):
                        item.value = StrLit(v.encode('latin-1', 'replace'))
                    else:
                        t = format(v.normalize(), 'f')
                        item.value = make_numlit(t.rstrip('0').rstrip('.') if '.' in t else t)
                else:
                    # GnuCOBOL: a level-01 CONSTANT keeps operator precedence,
                    # while a level-78 VALUE is evaluated left to right
                    item.value = self.parse_constant_value(left_to_right=False)
                level = 78
                item.level = 78
                if item.name and item.value is not None:
                    prog.constants[item.name] = item.value
                    if getattr(item, 'is_global', False):
                        prog.global_constants[item.name] = item.value
            elif w == 'RENAMES':
                self.next()
                a = self.parse_identifier()
                b = None
                if self.accept('THRU', 'THROUGH'):
                    b = self.parse_identifier()
                item.renames = (a, b)
            elif w == 'FALSE' and level == 88:
                self.next()
                self.accept('IS')
                item.false_value = self.parse_value_literal()
            elif w == 'WHEN' and level == 88:
                self.next()
                self.accept('SET')
                self.accept('TO')
                self.expect('FALSE')
                self.accept('IS')
                item.false_value = self.parse_value_literal()
            elif w == 'BASED':
                # a level 01/77 item whose storage is allocated at run time
                self.next()
                if level not in (1, 77):
                    raise CompileError("BASED requires a level 01 or 77 item", loc)
                item.based = True
            elif w == 'ANY':
                # PIC X ANY LENGTH: the size comes from the CALLing program
                self.next()
                self.expect('LENGTH')
                if item.pic is None or item.pic.category not in ('ALPHANUMERIC', 'ALPHABETIC'):
                    raise CompileError("ANY LENGTH requires an alphanumeric "
                                       "PICTURE on a level 01 or 77 item", loc)
                item.any_length = True
            else:
                raise self.err("unexpected word in data description")
        if item.pic is not None and item.usage in (None, 'DISPLAY'):
            try:
                item.decl_size = item.pic.size
                if item.name:
                    self.decl_sizes[item.name] = item.decl_size
            except AttributeError:
                pass
        self.expect_period()
        if level == 78:
            if item.value is None:
                raise CompileError("level 78 requires a VALUE", loc)
            prog.constants[item.name] = item.value
            if getattr(item, 'is_global', False):
                prog.global_constants[item.name] = item.value
        return item

    def _usage(self, item):
        w = self.next().up
        u = USAGES.get(w)
        if u is None:
            raise self.err("unknown USAGE")
        item.usage = u
        if w.startswith('UNSIGNED-'):
            item.usage_signed = False      # UNSIGNED-SHORT and friends
        if self.accept('SIGNED'):
            item.usage_signed = True
        elif self.accept('UNSIGNED'):
            item.usage_signed = False

    def _sign(self, item):
        w = self.expect('LEADING', 'TRAILING').up
        item.sign_lead = (w == 'LEADING')
        if self.accept('SEPARATE'):
            self.accept('CHARACTER')
            item.sign_sep = True

    def _occurs(self, item):
        oc = Occurs()
        oc.loc = self.peek().loc
        a = self.const_int('integer')
        if self.accept('TO'):
            oc.min = a
            oc.max = self.const_int('integer')
        else:
            oc.min = a
            oc.max = a
        self.accept('TIMES')
        while True:
            if self.accept('DEPENDING'):
                self.accept('ON')
                oc.depending = self.parse_identifier()
            elif self.is_word('ASCENDING', 'DESCENDING'):
                desc = self.next().up == 'DESCENDING'
                self.accept('KEY')
                self.accept('IS')
                while self.is_user_word():
                    oc.keys.append((desc, self.next().up))
                    while self.accept('OF', 'IN'):
                        self.next()
            elif self.accept('INDEXED'):
                self.accept('BY')
                while self.is_user_word():
                    oc.indexes.append((self.next().up, self.peek(-1).loc if False else oc.loc))
            else:
                break
        if oc.max < 1:
            raise CompileError("OCCURS must be at least 1", oc.loc)
        item.occurs = oc

    def _cond_values(self, item):
        while True:
            t = self.peek()
            if t.kind in ('NUM', 'STR') or (t.kind == 'WORD' and (t.up in FIGURATIVES or t.up == 'ALL' or t.up in self.prog.symbolic)) or \
                    (t.kind == 'OP' and t.val in '+-'):
                lo = self.parse_value_literal()
                hi = None
                if self.accept('THRU', 'THROUGH'):
                    hi = self.parse_value_literal()
                item.values.append((lo, hi))
            else:
                break
        if not item.values:
            raise self.err("condition value expected")

    def parse_constant_value(self, left_to_right=True):
        """The value of a constant: an arithmetic expression of literals,
        constants and LENGTH OF / BYTE-LENGTH OF, or a list of literals and
        constants joined with '&' (CONSTANT 'Cat ' & ' & ' & DOG)."""
        save = self.pos
        atom = self._const_atom()
        if atom is not None and self.peek().kind == 'OP' and self.peek().val == '&':
            parts = [atom]
            while self.peek().kind == 'OP' and self.peek().val == '&':
                self.next()
                nxt = self._const_atom()
                if nxt is None:
                    raise self.err("literal or constant expected after '&'")
                parts.append(nxt)
            out = b''
            for p in parts:
                out += p.value if isinstance(p, StrLit) else b' '
            return StrLit(out)
        self.pos = save
        self.const_expr = left_to_right
        try:
            e = self.parse_expr()
        finally:
            self.const_expr = False
        return fold_constant(e, self.decl_sizes)

    def _const_atom(self):
        """A literal, figurative constant or named constant, or None."""
        t = self.peek()
        if t.kind == 'STR' or (t.kind == 'WORD' and (t.up in FIGURATIVES or t.up == 'ALL')):
            return self.parse_value_literal()
        if t.kind == 'WORD' and t.up in self.visible_constants():
            self.next()
            return self.visible_constants()[t.up]
        return None

    def visible_constants(self):
        """Constants this program can name: its own, and the GLOBAL ones of the
        programs that contain it."""
        out = {}
        chain = []
        p = self.prog.parent if self.prog is not None else None
        while p is not None:
            chain.append(p)
            p = p.parent
        for pc in reversed(chain):
            out.update(getattr(pc, 'global_constants', {}))
        out.update(self.prog.constants if self.prog is not None else {})
        return out

    def const_int(self, what):
        """An integer literal or the name of an integer constant."""
        t = self.peek()
        vc = self.visible_constants()
        if t.kind == 'WORD' and t.up not in self.prog.constants and t.up in vc:
            self.next()
            return vc[t.up]
        if t.kind == 'WORD' and t.up in self.prog.constants:
            v = self.prog.constants[t.up]
            if isinstance(v, NumLit) and v.scale == 0 and not v.neg:
                self.next()
                return int(v.digits)
        return int(self.expect_kind('NUM', what).val)

    def parse_value_literal(self):
        t = self.peek()
        if t.kind == 'NUM':
            self.next()
            return make_numlit(t.val, t.loc)
        if t.kind == 'STR':
            self.next()
            return StrLit(t.val)
        if t.kind == 'OP' and t.val in '+-' and self.peek(1).kind == 'NUM':
            self.next()
            n = self.next()
            return make_numlit(t.val + n.val, n.loc)
        if t.kind == 'WORD':
            if t.up in FIGURATIVES:
                self.next()
                return Figurative(FIGURATIVES[t.up])
            if t.up == 'ALL':
                self.next()
                v = self.parse_value_literal()
                return self._make_all(v, t)
            if t.up in self.prog.symbolic:
                self.next()
                return StrLit(bytes([self.prog.symbolic[t.up]]))
            if t.up in self.prog.constants:
                self.next()
                return self.prog.constants[t.up]
        raise self.err("literal expected")

    def _make_all(self, v, t):
        if isinstance(v, StrLit):
            return AllLit(v.value)
        if isinstance(v, Figurative):
            return AllLit(FIG_BYTES[v.kind], is_zero=(v.kind == 'ZERO'))
        if isinstance(v, NumLit):
            return AllLit(v.digits.encode())
        raise self.err("literal expected after ALL", t)

    def build_tree(self, flat):
        roots = []
        stack = []
        last = None
        for e in flat:
            if e.level == 88:
                if last is None:
                    raise CompileError("level 88 item without a conditional variable", e.loc)
                last.conditions.append(e)
                e.parent = last
                continue
            if e.level == 78:
                continue
            if e.level == 66:
                if not roots:
                    raise CompileError("level 66 without a record", e.loc)
                roots[-1].children.append(e)
                e.parent = roots[-1]
                continue
            if e.level in (1, 77):
                roots.append(e)
                stack = [e]
                last = e
                continue
            while stack and stack[-1].level >= e.level:
                stack.pop()
            if not stack:
                raise CompileError(f"level {e.level:02d} item '{e.name or 'FILLER'}' is not subordinate to a record", e.loc)
            parent = stack[-1]
            if parent.level == 77:
                raise CompileError("level 77 items cannot have subordinates", e.loc)
            parent.children.append(e)
            e.parent = parent
            stack.append(e)
            last = e
        return roots

    # ---------------------------------------------------------- procedure division
    def parse_procedure(self, prog):
        self.expect('PROCEDURE')
        self.expect('DIVISION')
        if self.accept('CHAINING'):
            # legacy entry: the items are WORKING-STORAGE items that receive
            # the command-line arguments, keeping their VALUE when there are
            # fewer of them
            while self.is_user_word():
                prog.chaining.append(self.parse_identifier())
        if self.accept('USING'):
            mode = 'REFERENCE'
            while True:
                if self.accept('BY'):
                    mode = self.expect('REFERENCE', 'VALUE', 'CONTENT').up
                elif self.is_word('REFERENCE', 'VALUE', 'CONTENT'):
                    mode = self.next().up
                elif self.is_user_word():
                    prog.using.append((mode, self.parse_identifier()))
                elif self.accept('OPTIONAL'):
                    pass
                else:
                    break
        if self.accept('RETURNING', 'GIVING'):
            if self.accept('OMITTED'):
                prog.returning = None       # PROCEDURE DIVISION ... RETURNING OMITTED
                prog.returning_omitted = True
            else:
                prog.returning = self.parse_identifier()
        self.expect_period()
        if self.is_word('DECLARATIVES'):
            self.next()
            self.expect_period()
            while not (self.is_word('END') and self.is_word('DECLARATIVES', k=1)):
                if self.peek().kind == 'EOF':
                    raise self.err("END DECLARATIVES expected")
                if not self._section_start():
                    raise self.err("section header expected in DECLARATIVES")
                sec = self._section_header()
                if self.accept('USE'):
                    sec.use_global = bool(self.accept('GLOBAL'))
                    if self.accept('FOR'):
                        self.expect('DEBUGGING')
                        self.accept('ON')
                        sec.use_debug = self._debug_targets()
                        self.expect_period()
                    elif self.accept('BEFORE'):
                        self.expect('REPORTING')
                        sec.use_reporting = self.user_word('report group name')
                        self.expect_period()
                    else:
                        self.accept('AFTER')
                        self.accept('STANDARD')
                        self.expect('ERROR', 'EXCEPTION')
                        self.accept('PROCEDURE')
                        self.accept('ON')
                        files = []
                        while self.peek().kind == 'WORD' and self.peek().kind != '.':
                            w = self.next().up
                            if w in ('INPUT', 'OUTPUT', 'I-O', 'EXTEND'):
                                sec.use_mode = w
                            else:
                                files.append(w)
                        sec.use_files = files
                        self.expect_period()
                self._parse_section_body(sec, declaratives=True)
                prog.declaratives.append(sec)
            self.next(); self.next()
            self.expect_period()
        cur_sec = None
        while True:
            t = self.peek()
            if t.kind == 'EOF':
                break
            if self.is_word('END') and self.is_word('PROGRAM', 'FUNCTION', k=1):
                break
            if self.is_word('IDENTIFICATION', 'ID') and self.is_word('DIVISION', k=1):
                break
            if self.is_word('PROGRAM-ID', 'FUNCTION-ID'):
                break
            if self._section_start():
                cur_sec = self._section_header()
                prog.sections.append(cur_sec)
                self._parse_section_body(cur_sec)
                continue
            if cur_sec is None:
                cur_sec = Section(None, [], t.loc)
                prog.sections.append(cur_sec)
            self._parse_section_body(cur_sec)

    def _debug_targets(self):
        """USE FOR DEBUGGING ON {ALL PROCEDURES | [ALL [REFERENCES] [OF]] name [OF|IN qual]...}..."""
        targets = []
        while self.peek().kind not in ('.', 'EOF'):
            loc = self.peek().loc
            all_refs = False
            if self.accept('ALL'):
                if self.accept('PROCEDURES'):
                    targets.append(DebugTarget(None, False, loc))
                    continue
                self.accept('REFERENCES')
                self.accept('OF')
                all_refs = True
            name = self._debug_name()
            quals = []
            while self.accept('OF', 'IN'):
                quals.append(self._debug_name())
            targets.append(DebugTarget(DataRef(name, quals, [], None, loc), all_refs, loc))
        if not targets:
            raise self.err("USE FOR DEBUGGING requires a procedure, file or data name")
        return targets

    def _debug_name(self):
        t = self.peek()
        if t.kind == 'WORD' or (t.kind == 'NUM' and t.val.isdigit()):
            self.next()
            return t.up if t.kind == 'WORD' else t.val
        raise self.err("name expected in USE FOR DEBUGGING")

    def _section_start(self):
        t = self.peek()
        return (self.is_user_word() or (t.kind == 'NUM' and t.val.isdigit())) and self.is_word('SECTION', k=1)

    def _section_header(self):
        t = self.next()
        self.next()  # SECTION
        seg = 0
        if self.peek().kind == 'NUM':
            seg = int(self.next().val)
        self.expect_period()
        sec = Section(t.up if t.kind == 'WORD' else t.val, [], t.loc)
        sec.segment = seg
        return sec

    def _parse_section_body(self, sec, declaratives=False):
        para = None
        while True:
            t = self.peek()
            if t.kind == 'EOF':
                return
            if self.is_word('END') and self.is_word('PROGRAM', 'FUNCTION', 'DECLARATIVES', k=1):
                return
            if self.is_word('IDENTIFICATION', 'ID') and self.is_word('DIVISION', k=1):
                return
            if self.is_word('PROGRAM-ID', 'FUNCTION-ID'):
                return
            if self._section_start():
                return
            if t.kind == '.':
                self.next()
                continue
            if (self.is_user_word() or (t.kind == 'NUM' and '.' not in t.val and t.val[0] not in '+-')) and self.peek(1).kind == '.':
                self.next()
                self.next()
                para = Paragraph(t.up if t.kind == 'WORD' else t.val, [], t.loc)
                sec.paragraphs.append(para)
                continue
            if para is None:
                para = Paragraph(None, [], t.loc)
                sec.paragraphs.append(para)
            loc = t.loc
            stmts = self.parse_statements()
            if not stmts:
                raise self.err("statement expected")
            if self.peek().kind != '.':
                raise self.err("expected '.' or statement")
            self.next()
            para.sentences.append(Sentence(stmts, loc))

    # ---------------------------------------------------------- statements
    def parse_statements(self):
        stmts = []
        while True:
            t = self.peek()
            if t.kind != 'WORD' or t.up not in VERBS:
                break
            if t.up == 'NEXT' and not self.is_word('SENTENCE', k=1):
                break
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        t = self.next()
        fn = getattr(self, 'p_' + t.up.replace('-', '_'), None)
        if fn is None:
            raise ParseError(f"statement '{t.up}' is not supported", t.loc)
        return fn(t.loc)

    def _imperative_phrase(self, *words):
        """Parse 'stmts' after a phrase keyword sequence already consumed."""
        return self.parse_statements()

    def _end(self, word):
        self.accept(word)

    # ---- phrase helpers
    def _size_error(self):
        on = noton = None
        while True:
            if self.is_word('SIZE') or (self.is_word('ON') and self.is_word('SIZE', k=1)):
                self.accept('ON'); self.next(); self.expect('ERROR')
                on = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('SIZE', k=1) or (self.is_word('ON', k=1) and self.is_word('SIZE', k=2))):
                self.next(); self.accept('ON'); self.next(); self.expect('ERROR')
                noton = self.parse_statements()
            else:
                return on, noton

    def _overflow(self):
        on = noton = None
        while True:
            if self.is_word('OVERFLOW') or (self.is_word('ON') and self.is_word('OVERFLOW', k=1)):
                self.accept('ON'); self.next()
                on = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('OVERFLOW', k=1) or (self.is_word('ON', k=1) and self.is_word('OVERFLOW', k=2))):
                self.next(); self.accept('ON'); self.next()
                noton = self.parse_statements()
            else:
                return on, noton

    def _exception(self):
        on = noton = None
        while True:
            if self.is_word('EXCEPTION', 'OVERFLOW') or (self.is_word('ON') and self.is_word('EXCEPTION', 'OVERFLOW', k=1)):
                self.accept('ON'); self.next()
                on = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('EXCEPTION', k=1) or (self.is_word('ON', k=1) and self.is_word('EXCEPTION', k=2))):
                self.next(); self.accept('ON'); self.next()
                noton = self.parse_statements()
            else:
                return on, noton

    def _at_end(self):
        on = noton = None
        while True:
            if (self.is_word('AT') and self.is_word('END', k=1)) or (self.is_word('END') and not self.is_word('PROGRAM', 'DECLARATIVES', k=1)):
                self.accept('AT'); self.next()
                on = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('END', k=1) or (self.is_word('AT', k=1) and self.is_word('END', k=2))):
                self.next(); self.accept('AT'); self.next()
                noton = self.parse_statements()
            else:
                return on, noton

    def _invalid_key(self):
        on = noton = None
        while True:
            if self.is_word('INVALID'):
                self.next(); self.accept('KEY')
                on = self.parse_statements()
            elif self.is_word('NOT') and self.is_word('INVALID', k=1):
                self.next(); self.next(); self.accept('KEY')
                noton = self.parse_statements()
            else:
                return on, noton

    def _targets(self, allow_rounded=True):
        out = []
        while self.is_user_word():
            ref = self.parse_identifier()
            r = False
            if allow_rounded and self.accept('ROUNDED'):
                r = True                # the program's default rounding mode
                if self.accept('MODE'):
                    self.accept('IS')
                    w = self.next()
                    if w.up not in ROUNDING_MODES:
                        raise ParseError(f"invalid rounding mode '{w.val}'", w.loc)
                    r = w.up
            out.append(Target(ref, r))
        return out

    def _operands(self):
        out = []
        while self.is_operand_start():
            out.append(self.parse_operand())
        return out

    # ---- MOVE
    def p_MOVE(self, loc):
        corr = bool(self.accept('CORRESPONDING', 'CORR'))
        src = self.parse_operand(allow_all=True)
        self.expect('TO')
        dsts = []
        while self.is_user_word():
            dsts.append(self.parse_identifier())
        if not dsts:
            raise self.err("receiving item expected")
        return Move(loc, src, dsts, corr)

    # ---- arithmetic
    def p_ADD(self, loc):
        corr = bool(self.accept('CORRESPONDING', 'CORR'))
        ops = self._operands()
        st = Arith(loc, 'ADD', ops, [], [], corr=corr)
        if self.accept('TO'):
            if self.is_operand_start() and not self.is_user_word():
                st.operands.append(self.parse_operand())
                self.expect('GIVING')
                st.giving = self._targets()
            else:
                tg = self._targets()
                if self.accept('GIVING'):
                    if len(tg) != 1 or tg[0].rounded:
                        raise self.err("invalid ADD ... TO ... GIVING")
                    st.operands.append(tg[0].ref)
                    st.giving = self._targets()
                else:
                    st.to = tg
        elif self.accept('GIVING'):
            st.giving = self._targets()
        else:
            raise self.err("TO or GIVING expected")
        st.on_error, st.not_on_error = self._size_error()
        self._end('END-ADD')
        return st

    def p_SUBTRACT(self, loc):
        corr = bool(self.accept('CORRESPONDING', 'CORR'))
        ops = self._operands()
        self.expect('FROM')
        st = Arith(loc, 'SUBTRACT', ops, [], [], corr=corr)
        if self.is_operand_start() and not self.is_user_word():
            st.by_or_into = self.parse_operand()
            self.expect('GIVING')
            st.giving = self._targets()
        else:
            tg = self._targets()
            if self.accept('GIVING'):
                if len(tg) != 1 or tg[0].rounded:
                    raise self.err("invalid SUBTRACT ... GIVING")
                st.by_or_into = tg[0].ref
                st.giving = self._targets()
            else:
                st.to = tg
        st.on_error, st.not_on_error = self._size_error()
        self._end('END-SUBTRACT')
        return st

    def p_MULTIPLY(self, loc):
        a = self.parse_operand()
        self.expect('BY')
        st = Arith(loc, 'MULTIPLY', [a], [], [])
        if self.is_operand_start() and not self.is_user_word():
            st.by_or_into = self.parse_operand()
            self.expect('GIVING')
            st.giving = self._targets()
        else:
            tg = self._targets()
            if self.accept('GIVING'):
                if len(tg) != 1 or tg[0].rounded:
                    raise self.err("invalid MULTIPLY ... GIVING")
                st.by_or_into = tg[0].ref
                st.giving = self._targets()
            else:
                st.to = tg
        st.on_error, st.not_on_error = self._size_error()
        self._end('END-MULTIPLY')
        return st

    def p_DIVIDE(self, loc):
        a = self.parse_operand()
        form = self.expect('INTO', 'BY').up
        st = Arith(loc, 'DIVIDE', [a], [], [], form=form)
        if self.is_operand_start() and not self.is_user_word():
            st.by_or_into = self.parse_operand()
            self.expect('GIVING')
            st.giving = self._targets()
        else:
            tg = self._targets()
            if self.accept('GIVING'):
                if len(tg) != 1 or tg[0].rounded:
                    raise self.err("invalid DIVIDE ... GIVING")
                st.by_or_into = tg[0].ref
                st.giving = self._targets()
            else:
                if form == 'BY':
                    raise self.err("DIVIDE ... BY requires GIVING")
                st.to = tg
        if self.accept('REMAINDER'):
            st.remainder = self.parse_identifier()
        st.on_error, st.not_on_error = self._size_error()
        self._end('END-DIVIDE')
        return st

    def p_COMPUTE(self, loc):
        tg = self._targets()
        if not tg:
            raise self.err("receiving item expected")
        if not (self.accept('EQUAL') or (self.peek().kind == 'OP' and self.peek().val == '=' and self.next())):
            raise self.err("'=' expected")
        e = self.parse_expr()
        st = Compute(loc, tg, e)
        st.on_error, st.not_on_error = self._size_error()
        self._end('END-COMPUTE')
        return st

    # ---- DISPLAY / ACCEPT
    def p_EXHIBIT(self, loc):
        """EXHIBIT [NAMED | CHANGED | CHANGED NAMED] operand..."""
        # EXHIBIT names its operands unless it is the CHANGED form, which
        # prints bare values so that only the changed ones stand out
        named = True
        changed = False
        if self.accept('NAMED'):
            named = True
        elif self.accept('CHANGED'):
            changed = True
            named = self.accept('NAMED')
        items = []
        while self.is_operand_start():
            items.append(self.parse_operand(allow_all=True))
        if not items:
            raise self.err("EXHIBIT needs at least one operand")
        return Exhibit(loc, items, named, changed)

    def p_ALLOCATE(self, loc):
        """ALLOCATE item [INITIALIZED] | ALLOCATE n CHARACTERS [INITIALIZED]"""
        st = Allocate(loc)
        if self.peek().kind == 'NUM' and self.is_word('CHARACTERS', k=1):
            st.count = make_numlit(self.next().val, loc)
            self.next()
        elif self.peek().kind == 'NUM':
            st.count = make_numlit(self.next().val, loc)
            self.accept('CHARACTERS', 'BYTES')
        else:
            st.target = self.parse_identifier()
        if self.accept('INITIALIZED'):
            st.initialized = True
            if self.accept('TO'):
                st.init_value = self.parse_operand(allow_all=True)
        if self.accept('RETURNING'):
            st.returning = self.parse_identifier()
        return st

    def p_FREE(self, loc):
        self.accept('ADDRESS')
        self.accept('OF')
        return FreeStmt(loc, self.parse_identifier())

    def p_XML(self, loc):
        """XML GENERATE out FROM src [WITH XML-DECLARATION] [WITH ATTRIBUTES]
        [NAME OF ...] [TYPE OF ... IS ATTRIBUTE|CONTENT] [SUPPRESS ...]
        [NAMESPACE x] [NAMESPACE-PREFIX p] [COUNT IN n]."""
        if not self.accept('GENERATE'):
            raise self.err("XML PARSE is not supported (only XML GENERATE)")
        out = self.parse_identifier()
        self.expect('FROM')
        src = self.parse_identifier()
        st = XmlGenerate(loc, out, src)
        while True:
            if self.accept('WITH'):
                if self.accept('XML-DECLARATION'):
                    st.declaration = True
                elif self.accept('ATTRIBUTES'):
                    st.all_attributes = True
                else:
                    break
            elif self.accept('NAME'):
                self.accept('OF')
                while True:
                    ref = self.parse_identifier()
                    self.accept('IS')
                    t = self.peek()
                    if t.kind != 'STR':
                        raise self.err("an XML name must be a literal")
                    self.next()
                    st.names.append((ref, t.val.decode('latin-1')))
                    if self.accept('OF'):
                        continue
                    if self.is_word('TYPE', 'SUPPRESS', 'NAMESPACE', 'NAMESPACE-PREFIX',
                                    'COUNT', 'ON', 'NOT'):
                        break
                    if self.is_user_word():
                        continue
                    break
            elif self.accept('TYPE'):
                self.accept('OF')
                while True:
                    ref = self.parse_identifier()
                    self.accept('IS')
                    st.types.append((ref, self.expect('ATTRIBUTE', 'CONTENT', 'ELEMENT').up))
                    if self.accept('OF'):
                        continue
                    if self.is_word('NAME', 'SUPPRESS', 'NAMESPACE', 'NAMESPACE-PREFIX',
                                    'COUNT', 'ON', 'NOT'):
                        break
                    if self.is_user_word():
                        continue
                    break
            elif self.accept('SUPPRESS'):
                # the clause repeats: SUPPRESS a WHEN X, b WHEN Y, EVERY ELEMENT WHEN Z
                while True:
                    every = None
                    ref = None
                    if self.accept('EVERY'):
                        every = self.expect('ELEMENT', 'ATTRIBUTE', 'NONNUMERIC').up
                    elif self.is_user_word():
                        ref = self.parse_identifier()
                    self.expect('WHEN')
                    figs = set()
                    while True:
                        w = self.next()
                        figs.add(w.up)
                        if not self.accept('OR'):
                            break
                    st.suppress.append((ref, figs, every))
                    if self.accept('EVERY'):
                        self.pos -= 1
                        continue
                    if self.is_user_word():
                        continue
                    break
            elif self.accept('NAMESPACE'):
                st.namespace = self.parse_operand()
            elif self.accept('NAMESPACE-PREFIX'):
                st.namespace_prefix = self.parse_operand()
            elif self.is_word('COUNT') and self.is_word('IN', k=1):
                self.next(); self.next()
                st.count_in = self.parse_identifier()
            elif self.accept('ON') and self.accept('EXCEPTION'):
                st.on_exc = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('ON', k=1) or self.is_word('EXCEPTION', k=1)):
                self.next()
                self.accept('ON')
                self.expect('EXCEPTION')
                st.not_on_exc = self.parse_statements()
            elif self.accept('EXCEPTION'):
                st.on_exc = self.parse_statements()
            elif self.is_word('END-XML'):
                self.next()
                break
            else:
                break
        return st

    def p_JSON(self, loc):
        """JSON GENERATE out FROM src [NAME OF ...] [SUPPRESS ...] [COUNT IN n]
        [ON EXCEPTION ...] [NOT ON EXCEPTION ...] [END-JSON]"""
        if not self.accept('GENERATE'):
            raise self.err("JSON PARSE is not supported (only JSON GENERATE)")
        out = self.parse_identifier()
        self.expect('FROM')
        src = self.parse_identifier()
        st = JsonGenerate(loc, out, src)
        while True:
            if self.accept('NAME'):
                self.accept('OF')
                while True:
                    ref = self.parse_identifier()
                    self.accept('IS')
                    if self.accept('OMITTED'):
                        st.names.append((ref, None))
                    else:
                        t = self.peek()
                        if t.kind != 'STR':
                            raise self.err("a JSON name must be a literal")
                        self.next()
                        st.names.append((ref, t.val.decode('latin-1')))
                    # further entries follow after a comma or another OF
                    if self.accept('OF'):
                        continue
                    if self.peek().kind == '.' or self.is_kind('EOF'):
                        break
                    if self.is_word('SUPPRESS', 'COUNT', 'ON', 'NOT', 'END-JSON'):
                        break
                    if self.is_user_word():
                        continue
                    break
            elif self.accept('SUPPRESS'):
                while self.is_user_word():
                    st.suppress.append(self.parse_identifier())
            elif self.is_word('COUNT') and self.is_word('IN', k=1):
                self.next(); self.next()
                st.count_in = self.parse_identifier()
            elif self.accept('ON') and self.accept('EXCEPTION'):
                st.on_exc = self.parse_statements()
            elif self.is_word('NOT') and (self.is_word('ON', k=1)
                                          or self.is_word('EXCEPTION', k=1)):
                self.next()
                if self.accept('ON'):
                    pass
                self.expect('EXCEPTION')
                st.not_on_exc = self.parse_statements()
            elif self.accept('EXCEPTION'):
                st.on_exc = self.parse_statements()
            else:
                break
        if self.accept('END_JSON'):
            pass
        elif self.is_word('END-JSON'):
            self.next()
        return st

    def p_DISPLAY(self, loc):
        items = []
        while self.is_operand_start() or self.is_word('ALL'):
            items.append(self.parse_operand(allow_all=True))
        st = Display(loc, items)
        while True:
            if self.accept('UPON'):
                w = self.next().up
                st.upon = self.mnemonics.get(w, w)
            elif self.is_word('WITH') and self.is_word('NO', k=1):
                self.next(); self.next(); self.expect('ADVANCING')
                st.no_advancing = True
            elif self.is_word('NO') and self.is_word('ADVANCING', k=1):
                self.next(); self.next()
                st.no_advancing = True
            else:
                break
        st.on_exc, st.not_on_exc = self._exception()
        self._end('END-DISPLAY')
        return st

    def p_ACCEPT(self, loc):
        if self.accept('OMITTED'):
            # read and discard one line (ACCEPT OMITTED has no receiving item)
            return Accept(loc, None, 'OMITTED')
        target = self.parse_identifier()
        st = Accept(loc, target)
        if self.accept('FROM'):
            w = self.next().up
            w = self.mnemonics.get(w, w)
            if w == 'DATE':
                st.source = 'DATE'
                if self.accept('YYYYMMDD'):
                    st.source = 'DATE8'
            elif w == 'DAY':
                st.source = 'DAY'
                if self.accept('YYYYDDD'):
                    st.source = 'DAY7'
            elif w in ('DAY-OF-WEEK', 'TIME', 'COMMAND-LINE', 'ARGUMENT-VALUE', 'ARGUMENT-NUMBER',
                       'ENVIRONMENT-VALUE', 'ESCAPE', 'EXCEPTION'):
                st.source = w
                if w in ('ESCAPE', 'EXCEPTION'):
                    self.accept('KEY', 'STATUS')
            elif w == 'ENVIRONMENT':
                st.source = 'ENVIRONMENT'
                st.arg = self.parse_operand()
            elif w in ('CONSOLE', 'SYSIN', 'KEYBOARD', 'STDIN'):
                st.source = 'CONSOLE'
            else:
                raise ParseError(f"unsupported ACCEPT source '{w}'", loc)
        st.on_exc, st.not_on_exc = self._exception()
        self._end('END-ACCEPT')
        return st

    # ---- IF / EVALUATE
    def p_IF(self, loc):
        c = self.parse_condition()
        self.accept('THEN')
        then = self.parse_statements()
        els = None
        if self.accept('ELSE'):
            els = self.parse_statements()
        self._end('END-IF')
        return If(loc, c, then, els)

    def p_EVALUATE(self, loc):
        subjects = [self._eval_subject()]
        while self.accept('ALSO'):
            subjects.append(self._eval_subject())
        whens = []
        other = None
        while self.is_word('WHEN'):
            if self.is_word('OTHER', k=1):
                self.next(); self.next()
                other = self.parse_statements()
                break
            groups = []
            while self.is_word('WHEN') and not self.is_word('OTHER', k=1):
                self.next()
                objs = [self._eval_object(subjects[0])]
                i = 1
                while self.accept('ALSO'):
                    objs.append(self._eval_object(subjects[i] if i < len(subjects) else None))
                    i += 1
                if len(objs) != len(subjects):
                    raise ParseError("number of WHEN objects does not match EVALUATE subjects", loc)
                groups.append(objs)
            stmts = self.parse_statements()
            whens.append((groups, stmts))
        self._end('END-EVALUATE')
        return Evaluate(loc, subjects, whens, other)

    def _eval_subject(self):
        if self.accept('TRUE'):
            return 'TRUE'
        if self.accept('FALSE'):
            return 'FALSE'
        save = self.pos
        try:
            e = self.parse_expr()
            if self._cond_continues():
                raise Backtrack()
            return e
        except (Backtrack, ParseError):
            self.pos = save
            return self.parse_condition()

    def _cond_continues(self):
        t = self.peek()
        if t.kind == 'OP' and t.val in RELOP_SYM:
            return True
        return self.is_word('IS', 'NOT', 'EQUAL', 'EQUALS', 'GREATER', 'LESS', 'AND', 'OR',
                            'NUMERIC', 'ALPHABETIC', 'ALPHABETIC-LOWER', 'ALPHABETIC-UPPER',
                            'POSITIVE', 'NEGATIVE') or (self.is_word('ZERO', 'ZEROS', 'ZEROES')) or \
            (t.kind == 'WORD' and t.up in self.class_names)

    def _eval_object(self, subj):
        if self.accept('ANY'):
            return WhenObj('ANY')
        if self.is_word('TRUE') and not self._cond_after(1):
            self.next()
            return WhenObj('TRUE')
        if self.is_word('FALSE') and not self._cond_after(1):
            self.next()
            return WhenObj('FALSE')
        if subj in ('TRUE', 'FALSE'):
            return WhenObj('COND', self.parse_condition())
        # "WHEN >= 10000" / "WHEN < 5": a relation with the subject implied
        if subj not in ('TRUE', 'FALSE') and self._relop_start(allow_not=False):
            op = self.parse_relop()
            return WhenObj('RELOP', op, self.parse_expr())
        neg = bool(self.accept('NOT'))
        save = self.pos
        try:
            a = self.parse_expr()
            if self._cond_continues() and not self.is_word('AND', 'OR') and not self.is_word('NOT'):
                raise Backtrack()
        except (Backtrack, ParseError):
            self.pos = save
            c = self.parse_condition()
            return WhenObj('COND', c, None, neg)
        if self.accept('THRU', 'THROUGH'):
            b = self.parse_expr()
            return WhenObj('RANGE', a, b, neg)
        return WhenObj('VALUE', a, None, neg)

    def _cond_after(self, k):
        t = self.peek(k)
        return t.kind == 'WORD' and t.up in ('AND', 'OR')

    # ---- PERFORM
    def p_PERFORM(self, loc):
        first = last = None
        if self.is_user_word() and not self.is_word('FOREVER') and not self.is_word('TIMES', k=1) and not (
                self.peek(1).kind == '(' or (self.is_word('OF', 'IN', k=1) and self.is_word('TIMES', k=3))):
            first = self._procref()
            if self.accept('THRU', 'THROUGH'):
                last = self._procref()
        elif self.peek().kind == 'NUM' and self.peek().val.isdigit() and not self.is_word('TIMES', k=1):
            first = self._procref()
            if self.accept('THRU', 'THROUGH'):
                last = self._procref()
        st = Perform(loc, first, last)
        if first is None and self.accept('FOREVER'):
            st.until = ConstCond(False)
            st.body = self.parse_statements()
            self.expect('END-PERFORM')
            return st
        if self.is_word('WITH', 'TEST', 'UNTIL', 'VARYING'):
            if self.accept('WITH'):
                self.expect('TEST')
                st.test_after = self.expect('BEFORE', 'AFTER').up == 'AFTER'
            elif self.accept('TEST'):
                st.test_after = self.expect('BEFORE', 'AFTER').up == 'AFTER'
            if self.accept('UNTIL'):
                if self.accept('EXIT'):
                    st.until = ConstCond(False)
                else:
                    st.until = self.parse_condition()
            elif self.accept('VARYING'):
                st.varying = []
                while True:
                    var = self.parse_identifier()
                    self.expect('FROM')
                    frm = self.parse_expr()
                    self.expect('BY')
                    by = self.parse_expr()
                    self.expect('UNTIL')
                    cond = self.parse_condition()
                    st.varying.append(Varying(var, frm, by, cond))
                    if not self.accept('AFTER'):
                        break
            else:
                raise self.err("UNTIL or VARYING expected")
        elif self.accept('FOREVER'):
            st.until = ConstCond(False)        # as UNTIL EXIT: only EXIT PERFORM
        elif self.peek().kind == 'NUM' or self.is_user_word() or \
                self.is_word('FUNCTION', 'LENGTH', 'BYTE-LENGTH'):
            st.times = self.parse_expr()
            self.expect('TIMES')
        if first is None:
            st.body = self.parse_statements()
            self.expect('END-PERFORM')
        return st

    def _procref(self):
        t = self.next()
        if t.kind == 'WORD':
            name = t.up
        elif t.kind == 'NUM':
            name = t.val
        else:
            raise self.err("procedure name expected", t)
        qual = None
        if self.is_word('OF', 'IN') and self.peek(1).kind == 'WORD':
            self.next()
            qual = self.next().up
        return ProcRef(name, qual, t.loc)

    # ---- control flow
    def p_GO(self, loc):
        self.accept('TO')
        targets = []
        while self.is_user_word() or (self.peek().kind == 'NUM' and not self.is_word('DEPENDING', k=0)):
            targets.append(self._procref())
        dep = None
        if self.accept('DEPENDING'):
            self.accept('ON')
            dep = self.parse_identifier()
        return GoTo(loc, targets, dep)

    def p_STOP(self, loc):
        if self.accept('RUN'):
            ret = None
            if self.accept('RETURNING', 'GIVING'):
                ret = self.parse_operand()
            elif self.is_word('ERROR', 'NORMAL') or self.is_word('WITH'):
                # STOP RUN NORMAL / STOP RUN ERROR / STOP RUN WITH ERROR STATUS
                if not self.accept('WITH'):
                    pass
                w = self.expect('ERROR', 'NORMAL').up
                self.accept('STATUS')
                ret = make_numlit('1' if w == 'ERROR' else '0')
                if self.is_operand_start():
                    ret = self.parse_operand()
            elif self.is_operand_start():
                ret = self.parse_operand()      # STOP RUN 4 (extension)
            return StopRun(loc, ret)
        if self.peek().kind in ('STR', 'NUM') or self.is_word(*FIGURATIVES.keys()):
            lit = self.parse_operand()
            return Display(loc, [lit])
        raise self.err("RUN expected")

    def p_GOBACK(self, loc):
        ret = None
        if self.accept('RETURNING', 'GIVING'):
            ret = self.parse_operand()
        return GoBack(loc, ret)

    def p_EXIT(self, loc):
        if self.accept('PROGRAM'):
            ex = Exit(loc, 'PROGRAM')
            if self.accept('RETURNING', 'GIVING'):
                ex.returning = self.parse_operand()
            return ex
        if self.accept('PERFORM'):
            if self.accept('CYCLE'):
                return Exit(loc, 'CYCLE')
            return Exit(loc, 'PERFORM')
        if self.accept('PARAGRAPH'):
            return Exit(loc, 'PARAGRAPH')
        if self.accept('SECTION'):
            return Exit(loc, 'SECTION')
        return Exit(loc, '')

    def p_CONTINUE(self, loc):
        return Continue(loc)

    def p_NEXT(self, loc):
        self.expect('SENTENCE')
        return NextSentence(loc)

    def p_ALTER(self, loc):
        pairs = []
        while True:
            a = self._procref()
            self.expect('TO')
            if self.accept('PROCEED'):
                self.expect('TO')
            b = self._procref()
            pairs.append((a, b))
            if not (self.is_user_word() or (self.peek().kind == 'NUM' and self.is_word('TO', k=1))):
                break
        return Alter(loc, pairs)

    # ---- string handling
    def p_STRING(self, loc):
        sources = []
        while True:
            group = []
            while self.is_operand_start() or self.is_word('ALL'):
                group.append(self.parse_operand(allow_all=True))
            if not group:
                break
            if self.accept('DELIMITED'):
                self.accept('BY')
                if self.accept('SIZE'):
                    d = 'SIZE'
                else:
                    d = self.parse_operand(allow_all=True)
            else:
                d = 'SIZE'
            for g in group:
                sources.append((g, d))
            if self.is_word('INTO'):
                break
        self.expect('INTO')
        into = self.parse_identifier()
        ptr = None
        if self.accept('WITH'):
            self.expect('POINTER')
            ptr = self.parse_identifier()
        elif self.accept('POINTER'):
            ptr = self.parse_identifier()
        on, noton = self._overflow()
        self._end('END-STRING')
        return StringStmt(loc, sources, into, ptr, on, noton)

    def p_UNSTRING(self, loc):
        # identifier-1 in the standard, but GnuCOBOL, Micro Focus and IBM all
        # accept a literal or figurative constant here, and programs use it
        src = self.parse_operand()
        delims = []
        if self.accept('DELIMITED'):
            self.accept('BY')
            while True:
                al = bool(self.accept('ALL'))
                delims.append((al, self.parse_operand()))
                if not self.accept('OR'):
                    break
        self.expect('INTO')
        intos = []
        while self.is_user_word():
            tgt = self.parse_identifier()
            ui = UnstringInto(tgt, None, None)
            if self.accept('DELIMITER'):
                self.accept('IN')
                ui.delim_in = self.parse_identifier()
            if self.accept('COUNT'):
                self.accept('IN')
                ui.count_in = self.parse_identifier()
            intos.append(ui)
        ptr = tally = None
        while True:
            if self.accept('WITH'):
                self.expect('POINTER')
                ptr = self.parse_identifier()
            elif self.accept('POINTER'):
                ptr = self.parse_identifier()
            elif self.accept('TALLYING'):
                self.accept('IN')
                tally = self.parse_identifier()
            else:
                break
        on, noton = self._overflow()
        self._end('END-UNSTRING')
        return Unstring(loc, src, delims, intos, ptr, tally, on, noton)

    def _inspect_region(self):
        reg = InspectRegion()
        while self.is_word('BEFORE', 'AFTER'):
            w = self.next().up
            self.accept('INITIAL')
            v = self.parse_operand()
            if w == 'BEFORE':
                reg.before = v
            else:
                reg.after = v
        return reg

    def p_INSPECT(self, loc):
        target = self.parse_identifier()
        st = Inspect(loc, target, [], [], None)
        if self.accept('TALLYING'):
            counter = None
            mode = None
            while True:
                if self.is_word('CHARACTERS'):
                    self.next()
                    if counter is None:
                        raise self.err("counter expected")
                    st.tallying.append(InspectOp('CHARACTERS', None, None, counter, self._inspect_region()))
                    mode = None
                    continue
                if self.is_word('ALL', 'LEADING', 'TRAILING'):
                    mode = self.next().up
                    continue
                if self.is_word('REPLACING') or not (self.is_operand_start()):
                    break
                save = self.pos
                if self.is_user_word():
                    ref = self.parse_identifier()
                    if self.accept('FOR'):
                        counter = ref
                        mode = None
                        continue
                    self.pos = save
                if mode is None:
                    raise self.err("ALL, LEADING or CHARACTERS expected")
                pat = self.parse_operand()
                st.tallying.append(InspectOp(mode, pat, None, counter, self._inspect_region()))
        if self.accept('REPLACING'):
            mode = None
            while True:
                if self.is_word('CHARACTERS'):
                    self.next()
                    self.expect('BY')
                    by = self.parse_operand()
                    st.replacing.append(InspectOp('CHARACTERS', None, by, None, self._inspect_region()))
                    mode = None
                    continue
                if self.is_word('ALL', 'LEADING', 'FIRST', 'TRAILING'):
                    mode = self.next().up
                    continue
                if mode is None or not self.is_operand_start():
                    break
                pat = self.parse_operand()
                self.expect('BY')
                by = self.parse_operand()
                st.replacing.append(InspectOp(mode, pat, by, None, self._inspect_region()))
        if self.accept('CONVERTING'):
            a = self.parse_operand()
            self.expect('TO')
            b = self.parse_operand()
            st.converting = (a, b, self._inspect_region())
        if not (st.tallying or st.replacing or st.converting):
            raise self.err("TALLYING, REPLACING or CONVERTING expected")
        return st

    # ---- INITIALIZE / SET
    def p_INITIALIZE(self, loc):
        targets = []
        # the clause words end the target list; they are user words otherwise
        CLAUSE = {'WITH', 'FILLER', 'ALL', 'ALPHANUMERIC', 'NUMERIC', 'ALPHABETIC',
                  'ALPHANUMERIC-EDITED', 'NUMERIC-EDITED', 'NATIONAL', 'REPLACING',
                  'DEFAULT', 'VALUE'}
        while self.is_user_word() and self.peek().up not in CLAUSE:
            targets.append(self.parse_identifier())
        st = Initialize(loc, targets, [])
        while True:
            if self.accept('WITH'):
                self.expect('FILLER')
                st.with_filler = True
            elif self.is_word('FILLER'):
                self.next()
                st.with_filler = True
            elif self.is_word('ALL') and self.is_word('TO', k=1):
                self.next(); self.next(); self.expect('VALUE')
                st.to_value = True
            elif self.is_word('ALL') and self.is_word('VALUE', k=1):
                # INITIALIZE x ALL VALUE (GnuCOBOL: the same as ALL TO VALUE)
                self.next(); self.next()
                st.to_value = True
            elif self.accept('DEFAULT'):
                pass        # INITIALIZE x DEFAULT is the plain default behaviour
            elif self.is_word('ALPHANUMERIC', 'NUMERIC', 'ALPHABETIC', 'ALPHANUMERIC-EDITED',
                              'NUMERIC-EDITED', 'NATIONAL') and self.is_word('TO', k=1):
                self.next(); self.next(); self.expect('VALUE')
                st.to_value = True
            elif self.accept('THEN'):
                pass
            elif self.accept('REPLACING'):
                while self.is_word('ALPHANUMERIC', 'NUMERIC', 'ALPHABETIC', 'ALPHANUMERIC-EDITED',
                                   'NUMERIC-EDITED', 'NATIONAL', 'NATIONAL-EDITED'):
                    cat = self.next().up
                    self.accept('DATA')
                    self.expect('BY')
                    st.replacing.append((cat, self.parse_operand(allow_all=True)))
            elif self.is_word('TO') and self.is_word('DEFAULT', k=1):
                self.next(); self.next()
                st.to_default = True
            else:
                break
        return st

    def p_SET(self, loc):
        if self.is_word('LAST') and self.is_word('EXCEPTION', k=1):
            self.next(); self.next()
            self.expect('TO')
            return SetStmt(loc, 'EXCEPTION', [], self.expect('OFF').up)
        # SET ADDRESS OF item TO pointer: point a LINKAGE item at storage
        if self.is_word('ADDRESS') and self.is_word('OF', k=1):
            self.next(); self.next()
            ref = self.parse_identifier()
            self.expect('TO')
            st = SetStmt(loc, 'ADDRESS', [], self.parse_operand())
            st.addr_ref = ref
            return st
        targets = []
        while self.is_user_word() or self.is_word('ADDRESS'):
            if self.is_word('ADDRESS'):
                raise self.err("SET ADDRESS OF needs an item after OF")
            targets.append(self.parse_identifier())
        if not targets:
            raise self.err("SET target expected")
        if self.accept('TO'):
            if self.accept('TRUE'):
                return SetStmt(loc, 'TRUE', targets)
            if self.accept('FALSE'):
                return SetStmt(loc, 'FALSE', targets)
            if self.is_word('ON', 'OFF'):
                first = SetStmt(loc, 'SWITCH', targets, self.next().up == 'ON')
                more = [first]
                while self.is_user_word():
                    tg = []
                    while self.is_user_word():
                        tg.append(self.parse_identifier())
                    self.expect('TO')
                    more.append(SetStmt(loc, 'SWITCH', tg, self.expect('ON', 'OFF').up == 'ON'))
                return first if len(more) == 1 else StmtBlock(loc, more)
            if self.is_word('SIZE') and self.is_word('OF', k=1):
                self.next(); self.next()
                return SetStmt(loc, 'TO', targets, LengthOf(self.parse_identifier()))
            v = self.parse_expr()
            return SetStmt(loc, 'TO', targets, v)
        if self.is_word('UP', 'DOWN'):
            down = self.next().up == 'DOWN'
            self.expect('BY')
            v = self.parse_expr()
            return SetStmt(loc, 'UPDOWN', targets, v, down)
        raise self.err("TO, UP BY or DOWN BY expected")

    # ---- SEARCH
    def p_SEARCH(self, loc):
        al = bool(self.accept('ALL'))
        table = self.parse_identifier()
        varying = None
        if not al and self.accept('VARYING'):
            varying = self.parse_identifier()
        at_end, _ = self._at_end()
        whens = []
        while self.accept('WHEN'):
            c = self.parse_condition()
            stmts = self.parse_statements()
            whens.append(SearchWhen(c, stmts))
        if not whens:
            raise self.err("WHEN expected")
        self._end('END-SEARCH')
        return Search(loc, table, al, varying, at_end, whens)

    # ---- CALL
    def p_CALL(self, loc):
        t = self.peek()
        if t.kind == 'STR':
            self.next()
            prog = StrLit(t.val)
        else:
            prog = self.parse_identifier()
        args = []
        if self.accept('USING'):
            mode = 'REFERENCE'
            while True:
                if self.accept('BY'):
                    mode = self.expect('REFERENCE', 'CONTENT', 'VALUE').up
                elif self.is_word('REFERENCE', 'CONTENT', 'VALUE'):
                    mode = self.next().up
                elif self.accept('OMITTED'):
                    args.append(CallArg(mode, 'OMITTED'))
                elif self.is_word('ADDRESS') and self.is_word('OF', k=1):
                    self.next(); self.next()
                    args.append(CallArg(mode, AddressOf(self.parse_identifier())))
                elif self.is_operand_start():
                    args.append(CallArg(mode, self.parse_operand()))
                else:
                    break
        ret = None
        omitted_ret = False
        if self.accept('RETURNING', 'GIVING'):
            if self.accept('OMITTED'):          # CALL ... RETURNING OMITTED
                omitted_ret = True
            else:
                ret = self.parse_identifier()
        on, noton = self._exception()
        self._end('END-CALL')
        call = Call(loc, prog, args, ret, on, noton)
        call.returning_omitted = omitted_ret
        return call

    def p_CANCEL(self, loc):
        progs = []
        while self.is_operand_start():
            progs.append(self.parse_operand())
        return Cancel(loc, progs)

    # ---- file I/O
    def p_OPEN(self, loc):
        modes = []
        while self.is_word('INPUT', 'OUTPUT', 'I-O', 'EXTEND'):
            m = self.next().up
            files = []
            while self.is_user_word():
                files.append(self.next().up)
                while self.is_word('WITH', 'NO', 'REWIND', 'REVERSED', 'LOCK'):
                    self.next()
            modes.append((m, files))
        if not modes:
            raise self.err("INPUT, OUTPUT, I-O or EXTEND expected")
        return Open(loc, modes)

    def p_CLOSE(self, loc):
        files = []
        opts = []
        while self.is_user_word():
            files.append(self.next().up)
            opt = 0
            while self.is_word('WITH', 'NO', 'REWIND', 'LOCK', 'REEL', 'UNIT', 'FOR', 'REMOVAL'):
                w = self.next().up
                if w in ('REEL', 'UNIT'):
                    opt = 1
                elif w == 'REWIND':
                    opt = 2
                elif w == 'LOCK':
                    opt = 3
            opts.append(opt)
        st = Close(loc, files)
        st.opts = opts
        return st

    def p_READ(self, loc):
        f = self.user_word('file name')
        direction = ''
        if self.is_word('NEXT', 'PREVIOUS'):
            direction = self.next().up
        self.accept('RECORD')
        into = key = None
        if self.accept('INTO'):
            into = self.parse_identifier()
        while self.is_word('WITH', 'NO', 'LOCK', 'IGNORING', 'KEPT'):
            self.next()
        if self.accept('KEY'):
            self.accept('IS')
            key = self.parse_identifier()
        st = Read(loc, f, direction, into, key, None, None, None, None)
        while True:
            a, na = self._at_end()
            if a is not None:
                st.at_end = a
            if na is not None:
                st.not_at_end = na
            i, ni = self._invalid_key()
            if i is not None:
                st.invalid = i
            if ni is not None:
                st.not_invalid = ni
            if a is None and na is None and i is None and ni is None:
                break
        self._end('END-READ')
        return st

    def p_WRITE(self, loc):
        file_name = None
        if self.accept('FILE'):
            # WRITE FILE file-name FROM ... (COBOL 2014): the file's record area
            file_name = self.user_word('file name')
            rec = DataRef(file_name, [], [], None, loc)
        else:
            rec = self.parse_identifier()
        frm = None
        if self.accept('FROM'):
            frm = self.parse_operand()
        when = ''
        lines = None
        if self.is_word('BEFORE', 'AFTER'):
            when = self.next().up
            self.accept('ADVANCING')
            if self.accept('PAGE'):
                lines = 'PAGE'
            elif self.is_user_word() and self.peek().up in self.mnemonics:
                self.next()
                lines = 'PAGE'
            else:
                lines = self.parse_operand()
                self.accept('LINE', 'LINES')
        st = Write(loc, rec, frm, when, lines, None, None)
        st.file_name = file_name
        while True:
            progress = False
            if (self.is_word('AT') and self.is_word('END-OF-PAGE', 'EOP', k=1)) or self.is_word('END-OF-PAGE', 'EOP'):
                self.accept('AT'); self.next()
                st.eop = self.parse_statements()
                progress = True
            if self.is_word('NOT') and (self.is_word('END-OF-PAGE', 'EOP', k=1) or (self.is_word('AT', k=1) and self.is_word('END-OF-PAGE', 'EOP', k=2))):
                self.next(); self.accept('AT'); self.next()
                st.not_eop = self.parse_statements()
                progress = True
            i, ni = self._invalid_key()
            if i is not None:
                st.invalid = i
                progress = True
            if ni is not None:
                st.not_invalid = ni
                progress = True
            if not progress:
                break
        self._end('END-WRITE')
        return st

    def p_REWRITE(self, loc):
        file_name = None
        if self.accept('FILE'):
            file_name = self.user_word('file name')
            rec = DataRef(file_name, [], [], None, loc)
        else:
            rec = self.parse_identifier()
        frm = None
        if self.accept('FROM'):
            frm = self.parse_operand()
        while self.is_word('WITH', 'NO', 'LOCK'):
            self.next()
        i, ni = self._invalid_key()
        self._end('END-REWRITE')
        st = Rewrite(loc, rec, frm, i, ni)
        st.file_name = file_name
        return st

    def p_DELETE(self, loc):
        if self.accept('FILE'):
            files = []
            while self.is_user_word():
                files.append(self.next().up)
            if not files:
                raise self.err("file name expected")
            self._end('END-DELETE')
            return DeleteFile(loc, files)
        f = self.user_word('file name')
        self.accept('RECORD')
        i, ni = self._invalid_key()
        self._end('END-DELETE')
        return Delete(loc, f, i, ni)

    def p_START(self, loc):
        f = self.user_word('file name')
        op = 'EQ'
        key = None
        if self.is_word('FIRST', 'LAST'):
            op = self.next().up
        elif self.accept('KEY'):
            op = self.parse_relop()
            key = self.parse_identifier()
        i, ni = self._invalid_key()
        self._end('END-START')
        return Start(loc, f, op, key, i, ni)

    def p_SORT(self, loc):
        return self._sort_merge(loc, False)

    def p_MERGE(self, loc):
        return self._sort_merge(loc, True)

    def _sort_merge(self, loc, merge):
        target = self.parse_identifier()
        keys = []
        while True:
            self.accept('ON')
            if self.is_word('ASCENDING', 'DESCENDING'):
                desc = self.next().up == 'DESCENDING'
                self.accept('KEY')
                self.accept('IS')
                n = len(keys)
                while self.is_user_word():
                    keys.append(SortKey(desc, self.parse_identifier()))
                if len(keys) == n:
                    keys.append(SortKey(desc, None))    # table SORT: the whole element
            else:
                break
        dups = False
        if self.accept('WITH'):
            self.expect('DUPLICATES')
            dups = True
        elif self.accept('DUPLICATES'):
            dups = True
        if dups:
            self.accept('IN')
            self.accept('ORDER')
        coll = None
        if self.is_word('COLLATING') or self.is_word('SEQUENCE'):
            self.accept('COLLATING')
            self.expect('SEQUENCE')
            self.accept('IS')
            coll = self.next().up
            if self.is_user_word() and not self.is_word('USING', 'INPUT', 'GIVING', 'OUTPUT'):
                self.next()
        st = Sort(loc, target.name, keys, dups, [], [], None, None, merge)
        st.collating = coll
        if self.accept('USING'):
            while self.is_user_word():
                st.using.append(self.next().up)
        elif self.accept('INPUT'):
            self.expect('PROCEDURE')
            self.accept('IS')
            a = self._procref()
            b = None
            if self.accept('THRU', 'THROUGH'):
                b = self._procref()
            st.input_proc = (a, b)
        if self.accept('GIVING'):
            while self.is_user_word():
                st.giving.append(self.next().up)
        elif self.accept('OUTPUT'):
            self.expect('PROCEDURE')
            self.accept('IS')
            a = self._procref()
            b = None
            if self.accept('THRU', 'THROUGH'):
                b = self._procref()
            st.output_proc = (a, b)
        if not st.using and not st.input_proc and not st.giving and not st.output_proc:
            st.table = target
        return st

    def p_INITIATE(self, loc):
        names = []
        while self.is_user_word():
            names.append(self.next().up)
        if not names:
            raise self.err("report name expected")
        return Initiate(loc, names)

    def p_GENERATE(self, loc):
        return Generate(loc, self.parse_identifier())

    def p_TERMINATE(self, loc):
        names = []
        while self.is_user_word():
            names.append(self.next().up)
        if not names:
            raise self.err("report name expected")
        return Terminate(loc, names)

    def p_SUPPRESS(self, loc):
        self.accept('PRINTING')
        return Suppress(loc)

    def p_RELEASE(self, loc):
        rec = self.parse_identifier()
        frm = None
        if self.accept('FROM'):
            frm = self.parse_operand()
        return Release(loc, rec, frm)

    def p_RETURN(self, loc):
        f = self.user_word('file name')
        self.accept('RECORD')
        into = None
        if self.accept('INTO'):
            into = self.parse_identifier()
        a, na = self._at_end()
        self._end('END-RETURN')
        return Return(loc, f, into, a, na)

    # ---------------------------------------------------------- operands / identifiers
    def is_operand_start(self, k=0):
        t = self.peek(k)
        if t.kind in ('NUM', 'STR'):
            return True
        if t.kind == 'WORD':
            u = t.up
            if u in FIGURATIVES or u == 'FUNCTION':
                return True
            if u in ('LENGTH', 'BYTE-LENGTH'):
                if self.is_word('OF', k=k + 1) or self.is_operand_start(k + 1):
                    return True
            if u not in RESERVED or u in SPECIAL_REGISTERS or u in CONTEXT_WORDS:
                return True
            return False
        if t.kind == 'OP' and t.val in ('+', '-') and self.peek(k + 1).kind == 'NUM':
            return True
        return False

    def parse_operand(self, allow_all=False):
        t = self.peek()
        if t.kind == 'NUM':
            self.next()
            return make_numlit(t.val, t.loc)
        if t.kind == 'STR':
            self.next()
            return StrLit(t.val)
        if t.kind == 'OP' and t.val in ('+', '-') and self.peek(1).kind == 'NUM':
            self.next()
            n = self.next()
            return make_numlit(t.val + n.val, n.loc)
        if t.kind == 'WORD':
            u = t.up
            if u in self.udfs:
                self.next()
                args = []
                if self.peek().kind == '(':
                    self.next()
                    while self.peek().kind != ')':
                        args.append(self.parse_operand())
                        if self.peek().kind == ',':
                            self.next()
                    self.next()
                return FuncCall(u, args, None, t.loc)
            if u in FIGURATIVES:
                self.next()
                return Figurative(FIGURATIVES[u])
            if u == 'ALL' and allow_all:
                self.next()
                v = self.parse_operand()
                return self._make_all(v, t)
            if u in self.prog.symbolic:
                self.next()
                return StrLit(bytes([self.prog.symbolic[u]]))
            if u in self.prog.constants:
                self.next()
                return self.prog.constants[u]
            vcx = self.visible_constants()
            if u in vcx:
                self.next()
                return vcx[u]
            return self.parse_identifier()
        raise self.err("operand expected")

    def parse_identifier(self):
        t = self.peek()
        if t.kind == 'WORD' and t.up == 'FUNCTION':
            return self.parse_function()
        if t.kind == 'WORD' and t.up in ('LENGTH', 'BYTE-LENGTH') and not self.is_word('OF', k=1) \
                and self.is_operand_start(1):
            # LENGTH X without OF: a GnuCOBOL extension
            self.next()
            return LengthOf(self.parse_identifier())
        if t.kind == 'WORD' and t.up in ('LENGTH', 'BYTE-LENGTH') and self.is_word('OF', k=1):
            self.next(); self.next()
            if self.peek().kind == 'STR':           # LENGTH OF literal
                return make_numlit(str(len(self.parse_value_literal().value)))
            ref = self.parse_identifier()
            if isinstance(ref, StrLit):              # LENGTH OF constant-name
                return make_numlit(str(len(ref.value)))
            return LengthOf(ref)
        if t.kind == 'WORD' and t.up == 'ADDRESS' and self.is_word('OF', k=1):
            self.next(); self.next()
            return AddressOf(self.parse_identifier())
        if not (t.kind == 'WORD' and (t.up not in RESERVED or t.up in SPECIAL_REGISTERS
                                      or t.up in CONTEXT_WORDS)):
            raise self.err("identifier expected")
        self.next()
        if t.up in self.prog.constants:
            return self.prog.constants[t.up]
        name = t.up
        quals = []
        while self.is_word('OF', 'IN') and self.peek(1).kind == 'WORD' and self.peek(1).up not in RESERVED:
            self.next()
            quals.append(self.next().up)
        subs = []
        refmod = None
        if self.peek().kind == '(' and not self.peek().sep:
            subs, refmod = self._subs_refmod()
        return DataRef(name, quals, subs, refmod, t.loc)

    def _subs_refmod(self):
        self.expect_kind('(')
        if self.peek().kind == ':':
            raise self.err("reference modification start expected")
        first = self._sub_expr()
        if self.peek().kind == ':':
            self.next()
            length = None if self.peek().kind == ')' else self.parse_expr()
            self.expect_kind(')', "')'")
            return [], (first, length)
        subs = [first]
        while self.peek().kind != ')':
            if self.peek().kind == 'EOF':
                raise self.err("')' expected")
            subs.append(self._sub_expr())
        self.next()
        refmod = None
        if self.peek().kind == '(' and self._refmod_ahead():
            self.next()
            start = self.parse_expr()
            self.expect_kind(':', "':'")
            length = None if self.peek().kind == ')' else self.parse_expr()
            self.expect_kind(')', "')'")
            refmod = (start, length)
        return subs, refmod

    def _refmod_ahead(self):
        depth = 0
        i = self.pos
        while i < len(self.toks):
            t = self.toks[i]
            if t.kind == '(':
                depth += 1
            elif t.kind == ')':
                depth -= 1
                if depth == 0:
                    return False
            elif t.kind == ':' and depth == 1:
                return True
            elif t.kind in ('.', 'EOF'):
                return False
            i += 1
        return False

    def _sub_expr(self):
        if self.accept('ALL'):
            return 'ALL'
        return self.parse_expr(split_signed=False)

    def parse_function(self):
        ft = self.next()  # FUNCTION
        nt = self.next()
        if nt.kind != 'WORD':
            raise self.err("function name expected", nt)
        name = nt.up
        if name not in FUNCTIONS and name not in getattr(self, 'udfs', set()):
            raise ParseError(f"unknown intrinsic function '{name}'", nt.loc)
        if name in getattr(self, 'udfs', set()) and name not in FUNCTIONS:
            # a user-defined function: parsed like a call with arguments
            args = []
            if self.peek().kind == '(':
                self.next()
                while self.peek().kind != ')':
                    args.append(self.parse_operand())
                    if self.peek().kind == ',':
                        self.next()
                self.next()
            return FuncCall(name, args, None, nt.loc)
        args = []
        refmod = None
        if self.peek().kind == '(' and not (FUNCTIONS[name][2] == 0 and self._refmod_ahead()):
            self.next()
            if name == 'TRIM':
                pass
            while self.peek().kind != ')':
                if self.peek().kind == 'EOF':
                    raise self.err("')' expected")
                if name in ('TRIM',) and self.is_word('LEADING', 'TRAILING'):
                    args.append(StrLit(self.next().up.encode()))
                    continue
                if name in ('FORMATTED-TIME', 'FORMATTED-DATETIME') and self.is_word('SYSTEM-OFFSET'):
                    args.append(StrLit(self.next().up.encode()))
                    continue
                args.append(self.parse_expr(split_signed=False))
            self.next()
        if self.peek().kind == '(' and self._refmod_ahead():
            self.next()
            start = self.parse_expr()
            self.expect_kind(':', "':'")
            length = None if self.peek().kind == ')' else self.parse_expr()
            self.expect_kind(')', "')'")
            refmod = (start, length)
        kind, mn, mx = FUNCTIONS[name]
        nargs = len([a for a in args if not (name == 'TRIM' and isinstance(a, StrLit) and a.value in (b'LEADING', b'TRAILING'))])
        if not (mn <= nargs <= mx):
            raise ParseError(f"wrong number of arguments for FUNCTION {name}", nt.loc)
        return FuncCall(name, args, refmod, nt.loc)

    # ---------------------------------------------------------- expressions
    def parse_expr(self, split_signed=True):
        if getattr(self, 'const_expr', False):
            # A constant expression has no operator precedence: it applies
            # each operator to the accumulated value in source order, with
            # parentheses grouping (GnuCOBOL's "left to right precedence").
            left = self._unary()
            while True:
                t = self.peek()
                if t.kind == 'OP' and t.val in ('+', '-', '*', '/', '**'):
                    self.next()
                    left = BinOp(t.val, left, self._unary())
                elif split_signed and t.kind == 'NUM' and t.val[0] in '+-':
                    self.next()
                    left = BinOp(t.val[0], left, self._unary(make_numlit(t.val[1:], t.loc)))
                else:
                    return left
        left = self._term()
        while True:
            t = self.peek()
            if t.kind == 'OP' and t.val in ('+', '-'):
                self.next()
                right = self._term()
                left = BinOp(t.val, left, right)
            elif split_signed and t.kind == 'NUM' and t.val[0] in '+-':
                self.next()
                lit = make_numlit(t.val[1:], t.loc)
                right = self._term(lit)
                left = BinOp(t.val[0], left, right)
            else:
                return left

    def _term(self, first=None):
        left = self._power(first)
        while True:
            t = self.peek()
            if t.kind == 'OP' and t.val in ('*', '/'):
                self.next()
                right = self._power()
                left = BinOp(t.val, left, right)
            else:
                return left

    def _power(self, first=None):
        left = first if first is not None else self._unary()
        while self.peek().kind == 'OP' and self.peek().val == '**':
            self.next()
            right = self._unary()
            left = BinOp('**', left, right)
        return left

    def _unary(self, first=None):
        if first is not None:
            return first
        t = self.peek()
        if t.kind == 'OP' and t.val == '-':
            self.next()
            return Neg(self._unary())
        if t.kind == 'OP' and t.val == '+':
            self.next()
            return self._unary()
        return self._primary()

    def _primary(self):
        t = self.peek()
        # a REPOSITORY-declared function may be called without the FUNCTION
        # keyword, with or without arguments
        if t.kind == 'WORD' and t.up in self.udfs:
            self.next()
            args = []
            if self.peek().kind == '(':
                self.next()
                while self.peek().kind != ')':
                    args.append(self.parse_operand())
                    if self.peek().kind == ',':
                        self.next()
                self.next()
            return FuncCall(t.up, args, None, t.loc)
        if t.kind == '(':
            self.next()
            e = self.parse_expr()
            self.expect_kind(')', "')'")
            return e
        if t.kind == 'WORD' and t.up == 'ADDRESS' and self.is_word('OF', k=1):
            self.next(); self.next()
            return AddressOf(self.parse_identifier())
        if t.kind == 'WORD' and t.up == 'ALL':
            return self.parse_operand(allow_all=True)
        if t.kind in ('NUM', 'STR', 'WORD'):
            if t.kind == 'WORD' and t.up in RESERVED and t.up not in FIGURATIVES and t.up not in (
                    'FUNCTION', 'LENGTH') and t.up not in SPECIAL_REGISTERS:
                raise self.err("operand expected")
            return self.parse_operand()
        raise self.err("operand expected")

    # ---------------------------------------------------------- conditions
    def parse_condition(self):
        saved = (self.subj, self.relop)
        self.subj = None
        self.relop = None
        try:
            return self._or()
        finally:
            self.subj, self.relop = saved

    def _or(self):
        left = self._and()
        while self.is_word('OR'):
            self.next()
            right = self._and()
            left = Or(left, right)
        return left

    def _and(self):
        left = self._not()
        while self.is_word('AND'):
            self.next()
            right = self._not()
            left = And(left, right)
        return left

    def _not(self):
        if self.is_word('NOT'):
            if self.subj is not None and self._relop_start(1, allow_not=False):
                self.next()
                op = NEGATE[self.parse_relop()]
                right = self.parse_expr()
                self.relop = op
                return Rel(self.subj, op, right)
            self.next()
            return Not(self._not())
        return self._simple()

    def _relop_start(self, k=0, allow_not=True):
        t = self.peek(k)
        if t.kind == 'OP' and t.val in RELOP_SYM:
            return True
        if t.kind == 'WORD':
            if t.up in ('EQUAL', 'EQUALS', 'GREATER', 'LESS'):
                return True
            if t.up == 'IS':
                return self._relop_start(k + 1, allow_not)
            if t.up == 'NOT' and allow_not:
                return self._relop_start(k + 1, False)
        return False

    def parse_relop(self):
        self.accept('IS')
        neg = bool(self.accept('NOT'))
        t = self.next()
        if t.kind == 'OP' and t.val in RELOP_SYM:
            op = RELOP_SYM[t.val]
        elif t.kind == 'WORD' and t.up in ('EQUAL', 'EQUALS'):
            self.accept('TO')
            op = 'EQ'
        elif t.kind == 'WORD' and t.up == 'GREATER':
            self.accept('THAN')
            if self.is_word('OR') and self.is_word('EQUAL', k=1):
                self.next(); self.next(); self.accept('TO')
                op = 'GE'
            else:
                op = 'GT'
        elif t.kind == 'WORD' and t.up == 'LESS':
            self.accept('THAN')
            if self.is_word('OR') and self.is_word('EQUAL', k=1):
                self.next(); self.next(); self.accept('TO')
                op = 'LE'
            else:
                op = 'LT'
        else:
            raise self.err("relational operator expected", t)
        return NEGATE[op] if neg else op

    def _simple(self):
        t = self.peek()
        # IF item OMITTED: was the CALL argument left out?
        if t.kind == 'WORD' and self.is_user_word() and (
                self.is_word('OMITTED', k=1) or
                (self.is_word('NOT', k=1) and self.is_word('OMITTED', k=2))):
            ref = self.parse_identifier()
            neg = False
            if self.accept('NOT'):
                neg = True
            self.expect('OMITTED')
            return OmittedCond(ref, neg)
        if t.kind == '(':
            save = self.pos
            ctx = (self.subj, self.relop)
            try:
                self.next()
                c = self._or()
                if self.peek().kind != ')':
                    raise Backtrack()
                self.next()
                nt = self.peek()
                if (nt.kind == 'OP' and nt.val in ('+', '-', '*', '/', '**')) or self._relop_start() or \
                        (nt.kind == 'NUM' and nt.val[0] in '+-'):
                    raise Backtrack()
                if isinstance(c, MaybeCond) and c.subject is None:
                    # parenthesised operand: let caller treat as expression
                    pass
                return c
            except (Backtrack, ParseError):
                self.pos = save
                self.subj, self.relop = ctx
        if self.subj is not None and self._relop_start():
            op = self.parse_relop()
            right = self.parse_expr()
            self.relop = op
            return Rel(self.subj, op, right)
        left = self.parse_expr()
        save = self.pos
        self.accept('IS')
        neg = bool(self.accept('NOT'))
        t = self.peek()
        if t.kind == 'WORD' and (t.up in CLASS_WORDS or t.up in self.class_names):
            self.next()
            return ClassTest(left, t.up, neg)
        if t.kind == 'WORD' and t.up in SIGN_WORDS:
            self.next()
            return SignTest(left, SIGN_WORDS[t.up], neg)
        if self._relop_start(0, allow_not=False):
            op = self.parse_relop()
            if neg:
                op = NEGATE[op]
            # "IF 1 = (1 OR 2)": a parenthesised condition to the right of a
            # relation is the abbreviated form, where each operand inside is
            # compared with the subject - GnuCOBOL's semi-parenthesised
            # condition. Fall back to an arithmetic parenthesis otherwise.
            if self.peek().kind == '(':
                save2 = self.pos
                ctx2 = (self.subj, self.relop)
                try:
                    self.next()
                    self.subj, self.relop = left, op
                    inner = self._or()
                    if self.peek().kind != ')':
                        raise Backtrack()
                    self.next()
                    nt = self.peek()
                    if (nt.kind == 'OP' and nt.val in ('+', '-', '*', '/', '**')) \
                            or self._relop_start():
                        raise Backtrack()
                    self.subj, self.relop = left, op
                    return inner
                except (Backtrack, ParseError):
                    self.pos = save2
                    self.subj, self.relop = ctx2
            right = self.parse_expr()
            self.subj = left
            self.relop = op
            return Rel(left, op, right)
        if neg:
            raise self.err("relational operator or class condition expected")
        self.pos = save
        return MaybeCond(left, self.subj, self.relop)
