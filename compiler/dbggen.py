# SPDX-License-Identifier: MIT
"""Debug module: the DEBUG-ITEM special register and USE FOR DEBUGGING
declaratives in programs compiled WITH DEBUGGING MODE.

Debugging sections run only while the object-time switch is on
(COB_SET_DEBUG, see runtime/cobrt_core.c). Hooks are emitted:
  - at each monitored procedure-name, with the cause of the transfer of
    control (START PROGRAM, FALL THROUGH, PERFORM LOOP, GO TO, ALTER, SORT
    INPUT/OUTPUT, MERGE OUTPUT, USE PROCEDURE) kept in cob_dbg_cause/line;
  - for monitored file-names, after OPEN, CLOSE, DELETE and START, and after
    a successful READ;
  - for monitored identifiers, after each statement that references the
    item (ALL REFERENCES) or changes it, before WRITE/REWRITE, before the
    transfer of a GO TO DEPENDING, and after each initialization,
    modification or evaluation in a PERFORM VARYING/AFTER/UNTIL.
"""
from .data import DataItem, Picture, layout, resolve_types
from .errors import CompileError
from .nodes import (Accept, Arith, Call, CallArg, Close, Compute, Cond, DataRef, Delete, Expr,
                    GoTo, InspectOp, InspectRegion, Initialize, Inspect, Move, Open, Paragraph,
                    Perform, ProcRef, Read, Release, Return, Rewrite, Search, SearchWhen, SetStmt,
                    SortKey, Start, Stmt, StringStmt, Target, Unstring, UnstringInto, Varying,
                    WhenObj, Write)

CAUSE_C = {'FALL': 'COB_DBG_FALL', 'START': 'COB_DBG_START', 'PERFORM': 'COB_DBG_PERFORM',
           'GOTO': 'COB_DBG_GOTO', 'SORT_IN': 'COB_DBG_SORT_IN', 'SORT_OUT': 'COB_DBG_SORT_OUT',
           'MERGE_OUT': 'COB_DBG_MERGE_OUT', 'USE': 'COB_DBG_USE'}

# AST nodes that can contain data references inside a statement
_WALK = (Expr, Cond, Target, Varying, WhenObj, CallArg, UnstringInto, InspectOp, InspectRegion,
         SortKey, SearchWhen)


def _c_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


class DbgInfo:
    """Debugging state of one program."""

    def __init__(self):
        self.sym = None             # storage of DEBUG-ITEM
        self.size = 0
        self.sections = set()       # id() of the debugging sections
        self.all_procs = None       # section of USE FOR DEBUGGING ON ALL PROCEDURES
        self.procs = {}             # id(paragraph or section) -> debugging section
        self.files = {}             # id(FileInfo) -> debugging section
        self.data = {}              # id(DataItem) -> (debugging section, ALL REFERENCES)
        self.pending_procs = []     # (DebugTarget, section), resolved with the procedures
        self.track = False          # procedures are monitored: keep cause and line of transfers
        self.prev_line = {}         # id(procedure) -> last statement before it in the source
        self.first_line = 0         # first statement of the first procedure

    @property
    def di(self):
        return f"{self.sym}, {self.size}"


