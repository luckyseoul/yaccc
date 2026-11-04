# SPDX-License-Identifier: MIT
"""-fdump: a program's data described for the runtime (a mixin of CodeGen).

With -fdump, each program gets a static table of cob_dump_item entries --
section headings, each file's heading, the items of the sections asked for
in the order they are written, and the indexes -- which it registers when
it starts. After a runtime error the runtime (runtime/cobrt_dump.c) walks
the tables of the active programs and writes out every item's value.

A record's storage is either an array (WORKING-STORAGE, a file's record
area) or a pointer (LINKAGE, LOCAL-STORAGE, BASED): for a pointer the table
holds the pointer's address, read when the dump is written. A RECURSIVE
program's LOCAL-STORAGE and LINKAGE pointers are local to each call, so its
table leaves them out.
"""
from .data import IndexName

# the USAGE as a programmer writes it, for the normalised names
_USAGE_WORDS = {'PACKED': 'COMP-3', 'BINARY': 'COMP', 'FLOAT': 'COMP-1', 'DOUBLE': 'COMP-2'}

# the scopes of -fdump, as cobc names them
DUMP_SCOPES = {'ALL', 'WS', 'LO', 'LS', 'FD'}


def parse_dump_scopes(text):
    """'ALL' or a comma-separated list of WS, LO, LS (LINKAGE) and FD; RD and
    SC (the REPORT and SCREEN sections) have nothing to show here."""
    scopes = set()
    for w in (text or 'ALL').replace(' ', '').upper().split(','):
        if not w:
            continue
        if w in ('RD', 'SC'):
            raise ValueError(f"-fdump={w}: the {'REPORT' if w == 'RD' else 'SCREEN'} SECTION "
                             "is not dumped; use ALL, WS, LO, LS or FD")
        if w not in DUMP_SCOPES:
            raise ValueError(f"-fdump: unknown scope '{w}' (ALL, WS, LO, LS or FD)")
        scopes.add(w)
    if 'ALL' in scopes:
        scopes = {'WS', 'LO', 'LS', 'FD'}
    return scopes


class DumpGen:
    def dump_desc(self, it):
        parts = []
        if it.pic is not None:
            parts.append(it.pic.src)
        u = getattr(it, 'usage', None)
        if u and u != 'DISPLAY':
            parts.append(_USAGE_WORDS.get(u, u))
        oc = it.occurs
        if oc is not None:
            if oc.depending is not None:
                top = 'UNBOUNDED' if getattr(oc, 'unbounded', False) else oc.max
                parts.append(f"OCCURS {oc.min} TO {top} DEPENDING ON {oc.depending.name}")
            else:
                parts.append(f"OCCURS {oc.max}")
        if it.redefines is not None:
            parts.append(f"REDEFINES {it.redefines.name or 'FILLER'}")
        if getattr(it, 'based', False) and it.level in (1, 77):
            parts.append('BASED')
        return ' '.join(parts)

    def dump_items(self, root, base, ptr, rows, index_rows, where):
        """The rows of a record and everything under it, in order; returns
        nothing, appends to rows (dicts until the C is written)."""
        def walk(it, depth):
            if it.level == 66:
                return
            row = {'kind': 'COB_DUMP_ITEM', 'level': it.level, 'depth': depth,
                   'ptr': 1 if (depth == 0 and ptr) else 0, 'name': it.name,
                   'desc': self.dump_desc(it), 'base': base if depth == 0 else None,
                   'offset': it.offset, 'size': it.size, 'item': it,
                   'occurs': 0, 'odo': None, 'attr': None}
            if it.occurs is not None:
                row['occurs'] = min(it.occurs.max, 1 << 30)
                if it.occurs.depending is not None:
                    row['odo'] = it.occurs.depending
                for nm, _loc in it.occurs.indexes:
                    for ix in self.ctx.names.get(nm, []):
                        if isinstance(ix, IndexName) and ix.parent is it and ix.cname:
                            index_rows.append({'kind': 'COB_DUMP_INDEX', 'name': nm,
                                               'desc': f"of {it.name or 'FILLER'}",
                                               'base': f"&{ix.cname}"})
            if not it.children:
                row['attr'] = '&' + self.item_attr(it)
            at = len(rows)
            rows.append(row)
            for c in it.children:
                walk(c, depth + 1)
            row['span'] = len(rows) - at
        walk(root, 0)

    def gen_dump_table(self, prog):
        """The program's table, as (symbol, entries), or None without -fdump."""
        scopes = getattr(self.opts, 'dump', None)
        if not scopes:
            return None
        from .codegen import c_string
        ctx = self.ctx
        rows, index_rows = [], []

        def heading(kind, text, base=None):
            rows.append({'kind': kind, 'name': text, 'base': base})

        if 'FD' in scopes and ctx.files:
            heading('COB_DUMP_SECTION', 'FILE SECTION')
            for fi in ctx.files.values():
                fd = fi.fd
                heading('COB_DUMP_FILE', 'SD' if fi.is_sort else 'FD', f"&{fi.sym}")
                for r in fd.records:
                    self.dump_items(r, r.storage, False, rows, index_rows, 'FD')
        recursive = prog.is_recursive
        pointer_syms = set()
        for sym, _size, _r in ctx.local_blocks + ctx.link_blocks:
            pointer_syms.add(sym)
        for scope, title, roots in (('WS', 'WORKING-STORAGE SECTION', prog.working),
                                    ('LO', 'LOCAL-STORAGE SECTION', prog.local),
                                    ('LS', 'LINKAGE SECTION', prog.linkage)):
            if scope not in scopes or not roots:
                continue
            heading('COB_DUMP_SECTION', title)
            if recursive and scope in ('LO', 'LS'):
                heading('COB_DUMP_NOTE', 'each call of a RECURSIVE program has its own: not shown')
                continue
            for r in roots:
                if r.renames or r.level == 66 or r.level == 88:
                    continue
                sym = r.storage
                if sym is None:
                    continue
                based = getattr(r, 'based', False) or getattr(r, 'based_sym', None)
                ptr = sym in pointer_syms or bool(based)
                if ptr and recursive and sym in pointer_syms:
                    continue
                self.dump_items(r, sym, ptr, rows, index_rows, scope)
        if index_rows:
            heading('COB_DUMP_SECTION', 'INDEXES')
            rows.extend(index_rows)
        if not rows:
            return None
        # DEPENDING ON items: the row of the item that holds the count
        at = {id(r['item']): k for k, r in enumerate(rows) if 'item' in r}
        lines = []
        for r in rows:
            odo = -1
            if r.get('odo') is not None:
                try:
                    dep = self.resolve(r['odo'])
                except Exception:
                    dep = None
                odo = at.get(id(dep), -1) if dep is not None else -1
            base = r.get('base')
            if base and r['kind'] == 'COB_DUMP_ITEM':
                base = f"&{base}" if r.get('ptr') else base
            name = r.get('name')
            lines.append("\t{ %s, %d, %d, %d, %d, %s, %s, %s, %d, %d, %d, %d, %s }," % (
                r['kind'], r.get('level', 0), r.get('depth', 0), r.get('ptr', 0), r.get('span', 1),
                c_string(name) if name else 'NULL',
                c_string(r['desc']) if r.get('desc') else 'NULL',
                f"(const void *){base}" if base else 'NULL',
                r.get('offset', 0), r.get('size', 0), r.get('occurs', 0), odo,
                r.get('attr') or 'NULL'))
        sym = self.sym('cob_dump_')
        self.glob.append(f"static const cob_dump_item {sym}[] = {{")
        self.glob.extend(lines)
        self.glob.append("};")
        return sym, len(rows)
