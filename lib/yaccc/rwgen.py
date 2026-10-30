# SPDX-License-Identifier: MIT
"""Report Writer: analysis of the REPORT SECTION and generation of the report
tables and callbacks driven by the runtime RWCS (runtime/cobrt_rw.c)."""
from .data import (DataItem, Picture, layout, resolve_types, Occurs, T_NUM_COMP5,
                  T_NUM_EDITED)
from .errors import CompileError
from .nodes import DataRef, NumLit, StrLit

RW_TYPE_C = {'RH': 'COB_RW_RH', 'PH': 'COB_RW_PH', 'CH': 'COB_RW_CH', 'DE': 'COB_RW_DE',
             'CF': 'COB_RW_CF', 'PF': 'COB_RW_PF', 'RF': 'COB_RW_RF'}
RW_KIND_C = {'ABS': 'COB_RW_ABS', 'REL': 'COB_RW_REL', 'ABSNP': 'COB_RW_ABSNP', 'NP': 'COB_RW_NP'}


class RInfo:
    """One RD entry."""

    def __init__(self, rd):
        self.rd = rd
        self.name = rd.name
        self.sym = None
        self.file = None
        self.controls = []          # (DataRef, DataItem), level = index + 1
        self.levels = {}            # control name -> level (FINAL = 0)
        self.groups = []            # GInfo
        self.counters = []          # SumCounter
        self.code = rd.code or b''
        self.width = 1
        self.lc = self.pc = None    # LINE-COUNTER / PAGE-COUNTER items


class GInfo:
    """One report group (01 entry)."""

    def __init__(self, item, idx):
        self.item = item
        self.idx = idx
        self.name = item.name
        self.type, self.ctl = item.rw_type
        self.level = 0
        self.lines = []             # [(spec, [elementary entries])]
        self.next_group = item.rw_next_group
        self.decl_sec = None
        self.counters = []


class SumCounter:
    def __init__(self, entry, group):
        self.entry = entry
        self.group = group
        self.item = None            # the sum counter (numeric)
        self.image = None           # edited image addressed by the entry's name, if edited
        self.data_ops = []          # (DataRef, [detail group indices] for UPON)
        self.cross = []             # counters of the same group (crossfooting)
        self.rollers = []           # counters of higher groups that SUM this one (rolling forward)
        self.reset_level = None     # None: never reset


def _num_pic(digits, scale):
    if scale <= 0:
        return f"S9({max(digits, 1)})" + (f"P({-scale})" if scale < 0 else "")
    ip = digits - scale
    return "S" + (f"9({ip})" if ip > 0 else "") + f"V9({scale})"


class Spacer:
    """Marks a report line's current position at the start of one occurrence of
    a repeated group; it prints nothing."""
    rw_spacer = True
    rw_slot = 0

    def __init__(self, col, loc):
        self.rw_column = col
        self.loc = loc


