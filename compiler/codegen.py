"""Semantic analysis and C code generation."""
import datetime

from .data import (DataItem, IndexName, Picture, layout, link_redefines, resolve_types,
                   T_GROUP, T_ALNUM, T_ALPHA, T_ALNUM_EDITED, T_NUM_DISPLAY, T_NUM_PACKED,
                   T_NUM_BINARY, T_NUM_COMP5, T_NUM_FLOAT, T_NUM_DOUBLE, T_NUM_EDITED,
                   T_INDEX, T_ALL, T_POINTER, TYPE_NAMES, NUMERIC_TYPES,
                   F_SIGNED, F_SIGN_SEP, F_SIGN_LEAD, F_JUSTIFIED, F_BLANK_ZERO, F_DEC_COMMA)
from .errors import CompileError, DIAG
from .nodes import *
from .words import FIG_BYTES, FUNCTIONS

CMP_OP = {'EQ': '==', 'NE': '!=', 'LT': '<', 'LE': '<=', 'GT': '>', 'GE': '>='}
FIG_FIELD = {'SPACE': '&cob_fig_space', 'ZERO': '&cob_fig_zero', 'HIGH-VALUE': '&cob_fig_high',
             'LOW-VALUE': '&cob_fig_low', 'QUOTE': '&cob_fig_quote', 'NULL': '&cob_fig_null'}
ORG = {'SEQUENTIAL': 'COB_ORG_SEQUENTIAL', 'LINE SEQUENTIAL': 'COB_ORG_LINE_SEQ',
       'RELATIVE': 'COB_ORG_RELATIVE', 'INDEXED': 'COB_ORG_INDEXED'}
ACC = {'SEQUENTIAL': 'COB_ACC_SEQUENTIAL', 'RANDOM': 'COB_ACC_RANDOM', 'DYNAMIC': 'COB_ACC_DYNAMIC'}
OPEN_MODE = {'INPUT': 'COB_OPEN_INPUT', 'OUTPUT': 'COB_OPEN_OUTPUT', 'I-O': 'COB_OPEN_IO',
             'EXTEND': 'COB_OPEN_EXTEND'}
START_OP = {'EQ': 0, 'GT': 1, 'GE': 2, 'LT': 3, 'LE': 4, 'NE': 0}
MATH_FN = {'EXP': 0, 'EXP10': 1, 'LOG': 2, 'LOG10': 3, 'SIN': 4, 'COS': 5, 'TAN': 6,
           'ASIN': 7, 'ACOS': 8, 'ATAN': 9}
AGG_FN = {'SUM': 0, 'MEAN': 1, 'MEDIAN': 2, 'MIDRANGE': 3, 'RANGE': 4, 'VARIANCE': 5,
          'STANDARD-DEVIATION': 6, 'MAX': 7, 'MIN': 8}


class CVar(Expr):
    """Raw C integer expression (loop variable)."""

    def __init__(self, text):
        self.text = text


class CDec(Expr):
    """Raw C cob_dec expression (temporary)."""

    def __init__(self, text):
        self.text = text


class CField(Expr):
    """Raw C cob_field* expression."""

    def __init__(self, text, numeric=False):
        self.text = text
        self.numeric = numeric


def c_string(b):
    if isinstance(b, str):
        b = b.encode('latin-1')
    out = ['"']
    for ch in b:
        c = chr(ch)
        if c == '"':
            out.append('\\"')
        elif c == '\\':
            out.append('\\\\')
        elif c == '?':
            out.append('\\?')
        elif 32 <= ch < 127:
            out.append(c)
        else:
            out.append('\\%03o' % ch)
    out.append('"')
    return ''.join(out)


class Options:
    def __init__(self):
        self.binary_size = '2-4-8'
        self.check = True
        self.source_name = ''


class FileInfo:
    def __init__(self, fc, fd):
        self.fc = fc
        self.fd = fd
        self.sym = None
        self.buf = None
        self.size = 0
        self.is_sort = fd is not None and fd.kind == 'SD'
        self.keys = []          # (item, dups)
        self.declarative = None
        self.external = False


class Emitter:
    def __init__(self):
        self.lines = []
        self.ind = 1

    def __call__(self, s):
        self.lines.append('\t' * self.ind + s)

    def label(self, name):
        self.lines.append(f"{name}:;")

    def open(self, s):
        self(s + ' {')
        self.ind += 1

    def close(self, s='}'):
        self.ind -= 1
        self(s)


class ProgCtx:
    def __init__(self, prog):
        self.prog = prog
        self.names = {}
        self.files = {}
        self.sections = []
        self.paras_by_name = {}
        self.secs_by_name = {}
        self.cname = None
        self.init_flag = None
        self.rebinds = []           # static fields bound into LINKAGE/LOCAL-STORAGE
        self.local_blocks = []      # (sym, size) LOCAL-STORAGE
        self.link_blocks = []       # (sym, size, item)
        self.class_tables = {}


