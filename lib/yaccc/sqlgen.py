# SPDX-License-Identifier: MIT
"""Embedded SQL: the C for an EXEC SQL statement (a mixin of CodeGen).

Each statement is one call into the runtime (runtime/cobrt_sql.c) with its
host variables as arrays of cob_sql_hv -- a field, its indicator variable,
and for a VARCHAR (a group of two level-49 items, length then text) the
length item -- followed by the WHENEVER tests in force where it stands.
Cursor and statement names are the program's own: the runtime sees them
qualified by the program's name.
"""
from .data import DataItem, T_ALNUM, T_ALPHA, T_NUM_BINARY, T_NUM_COMP5, T_NUM_DISPLAY, T_NUM_PACKED
from .errors import CompileError
from .esql import HV_MARK, keyed_select
from .nodes import DataRef, StrLit

_WHENEVER = {'SQLERROR': 'cob_sql_code() < 0', 'NOT FOUND': 'cob_sql_code() == 100',
             'SQLWARNING': 'cob_sql_warn()'}


def _c_string(s):
    out = ['"']
    for ch in s.encode('latin-1'):
        c = chr(ch)
        if c in '"\\':
            out.append('\\' + c)
        elif 32 <= ch < 127 and c != '?':
            out.append(c)
        else:
            out.append(f'\\{ch:03o}')
    out.append('"')
    return ''.join(out)


