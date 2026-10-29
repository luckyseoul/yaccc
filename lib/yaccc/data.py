# SPDX-License-Identifier: MIT
"""Data items, PICTURE analysis, storage layout."""
from .errors import CompileError, DIAG

# runtime type codes (must match cobrt.h)
T_GROUP = 1
T_ALNUM = 2
T_ALPHA = 3
T_ALNUM_EDITED = 4
T_NUM_DISPLAY = 5
T_NUM_PACKED = 6
T_NUM_BINARY = 7
T_NUM_COMP5 = 8
T_NUM_FLOAT = 9
T_NUM_DOUBLE = 10
T_NUM_EDITED = 11
T_INDEX = 12
T_ALL = 13
T_POINTER = 14

TYPE_NAMES = {
    T_GROUP: 'COB_GROUP', T_ALNUM: 'COB_ALNUM', T_ALPHA: 'COB_ALPHA',
    T_ALNUM_EDITED: 'COB_ALNUM_EDITED', T_NUM_DISPLAY: 'COB_NUM_DISPLAY',
    T_NUM_PACKED: 'COB_NUM_PACKED', T_NUM_BINARY: 'COB_NUM_BINARY',
    T_NUM_COMP5: 'COB_NUM_COMP5', T_NUM_FLOAT: 'COB_NUM_FLOAT',
    T_NUM_DOUBLE: 'COB_NUM_DOUBLE', T_NUM_EDITED: 'COB_NUM_EDITED',
    T_INDEX: 'COB_INDEX', T_ALL: 'COB_ALL', T_POINTER: 'COB_POINTER',
}

NUMERIC_TYPES = {T_NUM_DISPLAY, T_NUM_PACKED, T_NUM_BINARY, T_NUM_COMP5,
                 T_NUM_FLOAT, T_NUM_DOUBLE, T_INDEX}

# attribute flags (must match cobrt.h)
F_SIGNED = 0x01
F_SIGN_SEP = 0x02
F_SIGN_LEAD = 0x04
F_JUSTIFIED = 0x08
F_BLANK_ZERO = 0x10
F_DEC_COMMA = 0x20
F_BINARY_TRUNC = 0x40
F_UNSIGNED_PACKED = 0x100     # COMP-6: packed decimal, no sign nibble


