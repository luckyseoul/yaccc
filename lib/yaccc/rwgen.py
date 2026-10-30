# SPDX-License-Identifier: MIT
"""Report Writer: the REPORT SECTION as tables for the runtime's RWCS
(runtime/cobrt_rw.c).

The tables have the shape GnuCOBOL 3.1.2's compiler gives them, because the
page and control-break behaviour its testsuite (and NIST) check depends on it:

- a print *line* for every 01 entry and every entry with a LINE clause. The 01
  lines form one chain (``next_line``) in source order; an 01's first LINE entry
  hangs from it (``first_line``) and its LINE entries chain from there;
- a list of report *items* per line: the entries under the line, in source
  order, up to the next LINE entry; a group item stays in the list (flagged)
  so PRESENT WHEN can drop everything under it, and an OCCURS item is listed
  once per occurrence;
- CONTROLs listed minor first, each with the CH / CF lines that name it;
- one hidden counter per SUM entry, in source order.

Group types, LINE, NEXT GROUP, COLUMN alignment and PRESENT are flag bits on
the lines and items (COB_RWF_* in runtime/cobrt.h). Expressions -- SOURCE,
SUM operands, PRESENT WHEN, CONTROL items -- become small callbacks.
docs/report-writer-page-model.md describes the model.
"""
from .data import DataItem, Picture, layout, resolve_types, Occurs, T_GROUP
from .errors import CompileError
from .nodes import DataRef, NumLit, StrLit, AllLit

# flag bits, as COB_RWF_* in runtime/cobrt.h
F_LINE = 1 << 0
F_LINE_PLUS = 1 << 1
F_COL_PLUS = 1 << 2
F_RESET_FINAL = 1 << 3
F_RH = 1 << 4
F_RF = 1 << 5
F_PH = 1 << 6
F_PF = 1 << 7
F_CH = 1 << 8
F_CH_FINAL = 1 << 9
F_CF = 1 << 10
F_CF_FINAL = 1 << 11
F_DE = 1 << 12
F_NG_LINE = 1 << 13
F_NG_PLUS = 1 << 14
F_NG_PAGE = 1 << 15
F_LINE_NP = 1 << 16
F_GI = 1 << 18
F_GROUP = 1 << 19
F_WHEN = 1 << 20
F_LEFT = 1 << 21
F_CENTER = 1 << 22
F_RIGHT = 1 << 23
F_PRESENT = 1 << 24
F_PAGE = 1 << 26
F_NEGATE = 1 << 28

TYPE_FLAG = {'RH': F_RH, 'PH': F_PH, 'DE': F_DE, 'PF': F_PF, 'RF': F_RF}
FOOTINGS = F_RF | F_CF | F_CF_FINAL


class RInfo:
    """One RD entry."""

    def __init__(self, rd):
        self.rd = rd
        self.name = rd.name
        self.sym = None
        self.file = None
        self.controls = []          # (DataRef, DataItem) in CONTROLS order (major first)
        self.code = rd.code or b''
        self.lc = self.pc = None    # LINE-COUNTER / PAGE-COUNTER items
        self.entries = []           # every entry, preorder
        self.lines = []             # entries that are print lines, preorder
        self.sums = []              # SUM entries, preorder


class RX:
    """Report Writer attributes of one entry."""

    def __init__(self):
        self.flags = 0
        self.line = 0
        self.col = 0
        self.cols = []              # COLUMN integer list
        self.step = 0
        self.ngl = 0
        self.ctl = None             # CONTROL name of a CH/CF, or PRESENT AFTER's
        self.when = None            # PRESENT / ABSENT WHEN condition
        self.counter = None         # hidden SUM counter item
        self.node = None            # line symbol, when the entry is a print line
        self.fields = []            # report item symbols (occurrences of an OCCURS item)
        self.snap = None            # snapshot field for an indexed SOURCE
        self.decl = 0


def _counter_pic(it):
    """The hidden SUM counter: two more digits than the item, 18 at most."""
    pic = it.pic
    digits = getattr(pic, 'digits', 0) if pic is not None else 0
    scale = getattr(pic, 'scale', 0) if pic is not None else 0
    if digits == 0:
        dig = 16
    elif digits > 17:
        dig = 18
    else:
        dig = digits + 2
    if scale > 0:
        ip = dig - scale
        if ip == 0:
            return f"SV9({scale})"
        if ip < 0:
            return f"SP({-ip})V9({scale})"
        return f"S9({ip})V9({scale})"
    return f"S9({dig})"