class SqlGen:
    def sql_name(self, name):
        return _c_string(f"{self.prog.name}:{name}")

    def sql_ca(self):
        """Declare cob_ca, where a statement's outcome goes: the items of the
        program's SQLCA, found by name, or the SQLCODE and SQLSTATE it
        declares on their own. An SQLCA laid out otherwise than DB2's (OCESQL
        has one without SQLEXT) still gets each item in its place."""
        cache = self.__dict__.setdefault('_sql_ca', {})
        key = id(self.prog)
        if key not in cache:
            names = self.ctx.names
            recs = [it for it in names.get('SQLCA', []) if isinstance(it, DataItem)]
            items = {}
            if recs:
                rec = recs[0]
                for it in rec.walk():
                    if it.name and it.name not in items:
                        items[it.name] = it
            else:
                for nm in ('SQLCODE', 'SQLSTATE'):
                    its = [it for it in names.get(nm, []) if isinstance(it, DataItem)]
                    if its:
                        items[nm] = its[0]

            def f(nm):
                it = items.get(nm)
                return self._item_field(it) if it is not None else 'NULL'
            errd = items.get('SQLERRD')
            nerrd = errd.occurs.max if errd is not None and errd.occurs else (1 if errd else 0)
            cache[key] = (f"{{{f('SQLCAID')}, {f('SQLCABC')}, {f('SQLCODE')}, {f('SQLERRML')}, "
                          f"{f('SQLERRMC')}, {f('SQLERRP')}, {f('SQLERRD')}, {nerrd}, {f('SQLWARN')}, "
                          f"{f('SQLSTATE')}}}")
        self.em(f"cob_sql_ca cob_ca = {cache[key]};")
        return '&cob_ca'

    def _item_field(self, it, extra=0):
        return f"CF({it.storage} + {it.offset + extra}, {it.size}, &{self.item_attr(it)})"

    @staticmethod
    def _is_varchar(it):
        kids = [c for c in it.children if c.level not in (66, 88)]
        return (len(kids) == 2 and all(c.level == 49 for c in kids)
                and kids[0].type in (T_NUM_BINARY, T_NUM_COMP5, T_NUM_DISPLAY, T_NUM_PACKED)
                and kids[1].type in (T_ALNUM, T_ALPHA) and not kids[1].children)

    def _hv_items(self, it):
        """A host structure's host variables: its elementary items, and its
        VARCHAR groups as one each."""
        out = []
        for c in it.children:
            if c.level in (66, 88) or c.redefines is not None:
                continue
            if c.occurs:
                raise CompileError(f"host structure '{it.name}': '{c.name or 'FILLER'}' has OCCURS; "
                                   "a table is not a host variable", c.loc)
            if c.children and self._is_varchar(c):
                out.append(('varchar', c))
            elif c.children:
                out.extend(self._hv_items(c))
            else:
                out.append(('item', c))
        return out

    def _indicators(self, hv, count):
        """The indicator for each of count host variables from one reference:
        an indicator array (OCCURS) or group gives one each."""
        if hv.ind is None:
            return ['NULL'] * count
        ind = self.resolve(hv.ind)
        if count == 1 and not (isinstance(ind, DataItem) and (ind.occurs or ind.children)):
            return [self.field(hv.ind)]
        if isinstance(ind, DataItem) and ind.occurs and not ind.children:
            n = ind.occurs.max
            return [self._item_field(ind, k * ind.size) if k < n else 'NULL' for k in range(count)]
        if isinstance(ind, DataItem) and ind.children:
            leaves = [c for c in ind.walk() if not c.children and c.level not in (66, 88)
                      and not c.occurs]
            return [self._item_field(leaves[k]) if k < len(leaves) else 'NULL' for k in range(count)]
        return [self.field(hv.ind)] + ['NULL'] * (count - 1)

    def sql_entries(self, hv):
        """(field, indicator, length) C expressions for one host variable."""
        it = self.resolve(hv.ref)
        if not isinstance(it, DataItem) or it.level in (66, 88):
            raise CompileError(f"'{hv.ref.name}' is not a data item, so it can't be a host variable",
                               hv.ref.loc)
        if it.children and self._is_varchar(it) and not hv.ref.subs:
            kids = [c for c in it.children if c.level not in (66, 88)]
            return [(self._item_field(kids[1]), self._indicators(hv, 1)[0], self._item_field(kids[0]))]
        if it.children and not hv.ref.subs and not it.occurs:
            parts = self._hv_items(it)
            inds = self._indicators(hv, len(parts))
            out = []
            for (kind, c), ind in zip(parts, inds):
                if kind == 'varchar':
                    kids = [k for k in c.children if k.level not in (66, 88)]
                    out.append((self._item_field(kids[1]), ind, self._item_field(kids[0])))
                else:
                    out.append((self._item_field(c), ind, 'NULL'))
            return out
        return [(self.field(hv.ref), self._indicators(hv, 1)[0], 'NULL')]

    def sql_text(self, text, hvs):
        """The statement's text with a ? for each value of each host variable."""
        parts = text.split(HV_MARK)
        if len(parts) - 1 != len(hvs):
            raise CompileError("EXEC SQL: host variables and their places differ in number", None)
        out = [parts[0]]
        for hv, rest in zip(hvs, parts[1:]):
            out.append(', '.join(['?'] * len(self.sql_entries(hv))))
            out.append(rest)
        return _c_string(''.join(out))

    def sql_array(self, name, hvs):
        """Declare the cob_sql_hv array name; its length."""
        em = self.em
        rows = [e for hv in hvs for e in self.sql_entries(hv)]
        if not rows:
            em(f"const cob_sql_hv *{name} = NULL;")
            return 0
        em(f"cob_sql_hv {name}[{len(rows)}] = {{")
        for f, ind, ln in rows:
            em(f"\t{{{f}, {ind}, {ln}}},")
        em("};")
        return len(rows)

    def sql_operand(self, x):
        """A CONNECT operand or dynamic statement text as a field."""
        if x is None:
            return 'NULL'
        if isinstance(x, StrLit):
            return self.lit_str(x.value) if x.value else 'NULL'
        f, _ind, _ln = self.sql_entries(x)[0]
        return f

    def g_ExecSql(self, s):
        em = self.em
        k = s.kind
        prog = self.prog
        em("{")
        em.ind += 1
        ca = self.sql_ca()
        if k == 'CONNECT':
            a = s.args
            em(f"cob_sql_connect({ca}, {self.sql_operand(a.get('target'))}, "
               f"{self.sql_operand(a.get('user'))}, {self.sql_operand(a.get('password'))}, "
               f"{self.sql_operand(a.get('name'))});")
        elif k == 'DISCONNECT':
            em(f"cob_sql_disconnect({ca}, {self.sql_operand(s.args.get('name'))}, {1 if s.all else 0});")
        elif k == 'SET CONNECTION':
            em(f"cob_sql_set_connection({ca}, {self.sql_operand(s.args.get('name'))});")
        elif k in ('COMMIT', 'ROLLBACK'):
            em(f"cob_sql_end_work({ca}, {1 if k == 'ROLLBACK' else 0}, {1 if s.release else 0});")
        elif k == 'EXEC':
            nin = self.sql_array('cob_sqi', s.ins)
            nout = self.sql_array('cob_sqo', s.outs)
            em(f"cob_sql_exec({ca}, {self.sql_text(s.sql, s.ins)}, {nin}, cob_sqi, {nout}, cob_sqo);")
        elif k == 'CURRENT':
            self.sql_cursor(s)
            nin = self.sql_array('cob_sqi', s.ins)
            em(f"cob_sql_current({ca}, {self.sql_text(s.sql, s.ins)}, {self.sql_name(s.cursor)}, "
               f"{nin}, cob_sqi);")
        elif k == 'OPEN':
            cur = self.sql_cursor(s)
            nin = self.sql_array('cob_sqi', cur['ins'] + s.ins)
            keyed = s.cursor in prog.sql_keyed and cur['sql'] is not None
            if cur['sql'] is not None:
                text = keyed_select(cur['sql']) if keyed else cur['sql']
                sql, stmt = self.sql_text(text, cur['ins']), 'NULL'
            else:
                sql, stmt = 'NULL', self.sql_name(cur['stmt'])
            em(f"cob_sql_open({ca}, {self.sql_name(s.cursor)}, {sql}, {stmt}, {1 if keyed else 0}, "
               f"{1 if cur['hold'] else 0}, {nin}, cob_sqi);")
        elif k == 'FETCH':
            self.sql_cursor(s)
            nout = self.sql_array('cob_sqo', s.outs)
            em(f"cob_sql_fetch({ca}, {self.sql_name(s.cursor)}, {nout}, cob_sqo);")
        elif k == 'CLOSE':
            self.sql_cursor(s)
            em(f"cob_sql_close({ca}, {self.sql_name(s.cursor)});")
        elif k in ('PREPARE', 'IMMEDIATE'):
            if isinstance(s.text, StrLit):
                em(f"cob_sql_hv cob_sqt = {{{self.lit_str(s.text.value)}, NULL, NULL}};")
            else:
                f, ind, ln = self.sql_entries(s.text)[0]
                em(f"cob_sql_hv cob_sqt = {{{f}, {ind}, {ln}}};")
            if k == 'PREPARE':
                em(f"cob_sql_prepare({ca}, {self.sql_name(s.stmt)}, &cob_sqt);")
            else:
                em(f"cob_sql_immediate({ca}, &cob_sqt);")
        elif k == 'EXECUTE':
            nin = self.sql_array('cob_sqi', s.ins)
            nout = self.sql_array('cob_sqo', s.outs)
            em(f"cob_sql_execute({ca}, {self.sql_name(s.stmt)}, {nin}, cob_sqi, {nout}, cob_sqo);")
        else:
            raise CompileError(f"EXEC SQL: {k} is not handled", s.loc)
        em.ind -= 1
        em("}")
        for cond, act in s.whenever:
            em(f"if ({_WHENEVER[cond]}) {{")
            em.ind += 1
            self.stmts([act])
            em.ind -= 1
            em("}")

    def sql_cursor(self, s):
        cur = self.prog.sql_cursors.get(s.cursor)
        if cur is None:
            known = ', '.join(sorted(self.prog.sql_cursors)) or 'none'
            raise CompileError(f"EXEC SQL: cursor {s.cursor} is not declared (declared: {known})", s.loc)
        return cur