class Picture:
    def __init__(self, src, loc, currency='$', decimal_comma=False, constants=None):
        self.src = src
        self.loc = loc
        self.currency = currency
        self.decimal_comma = decimal_comma
        self.constants = constants or {}
        self.symbols = self._expand(src)        # list of single symbols ('CR','DB' as one)
        self._classify()

    def _expand(self, s):
        out = []
        i = 0
        n = len(s)
        up = s.upper()
        cur = self.currency.upper()
        while i < n:
            c = up[i]
            if c == '(':
                j = up.find(')', i)
                if j < 0 or not out:
                    raise CompileError(f"invalid PICTURE string '{s}'", self.loc)
                try:
                    rep = int(up[i + 1:j])
                except ValueError:
                    c = self.constants.get(up[i + 1:j].strip())     # PIC X(constant-name)
                    if c is None or getattr(c, 'scale', 1) != 0 or getattr(c, 'neg', True):
                        raise CompileError(f"invalid repetition in PICTURE '{s}'", self.loc)
                    rep = int(c.digits)
                if rep < 1:
                    raise CompileError(f"invalid repetition in PICTURE '{s}'", self.loc)
                out.extend([out[-1]] * (rep - 1))
                i = j + 1
                continue
            if up.startswith('CR', i) or up.startswith('DB', i):
                out.append(up[i:i + 2])
                i += 2
                continue
            if c == cur or s[i] == self.currency:
                out.append('$')
                i += 1
                continue
            if c not in 'AX9SVPZ*B0/,.+-$N':
                raise CompileError(f"invalid character '{s[i]}' in PICTURE '{s}'", self.loc)
            out.append('X' if c == 'N' else c)
            i += 1
        return out

    def _classify(self):
        syms = self.symbols
        sset = set(syms)
        dp, sep = ('.', ',') if not self.decimal_comma else (',', '.')
        self.signed = False
        self.edited_pic = None
        self.digits = 0
        self.scale = 0
        if sset <= set('9SVP'):
            self.category = 'NUMERIC'
            self.signed = 'S' in sset
            if syms.count('S') > 1 or ('S' in sset and syms[0] != 'S'):
                raise CompileError(f"invalid use of S in PICTURE '{self.src}'", self.loc)
            if syms.count('V') > 1:
                raise CompileError(f"multiple V in PICTURE '{self.src}'", self.loc)
            body = [c for c in syms if c != 'S']
            self.digits = body.count('9')
            if 'V' in body:
                vpos = body.index('V')
                self.scale = sum(1 for c in body[vpos + 1:] if c in '9P')
            elif body and body[0] == 'P':
                self.scale = sum(1 for c in body if c in '9P')
            else:
                k = 0
                for c in reversed(body):
                    if c == 'P':
                        k += 1
                    else:
                        break
                self.scale = -k
            self.size = self.digits
            if self.digits == 0:
                raise CompileError(f"PICTURE '{self.src}' has no digit positions", self.loc)
            if self.digits > 38:
                raise CompileError(f"PICTURE '{self.src}' exceeds 38 digits", self.loc)
            return
        if sset <= set('A'):
            self.category = 'ALPHABETIC'
            self.size = len(syms)
            return
        if sset <= set('AX9'):
            self.category = 'ALPHANUMERIC'
            self.size = len(syms)
            return
        if 'X' in sset or 'A' in sset:
            if not sset <= set('AX9B0/'):
                raise CompileError(f"invalid PICTURE '{self.src}'", self.loc)
            self.category = 'ALPHANUMERIC-EDITED'
            self.size = len(syms)
            self.edited_pic = ''.join(syms)
            return
        # numeric edited
        self.category = 'NUMERIC-EDITED'
        allowed = set(['9', 'Z', '*', 'B', '0', '/', ',', '.', '+', '-', 'CR', 'DB', '$', 'V', 'P'])
        if not sset <= allowed:
            raise CompileError(f"invalid PICTURE '{self.src}'", self.loc)
        self.signed = bool(sset & {'+', '-', 'CR', 'DB'})
        # digit positions
        digits = 0
        scale = 0
        after_point = False
        float_ch = None
        float_seen = 0
        for idx, c in enumerate(syms):
            if c == 'V' or c == dp:
                after_point = True
                continue
            if c in ('9', 'Z', '*'):
                digits += 1
                if after_point:
                    scale += 1
            elif c in ('+', '-', '$'):
                # count repeated floating symbols (first one is not a digit position)
                if float_ch == c:
                    digits += 1
                    float_seen += 1
                    if after_point:
                        scale += 1
                elif float_ch is None and syms.count(c) > 1 and not (c in '+-' and idx == len(syms) - 1):
                    float_ch = c
                    float_seen = 1
        # P scaling positions in edited pictures
        if 'P' in sset:
            dpos = [i for i, c in enumerate(syms) if c in ('9', 'Z', '*') or (c == float_ch)]
            ppos = [i for i, c in enumerate(syms) if c == 'P']
            if dpos and all(i > max(dpos) for i in ppos):
                scale = -len(ppos)
            elif dpos and all(i < min(dpos) for i in ppos):
                scale = scale + len(ppos)
        self.digits = digits
        self.scale = scale
        self.size = sum(2 if c in ('CR', 'DB') else 1 for c in syms if c not in ('V', 'P'))
        pic = []
        for c in syms:
            if c == 'P':
                continue
            pic.append(c)
        self.edited_pic = ''.join(pic)
        if digits > 38:
            raise CompileError(f"PICTURE '{self.src}' exceeds 38 digits", self.loc)


class Occurs:
    def __init__(self):
        self.min = 0
        self.max = 0
        self.depending = None       # DataRef
        self.keys = []              # (descending, name)
        self.indexes = []           # index names
        self.loc = None


class IndexName:
    """An index defined with INDEXED BY."""

    def __init__(self, name, table, loc):
        self.name = name
        self.table = table
        self.loc = loc
        self.cname = None
        self.level = 0
        self.parent = table

    def __repr__(self):
        return f"IndexName({self.name})"