class ReportWriterGen:
    """Mixed into CodeGen."""

    # ------------------------------------------------------------ analysis
    def rw_analyze(self, prog):
        ctx = self.ctx
        ctx.reports = {}
        ctx.rw_groups = {}          # entry name -> (RInfo, entry)
        ctx.rw_init = []
        ctx.rw_trees = []
        for rd in prog.reports:
            if rd.name in ctx.reports:
                raise CompileError(f"duplicate report name '{rd.name}'", rd.loc)
            ri = RInfo(rd)
            ri.sym = self.sym('rep_')
            ctx.reports[rd.name] = ri
            files = [fi for fi in ctx.files.values() if rd.name in fi.fd.reports]
            if not files:
                raise CompileError(f"report '{rd.name}' is not named in the REPORT clause of an FD", rd.loc)
            ri.file = files[0]
            for ref in rd.controls:
                it = self.resolve(ref, allow_cond=False)
                if not isinstance(it, DataItem):
                    raise CompileError(f"CONTROL '{ref.name}' must be a data item", ref.loc)
                ri.controls.append((ref, it))
            ri.lc = self.rw_special(ri, 'LINE-COUNTER')
            ri.pc = self.rw_special(ri, 'PAGE-COUNTER')
            for g in rd.groups:
                if g.level != 1:
                    raise CompileError("report group description must have level 01", g.loc)
                self.rw_prepare(ri, g)
            for g in rd.groups:
                for it in g.walk():
                    ri.entries.append(it)
                    it.rx = RX()
                    if it.name:
                        ctx.rw_groups.setdefault(it.name, (ri, it))
            for it in ri.entries:
                self.rw_flags(ri, it)
            for it in ri.entries:
                # a second absolute LINE n among the entries of a group is
                # dropped: the entry joins the line before it
                x = it.rx
                if x.flags & F_LINE and not x.flags & F_LINE_PLUS and it.parent is not None \
                        and it.parent.children[0] is not it:
                    for c in it.parent.children:
                        if c is it:
                            break
                        if c.rx.flags & F_LINE and not c.rx.flags & F_LINE_PLUS and c.rx.line == x.line:
                            x.line = 0
                            x.flags &= ~F_LINE
            self.rw_columns(rd.groups)
            for it in ri.entries:
                if it.level == 1 or it.rx.flags & F_LINE:
                    ri.lines.append(it)
                if it.rw_sums:
                    ri.sums.append(it)
                    self.rw_counter(it)

    def rw_special(self, ri, name):
        sym = self.sym('rwc_')
        it = DataItem(1, name, ri.rd.loc)
        from .data import T_NUM_COMP5
        # an unsigned native 4-byte integer, as cobc declares them: DISPLAY
        # shows all 10 digits
        it.type = T_NUM_COMP5
        it.digits = 10
        it.flags = 0
        it.size = 4
        it.report_name = ri.name
        self.glob.append(f"static unsigned char {sym}_d[4];")
        self.glob.append(f"static cob_field {sym} = {{4, {sym}_d, &{self.item_attr(it)}}};")
        it.special = '&' + sym
        self.ctx.names.setdefault(name, []).append(it)
        return it

    def rw_prepare(self, ri, g):
        """Types, layout and storage of one report group."""
        for it in g.walk():
            if it.children:
                continue
            if it.pic is None:
                if isinstance(it.value, StrLit):
                    it.pic = Picture(f"X({max(len(it.value.value), 1)})", it.loc, '$', False)
                elif isinstance(it.value, NumLit):
                    it.pic = Picture(f"9({max(len(it.value.digits), 1)})", it.loc, '$', False)
                elif it.rw_column is not None or it.rw_source is not None or it.rw_sums:
                    raise CompileError("report item needs a PICTURE clause", it.loc)
            # the report's own LINE-COUNTER / PAGE-COUNTER when unqualified
            src = it.rw_source
            if isinstance(src, DataRef) and src.name in ('LINE-COUNTER', 'PAGE-COUNTER') and not src.quals:
                src.quals = [ri.name]
            if getattr(it, 'rw_columns', None) and not it.occurs:
                # COLUMN 1, 11, 21: one occurrence per column (an implicit OCCURS)
                oc = Occurs()
                oc.min = oc.max = len(it.rw_columns)
                oc.loc = it.loc
                it.occurs = oc
        resolve_types(g, self.opts)
        layout(g, 0)
        # report items have their own storage: a program can MOVE to them,
        # and an item without SOURCE or VALUE prints what it holds
        sym = self.sym('rwd_')
        self.glob.append(f"static unsigned char {sym}[{max(g.total_size(), 1)}];"
                         f" /* report group {g.name or 'FILLER'} */")
        for it in g.walk():
            it.storage = sym
            it.section = 'WS'
            it.record = g
            it.report_name = ri.name
        self.register_tree(g)
        self.ctx.rw_trees.append(g)

    def rw_flags(self, ri, it):
        x = it.rx
        fl = 0
        if it.rw_type is not None:
            kind, ctl = it.rw_type
            if kind in TYPE_FLAG:
                fl |= TYPE_FLAG[kind]
            elif kind == 'CH':
                fl |= F_CH_FINAL if ctl == 'FINAL' else F_CH
            elif kind == 'CF':
                fl |= F_CF_FINAL if ctl == 'FINAL' else F_CF
            if kind in ('CH', 'CF') and ctl != 'FINAL':
                if not any(ref.name == ctl for ref, _ in ri.controls):
                    raise CompileError(f"'{ctl}' is not a CONTROL of report '{ri.name}'", it.loc)
                x.ctl = ctl
        if it.rw_line is not None:
            kind, n = it.rw_line
            fl |= F_LINE
            x.line = n
            if kind == 'REL':
                fl |= F_LINE_PLUS
            elif kind in ('ABSNP', 'NP'):
                fl |= F_LINE_NP
        if it.rw_next_group is not None:
            kind, n = it.rw_next_group
            fl |= {'ABS': F_NG_LINE, 'REL': F_NG_PLUS, 'NP': F_NG_PAGE}[kind]
            x.ngl = n
        if it.rw_just:
            fl |= {'L': F_LEFT, 'R': F_RIGHT, 'C': F_CENTER}[it.rw_just]
        x.step = getattr(it, 'rw_step', 0) or 0
        col = it.rw_column
        if isinstance(col, tuple):
            n = col[1]
            if n != 0:
                first = it.parent is not None and it.parent.children and it.parent.children[0] is it
                if first:
                    # PLUS on the first item of a line counts from column 1
                    if x.step == 0:
                        x.step = n
                else:
                    fl |= F_COL_PLUS
            x.col = n
        elif isinstance(col, int):
            x.col = col
            x.cols = list(getattr(it, 'rw_columns', None) or [col])
        if it.rw_group_indicate:
            fl |= F_GI
        p = getattr(it, 'rw_present', None)
        if p is not None:
            what, absent = p
            fl |= F_PRESENT
            if absent:
                fl |= F_NEGATE
            if isinstance(what, tuple) and what and what[0] == 'AFTER':
                for name in what[1]:
                    if name == 'PAGE':
                        fl |= F_PAGE
                    else:
                        x.ctl = name
            else:
                x.when = what
        x.flags = fl

    def rw_columns(self, groups):
        """Columns of the items: a COLUMN PLUS, or no COLUMN at all, counts
        from where the item before it on the line ended."""
        pos = 1

        def walk(items):
            nonlocal pos
            for p in items:
                x = p.rx
                if p.level == 1 or x.flags & (F_LINE | F_LINE_PLUS | F_DE | F_RH | F_RF | F_PH | F_PF):
                    prev = pos = 1
                else:
                    if x.flags & F_COL_PLUS and x.col > 0:
                        x.col = pos + x.col - 1
                    elif x.col <= 0:
                        x.col = pos
                    prev = pos
                    if p.occurs and p.occurs.max > 1:
                        if x.step < p.size:
                            x.step = p.size
                        cols = x.cols
                        if cols and len(cols) >= p.occurs.max:
                            pos = cols[-1] + x.step
                        elif cols and len(cols) > 1:
                            pos = cols[-1] + x.step * (p.occurs.max - len(cols) + 1)
                        else:
                            pos = x.col + x.step * p.occurs.max
                    elif x.flags & F_RIGHT:
                        pos = x.col + 1
                        x.col = pos - p.size
                    elif x.flags & F_CENTER:
                        if p.size & 1:
                            x.col = x.col - (p.size - 1) // 2
                        else:
                            x.col = x.col - p.size // 2 + 1
                        pos = x.col + p.size // 2 + 1
                    else:
                        pos = x.col + p.size
                if p.children:
                    pos = prev
                    walk(p.children)
        walk(groups)

    def rw_counter(self, it):
        """The hidden counter a SUM entry accumulates in."""
        if it.category() not in ('NUMERIC', 'NUMERIC-EDITED'):
            raise CompileError("a SUM item must have a numeric or numeric-edited PICTURE", it.loc)
        ctr = DataItem(1, None, it.loc)
        ctr.pic = Picture(_counter_pic(it), it.loc, '$', False)
        resolve_types(ctr, self.opts)
        layout(ctr, 0)
        sym = self.sym('rsum_')
        self.glob.append(f"static unsigned char {sym}[{ctr.size}]; /* SUM {it.name or 'FILLER'} */")
        ctr.storage = sym
        ctr.section = 'WS'
        ctr.record = ctr
        ctr.offset = 0
        self.ctx.rw_init.append(ctr)
        it.rx.counter = ctr

    # ------------------------------------------------------------ generation
    def rw_item_field(self, it):
        ref = DataRef(it.name or '', [], [], None, it.loc)
        ref.item = it
        return self.field(ref)

    def rw_function(self, decl, body):
        from .codegen import Emitter
        saved = (getattr(self, 'em', None), getattr(self, 'fn_locals', []))
        self.em = Emitter()
        self.fn_locals = []
        body(self.em)
        lines, locs = self.em.lines, self.fn_locals
        self.em, self.fn_locals = saved
        self.funcs.append(decl)
        self.funcs.append('{')
        for d in sorted(set(locs)):
            self.funcs.append('\t' + d)
        self.funcs.extend(lines)
        self.funcs.append('}')
        self.funcs.append('')

    def rw_emit(self, prog):
        ctx = self.ctx
        for sec in prog.declaratives:
            if sec.use_reporting:
                tgt = ctx.rw_groups.get(sec.use_reporting) if ctx.reports else None
                if tgt is None:
                    raise CompileError(f"USE BEFORE REPORTING: '{sec.use_reporting}' is not a report group",
                                       sec.loc)
                tgt[1].rx.decl = sec.id
        for ri in ctx.reports.values():
            self.rw_emit_report(prog, ri)

    def rw_fields_of(self, ri, first, start):
        """The report items of a print line: `first` and what follows it, in
        source order, down to the next LINE entry."""
        out = []

        def walk(f, begin):
            sibs = f.parent.children if f.parent is not None else ri.rd.groups
            i = sibs.index(f)
            for j in range(i, len(sibs)):
                e = sibs[j]
                if not (begin and j == i) and e.rx.flags & F_LINE:
                    return
                if e.occurs and e.occurs.max > 1:
                    for k in range(1, e.occurs.max + 1):
                        out.append((e, k))
                    continue
                out.append((e, 0))
                if e.children:
                    walk(e.children[0], False)
        walk(first, start)
        return out

    def rw_emit_report(self, prog, ri):
        n = ri.sym
        rd = ri.rd
        cname = self.prog_syms[id(prog)]
        ctl_names = [ref.name for ref, _ in ri.controls]
        engine_ctl = list(reversed(ctl_names))          # minor first

        def ctl_index(name):
            return engine_ctl.index(name) if name in engine_ctl else -1

        # print lines
        for i, it in enumerate(ri.lines):
            it.rx.node = f"{n}_l{i}"
            self.glob.append(f"static cob_rwline {it.rx.node};")
        # nested LINE: an 01 LINE clause is dropped when its first entry has one
        for it in ri.lines:
            x = it.rx
            if x.flags & F_LINE and it.children and it.children[0].rx.flags & F_LINE:
                x.line = 0
                x.flags &= ~(F_LINE | F_LINE_PLUS)
        src_cases = []              # (id, C statement)
        snaps = []                  # (entry, snapshot symbol)
        fid = 0
        recsz = max(ri.file.size, 1)
        line_rows = []
        for it in ri.lines:
            x = it.rx
            # the line's items
            items = []
            if x.flags & F_LINE and it.children:
                items = self.rw_fields_of(ri, it.children[0], True)
            elif not it.children and x.flags & F_LINE:
                items = self.rw_fields_of(ri, it, True)
            syms = []
            for e, k in items:
                fid += 1
                fs = f"{n}_r{fid}"
                syms.append((fs, e, k, fid))
                self.glob.append(f"static cob_rwfld {fs};")
            for idx, (fs, e, k, fnum) in enumerate(syms):
                ex = e.rx
                nxt = f"&{syms[idx + 1][0]}" if idx + 1 < len(syms) else 'NULL'
                step = max(ex.step, e.size)
                ex.step = step
                col = ex.col if ex.col > 0 else 1
                if k > 1:
                    cols = ex.cols
                    if len(cols) >= k:
                        col = cols[k - 1]
                    elif len(cols) >= 2:
                        col = cols[-1] + step * (k - len(cols))
                    else:
                        col = col + step * (k - 1)
                flags = ex.flags
                if e.children:
                    flags |= F_GROUP
                if ex.when is not None:
                    flags |= F_WHEN
                if k > 0:
                    flags &= ~F_GROUP
                off = e.offset + (e.size * (k - 1) if k > 1 else 0)
                fsym = f"{n}_f{fnum}"
                self.glob.append(f"static cob_field {fsym} = {{{e.size}, {e.storage} + {off}, "
                                 f"&{self.item_attr(e)}}};")
                lit, litlen = 'NULL', 0
                src = 0
                if ex.counter is not None:
                    src = fnum
                    src_cases.append((fnum, 'ctr', ex.counter, fsym))
                elif e.rw_source is not None:
                    src = fnum
                    s = e.rw_source
                    if isinstance(s, DataRef) and (s.subs or s.refmod or
                                                   getattr(self.resolve(s), 'section', None) == 'LS'):
                        # an indexed or reference-modified SOURCE is taken when
                        # the GENERATE starts, not when the line prints
                        if ex.snap is None:
                            ex.snap = f"{n}_t{fnum}"
                            sz = max(self.rw_source_size(s), 1)
                            self.glob.append(f"static unsigned char {ex.snap}_d[{sz}];")
                            self.glob.append(f"static cob_field {ex.snap} = {{0, {ex.snap}_d, NULL}};")
                            snaps.append((e, ex.snap))
                        src_cases.append((fnum, 'snap', ex.snap, fsym))
                    else:
                        src_cases.append((fnum, 'ref', s, fsym))
                elif isinstance(e.value, (StrLit, NumLit, AllLit)):
                    if isinstance(e.value, StrLit):
                        b = e.value.value
                    elif isinstance(e.value, NumLit):
                        b = e.value.digits.encode()
                    else:
                        # ALL literal: its first character, the item's width
                        b = (e.value.value or b' ')[:1] * e.size
                    lit = self.c_bytes(b)
                    litlen = len(b)
                ctl = ctl_index(ex.ctl) if ex.ctl and flags & F_PRESENT else -1
                self.glob.append(
                    f"static cob_rwfld {fs} = {{{nxt}, &{fsym}, {src}, {ctl}, {lit}, {litlen}, "
                    f"0x{flags:x}u, {ex.line if e.rx.flags & F_LINE else 0}, {col}, {step}, {ex.ngl}, "
                    f"{e.level}, 0, 0, 0}};")
                ex.fields.append(fs)
                recsz = max(recsz, col - 1 + max(e.size, litlen))
            # links
            sibs = it.parent.children if it.parent is not None else rd.groups
            si = sibs.index(it)
            sister = 'NULL'
            if si + 1 < len(sibs):
                s = sibs[si + 1]
                if not (s.level > 1 and not s.rx.flags & F_LINE) and s.rx.node:
                    sister = f"&{s.rx.node}"
            child = 'NULL'
            if it.level == 1 and it.children and it.children[0].rx.flags & F_LINE and it.children[0].rx.node:
                child = f"&{it.children[0].rx.node}"
            fields = f"&{syms[0][0]}" if syms else 'NULL'
            ctl = ctl_index(x.ctl) if x.ctl and x.flags & (F_CH | F_CF) else -1
            line_rows.append(f"static cob_rwline {x.node} = {{{sister}, {child}, {fields}, {ctl}, "
                             f"{x.decl}, 0x{x.flags:x}u, {x.line}, {x.step}, {x.ngl}, 0}};")
        self.glob.extend(line_rows)

        # controls, minor first, each with its CH / CF lines (last first)
        ctl_rows = []
        for ci, name in enumerate(engine_ctl):
            refs = [it for it in ri.lines if it.rx.ctl == name and it.rx.flags & (F_CH | F_CF)]
            refs.reverse()
            rs = 'NULL'
            if refs:
                rs = f"{n}_cr{ci}"
                self.glob.append(f"static cob_rwline *const {rs}[] = {{"
                                 f"{', '.join('&' + r.rx.node for r in refs)}}};")
            ctl_rows.append(f"{{{ci + 1}, {len(refs)}, {rs}, NULL, NULL, 0, 0}}")
        if ctl_rows:
            self.glob.append(f"static cob_rwctl {n}_c[] = {{{', '.join(ctl_rows)}}};")

        # SUM counters, in source order
        counters = ri.sums
        by_item = {id(it): k for k, it in enumerate(counters)}
        ops_of = []
        for it in counters:
            ops = []
            sub = False
            for ops_list, _upon in it.rw_sums:
                for ref in ops_list:
                    tgt = self.resolve(ref) if isinstance(ref, DataRef) else None
                    if tgt is not None and id(tgt) in by_item:
                        ops.append(('ctr', by_item[id(tgt)]))
                        sub = True
                    else:
                        ops.append(('fld', ref))
            ops_of.append((ops, sub))
        sum_rows = []
        for k, it in enumerate(counters):
            ops, sub = ops_of[k]
            rolls = [j for j, (oj, _) in enumerate(ops_of) if ('ctr', k) in oj]
            rsym = 'NULL'
            if rolls:
                rsym = f"{n}_sr{k}"
                self.glob.append(f"static const int {rsym}[] = {{{', '.join(map(str, rolls))}}};")
            ctl, final = -1, 0
            p = it
            while p is not None:
                if p.rx.ctl:
                    ctl = ctl_index(p.rx.ctl)
                    break
                if p.rx.flags & F_CF_FINAL:
                    final = 1
                    break
                p = p.parent
            # RESET ON (which cobc 3.1.2 ignores): the counter is reset by the
            # footing of the named control, or only at the end for FINAL
            if it.rw_reset == 'FINAL':
                ctl, final = -1, 1
            elif it.rw_reset:
                if it.rw_reset not in engine_ctl:
                    raise CompileError(f"RESET ON '{it.rw_reset}': not a CONTROL of this report", it.loc)
                ctl, final = ctl_index(it.rw_reset), 0
            # SUM ... UPON (which cobc 3.1.2 ignores): only these DETAIL
            # groups' GENERATEs add to the counter
            upon = []
            for _ops, names in it.rw_sums:
                for nm in names:
                    tgt = self.ctx.rw_groups.get(nm)
                    if tgt is None or tgt[0] is not ri or tgt[1].rx.node is None:
                        raise CompileError(f"UPON '{nm}' is not a DETAIL group of this report", it.loc)
                    upon.append(tgt[1].rx.node)
            usym = 'NULL'
            if upon:
                usym = f"{n}_su{k}"
                self.glob.append(f"static cob_rwline *const {usym}[] = {{{', '.join('&' + u for u in upon)}}};")
            sum_rows.append(f"{{{self.rw_item_field(it.rx.counter)}, {ctl}, {len(ops)}, {final}, "
                            f"{1 if sub else 0}, {len(rolls)}, {rsym}, {len(upon)}, {usym}}}")
        if sum_rows:
            self.glob.append(f"static cob_rwsum {n}_s[] = {{{', '.join(sum_rows)}}};")

        code = 'NULL'
        if ri.code:
            code = f"{n}_code"
            self.glob.append(f"static const unsigned char {code}[] = {{{', '.join(str(b) for b in ri.code)}}};")

        # PAGE clause, with the defaults the reference fills in
        lines = rd.page_limit or 0
        h, fd, ld, ft, lctl = rd.heading or 0, rd.first_detail or 0, rd.last_detail or 0, rd.footing or 0, 0
        if lines:
            h = h or 1
            fd = fd or h
            lctl = ld or ft or lines
            if not ld and not ft:
                ld = ft = lines
            elif not ld:
                ld = ft
            elif not ft:
                ft = ld
        if fd < 1:
            fd = 1
        cols = getattr(rd, 'line_limit', 0) or 0

        self.protos.append(f"static void {n}_src(int id);")
        self.protos.append(f"static cob_field *{n}_ctlf(int i);")
        self.protos.append(f"static void {n}_sumadd(int k);")
        self.protos.append(f"static void {n}_decl(int id);")
        self.protos.append(f"static void {n}_moves(int foot);")
        first = ri.lines[0].rx.node if ri.lines else None
        self.glob.append(
            f"static cob_report {n} = {{\"{ri.name}\", &{ri.file.sym}, {ri.pc.special}, {ri.lc.special}, "
            f"{'&' + first if first else 'NULL'}, {len(engine_ctl)}, {n + '_c' if ctl_rows else 'NULL'}, "
            f"{len(counters)}, {n + '_s' if sum_rows else 'NULL'}, "
            f"{lines}, {cols}, {h}, {fd}, {lctl}, {ld}, {ft}, {code}, {len(ri.code)}, {recsz}, "
            f"{n}_src, {n}_ctlf, {n}_sumadd, {n}_decl, {n}_moves}};")

        def src(em):
            em("switch (id) {")
            for k, kind, v, fsym in src_cases:
                if kind == 'ctr':
                    s = self.rw_item_field(v)
                elif kind == 'snap':
                    s = '&' + v
                else:
                    s = self.field(v)
                em(f"case {k}: cob_move({s}, &{fsym}); break;")
            em("}")
            em("(void)id;")
        self.rw_function(f"static void {n}_src(int id)", src)

        def ctlf(em):
            em("switch (i) {")
            for ci, name in enumerate(engine_ctl):
                ref = next(r for r, _ in ri.controls if r.name == name)
                # a CF() is a temporary: hand back a copy that outlives the call
                em(f"case {ci}: {{ static cob_field f; f = *{self.field(ref)}; return &f; }}")
            em("}")
            em("(void)i;")
            em("return NULL;")
        self.rw_function(f"static cob_field *{n}_ctlf(int i)", ctlf)

        def sumadd(em):
            em("switch (k) {")
            for k, it in enumerate(counters):
                ops, _ = ops_of[k]
                c = self.rw_item_field(it.rx.counter)
                em(f"case {k}:")
                em.ind += 1
                for kind, v in ops:
                    if kind == 'ctr':
                        o = self.rw_item_field(counters[v].rx.counter)
                    else:
                        o = self.field(v)
                    em(f"cob_d_set({c}, cob_d_add(cob_d_get({c}), cob_d_get({o})), 0);")
                em("break;")
                em.ind -= 1
            em("}")
            em("(void)k;")
        self.rw_function(f"static void {n}_sumadd(int k)", sumadd)

        def decl(em):
            ids = sorted({it.rx.decl for it in ri.lines if it.rx.decl})
            em("switch (id) {")
            for d in ids:
                em(f"case {d}: cob_decl_which = {d}; {cname}(COB_DECL_ENTRY, NULL); break;")
            em("}")
            em("(void)id;")
        self.rw_function(f"static void {n}_decl(int id)", decl)

        # what each GENERATE (and TERMINATE, for the footing groups) does
        # before it starts: snapshot indexed SOURCEs, evaluate PRESENT WHEN
        state = {'foot': False}

        def moves_pass(em, footing):
            def walk(items):
                for p in items:
                    x = p.rx
                    if x.flags & FOOTINGS:
                        state['foot'] = True
                    mine = state['foot'] == footing
                    if x.snap is not None and mine:
                        # every GENERATE takes the snapshots of all groups,
                        # printed or not, so an index past its table here is
                        # not the program's error: no bounds check (nor does cobc)
                        self.rw_unchecked = True
                        try:
                            s = self.field(p.rw_source)
                        finally:
                            self.rw_unchecked = False
                        em(f"{{ const cob_field *s = {s}; {x.snap}.size = s->size; {x.snap}.attr = s->attr; "
                           f"memcpy({x.snap}_d, s->data, s->size); }}")
                    if x.when is not None and mine:
                        if x.flags & F_LINE or not x.fields:
                            tgt = f"{x.node}.sup" if x.node else None
                        else:
                            tgt = f"{x.fields[0]}.sup"
                        if tgt:
                            em(f"{tgt} = ({self.cond(x.when)}) ? 0 : 1;")
                    if p.children:
                        walk(p.children)
                        if x.flags & FOOTINGS:
                            state['foot'] = False
            walk(rd.groups)

        def moves(em):
            em("if (!foot) {")
            em.ind += 1
            moves_pass(em, False)
            em.ind -= 1
            em("}")
            moves_pass(em, True)
            em("(void)foot;")
        self.rw_function(f"static void {n}_moves(int foot)", moves)

    def rw_counter_refs(self, s):
        """A report item with SUM stands for its sum counter where a statement
        takes its numeric value: the operands of COMPUTE, ADD, SUBTRACT,
        MULTIPLY and DIVIDE and the sending item of a MOVE (as cobc compiles
        them). DISPLAY, conditions and SOURCE see the item itself."""
        from .nodes import BinOp, Neg, Move, Arith, Compute

        def fix(e):
            if isinstance(e, DataRef):
                if e.item is None:
                    try:
                        it = self.resolve(e)
                    except CompileError:
                        return
                else:
                    it = e.item
                rx = getattr(it, 'rx', None)
                if rx is not None and rx.counter is not None:
                    e.item = rx.counter
            elif isinstance(e, BinOp):
                fix(e.left)
                fix(e.right)
            elif isinstance(e, Neg):
                fix(e.e)
        if isinstance(s, Move):
            fix(s.src)
        elif isinstance(s, Arith):
            for e in s.operands:
                fix(e)
            if s.by_or_into is not None:
                fix(s.by_or_into)
        elif isinstance(s, Compute):
            fix(s.expr)

    def rw_source_size(self, ref):
        it = self.resolve(ref)
        size = getattr(it, 'size', 0) or 0
        if ref.refmod is not None and it is not None:
            size = it.total_size() if hasattr(it, 'total_size') else size
        return size

    def c_bytes(self, b):
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

    # ------------------------------------------------------------ statements
    def rw_report(self, name, loc):
        ri = self.ctx.reports.get(name)
        if ri is None:
            raise CompileError(f"'{name}' is not a report", loc)
        return ri

    def g_Initiate(self, s):
        for name in s.reports:
            self.em(f"cob_rw_initiate(&{self.rw_report(name, s.loc).sym}, {self.locstr()});")

    def g_Terminate(self, s):
        for name in s.reports:
            self.em(f"cob_rw_terminate(&{self.rw_report(name, s.loc).sym}, {self.locstr()});")

    def g_Generate(self, s):
        ref = s.name
        name = ref.name if isinstance(ref, DataRef) else None
        ri = self.ctx.reports.get(name)
        if ri is not None:
            self.em(f"cob_rw_generate(&{ri.sym}, NULL, {self.locstr()});")
            return
        tgt = self.ctx.rw_groups.get(name)
        if tgt is None or tgt[1].rx.node is None or not (tgt[1].rx.flags & F_DE or
                                                          any(a.rx.flags & F_DE for a in tgt[1].ancestors())):
            raise CompileError(f"GENERATE: '{name}' is not a report or a DETAIL report group", s.loc)
        self.em(f"cob_rw_generate(&{tgt[0].sym}, &{tgt[1].rx.node}, {self.locstr()});")

    def g_Suppress(self, s):
        self.em("cob_rw_suppress_printing();")
