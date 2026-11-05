# SPDX-License-Identifier: MIT
"""-t / -T FILE: the compile listing; -Xref: its cross-reference.

The listing is the source as written, every line numbered: the lines of each
copybook follow the COPY statement that brought them in, numbered in the
copybook and marked C, and each error and warning comes under the line it
is about. A data map follows -- each program's items with their offset,
size, PICTURE and USAGE -- and with -Xref, for every data item, index and
procedure, the lines that refer to it: a number alone is a line of the
source, NAME:n is line n of copybook NAME; * marks a reference that changes
the item, and P, G, A and S a procedure's PERFORM, GO TO, ALTER and SORT or
MERGE procedure.
"""
import datetime
import os

from . import source
from .data import DataItem, item_desc


def _key(path):
    return os.path.abspath(path) if path else path


def _all_programs(programs):
    for p in programs:
        yield p
        yield from _all_programs(getattr(p, 'nested', []) or [])


class Listing:
    def __init__(self, sources, includes, diags, programs, gen, version):
        self.sources = list(sources)    # the files compiled
        self.includes = includes        # [(file, line, copybook)] in the order found
        self.diags = diags              # [(kind, CompileError)]
        self.programs = list(_all_programs(programs or []))
        self.gen = gen                  # the CodeGen, with -Xref's references; None without
        self.version = version
        self.main = _key(self.sources[0]) if self.sources else None
        self.out = []

    def where(self, loc):
        """A line as the listing names it: the number alone in the first
        source, the file's name and the line otherwise."""
        if loc is None:
            return '?'
        f = getattr(loc, 'file', None)
        if f is None or _key(f) == self.main:
            return str(loc.line)
        return f"{os.path.basename(f)}:{loc.line}"

    def write(self, path):
        o = self.out
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        o.append(f"YACCC {self.version}  {' '.join(self.sources)}  {now}")
        self.source_part()
        for prog in self.programs:
            self.data_map(prog)
        if self.gen is not None:
            for prog in self.programs:
                self.cross_reference(prog)
        with open(path, 'w', encoding='latin-1', errors='replace') as f:
            f.write('\n'.join(o) + '\n')

    # ---------------------------------------------------------------- source
    def source_part(self):
        o = self.out
        by_line = {}
        for f, line, cpath in self.includes:
            by_line.setdefault((_key(f), line), []).append(cpath)
        diag_at, loose = {}, []
        for kind, e in self.diags:
            loc = getattr(e, 'loc', None)
            if loc is None or getattr(loc, 'file', None) is None:
                loose.append((kind, e))
            else:
                diag_at.setdefault((_key(loc.file), loc.line), []).append((kind, e))

        def emit(fpath, depth):
            try:
                raw = source.read_raw(fpath)
            except OSError:
                o.append(f"        (cannot read {fpath})")
                return
            k = _key(fpath)
            for n, text in enumerate(raw, 1):
                o.append(f"{n:6d}{'C' if depth else ' '} {text}")
                for kind, e in diag_at.get((k, n), []):
                    o.append(f"       *** {kind}: {e.msg}")
                for cpath in by_line.get((k, n), []):
                    if depth < 40:
                        rel = os.path.relpath(cpath)
                        o.append(f"       --- COPY {cpath if rel.startswith('..') else rel}")
                        emit(cpath, depth + 1)
                        o.append(f"       --- end of {os.path.basename(cpath)}")

        for src in self.sources:
            o.append('')
            o.append(f"SOURCE {src}")
            o.append('')
            emit(src, 0)
        for kind, e in loose:
            o.append(f"       *** {kind}: {e.msg}")
        nerr = sum(1 for k, _ in self.diags if k == 'error')
        nwarn = sum(1 for k, _ in self.diags if k == 'warning')
        o.append('')
        o.append(f"{nerr} error{'' if nerr == 1 else 's'}, {nwarn} warning{'' if nwarn == 1 else 's'}")

    # ---------------------------------------------------------------- data map
    @staticmethod
    def sections(prog):
        return [('FILE SECTION', [r for fd in prog.file_descs for r in fd.records]),
                ('WORKING-STORAGE SECTION', prog.working),
                ('LOCAL-STORAGE SECTION', prog.local),
                ('LINKAGE SECTION', prog.linkage)]

    def data_map(self, prog):
        o = self.out
        rows = []
        for title, roots in self.sections(prog):
            if not roots:
                continue
            rows.append((None, title))
            for r in roots:
                if r.level == 66 or r.renames:
                    continue
                for it in r.walk():
                    if it.level == 66:
                        continue
                    depth = 0
                    p = it.parent
                    while isinstance(p, DataItem):
                        depth += 1
                        p = p.parent
                    name = f"{'  ' * depth}{it.level:02d} {it.name or 'FILLER'}"
                    size = it.total_size() if it.occurs else it.size
                    rows.append((self.where(it.loc), (name, it.offset, size, item_desc(it))))
        w = max([4] + [len(r[0]) for r in rows if r[0] is not None])
        nw = max([14] + [len(r[1][0]) for r in rows if r[0] is not None])
        o.append('')
        o.append(f"DATA MAP OF {prog.name}")
        o.append(f"{'LINE':>{w}}  {'LEVEL AND NAME':<{nw}} {'OFFSET':>7} {'SIZE':>7}  PICTURE, USAGE, OCCURS")
        for where, row in rows:
            if where is None:
                o.append(f"{'':>{w}}  {row}")
                continue
            name, off, size, desc = row
            o.append(f"{where:>{w}}  {name:<{nw}} {off:>7} {size:>7}  {desc}".rstrip())

    # ---------------------------------------------------------------- cross-reference
    def refs_text(self, refs):
        """'12 14* COPYBK.cpy:3' for [(loc, mark)], one entry per line."""
        marks = {}
        order = []
        for loc, mark in refs:
            w = self.where(loc)
            if w not in marks:
                marks[w] = set()
                order.append((getattr(loc, 'file', None) is not None and _key(loc.file) != self.main,
                              getattr(loc, 'file', '') or '', loc.line, w))
            if mark:
                marks[w].add(mark)
        order.sort()
        return ' '.join(w + ''.join(sorted(marks[w])) for *_, w in order)

    def cross_reference(self, prog):
        gen = self.gen
        o = self.out
        refs = {}
        for it, loc, ref in gen.xref_refs:
            refs.setdefault(id(it), []).append((loc, '*' if id(ref) in gen.xref_changed else ''))
        procs = {}
        for p, loc, how in gen.xref_procs:
            procs.setdefault(id(p), []).append((loc, how))
        names = []
        for _title, roots in self.sections(prog):
            for r in roots:
                for it in r.walk():
                    if it.name and it.level != 66:
                        names.append((it.name, it))
                    for c in getattr(it, 'conditions', []) or []:
                        if c.name:
                            names.append((c.name, c))
        data_rows = []
        for nm, it in sorted(names, key=lambda x: (x[0], getattr(x[1].loc, 'line', 0))):
            data_rows.append((nm, self.where(it.loc), self.refs_text(refs.get(id(it), [])) or '(not referenced)'))
        # indexes resolve as IndexName objects, made by the code generator
        seen = set()
        for it, loc, ref in gen.xref_refs:
            if type(it).__name__ != 'IndexName' or id(it) in seen:
                continue
            if getattr(it, 'table', None) is None or not self.owned(prog, it.table):
                continue
            seen.add(id(it))
            data_rows.append((f"{it.name} (index)", self.where(getattr(it, 'loc', None)),
                              self.refs_text(refs.get(id(it), []))))
        proc_rows = []
        for sec in list(prog.declaratives) + list(prog.sections):
            for p in [sec] + list(sec.paragraphs):
                if getattr(p, 'name', None):
                    proc_rows.append((f"{p.name} SECTION" if p is sec else p.name, self.where(p.loc),
                                      self.refs_text(procs.get(id(p), []))))
        nw = max([12] + [len(r[0]) for r in data_rows + proc_rows])
        dw = max([7] + [len(r[1]) for r in data_rows + proc_rows])
        o.append('')
        o.append(f"CROSS-REFERENCE OF {prog.name}")
        o.append(f"{'DATA NAME':<{nw}} {'DEFINED':>{dw}}  REFERENCES (* changes it)")
        for nm, where, text in data_rows:
            o.append(f"{nm:<{nw}} {where:>{dw}}  {text}".rstrip())
        o.append('')
        o.append(f"{'PROCEDURE':<{nw}} {'DEFINED':>{dw}}  REFERENCES (P PERFORM, G GO TO, A ALTER, S SORT)")
        for nm, where, text in proc_rows:
            o.append(f"{nm:<{nw}} {where:>{dw}}  {text}".rstrip())

    def owned(self, prog, item):
        """The item is in one of the program's own sections."""
        rec = item
        while isinstance(getattr(rec, 'parent', None), DataItem):
            rec = rec.parent
        return any(rec is r for _t, roots in self.sections(prog) for r in roots)