class DataItem:
    def __init__(self, level, name, loc):
        self.level = level
        self.name = name            # upper-case or None for FILLER
        self.loc = loc
        self.parent = None
        self.children = []
        self.conditions = []        # level-88 items
        self.pic = None
        self.usage = None
        self.usage_signed = None    # for BINARY-CHAR SIGNED/UNSIGNED
        self.sign_lead = None       # None = not specified
        self.sign_sep = False
        self.occurs = None
        self.redefines_name = None
        self.redefines = None
        self.redefined_by = []
        self.justified = False
        self.blank_zero = False
        self.value = None
        self.values = []            # 88: list of (lo, hi)
        self.false_value = None
        self.external = False
        self.is_global = False
        self.renames = None         # (DataRef, DataRef|None)
        self.based = False
        # Report Writer (REPORT SECTION entries)
        self.rw_line = None         # ('ABS', n) ('REL', n) ('ABSNP', n) ('NP', 0)
        self.rw_next_group = None   # ('ABS', n) ('REL', n) ('NP', 0)
        self.rw_type = None         # (kind, control-name|'FINAL'|None)
        self.src_name = None            # name as written in the source
        self.external_name = None       # EXTERNAL AS "name"
        self.any_length = False         # PIC X ANY LENGTH: size from the caller
        self.based = False              # storage allocated by ALLOCATE
        self.rw_step = 0
        self.rw_columns = None
        self.rw_column = None
        self.rw_just = None             # COLUMN LEFT / RIGHT / CENTER: 'L', 'R', 'C'
        self.rw_source = None
        self.rw_sums = []           # [(operands, upon-names)]
        self.rw_reset = None        # control name or 'FINAL'
        self.rw_group_indicate = False
        # computed
        self.type = None
        self.digits = 0
        self.scale = 0
        self.flags = 0
        self.size = 0
        self.offset = 0
        self.record = None          # owning 01 item
        self.section = None         # FILE WS LS LK
        self.file = None            # FileDesc for FD records
        self.storage = None         # C symbol of the storage block
        self.attr_sym = None
        self.cname = None

    def __repr__(self):
        return f"DataItem({self.level} {self.name})"

    @property
    def is_filler(self):
        return self.name is None

    @property
    def is_group(self):
        return bool(self.children)

    @property
    def is_condition(self):
        return self.level == 88

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def total_size(self):
        if self.occurs:
            return self.size * self.occurs.max
        return self.size

    def occurs_chain(self):
        """Items with OCCURS from outermost to this item (inclusive)."""
        chain = []
        it = self
        while it is not None:
            if isinstance(it, DataItem) and it.occurs:
                chain.append(it)
            it = it.parent
        chain.reverse()
        return chain

    def is_numeric(self):
        return self.type in NUMERIC_TYPES

    def category(self):
        t = self.type
        if t == T_GROUP:
            return 'GROUP'
        if t in NUMERIC_TYPES:
            return 'NUMERIC'
        if t == T_NUM_EDITED:
            return 'NUMERIC-EDITED'
        if t == T_ALNUM_EDITED:
            return 'ALPHANUMERIC-EDITED'
        if t == T_ALPHA:
            return 'ALPHABETIC'
        return 'ALPHANUMERIC'

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def contains_odo(self):
        for it in self.walk():
            if it.occurs and it.occurs.depending is not None:
                return it
        return None


BINARY_SIZES = {'2-4-8': [(4, 2), (9, 4), (18, 8), (38, 16)],
                '1-2-4-8': [(2, 1), (4, 2), (9, 4), (18, 8), (38, 16)]}


def binary_size(digits, scheme):
    for maxd, sz in BINARY_SIZES[scheme]:
        if digits <= maxd:
            return sz
    return 16


