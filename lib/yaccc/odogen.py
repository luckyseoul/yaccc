# SPDX-License-Identifier: MIT
"""OCCURS DEPENDING ON at run time (a mixin of CodeGen): the current size of
a group that holds a variable table, and where the items after one are.

A table with OCCURS DEPENDING ON takes up as many occurrences as its
DEPENDING ON item says. Without -fodoslide it does so, as with cobc
(-fcomplex-odo, and its ibm and mf dialects), only when nothing follows it
in its group: a table with items after it keeps its maximum size, and they
their places. A group that ends with a variable table, or with a group that
does, is variable in size itself, and the items after that group follow
its current end. With -fodoslide (IBM Enterprise COBOL's layout, and Micro
Focus's ODOSLIDE) every such table takes its current size, and all that
follows it in the record moves up with it.

So in C an item's size is its static size less what the variable tables
in it have shrunk by, its offset its static offset less what the variable
tables before it have, and a table whose elements hold a variable table has
a variable stride. A record without a variable table has none of these
terms.

A DEPENDING ON item inside a table element gives each element its own
count: it is read with the subscripts of the reference being made, and
where there are none (the size of the whole table) the table counts at its
maximum.
"""
from .data import DataItem
from .errors import CompileError
from .nodes import DataRef


def storage_children(it):
    """The children of an item that take up storage of their own: not
    level 66 or 88 items, nor REDEFINES."""
    return [c for c in it.children if c.level not in (66, 88) and c.redefines is None]


def c_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


class OdoLayout:
    def odo_init(self):
        self._odo_may = {}          # id(item) -> can its extent vary at all
        self._odo_busy = set()      # tables whose count is being worked out
        self._odo_inside = {}       # id(item) -> a variable table's ODO item is in it

    # ------------------------------------------------------------ structure
    def odo_varies(self, t):
        """Does the table t take up only its current number of occurrences?"""
        occ = t.occurs
        if occ is None or occ.depending is None or getattr(occ, 'unbounded', False):
            return False
        if getattr(self.opts, 'odoslide', False) or t.parent is None:
            return True
        sib = storage_children(t.parent)
        return bool(sib) and sib[-1] is t

    def odo_may_vary(self, it):
        """Can the extent of it ever differ from its static extent?"""
        key = id(it)
        v = self._odo_may.get(key)
        if v is None:
            v = self.odo_varies(it) or any(self.odo_may_vary(c) for c in storage_children(it))
            self._odo_may[key] = v
        return v

    @staticmethod
    def odo_root(it):
        while it.parent is not None:
            it = it.parent
        return it

    def odo_object_inside(self, it):
        """Is the DEPENDING ON item of a variable table of it inside it? A
        receiving group that holds its own counter is moved to at its full
        size, as the standard says."""
        key = id(it)
        v = self._odo_inside.get(key)
        if v is None:
            inside = {id(x) for x in it.walk()}
            v = False
            for t in it.walk():
                if t is not it and self.odo_varies(t):
                    try:
                        obj = self.resolve(t.occurs.depending)
                    except CompileError:
                        continue
                    if id(obj) in inside:
                        v = True
                        break
            self._odo_inside[key] = v
        return v

    # ------------------------------------------------------------ C expressions
    def odo_count(self, t, loc, ctx=None, check=True):
        """C expression: the current occurrences of the variable table t,
        checked against its bounds when the ODO checks are on; None when its
        DEPENDING ON item is in a table element ctx gives no subscript for.
        ctx maps id(table) to a C expression for its (1-based) subscript."""
        occ = t.occurs
        dep = occ.depending
        obj = self.resolve(dep)
        chain = obj.occurs_chain() if isinstance(obj, DataItem) else []
        if chain:
            if ctx is None or any(id(c) not in ctx for c in chain):
                return None
            from .codegen import CVar
            ref = DataRef(dep.name, dep.quals, [CVar(ctx[id(c)]) for c in chain], None, dep.loc)
            ref.item = obj
            ref.implicit = True     # not a reference the source makes, for -Xref
        else:
            ref = dep
        oname = obj.name or 'FILLER'
        tname = t.name or 'FILLER'
        if id(t) in self._odo_busy:
            raise CompileError(f"'{oname}' follows the table '{tname}' whose size it gives, "
                               f"so its place depends on its own value", dep.loc)
        self._odo_busy.add(id(t))
        try:
            cur = self.int_expr(ref)
        finally:
            self._odo_busy.discard(id(t))
        if check and self.checks_on(loc, 'odo'):
            top = 2147483647 if getattr(occ, 'unbounded', False) else occ.max
            cur = (f"cob_chk_odo({cur}, {occ.min}, {top}, {c_str(oname)}, "
                   f"{c_str(tname)}, {self.locstr(loc)})")
        return cur

    def odo_shrink(self, it, loc, ctx=None):
        """C expression for how much less than its static extent (all its
        occurrences) the item takes up now, or None when it can't vary."""
        if not self.odo_may_vary(it):
            return None
        occ = it.occurs
        inner = self.odo_elem_shrink(it, loc, ctx)
        if occ is None:
            return inner
        cur = self.odo_count(it, loc, ctx) if self.odo_varies(it) else None
        if cur is not None:
            if inner is None:
                return f"(({occ.max} - {cur}) * {it.size})"
            return f"({occ.max * it.size} - {cur} * ({it.size} - {inner}))"
        if inner is None:
            return None
        return f"({occ.max} * {inner})"

    def odo_elem_shrink(self, it, loc, ctx=None):
        """... of one element of a table (or of the item, when it is none):
        what the variable tables in it have shrunk by."""
        parts = [p for p in (self.odo_shrink(c, loc, ctx) for c in storage_children(it))
                 if p is not None]
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else '(' + ' + '.join(parts) + ')'

    def odo_stride(self, t, loc, ctx=None):
        """C expression for the distance between the elements of table t."""
        inner = self.odo_elem_shrink(t, loc, ctx)
        return str(t.size) if inner is None else f"({t.size} - {inner})"

    def odo_before(self, it, loc, ctx=None, stop=None):
        """What the variable tables before it in its record (or in stop, an
        ancestor) have shrunk by: C expressions to take off its static
        offset."""
        if not self.odo_may_vary(self.odo_root(it) if stop is None else stop):
            return []
        terms = []
        node = it
        while node.parent is not None and node is not stop:
            for s in storage_children(node.parent):
                if s.offset >= node.offset:
                    break
                x = self.odo_shrink(s, loc, ctx)
                if x is not None:
                    terms.append(x)
            node = node.parent
        return terms

    def odo_ctx(self, chain, subs):
        """A subscript context from a reference's tables and their subscripts'
        C expressions."""
        return {id(occ): s for occ, s in zip(chain, subs)}

    def variably_located(self, it):
        """Does where it is depend on a variable table before it?"""
        root = self.odo_root(it)
        if not self.odo_may_vary(root):
            return False
        node = it
        while node.parent is not None:
            for s in storage_children(node.parent):
                if s.offset >= node.offset:
                    break
                if self.odo_may_vary(s):
                    return True
            node = node.parent
        return False