class CodeGen:
    def __init__(self, programs, opts):
        self.programs = programs
        self.opts = opts
        self.glob = []
        self.funcs = []
        self.protos = []
        self.attr_cache = {}
        self.lit_cache = {}
        self.static_fields = {}
        self.n = 0
        self.prog_syms = {}
        self.externals = {}
        self.ext_files = {}         # name -> [sym, buf, size]
        self.ext_inited = set()
        self.init_flags = {}
        self.all_progs = []

    def sym(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def err(self, msg, loc=None):
        raise CompileError(msg, loc or getattr(self, 'cur_loc', None))

    # ================================================================ entry
    def generate(self):
        # flatten nested programs
        def walk(p):
            self.all_progs.append(p)
            for q in p.nested:
                walk(q)
        for p in self.programs:
            walk(p)
        for p in self.all_progs:
            if p.name.upper() in self.prog_syms:
                raise CompileError(f"duplicate program name '{p.name}'", p.loc)
            self.prog_syms[p.name.upper()] = self.sym('prog_')
        for p in self.all_progs:
            self.protos.append(f"static int {self.prog_syms[p.name.upper()]}(int cob_argc, unsigned char **cob_argv);")
            flag = self.sym('cob_inited_')
            self.init_flags[p.name.upper()] = flag
            self.protos.append(f"static int {flag};")
        for p in self.all_progs:
            self.gen_program(p)
        for name, (fsym, buf, size) in self.ext_files.items():
            self.protos.append(f"static unsigned char {buf}[{size}] __attribute__((aligned(16)));")
            self.protos.append(f"static cob_file {fsym};")
            self.protos.append(f"static int {fsym}_inited;")
        # CANCEL support: reset to initial state, close open files, cancel contained programs
        for p in self.all_progs:
            cs = self.sym('cancel_')
            p._cancel_sym = cs
        for p in self.all_progs:
            self.protos.append(f"static void {p._cancel_sym}(void);")
            body = [f"static void {p._cancel_sym}(void)", "{"]
            flag = self.init_flags[p.name.upper()]
            body.append(f"\tif (!{flag}) return;")
            for fs in p._cancel_files:
                body.append(f"\tif ({fs}.open_mode) cob_close_quiet(&{fs});")
            for q in p.nested:
                body.append(f"\t{q._cancel_sym}();")
            body.append(f"\t{flag} = 0;")
            body.append("}")
            self.funcs.extend(body)
        main = self.programs[0]
        now = datetime.datetime.now()
        wc = now.strftime('%m/%d/%Y%H.%M.%S') if False else now.strftime('%Y%m%d%H%M%S00+0000')
        out = []
        out.append('/* Generated by cobolc - do not edit */')
        out.append('#include "cobrt.h"')
        out.append('')
        out.extend(self.protos)
        out.append('')
        out.extend(self.glob)
        out.append('')
        out.extend(self.funcs)
        out.append('')
        out.append('static void cob_register_all(void)')
        out.append('{')
        for p in self.all_progs:
            out.append(f'\tcob_register_program({c_string(p.name)}, {self.prog_syms[p.name.upper()]}, {p._cancel_sym});')
        out.append('}')
        out.append('')
        out.append('int main(int argc, char **argv)')
        out.append('{')
        out.append('\tcob_init(argc, argv);')
        out.append(f'\tcob_when_compiled = {c_string(wc)};')
        out.append('\tcob_register_all();')
        out.append(f'\tint rc = {self.prog_syms[main.name.upper()]}(-1, NULL);')
        out.append('\tcob_stop_run(rc);')
        out.append('\treturn rc;')
        out.append('}')
        return '\n'.join(out) + '\n'

    # ================================================================ attributes / literals
    def attr(self, typ, digits=0, scale=0, flags=0, pic=None, currency=0):
        key = (typ, digits, scale, flags, pic, currency)
        s = self.attr_cache.get(key)
        if s:
            return s
        s = self.sym('a_')
        pc = c_string(pic) if pic else 'NULL'
        self.glob.append(f"static const cob_attr {s} = {{{TYPE_NAMES[typ]}, {digits}, {scale}, {flags}, {pc}, {currency}}};")
        self.attr_cache[key] = s
        return s

    def item_attr(self, it):
        if it.attr_sym:
            return it.attr_sym
        pic = None
        cur = 0
        if it.type in (T_NUM_EDITED, T_ALNUM_EDITED) and it.pic is not None:
            pic = it.pic.edited_pic
            if it.pic.currency != '$':
                cur = ord(it.pic.currency)
        it.attr_sym = self.attr(it.type, min(it.digits, 255), it.scale, it.flags, pic, cur)
        return it.attr_sym

    def lit_str(self, b):
        if len(b) == 0:
            b = b' '
        key = ('S', b)
        if key in self.lit_cache:
            return self.lit_cache[key]
        s = self.sym('lit_')
        self.glob.append(f"static cob_field {s} = {{{len(b)}, (unsigned char *){c_string(b)}, &cob_attr_alnum}};")
        self.lit_cache[key] = '&' + s
        return '&' + s

    def lit_num(self, n):
        key = ('N', n.text)
        if key in self.lit_cache:
            return self.lit_cache[key]
        digits = n.digits
        signed = n.text[:1] in '+-'
        flags = F_SIGNED | F_SIGN_SEP | F_SIGN_LEAD if signed else 0
        data = (('-' if n.neg else '+') if signed else '') + digits
        a = self.attr(T_NUM_DISPLAY, len(digits), n.scale, flags)
        s = self.sym('lit_')
        self.glob.append(f"static cob_field {s} = {{{len(data)}, (unsigned char *){c_string(data)}, &{a}}};")
        self.lit_cache[key] = '&' + s
        return '&' + s

    def lit_all(self, e):
        key = ('A', e.value, e.is_zero)
        if key in self.lit_cache:
            return self.lit_cache[key]
        a = self.attr(T_ALL, 0, 0, 0x80 if e.is_zero else 0)
        s = self.sym('lit_')
        v = e.value or b' '
        self.glob.append(f"static cob_field {s} = {{{len(v)}, (unsigned char *){c_string(v)}, &{a}}};")
        self.lit_cache[key] = '&' + s
        return '&' + s

    # ================================================================ data analysis
    def gen_program(self, prog):
        ctx = ProgCtx(prog)
        self.ctx = ctx
        self.prog = prog
        ctx.cname = self.prog_syms[prog.name.upper()]
        ctx.coll = None
        if prog.collating:
            self.build_collating(prog)
        ctx.init_flag = self.init_flags[prog.name.upper()]
        self.cur_loc = prog.loc
        self.glob.append(f"/* ---------------- program {prog.name} */")
        self.analyze_data(prog)
        prog._cancel_files = [fi.sym for fi in ctx.files.values()
                              if not fi.external and any(fi.fd is d for d in prog.file_descs)]
        self.collect_procedures(prog)
        self.emit_program(prog)

    def build_collating(self, prog):
        ctx = self.ctx
        res = self.collating_table(prog, prog.collating, prog.loc)
        if res is None:
            return
        sym, lo, hi = res
        ctx.coll = sym
        ctx.coll_fig = {'LOW-VALUE': self.lit_all(AllLit(bytes([lo]))),
                        'HIGH-VALUE': self.lit_all(AllLit(bytes([hi])))}

    def collating_table(self, prog, name, loc):
        """Weight table for an alphabet-name; None for the native sequence."""
        p = prog
        spec = None
        while p is not None and spec is None:
            spec = p.alphabets.get(name)
            p = p.parent
        if spec is None:
            raise CompileError(f"alphabet '{name}' is not defined", loc)
        if isinstance(spec, str):
            if spec in ('NATIVE', 'ASCII', 'STANDARD-1', 'STANDARD-2'):
                return None
            raise CompileError(f"alphabet {spec} is not supported", loc)
        cache = self.__dict__.setdefault('_coll_cache', {})
        if id(spec) in cache:
            return cache[id(spec)]
        weight = {}
        w = 0
        order = []
        for item in spec:
            if item[0] == 'RANGE':
                a, b = item[1][0], item[2][0]
                step = 1 if b >= a else -1
                for c in range(a, b + step, step):
                    if c not in weight:
                        weight[c] = w
                        order.append(c)
                        w += 1
            else:
                used = False
                for lit in item[1]:
                    chars = list(lit)
                    if len(item[1]) == 1 and len(chars) > 1:
                        for c in chars:
                            if c not in weight:
                                weight[c] = w
                                order.append(c)
                                w += 1
                        continue
                    for c in chars:
                        if c not in weight:
                            weight[c] = w
                            order.append(c)
                            used = True
                if used:
                    w += 1
        for c in range(256):
            if c not in weight:
                weight[c] = w
                order.append(c)
                w += 1
        sym = self.sym('coll_')
        self.glob.append(f"static const unsigned short {sym}[256] = {{{','.join(str(weight[c]) for c in range(256))}}};")
        lo = min(range(256), key=lambda c: (weight[c], c))
        hi = max(range(256), key=lambda c: (weight[c], c))
        cache[id(spec)] = (sym, lo, hi)
        return cache[id(spec)]

    def analyze_data(self, prog):
        ctx = self.ctx
        # file section
        fds = {fd.name: fd for fd in prog.file_descs}
        for fc in prog.file_controls:
            if fc.name not in fds:
                raise CompileError(f"no FD/SD entry for file '{fc.name}'", fc.loc)
        fcs = {fc.name: fc for fc in prog.file_controls}
        same_group = {}
        for gi, names in enumerate(prog.same_record):
            for nm in names:
                same_group[nm] = gi
        same_bufs = {}
        for fd in prog.file_descs:
            fc = fcs.get(fd.name)
            if fc is None:
                if fd.kind == 'SD':
                    fc = FileControl(name=fd.name, assign=None, loc=fd.loc)
                else:
                    raise CompileError(f"file '{fd.name}' has no SELECT entry", fd.loc)
            fi = FileInfo(fc, fd)
            if fd.external:
                base = ''.join(ch if ch.isalnum() else '_' for ch in fd.name)
                fi.sym = 'cobextf_' + base
                fi.buf = 'cobextr_' + base
                fi.external = True
            else:
                fi.sym = self.sym('file_')
                if fd.name in same_group:
                    ent = same_bufs.setdefault(same_group[fd.name], [self.sym('b_'), 0])
                    fi.buf = ent[0]
                    fi.same_area = ent
                else:
                    fi.buf = self.sym('b_')
            ctx.files[fd.name] = fi
            size = 0
            link_redefines(fd.records)
            for r in fd.records:
                resolve_types(r, self.opts)
                layout(r, 0)
                size = max(size, r.size)
                for it in r.walk():
                    it.record = r
                    it.storage = fi.buf
                    it.section = 'FILE'
                    it.file = fi
            if fd.rec_max:
                size = max(size, fd.rec_max)
            if size == 0:
                size = 1
            fi.size = size
            if fi.external:
                ent = self.ext_files.setdefault(fd.name, [fi.sym, fi.buf, size])
                ent[2] = max(ent[2], size)
            elif getattr(fi, 'same_area', None) is not None:
                fi.same_area[1] = max(fi.same_area[1], size)
                self.glob.append(f"static cob_file {fi.sym};")
            else:
                self.glob.append(f"static unsigned char {fi.buf}[{size}] __attribute__((aligned(16)));")
                self.glob.append(f"static cob_file {fi.sym};")
            for r in fd.records:
                self.register_tree(r)
        for buf, size in same_bufs.values():
            self.glob.append(f"static unsigned char {buf}[{max(size, 1)}] __attribute__((aligned(16))); /* SAME RECORD AREA */")
        for sec, roots in (('WS', prog.working), ('LS', prog.local), ('LK', prog.linkage)):
            link_redefines(roots)
            for r in roots:
                if r.renames:
                    continue
                resolve_types(r, self.opts)
                layout(r, 0)
            for r in roots:
                if r.redefines is not None:
                    continue
                size = max([r.size] + [x.size for x in r.redefined_by])
                if sec == 'WS':
                    if r.external:
                        key = r.name
                        if key in self.externals:
                            sym = self.externals[key]
                        else:
                            sym = 'cobext_' + ''.join(ch if ch.isalnum() else '_' for ch in r.name)
                            self.externals[key] = sym
                            self.glob.append(f"static unsigned char {sym}[{size}] __attribute__((aligned(16)));")
                    else:
                        sym = self.sym('b_')
                        self.glob.append(f"static unsigned char {sym}[{size}] __attribute__((aligned(16))); /* {r.name or 'FILLER'} */")
                elif sec == 'LS':
                    sym = self.sym('ls_')
                    ctx.local_blocks.append((sym, size, r))
                else:
                    sym = self.sym('lk_')
                    ctx.link_blocks.append((sym, size, r))
                for x in [r] + r.redefined_by:
                    for it in x.walk():
                        it.record = x
                        it.storage = sym
                        it.section = sec
            for r in roots:
                self.register_tree(r)
            # level 66
            for r in roots:
                for c in list(r.children):
                    if c.level == 66:
                        self.resolve_renames(c, r)
        # LINAGE-COUNTER, one per file with a LINAGE clause
        for fi in list(ctx.files.values()):
            if fi.fd.linage is None:
                continue
            lc = self.sym('lc_')
            it = DataItem(1, 'LINAGE-COUNTER', fi.fd.loc)
            it.type = T_NUM_BINARY
            it.digits = 9
            it.flags = 0
            it.size = 4
            it.file = fi
            self.glob.append(f"static unsigned char {lc}_d[4];")
            self.glob.append(f"static cob_field {lc} = {{4, {lc}_d, &{self.item_attr(it)}}};")
            it.special = '&' + lc
            fi.linage_ctr = '&' + lc
            ctx.names.setdefault('LINAGE-COUNTER', []).append(it)
        # special registers
        for nm, expr, typ, digits, flags, size in (
                ('RETURN-CODE', '&cob_return_code', T_NUM_BINARY, 9, F_SIGNED, 4),
                ('TALLY', '&cob_tally', T_NUM_BINARY, 5, 0, 4),
                ('SORT-RETURN', '&cob_sort_return_reg', T_NUM_BINARY, 4, F_SIGNED, 4)):
            if nm not in ctx.names:
                it = DataItem(1, nm, prog.loc)
                it.special = expr
                it.type = typ
                it.digits = digits
                it.flags = flags
                it.size = size
                ctx.names[nm] = [it]
        # GLOBAL items visible to nested programs
        gc = {}
        for roots in (prog.working, prog.linkage):
            for r in roots:
                if r.is_global:
                    for it in r.walk():
                        if it.name:
                            gc.setdefault(it.name, []).append(it)
                        for c in it.conditions:
                            gc.setdefault(c.name, []).append(c)
        for fd in prog.file_descs:
            if fd.is_global:
                for r in fd.records:
                    for it in r.walk():
                        if it.name:
                            gc.setdefault(it.name, []).append(it)
                        for c in it.conditions:
                            gc.setdefault(c.name, []).append(c)
        prog._gcache = gc
        prog._gfiles = {fd.name: ctx.files[fd.name] for fd in prog.file_descs if fd.is_global}
        # classes
        for cname, ranges in prog.classes.items():
            tbl = [0] * 256
            for lo, hi in ranges:
                if len(lo) == 1 and len(hi) == 1:
                    a, b = sorted((lo[0], hi[0]))
                    for c in range(a, b + 1):
                        tbl[c] = 1
                else:
                    for c in lo:
                        tbl[c] = 1
            s = self.sym('cls_')
            self.glob.append(f"static const unsigned char {s}[256] = {{{','.join(map(str, tbl))}}};")
            ctx.class_tables[cname] = s
        # file keys
        for fi in ctx.files.values():
            fc = fi.fc
            if fc.record_key is not None:
                k = self.resolve(fc.record_key)
                fi.keys.append((k, False))
            for kref, dups in fc.alt_keys:
                fi.keys.append((self.resolve(kref), dups))
            for k, _ in fi.keys:
                if getattr(k, 'file', None) is not fi:
                    raise CompileError(f"key '{k.name}' is not part of the record of file '{fc.name}'", fc.loc)

    def resolve_renames(self, item, record):
        a, b = item.renames
        ia = self.resolve(a)
        ib = self.resolve(b) if b else ia
        item.type = T_GROUP if (b or ia.children) else ia.type
        if not b and not ia.children:
            item.digits, item.scale, item.flags, item.pic = ia.digits, ia.scale, ia.flags, ia.pic
        item.offset = ia.offset
        item.size = ib.offset + ib.size - ia.offset
        item.storage = ia.storage
        item.record = ia.record
        item.section = ia.section
        item.children = []

    def register_tree(self, root):
        ctx = self.ctx
        for it in root.walk():
            if it.name:
                ctx.names.setdefault(it.name, []).append(it)
            for c in it.conditions:
                c.record = it.record
                if c.name:
                    ctx.names.setdefault(c.name, []).append(c)
            if it.occurs:
                for nm, loc in it.occurs.indexes:
                    ix = IndexName(nm, it, loc)
                    ix.cname = self.sym('ix_')
                    self.glob.append(f"static int {ix.cname} = 1; /* index {nm} */")
                    ctx.names.setdefault(nm, []).append(ix)

    # ================================================================ name resolution
    def resolve(self, ref, allow_cond=True):
        if isinstance(ref, (CVar, CDec, CField)):
            return None
        if ref.item is not None:
            return ref.item
        ctx = self.ctx
        cands = list(ctx.names.get(ref.name, []))
        p = self.prog.parent
        if not cands:
            pc = p
            while pc is not None and not cands:
                for it in self.global_items(pc).get(ref.name, []):
                    cands.append(it)
                pc = pc.parent
        if ref.quals:
            cands = [c for c in cands if self.qual_ok(c, ref.quals)]
        if not cands:
            if ref.quals:
                raise CompileError(f"'{ref.name}' in '{' OF '.join(ref.quals)}' is not defined", ref.loc)
            raise CompileError(f"'{ref.name}' is not defined", ref.loc)
        if len(cands) > 1:
            raise CompileError(f"'{ref.name}' is ambiguous; it needs qualification", ref.loc)
        it = cands[0]
        if not allow_cond and isinstance(it, DataItem) and it.level == 88:
            raise CompileError(f"condition-name '{ref.name}' used as data item", ref.loc)
        ref.item = it
        return it

    def global_items(self, prog):
        return getattr(prog, '_gcache', {})

    def qual_ok(self, item, quals):
        chain = []
        p = item.parent if not isinstance(item, IndexName) else item.table
        if isinstance(item, IndexName):
            chain.append(item.table.name)
            p = item.table.parent
        while p is not None:
            chain.append(p.name)
            p = p.parent
        fi = getattr(item, 'file', None)
        if fi is not None:
            chain.append(fi.fd.name)
        i = 0
        for q in quals:
            while i < len(chain) and chain[i] != q:
                i += 1
            if i == len(chain):
                return False
            i += 1
        return True

    def lookup_file(self, name, prog=None):
        prog = prog or self.prog
        fi = self.ctx.files.get(name) if prog is self.prog else getattr(prog, '_files', {}).get(name)
        pc = prog.parent
        while fi is None and pc is not None:
            fi = getattr(pc, '_gfiles', {}).get(name)
            pc = pc.parent
        return fi

    def file_info(self, name, loc):
        fi = self.lookup_file(name)
        if fi is None:
            raise CompileError(f"'{name}' is not a file", loc)
        return fi

    # ================================================================ procedures
    def collect_procedures(self, prog):
        ctx = self.ctx
        allsecs = prog.declaratives + prog.sections
        for sec in allsecs:
            sec.id = self.next_id()
            sec.label = f"L{sec.id}"
            if sec.name:
                if sec.name in ctx.secs_by_name:
                    raise CompileError(f"duplicate section name '{sec.name}'", sec.loc)
                ctx.secs_by_name[sec.name] = sec
            for para in sec.paragraphs:
                para.id = self.next_id()
                para.label = f"L{para.id}"
                para.section = sec
                if para.name:
                    ctx.paras_by_name.setdefault(para.name, []).append(para)
        prog._files = dict(ctx.files)
        prog._decl_file = {}
        prog._decl_mode = {}
        for sec in prog.declaratives:
            if sec.use_files:
                for fname in sec.use_files:
                    fi = self.lookup_file(fname, prog)
                    if fi is None:
                        raise CompileError(f"USE: '{fname}' is not a file", sec.loc)
                    prog._decl_file[fname] = (sec, fi)
            elif sec.use_mode:
                prog._decl_mode[sec.use_mode] = sec

    def next_id(self):
        self.n += 1
        return self.n

    def resolve_proc(self, pr):
        ctx = self.ctx
        if pr.target is not None:
            return pr.target
        if pr.qual:
            sec = ctx.secs_by_name.get(pr.qual)
            if sec is None:
                raise CompileError(f"section '{pr.qual}' is not defined", pr.loc)
            for para in sec.paragraphs:
                if para.name == pr.name:
                    pr.target = para
                    return para
            raise CompileError(f"paragraph '{pr.name}' not found in section '{pr.qual}'", pr.loc)
        paras = ctx.paras_by_name.get(pr.name, [])
        if len(paras) == 1:
            pr.target = paras[0]
            return paras[0]
        if len(paras) > 1:
            local = [p for p in paras if p.section is self.cur_section]
            if len(local) == 1:
                pr.target = local[0]
                return local[0]
            raise CompileError(f"paragraph '{pr.name}' is ambiguous; qualify it with OF section", pr.loc)
        sec = ctx.secs_by_name.get(pr.name)
        if sec is not None:
            pr.target = sec
            return sec
        raise CompileError(f"procedure '{pr.name}' is not defined", pr.loc)

    # ================================================================ program emission
    def all_stmts(self, prog):
        def walk(x):
            if isinstance(x, Stmt):
                yield x
                for v in vars(x).values():
                    yield from walk(v)
            elif isinstance(x, (list, tuple)):
                for v in x:
                    yield from walk(v)
            elif isinstance(x, (SearchWhen,)):
                yield from walk(x.stmts)
        for sec in prog.declaratives + prog.sections:
            for para in sec.paragraphs:
                for sent in para.sentences:
                    yield from walk(sent.stmts)

    def prepare_alters(self, prog):
        """Paragraphs named in ALTER statements get a variable holding the
        current target of their GO TO (NULL = initial state)."""
        self.alter_paras = {}
        self.alter_vars = []
        self.seg_alters = {}

        def walk(x):
            if isinstance(x, Stmt):
                yield x
                for v in vars(x).values():
                    yield from walk(v)
            elif isinstance(x, (list, tuple)):
                for v in x:
                    yield from walk(v)
            elif isinstance(x, (SearchWhen,)):
                yield from walk(x.stmts)
        for sec in prog.declaratives + prog.sections:
            self.cur_section = sec
            for para in sec.paragraphs:
                for sent in para.sentences:
                    for st in walk(sent.stmts):
                        if not isinstance(st, Alter):
                            continue
                        for p1, _ in st.pairs:
                            tgt = self.resolve_proc(p1)
                            if not isinstance(tgt, Paragraph):
                                raise CompileError(f"ALTER: '{p1.name}' is not a paragraph", st.loc)
                            stmts = [x for sn in tgt.sentences for x in sn.stmts]
                            if len(stmts) != 1 or not isinstance(stmts[0], GoTo) or stmts[0].depending is not None:
                                raise CompileError(f"ALTER: paragraph '{p1.name}' must consist of a single GO TO", st.loc)
                            if id(tgt) not in self.alter_paras:
                                var = self.sym('alt_')
                                self.glob.append(f"static void *{var};")
                                self.alter_paras[id(tgt)] = var
                                self.alter_vars.append(var)
                                self.seg_alters.setdefault(tgt.section.segment, []).append(var)
        self.cur_section = None
        self.seg_tracking = any(seg >= 50 for seg in self.seg_alters)

    def seg_enter(self, sec):
        """Independent segments (49 < segment-number) are in their initial
        state whenever entered from another segment."""
        if not self.seg_tracking:
            return
        em = self.em
        n = sec.segment
        if n >= 50 and n in self.seg_alters:
            resets = ' '.join(f"{v} = NULL;" for v in self.seg_alters[n])
            em(f"if (cob_seg != {n}) {{ {resets} }}")
        em(f"cob_seg = {n};")

    def emit_program(self, prog):
        ctx = self.ctx
        self.prepare_alters(prog)
        self.advancing_files = set()
        for st in self.all_stmts(prog):
            if isinstance(st, Write) and st.adv_when:
                it = self.resolve(st.record)
                fi = getattr(it, 'file', None)
                if fi is not None:
                    self.advancing_files.add(fi.fd.name)
        # init function
        init_name = self.sym('init_')
        em = Emitter()
        self.em = em
        self.fn_locals = []
        self.cur_section = None
        self.cur_para = None
        self.cur_sentence_end = None
        self.inline_stack = []
        for var in self.alter_vars:
            em(f"{var} = NULL;")
        for fi in ctx.files.values():
            if fi.external:
                em(f"if (!{fi.sym}_inited) {{")
                em.ind += 1
                self.emit_file_init(fi)
                em(f"memset({fi.buf}, ' ', {fi.size});")
                em(f"{fi.sym}_inited = 1;")
                em.ind -= 1
                em("}")
            else:
                self.emit_file_init(fi)
        for r in self.ws_roots(prog):
            self.init_tree(r, mode='init')
        for fi in ctx.files.values():
            if fi.external:
                continue
            for r in fi.fd.records[:1]:
                em(f"memset({fi.buf}, ' ', {fi.size});")
        init_body = em.lines
        init_locals = self.fn_locals
        self.funcs.append(f"static void {init_name}(void)")
        self.funcs.append('{')
        for d in sorted(set(init_locals)):
            self.funcs.append('\t' + d)
        self.funcs.extend(init_body)
        self.funcs.append('}')
        self.funcs.append('')
        # program function
        em = Emitter()
        self.em = em
        self.fn_locals = []
        self.loc_str = c_string(str(prog.loc))
        body = em
        gdecls = [sec for sec in prog.declaratives if sec.use_global]
        if gdecls:
            em("if (cob_argc == COB_DECL_ENTRY) goto L_decl_entry;")
        em(f"cob_set_collating({ctx.coll or 'NULL'});")
        if prog.is_initial:
            em(f"{init_name}();")
        else:
            em(f"if (!{ctx.init_flag}) {{ {init_name}(); {ctx.init_flag} = 1; }}")
        for sym, size, r in ctx.local_blocks:
            em(f"{sym} = cob_malloc({size});")
        for sym, size, r in ctx.local_blocks:
            self.init_tree(r, mode='init')
        # linkage binding
        using_items = []
        for i, (mode, ref) in enumerate(prog.using):
            it = self.resolve(ref)
            if it.section != 'LK' or it.level not in (1, 77):
                raise CompileError(f"USING item '{ref.name}' must be a level 01/77 LINKAGE item", ref.loc)
            using_items.append(it.storage)
            em(f"{it.storage} = (cob_argc > {i} && cob_argv[{i}]) ? cob_argv[{i}] : {it.storage}_dummy;")
        for sym, size, r in ctx.link_blocks:
            self.glob.append(f"static unsigned char {sym}_dummy[{size}];")
            if sym not in using_items:
                em(f"{sym} = {sym}_dummy;")
        rebind_at = len(em.lines)
        decls = [s for s in prog.declaratives]
        if decls:
            em("goto L_start;")
            for sec in decls:
                self.gen_section(sec)
            em.label("L_start")
        for sec in prog.sections:
            self.gen_section(sec)
        em("goto L_exit;")
        em.label("L_exit")
        for sym, size, r in ctx.local_blocks:
            em(f"free({sym});")
        if prog.returning is not None:
            f = self.field(prog.returning)
            em(f"return (int)cob_get_int({f});")
        else:
            em("return (int)cob_get_int(&cob_return_code);")
        if gdecls:
            em.label("L_decl_entry")
            em("switch (cob_decl_which) {")
            for sec in gdecls:
                em(f"case {sec.id}:")
                em.ind += 1
                self.perform_section(sec)
                em("break;")
                em.ind -= 1
            em("}")
            em("return 0;")
        em.lines[rebind_at:rebind_at] = ['\t' + l for l in ctx.rebinds]
        out = self.funcs
        out.append(f"/* PROGRAM-ID. {prog.name} */")
        out.append(f"static int {ctx.cname}(int cob_argc, unsigned char **cob_argv)")
        out.append('{')
        out.append('\tstruct cob_frame cob_frames[COB_STACK_SIZE];')
        out.append('\tstruct cob_frame *frame_ptr = cob_frames;')
        for sym, size, r in ctx.local_blocks + ctx.link_blocks:
            if prog.is_recursive:
                out.append(f'\tunsigned char *{sym};')
            else:
                self.protos.append(f'static unsigned char *{sym};')
        for d in sorted(set(self.fn_locals)):
            out.append('\t' + d)
        if self.seg_tracking:
            out.append('\tint cob_seg = -1;')
        out.append('\t(void)cob_argv;')
        out.append('\tframe_ptr->perform_through = 0;')
        out.append('\tframe_ptr->return_address = &&L_exit;   /* never used; keeps clang happy */')
        out.extend(body.lines)
        out.append('}')
        out.append('')

    def ws_roots(self, prog):
        out = []
        for r in prog.working:
            if r.redefines is not None or r.renames:
                continue
            if r.external:
                if r.name in self.ext_inited:
                    continue
                self.ext_inited.add(r.name)
            out.append(r)
        return out

    def local(self, decl):
        self.fn_locals.append(decl)

    def new_label(self, prefix='T'):
        return f"{prefix}{self.next_id()}"

    def locstr(self, loc=None):
        loc = loc or self.cur_loc
        return c_string(str(loc))

    # ================================================================ files
    def static_field(self, ref):
        it = self.resolve(ref, allow_cond=False)
        if getattr(it, 'special', None):
            return it.special.lstrip('&') if False else it.special
        if it.section not in ('WS', 'FILE', 'LK', 'LS') or it.occurs_chain() or ref.subs or ref.refmod:
            raise CompileError(f"'{ref.name}' must be a non-subscripted data item here", ref.loc)
        key = id(it)
        if key in self.static_fields:
            return self.static_fields[key]
        s = self.sym('sf_')
        if it.section in ('LK', 'LS'):
            self.glob.append(f"static cob_field {s} = {{{it.size}, NULL, &{self.item_attr(it)}}};")
            self.ctx.rebinds.append(f"{s}.data = {it.storage} + {it.offset};")
            self.static_fields[key] = '&' + s
            return '&' + s
        self.glob.append(f"static cob_field {s} = {{{it.size}, {it.storage} + {it.offset}, &{self.item_attr(it)}}};")
        self.static_fields[key] = '&' + s
        return '&' + s

    def file_bindings(self, fi):
        f = fi.sym
        fc = fi.fc
        out = []
        if fi.fd.depending is not None:
            out.append(f"{f}.size_field = {self.static_field(fi.fd.depending)};")
        elif fi.external:
            out.append(f"{f}.size_field = NULL;")
        if fc.status is not None:
            out.append(f"{f}.status = {self.static_field(fc.status)};")
        elif fi.external:
            out.append(f"{f}.status = NULL;")
        if fc.relative_key is not None:
            out.append(f"{f}.relative_key = {self.static_field(fc.relative_key)};")
        return out

    def emit_file_init(self, fi):
        em = self.em
        fc = fi.fc
        f = fi.sym
        em(f"memset(&{f}, 0, sizeof {f});")
        em(f"{f}.select_name = {c_string(fc.name)};")
        org = 'SEQUENTIAL' if fi.is_sort else fc.organization
        if org == 'SEQUENTIAL' and (fi.fd.name in self.advancing_files or fc.assign_kind == 'PRINTER'
                                    or fi.fd.linage is not None):
            org = 'LINE SEQUENTIAL'
            fc.organization = org
        em(f"{f}.organization = {ORG[org]};")
        em(f"{f}.access = {ACC[fc.access]};")
        em(f"{f}.optional = {1 if fc.optional else 0};")
        kind = {'': 0, 'KEYBOARD': 1, 'DISPLAY': 2, 'PRINTER': 2}.get(fc.assign_kind, 0)
        em(f"{f}.assign_kind = {kind};")
        a = fc.assign
        if isinstance(a, StrLit):
            em(f"{f}.assign_name = {c_string(a.value)};")
            em(f"{f}.assign_literal = 1;")
        elif isinstance(a, DataRef):
            items = self.ctx.names.get(a.name)
            if items and not a.quals and len(items) >= 1:
                em(f"{f}.assign_field = {self.static_field(a)};")
            else:
                em(f"{f}.assign_name = {c_string(a.name)};")
        em(f"{f}.record = {fi.buf};")
        em(f"{f}.record_max = {fi.size};")
        rmin = fi.fd.rec_min or min([r.size for r in fi.fd.records] or [fi.size])
        em(f"{f}.record_min = {rmin};")
        variable = fi.fd.depending is not None or (fi.fd.rec_min and fi.fd.rec_min != fi.fd.rec_max)
        if org in ('SEQUENTIAL', 'INDEXED') and len(set(r.size for r in fi.fd.records)) > 1 and org != 'INDEXED':
            variable = True
        fi.variable = bool(variable and org != 'LINE SEQUENTIAL')
        em(f"{f}.variable = {1 if fi.variable else 0};")
        for line in self.file_bindings(fi):
            em(line)
        if org == 'INDEXED' and not fi.keys:
            raise CompileError(f"INDEXED file '{fc.name}' requires RECORD KEY", fc.loc)
        if len(fi.keys) > 64:
            raise CompileError(f"file '{fc.name}' has more than 64 keys", fc.loc)
        for k, _ in fi.keys:
            if k.size > 4096:
                raise CompileError(f"key '{k.name}' is longer than 4096 bytes", fc.loc)
        em(f"{f}.nkeys = {len(fi.keys)};")
        for i, (k, dups) in enumerate(fi.keys):
            em(f"{f}.keys[{i}] = (cob_file_key){{{k.offset}, {k.size}, &{self.item_attr(k)}, {1 if dups else 0}}};")
        em(f"{f}.is_sort = {1 if fi.is_sort else 0};")
        if fi.fd.linage is not None:
            em(f"{f}.linage_ctr = {fi.linage_ctr};")
            for i, op in enumerate((fi.fd.linage, fi.fd.footing, fi.fd.top, fi.fd.bottom)):
                if op is None:
                    continue
                if isinstance(op, NumLit):
                    em(f"{f}.lin_const[{i}] = {int(float(op.text))};")
                else:
                    em(f"{f}.lin_src[{i}] = {self.static_field(op)};")

    # ================================================================ references
    def is_numeric(self, e):
        if isinstance(e, NumLit):
            return True
        if isinstance(e, (BinOp, Neg, LengthOf, CDec, CVar)):
            return True
        if isinstance(e, CField):
            return e.numeric
        if isinstance(e, Figurative):
            return e.kind == 'ZERO'
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, IndexName):
                return True
            if e.refmod:
                return False
            return it.type in NUMERIC_TYPES
        if isinstance(e, FuncCall):
            k = FUNCTIONS[e.name][0]
            if e.refmod:
                return False
            if k == 'N':
                return True
            if k == 'M':
                return any(self.is_numeric(a) for a in e.args)
            return False
        return False

    def is_zero_fig(self, e):
        return isinstance(e, Figurative) and e.kind == 'ZERO'

    def field(self, e):
        """C expression of type cob_field* for operand e."""
        if isinstance(e, DataRef):
            return self.ref_field(e)
        if isinstance(e, NumLit):
            return self.lit_num(e)
        if isinstance(e, StrLit):
            return self.lit_str(e.value)
        if isinstance(e, Figurative):
            if self.ctx.coll and e.kind in ('LOW-VALUE', 'HIGH-VALUE'):
                return self.ctx.coll_fig[e.kind]
            return FIG_FIELD[e.kind]
        if isinstance(e, AllLit):
            return self.lit_all(e)
        if isinstance(e, FuncCall):
            k = FUNCTIONS[e.name][0]
            if k == 'X' or (k == 'M' and not self.is_numeric(FuncCall(e.name, e.args, None, e.loc))):
                f = self.func_alnum(e)
            else:
                f = f"cob_dec_field({self.func_num(e)})"
            if e.refmod:
                f = self.apply_refmod(f, e.refmod, e.loc)
            return f
        if isinstance(e, CField):
            return e.text
        if isinstance(e, LengthOf):
            return f"cob_dec_field({self.dec(e)})"
        if isinstance(e, (BinOp, Neg, CDec, CVar)):
            return f"cob_dec_field({self.dec(e)})"
        raise CompileError("invalid operand", getattr(e, 'loc', None))

    def apply_refmod(self, f, refmod, loc):
        start, length = refmod
        s = self.int_expr(start)
        l = self.int_expr(length) if length is not None else '-1'
        return f"cob_refmod(&(cob_field){{0}}, {f}, {s}, {l}, {1 if self.opts.check else 0}, {c_string(str(loc))})"

    def item_base(self, it):
        return it.storage

    def offset_expr(self, ref, it):
        chain = it.occurs_chain()
        subs = ref.subs
        if len(subs) != len(chain):
            if not subs and chain:
                raise CompileError(f"'{ref.name}' requires {len(chain)} subscript(s)", ref.loc)
            raise CompileError(f"'{ref.name}' has {len(subs)} subscript(s), expected {len(chain)}", ref.loc)
        const = it.offset
        terms = []
        for occ, sub in zip(chain, subs):
            if sub == 'ALL':
                raise CompileError("ALL subscript is only allowed in function arguments", ref.loc)
            if isinstance(sub, NumLit) and sub.scale == 0 and not sub.neg:
                v = int(sub.digits)
                if v < 1 or v > occ.occurs.max:
                    raise CompileError(f"subscript {v} of '{ref.name}' out of range 1..{occ.occurs.max}", ref.loc)
                const += (v - 1) * occ.size
                continue
            s = self.int_expr(sub)
            if self.opts.check:
                s = f"cob_chk_sub({s}, {occ.occurs.max}, {c_string(ref.name)}, {c_string(str(ref.loc))})"
            terms.append(f"({s} - 1) * {occ.size}")
        return ' + '.join([str(const)] + terms)

    def size_expr(self, it, receiving=False):
        d = it.contains_odo() if it.children or it.occurs else None
        if d is None or d is it:
            return str(it.size)
        dep = d.occurs.depending
        if receiving:
            obj = self.resolve(dep)
            if obj is not None and any(x is obj for x in it.walk()):
                return str(it.size)
        cur = self.int_expr(dep)
        return f"({it.size} - ({d.occurs.max} - {cur}) * {d.size})"

    def ref_field(self, ref, receiving=False):
        it = self.resolve(ref)
        if isinstance(it, IndexName):
            a = self.attr(T_INDEX, 9, 0, F_SIGNED)
            f = f"CF(&{it.cname}, 4, &{a})"
            if ref.refmod:
                f = self.apply_refmod(f, ref.refmod, ref.loc)
            return f
        if getattr(it, 'special', None):
            f = it.special
            if ref.refmod:
                f = self.apply_refmod(f, ref.refmod, ref.loc)
            return f
        if it.level == 88:
            raise CompileError(f"condition-name '{ref.name}' cannot be used as a data item", ref.loc)
        off = self.offset_expr(ref, it)
        f = f"CF({it.storage} + {off}, {self.size_expr(it, receiving)}, &{self.item_attr(it)})"
        if ref.refmod:
            f = self.apply_refmod(f, ref.refmod, ref.loc)
        return f

    def data_ptr(self, ref):
        """C expression for data pointer of a reference (no refmod)."""
        it = self.resolve(ref)
        if isinstance(it, IndexName):
            return f"((unsigned char *)&{it.cname})"
        if getattr(it, 'special', None):
            return f"({it.special})->data"
        off = self.offset_expr(ref, it)
        return f"({it.storage} + {off})"

    # ================================================================ fixed-point fast paths
    C5_DIGITS = {1: 3, 2: 5, 4: 10, 8: 19}

    def fast_kind(self, ref):
        """(kind, ptr, item) for numeric items with inline scaled-integer access."""
        if not isinstance(ref, DataRef) or ref.refmod:
            return None
        it = self.resolve(ref)
        if isinstance(it, IndexName):
            return ('IX', it.cname, it)
        if not isinstance(it, DataItem) or getattr(it, 'special', None) or it.level == 88:
            return None
        if it.scale < 0 or it.digits > 18 or it.children:
            return None
        t = it.type
        if t == T_NUM_BINARY and it.size in (2, 4, 8):
            kind = 'BIN'
        elif t == T_NUM_COMP5 and it.size in (1, 2, 4, 8):
            kind = 'C5'
        elif t == T_NUM_DISPLAY and not (it.flags & F_SIGNED):
            kind = 'DU'
        elif t == T_NUM_DISPLAY and (it.flags & F_SIGNED) and not (it.flags & (F_SIGN_SEP | F_SIGN_LEAD)):
            kind = 'DS'
        elif t == T_NUM_PACKED and it.size <= 10:
            kind = 'PK'
        elif t == T_INDEX:
            kind = 'INDEXITEM'
        else:
            return None
        return (kind, self.data_ptr(ref), it)

    def fast_get(self, fk):
        kind, p, it = fk
        if kind == 'IX':
            return f"(cob_s64){p}"
        sg = 1 if (it.flags & F_SIGNED) else 0
        if kind == 'BIN':
            return f"cob_bin_get({p}, {it.size}, {sg})"
        if kind == 'C5':
            return f"cob_c5_get({p}, {it.size}, {sg})"
        if kind == 'DU':
            return f"cob_disp_get({p}, {it.size})"
        if kind == 'DS':
            return f"cob_disps_get({p}, {it.size})"
        if kind == 'PK':
            return f"cob_pack_get({p}, {it.size})"
        return f"cob_c5_get({p}, 4, 1)"

    def fast_scale(self, fk):
        kind, p, it = fk
        return 0 if kind in ('IX', 'INDEXITEM') else it.scale

    def fast_digits(self, fk):
        kind, p, it = fk
        if kind in ('IX', 'INDEXITEM'):
            return 10
        if kind == 'C5':
            return self.C5_DIGITS[it.size]
        return it.digits

    def fx(self, e, wide=False):
        """Scaled-integer evaluation: (C expr, scale, digit bound) or None."""
        cast = '(cob_s128)' if wide else ''
        if isinstance(e, CVar):
            return (f"({cast}{e.text})", 0, 18)
        if isinstance(e, NumLit):
            if len(e.digits) <= 18:
                v = int(e.digits)
                return (f"({cast}{'-' if e.neg else ''}{v}LL)", e.scale, max(1, len(str(v))))
            return None
        if isinstance(e, Figurative) and e.kind == 'ZERO':
            return (f"({cast}0LL)", 0, 1)
        if isinstance(e, DataRef):
            fk = self.fast_kind(e)
            if fk is None:
                return None
            return (f"({cast}{self.fast_get(fk)})", self.fast_scale(fk), self.fast_digits(fk))
        if isinstance(e, BinOp) and e.op in ('+', '-', '*'):
            a = self.fx(e.left, wide)
            if a is None:
                return None
            b = self.fx(e.right, wide)
            if b is None:
                return None
            if e.op == '*':
                return (f"({a[0]} * {b[0]})", a[1] + b[1], a[2] + b[2])
            S = max(a[1], b[1])
            ea, eb = a[0], b[0]
            if S > a[1]:
                ea = f"({ea} * {cast}{10 ** (S - a[1])}LL)"
            if S > b[1]:
                eb = f"({eb} * {cast}{10 ** (S - b[1])}LL)"
            d = max(a[2] + S - a[1], b[2] + S - b[1]) + 1
            return (f"({ea} {e.op} {eb})", S, d)
        if isinstance(e, Neg):
            a = self.fx(e.e, wide)
            if a is None:
                return None
            return (f"(-{a[0]})", a[1], a[2])
        return None

    def fast_value(self, e, target_scale=None):
        """(expr, scale, wide) evaluating e as scaled integer, or None."""
        r = self.fx(e)
        if r is None:
            return None
        extra = max(0, (target_scale or 0) - r[1]) if target_scale is not None else 0
        if r[2] + extra <= 18:
            return (r[0], r[1], False)
        if r[2] + extra <= 37:
            w = self.fx(e, True)
            return (w[0], w[1], True)
        return None

    def fast_int(self, e):
        """(expr, digit bound) for integer-valued expressions (scale 0)."""
        r = self.fx(e)
        if r is None or r[1] != 0:
            return None
        return (r[0], r[2])

    def fast_set(self, fk, val, vscale=0, wide=False, rounded=False):
        """Statement storing scaled integer val (scale vscale) into the item,
        with COBOL truncation (or rounding) semantics."""
        kind, p, it = fk
        if kind == 'IX':
            return f"{p} = (int)({val});" if vscale == 0 else f"{p} = (int)(({val}) / {10 ** vscale}LL);"
        tscale = self.fast_scale(fk)
        t = 'cob_s128' if wide else 'cob_s64'
        parts = [f"{t} cob_w = ({val});"]
        if vscale > tscale:
            k = vscale - tscale
            parts.append(f"cob_w = cob_round_div(cob_w, {10 ** k}LL, {1 if rounded else 0});")
        elif vscale < tscale:
            parts.append(f"cob_w *= {10 ** (tscale - vscale)}LL;")
        if kind == 'INDEXITEM':
            parts.append(f"cob_c5_set({p}, 4, (cob_s64)cob_w);")
            return '{ ' + ' '.join(parts) + ' }'
        signed = bool(it.flags & F_SIGNED)
        if not signed:
            parts.append("if (cob_w < 0) cob_w = -cob_w;")
        if kind == 'C5':
            parts.append(f"cob_c5_set({p}, {it.size}, (cob_s64)cob_w);")
        else:
            parts.append(f"cob_w %= {10 ** it.digits}LL;")
            if kind == 'BIN':
                parts.append(f"cob_bin_set({p}, {it.size}, (cob_s64)cob_w);")
            elif kind == 'DU':
                parts.append(f"cob_disp_set({p}, {it.size}, (cob_u64)cob_w);")
            elif kind == 'DS':
                parts.append(f"cob_disps_set({p}, {it.size}, (cob_s64)cob_w);")
            else:
                parts.append(f"cob_pack_set({p}, {it.size}, (cob_s64)cob_w, {1 if signed else 0}, {1 if it.digits % 2 == 0 else 0});")
        return '{ ' + ' '.join(parts) + ' }'

    # ================================================================ numeric expressions
    def int_expr(self, e):
        if isinstance(e, CVar):
            return e.text
        if isinstance(e, NumLit):
            if e.scale == 0 and len(e.digits) <= 18:
                return ('-' if e.neg else '') + str(int(e.digits)) + 'LL'
            return f"cob_d_to_int({self.dec(e)})"
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, IndexName) and not e.refmod:
                return it.cname
            if isinstance(it, DataItem) and it.level == 88:
                raise CompileError(f"condition-name '{e.name}' used in arithmetic", e.loc)
            fk = self.fast_kind(e)
            if fk is not None:
                return self.fast_get(fk)
            return f"cob_get_int({self.field(e)})"
        if isinstance(e, BinOp) and e.op in ('+', '-', '*'):
            fv = self.fast_int(e)
            if fv is not None and fv[1] <= 18:
                return fv[0]
            if self.intish(e.left) and self.intish(e.right):
                return f"({self.int_expr(e.left)} {e.op} {self.int_expr(e.right)})"
        if isinstance(e, Neg) and self.intish(e.e):
            return f"(-{self.int_expr(e.e)})"
        if isinstance(e, LengthOf):
            return f"(cob_s64)({self.length_of(e)})"
        return f"cob_d_to_int({self.dec(e)})"

    def intish(self, e):
        if isinstance(e, CVar):
            return True
        if isinstance(e, NumLit):
            return e.scale == 0 and len(e.digits) <= 18
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, IndexName):
                return True
            return isinstance(it, DataItem) and it.type in NUMERIC_TYPES and it.scale <= 0 and not e.refmod
        if isinstance(e, BinOp) and e.op in ('+', '-', '*'):
            return self.intish(e.left) and self.intish(e.right)
        return False

    def length_of(self, e):
        r = e.ref
        if isinstance(r, DataRef):
            it = self.resolve(r)
            if isinstance(it, IndexName):
                return '4'
            if getattr(it, 'special', None):
                return f"({it.special})->size"
            if r.refmod:
                return f"({self.field(r)})->size"
            return self.size_expr(it)
        return f"({self.field(r)})->size"

    def dec(self, e):
        if isinstance(e, CDec):
            return e.text
        if isinstance(e, CVar):
            return f"cob_d_int({e.text})"
        if isinstance(e, NumLit):
            if len(e.digits) <= 18:
                return f"cob_d_lit({'-' if e.neg else ''}{int(e.digits)}LL, {e.scale})"
            return f"cob_d_str({c_string(e.text)})"
        if isinstance(e, Figurative):
            if e.kind == 'ZERO':
                return "cob_d_int(0)"
            return f"cob_d_get({self.field(e)})"
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, IndexName) and not e.refmod:
                return f"cob_d_int({it.cname})"
            if isinstance(it, DataItem) and it.level == 88:
                raise CompileError(f"condition-name '{e.name}' used in arithmetic", e.loc)
            return f"cob_d_get({self.field(e)})"
        if isinstance(e, BinOp):
            fn = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'div', '**': 'pow'}[e.op]
            return f"cob_d_{fn}({self.dec(e.left)}, {self.dec(e.right)})"
        if isinstance(e, Neg):
            return f"cob_d_neg({self.dec(e.e)})"
        if isinstance(e, LengthOf):
            return f"cob_d_int((cob_s64)({self.length_of(e)}))"
        if isinstance(e, FuncCall):
            k = FUNCTIONS[e.name][0]
            if e.refmod or k == 'X' or (k == 'M' and not self.is_numeric(e)):
                return f"cob_d_get({self.field(e)})"
            return self.func_num(e)
        if isinstance(e, CField):
            return f"cob_d_get({e.text})"
        return f"cob_d_get({self.field(e)})"

    # ================================================================ intrinsic functions
    def has_all_sub(self, e):
        return isinstance(e, DataRef) and any(s == 'ALL' for s in e.subs)

    def expand_all_args(self, args, kind):
        """Returns (prelude C code, count expr, array expr) for argument lists
        that may contain ALL subscripts. kind 'D' for cob_dec, 'F' for fields."""
        if not any(self.has_all_sub(a) for a in args):
            if kind == 'D':
                items = ', '.join(self.dec(a) for a in args)
                return None, str(len(args)), f"(cob_dec[]){{{items}}}"
            items = ', '.join(self.field(a) for a in args)
            return None, str(len(args)), f"(cob_field *[]){{{items}}}"
        total = 0
        parts = []
        buf = self.sym('cob_ab')
        cnt = self.sym('cob_an')
        typ = 'cob_dec' if kind == 'D' else 'cob_field *'
        maxn = 0
        for a in args:
            if self.has_all_sub(a):
                it = self.resolve(a)
                chain = it.occurs_chain()
                n = 1
                for occ, s in zip(chain, a.subs):
                    if s == 'ALL':
                        n *= occ.occurs.max
                maxn += n
            else:
                maxn += 1
        if kind == 'D':
            code = [f"cob_dec {buf}[{maxn}]; cob_s64 {cnt} = 0;"]
        else:
            code = [f"cob_field {buf}v[{maxn}]; cob_field *{buf}[{maxn}]; cob_s64 {cnt} = 0;"]
        for a in args:
            if not self.has_all_sub(a):
                if kind == 'D':
                    code.append(f"{buf}[{cnt}++] = {self.dec(a)};")
                else:
                    code.append(f"{buf}v[{cnt}] = *({self.field(a)}); {buf}[{cnt}] = &{buf}v[{cnt}]; {cnt}++;")
                continue
            it = self.resolve(a)
            chain = it.occurs_chain()
            newsubs = []
            loops = []
            for occ, sb in zip(chain, a.subs):
                if sb == 'ALL':
                    v = self.sym('cob_ai')
                    loops.append((v, occ.occurs.max))
                    newsubs.append(CVar(v))
                else:
                    newsubs.append(sb)
            r2 = DataRef(a.name, a.quals, newsubs, a.refmod, a.loc)
            r2.item = it
            prefix = ''
            for v, mx in loops:
                prefix += f"for (cob_s64 {v} = 1; {v} <= {mx}; {v}++) "
            if kind == 'D':
                code.append(prefix + f"{buf}[{cnt}++] = {self.dec(r2)};")
            else:
                code.append(prefix + f"{{ {buf}v[{cnt}] = *({self.field(r2)}); {buf}[{cnt}] = &{buf}v[{cnt}]; {cnt}++; }}")
        return ' '.join(code), cnt, buf

    def func_num(self, e):
        name = e.name
        a = e.args
        D = lambda i: self.dec(a[i])
        F = lambda i: self.field(a[i])
        if name == 'ABS':
            return f"cob_fn_abs({D(0)})"
        if name == 'INTEGER':
            return f"cob_fn_integer({D(0)})"
        if name == 'INTEGER-PART':
            return f"cob_fn_integer_part({D(0)})"
        if name == 'FRACTION-PART':
            return f"cob_fn_fraction_part({D(0)})"
        if name == 'SIGN':
            return f"cob_fn_sign({D(0)})"
        if name == 'SQRT':
            return f"cob_fn_sqrt({D(0)})"
        if name == 'FACTORIAL':
            return f"cob_fn_factorial({D(0)})"
        if name == 'MOD':
            return f"cob_fn_mod({D(0)}, {D(1)})"
        if name == 'REM':
            return f"cob_fn_rem({D(0)}, {D(1)})"
        if name in MATH_FN:
            return f"cob_fn_math({MATH_FN[name]}, {D(0)})"
        if name == 'PI':
            return "cob_fn_pi()"
        if name == 'E':
            return "cob_fn_e()"
        if name == 'RANDOM':
            return f"cob_fn_random(1, {D(0)})" if a else "cob_fn_random(0, cob_d_int(0))"
        if name in ('LENGTH', 'BYTE-LENGTH', 'STORED-CHAR-LENGTH'):
            if isinstance(a[0], DataRef) and not a[0].refmod:
                return f"cob_d_int((cob_s64)({self.length_of(LengthOf(a[0]))}))"
            if isinstance(a[0], StrLit):
                return f"cob_d_int({len(a[0].value)})"
            if name == 'STORED-CHAR-LENGTH':
                return f"cob_fn_length(cob_fn_trim({F(0)}, 2))"
            return f"cob_fn_length({F(0)})"
        if name == 'ORD':
            return f"cob_fn_ord({F(0)})"
        if name in ('NUMVAL', 'NUMVAL-F'):
            return f"cob_fn_numval({F(0)})"
        if name == 'NUMVAL-C':
            return f"cob_fn_numval_c({F(0)}, {F(1) if len(a) > 1 else 'NULL'})"
        if name == 'TEST-NUMVAL':
            return f"cob_fn_test_numval({F(0)})"
        if name in AGG_FN:
            pre, n, arr = self.expand_all_args(a, 'D')
            call = f"cob_fn_aggregate({AGG_FN[name]}, (int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        if name in ('ORD-MAX', 'ORD-MIN'):
            if all(self.is_numeric(x) for x in a):
                pre, n, arr = self.expand_all_args(a, 'D')
                call = f"cob_fn_ord_minmax({1 if name == 'ORD-MAX' else 0}, (int){n}, {arr})"
            else:
                pre, n, arr = self.expand_all_args(a, 'F')
                call = f"cob_fn_ord_minmax_alnum({1 if name == 'ORD-MAX' else 0}, (int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        if name == 'ANNUITY':
            return f"cob_fn_annuity({D(0)}, {D(1)})"
        if name == 'PRESENT-VALUE':
            pre, n, arr = self.expand_all_args(a, 'D')
            call = f"cob_fn_present_value((int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        simple = {'INTEGER-OF-DATE': 'integer_of_date', 'DATE-OF-INTEGER': 'date_of_integer',
                  'INTEGER-OF-DAY': 'integer_of_day', 'DAY-OF-INTEGER': 'day_of_integer',
                  'TEST-DATE-YYYYMMDD': 'test_date', 'TEST-DAY-YYYYDDD': 'test_day'}
        if name in simple:
            return f"cob_fn_{simple[name]}({D(0)})"
        if name in ('DATE-TO-YYYYMMDD', 'DAY-TO-YYYYDDD', 'YEAR-TO-YYYY'):
            fn = {'DATE-TO-YYYYMMDD': 'date_to_yyyymmdd', 'DAY-TO-YYYYDDD': 'day_to_yyyyddd',
                  'YEAR-TO-YYYY': 'year_to_yyyy'}[name]
            args = [D(i) if i < len(a) else 'cob_d_int(0)' for i in range(3)]
            return f"cob_fn_{fn}({len(a)}, {', '.join(args)})"
        if name == 'SECONDS-PAST-MIDNIGHT':
            return "cob_fn_seconds_past_midnight()"
        if name == 'INTEGER-OF-BOOLEAN':
            return f"cob_d_get({F(0)})"
        raise CompileError(f"function {name} is not supported in numeric context", e.loc)

    def func_alnum(self, e):
        name = e.name
        a = e.args
        F = lambda i: self.field(a[i])
        if name == 'UPPER-CASE':
            return f"cob_fn_upper({F(0)})"
        if name == 'LOWER-CASE':
            return f"cob_fn_lower({F(0)})"
        if name == 'REVERSE':
            return f"cob_fn_reverse({F(0)})"
        if name in ('TRIM', 'TRIML', 'TRIMR'):
            mode = {'TRIM': 0, 'TRIML': 1, 'TRIMR': 2}[name]
            args = list(a)
            if len(args) > 1 and isinstance(args[-1], StrLit) and args[-1].value in (b'LEADING', b'TRAILING'):
                mode = 1 if args[-1].value == b'LEADING' else 2
                args = args[:-1]
            return f"cob_fn_trim({self.field(args[0])}, {mode})"
        if name == 'CHAR':
            return f"cob_fn_char({self.dec(a[0])})"
        if name == 'CURRENT-DATE':
            return "cob_fn_current_date()"
        if name == 'WHEN-COMPILED':
            return "cob_fn_when_compiled()"
        if name == 'MODULE-NAME':
            return f"cob_fn_module_name({c_string(self.prog.name)})"
        if name == 'HEX-OF':
            return f"cob_fn_hex_of({F(0)})"
        if name in ('CONCATENATE', 'SUBSTITUTE'):
            pre, n, arr = self.expand_all_args(a, 'F')
            call = f"cob_fn_{name.lower()}((int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        if name in ('MAX', 'MIN'):
            pre, n, arr = self.expand_all_args(a, 'F')
            call = f"cob_fn_minmax_alnum({1 if name == 'MAX' else 0}, (int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        raise CompileError(f"function {name} is not supported in alphanumeric context", e.loc)

    # ================================================================ conditions
    def cond(self, c):
        if isinstance(c, Rel):
            return self.rel(c.left, c.op, c.right)
        if isinstance(c, And):
            return f"({self.cond(c.a)} && {self.cond(c.b)})"
        if isinstance(c, Or):
            return f"({self.cond(c.a)} || {self.cond(c.b)})"
        if isinstance(c, Not):
            return f"!{self.cond(c.a)}"
        if isinstance(c, ConstCond):
            return '1' if c.value else '0'
        if isinstance(c, ClassTest):
            f = self.field(c.expr)
            if c.cls == 'NUMERIC':
                x = f"cob_is_numeric({f})"
            elif c.cls in ('ALPHABETIC',):
                x = f"cob_is_alpha({f})"
            elif c.cls == 'ALPHABETIC-LOWER':
                x = f"cob_is_lower({f})"
            elif c.cls == 'ALPHABETIC-UPPER':
                x = f"cob_is_upper({f})"
            elif c.cls == 'ALPHANUMERIC':
                x = "1"
            else:
                tbl = self.ctx.class_tables.get(c.cls)
                if tbl is None:
                    raise CompileError(f"unknown class '{c.cls}'", self.cur_loc)
                x = f"cob_is_class({f}, {tbl})"
            return f"(!{x})" if c.neg else f"({x})"
        if isinstance(c, SignTest):
            d = f"cob_d_sign({self.dec(c.expr)})"
            op = {'POSITIVE': '> 0', 'NEGATIVE': '< 0', 'ZERO': '== 0'}[c.sign]
            x = f"({d} {op})"
            return f"(!{x})" if c.neg else x
        if isinstance(c, CondRef):
            return self.cond_name(c.ref)
        if isinstance(c, MaybeCond):
            o = c.operand
            if isinstance(o, DataRef) and not o.quals and not o.subs and o.name in self.prog.switch_conds \
                    and o.name not in self.ctx.names:
                n, on = self.prog.switch_conds[o.name]
                return f"(cob_switch_get({n}) == {1 if on else 0})"
            if isinstance(o, DataRef):
                it = self.resolve(o)
                if isinstance(it, DataItem) and it.level == 88:
                    return self.cond_name(o)
            if c.subject is not None and c.op is not None:
                return self.rel(c.subject, c.op, o)
            if isinstance(o, DataRef):
                raise CompileError(f"'{o.name}' is not a condition", o.loc)
            raise CompileError("condition expected", self.cur_loc)
        raise CompileError("invalid condition", self.cur_loc)

    def alnum_fixed(self, e):
        """(ptr expr, size) for plain alphanumeric operands of fixed size."""
        if isinstance(e, StrLit):
            v = e.value or b' '
            return (f"(const unsigned char *){c_string(v)}", len(v))
        if isinstance(e, DataRef) and not e.refmod:
            it = self.resolve(e)
            if isinstance(it, DataItem) and it.level != 88 and not getattr(it, 'special', None) and \
                    it.type in (T_ALNUM, T_ALPHA, T_GROUP, T_ALNUM_EDITED, T_NUM_EDITED) and \
                    (it.type != T_GROUP or it.contains_odo() is None):
                return (self.data_ptr(e), it.size)
        return None

    def rel(self, l, op, r):
        cop = CMP_OP[op]
        if self.is_numeric(l) and self.is_numeric(r):
            a = self.fx(l)
            b = self.fx(r) if a is not None else None
            if a is not None and b is not None:
                S = max(a[1], b[1])
                need = max(a[2] + S - a[1], b[2] + S - b[1])
                if need <= 37:
                    wide = need > 18
                    a = self.fx(l, wide)
                    b = self.fx(r, wide)
                    cast = '(cob_s128)' if wide else ''
                    ea = a[0] if S == a[1] else f"({a[0]} * {cast}{10 ** (S - a[1])}LL)"
                    eb = b[0] if S == b[1] else f"({b[0]} * {cast}{10 ** (S - b[1])}LL)"
                    return f"({ea} {cop} {eb})"
        if not self.is_numeric(l) and not self.is_numeric(r) and not self.ctx.coll:
            al = self.alnum_fixed(l)
            ar = self.alnum_fixed(r)
            if al is not None and ar is not None and al[1] == ar[1] and not (
                    isinstance(l, StrLit) and isinstance(r, StrLit)):
                if al[1] == 1:
                    return f"(({al[0]})[0] {cop} ({ar[0]})[0])"
                return f"(memcmp({al[0]}, {ar[0]}, {al[1]}) {cop} 0)"
        if self.is_numeric(l) and self.is_numeric(r):
            if isinstance(r, Figurative) and r.kind == 'ZERO':
                return f"(cob_d_sign({self.dec(l)}) {cop} 0)"
            return f"(cob_d_cmp({self.dec(l)}, {self.dec(r)}) {cop} 0)"
        return f"(cob_cmp({self.field(l)}, {self.field(r)}) {cop} 0)"

    def cond_name(self, ref):
        c = self.resolve(ref)
        if not (isinstance(c, DataItem) and c.level == 88):
            raise CompileError(f"'{ref.name}' is not a condition-name", ref.loc)
        var = c.parent
        vref = DataRef(var.name or 'FILLER', [], ref.subs, None, ref.loc)
        vref.item = var
        f = self.field(vref)
        num = var.type in NUMERIC_TYPES
        parts = []
        for lo, hi in c.values:
            if hi is None:
                parts.append(self.cmp_val('cob_c', num, lo, '=='))
            else:
                parts.append(f"({self.cmp_val('cob_c', num, lo, '>=')} && {self.cmp_val('cob_c', num, hi, '<=')})")
        return f"({{ const cob_field *cob_c = {f}; ({' || '.join(parts)}); }})"

    def cmp_val(self, var, num, v, op):
        if num and isinstance(v, NumLit):
            return f"(cob_d_cmp(cob_d_get({var}), {self.dec(v)}) {op} 0)"
        if num and isinstance(v, Figurative) and v.kind == 'ZERO':
            return f"(cob_d_sign(cob_d_get({var})) {op} 0)"
        return f"(cob_cmp({var}, {self.field(v)}) {op} 0)"

    # ================================================================ sections / statements
    def gen_section(self, sec):
        em = self.em
        self.cur_section = sec
        sec.end_label = f"{sec.label}_end"
        em(f"/* SECTION {sec.name or '(unnamed)'} */")
        em.label(sec.label)
        self.seg_enter(sec)
        for para in sec.paragraphs:
            self.cur_para = para
            para.end_label = f"{para.label}_end"
            em(f"/* PARAGRAPH {para.name or '(unnamed)'} */")
            em.label(para.label)
            self.seg_enter(sec)
            for sent in para.sentences:
                end = self.new_label('E')
                self.cur_sentence_end = end
                for st in sent.stmts:
                    self.stmt(st)
                em.label(end)
            em.label(para.end_label)
            em(f"if (frame_ptr->perform_through == {para.id}) goto *frame_ptr->return_address;")
        em.label(sec.end_label)
        em(f"if (frame_ptr->perform_through == {sec.id}) goto *frame_ptr->return_address;")

    def stmts(self, lst):
        if lst:
            for s in lst:
                self.stmt(s)

    def stmt(self, s):
        self.cur_loc = s.loc
        fn = getattr(self, 'g_' + type(s).__name__, None)
        if fn is None:
            raise CompileError(f"{type(s).__name__} is not supported", s.loc)
        self.em(f"/* line {s.loc.line}: {type(s).__name__.upper()} */")
        fn(s)

    def block(self, stmts):
        self.em.ind += 1
        self.stmts(stmts)
        self.em.ind -= 1

    def handlers(self, cond_c, on, noton):
        em = self.em
        if on is None and noton is None:
            return
        if on is not None:
            em(f"if ({cond_c}) {{")
            self.block(on)
            if noton is not None:
                em("} else {")
                self.block(noton)
            em("}")
        else:
            em(f"if (!({cond_c})) {{")
            self.block(noton)
            em("}")

    # ---------------------------------------------------------------- MOVE
    def check_receiving(self, ref):
        if not isinstance(ref, DataRef):
            raise CompileError("receiving operand must be a data item", self.cur_loc)
        it = self.resolve(ref)
        if isinstance(it, DataItem) and it.level == 88:
            raise CompileError(f"condition-name '{ref.name}' cannot be a receiving item", ref.loc)
        return it

    def g_Move(self, s):
        em = self.em
        if s.corr:
            if not isinstance(s.src, DataRef):
                raise CompileError("MOVE CORRESPONDING requires group items", s.loc)
            for d in s.dsts:
                self.gen_corr(s.src, d, 'MOVE', None)
            return
        for d in s.dsts:
            it = self.check_receiving(d)
            if isinstance(it, IndexName):
                raise CompileError(f"index '{d.name}' cannot be a MOVE target; use SET", d.loc)
        if len(s.dsts) == 1:
            line = self.fast_move(s.src, s.dsts[0])
            em(line if line else f"cob_move({self.field(s.src)}, {self.ref_field(s.dsts[0], True)});")
            return
        em("{")
        em.ind += 1
        em(f"const cob_field *cob_s = {self.field(s.src)};")
        for d in s.dsts:
            em(f"cob_move(cob_s, {self.ref_field(d, True)});")
        em.ind -= 1
        em("}")

    def fast_move(self, src, dst):
        fd = self.fast_kind(dst) if isinstance(dst, DataRef) else None
        if fd is not None and fd[0] != 'IX' and self.is_numeric(src):
            fv = self.fast_value(src, self.fast_scale(fd))
            if fv is not None:
                return self.fast_set(fd, fv[0], fv[1], fv[2])
        if isinstance(dst, DataRef) and not dst.refmod:
            it = self.resolve(dst)
            if isinstance(it, DataItem) and it.type in (T_ALNUM, T_ALPHA, T_GROUP) and \
                    not (it.flags & F_JUSTIFIED) and it.level != 88 and not getattr(it, 'special', None) and \
                    (it.type != T_GROUP or it.contains_odo() is None):
                src_a = None
                if isinstance(src, StrLit):
                    src_a = self.alnum_fixed(src)
                elif isinstance(src, DataRef) and not src.refmod:
                    si = self.resolve(src)
                    if isinstance(si, DataItem) and si.type in (T_ALNUM, T_ALPHA, T_GROUP) and \
                            si.level != 88 and (si.type != T_GROUP or si.contains_odo() is None) and \
                            not getattr(si, 'special', None):
                        src_a = (self.data_ptr(src), si.size)
                if src_a is not None:
                    dp = self.data_ptr(dst)
                    n = min(src_a[1], it.size)
                    code = f"memmove({dp}, {src_a[0]}, {n});"
                    if it.size > n:
                        code = f"{{ unsigned char *cob_dp = {dp}; memmove(cob_dp, {src_a[0]}, {n}); memset(cob_dp + {n}, ' ', {it.size - n}); }}"
                    return code
        return None

    def corr_pairs(self, g1, g2, numeric):
        pairs = []
        for c1 in g1.children:
            if c1.is_filler or c1.redefines is not None or c1.occurs or c1.level in (66, 88):
                continue
            for c2 in g2.children:
                if c2.name != c1.name or c2.redefines is not None or c2.occurs or c2.level in (66, 88):
                    continue
                if c1.children and c2.children:
                    pairs.extend(self.corr_pairs(c1, c2, numeric))
                elif not (c1.children or c2.children) or not numeric:
                    if numeric and not (c1.type in NUMERIC_TYPES and c2.type in NUMERIC_TYPES):
                        break
                    pairs.append((c1, c2))
                break
        return pairs

    def gen_corr(self, src, dst, verb, target_opts, err_var=None):
        em = self.em
        g1 = self.resolve(src)
        g2 = self.resolve(dst)
        if not (isinstance(g1, DataItem) and g1.children and isinstance(g2, DataItem) and g2.children):
            raise CompileError("CORRESPONDING requires group items", self.cur_loc)
        pairs = self.corr_pairs(g1, g2, verb != 'MOVE')
        if not pairs:
            DIAG.warn("no corresponding items found", self.cur_loc)
            return
        em("{")
        em.ind += 1
        em(f"unsigned char *cob_g1 = {self.data_ptr(src)};")
        em(f"unsigned char *cob_g2 = {self.data_ptr(dst)};")
        for a, b in pairs:
            fa = f"CF(cob_g1 + {a.offset - g1.offset}, {a.size}, &{self.item_attr(a)})"
            fb = f"CF(cob_g2 + {b.offset - g2.offset}, {b.size}, &{self.item_attr(b)})"
            if verb == 'MOVE':
                em(f"cob_move({fa}, {fb});")
            else:
                fn = 'add' if verb == 'ADD' else 'sub'
                em(f"{err_var} |= cob_d_set({fb}, cob_d_{fn}(cob_d_get({fb}), cob_d_get({fa})), {target_opts});")
        em.ind -= 1
        em("}")

    # ---------------------------------------------------------------- arithmetic
    def target_opt(self, t, chk):
        o = []
        if t.rounded:
            o.append('COB_ROUNDED')
        if chk:
            o.append('COB_SIZE_CHECK')
        return '|'.join(o) if o else '0'

    def check_numeric_target(self, ref):
        it = self.check_receiving(ref)
        if isinstance(it, IndexName):
            return
        if it.type not in NUMERIC_TYPES and it.type != T_NUM_EDITED:
            raise CompileError(f"'{ref.name}' is not numeric", ref.loc)

    def check_numeric_operand(self, e):
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, DataItem) and it.level != 88 and it.type not in NUMERIC_TYPES and not e.refmod:
                if it.type == T_NUM_EDITED:
                    return
                raise CompileError(f"'{e.name}' is not numeric", e.loc)
        elif isinstance(e, (StrLit, AllLit)):
            raise CompileError("alphanumeric literal used in arithmetic", self.cur_loc)

    def fast_arith(self, s):
        """Fixed-point fast path for ADD/SUBTRACT/MULTIPLY without size checks."""
        if s.on_error is not None or s.not_on_error is not None or s.corr:
            return False
        if s.verb == 'DIVIDE':
            return False
        targets = s.to + s.giving
        fks = []
        for t in targets:
            fk = self.fast_kind(t.ref)
            if fk is None or fk[0] == 'IX':
                return False
            fks.append(fk)
        ops = list(s.operands) + ([s.by_or_into] if s.by_or_into is not None else [])
        for o in ops:
            if not self.is_numeric(o) or self.fx(o) is None:
                return False
        acc = s.operands[0]
        if s.verb in ('ADD', 'SUBTRACT'):
            for o in s.operands[1:]:
                acc = BinOp('+', acc, o)
        av = self.fast_value(acc)
        if av is None or av[2]:
            return False
        tmp = CVar('cob_ft')
        tscale = av[1]
        exprs = []
        if s.verb in ('ADD', 'SUBTRACT'):
            for t in s.to:
                exprs.append(BinOp('+' if s.verb == 'ADD' else '-', t.ref, tmp))
            for t in s.giving:
                exprs.append(tmp if s.verb == 'ADD' else BinOp('-', s.by_or_into, tmp))
        else:
            for t in s.to:
                exprs.append(BinOp('*', tmp, t.ref))
            for t in s.giving:
                exprs.append(BinOp('*', tmp, s.by_or_into))
        # the temporary carries the accumulator's scale and digit bound
        self._tmp_fx = (av[1], self.fx(acc)[2])
        vals = []
        try:
            for e, fk in zip(exprs, fks):
                v = self.fx_tmp(e, False)
                if v is None:
                    return False
                extra = max(0, self.fast_scale(fk) - v[1])
                if v[2] + extra > 37:
                    return False
                wide = v[2] + extra > 18
                if wide:
                    v = self.fx_tmp(e, True)
                vals.append((v[0], v[1], wide))
        finally:
            pass
        em = self.em
        em("{")
        em.ind += 1
        em(f"cob_s64 cob_ft = {av[0]};")
        for fk, t, (val, sc, wide) in zip(fks, targets, vals):
            em(self.fast_set(fk, val, sc, wide, t.rounded))
        em.ind -= 1
        em("}")
        return True

    def fx_tmp(self, e, wide):
        """fx() where CVar('cob_ft') has the accumulator's scale/bound."""
        cast = '(cob_s128)' if wide else ''
        if isinstance(e, CVar) and e.text == 'cob_ft':
            sc, d = self._tmp_fx
            return (f"({cast}cob_ft)", sc, d)
        if isinstance(e, BinOp):
            a = self.fx_tmp(e.left, wide)
            b = self.fx_tmp(e.right, wide) if a is not None else None
            if a is None or b is None:
                return None
            if e.op == '*':
                return (f"({a[0]} * {b[0]})", a[1] + b[1], a[2] + b[2])
            S = max(a[1], b[1])
            ea, eb = a[0], b[0]
            if S > a[1]:
                ea = f"({ea} * {cast}{10 ** (S - a[1])}LL)"
            if S > b[1]:
                eb = f"({eb} * {cast}{10 ** (S - b[1])}LL)"
            return (f"({ea} {e.op} {eb})", S, max(a[2] + S - a[1], b[2] + S - b[1]) + 1)
        return self.fx(e, wide)

    def g_Arith(self, s):
        em = self.em
        chk = s.on_error is not None or s.not_on_error is not None
        if self.fast_arith(s):
            return
        for o in ([] if s.corr else s.operands):
            self.check_numeric_operand(o)
        if s.by_or_into is not None:
            self.check_numeric_operand(s.by_or_into)
        for t in ([] if s.corr else s.to + s.giving):
            self.check_numeric_target(t.ref)
        em("{")
        em.ind += 1
        em("int cob_err = 0;")
        if s.corr:
            if len(s.operands) != 1 or len(s.to) != 1:
                raise CompileError(f"{s.verb} CORRESPONDING requires one group on each side", s.loc)
            self.gen_corr(s.operands[0], s.to[0].ref, s.verb, self.target_opt(s.to[0], chk), 'cob_err')
        elif s.verb in ('ADD', 'SUBTRACT'):
            ops = s.operands
            acc = self.dec(ops[0])
            for o in ops[1:]:
                acc = f"cob_d_add({acc}, {self.dec(o)})"
            em(f"cob_dec cob_t = {acc};")
            if s.verb == 'ADD':
                for t in s.to:
                    f = self.field(t.ref)
                    em(f"cob_err |= cob_d_set({f}, cob_d_add(cob_d_get({f}), cob_t), {self.target_opt(t, chk)});")
                for t in s.giving:
                    em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_t, {self.target_opt(t, chk)});")
            else:
                for t in s.to:
                    f = self.field(t.ref)
                    em(f"cob_err |= cob_d_set({f}, cob_d_sub(cob_d_get({f}), cob_t), {self.target_opt(t, chk)});")
                if s.giving:
                    em(f"cob_dec cob_r = cob_d_sub({self.dec(s.by_or_into)}, cob_t);")
                    for t in s.giving:
                        em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_r, {self.target_opt(t, chk)});")
        elif s.verb == 'MULTIPLY':
            em(f"cob_dec cob_t = {self.dec(s.operands[0])};")
            for t in s.to:
                f = self.field(t.ref)
                em(f"cob_err |= cob_d_set({f}, cob_d_mul(cob_t, cob_d_get({f})), {self.target_opt(t, chk)});")
            if s.giving:
                em(f"cob_dec cob_r = cob_d_mul(cob_t, {self.dec(s.by_or_into)});")
                for t in s.giving:
                    em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_r, {self.target_opt(t, chk)});")
        elif s.verb == 'DIVIDE':
            em(f"cob_dec cob_t = {self.dec(s.operands[0])};")
            for t in s.to:
                f = self.field(t.ref)
                em(f"cob_err |= cob_d_set({f}, cob_d_div(cob_d_get({f}), cob_t), {self.target_opt(t, chk)});")
            if s.giving:
                if s.form == 'INTO':
                    em(f"cob_dec cob_dd = {self.dec(s.by_or_into)}, cob_dv = cob_t;")
                else:
                    em(f"cob_dec cob_dd = cob_t, cob_dv = {self.dec(s.by_or_into)};")
                em("cob_dec cob_q = cob_d_div(cob_dd, cob_dv);")
                for t in s.giving:
                    em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_q, {self.target_opt(t, chk)});")
                if s.remainder is not None:
                    self.check_numeric_target(s.remainder)
                    g = self.resolve(s.giving[0].ref)
                    sc = g.scale if isinstance(g, DataItem) else 0
                    em(f"cob_dec cob_qt = cob_d_trunc(cob_q, {sc});")
                    em(f"cob_err |= cob_d_set({self.field(s.remainder)}, cob_d_sub(cob_dd, cob_d_mul(cob_qt, cob_dv)), {'COB_SIZE_CHECK' if chk else '0'});")
        self.handlers('cob_err', s.on_error, s.not_on_error)
        em("(void)cob_err;")
        em.ind -= 1
        em("}")

    def g_Compute(self, s):
        em = self.em
        chk = s.on_error is not None or s.not_on_error is not None
        for t in s.targets:
            self.check_numeric_target(t.ref)
        if not chk:
            fks = [self.fast_kind(t.ref) for t in s.targets]
            if all(fk is not None and fk[0] != 'IX' for fk in fks):
                ts = max(self.fast_scale(fk) for fk in fks)
                fv = self.fast_value(s.expr, ts)
                if fv is not None:
                    if len(fks) == 1:
                        em(self.fast_set(fks[0], fv[0], fv[1], fv[2], s.targets[0].rounded))
                    else:
                        em("{")
                        em.ind += 1
                        em(f"{'cob_s128' if fv[2] else 'cob_s64'} cob_fc = {fv[0]};")
                        for fk, t in zip(fks, s.targets):
                            em(self.fast_set(fk, 'cob_fc', fv[1], fv[2], t.rounded))
                        em.ind -= 1
                        em("}")
                    return
        em("{")
        em.ind += 1
        em("int cob_err = 0;")
        em(f"cob_dec cob_t = {self.dec(s.expr)};")
        for t in s.targets:
            em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_t, {self.target_opt(t, chk)});")
        self.handlers('cob_err', s.on_error, s.not_on_error)
        em("(void)cob_err;")
        em.ind -= 1
        em("}")

    # ---------------------------------------------------------------- DISPLAY / ACCEPT
    def g_Display(self, s):
        em = self.em
        upon = s.upon
        if upon in ('ENVIRONMENT-NAME', 'ENVIRONMENT-VALUE', 'ARGUMENT-NUMBER'):
            k = {'ENVIRONMENT-NAME': 0, 'ENVIRONMENT-VALUE': 1, 'ARGUMENT-NUMBER': 2}[upon]
            em(f"cob_display_env({k}, {self.field(s.items[0])});")
            return
        dev = 1 if upon in ('SYSERR', 'STDERR') else 0
        for it in s.items:
            if isinstance(it, StrLit):
                v = it.value
                em(f"cob_display_lit({dev}, {c_string(v)}, {len(v)});")
            elif isinstance(it, NumLit):
                t = it.text
                em(f"cob_display_lit({dev}, {c_string(t)}, {len(t)});")
            elif isinstance(it, Figurative):
                v = FIG_BYTES[it.kind]
                em(f"cob_display_lit({dev}, {c_string(v)}, 1);")
            elif isinstance(it, AllLit):
                em(f"cob_display_lit({dev}, {c_string(it.value)}, {len(it.value)});")
            elif isinstance(it, FuncCall) and self.is_numeric(it):
                em(f"cob_display_dec({dev}, {self.dec(it)});")
            elif isinstance(it, (LengthOf, BinOp, Neg)):
                em(f"cob_display_dec({dev}, {self.dec(it)});")
            else:
                em(f"cob_display({dev}, {self.field(it)});")
        em(f"cob_display_end({dev}, {0 if s.no_advancing else 1});")
        if s.not_on_exc:
            self.stmts(s.not_on_exc)

    def g_Accept(self, s):
        em = self.em
        self.check_receiving(s.target)
        f = self.field(s.target)
        src = s.source
        rc = None
        if src == 'CONSOLE':
            rc = f"cob_accept({f})"
        elif src in ('DATE', 'DATE8', 'DAY', 'DAY7', 'DAY-OF-WEEK'):
            k = {'DATE': 0, 'DATE8': 1, 'DAY': 2, 'DAY7': 3, 'DAY-OF-WEEK': 4}[src]
            em(f"cob_accept_date({f}, {k});")
        elif src == 'TIME':
            em(f"cob_accept_time({f});")
        elif src == 'COMMAND-LINE':
            em(f"cob_accept_cmdline({f});")
        elif src == 'ENVIRONMENT':
            rc = f"cob_accept_env({f}, {self.field(s.arg)})"
        elif src == 'ENVIRONMENT-VALUE':
            rc = f"cob_accept_env({f}, NULL)"
        elif src == 'ARGUMENT-NUMBER':
            em(f"cob_accept_argv({f}, 0);")
        elif src == 'ARGUMENT-VALUE':
            em(f"cob_accept_argv({f}, 1);")
        else:
            em(f"cob_accept({f});")
        if rc:
            if s.on_exc is not None or s.not_on_exc is not None:
                em("{")
                em.ind += 1
                em(f"int cob_ex = {rc};")
                self.handlers('cob_ex', s.on_exc, s.not_on_exc)
                em.ind -= 1
                em("}")
            else:
                em(f"(void){rc};")

    # ---------------------------------------------------------------- IF / EVALUATE
    def g_If(self, s):
        em = self.em
        em(f"if ({self.cond(s.cond)}) {{")
        self.block(s.then)
        if s.els:
            em("} else {")
            self.block(s.els)
        em("}")

    def g_Evaluate(self, s):
        em = self.em
        subj = []
        for sb in s.subjects:
            if sb in ('TRUE', 'FALSE'):
                subj.append(('B', sb == 'TRUE'))
            elif isinstance(sb, Cond):
                v = self.sym('cob_eb')
                self.local(f"int {v};")
                em(f"{v} = {self.cond(sb)};")
                subj.append(('C', v))
            elif isinstance(sb, DataRef) and isinstance(self.resolve(sb), DataItem) and self.resolve(sb).level == 88:
                v = self.sym('cob_eb')
                self.local(f"int {v};")
                em(f"{v} = {self.cond_name(sb)};")
                subj.append(('C', v))
            elif isinstance(sb, (BinOp, Neg)) or (isinstance(sb, FuncCall) and self.is_numeric(sb)):
                v = self.sym('cob_ed')
                self.local(f"cob_dec {v};")
                em(f"{v} = {self.dec(sb)};")
                subj.append(('V', CDec(v)))
            else:
                subj.append(('V', sb))
        first = True
        for groups, stmts in s.whens:
            alts = []
            for objs in groups:
                terms = []
                for (kind, sv), ob in zip(subj, objs):
                    t = self.when_term(kind, sv, ob)
                    if t != '1':
                        terms.append(t)
                alts.append('(' + (' && '.join(terms) if terms else '1') + ')')
            c = ' || '.join(alts)
            em(f"{'if' if first else '} else if'} ({c}) {{")
            first = False
            self.block(stmts)
        if s.other is not None:
            if first:
                em("{")
            else:
                em("} else {")
            self.block(s.other)
            em("}")
        elif not first:
            em("}")

    def when_term(self, kind, sv, ob):
        if ob.kind == 'ANY':
            return '1'
        if kind == 'B':
            if ob.kind == 'TRUE':
                return '1' if sv else '0'
            if ob.kind == 'FALSE':
                return '0' if sv else '1'
            if ob.kind == 'COND':
                c = self.cond(ob.a)
                if ob.neg:
                    c = f"!{c}"
                return c if sv else f"!{c}"
            # value object under TRUE subject: treat as condition-name or error
            if ob.kind == 'VALUE' and isinstance(ob.a, DataRef):
                c = self.cond(MaybeCond(ob.a, None, None))
                return c if sv else f"!{c}"
            raise CompileError("WHEN object must be a condition", self.cur_loc)
        if kind == 'C':
            if ob.kind == 'TRUE':
                return sv
            if ob.kind == 'FALSE':
                return f"!{sv}"
            raise CompileError("WHEN object must be TRUE or FALSE", self.cur_loc)
        # value subject
        if ob.kind in ('TRUE', 'FALSE'):
            raise CompileError("TRUE/FALSE object requires a conditional subject", self.cur_loc)
        if ob.kind == 'COND':
            c = self.cond(ob.a)
            return f"!{c}" if ob.neg else c
        if ob.kind == 'VALUE':
            c = self.rel(sv, 'EQ', ob.a)
        else:
            c = f"({self.rel(sv, 'GE', ob.a)} && {self.rel(sv, 'LE', ob.b)})"
        return f"!{c}" if ob.neg else c

    # ---------------------------------------------------------------- PERFORM
    def perform_call(self, first, last):
        em = self.em
        t1 = self.resolve_proc(first)
        t2 = self.resolve_proc(last) if last else t1
        ret = self.new_label('R')
        em(f"if (++frame_ptr == cob_frames + COB_STACK_SIZE) cob_perform_overflow({self.locstr()});")
        em(f"frame_ptr->perform_through = {t2.id};")
        em(f"frame_ptr->return_address = &&{ret};")
        em(f"goto {t1.label};")
        em.label(ret)
        em("frame_ptr--;")
        if self.seg_tracking and self.cur_section is not None:
            em(f"cob_seg = {self.cur_section.segment};")

    def g_Perform(self, s):
        em = self.em
        brk = self.new_label('B')
        cont = self.new_label('C')
        inline = s.body is not None
        if inline:
            self.inline_stack.append((brk, cont))

        def body():
            if inline:
                self.stmts(s.body)
            else:
                self.perform_call(s.first, s.last)

        if s.varying:
            self.gen_varying(s, body, brk, cont)
        elif s.until is not None:
            em("for (;;) {")
            em.ind += 1
            if not s.test_after:
                em(f"if ({self.cond(s.until)}) break;")
            body()
            em.label(cont)
            if s.test_after:
                em(f"if ({self.cond(s.until)}) break;")
            em.ind -= 1
            em("}")
        elif s.times is not None:
            cnt = self.sym('cob_n')
            self.local(f"cob_s64 {cnt};")
            em(f"for ({cnt} = {self.int_expr(s.times)}; {cnt} > 0; {cnt}--) {{")
            em.ind += 1
            body()
            em.label(cont)
            em.ind -= 1
            em("}")
        else:
            body()
            em.label(cont)
        em.label(brk)
        if inline:
            self.inline_stack.pop()

    def set_var(self, var, val):
        it = self.resolve(var)
        if isinstance(it, IndexName):
            return f"{it.cname} = (int){self.int_expr(val)};"
        self.check_numeric_target(var)
        fk = self.fast_kind(var)
        fv = self.fast_value(val, self.fast_scale(fk)) if (fk is not None and self.is_numeric(val)) else None
        if fk is not None and fv is not None:
            return self.fast_set(fk, fv[0], fv[1], fv[2])
        return f"cob_d_set({self.field(var)}, {self.dec(val)}, 0);"

    def aug_var(self, var, by):
        it = self.resolve(var)
        if isinstance(it, IndexName):
            return f"{it.cname} += (int){self.int_expr(by)};"
        fk = self.fast_kind(var)
        fv = self.fast_value(BinOp('+', var, by), self.fast_scale(fk)) if (fk is not None and self.is_numeric(by)) else None
        if fk is not None and fv is not None:
            return self.fast_set(fk, fv[0], fv[1], fv[2])
        f = self.field(var)
        return f"cob_d_set({f}, cob_d_add(cob_d_get({f}), {self.dec(by)}), 0);"

    def gen_varying(self, s, body, brk, cont):
        em = self.em
        vs = s.varying
        n = len(vs)
        labels = [self.new_label('V') for _ in vs]
        for v in vs:
            em(self.set_var(v.var, v.frm))
        if not s.test_after:
            em.label(labels[0])
            em(f"if ({self.cond(vs[0].until)}) goto {brk};")
            for k in range(1, n):
                em.label(labels[k])
                em(f"if ({self.cond(vs[k].until)}) {{")
                em.ind += 1
                em(self.aug_var(vs[k - 1].var, vs[k - 1].by))
                em(self.set_var(vs[k].var, vs[k].frm))
                em(f"goto {labels[k - 1]};")
                em.ind -= 1
                em("}")
            body()
            em.label(cont)
            em(self.aug_var(vs[n - 1].var, vs[n - 1].by))
            em(f"goto {labels[n - 1]};")
        else:
            top = labels[0]
            em.label(top)
            body()
            em.label(cont)
            for k in range(n - 1, -1, -1):
                em(f"if (!{self.cond(vs[k].until)}) {{")
                em.ind += 1
                em(self.aug_var(vs[k].var, vs[k].by))
                for j in range(k + 1, n):
                    em(self.set_var(vs[j].var, vs[j].frm))
                em(f"goto {top};")
                em.ind -= 1
                em("}")

    # ---------------------------------------------------------------- control flow
    def proc_label(self, pr):
        return self.resolve_proc(pr).label

    def g_GoTo(self, s):
        em = self.em
        if s.depending is None:
            var = self.alter_paras.get(id(self.cur_para))
            if var is not None:
                if s.targets:
                    em(f"goto *({var} ? {var} : &&{self.proc_label(s.targets[0])});")
                else:
                    em(f"if (!{var}) cob_fatal(\"%s: GO TO has not been ALTERed\", {self.locstr()});")
                    em(f"goto *{var};")
                return
            if not s.targets:
                raise CompileError("GO TO without a target is only allowed in a paragraph named in an ALTER statement", s.loc)
            if len(s.targets) != 1:
                raise CompileError("GO TO with several targets requires DEPENDING ON", s.loc)
            em(f"goto {self.proc_label(s.targets[0])};")
            return
        em(f"switch ({self.int_expr(s.depending)}) {{")
        for i, t in enumerate(s.targets):
            em(f"case {i + 1}: goto {self.proc_label(t)};")
        em("default: break;")
        em("}")

    def g_Alter(self, s):
        for p1, p2 in s.pairs:
            var = self.alter_paras[id(self.resolve_proc(p1))]
            self.em(f"{var} = &&{self.proc_label(p2)};")

    def g_StopRun(self, s):
        if s.returning is not None:
            self.em(f"cob_stop_run((int){self.int_expr(s.returning)});")
        else:
            self.em("cob_stop_run((int)cob_get_int(&cob_return_code));")

    def g_GoBack(self, s):
        if s.returning is not None:
            self.em(f"cob_set_int(&cob_return_code, {self.int_expr(s.returning)});")
        self.em("goto L_exit;")

    def g_Exit(self, s):
        em = self.em
        if s.kind == '':
            em(";")
        elif s.kind == 'PROGRAM':
            em("if (cob_argc >= 0) goto L_exit;")
        elif s.kind in ('PERFORM', 'CYCLE'):
            if not self.inline_stack:
                raise CompileError(f"EXIT PERFORM{' CYCLE' if s.kind == 'CYCLE' else ''} outside of an inline PERFORM", s.loc)
            brk, cont = self.inline_stack[-1]
            em(f"goto {brk if s.kind == 'PERFORM' else cont};")
        elif s.kind == 'PARAGRAPH':
            em(f"goto {self.cur_para.label}_end;")
        elif s.kind == 'SECTION':
            em(f"goto {self.cur_section.label}_end;")

    def g_StmtBlock(self, s):
        self.stmts(s.stmts)

    def g_Continue(self, s):
        self.em(";")

    def g_NextSentence(self, s):
        self.em(f"goto {self.cur_sentence_end};")

    # ---------------------------------------------------------------- STRING / UNSTRING / INSPECT
    def g_StringStmt(self, s):
        em = self.em
        self.check_receiving(s.into)
        em("{")
        em.ind += 1
        ptr = self.field(s.pointer) if s.pointer else 'NULL'
        em(f"cob_string_init({self.field(s.into)}, {ptr});")
        last = object()
        for src, d in s.sources:
            if d is not last:
                em(f"cob_string_delimited({'NULL' if d == 'SIZE' else self.field(d)});")
                last = d
            em(f"cob_string_append({self.field(src)});")
        em("int cob_ovf = cob_string_finish();")
        self.handlers('cob_ovf', s.on_overflow, s.not_on_overflow)
        em("(void)cob_ovf;")
        em.ind -= 1
        em("}")

    def g_Unstring(self, s):
        em = self.em
        em("{")
        em.ind += 1
        ptr = self.field(s.pointer) if s.pointer else 'NULL'
        em(f"cob_unstring_init({self.field(s.src)}, {ptr});")
        for al, d in s.delims:
            em(f"cob_unstring_delim({self.field(d)}, {1 if al else 0});")
        for ui in s.intos:
            self.check_receiving(ui.target)
            dl = self.field(ui.delim_in) if ui.delim_in else 'NULL'
            cn = self.field(ui.count_in) if ui.count_in else 'NULL'
            em(f"cob_unstring_into({self.field(ui.target)}, {dl}, {cn});")
        if s.tallying:
            em(f"cob_unstring_tallying({self.field(s.tallying)});")
        em("int cob_ovf = cob_unstring_finish();")
        self.handlers('cob_ovf', s.on_overflow, s.not_on_overflow)
        em("(void)cob_ovf;")
        em.ind -= 1
        em("}")

    def g_Inspect(self, s):
        em = self.em
        modes = {'CHARACTERS': 'COB_INSP_CHARACTERS', 'ALL': 'COB_INSP_ALL', 'LEADING': 'COB_INSP_LEADING',
                 'FIRST': 'COB_INSP_FIRST'}
        em("{")
        em.ind += 1
        t = self.field(s.target)
        if s.tallying or s.replacing:
            em(f"cob_inspect_start({t});")
            for op in s.tallying:
                pat = self.field(op.pattern) if op.pattern is not None else 'NULL'
                b = self.field(op.region.before) if op.region.before is not None else 'NULL'
                a = self.field(op.region.after) if op.region.after is not None else 'NULL'
                em(f"cob_inspect_tally({self.field(op.counter)}, {modes[op.mode]}, {pat}, {b}, {a});")
            for op in s.replacing:
                pat = self.field(op.pattern) if op.pattern is not None else 'NULL'
                b = self.field(op.region.before) if op.region.before is not None else 'NULL'
                a = self.field(op.region.after) if op.region.after is not None else 'NULL'
                em(f"cob_inspect_replace({modes[op.mode]}, {pat}, {self.field(op.by)}, {b}, {a});")
            em("cob_inspect_end();")
        if s.converting:
            fr, to, reg = s.converting
            b = self.field(reg.before) if reg.before is not None else 'NULL'
            a = self.field(reg.after) if reg.after is not None else 'NULL'
            em(f"cob_inspect_converting({t}, {self.field(fr)}, {self.field(to)}, {b}, {a});")
        em.ind -= 1
        em("}")

    # ---------------------------------------------------------------- INITIALIZE
    def g_Initialize(self, s):
        em = self.em
        for ref in s.targets:
            it = self.check_receiving(ref)
            if not isinstance(it, DataItem):
                continue
            em("{")
            em.ind += 1
            whole_table = bool(it.occurs) and len(ref.subs) < len(it.occurs_chain())
            pref = ref
            if whole_table:
                pref = DataRef(ref.name, ref.quals, list(ref.subs) + [NumLit('1', '1', 0, False)], None, ref.loc)
                pref.item = it
            em(f"unsigned char *cob_ib = {self.data_ptr(pref)};")
            self.init_spec = s
            self.init_item(it, 'cob_ib', '0', 'initialize', root=True, root_occurs=whole_table)
            em.ind -= 1
            em("}")

    def init_tree(self, root, mode):
        self.init_spec = None
        if root.level == 66:
            return
        self.init_item(root, root.storage, str(root.offset), mode, root=True, root_occurs=bool(root.occurs))

    def init_item(self, it, base, off, mode, root=False, root_occurs=False):
        em = self.em
        if it.level in (66, 88):
            return
        if not root and it.redefines is not None:
            return
        spec = self.init_spec
        if not root and it.is_filler and mode == 'initialize' and not (spec and spec.with_filler):
            return
        if it.occurs and (not root or root_occurs):
            v = self.sym('cob_i')
            self.local(f"cob_s64 {v};")
            em(f"for ({v} = 0; {v} < {it.occurs.max}; {v}++) {{")
            em.ind += 1
            self.init_one(it, base, f"{off} + {v} * {it.size}", mode)
            em.ind -= 1
            em("}")
        else:
            self.init_one(it, base, off, mode)

    def init_one(self, it, base, off, mode):
        em = self.em
        spec = self.init_spec
        f = f"CF({base} + {off}, {it.size}, &{self.item_attr(it)})"
        if it.children:
            if mode == 'init' and it.value is not None:
                em(self.value_move(it.value, f, it))
                return
            if mode == 'initialize' and spec and spec.to_value and it.value is not None:
                em(f"cob_move({self.field(it.value)}, {f});")
                return
            for c in it.children:
                if c.level in (66, 88):
                    continue
                self.init_item(c, base, f"{off} + {c.offset - it.offset}", mode)
            return
        t = it.type
        if t in (T_INDEX, T_POINTER):
            if mode == 'init':
                em(f"memset({base} + {off}, 0, {it.size});")
            return
        cat = it.category()
        if mode == 'init':
            if it.value is not None:
                em(self.value_move(it.value, f, it))
                return
        elif spec is not None:
            if spec.to_value and it.value is not None:
                em(f"cob_move({self.field(it.value)}, {f});")
                return
            if spec.replacing:
                for rc, rv in spec.replacing:
                    if rc == cat or (rc == 'ALPHANUMERIC' and cat == 'ALPHANUMERIC') or \
                            (rc == 'NATIONAL' and cat == 'ALPHANUMERIC'):
                        em(f"cob_move({self.field(rv)}, {f});")
                        return
                if not spec.to_default:
                    return
            elif spec.to_value and not spec.to_default:
                return
        if cat in ('NUMERIC', 'NUMERIC-EDITED'):
            if t == T_NUM_DISPLAY and not (it.flags & F_SIGN_SEP):
                em(f"memset({base} + {off}, '0', {it.size});")
            else:
                em(f"cob_move(&cob_fig_zero, {f});")
        elif t == T_ALNUM_EDITED:
            em(f"cob_move(&cob_fig_space, {f});")
        else:
            em(f"memset({base} + {off}, ' ', {it.size});")

    def value_move(self, v, f, it):
        """VALUE clause: literals are placed without editing/justification."""
        if isinstance(v, NumLit) or (isinstance(v, Figurative) and v.kind == 'ZERO' and
                                     (it.type in NUMERIC_TYPES or it.type == T_NUM_EDITED)):
            return f"cob_move({self.field(v)}, {f});"
        if isinstance(v, AllLit) and v.is_zero and (it.type in NUMERIC_TYPES or it.type == T_NUM_EDITED):
            return f"cob_move({self.field(v)}, {f});"
        if it.type in (T_NUM_PACKED, T_NUM_BINARY, T_NUM_COMP5, T_NUM_FLOAT, T_NUM_DOUBLE, T_INDEX):
            return f"cob_move({self.field(v)}, {f});"
        return f"cob_move_raw({self.field(v)}, {f});"

    # ---------------------------------------------------------------- SET
    def g_SetStmt(self, s):
        em = self.em
        if s.kind == 'SWITCH':
            for t in s.targets:
                n = self.prog.switches.get(t.name)
                if n is None:
                    raise CompileError(f"'{t.name}' is not a switch mnemonic", t.loc)
                em(f"cob_switch_set({n}, {1 if s.value else 0});")
            return
        if s.kind in ('TRUE', 'FALSE'):
            for t in s.targets:
                c = self.resolve(t)
                if not (isinstance(c, DataItem) and c.level == 88):
                    raise CompileError(f"'{t.name}' is not a condition-name", t.loc)
                var = c.parent
                vref = DataRef(var.name or 'FILLER', [], t.subs, None, t.loc)
                vref.item = var
                if s.kind == 'TRUE':
                    v = c.values[0][0]
                else:
                    if c.false_value is None:
                        raise CompileError(f"condition-name '{t.name}' has no WHEN SET TO FALSE value", t.loc)
                    v = c.false_value
                em(f"cob_move({self.field(v)}, {self.field(vref)});")
            return
        if s.kind == 'TO':
            for t in s.targets:
                it = self.check_receiving(t)
                if isinstance(it, IndexName):
                    em(f"{it.cname} = (int){self.int_expr(s.value)};")
                else:
                    if it.type not in NUMERIC_TYPES:
                        raise CompileError(f"SET target '{t.name}' must be an index or numeric item", t.loc)
                    em(f"cob_d_set({self.field(t)}, {self.dec(s.value)}, 0);")
            return
        for t in s.targets:
            it = self.check_receiving(t)
            op = '-' if s.down else '+'
            if isinstance(it, IndexName):
                em(f"{it.cname} {op}= (int){self.int_expr(s.value)};")
            else:
                f = self.field(t)
                fn = 'sub' if s.down else 'add'
                em(f"cob_d_set({f}, cob_d_{fn}(cob_d_get({f}), {self.dec(s.value)}), 0);")

    # ---------------------------------------------------------------- SEARCH
    def g_Search(self, s):
        em = self.em
        tbl = self.resolve(s.table)
        if not (isinstance(tbl, DataItem) and tbl.occurs):
            raise CompileError(f"'{s.table.name}' is not a table (no OCCURS)", s.loc)
        if not tbl.occurs.indexes and not s.varying:
            raise CompileError(f"SEARCH requires an INDEXED BY index for '{tbl.name}'", s.loc)
        ix = None
        for nm, _ in tbl.occurs.indexes:
            for cand in self.ctx.names.get(nm, []):
                if isinstance(cand, IndexName) and cand.table is tbl:
                    ix = cand
                    break
            break
        vary = None
        if s.varying is not None:
            vi = self.resolve(s.varying)
            if isinstance(vi, IndexName) and vi.table is tbl:
                ix = vi
            else:
                vary = s.varying
        if ix is None:
            raise CompileError("SEARCH requires an index", s.loc)
        if tbl.occurs.depending is not None:
            mx = self.int_expr(tbl.occurs.depending)
        else:
            mx = str(tbl.occurs.max)
        end = self.new_label('S')
        if not s.all:
            em("for (;;) {")
            em.ind += 1
            em(f"if ({ix.cname} < 1 || {ix.cname} > {mx}) {{")
            self.block(s.at_end or [])
            em(f"goto {end};")
            em("}")
            for w in s.whens:
                em(f"if ({self.cond(w.cond)}) {{")
                self.block(w.stmts)
                em(f"goto {end};")
                em("}")
            em(f"{ix.cname}++;")
            if vary is not None:
                vit = self.resolve(vary)
                if isinstance(vit, IndexName):
                    em(f"{vit.cname}++;")
                else:
                    f = self.field(vary)
                    em(f"cob_d_set({f}, cob_d_add(cob_d_get({f}), cob_d_int(1)), 0);")
            em.ind -= 1
            em("}")
            em.label(end)
            return
        # SEARCH ALL: binary search on keys
        w = s.whens[0]
        if len(s.whens) != 1:
            raise CompileError("SEARCH ALL allows only one WHEN", s.loc)
        conds = []

        def flatten(c):
            if isinstance(c, And):
                flatten(c.a)
                flatten(c.b)
            else:
                conds.append(c)
        flatten(w.cond)
        keys = tbl.occurs.keys
        if not keys:
            raise CompileError(f"SEARCH ALL requires KEY clause on '{tbl.name}'", s.loc)
        keymap = {}
        for c in conds:
            pair = self.search_all_term(c, tbl, ix)
            if pair is None:
                raise CompileError("SEARCH ALL condition must be key = value [AND ...]", s.loc)
            keymap[pair[0].name] = pair
        order = []
        for desc, kname in keys:
            if kname in keymap:
                order.append((desc, keymap[kname]))
            else:
                break
        if len(order) != len(keymap):
            raise CompileError("SEARCH ALL keys must be tested in KEY clause order", s.loc)
        lo = self.sym('cob_lo')
        hi = self.sym('cob_hi')
        self.local(f"cob_s64 {lo}, {hi};")
        em(f"{lo} = 1; {hi} = {mx};")
        found = self.new_label('F')
        em(f"while ({lo} <= {hi}) {{")
        em.ind += 1
        em(f"{ix.cname} = (int)(({lo} + {hi}) / 2);")
        em("int cob_c = 0;")
        for desc, (kitem, kref, val) in order:
            cmpx = f"cob_cmp({self.field(kref)}, {self.field(val)})"
            if self.is_numeric(kref) and self.is_numeric(val):
                cmpx = f"cob_d_cmp({self.dec(kref)}, {self.dec(val)})"
            em(f"if (cob_c == 0) cob_c = {'-' if desc else ''}{cmpx};")
        em(f"if (cob_c == 0) goto {found};")
        em(f"if (cob_c < 0) {lo} = {ix.cname} + 1; else {hi} = {ix.cname} - 1;")
        em.ind -= 1
        em("}")
        self.stmts(s.at_end or [])
        em(f"goto {end};")
        em.label(found)
        self.stmts(w.stmts)
        em.label(end)

    def search_all_term(self, c, tbl, ix):
        if isinstance(c, MaybeCond) and isinstance(c.operand, DataRef):
            it = self.resolve(c.operand)
            if isinstance(it, DataItem) and it.level == 88:
                c = CondRef(c.operand)
        if isinstance(c, CondRef):
            cn = self.resolve(c.ref)
            var = cn.parent
            vref = DataRef(var.name, [], c.ref.subs, None, c.ref.loc)
            vref.item = var
            return (var, vref, cn.values[0][0])
        if isinstance(c, Rel) and c.op == 'EQ':
            for a, b in ((c.left, c.right), (c.right, c.left)):
                if isinstance(a, DataRef):
                    it = self.resolve(a)
                    if isinstance(it, DataItem) and tbl in [it] + list(it.ancestors()):
                        return (it, a, b)
        return None

    # ---------------------------------------------------------------- CALL
    def g_Call(self, s):
        em = self.em
        em("{")
        em.ind += 1
        n = len(s.args)
        frees = []
        em(f"unsigned char *cob_av[{max(n, 1)}];")
        for i, a in enumerate(s.args):
            if a.value == 'OMITTED':
                em(f"cob_av[{i}] = NULL;")
                continue
            v = a.value
            if a.mode == 'REFERENCE' and isinstance(v, DataRef):
                em(f"cob_av[{i}] = ({self.field(v)})->data;")
            elif a.mode == 'VALUE' and self.is_numeric(v):
                em(f"int32_t cob_vi{i} = (int32_t){self.int_expr(v)};")
                em(f"cob_av[{i}] = (unsigned char *)&cob_vi{i};")
            else:
                f = self.field(v)
                em(f"const cob_field *cob_cf{i} = {f};")
                em(f"unsigned char *cob_cb{i} = cob_malloc(cob_cf{i}->size + 1);")
                em(f"memcpy(cob_cb{i}, cob_cf{i}->data, cob_cf{i}->size);")
                em(f"cob_av[{i}] = cob_cb{i};")
                frees.append(f"free(cob_cb{i});")
        if isinstance(s.prog, StrLit):
            name = s.prog.value.decode('latin-1').strip()
            if name.upper() == 'SYSTEM':
                if not s.args:
                    raise CompileError("CALL 'SYSTEM' requires an argument", s.loc)
                em(f"cob_call_system({self.field(s.args[0].value)});")
                if s.not_on_exc:
                    self.block(s.not_on_exc)
                em.ind -= 1
                em("}")
                return
            sym = self.prog_syms.get(name.upper())
            fn = sym if sym else f"cob_resolve_name({c_string(name)})"
        else:
            fn = f"cob_resolve({self.field(s.prog)})"
        em(f"cob_prog_fn cob_fn = {fn};")
        em("if (!cob_fn) {")
        if s.on_exc is not None:
            self.block(s.on_exc)
        else:
            if isinstance(s.prog, StrLit):
                em(f"\tcob_fatal(\"%s: module '%s' not found\", {self.locstr()}, {c_string(s.prog.value)});")
            else:
                em(f"\tcob_fatal(\"%s: called program not found\", {self.locstr()});")
        em("} else {")
        em.ind += 1
        em(f"int cob_rc = cob_fn({n}, cob_av);")
        em(f"cob_set_collating({self.ctx.coll or 'NULL'});")
        if s.returning is not None:
            em(f"cob_set_int({self.field(s.returning)}, cob_rc);")
        else:
            em("cob_set_int(&cob_return_code, cob_rc);")
        for fr in frees:
            em(fr)
        if s.not_on_exc is not None:
            self.stmts(s.not_on_exc)
        em.ind -= 1
        em("}")
        em.ind -= 1
        em("}")

    def g_Cancel(self, s):
        for p in s.progs:
            if isinstance(p, StrLit):
                self.em(f"cob_cancel_name({c_string(p.value.decode('latin-1').strip())});")
            else:
                self.em(f"cob_cancel({self.field(p)});")
        if not s.progs:
            self.em(";")

    # ---------------------------------------------------------------- file I/O
    def io_result(self, fi, call, at_end=None, not_at_end=None, invalid=None, not_invalid=None,
                  on_ok=None, eop=None, not_eop=None):
        em = self.em
        em("{")
        em.ind += 1
        if fi.external:
            for line in self.file_bindings(fi):
                em(line)
        em(f"int cob_io = {call};")
        if on_ok:
            em("if (cob_io == COB_IO_OK) {")
            em.ind += 1
            for line in on_ok:
                em(line)
            em.ind -= 1
            em("}")
        branches = []
        if at_end is not None:
            branches.append(('COB_IO_ATEND', at_end))
        if invalid is not None:
            branches.append(('COB_IO_INVALID', invalid))
        first = True
        for code, stmts in branches:
            em(f"{'if' if first else '} else if'} (cob_io == {code}) {{")
            first = False
            self.block(stmts)
        em(f"{'if' if first else '} else if'} (cob_io != COB_IO_OK) {{")
        em.ind += 1
        self.emit_use(fi)
        em.ind -= 1
        ok_stmts = not_at_end if not_at_end is not None else not_invalid
        if eop is not None or not_eop is not None:
            em(f"}} else if ({fi.sym}.eop) {{")
            self.block(eop or [])
            if not_eop is not None:
                em("} else {")
                self.block(not_eop)
        elif ok_stmts is not None:
            em("} else {")
            self.block(ok_stmts)
        em("}")
        em.ind -= 1
        em("}")

    def into_field(self, e):
        if isinstance(e, DataRef):
            return self.ref_field(e, True)
        return self.field(e)

    def cur_rec_size(self, fi):
        return f"{fi.sym}.cur_size" if getattr(fi, 'variable', False) else str(fi.size)

    def emit_use(self, fi):
        """Select the applicable USE AFTER ERROR procedure: file-specific, then by
        open mode, then GLOBAL procedures of containing programs (innermost first)."""
        em = self.em
        P = self.prog
        name = fi.fd.name
        ent = P._decl_file.get(name)
        if ent is not None and ent[1] is fi:
            self.perform_section(ent[0])
            return
        conds = []
        for mode, sec in P._decl_mode.items():
            conds.append((mode, None, sec))
        A = P.parent
        while A is not None:
            ent = getattr(A, '_decl_file', {}).get(name)
            if ent is not None and ent[1] is fi and ent[0].use_global:
                conds.append((None, A, ent[0]))
                break
            for mode, sec in getattr(A, '_decl_mode', {}).items():
                if sec.use_global:
                    conds.append((mode, A, sec))
            A = A.parent
        unhandled = f"cob_io_unhandled(&{fi.sym}, cob_io, {self.locstr()});"

        def act(owner, sec):
            if owner is None:
                self.perform_section(sec)
            else:
                em(f"cob_decl_which = {sec.id};")
                em(f"{self.prog_syms[owner.name.upper()]}(COB_DECL_ENTRY, NULL);")
                em(f"cob_set_collating({self.ctx.coll or 'NULL'});")
        first = True
        for mode, owner, sec in conds:
            if mode is None:
                if first:
                    act(owner, sec)
                    return
                em("} else {")
                em.ind += 1
                act(owner, sec)
                em.ind -= 1
                em("}")
                return
            em(f"{'if' if first else '} else if'} ({fi.sym}.use_mode == {OPEN_MODE[mode]}) {{")
            first = False
            em.ind += 1
            act(owner, sec)
            em.ind -= 1
        if first:
            em(unhandled)
        else:
            em("} else {")
            em.ind += 1
            em(unhandled)
            em.ind -= 1
            em("}")

    def perform_section(self, sec):
        em = self.em
        ret = self.new_label('R')
        em(f"if (++frame_ptr == cob_frames + COB_STACK_SIZE) cob_perform_overflow({self.locstr()});")
        em(f"frame_ptr->perform_through = {sec.id};")
        em(f"frame_ptr->return_address = &&{ret};")
        em(f"goto {sec.label};")
        em.label(ret)
        em("frame_ptr--;")
        if getattr(self, 'seg_tracking', False) and self.cur_section is not None:
            em(f"cob_seg = {self.cur_section.segment};")

    def g_Open(self, s):
        for mode, files in s.modes:
            for fn in files:
                fi = self.file_info(fn, s.loc)
                if fi.is_sort:
                    raise CompileError(f"cannot OPEN sort file '{fn}'", s.loc)
                self.io_result(fi, f"cob_open(&{fi.sym}, {OPEN_MODE[mode]})")

    def g_Close(self, s):
        for i, fn in enumerate(s.files):
            fi = self.file_info(fn, s.loc)
            opt = s.opts[i] if i < len(s.opts) else 0
            self.io_result(fi, f"cob_close_opt(&{fi.sym}, {opt})")

    def record_of(self, ref):
        it = self.resolve(ref)
        fi = getattr(it, 'file', None)
        if fi is None or it.level != 1:
            raise CompileError(f"'{ref.name}' is not a record of a file", ref.loc)
        return it, fi

    def key_index(self, fi, ref):
        it = self.resolve(ref)
        for i, (k, _) in enumerate(fi.keys):
            if k is it:
                return i, k.size
        for i, (k, _) in enumerate(fi.keys):
            if getattr(it, 'file', None) is fi and it.offset == k.offset and it.size <= k.size:
                return i, it.size
        raise CompileError(f"'{ref.name}' is not a key of file '{fi.fc.name}'", ref.loc)

    def g_Read(self, s):
        fi = self.file_info(s.file, s.loc)
        next_ = 1 if s.direction == 'NEXT' or fi.fc.access == 'SEQUENTIAL' else 0
        if s.direction == 'PREVIOUS':
            raise CompileError("READ PREVIOUS is not supported", s.loc)
        if fi.fc.organization == 'LINE SEQUENTIAL' or fi.fc.organization == 'SEQUENTIAL':
            next_ = 1
        kidx = -1
        if s.key is not None:
            kidx, _ = self.key_index(fi, s.key)
        on_ok = []
        if s.into is not None:
            self.check_receiving(s.into)
            on_ok.append(f"cob_move(CF({fi.buf}, {self.cur_rec_size(fi)}, &cob_attr_group), {self.into_field(s.into)});")
        self.io_result(fi, f"cob_read(&{fi.sym}, {next_}, {kidx})", s.at_end, s.not_at_end, s.invalid,
                       s.not_invalid, on_ok)

    def g_Write(self, s):
        em = self.em
        rec, fi = self.record_of(s.record)
        if fi.is_sort:
            raise CompileError("use RELEASE for sort files", s.loc)
        if s.frm is not None:
            em(f"cob_move({self.field(s.frm)}, {self.field(s.record)});")
        when = {'': 'COB_ADV_NONE', 'BEFORE': 'COB_ADV_BEFORE', 'AFTER': 'COB_ADV_AFTER'}[s.adv_when]
        if s.adv_lines == 'PAGE':
            lines = 'COB_ADV_PAGE'
        elif s.adv_lines is None:
            lines = '1'
        else:
            lines = f"(int){self.int_expr(s.adv_lines)}"
        size = self.size_expr(rec)
        self.io_result(fi, f"cob_write(&{fi.sym}, {size}, {when}, {lines})", None, None, s.invalid,
                       s.not_invalid if s.not_invalid is not None else None,
                       eop=getattr(s, 'eop', None), not_eop=getattr(s, 'not_eop', None))

    def g_Rewrite(self, s):
        em = self.em
        rec, fi = self.record_of(s.record)
        if s.frm is not None:
            em(f"cob_move({self.field(s.frm)}, {self.field(s.record)});")
        self.io_result(fi, f"cob_rewrite(&{fi.sym}, {self.size_expr(rec)})", None, None, s.invalid, s.not_invalid)

    def g_Delete(self, s):
        fi = self.file_info(s.file, s.loc)
        self.io_result(fi, f"cob_delete(&{fi.sym})", None, None, s.invalid, s.not_invalid)

    def g_Start(self, s):
        fi = self.file_info(s.file, s.loc)
        kidx, klen = 0, 0
        if s.key is not None and fi.fc.organization != 'RELATIVE':
            kidx, klen = self.key_index(fi, s.key)
        op = START_OP.get(s.op, 0)
        self.io_result(fi, f"cob_start(&{fi.sym}, {op}, {kidx}, {klen})", None, None, s.invalid, s.not_invalid)

    # ---------------------------------------------------------------- SORT
    def sort_keys_array(self, keys, base_item, loc):
        parts = []
        for k in keys:
            it = self.resolve(k.ref)
            if not isinstance(it, DataItem):
                raise CompileError(f"invalid sort key '{k.ref.name}'", loc)
            off = it.offset - base_item.offset if base_item is not None else it.offset
            parts.append(f"{{{off}, {it.size}, &{self.item_attr(it)}, {1 if k.descending else 0}}}")
        s = self.sym('sk_')
        self.glob.append(f"static const cob_sort_key {s}[] = {{{', '.join(parts) or '{0, 0, NULL, 0}'}}};")
        return s

    def g_Sort(self, s):
        em = self.em
        if s.table is not None:
            tbl = self.resolve(s.table)
            if not (isinstance(tbl, DataItem) and tbl.occurs):
                raise CompileError(f"'{s.table.name}' is not a table or sort file", s.loc)
            keys = s.keys
            if not keys and tbl.occurs.keys:
                keys = []
                for desc, nm in tbl.occurs.keys:
                    r = DataRef(nm, [tbl.name] if tbl.name else [], [], None, s.loc)
                    keys.append(SortKey(desc, r))
            if keys:
                arr = self.sort_keys_array(keys, tbl, s.loc)
                nk = len(keys)
            else:
                a = self.attr(T_ALNUM)
                arr = self.sym('sk_')
                self.glob.append(f"static const cob_sort_key {arr}[] = {{{{0, {tbl.size}, &{a}, 0}}}};")
                nk = 1
            chain = tbl.occurs_chain()
            r2 = DataRef(s.table.name, s.table.quals, list(s.table.subs) + [NumLit('1', '1', 0, False)], None, s.table.loc)
            r2.item = tbl
            if len(r2.subs) != len(chain):
                raise CompileError("table SORT requires subscripts for outer tables", s.loc)
            n = self.int_expr(tbl.occurs.depending) if tbl.occurs.depending is not None else str(tbl.occurs.max)
            em(f"cob_table_sort({self.data_ptr(r2)}, (size_t)({n}), {tbl.size}, {nk}, {arr});")
            return
        sd = self.file_info(s.file, s.loc)
        if not sd.is_sort:
            raise CompileError(f"'{s.file}' is not a sort file (SD)", s.loc)
        rec = sd.fd.records[0] if sd.fd.records else None
        arr = self.sort_keys_array(s.keys, None, s.loc)
        em(f"cob_sort_init(&{sd.sym}, {len(s.keys)}, {arr}, {1 if s.duplicates else 0});")
        if s.using:
            for fn in s.using:
                fi = self.file_info(fn, s.loc)
                em(f"cob_sort_using(&{sd.sym}, &{fi.sym});")
        elif s.input_proc:
            self.perform_call(*s.input_proc)
        coll = self.ctx.coll
        if getattr(s, 'collating', None):
            res = self.collating_table(self.prog, s.collating, s.loc)
            coll = res[0] if res else None
        em(f"{sd.sym}.sort_coll = {coll or 'NULL'};")
        em(f"cob_sort_sort(&{sd.sym});")
        if s.giving:
            for fn in s.giving:
                fi = self.file_info(fn, s.loc)
                em(f"cob_sort_giving(&{sd.sym}, &{fi.sym});")
                if len(s.giving) > 1:
                    em(f"{sd.sym}.sret = 0;")
        elif s.output_proc:
            self.perform_call(*s.output_proc)
        em(f"cob_sort_end(&{sd.sym});")

    def g_Release(self, s):
        em = self.em
        rec, fi = self.record_of(s.record)
        if not fi.is_sort:
            raise CompileError("RELEASE requires a sort record", s.loc)
        if s.frm is not None:
            em(f"cob_move({self.field(s.frm)}, {self.field(s.record)});")
        em(f"cob_sort_release(&{fi.sym});")

    def g_Return(self, s):
        em = self.em
        fi = self.file_info(s.file, s.loc)
        em("{")
        em.ind += 1
        em(f"int cob_io = cob_sort_return(&{fi.sym});")
        if s.into is not None:
            em(f"if (cob_io == COB_IO_OK) cob_move(CF({fi.buf}, {fi.size}, &cob_attr_group), {self.into_field(s.into)});")
        em("if (cob_io != COB_IO_OK) {")
        self.block(s.at_end or [])
        if s.not_at_end is not None:
            em("} else {")
            self.block(s.not_at_end)
        em("}")
        em.ind -= 1
        em("}")