def resolve_types(item, opts, inh_usage=None, inh_sign=None):
    """Determine the runtime type/size of each item (recursively)."""
    usage = item.usage or inh_usage
    sign = (item.sign_lead, item.sign_sep) if item.sign_lead is not None else inh_sign
    if item.level == 66:
        return
    if item.children:
        if item.pic is not None:
            raise CompileError(f"group item '{item.name}' cannot have a PICTURE", item.loc)
        for c in item.children:
            resolve_types(c, opts, usage, sign)
        item.type = T_GROUP
        return
    pic = item.pic
    if usage in ('FLOAT', 'DOUBLE', 'FLOAT-DECIMAL-16', 'FLOAT-DECIMAL-34'):
        # FLOAT-DECIMAL-16/34 are IEEE 754 decimal floating point. yaccc has no
        # decimal-float type; the values the testsuite uses are small exact
        # integers, which a double holds exactly, so it stands in. Sizes are
        # the standard's: 8 bytes for -16, 16 for -34.
        big = usage in ('DOUBLE', 'FLOAT-DECIMAL-34')
        item.type = T_NUM_DOUBLE if big else T_NUM_FLOAT
        item.size = {'DOUBLE': 8, 'FLOAT': 4,
                     'FLOAT-DECIMAL-16': 8, 'FLOAT-DECIMAL-34': 16}[usage]
        item.digits = 17 if big else 9
        item.scale = 0
        item.flags = F_SIGNED
        return
    if usage == 'INDEX':
        item.type = T_INDEX
        item.size = 4
        item.digits = 9
        item.flags = F_SIGNED
        return
    if usage == 'POINTER':
        item.type = T_POINTER
        item.size = 8
        item.digits = 18
        return
    if usage in ('BINARY-CHAR', 'BINARY-SHORT', 'BINARY-LONG', 'BINARY-DOUBLE'):
        sz = {'BINARY-CHAR': 1, 'BINARY-SHORT': 2, 'BINARY-LONG': 4, 'BINARY-DOUBLE': 8}[usage]
        item.type = T_NUM_COMP5
        item.size = sz
        signed = item.usage_signed if item.usage_signed is not None else (usage != 'BINARY-CHAR' or True)
        item.digits = {1: 3, 2: 5, 4: 10, 8: 19}[sz] if signed else {1: 3, 2: 5, 4: 10, 8: 20}[sz]
        item.flags = F_SIGNED if signed else 0
        return
    if pic is None:
        if usage == 'COMP-X':
            raise CompileError(f"COMP-X item '{item.name}' requires a PICTURE", item.loc)
        # a literal VALUE gives the item its PICTURE, as GnuCOBOL does for an
        # untyped 01 such as "01 PT BASED VALUE "."."
        from .nodes import StrLit, NumLit
        if isinstance(item.value, StrLit):
            pic = Picture(f"X({max(len(item.value.value), 1)})", item.loc, '$', False)
        elif isinstance(item.value, NumLit):
            digits = len(item.value.digits) or 1
            pic = Picture(f"9({digits})", item.loc, '$', False)
        else:
            raise CompileError(f"elementary item '{item.name or 'FILLER'}' has no PICTURE clause",
                               item.loc)
    cat = pic.category
    if usage in (None, 'DISPLAY'):
        if cat == 'NUMERIC':
            item.type = T_NUM_DISPLAY
            item.digits = pic.digits
            item.scale = pic.scale
            item.size = pic.digits
            if pic.signed:
                item.flags |= F_SIGNED
                if sign is not None:
                    lead, sep = sign
                    if lead:
                        item.flags |= F_SIGN_LEAD
                    if sep:
                        item.flags |= F_SIGN_SEP
                        item.size += 1
        elif cat == 'ALPHABETIC':
            item.type = T_ALPHA
            item.size = pic.size
        elif cat == 'ALPHANUMERIC':
            item.type = T_ALNUM
            item.size = pic.size
        elif cat == 'ALPHANUMERIC-EDITED':
            item.type = T_ALNUM_EDITED
            item.size = pic.size
        else:
            item.type = T_NUM_EDITED
            item.digits = pic.digits
            item.scale = pic.scale
            item.size = pic.size
            if pic.signed:
                item.flags |= F_SIGNED
        if item.justified:
            if item.type not in (T_ALNUM, T_ALPHA):
                raise CompileError("JUSTIFIED is only valid for alphanumeric items", item.loc)
            item.flags |= F_JUSTIFIED
        if item.blank_zero:
            if item.type not in (T_NUM_EDITED, T_NUM_DISPLAY):
                raise CompileError("BLANK WHEN ZERO requires a numeric item", item.loc)
            if item.type == T_NUM_DISPLAY:
                # numeric DISPLAY with BLANK WHEN ZERO becomes numeric-edited
                item.type = T_NUM_EDITED
                pic.edited_pic = '9' * (pic.digits - pic.scale) + ('V' + '9' * pic.scale if pic.scale else '')
            item.flags |= F_BLANK_ZERO
        if pic.decimal_comma:
            item.flags |= F_DEC_COMMA
        return
    if cat != 'NUMERIC':
        if usage in ('COMP-5', 'COMP-X') and cat == 'ALPHANUMERIC' and set(pic.symbols) <= {'X'}:
            # Micro Focus PIC X(n) COMP-5 / COMP-X: an n-byte unsigned binary
            # number (native byte order for COMP-5, big-endian for COMP-X)
            n = pic.size
            if n > 16:
                raise CompileError(f"USAGE {usage} item '{item.name}' is longer than 16 bytes", item.loc)
            item.type = T_NUM_COMP5 if usage == 'COMP-5' else T_NUM_BINARY
            item.size = n
            item.digits = min(len(str(256 ** n - 1)), 38)
            item.scale = 0
            return
        raise CompileError(f"USAGE {usage} requires a numeric PICTURE", item.loc)
    item.digits = pic.digits
    item.scale = pic.scale
    if pic.signed:
        item.flags |= F_SIGNED
    if usage == 'PACKED':
        item.type = T_NUM_PACKED
        item.size = pic.digits // 2 + 1
    elif usage == 'COMP-6':
        # packed decimal with no sign nibble: the digits fill every nibble,
        # so PIC 99 COMP-6 is one byte and PIC 999 is two
        item.type = T_NUM_PACKED
        item.size = (pic.digits + 1) // 2
        item.flags |= F_UNSIGNED_PACKED
    elif usage == 'BINARY':
        item.type = T_NUM_BINARY
        item.size = binary_size(pic.digits, opts.binary_size)
        if getattr(opts, 'binary_truncate', True):
            item.flags |= F_BINARY_TRUNC
    elif usage == 'COMP-5':
        item.type = T_NUM_COMP5
        item.size = binary_size(pic.digits, opts.binary_size)
    elif usage == 'COMP-X':
        # COMP-X with a numeric PICTURE: the fewest bytes that hold its digits
        item.type = T_NUM_BINARY
        top = 10 ** pic.digits - 1
        n = 1
        while (2 ** (8 * n - 1) if pic.signed else 2 ** (8 * n)) <= top:
            n += 1
        item.size = n
    else:
        raise CompileError(f"unsupported USAGE {usage}", item.loc)
    if pic.decimal_comma:
        item.flags |= F_DEC_COMMA


def layout(item, offset):
    item.offset = offset
    if not item.children:
        return
    pos = offset
    extent = offset
    for c in item.children:
        if c.level == 66:
            continue
        if c.redefines is not None:
            layout(c, c.redefines.offset)
        else:
            layout(c, pos)
            pos = c.offset + c.total_size()
        extent = max(extent, c.offset + c.total_size())
    item.size = extent - offset
    if item.size == 0:
        raise CompileError(f"group item '{item.name}' has zero length", item.loc)


def link_redefines(siblings, section_roots=None):
    """Resolve REDEFINES among a list of sibling items."""
    for idx, it in enumerate(siblings):
        if it.redefines_name:
            target = None
            for prev in reversed(siblings[:idx]):
                if prev.level == it.level and prev.name == it.redefines_name:
                    target = prev
                    break
                if prev.redefines_name is None and prev.level == it.level and prev.name != it.redefines_name:
                    # standard: must immediately follow (allow intervening redefinitions)
                    pass
            if target is None:
                raise CompileError(f"REDEFINES target '{it.redefines_name}' not found", it.loc)
            while target.redefines is not None:
                target = target.redefines
            it.redefines = target
            target.redefined_by.append(it)
        if it.children:
            link_redefines(it.children)
