# SPDX-License-Identifier: MIT
"""Embedded SQL: what an EXEC SQL ... END-EXEC statement asks for.

The lexer hands over each statement's text as one EXECSQL token. This module
reads it: the host variables (:NAME, :GROUP.NAME, each with an indicator
variable as :NAME:IND or :NAME INDICATOR :IND), the statement's kind, and the
text the database is to run, with a ? where each input host variable stood.
The declarations -- INCLUDE SQLCA, BEGIN / END DECLARE SECTION, DECLARE
CURSOR / TABLE / STATEMENT, WHENEVER -- take effect here and run nothing.
"""
import re

from .errors import CompileError
from .nodes import (DataRef, ExecSql, GoTo, HostVar, Perform, ProcRef, StopRun, StrLit)

# DB2's SQLCA, for INCLUDE SQLCA: the runtime reaches its items by name, so a
# program's own SQLCA laid out otherwise works too
SQLCA_TEXT = """
       01 SQLCA.
          05 SQLCAID  PIC X(8) VALUE 'SQLCA'.
          05 SQLCABC  PIC S9(9) COMP-5 VALUE 136.
          05 SQLCODE  PIC S9(9) COMP-5 VALUE 0.
          05 SQLERRM.
             49 SQLERRML PIC S9(4) COMP-5 VALUE 0.
             49 SQLERRMC PIC X(70) VALUE SPACES.
          05 SQLERRP  PIC X(8) VALUE SPACES.
          05 SQLERRD  PIC S9(9) COMP-5 OCCURS 6 TIMES.
          05 SQLWARN.
             10 SQLWARN0 PIC X VALUE SPACE.
             10 SQLWARN1 PIC X VALUE SPACE.
             10 SQLWARN2 PIC X VALUE SPACE.
             10 SQLWARN3 PIC X VALUE SPACE.
             10 SQLWARN4 PIC X VALUE SPACE.
             10 SQLWARN5 PIC X VALUE SPACE.
             10 SQLWARN6 PIC X VALUE SPACE.
             10 SQLWARN7 PIC X VALUE SPACE.
          05 SQLEXT.
             10 SQLWARN8 PIC X VALUE SPACE.
             10 SQLWARN9 PIC X VALUE SPACE.
             10 SQLWARNA PIC X VALUE SPACE.
             10 SQLSTATE PIC X(5) VALUE '00000'.
"""

