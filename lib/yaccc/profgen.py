# SPDX-License-Identifier: MIT
"""-fprof: where a run's time goes, procedure by procedure (a mixin of
CodeGen).

Each program gets a static table with an entry for every section and
paragraph, in source order. The runtime keeps one current entry for the
whole run unit: reaching a procedure's label (by falling into it, GO TO or
PERFORM) charges the time since the last switch to the entry that was
current and makes the new one current, counting a call; the return from a
PERFORM, or from a CALL, makes the procedure that issued it current again
without counting one. The time of each entry is therefore its own, not that
of the procedures it performs or the programs it calls. At the end of the
run, runtime/cobrt_prof.c writes the tables out as CSV.
"""


def c_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def line_of(proc):
    loc = getattr(proc, 'loc', None)
    return getattr(loc, 'line', 0) or 0


class ProfGen:
    def prof_init(self):
        self.prof_on = bool(getattr(self.opts, 'prof', False))
        self.prof_sym = None
        self.prof_index = {}        # id(section / paragraph) -> table index

    def prof_begin(self, prog, sections):
        """The program's table, and its registration where the procedures
        begin."""
        if not self.prof_on:
            return
        self.prof_sym = self.sym('cob_prof_')
        self.prof_index = {}
        rows = []
        for sec in sections:
            self.prof_index[id(sec)] = len(rows)
            rows.append((sec.name or '', '', line_of(sec), 1))
            for para in sec.paragraphs:
                self.prof_index[id(para)] = len(rows)
                rows.append((sec.name or '', para.name or '', line_of(para), 0))
        if not rows:
            self.prof_sym = None
            return
        name = c_str(prog.ext_name or prog.name or '')
        src = c_str(str(prog.loc.file) if getattr(prog, 'loc', None) else '')
        body = ', '.join(f"{{{name}, {src}, {c_str(s)}, {c_str(p)}, {line}, {kind}, 0, 0}}"
                         for s, p, line, kind in rows)
        self.glob.append(f"static cob_prof_entry {self.prof_sym}[{len(rows)}] = {{{body}}};")
        self.glob.append(f"static int {self.prof_sym}_done;")
        self.em(f"cob_prof_register({self.prof_sym}, {len(rows)}, &{self.prof_sym}_done);")

    def prof_enter(self, proc):
        """At the label of a section or paragraph: it is entered."""
        if self.prof_sym is not None and id(proc) in self.prof_index:
            self.em(f"cob_prof_switch(&{self.prof_sym}[{self.prof_index[id(proc)]}], 1);")

    def prof_resume(self):
        """After a PERFORM or CALL returns: the procedure that issued it is
        current again."""
        if self.prof_sym is None:
            return
        proc = getattr(self, 'cur_para', None)
        if proc is None or id(proc) not in self.prof_index:
            proc = getattr(self, 'cur_section', None)
        if proc is not None and id(proc) in self.prof_index:
            self.em(f"cob_prof_switch(&{self.prof_sym}[{self.prof_index[id(proc)]}], 0);")