class ReportWriterGen:
    """Mixed into CodeGen."""

    # ------------------------------------------------------------ analysis
    def rw_analyze(self, prog):
        ctx = self.ctx
        ctx.reports = {}
        ctx.rw_groups = {}
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
            for i, ref in enumerate(rd.controls):
                it = self.resolve(ref, allow_cond=False)
                if not isinstance(it, DataItem):
                    raise CompileError(f"CONTROL '{ref.name}' must be a data item", ref.loc)
                ri.controls.append((ref, it))
                ri.levels[ref.name] = i + 1
            ri.levels['FINAL'] = 0
            ri.lc = self.rw_special(ri, 'LINE-COUNTER')
            ri.pc = self.rw_special(ri, 'PAGE-COUNTER')
            self.rw_page(ri)
            for idx, g in enumerate(rd.groups):
                if g.level != 1:
                    raise CompileError("report group description must have level 01", g.loc)
                if g.rw_type is None:
                    raise CompileError(f"report group '{g.name or 'FILLER'}' needs a TYPE clause", g.loc)
                gi = GInfo(g, idx)
                if gi.type in ('CH', 'CF'):
                    if gi.ctl not in ri.levels:
                        raise CompileError(f"'{gi.ctl}' is not a CONTROL of report '{rd.name}'", g.loc)
                    gi.level = ri.levels[gi.ctl]
                    dup = [x for x in ri.groups if x.type == gi.type and x.level == gi.level]
                    if dup:
                        raise CompileError(f"more than one {gi.type} group for '{gi.ctl}'", g.loc)
                elif gi.type in ('RH', 'PH', 'PF', 'RF'):
                    if any(x.type == gi.type for x in ri.groups):
                        raise CompileError(f"more than one {gi.type} group in report '{rd.name}'", g.loc)
                    if gi.type in ('PH', 'PF') and not rd.page_limit:
                        raise CompileError(f"{gi.type} group requires a PAGE clause in the RD", g.loc)
                ri.groups.append(gi)
                if g.name:
                    ctx.rw_groups[g.name] = (ri, gi)
                self.rw_group(ri, gi)
            self.rw_link_sums(ri)
            ri.width = max([ri.width] + [len(ri.code) + f.rw_column - 1 + f.rw_slot
                                         for g in ri.groups for _, fl in g.lines for f in fl])
            if rd.line_limit:
                for g in ri.groups:
                    for _, fl in g.lines:
                        for f in fl:
                            if f.rw_column - 1 + f.rw_slot > rd.line_limit:
                                raise CompileError(f"report item ends in column {f.rw_column - 1 + f.size}, "
                                                   f"beyond the LINE LIMIT of {rd.line_limit}", f.loc)

    def rw_special(self, ri, name):
        sym = self.sym('rwc_')
        # an unsigned 32-bit binary item: DISPLAY shows ten digits, as cobc's
        # LINE-COUNTER and PAGE-COUNTER do
        it = DataItem(1, name, ri.rd.loc)
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

    def rw_page(self, ri):
        rd = ri.rd
        pl = rd.page_limit
        if not pl:
            ri.page = (0, 0, 0, 0, 0)
            return
        h = rd.heading or 1
        fd = rd.first_detail or h
        ld = rd.last_detail or rd.footing or pl
        # where the page footing sits: an explicit FOOTING clause wins, then a
        # PAGE FOOTING group's own LINE NUMBER (which is how reports usually
        # say it), then LAST DETAIL
        ft = rd.footing or self.page_footing_line(rd) or rd.last_detail or pl
        if not (1 <= h <= fd <= ld <= ft <= pl):
            raise CompileError("PAGE clause: HEADING <= FIRST DETAIL <= LAST DETAIL <= FOOTING <= PAGE LIMIT "
                               "is required", rd.loc)
        ri.page = (pl, h, fd, ld, ft)

    @staticmethod
    def page_footing_line(rd):
        """The absolute line a PAGE FOOTING group is presented on, or 0."""
        for g in rd.groups:
            t = getattr(g, 'rw_type', None)
            ln = getattr(g, 'rw_line', None)
            if t and t[0] == 'PF' and ln and ln[0] == 'ABS':
                return ln[1]
        return 0

    def rw_group(self, ri, gi):
        g = gi.item
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
                # COLUMN 1, 11, 21, 27: one occurrence per column, subscripted
                # like a table (GnuCOBOL gives the item an implicit OCCURS)
                oc = Occurs()
                oc.min = oc.max = len(it.rw_columns)
                oc.loc = it.loc
                it.occurs = oc
        resolve_types(g, self.opts)
        layout(g, 0)
        # report items live in their own storage: a program can MOVE to them or
        # read them by name, and the presentation copies the item's current value
        # into the print line (GnuCOBOL's reportio.c, copy_line_fields)
        sym = self.sym('rwd_')
        self.glob.append(f"static unsigned char {sym}[{g.total_size()}];"
                         f" /* report group {g.name or 'FILLER'} */")
        for it in g.walk():
            it.storage = sym
            it.section = 'WS'
            it.record = g
            it.report_name = ri.name
        self.register_tree(g)
        self.ctx.rw_trees.append(g)
        cur = None
        # An 01 LINE clause is dropped when the 01's first subordinate entry has
        # one too; the 01 is then, like an 01 without LINE whose lines come from
        # entries below it, a print line of its own that holds nothing (`hdr`).
        nested = (g.rw_line is not None and bool(g.children)
                  and g.children[0].rw_line is not None)
        gi.hdr = (g.rw_line is None or nested) and any(
            c.rw_line is not None for c in g.walk() if c is not g)
        floor = 0                   # items of the line before this index belong to an outer group
        gi.line_conds = {}          # print line index -> PRESENT WHEN of its LINE entry

        def when_of(it):
            """PRESENT WHEN / ABSENT WHEN on an entry below the 01 (the 01's own
            is checked by the runtime for the whole group)."""
            p = getattr(it, 'rw_present', None)
            if it is g or p is None:
                return None
            if isinstance(p[0], tuple) and p[0] and p[0][0] == 'AFTER':
                return None
            return p

        def walk(it, shift=0, subs=(), conds=()):
            nonlocal cur, floor
            own = when_of(it)
            if it.rw_line is not None and not (it is g and nested):
                kind_num = tuple(it.rw_line)
                if not (kind_num[0] == 'ABS' and cur is not None
                        and any(tuple(sp) == kind_num for sp, _ in gi.lines)):
                    cur = (it.rw_line, [])
                    gi.lines.append(cur)
                    floor = 0
                    if own is not None:
                        # on a LINE entry it decides whether the line is there
                        gi.line_conds[len(gi.lines) - 1] = own
                        own = None
                # else: a second absolute LINE n with the same n as an earlier
                # one in the group joins the line before it (measured on cobc
                # 3.1.2: run_reportwriter.at's Inventory report heading)
            if own is not None:
                conds = conds + (own,)
            if not it.children:
                place(it, shift, subs, conds)
                return
            if it.occurs:
                # OCCURS on a group repeats everything inside it, each occurrence
                # STEP columns right of the one before (default: the group width)
                step = it.rw_step or it.size
                c0 = start_col(it, shift)
                for k in range(it.occurs.max):
                    cur[1].append(Spacer(c0 + k * step, it.loc))
                    for c in it.children:
                        walk(c, 0, subs + ((it, k + 1),), conds)
                return
            # a group item below the line entry starts its own run of columns:
            # COLUMN PLUS and items without COLUMN count from its first column
            # (measured: a FILLER group holding COLUMN PLUS 1 prints in column 1)
            inner = it is not g and it.rw_line is None and cur is not None
            saved = floor
            if inner:
                floor = len(cur[1])
            for c in it.children:
                walk(c, shift, subs, conds)
            if inner:
                floor = saved

        def start_col(it, shift):
            """Column of an item's first occurrence, from the previous item of
            the line and its own COLUMN clause."""
            prev = cur[1][-1] if len(cur[1]) > floor else None
            prev_end = prev.rw_column + prev.rw_slot if prev else 1
            col = it.rw_column
            if col is None:
                # no COLUMN clause: the item follows the previous one
                return prev_end + shift
            if isinstance(col, tuple):
                # COLUMN PLUS n: n positions right of the previous item of the line
                return (prev_end - 1 if prev else 0) + col[1] + shift
            return col + shift

        def place(it, shift, subs, conds=()):
            nonlocal cur
            if cur is None:
                # a group without LINE clauses: its items go on the next line
                cur = (('REL', 1), [])
                gi.lines.append(cur)
            col = start_col(it, shift)
            step = (it.rw_step or it.size) if it.occurs else 0
            n = it.occurs.max if it.occurs else 1
            listed = getattr(it, 'rw_columns', None)
            if listed and len(listed) != n:
                raise CompileError(f"'{it.name or 'FILLER'}' lists {len(listed)} COLUMN values for "
                                   f"{n} occurrence(s)", it.loc)
            import copy as _copy
            for k in range(n):
                base = (listed[k] + shift) if listed else col + k * step
                if it.rw_just == 'R':           # COLUMN RIGHT n: the item ends in column n
                    base = base - it.size + 1
                elif it.rw_just == 'C':         # COLUMN CENTER n: centered on column n
                    base = base - (it.size - 1) // 2 if it.size % 2 else base - it.size // 2 + 1
                if base < 1:
                    raise CompileError("report item starts before column 1", it.loc)
                rep = _copy.copy(it)
                rep.rw_column = base
                rep.rw_slot = it.size if listed else (step if step else it.size)
                rep.rw_subs = subs + ((it, k + 1),) if it.occurs else subs
                rep.rw_columns = None
                rep.rw_when = conds
                cur[1].append(rep)
            if it.rw_group_indicate and gi.type != 'DE':
                raise CompileError("GROUP INDICATE is only allowed in a DETAIL group", it.loc)
            if it.rw_sums and not getattr(it, 'rw_counted', False):
                if gi.type not in ('CF', 'RF'):
                    raise CompileError("SUM is only allowed in CONTROL FOOTING and REPORT FOOTING groups",
                                       it.loc)
                it.rw_counted = True
                self.rw_counter(ri, gi, it)

        walk(g)
        for spec, _ in gi.lines[1:]:
            if spec[0] in ('ABSNP', 'NP'):
                raise CompileError("NEXT PAGE is only allowed in the first LINE clause of a group", g.loc)

    def rw_counter(self, ri, gi, entry):
        if entry.category() not in ('NUMERIC', 'NUMERIC-EDITED'):
            raise CompileError("a SUM item must have a numeric or numeric-edited PICTURE", entry.loc)
        sc = SumCounter(entry, gi)
        if entry.type == T_NUM_EDITED:
            # an edited item cannot be added to; accumulate in a numeric field
            # and move the result through the item itself for presentation
            ctr = DataItem(1, None, entry.loc)
            ctr.pic = Picture(_num_pic(entry.pic.digits, entry.pic.scale), entry.loc, '$', False)
            resolve_types(ctr, self.opts)
            layout(ctr, 0)
            sym = self.sym('rsum_')
            self.glob.append(f"static unsigned char {sym}[{ctr.size}];"
                             f" /* sum counter {entry.name or ''} */")
            ctr.storage = sym
            ctr.section = 'WS'
            ctr.record = ctr
            ctr.offset = 0
            self.ctx.rw_init.append(ctr)
            sc.image = entry
        else:
            # the item is its own accumulator: GnuCOBOL sums into the item's field
            ctr = entry
        sc.item = ctr
        if gi.type == 'RF':
            sc.reset_level = None
        elif entry.rw_reset == 'FINAL':
            sc.reset_level = 0
        elif entry.rw_reset:
            if entry.rw_reset not in ri.levels:
                raise CompileError(f"RESET ON '{entry.rw_reset}': not a CONTROL of this report", entry.loc)
            sc.reset_level = ri.levels[entry.rw_reset]
        else:
            sc.reset_level = gi.level
        ri.counters.append(sc)
        gi.counters.append(sc)

    def rw_link_sums(self, ri):
        by_name = {sc.entry.name: sc for sc in ri.counters if sc.entry.name}
        for sc in ri.counters:
            for ops, upon in sc.entry.rw_sums:
                upon_idx = []
                for nm in upon:
                    tgt = self.ctx.rw_groups.get(nm)
                    if tgt is None or tgt[0] is not ri or tgt[1].type != 'DE':
                        raise CompileError(f"UPON '{nm}' is not a DETAIL group of this report", sc.entry.loc)
                    upon_idx.append(tgt[1].idx)
                for ref in ops:
                    d = by_name.get(ref.name) if isinstance(ref, DataRef) and not ref.subs else None
                    if d is not None:
                        if d.group is sc.group:
                            sc.cross.append(d)
                        else:
                            d.rollers.append(sc)
                    else:
                        sc.data_ops.append((ref, upon_idx))

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
        if not ctx.reports:
            for sec in prog.declaratives:
                if sec.use_reporting:
                    raise CompileError(f"USE BEFORE REPORTING: '{sec.use_reporting}' is not a report group",
                                       sec.loc)
            return
        for sec in prog.declaratives:
            if sec.use_reporting:
                tgt = ctx.rw_groups.get(sec.use_reporting)
                if tgt is None:
                    raise CompileError(f"USE BEFORE REPORTING: '{sec.use_reporting}' is not a report group",
                                       sec.loc)
                tgt[1].decl_sec = sec
        for ri in ctx.reports.values():
            self.rw_emit_report(prog, ri)

    def rw_emit_report(self, prog, ri):
        n = ri.sym
        cname = self.prog_syms[id(prog)]
        # tables
        rows = []
        for g in ri.groups:
            lsym = 'NULL'
            if g.lines:
                lsym = f"{n}_l{g.idx}"
                specs = ', '.join(f"{{{RW_KIND_C[k]}, {num}}}" for (k, num), _ in g.lines)
                self.glob.append(f"static const cob_rw_lspec {lsym}[] = {{{specs}}};")
            ngk, ngn = ('0', 0)
            if g.next_group is not None:
                ngk, ngn = RW_KIND_C[g.next_group[0]], g.next_group[1]
            # PRESENT WHEN / ABSENT WHEN: a function returning the condition
            pw, ab = 'NULL', 0
            cond = getattr(g.item, 'rw_present', None)
            if cond is not None:
                c, invert = cond
                fsym = f"{n}_when{g.idx}"
                body = self.cond(c)
                self.glob.append(f"static int {fsym}(void) {{ return {body}; }}")
                pw, ab = fsym, 1 if invert else 0
            rows.append(f"{{{RW_TYPE_C[g.type]}, {g.level}, {len(g.lines)}, {lsym}, {ngk}, {ngn}, "
                        f"{1 if g.decl_sec else 0}, {pw}, {ab}, {1 if getattr(g, 'hdr', False) else 0}}}")
        self.glob.append(f"static const cob_rw_group {n}_g[] = {{{', '.join(rows)}}};")
        code = 'NULL'
        if ri.code:
            code = f"{n}_code"
            self.glob.append(f"static const unsigned char {code}[] = {{{', '.join(str(b) for b in ri.code)}}};")
        self.protos.append(f"static int {n}_fmt(int g, int line, unsigned char *buf, int gi);")
        self.protos.append(f"static void {n}_sum(int op, int arg);")
        self.protos.append(f"static int {n}_ctl(int op);")
        self.protos.append(f"static void {n}_decl(int g);")
        pl, h, fd, ld, ft = ri.page
        rd_footing = ri.rd.footing or self.page_footing_line(ri.rd)
        self.glob.append(
            f"static cob_report {n} = {{\"{ri.name}\", &{ri.file.sym}, {pl}, {h}, {fd}, {ld}, {ft}, "
            f"{1 if ri.rd.last_detail else 0}, {1 if rd_footing else 0}, "
            f"{1 if ri.rd.first_detail else 0}, {1 if ri.rd.footing else 0}, {ri.width}, "
            f"{code}, {len(ri.code)}, {len(ri.groups)}, {n}_g, {len(ri.controls)}, {ri.lc.special}, "
            f"{ri.pc.special}, {n}_fmt, {n}_sum, {n}_ctl, {n}_decl}};")

        # format callback
        def fmt(em):
            em("switch (g) {")
            for g in ri.groups:
                if not g.lines:
                    continue
                em(f"case {g.idx}:")
                em.ind += 1
                em("switch (line) {")
                for li, (_, fields) in enumerate(g.lines):
                    em(f"case {li}:")
                    em.ind += 1
                    lc = getattr(g, 'line_conds', {}).get(li)
                    if lc is not None:
                        em(f"if (!({self.rw_when_c([lc])})) return 0;")
                    if not any(not getattr(f, 'rw_spacer', False) for f in fields):
                        em("return 0;")     # a line with no items prints nothing
                    for f in fields:
                        if getattr(f, 'rw_spacer', False):
                            continue
                        src = self.rw_source(ri, f)
                        if src is None:
                            continue
                        off = len(ri.code) + f.rw_column - 1
                        dst = f"CF(buf + {off}, {f.size}, &{self.item_attr(f)})"
                        stmt = f"cob_move({src}, {dst});"
                        if f.rw_just and (f.rw_source is not None or f.rw_sums):
                            # GnuCOBOL aligns SOURCE and SUM data within the item, not VALUEs
                            stmt = f"{{ {stmt} cob_rw_justify(buf + {off}, {f.size}, '{f.rw_just}'); }}"
                        if f.rw_group_indicate:
                            stmt = f"if (gi) {stmt}"
                        cond = self.present_after(ri, f)
                        if cond is not None:
                            stmt = f"if ({cond}) {stmt}"
                        when = getattr(f, 'rw_when', ())
                        if when:
                            stmt = f"if ({self.rw_when_c(when)}) {stmt}"
                        em(stmt)
                    em("break;")
                    em.ind -= 1
                em("}")
                em("break;")
                em.ind -= 1
            em("}")
            em("(void)buf; (void)gi; (void)line;")
            em("return 1;")
        self.rw_function(f"static int {n}_fmt(int g, int line, unsigned char *buf, int gi)", fmt)

        # sum counter callback
        def add(em, dst, src, cond=None):
            c = self.rw_item_field(dst.item)
            s = f"cob_d_set({c}, cob_d_add(cob_d_get({c}), cob_d_get({src})), 0);"
            em(f"if ({cond}) {s}" if cond else s)

        def sums(em):
            em("switch (op) {")
            em("case 0: /* subtotaling */")
            em.ind += 1
            for sc in ri.counters:
                for ref, upon in sc.data_ops:
                    cond = ' || '.join(f"arg == {u}" for u in upon) if upon else None
                    add(em, sc, self.field(ref), cond)
            em("break;")
            em.ind -= 1
            for op, what in ((1, 'cross'), (2, 'rollers')):
                em(f"case {op}: /* {'crossfooting' if op == 1 else 'rolling forward'} */")
                em.ind += 1
                em("switch (arg) {")
                for g in ri.groups:
                    body = []
                    for sc in g.counters:
                        if op == 1:
                            body += [(sc, d) for d in sc.cross]
                        else:
                            body += [(t, sc) for t in sc.rollers]
                    if body:
                        em(f"case {g.idx}:")
                        em.ind += 1
                        for dst, srcc in body:
                            add(em, dst, self.rw_item_field(srcc.item))
                        em("break;")
                        em.ind -= 1
                em("}")
                em("break;")
                em.ind -= 1
            em("case 3: /* INITIATE */")
            em.ind += 1
            for sc in ri.counters:
                em(f"cob_move(&cob_fig_zero, {self.rw_item_field(sc.item)});")
            em("break;")
            em.ind -= 1
            em("case 4: /* reset at a control level */")
            em.ind += 1
            em("switch (arg) {")
            for lev in sorted(set(sc.reset_level for sc in ri.counters if sc.reset_level is not None)):
                em(f"case {lev}:")
                em.ind += 1
                for sc in ri.counters:
                    if sc.reset_level == lev:
                        em(f"cob_move(&cob_fig_zero, {self.rw_item_field(sc.item)});")
                em("break;")
                em.ind -= 1
            em("}")
            em("break;")
            em.ind -= 1
            em("}")
            for sc in ri.counters:
                if sc.image is not None:
                    em(f"cob_move({self.rw_item_field(sc.item)}, {self.rw_item_field(sc.image)});")
            em("(void)arg;")
        self.rw_function(f"static void {n}_sum(int op, int arg)", sums)

        # control data items
        saves = []
        for ref, it in ri.controls:
            s = self.sym('rctl_')
            self.glob.append(f"static unsigned char {s}[{it.size}];")
            saves.append((s, ref, it))

        def ctl(em):
            em("switch (op) {")
            em("case 0:")
            em.ind += 1
            for s, ref, it in saves:
                em(f"memcpy({s}, ({self.field(ref)})->data, {it.size});")
            em("return 0;")
            em.ind -= 1
            em("case 1:")
            em.ind += 1
            for lev, (s, ref, it) in enumerate(saves, 1):
                em(f"if (cob_cmp({self.field(ref)}, CF({s}, {it.size}, &{self.item_attr(it)})) != 0) return {lev};")
            em("return 0;")
            em.ind -= 1
            em("case 2: {")
            em.ind += 1
            if saves:
                em(f"unsigned char t[{max(it.size for _, _, it in saves)}];")
                for s, ref, it in saves:
                    em(f"memcpy(t, ({self.field(ref)})->data, {it.size});")
                    em(f"memcpy(({self.field(ref)})->data, {s}, {it.size});")
                    em(f"memcpy({s}, t, {it.size});")
            em("return 0;")
            em.ind -= 1
            em("}")
            em("}")
            em("return 0;")
        self.rw_function(f"static int {n}_ctl(int op)", ctl)

        # USE BEFORE REPORTING
        def decl(em):
            em("switch (g) {")
            for g in ri.groups:
                if g.decl_sec is not None:
                    em(f"case {g.idx}: cob_decl_which = {g.decl_sec.id}; {cname}(COB_DECL_ENTRY, NULL); break;")
            em("}")
            em("(void)g;")
        self.rw_function(f"static void {n}_decl(int g)", decl)

    def rw_when_c(self, conds):
        """C condition for a list of (condition, absent) PRESENT WHEN /
        ABSENT WHEN clauses, all of which must hold."""
        parts = []
        for c, absent in conds:
            body = self.cond(c)
            parts.append(f"!({body})" if absent else f"({body})")
        return ' && '.join(parts)

    def present_after(self, ri, f):
        """C condition for PRESENT AFTER PAGE OR <control> (negated for
        ABSENT AFTER): the item is shown on the first detail line of a page or
        after one of the named controls changes."""
        p = getattr(f, 'rw_present', None)
        if p is None:
            return None
        what, absent = p
        if not (isinstance(what, tuple) and what[0] == 'AFTER'):
            return None
        parts = []
        for name in what[1]:
            if name == 'PAGE':
                parts.append("cob_rw_new_page")
                continue
            lev = ri.levels.get(name)
            if lev is None:
                raise CompileError(f"PRESENT AFTER '{name}': not a CONTROL of "
                                   f"this report", f.loc)
            if lev == 0:
                parts.append("cob_rw_ctl_change == 0")   # FINAL: the first detail
            else:
                # controls nest: a change at a major level changes the minor ones too
                parts.append(f"(cob_rw_ctl_change > 0 && cob_rw_ctl_change <= {lev})")
        cond = ' || '.join(parts) or '1'
        return f"!({cond})" if absent else cond

    def rw_source(self, ri, f):
        if f.rw_sums:
            for sc in ri.counters:
                if sc.entry is f:
                    return self.rw_item_field(sc.item)
        if f.rw_source is not None:
            return self.field(f.rw_source)
        if f.value is not None:
            # a VALUE clause is refreshed at every presentation, so a MOVE to the
            # item does not show (reportio.c, copy_line_fields: rf->litval)
            return self.field(f.value)
        return self.rw_item_ref(f)

    def rw_item_ref(self, it):
        """C field for a report item's own storage, at one occurrence."""
        terms = [str(it.offset)]
        for occ, k in getattr(it, 'rw_subs', ()) or ():
            terms.append(f"({k} - 1) * {occ.size}")
        return f"CF({it.storage} + {' + '.join(terms)}, {it.size}, &{self.item_attr(it)})"

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
            self.em(f"cob_rw_generate(&{ri.sym}, -1, {self.locstr()});")
            return
        tgt = self.ctx.rw_groups.get(name)
        if tgt is None or tgt[1].type != 'DE':
            raise CompileError(f"GENERATE: '{name}' is not a report or a DETAIL report group", s.loc)
        self.em(f"cob_rw_generate(&{tgt[0].sym}, {tgt[1].idx}, {self.locstr()});")

    def g_Suppress(self, s):
        self.em("cob_rw_suppress = 1;")