# where a host variable stood in a statement's text: the code generator puts
# a ? there for each value it gives (a host structure gives several)
HV_MARK = '\x03'

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>'(?:[^']|'')*'?)
  | (?P<qid>"(?:[^"]|"")*"?)
  | (?P<cast>::)
  | (?P<host>:[A-Za-z0-9_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_][A-Za-z0-9_-]*)*)
  | (?P<word>[A-Za-z_#$@][A-Za-z0-9_#$@]*)
  | (?P<num>\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?|\.\d+(?:[Ee][+-]?\d+)?)
  | (?P<op>.)
""", re.X | re.S)


class Sql:
    """One statement's tokens, (kind, text) pairs, white space dropped but
    remembered: a token that followed white space has ws=True."""

    def __init__(self, text, loc):
        self.loc = loc
        self.toks = []
        ws = False
        for m in _TOKEN.finditer(text):
            kind = m.lastgroup
            if kind == 'ws':
                ws = True
                continue
            val = m.group()
            if kind == 'host' and val.endswith('-'):
                # :A- 1 is :A minus 1: a name doesn't end with a hyphen
                name = val.rstrip('-')
                self.toks.append([kind, name, ws])
                for _ in range(len(val) - len(name)):
                    self.toks.append(['op', '-', False])
                ws = False
                continue
            self.toks.append([kind, val, ws])
            ws = False

    def words(self, i, n):
        """The upper-cased words at i.. (None where a token is not a word)."""
        return [t[1].upper() if t[0] == 'word' else None for t in self.toks[i:i + n]]

    def is_word(self, i, *words):
        return i < len(self.toks) and self.toks[i][0] == 'word' and self.toks[i][1].upper() in words

    def name_at(self, i):
        """A cursor or statement name at i -- SQL's letters, digits and _, or a
        COBOL-style name with hyphens written without spaces -- and the index
        after it."""
        if i >= len(self.toks) or self.toks[i][0] not in ('word', 'num'):
            raise CompileError("EXEC SQL: a name expected", self.loc)
        name = self.toks[i][1]
        i += 1
        while i + 1 < len(self.toks) and self.toks[i][1] == '-' and not self.toks[i][2] \
                and not self.toks[i + 1][2] and self.toks[i + 1][0] in ('word', 'num'):
            name += '-' + self.toks[i + 1][1]
            i += 2
        return name.upper(), i

    def host(self, i):
        """The host variable at i and its indicator: (HostVar, next index)."""
        t = self.toks[i]
        hv = HostVar(_ref(t[1][1:], self.loc))
        i += 1
        if i < len(self.toks) and self.toks[i][0] == 'host':
            hv.ind = _ref(self.toks[i][1][1:], self.loc)
            i += 1
        elif self.is_word(i, 'INDICATOR') and i + 1 < len(self.toks) and self.toks[i + 1][0] == 'host':
            hv.ind = _ref(self.toks[i + 1][1][1:], self.loc)
            i += 2
        return hv, i

    def host_list(self, i):
        """:a, :b:ib, ... at i: ([HostVar], next index)."""
        out = []
        while i < len(self.toks) and self.toks[i][0] == 'host':
            hv, i = self.host(i)
            out.append(hv)
            if i < len(self.toks) and self.toks[i][1] == ',' and i + 1 < len(self.toks) \
                    and self.toks[i + 1][0] == 'host':
                i += 1
        return out, i

    def text(self, start=0, end=None, ins=None):
        """The database's text for tokens start..end: each host variable (with
        its indicator) a place for its values, appended to ins. DB2's
        CURRENT DATE / TIME / TIMESTAMP are written as SQLite and PostgreSQL
        know them (CURRENT_DATE ...), and FETCH FIRST n ROWS ONLY as LIMIT n."""
        out = []
        toks = self.toks[start:end]
        i = 0
        while i < len(toks):
            kind, val, ws = toks[i]
            if out and ws:
                out.append(' ')
            up = val.upper() if kind == 'word' else None
            if up == 'CURRENT' and i + 1 < len(toks) and toks[i + 1][0] == 'word' and \
                    toks[i + 1][1].upper() in ('DATE', 'TIME', 'TIMESTAMP'):
                out.append('CURRENT_' + toks[i + 1][1].upper())
                i += 2
                continue
            if up == 'FETCH' and i + 1 < len(toks) and toks[i + 1][1].upper() in ('FIRST', 'NEXT'):
                j = i + 2
                count = '1'
                if j < len(toks) and toks[j][0] == 'num':
                    count = toks[j][1]
                    j += 1
                if j + 1 < len(toks) and toks[j][1].upper() in ('ROW', 'ROWS') and \
                        toks[j + 1][1].upper() == 'ONLY':
                    out.append('LIMIT ' + count)
                    i = j + 2
                    continue
            if kind == 'host':
                hv, j = Sql.host(_View(toks, self.loc), i)
                if ins is None:
                    raise CompileError("EXEC SQL: a host variable cannot stand here", self.loc)
                ins.append(hv)
                out.append(HV_MARK)         # a ? for each of its values, once they are known
                i = j
                continue
            out.append(val)
            i += 1
        return ''.join(out).strip()


class _View(Sql):
    """A slice of a statement's tokens, for Sql.host."""

    def __init__(self, toks, loc):
        self.toks = toks
        self.loc = loc


def _ref(name, loc):
    """:NAME or :GROUP.NAME as a data reference (NAME OF GROUP)."""
    parts = [p.upper() for p in name.split('.') if p]
    if not parts:
        raise CompileError("EXEC SQL: host variable name expected after ':'", loc)
    return DataRef(parts[-1], list(reversed(parts[:-1])), [], None, loc)


def _arg(sql, i):
    """A CONNECT operand: a host variable, a literal or a plain name."""
    t = sql.toks[i]
    if t[0] == 'host':
        hv, i = sql.host(i)
        return hv, i
    if t[0] == 'str':
        return StrLit(t[1][1:-1].replace("''", "'").encode('latin-1')), i + 1
    if t[0] == 'qid':
        return StrLit(t[1][1:-1].encode('latin-1')), i + 1
    name, i = sql.name_at(i)
    # a database name or path as written: name.db, dir/name.db, name@host:port
    while i < len(sql.toks) and not sql.toks[i][2] and sql.toks[i][1] in ('.', '/', '@', ':') \
            and i + 1 < len(sql.toks) and not sql.toks[i + 1][2]:
        name += sql.toks[i][1] + sql.toks[i + 1][1]
        i += 2
    return StrLit(name.encode('latin-1')), i


def _top_word(sql, start, *words):
    """The index of the first of words outside parentheses at start.., or -1."""
    depth = 0
    for i in range(start, len(sql.toks)):
        kind, val, _ = sql.toks[i]
        if val == '(':
            depth += 1
        elif val == ')':
            depth -= 1
        elif depth == 0 and kind == 'word' and val.upper() in words:
            return i
    return -1


# clauses a SELECT may end with that only DB2 knows; FOR UPDATE makes a
# cursor one that positioned UPDATE and DELETE can use, and stays as FOR
# UPDATE (DB2's OF list names columns, PostgreSQL's tables; the runtime drops
# the clause for SQLite, which locks the whole database instead)
_SELECT_TAIL = re.compile(r"""\s+(?:FOR\s+UPDATE(?:\s+OF\s+[\w\s,."]+?)?|FOR\s+(?:READ|FETCH)\s+ONLY
                              |WITH\s+(?:UR|CS|RS|RR)(?:\s+USE\s+AND\s+KEEP\s+\w+\s+LOCKS)?
                              |OPTIMIZE\s+FOR\s+\d+\s+ROWS?|QUERYNO\s+\d+|SKIP\s+LOCKED\s+DATA)\s*$""",
                          re.I | re.X)


def _cursor_select(text):
    """A SELECT without the DB2 clauses at its end: (text, for update)."""
    upd = False
    while True:
        m = _SELECT_TAIL.search(text)
        if not m:
            return text + (' FOR UPDATE' if upd else ''), upd
        if m.group().strip().upper().startswith('FOR UPDATE'):
            upd = True
        text = text[:m.start()]


def keyed_select(text):
    """The cursor's SELECT with the row key (\\x01, which the runtime names
    rowid or ctid) added after the select list, for WHERE CURRENT OF."""
    sql = Sql(text, None)
    i = _top_word(sql, 1, 'FROM')
    if i < 0:
        return text
    head = _View(sql.toks[:i], None)
    tail = _View(sql.toks[i:], None)
    return head.text(ins=[]) + ', \x01 ' + tail.text(ins=[])


class SqlParser:
    """The EXEC SQL part of the parser: a mixin of Parser."""

    def sql_state(self):
        st = getattr(self, '_sql', None)
        if st is None:
            st = self._sql = {'SQLERROR': None, 'NOT FOUND': None, 'SQLWARNING': None}
        return st

    def sql_data_entry(self):
        """An EXEC SQL statement among data description entries."""
        t = self.next()
        if self.peek().kind == '.':
            self.next()
        sql = Sql(t.val, t.loc)
        w = sql.words(0, 3)
        if w[:2] == ['INCLUDE', 'SQLCA']:
            self.prog.sql_ca = True
            self.toks[self.pos:self.pos] = self.sql_tokens(SQLCA_TEXT, t.loc)
            return
        if w[:2] == ['INCLUDE', 'SQLDA']:
            raise CompileError("EXEC SQL INCLUDE SQLDA: SQL descriptors are not supported", t.loc)
        st = self.sql_statement(sql)
        if st is not None:
            raise CompileError(f"EXEC SQL {w[0] or ''}: this statement belongs in the PROCEDURE DIVISION",
                               t.loc)

    def sql_tokens(self, text, loc):
        from .lexer import Lexer
        lx = Lexer()
        toks = []
        for line in text.strip('\n').split('\n'):
            lx.lex_text(line, loc, toks)
        return toks

    def sql_add_sqlca(self, prog):
        """A program that runs SQL and declares neither an SQLCA nor SQLCODE
        gets an SQLCA of its own, in WORKING-STORAGE."""
        for r in prog.working + prog.local + prog.linkage:
            for it in r.walk():
                if it.name in ('SQLCA', 'SQLCODE'):
                    return
        from .lexer import Tok
        save = self.toks, self.pos
        toks = self.sql_tokens(SQLCA_TEXT, prog.loc)
        self.toks, self.pos = toks + [Tok('EOF', '', prog.loc)], 0
        try:
            prog.working.extend(self.parse_entries())
        finally:
            self.toks, self.pos = save

    def parse_exec_sql(self):
        """An EXEC SQL statement in the PROCEDURE DIVISION."""
        t = self.next()
        st = self.sql_statement(Sql(t.val, t.loc))
        if st is None:
            from .nodes import Continue
            return Continue(t.loc)
        self.prog.sql_used = True
        st.whenever = [(cond, act) for cond, act in self.sql_state().items() if act is not None]
        return st

    def sql_statement(self, sql):
        """The ExecSql node for a statement, or None for a declaration."""
        loc = sql.loc
        w = sql.words(0, 4)
        n = len(sql.toks)
        if not n:
            raise CompileError("EXEC SQL: empty statement", loc)
        first = w[0]
        prog = self.prog
        if first in ('BEGIN', 'END') and w[1:3] == ['DECLARE', 'SECTION']:
            return None
        if first == 'INCLUDE':
            if w[1] == 'SQLCA':
                prog.sql_ca = True
                return None             # the PROCEDURE DIVISION: SQLCA is added at the end
            raise CompileError("EXEC SQL INCLUDE belongs in the DATA DIVISION", loc)
        if first == 'WHENEVER':
            return self.sql_whenever(sql)
        if first == 'DECLARE':
            name, i = sql.name_at(1)
            j = _top_word(sql, i, 'CURSOR', 'TABLE', 'STATEMENT', 'STATEMENTS')
            if j >= 0 and sql.toks[j][1].upper() == 'CURSOR':
                self.sql_declare_cursor(sql, name, j + 1)
                return None
            if j >= 0 or sql.is_word(i, 'GLOBAL'):
                if sql.is_word(i, 'GLOBAL'):    # DECLARE GLOBAL TEMPORARY TABLE runs
                    return ExecSql(loc, 'EXEC', sql.text(ins=[]))
                return None
            raise CompileError("EXEC SQL DECLARE: CURSOR, TABLE or STATEMENT expected", loc)
        if first == 'CONNECT':
            return self.sql_connect(sql)
        if first == 'DISCONNECT':
            st = ExecSql(loc, 'DISCONNECT')
            if n > 1:
                if sql.is_word(1, 'ALL'):
                    st.all = True
                elif not sql.is_word(1, 'CURRENT'):
                    st.args['name'], _ = _arg(sql, 1)
            return st
        if first == 'SET' and sql.is_word(1, 'CONNECTION'):
            st = ExecSql(loc, 'SET CONNECTION')
            st.args['name'], _ = _arg(sql, 2)
            return st
        if first == 'SET' and n > 2 and sql.toks[1][0] == 'host':
            # SET :hv = expression: the expression's value, as SELECT gives it
            outs, i = sql.host_list(1)
            if i >= n or sql.toks[i][1] != '=':
                raise CompileError("EXEC SQL SET: '=' expected", loc)
            st = ExecSql(loc, 'EXEC')
            st.sql = 'SELECT ' + sql.text(i + 1, ins=st.ins)
            st.outs = outs
            return st
        if first in ('COMMIT', 'ROLLBACK'):
            i = 1
            if sql.is_word(i, 'WORK', 'TRANSACTION', 'TRAN'):
                i += 1
            if sql.is_word(i, 'TO'):           # ROLLBACK TO SAVEPOINT x: as written
                return ExecSql(loc, 'EXEC', sql.text(ins=[]))
            st = ExecSql(loc, first)
            if sql.is_word(i, 'RELEASE'):
                st.release = True
                i += 1
            if i < n:
                raise CompileError(f"EXEC SQL {first}: unexpected '{sql.toks[i][1]}'", loc)
            return st
        if first == 'OPEN':
            name, i = sql.name_at(1)
            st = ExecSql(loc, 'OPEN', cursor=name)
            if sql.is_word(i, 'USING'):
                if sql.is_word(i + 1, 'DESCRIPTOR'):
                    raise CompileError("EXEC SQL OPEN ... USING DESCRIPTOR: SQL descriptors are not "
                                       "supported", loc)
                st.ins, i = sql.host_list(i + 1)
            if i < n:
                raise CompileError(f"EXEC SQL OPEN: unexpected '{sql.toks[i][1]}'", loc)
            return st
        if first == 'FETCH':
            i = 1
            if sql.is_word(i, 'NEXT'):
                i += 1
            elif sql.is_word(i, 'PRIOR', 'FIRST', 'LAST', 'ABSOLUTE', 'RELATIVE', 'BEFORE', 'AFTER',
                             'CURRENT', 'ROWSET'):
                raise CompileError(f"EXEC SQL FETCH {sql.toks[i][1].upper()}: only FETCH NEXT is "
                                   "supported", loc)
            if sql.is_word(i, 'FROM', 'IN'):
                i += 1
            name, i = sql.name_at(i)
            st = ExecSql(loc, 'FETCH', cursor=name)
            if sql.is_word(i, 'INTO'):
                st.outs, i = sql.host_list(i + 1)
            elif sql.is_word(i, 'USING'):
                raise CompileError("EXEC SQL FETCH ... USING DESCRIPTOR: SQL descriptors are not "
                                   "supported", loc)
            if i < n:
                raise CompileError(f"EXEC SQL FETCH: unexpected '{sql.toks[i][1]}'", loc)
            return st
        if first == 'CLOSE':
            name, i = sql.name_at(1)
            return ExecSql(loc, 'CLOSE', cursor=name)
        if first == 'PREPARE':
            name, i = sql.name_at(1)
            if sql.is_word(i, 'INTO'):
                raise CompileError("EXEC SQL PREPARE ... INTO: SQL descriptors are not supported", loc)
            if not sql.is_word(i, 'FROM'):
                raise CompileError("EXEC SQL PREPARE: FROM expected", loc)
            st = ExecSql(loc, 'PREPARE', stmt=name)
            st.text, _ = _arg(sql, i + 1)
            return st
        if first == 'EXECUTE' and sql.is_word(1, 'IMMEDIATE'):
            st = ExecSql(loc, 'IMMEDIATE')
            st.text, _ = _arg(sql, 2)
            return st
        if first == 'EXECUTE':
            name, i = sql.name_at(1)
            st = ExecSql(loc, 'EXECUTE', stmt=name)
            while i < n:
                if sql.is_word(i, 'USING'):
                    st.ins, i = sql.host_list(i + 1)
                elif sql.is_word(i, 'INTO'):
                    st.outs, i = sql.host_list(i + 1)
                else:
                    raise CompileError(f"EXEC SQL EXECUTE: unexpected '{sql.toks[i][1]}'", loc)
            return st
        if first in ('SELECT', 'WITH', 'VALUES'):
            return self.sql_select(sql)
        if first in ('UPDATE', 'DELETE'):
            i = _top_word(sql, 1, 'CURRENT')
            if i > 0 and sql.is_word(i + 1, 'OF') and sql.is_word(i - 1, 'WHERE'):
                name, j = sql.name_at(i + 2)
                st = ExecSql(loc, 'CURRENT', cursor=name)
                head = sql.text(0, i, ins=st.ins)
                st.sql = head + ' \x01 = ?'
                if j < n:
                    raise CompileError(f"EXEC SQL {first} ... WHERE CURRENT OF: unexpected "
                                       f"'{sql.toks[j][1]}'", loc)
                prog.sql_keyed.add(name)
                return st
        st = ExecSql(loc, 'EXEC')
        st.sql = sql.text(ins=st.ins)
        return st

    def sql_select(self, sql):
        """SELECT ... INTO :a, :b FROM ...: the INTO list comes out, and the
        statement must find one row. VALUES ... INTO is a SELECT too."""
        st = ExecSql(sql.loc, 'EXEC')
        i = _top_word(sql, 1, 'INTO')
        if i > 0 and i + 1 < len(sql.toks) and sql.toks[i + 1][0] == 'host':
            st.outs, j = sql.host_list(i + 1)
            head = sql.text(0, i, ins=st.ins)
            tail = sql.text(j, ins=st.ins)
            text = (head + ' ' + tail).strip()
        else:
            text = sql.text(ins=st.ins)
        text, _upd = _cursor_select(text)
        if sql.is_word(0, 'VALUES'):
            text = 'SELECT ' + text[len('VALUES'):].strip()
        st.sql = text
        return st

    def sql_declare_cursor(self, sql, name, i):
        hold = False
        while i < len(sql.toks) and not sql.is_word(i, 'FOR'):
            if sql.is_word(i, 'WITH') and sql.is_word(i + 1, 'HOLD'):
                hold = True
            i += 1
        if not sql.is_word(i, 'FOR'):
            raise CompileError(f"EXEC SQL DECLARE {name} CURSOR: FOR expected", sql.loc)
        i += 1
        cur = {'loc': sql.loc, 'hold': hold, 'ins': [], 'sql': None, 'stmt': None, 'update': False}
        if i < len(sql.toks) and not sql.is_word(i, 'SELECT', 'WITH', 'VALUES') and sql.toks[i][1] != '(':
            cur['stmt'], j = sql.name_at(i)
            if j < len(sql.toks):
                raise CompileError(f"EXEC SQL DECLARE {name} CURSOR FOR {cur['stmt']}: unexpected "
                                   f"'{sql.toks[j][1]}'", sql.loc)
        else:
            text = sql.text(i, ins=cur['ins'])
            cur['sql'], cur['update'] = _cursor_select(text)
        self.prog.sql_cursors[name] = cur
        if cur['update']:
            self.prog.sql_keyed.add(name)

    def sql_connect(self, sql):
        loc = sql.loc
        st = ExecSql(loc, 'CONNECT')
        n = len(sql.toks)
        if sql.is_word(1, 'RESET'):
            return ExecSql(loc, 'DISCONNECT')
        if sql.is_word(1, 'TO'):
            # DB2 and the standard: CONNECT TO db [AS name] [USER u [USING p]]
            if sql.is_word(2, 'DEFAULT'):
                st.args['target'] = StrLit(b'')
                i = 3
            else:
                st.args['target'], i = _arg(sql, 2)
            while i < n:
                if sql.is_word(i, 'AS'):
                    st.args['name'], i = _arg(sql, i + 1)
                elif sql.is_word(i, 'USER'):
                    st.args['user'], i = _arg(sql, i + 1)
                elif sql.is_word(i, 'USING'):
                    st.args['password'], i = _arg(sql, i + 1)
                elif sql.is_word(i, 'IDENTIFIED') and sql.is_word(i + 1, 'BY'):
                    st.args['password'], i = _arg(sql, i + 2)
                else:
                    raise CompileError(f"EXEC SQL CONNECT: unexpected '{sql.toks[i][1]}'", loc)
            return st
        # Oracle and OCESQL: CONNECT :user IDENTIFIED BY :pw [AT name] [USING :db]
        first, i = _arg(sql, 1)
        if sql.is_word(i, 'IDENTIFIED') and sql.is_word(i + 1, 'BY'):
            st.args['user'] = first
            st.args['password'], i = _arg(sql, i + 2)
        else:
            st.args['target'] = first
        while i < n:
            if sql.is_word(i, 'AT'):
                st.args['name'], i = _arg(sql, i + 1)
            elif sql.is_word(i, 'USING'):
                st.args['target'], i = _arg(sql, i + 1)
            else:
                raise CompileError(f"EXEC SQL CONNECT: unexpected '{sql.toks[i][1]}'", loc)
        if 'target' not in st.args:
            st.args['target'] = StrLit(b'')     # COB_SQL_DATABASE names it
        return st

    def sql_whenever(self, sql):
        loc = sql.loc
        w = sql.words(0, 4)
        if w[1] == 'SQLERROR':
            cond, i = 'SQLERROR', 2
        elif w[1] == 'SQLWARNING':
            cond, i = 'SQLWARNING', 2
        elif w[1:3] == ['NOT', 'FOUND']:
            cond, i = 'NOT FOUND', 3
        else:
            raise CompileError("EXEC SQL WHENEVER: SQLERROR, SQLWARNING or NOT FOUND expected", loc)
        act = sql.words(i, 2)
        if act[0] == 'CONTINUE':
            action = None
        elif act[0] in ('GO', 'GOTO'):
            j = i + (2 if act[0] == 'GO' and act[1] == 'TO' else 1)
            name, _ = sql.name_at(j)
            action = GoTo(loc, [ProcRef(name, None, loc)])
        elif act[0] == 'PERFORM':
            name, _ = sql.name_at(i + 1)
            action = Perform(loc, ProcRef(name, None, loc), None)
        elif act[0] == 'STOP':
            action = StopRun(loc)
        else:
            raise CompileError("EXEC SQL WHENEVER: CONTINUE, GO TO, PERFORM or STOP expected", loc)
        self.sql_state()[cond] = action
        return None