class DebugGen:
    dbg = None
    dbg_pending = None

    # ---------------------------------------------------------------- analysis
    def dbg_analyze(self, prog):
        """After the data division is laid out: classify the USE FOR DEBUGGING
        subjects and define DEBUG-ITEM."""
        self.dbg = None
        self.dbg_pending = None
        dsecs = [s for s in prog.declaratives if s.use_debug]
        # a contained program has no CONFIGURATION SECTION of its own: the
        # containing program's WITH DEBUGGING MODE applies to it
        mode = self.opts.debugging
        p = prog
        while p is not None and not mode:
            mode = p.debugging
            p = p.parent
        if not mode:
            if dsecs:
                # without WITH DEBUGGING MODE, debugging sections are comments
                prog.declaratives = [s for s in prog.declaratives if not s.use_debug]
            return
        d = DbgInfo()
        contents = 30
        for sec in dsecs:
            d.sections.add(id(sec))
            for t in sec.use_debug:
                if t.ref is None:
                    if d.all_procs is not None:
                        raise CompileError("ALL PROCEDURES may appear in only one USE FOR DEBUGGING statement", t.loc)
                    d.all_procs = sec
                    continue
                ref = t.ref
                fi = None if ref.quals else self.lookup_file(ref.name)
                if fi is not None:
                    if t.all_refs:
                        raise CompileError(f"ALL REFERENCES OF requires a data item; '{ref.name}' is a file", t.loc)
                    self.dbg_unique(d.files, fi, sec, ref.name, t.loc)
                    contents = max(contents, fi.size)
                    continue
                if not self.dbg_is_data(ref.name):
                    if t.all_refs:
                        raise CompileError(f"'{ref.name}' is not a data item", t.loc)
                    d.pending_procs.append((t, sec))
                    continue
                it = self.resolve(ref)
                if not isinstance(it, DataItem) or it.level == 88 or getattr(it, 'special', None):
                    raise CompileError(f"'{ref.name}' cannot be monitored by USE FOR DEBUGGING", t.loc)
                if id(it) in d.data:
                    raise CompileError(f"'{ref.name}' appears in more than one USE FOR DEBUGGING statement", t.loc)
                d.data[id(it)] = (sec, t.all_refs)
                contents = max(contents, it.size)
        if d.all_procs is not None and d.pending_procs:
            t = d.pending_procs[0][0]
            raise CompileError("procedure-names cannot be monitored in addition to ALL PROCEDURES", t.loc)
        self.dbg_define_item(prog, d, contents)
        self.dbg = d

    def dbg_unique(self, table, obj, sec, name, loc):
        if id(obj) in table:
            raise CompileError(f"'{name}' appears in more than one USE FOR DEBUGGING statement", loc)
        table[id(obj)] = sec

    def dbg_is_data(self, name):
        if self.ctx.names.get(name):
            return True
        p = self.prog.parent
        while p is not None:
            if self.global_items(p).get(name):
                return True
            p = p.parent
        return False

    def dbg_define_item(self, prog, d, contents):
        """01 DEBUG-ITEM: DEBUG-LINE X(6), DEBUG-NAME X(30), DEBUG-SUB-1..3
        S9(4) SIGN LEADING SEPARATE and DEBUG-CONTENTS, separated by spaces.
        DEBUG-CONTENTS holds the largest monitored item or record."""
        loc = prog.loc
        root = DataItem(1, 'DEBUG-ITEM', loc)

        def add(name, pic, signed=False):
            it = DataItem(2, name, loc)
            it.pic = Picture(pic, loc)
            if signed:
                it.sign_lead = True
                it.sign_sep = True
            it.parent = root
            root.children.append(it)
        add('DEBUG-LINE', 'X(6)')
        add(None, 'X')
        add('DEBUG-NAME', 'X(30)')
        for i in (1, 2, 3):
            add(None, 'X')
            add(f'DEBUG-SUB-{i}', 'S9(4)', True)
        add(None, 'X')
        add('DEBUG-CONTENTS', f'X({contents})')
        resolve_types(root, self.opts)
        layout(root, 0)
        d.sym = self.sym('dbg_')
        d.size = root.size
        self.glob.append(f"static unsigned char {d.sym}[{d.size}]; /* DEBUG-ITEM */")
        for it in root.walk():
            it.record = root
            it.storage = d.sym
            it.section = 'WS'
        self.register_tree(root)

    def dbg_collect(self, prog):
        """After the procedures are collected: resolve monitored procedure-names
        and record, for each procedure, the statement that precedes it."""
        d = self.dbg
        if d is None:
            return
        save = getattr(self, 'cur_section', None)
        self.cur_section = None
        for t, sec in d.pending_procs:
            ref = t.ref
            if len(ref.quals) > 1:
                raise CompileError(f"'{ref.name}' is not a procedure, file or data name", t.loc)
            p = self.resolve_proc(ProcRef(ref.name, ref.quals[0] if ref.quals else None, t.loc))
            owner = p.section if isinstance(p, Paragraph) else p
            if id(owner) in d.sections:
                raise CompileError(f"'{ref.name}' is in a debugging section and cannot be monitored", t.loc)
            self.dbg_unique(d.procs, p, sec, ref.name, t.loc)
        self.cur_section = save
        d.track = d.all_procs is not None or bool(d.procs)
        first = None
        for group in [prog.sections] + [[s] for s in prog.declaratives if id(s) not in d.sections]:
            last = 0
            for sec in group:
                d.prev_line[id(sec)] = last
                for para in sec.paragraphs:
                    d.prev_line[id(para)] = last
                    for sent in para.sentences:
                        if sent.stmts:
                            if first is None and group is prog.sections:
                                first = sent.stmts[0].loc.line
                            last = sent.stmts[-1].loc.line
        d.first_line = first or 0

    # ---------------------------------------------------------------- emission helpers
    def dbg_in_debug_section(self):
        sec = getattr(self, 'cur_section', None)
        return sec is not None and id(sec) in self.dbg.sections

    def dbg_locals(self):
        d = self.dbg
        if d is None:
            return []
        return [f"int cob_dbg_cause = COB_DBG_START, cob_dbg_line = {d.first_line}, cob_dbg_busy = 0;",
                "(void)cob_dbg_cause; (void)cob_dbg_line; (void)cob_dbg_busy;"]

    def dbg_invoke(self, dsec, fill):
        """Fill DEBUG-ITEM and perform the debugging section, unless the
        object-time switch is off or a debugging section is running."""
        em = self.em
        em("if (cob_debug_on && !cob_dbg_busy) {")
        em.ind += 1
        em(fill)
        em("cob_dbg_busy = 1;")
        self.perform_section(dsec)
        em("cob_dbg_busy = 0;")
        em.ind -= 1
        em("}")

    def dbg_cause(self, kind, line=None):
        """C statement recording the cause of a transfer of control ('' if
        procedures are not monitored)."""
        d = self.dbg
        if d is None or not d.track or self.dbg_in_debug_section():
            return ''
        if line is None:
            line = self.cur_loc.line if self.cur_loc is not None else 0
        return f"cob_dbg_cause = {CAUSE_C[kind]}; cob_dbg_line = {line};"

    def dbg_emit_cause(self, kind, line=None):
        c = self.dbg_cause(kind, line)
        if c:
            self.em(c)

    def dbg_label(self, p):
        """At a section or paragraph label: run its debugging section."""
        d = self.dbg
        if d is None or not d.track or self.dbg_in_debug_section():
            return
        dsec = d.all_procs if d.all_procs is not None else d.procs.get(id(p))
        if dsec is not None and p.name:
            line = f"(cob_dbg_cause == COB_DBG_FALL ? {d.prev_line.get(id(p), 0)} : cob_dbg_line)"
            self.dbg_invoke(dsec, f"cob_dbg_proc({d.di}, {line}, {_c_str(p.name)}, cob_dbg_cause);")
        if isinstance(p, Paragraph):
            # control reaching the next procedure without a transfer falls through
            self.em("cob_dbg_cause = COB_DBG_FALL;")

    def dbg_alter(self, p1, p2):
        """After ALTER p1 TO PROCEED TO p2."""
        d = self.dbg
        if d is None or not d.track or self.dbg_in_debug_section():
            return
        dsec = d.all_procs if d.all_procs is not None else d.procs.get(id(p1))
        if dsec is not None:
            self.dbg_invoke(dsec, f"cob_dbg_alter({d.di}, {self.cur_loc.line}, {_c_str(p1.name)}, "
                                  f"{_c_str(p2.name or '')});")

    # ---------------------------------------------------------------- identifiers and files
    def dbg_watching(self):
        d = self.dbg
        return d is not None and bool(d.files or d.data) and not self.dbg_in_debug_section()

    def dbg_walk(self, node, out, top=False):
        """Data references in a statement's own operands, in source order
        (not those of nested statements)."""
        if isinstance(node, DataRef):
            out.append(node)
            for x in node.subs:
                if x != 'ALL':
                    self.dbg_walk(x, out)
            if node.refmod:
                for x in node.refmod:
                    if x is not None:
                        self.dbg_walk(x, out)
            return
        if isinstance(node, (list, tuple)):
            for x in node:
                self.dbg_walk(x, out)
            return
        if isinstance(node, Stmt):
            if not top:
                return
        elif not isinstance(node, _WALK):
            return
        for k, v in vars(node).items():
            if k not in ('loc', 'item', 'target') and not k.startswith('_'):
                self.dbg_walk(v, out)

    def dbg_item(self, ref):
        try:
            it = self.resolve(ref)
        except CompileError:
            return None
        return it if isinstance(it, DataItem) else None

    def dbg_receiving(self, s):
        """Operands a statement stores into."""
        r = []
        if isinstance(s, Move):
            r += s.dsts
        elif isinstance(s, Arith):
            r += [t.ref for t in s.to] + [t.ref for t in s.giving] + [s.remainder]
        elif isinstance(s, Compute):
            r += [t.ref for t in s.targets]
        elif isinstance(s, Accept):
            r.append(s.target)
        elif isinstance(s, StringStmt):
            r += [s.into, s.pointer]
        elif isinstance(s, Unstring):
            for u in s.intos:
                r += [u.target, u.delim_in, u.count_in]
            r += [s.pointer, s.tallying]
        elif isinstance(s, Inspect):
            r += [op.counter for op in s.tallying]
            if s.replacing or s.converting:
                r.append(s.target)
        elif isinstance(s, Initialize):
            r += s.targets
        elif isinstance(s, SetStmt):
            r += s.targets
        elif isinstance(s, Search):
            r.append(s.varying)
        elif isinstance(s, Call):
            r += [a.value for a in s.args if a.mode == 'REFERENCE'] + [s.returning]
        elif isinstance(s, (Read, Return)):
            r.append(s.into)
        elif isinstance(s, Release):
            if s.frm is not None:
                r.append(s.record)
        return [x for x in r if isinstance(x, DataRef)]

    def dbg_plan(self, s):
        """Hooks a statement fires, by timing: 'after' the statement (before its
        conditional phrases), 'before' a WRITE/REWRITE, before the transfer of
        a GO TO DEPENDING ('goto'), after a successful READ or RETURN ('read')."""
        d = self.dbg
        plan = {'line': s.loc.line, 'after': [], 'before': [], 'goto': [], 'read': []}
        if d.files:
            kind = 'after'
            if isinstance(s, Open):
                names = [fn for _, fs in s.modes for fn in fs]
            elif isinstance(s, Close):
                names = s.files
            elif isinstance(s, (Delete, Start)):
                names = [s.file]
            elif isinstance(s, Read):
                names = [s.file]
                kind = 'read'
            else:
                names = []
            seen = set()
            for fn in names:
                fi = self.lookup_file(fn)
                if fi is None or id(fi) in seen:
                    continue
                seen.add(id(fi))
                dsec = d.files.get(id(fi))
                if dsec is not None:
                    plan[kind].append(('file', fi, dsec, kind == 'read'))
        if d.data:
            refs = []
            self.dbg_walk(s, refs, top=True)
            recv = {id(r) for r in self.dbg_receiving(s)}
            skip = set()
            if isinstance(s, Perform):
                # VARYING/AFTER/UNTIL references fire during the loop (dbg_perf)
                tmp = []
                self.dbg_walk([s.varying, s.until], tmp)
                skip = {id(r) for r in tmp}
            chosen = {}
            for ref in refs:
                if id(ref) in skip:
                    continue
                it = self.dbg_item(ref)
                ent = d.data.get(id(it)) if it is not None else None
                if ent is None:
                    continue
                dsec, all_refs = ent
                if isinstance(s, (Write, Rewrite)):
                    kind = 'before'
                elif isinstance(s, GoTo):
                    if not all_refs:
                        continue
                    kind = 'goto'
                else:
                    if not all_refs and id(ref) not in recv:
                        continue
                    # READ/RETURN INTO changes the item only when a record is read
                    kind = 'read' if not all_refs and isinstance(s, (Read, Return)) else 'after'
                key = (id(it), kind)
                if key not in chosen:
                    chosen[key] = [ref, it, dsec, kind]
                elif id(ref) in recv and id(chosen[key][0]) not in recv:
                    chosen[key][0] = ref
            for ref, it, dsec, kind in chosen.values():
                plan[kind].append(('data', ref, it, dsec))
        return plan

    def dbg_flush(self, kind='after'):
        p = self.dbg_pending
        if not p or not p[kind]:
            return
        hooks = p[kind]
        p[kind] = []
        for h in hooks:
            self.dbg_hook(h, p['line'])

    def dbg_hook(self, h, line):
        d = self.dbg
        if h[0] == 'file':
            _, fi, dsec, record = h
            data, size = (fi.buf, self.cur_rec_size(fi)) if record else ('NULL', '0')
            fill = f"cob_dbg_data({d.di}, {line}, {_c_str(fi.fd.name)}, {data}, {size}, 0, 0, 0, 0);"
        else:
            _, ref, it, dsec = h
            name = ' OF '.join([ref.name] + list(ref.quals))[:30]
            r2 = DataRef(ref.name, ref.quals, ref.subs, None, ref.loc)
            r2.item = it
            subs = [self.int_expr(x) for x in ref.subs if x != 'ALL'][:3]
            args = subs + ['0'] * (3 - len(subs))
            fill = (f"cob_dbg_data({d.di}, {line}, {_c_str(name)}, {self.data_ptr(r2)}, {self.size_expr(it)}, "
                    f"{len(subs)}, {args[0]}, {args[1]}, {args[2]});")
        self.dbg_invoke(dsec, fill)

    # ---------------------------------------------------------------- PERFORM VARYING / UNTIL
    def dbg_perf_hooks(self, nodes):
        d = self.dbg
        if d is None or not d.data or self.dbg_in_debug_section():
            return []
        refs = []
        self.dbg_walk(nodes, refs)
        out = []
        seen = set()
        for ref in refs:
            it = self.dbg_item(ref)
            ent = d.data.get(id(it)) if it is not None else None
            if ent is not None and id(it) not in seen:
                seen.add(id(it))
                out.append(('data', ref, it, ent[0]))
        return out

    def dbg_perf(self, s, *nodes):
        """Hooks after an initialization or modification in PERFORM VARYING."""
        for h in self.dbg_perf_hooks(list(nodes)):
            self.dbg_hook(h, s.loc.line)

    def cond_open(self, s, cond, neg=False):
        """Emit 'if (cond) {' for a PERFORM UNTIL condition, running the hooks
        of the identifiers it references right after it is evaluated. Returns
        the number of braces to close."""
        em = self.em
        c = self.cond(cond)
        hooks = self.dbg_perf_hooks([cond])
        if not hooks:
            em(f"if ({'!' if neg else ''}({c})) {{")
            return 1
        em("{")
        em(f"int cob_dc = {c};")
        for h in hooks:
            self.dbg_hook(h, s.loc.line)
        em(f"if ({'!' if neg else ''}cob_dc) {{")
        return 2
