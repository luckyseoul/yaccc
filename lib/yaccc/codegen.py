# SPDX-License-Identifier: MIT
"""Semantic analysis and C code generation."""
import datetime
import re

from .data import (DataItem, IndexName, Picture, layout, link_redefines, resolve_types,
                   T_GROUP, T_ALNUM, T_ALPHA, T_ALNUM_EDITED, T_NUM_DISPLAY, T_NUM_PACKED,
                   T_NUM_BINARY, T_NUM_COMP5, T_NUM_FLOAT, T_NUM_DOUBLE, T_NUM_EDITED,
                   T_INDEX, T_ALL, T_POINTER, T_NUM_DEC_FLOAT, TYPE_NAMES, NUMERIC_TYPES,
                   F_SIGNED, F_SIGN_SEP, F_SIGN_LEAD, F_JUSTIFIED, F_BLANK_ZERO, F_DEC_COMMA,
                   F_BINARY_TRUNC, F_UNSIGNED_PACKED)
from . import errors
from .errors import CompileError, DIAG, ErrorsReported, did_you_mean, source_line
from .nodes import *
from .dbggen import DebugGen
from .dumpgen import DumpGen
from .odogen import OdoLayout, storage_children
from .rwgen import ReportWriterGen
from .scrgen import ScreenGen
from .sqlgen import SqlGen
from .words import FIG_BYTES, FUNCTIONS

CMP_OP = {'EQ': '==', 'NE': '!=', 'LT': '<', 'LE': '<=', 'GT': '>', 'GE': '>='}
FIG_FIELD = {'SPACE': '&cob_fig_space', 'ZERO': '&cob_fig_zero', 'HIGH-VALUE': '&cob_fig_high',
             'LOW-VALUE': '&cob_fig_low', 'QUOTE': '&cob_fig_quote', 'NULL': '&cob_fig_null'}
ORG = {'SEQUENTIAL': 'COB_ORG_SEQUENTIAL', 'LINE SEQUENTIAL': 'COB_ORG_LINE_SEQ',
       'RELATIVE': 'COB_ORG_RELATIVE', 'INDEXED': 'COB_ORG_INDEXED'}
ACC = {'SEQUENTIAL': 'COB_ACC_SEQUENTIAL', 'RANDOM': 'COB_ACC_RANDOM', 'DYNAMIC': 'COB_ACC_DYNAMIC'}
OPEN_MODE = {'INPUT': 'COB_OPEN_INPUT', 'OUTPUT': 'COB_OPEN_OUTPUT', 'I-O': 'COB_OPEN_IO',
             'EXTEND': 'COB_OPEN_EXTEND'}
START_OP = {'EQ': 0, 'GT': 1, 'GE': 2, 'LT': 3, 'LE': 4, 'NE': 0, 'FIRST': 5, 'LAST': 6}
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
        self.binary_truncate = True  # a BINARY item holds its PICTURE's digits
        self.pretty_display = True   # DISPLAY writes the point and a leading sign
        self.arithmetic_osvs = False # truncate each COMPUTE intermediate (OS/VS)
        self.missing_period = False  # accept a statement where '.' is required
        self.host_sign = False       # signed packed with sign F is NUMERIC (ibm)
        self.nonnum_zero = False     # MOVE SPACE/QUOTE/LOW/HIGH or "abc" to numeric moves 0 (mf)
        self.space_raw = False       # MOVE SPACE to numeric DISPLAY stores spaces (acu)
        self.dialect = 'default'
        self.dpc_in_data = 'none'    # -fdpc-in-data: '.' or ',' in JSON/XML numbers
        self.check = True
        self.source_name = ''
        self.debugging = False
        self.line_map = False        # #line directives, so a debugger shows COBOL
        self.directives = None       # for >>TURN / $SET SSRANGE
        self.trace = 0               # -ftrace 1 (procedures), -ftraceall 2 (and statements)
        self.filename_mapping = True # DD_name / $VAR / COB_FILE_PATH applied to ASSIGN names
        self.sign = 'ascii'          # -fsign: embedded signs as ASCII (0x70-0x79) or EBCDIC overpunch
        self.sticky_linkage = False  # LINKAGE items keep their addresses between calls
        self.defaultbyte = None      # -fdefaultbyte: WORKING-STORAGE without VALUE starts as this byte
        self.recursive_check = True  # EC-PROGRAM-RECURSIVE-CALL for a program that isn't RECURSIVE
        self.stack_trace = True      # PERFORM frames a runtime error can list (-fno-stack-trace)
        self.static_call = False     # -fstatic-call: a CALL literal's program must be linked in
        self.dump = None             # -fdump: the sections whose data a runtime error writes out
        self.emit_main = True        # an executable's main(); not for -c or -m
        self.export_c = False        # C entry points, for C code that calls COBOL


# C library names a COBOL program is not exported under: defining one in an
# executable would replace the library function for the whole program
C_LIBRARY_NAMES = frozenset('''
    main exit _exit abort atexit open close read write creat lseek time clock sleep
    usleep alarm pause system printf fprintf sprintf snprintf puts putchar getchar gets
    fgets fputs fopen fclose fread fwrite fflush fseek ftell scanf sscanf perror malloc
    calloc realloc free select poll signal raise kill link unlink remove rename sync wait
    waitpid fork pipe dup dup2 stat fstat lstat access chdir mkdir rmdir chmod chown
    umask getpid getenv setenv putenv strlen strcpy strncpy strcat strcmp strncmp
    strchr strrchr strstr memcpy memmove memset memcmp atoi atol strtol qsort bsearch
    exp log sin cos tan sqrt pow abs labs div random rand srand ctime localtime gmtime
    mktime strftime index send recv connect accept bind listen socket ioctl fcntl
    truncate environ errno
'''.split())


def c_identifier(name):
    """The C name for a COBOL program name, as cobc spells it ('-' becomes
    '__', a leading digit gets '_'), or None when there is none."""
    if not name:
        return None
    out = '_' if name[0].isdigit() else ''
    for ch in name:
        if ch == '-':
            out += '__'
        elif ch.isalnum() and ch.isascii() or ch == '_':
            out += ch
        else:
            return None
    return out


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

    def line_map(self, path, line):
        # c_string escapes quotes and non-ASCII bytes; it returns a C literal
        self.lines.append(f'#line {line} {c_string(path or "")}')

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
        self.ptr_inits = []         # storage addresses known only at run time


# library routines called by name: name -> (minimum, maximum) number of arguments
SYSTEM_ROUTINES = {
    'CBL_AND': (3, 3), 'CBL_OR': (3, 3), 'CBL_NOR': (3, 3), 'CBL_XOR': (3, 3), 'CBL_IMP': (3, 3),
    'CBL_NIMP': (3, 3), 'CBL_EQ': (3, 3), 'CBL_NOT': (2, 2),
    'CBL_TOUPPER': (2, 2), 'CBL_TOLOWER': (2, 2), 'C$TOUPPER': (2, 2), 'C$TOLOWER': (2, 2),
    'C$JUSTIFY': (1, 2), 'C$PRINTABLE': (1, 2), 'CBL_OC_DUMP': (1, 1), 'CBL_GC_DUMP': (1, 1),
    'C$NARG': (1, 1), 'C$PARAMSIZE': (1, 1), 'C$CALLEDBY': (1, 1),
    'C$GETPID': (0, 0), 'C$SLEEP': (1, 1), 'CBL_GC_NANOSLEEP': (1, 1), 'CBL_OC_NANOSLEEP': (1, 1),
    'CBL_GC_FORK': (0, 0), 'CBL_GC_WAITPID': (1, 1),
    'CBL_CREATE_DIR': (1, 1), 'CBL_DELETE_DIR': (1, 1), 'CBL_CHANGE_DIR': (1, 1), 'C$MAKEDIR': (1, 1),
    'C$CHDIR': (1, 2), 'CBL_GET_CURRENT_DIR': (3, 3),
    'CBL_DELETE_FILE': (1, 1), 'C$DELETE': (1, 2), 'CBL_RENAME_FILE': (2, 2), 'CBL_COPY_FILE': (2, 2),
    'C$COPY': (2, 3), 'CBL_CHECK_FILE_EXIST': (2, 2), 'C$FILEINFO': (2, 2),
    'CBL_GC_GETOPT': (6, 6), 'CBL_ERROR_PROC': (2, 2),
    'CBL_OPEN_FILE': (5, 5), 'CBL_CREATE_FILE': (5, 5), 'CBL_READ_FILE': (5, 5),
    'CBL_WRITE_FILE': (5, 5), 'CBL_CLOSE_FILE': (1, 1), 'CBL_FLUSH_FILE': (1, 1),
    'CBL_GC_HOSTED': (2, 2), 'CBL_OC_HOSTED': (2, 2), 'CBL_OC_GETOPT': (6, 6),
    'CBL_GC_PRINTABLE': (1, 2),
    'CBL_ALLOC_MEM': (2, 3), 'CBL_FREE_MEM': (1, 1), 'CBL_EXIT_PROC': (2, 2),
    'CBL_GET_SCR_SIZE': (2, 2), 'CBL_GET_CSR_POS': (1, 1), 'CBL_SET_CSR_POS': (1, 1),
    'CBL_READ_KBD_CHAR': (1, 1), 'CBL_GET_KBD_STATUS': (1, 1),
    '\xf4': (2, 2), '\xf5': (2, 2), '\xe4': (0, 0), '\xe5': (0, 0),
}
SYSTEM_ROUTINES_ALIAS = {'CBL_GC_DUMP': 'CBL_OC_DUMP', 'CBL_OC_NANOSLEEP': 'CBL_GC_NANOSLEEP',
                         'CBL_OC_HOSTED': 'CBL_GC_HOSTED', 'CBL_OC_GETOPT': 'CBL_GC_GETOPT',
                         'CBL_GC_PRINTABLE': 'C$PRINTABLE',
                         '\xf4': 'X_F4', '\xf5': 'X_F5', '\xe4': 'X_E4', '\xe5': 'X_E5'}


class CodeGen(ReportWriterGen, DebugGen, ScreenGen, SqlGen, DumpGen, OdoLayout):
    def __init__(self, programs, opts):
        self.programs = programs
        self.odo_init()
        self.udf_names = set()
        self.opts = opts
        # -Xref: every reference to a data item or procedure, as it resolves
        self.xref_on = bool(getattr(opts, 'xref', False))
        self.xref_refs = []         # (item, loc, ref)
        self.xref_procs = []        # (procedure, loc, how)
        self.xref_changed = set()   # id of each ref that is a receiving operand
        self._xref_seen = {}        # id(ref) -> ref, kept alive so ids stay unique
        self.glob = []
        self.performs = []          # the program's static cob_perform declarations
        self.funcs = []
        self.protos = []
        self.attr_cache = {}
        self.lit_cache = {}
        self.static_fields = {}
        self.dyn_fields = []        # static fields over BASED storage, bound at OPEN
        self.n = 0
        self.prog_syms = {}
        self.externals = {}
        self.ext_files = {}         # name -> [sym, buf, size]
        self.ext_inited = set()
        self.init_flags = {}
        self.all_progs = []
        self.now = datetime.datetime.now().astimezone()
        self.locs = {}              # (prog, para, sect, line, stmt) -> static cob_loc symbol

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
            if getattr(p, 'is_function', False):
                self.udf_names.add(p.ext_name.upper())
            walk(p)
        # program names are unique among separately compiled programs, and
        # within each of them among the programs it contains
        def check_unique(progs, what):
            seen = set()
            for p in progs:
                if p.ext_name in seen:
                    raise CompileError(f"duplicate program name '{p.ext_name}'{what}", p.loc)
                seen.add(p.ext_name)
        check_unique(self.programs, '')
        for top in self.programs:
            tree = []

            def collect(p):
                tree.append(p)
                for q in p.nested:
                    collect(q)
            collect(top)
            check_unique(tree, f" in '{top.ext_name}'")
        for p in self.all_progs:
            self.prog_syms[id(p)] = self.sym('prog_')
        for p in self.all_progs:
            self.protos.append(f"static int {self.prog_syms[id(p)]}(int cob_argc, unsigned char **cob_argv);")
            # its C-convention entry (see c_entry_points), which a PROGRAM-POINTER holds
            self.protos.append(f"static int cob_cw_{self.prog_syms[id(p)]}();")
            flag = self.sym('cob_inited_')
            self.init_flags[id(p)] = flag
            self.protos.append(f"static int {flag};")
        failed = set()
        for p in self.all_progs:
            q = p.parent
            while q is not None and id(q) not in failed:
                q = q.parent
            if q is not None:
                failed.add(id(p))       # its container's errors would only repeat here
                continue
            try:
                self.gen_program(p)
            except ErrorsReported:
                raise
            except CompileError as e:
                DIAG.error(e)
                failed.add(id(p))
        DIAG.check()
        for name, (fsym, buf, size) in self.ext_files.items():
            # weak global definitions: every object file and loaded module that
            # declares the EXTERNAL file binds to the same one
            self.protos.append(f"unsigned char {buf}[{size}] __attribute__((weak, aligned(16)));")
            self.protos.append(f"cob_file {fsym} __attribute__((weak));")
            self.protos.append(f"int {fsym}_inited __attribute__((weak));")
        # CANCEL support: reset to initial state, close open files, cancel contained programs
        for p in self.all_progs:
            cs = self.sym('cancel_')
            p._cancel_sym = cs
        for p in self.all_progs:
            self.protos.append(f"static void {p._cancel_sym}(void);")
            body = [f"static void {p._cancel_sym}(void)", "{"]
            body.append(f'\tif ({p._active_sym}) cob_fatal("attempt to CANCEL active program");')
            flag = self.init_flags[id(p)]
            body.append(f"\tif (!{flag}) return;")
            for fs in p._cancel_files:
                body.append(f"\tif ({fs}.open_mode) cob_close_quiet(&{fs});")
            for q in p.nested:
                body.append(f"\t{q._cancel_sym}();")
            body.append(f"\t{flag} = 0;")
            body.append("}")
            self.funcs.extend(body)
        # the entry point is the first program that is not a FUNCTION
        main = next((p for p in self.programs if not getattr(p, 'is_function', False)),
                    self.programs[0])
        now = self.now
        # FUNCTION WHEN-COMPILED (as CURRENT-DATE) and the WHEN-COMPILED register (IBM format)
        wc = now.strftime('%Y%m%d%H%M%S') + f"{now.microsecond // 10000:02d}" + now.strftime('%z')
        reg = now.strftime('%m/%d/%y%H.%M.%S')
        out = []
        out.append('/* Generated by YACCC (Yet Another COBOL C compiler) - do not edit */')
        out.append('#include "cobrt.h"')
        out.append('')
        out.append(f'static unsigned char cob_wc_reg_d[16] = {c_string(reg)};')
        out.append('static cob_field cob_wc_reg = {16, cob_wc_reg_d, &cob_attr_alnum};')
        out.append('')
        # ENTRY aliases: a name that starts the program part-way in. Their
        # prototypes and functions are added before the tables are written out,
        # because the order protos -> glob -> funcs matters: a report's format
        # function is declared in protos and defined in funcs, and its address
        # is taken in glob.
        aliases = []
        counts = {}
        for p in self.all_progs:
            counts[p.ext_name] = counts.get(p.ext_name, 0) + 1
        for p in self.all_progs:
            if p.parent is not None and counts[p.ext_name] != 1:
                continue
            for k, st in enumerate(getattr(p, '_entries', []), 1):
                nm = getattr(st, 'name', None)
                if nm is None:
                    continue        # a computed entry name is not registered
                alias = f"{self.prog_syms[id(p)]}_ent{k}"
                self.protos.append(f"static int {alias}(int, unsigned char **);")
                self.funcs.append(f"static int {alias}(int cob_argc, unsigned char **cob_argv)")
                self.funcs.append('{')
                # an ENTRY point may be called while its program is active
                # (that is how a program calls its own entry points), which the
                # not-RECURSIVE guard would otherwise reject
                self.funcs.append("\tcob_entry_reentry = 1;")
                self.funcs.append(f"\tcob_enter_at({k});")
                self.funcs.append(f"\treturn {self.prog_syms[id(p)]}(cob_argc, cob_argv);")
                self.funcs.append('}')
                self.funcs.append('')
                aliases.append((p, nm, alias))
        out.extend(self.protos)
        out.append('')
        out.extend(self.glob)
        out.append('')
        out.extend(self.funcs)
        out.append('')
        out.extend(self.c_entry_points(aliases, counts))
        # a constructor, so that the programs of an object file or a loaded
        # module are known to CALL by name as soon as it is loaded
        out.append('__attribute__((constructor)) static void cob_register_all(void)')
        out.append('{')
        # CALL by data name finds separately compiled programs, and contained
        # programs whose names are unique in the executable
        for p in self.all_progs:
            if p.parent is None or counts[p.ext_name] == 1:
                sym = self.prog_syms[id(p)]
                out.append(f'\tcob_register_entry({c_string(p.ext_name)}, {sym}, {p._cancel_sym}, '
                           f'(void *)cob_cw_{sym});')
        for p, nm, alias in aliases:
            out.append(f'\tcob_register_entry({c_string(nm)}, {alias}, {p._cancel_sym}, (void *)cob_cw_{alias});')
        if not self.opts.emit_main:
            # a module or object file: its compile settings, for a run unit
            # that no main() of ours started (yacccrun, or a C program)
            out.append(f"\tcob_module_settings({1 if getattr(self.opts, 'pretty_display', True) else 0}, "
                       f"{1 if getattr(self.opts, 'host_sign', False) else 0}, "
                       f"{1 if getattr(self.opts, 'sign', 'ascii') == 'ebcdic' else 0}, {c_string(wc)});")
        out.append('}')
        out.append('')
        if not self.opts.emit_main:
            return '\n'.join(out) + '\n'
        out.append('int main(int argc, char **argv)')
        out.append('{')
        out.append('\tcob_init(argc, argv);')
        if getattr(self.opts, 'host_sign', False):
            out.append('\tcob_host_sign = 1;')
        if not getattr(self.opts, 'pretty_display', True):
            out.append('\tcob_pretty_display = 0;')
        if getattr(self.opts, 'sign', 'ascii') == 'ebcdic':
            out.append('\tcob_sign_ebcdic = 1;')
        out.append(f'\tcob_when_compiled = {c_string(wc)};')
        out.append('\tcob_settings_fixed = 1;')
        out.append(f'\tint rc = {self.prog_syms[id(main)]}(-1, NULL);')
        out.append('\tcob_stop_run(rc);')
        out.append('\treturn rc;')
        out.append('}')
        return '\n'.join(out) + '\n'

    def c_entry_points(self, aliases, counts):
        """The C calling convention for the programs of this compile: a static
        wrapper per program and ENTRY name, taking an address for each USING
        item and the value itself for a BY VALUE one. A PROGRAM-POINTER holds
        one of these, so C code can call back a program it was handed; with
        export_c each also gets an external name C code can call it by."""
        out = []
        targets = []
        for p in self.all_progs:
            targets.append((p, p.ext_name, self.prog_syms[id(p)], [m for m, _ in p.using]))
        for p, nm, alias in aliases:
            st = next((e for e in getattr(p, '_entries', []) if getattr(e, 'name', None) == nm), None)
            n = len(getattr(st, 'using', []) or []) if st is not None else 0
            targets.append((p, nm, alias, ['REFERENCE'] * n))
        seen = set()
        for p, nm, fn, modes in targets:
            n = len(modes)
            params = ', '.join(f"intptr_t v{i}" if m == 'VALUE' else f"void *a{i}"
                               for i, m in enumerate(modes)) or 'void'
            args = ', '.join(f"v{i}" if m == 'VALUE' else f"a{i}" for i, m in enumerate(modes))
            out.append(f"static int cob_cw_{fn}({params})")
            out.append('{')
            out.append('\tcob_ensure_init();')
            if n:
                out.append(f"\tunsigned char *av[{n}];")
                sizes = []
                for i, m in enumerate(modes):
                    if m == 'VALUE':
                        out.append(f"\tunsigned char vb{i}[8];")
                        out.append(f"\tcob_put_value(8, vb{i}, (cob_s64)v{i});")
                        out.append(f"\tav[{i}] = vb{i};")
                        sizes.append('8')
                    else:
                        out.append(f"\tav[{i}] = (unsigned char *)a{i};")
                        sizes.append('0')
                out.append(f"\tstatic const int sizes[{n}] = {{{', '.join(sizes)}}};")
                out.append(f'\tint argc = cob_c_argc({n});')
                out.append('\tcob_call_sizes = sizes;')
                out.append('\tcob_call_arg_omitted = NULL;')
                out.append(f'\treturn {fn}(argc, av);')
            else:
                out.append('\tcob_c_argc(0);')
                out.append('\tcob_call_sizes = NULL;')
                out.append('\tcob_call_arg_omitted = NULL;')
                out.append(f'\treturn {fn}(0, NULL);')
            out.append('}')
            out.append('')
            if not self.opts.export_c or (p.parent is not None and nm == p.ext_name) \
                    or getattr(p, 'is_function', False) or counts.get(p.ext_name, 1) != 1 and p.parent is not None:
                continue
            cname = c_identifier(nm)
            if cname is None or cname in seen:
                continue
            if cname in C_LIBRARY_NAMES or cname.startswith('cob_'):
                DIAG.warn(f"program '{nm}' is not callable from C under the name '{cname}', "
                          f"which belongs to the C library", p.loc)
                continue
            seen.add(cname)
            out.append(f"int {cname}({params});")
            out.append(f"int {cname}({params})")
            out.append('{')
            out.append(f'\treturn cob_cw_{fn}({args});')
            out.append('}')
            out.append('')
        return out

    # ================================================================ attributes / literals
    def attr(self, typ, digits=0, scale=0, flags=0, pic=None, currency=0, pdigits=0):
        key = (typ, digits, scale, flags, pic, currency, pdigits)
        s = self.attr_cache.get(key)
        if s:
            return s
        s = self.sym('a_')
        pc = c_string(pic) if pic else 'NULL'
        tail = f", {pdigits}" if pdigits else ""
        self.glob.append(f"static const cob_attr {s} = {{{TYPE_NAMES[typ]}, {digits}, {scale}, {flags}, {pc}, {currency}{tail}}};")
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
    @staticmethod
    def program_visible(p, caller):
        """Scope of program names: separately compiled programs are visible
        everywhere; a contained program to the program that directly contains
        it, and, when COMMON, to every program its container contains."""
        if p.parent is None or p.parent is caller or p is caller:
            return True
        if p.is_common:
            a = caller.parent
            while a is not None:
                if p.parent is a:
                    return True
                a = a.parent
        return False

    def find_program(self, name):
        """C function of the program a CALL literal names: the exact external
        name, else the only one that matches ignoring case; 'NULL' when such
        programs exist but none is visible from this one (None: resolve at
        run time)."""
        cands = [p for p in self.all_progs if p.ext_name == name]
        if not cands:
            cands = [p for p in self.all_progs if p.ext_name.upper() == name.upper()]
            if len(cands) > 1:
                return None
        vis = [p for p in cands if self.program_visible(p, self.prog)]
        if vis:
            return self.prog_syms[id(vis[0])]
        return 'NULL' if cands else None

    def gen_program(self, prog):
        ctx = ProgCtx(prog)
        self.ctx = ctx
        self.prog = prog
        self.performs = []
        self.cur_para = self.cur_section = None
        ctx.cname = self.prog_syms[id(prog)]
        ctx.coll = None
        if not prog.collating and getattr(self.opts, 'default_colseq', None) == 'EBCDIC':
            # -fdefault-colseq=EBCDIC: as PROGRAM COLLATING SEQUENCE IS an
            # EBCDIC alphabet, for a program that names none
            prog.alphabets.setdefault('(EBCDIC)', 'EBCDIC')
            prog.collating = '(EBCDIC)'
        if prog.collating:
            self.build_collating(prog)
        ctx.init_flag = self.init_flags[id(prog)]
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
            if spec != 'EBCDIC':
                raise CompileError(f"alphabet {spec} is not supported", loc)
            # EBCDIC (code page 037) order of the native characters
            spec = [('LIT', [bytes([c])]) for c in sorted(range(256), key=lambda c: bytes([c]).decode('latin-1').encode('cp037')[0])]
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
                size = max(size, r.total_size())
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
                # a section root may itself have OCCURS: allocate every occurrence
                size = max([r.total_size()] + [x.total_size() for x in r.redefined_by])
                if sec == 'WS' and r.external and (r.external_name or r.name) == 'errno':
                    # EXTERNAL AS "errno": the C library's errno itself, which
                    # lives at an address known only at run time
                    sym = self.sym('bas_')
                    self.glob.append(f"static unsigned char *{sym}; /* errno */")
                    r.based = True
                    r.based_sym = sym
                    r.errno_alias = True
                    ctx.ptr_inits.append(f"{sym} = (unsigned char *)&errno;")
                elif getattr(r, 'based', False):
                    # storage allocated by ALLOCATE at run time, in any section
                    sym = self.sym('bas_')
                    self.glob.append(f"static unsigned char *{sym}; /* BASED {r.name} */")
                    r.based_sym = sym
                elif sec == 'WS':
                    if r.external:
                        key = r.external_name or r.name
                        if key in self.externals:
                            sym = self.externals[key]
                        else:
                            # the symbol follows the external name, so two
                            # programs that share it share the storage
                            sym = 'cobext_' + ''.join(ch if ch.isalnum() else '_' for ch in key)
                            self.externals[key] = sym
                            # a weak global definition: separately compiled
                            # objects and loaded modules share one copy, and one
                            # flag that says its VALUEs have been set
                            self.glob.append(f"unsigned char {sym}[{size}] __attribute__((weak, aligned(16)));")
                            self.glob.append(f"unsigned char {sym}_init __attribute__((weak));")
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
        # SCREEN SECTION: the fields' storage, then the tables drawn from
        self.scr_layout(prog)
        self.scr_tables(prog)
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
                ('SORT-RETURN', '&cob_sort_return_reg', T_NUM_BINARY, 4, F_SIGNED, 4),
                ('WHEN-COMPILED', '&cob_wc_reg', T_ALNUM, 0, 0, 16),
                ('NUMBER-OF-CALL-PARAMETERS', '&cob_ncp_reg', T_NUM_BINARY, 9, F_SIGNED, 4),
                ('JSON-CODE', '&cob_json_code_reg', T_NUM_BINARY, 9, F_SIGNED, 4),
                ('JSON-STATUS', '&cob_json_status_reg', T_NUM_BINARY, 9, F_SIGNED, 4),
                ('XML-CODE', '&cob_xml_code_reg', T_NUM_BINARY, 9, F_SIGNED, 4),
                # XML PARSE: the event, and its text and names, whose length
                # is the event's (XML-N... are the same: there is no national)
                ('XML-EVENT', '&cob_xml_event_reg', T_ALNUM, 0, 0, 30),
                ('XML-TEXT', '&cob_xml_text_reg', T_ALNUM, 0, 0, 0),
                ('XML-NTEXT', '&cob_xml_text_reg', T_ALNUM, 0, 0, 0),
                ('XML-NAMESPACE', '&cob_xml_ns_reg', T_ALNUM, 0, 0, 0),
                ('XML-NNAMESPACE', '&cob_xml_ns_reg', T_ALNUM, 0, 0, 0),
                ('XML-NAMESPACE-PREFIX', '&cob_xml_nsprefix_reg', T_ALNUM, 0, 0, 0),
                ('XML-NNAMESPACE-PREFIX', '&cob_xml_nsprefix_reg', T_ALNUM, 0, 0, 0),
                # the key that ended the last screen ACCEPT, without a CRT STATUS clause
                ('COB-CRT-STATUS', '&cob_crt_status_reg', T_NUM_DISPLAY, 4, 0, 4)):
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
                fi.key_names = getattr(fi, 'key_names', {})
                if fc.key_sources:
                    # RECORD KEY IS <name> SOURCE IS a, b: the name is the
                    # key's name, and the SOURCE items are what it is made of.
                    # The items must be resolved before they are looked up as
                    # data names, since the key name often is not one.
                    srcs = [self.resolve(sr) for sr in fc.key_sources]
                    base = srcs[0]
                    fi.keys.append((base, False, fc.key_sources, None))
                else:
                    k = self.resolve(fc.record_key)
                    fi.keys.append((k, False, None, None))
                # a split key's length is the concatenation of its parts
                n0 = (sum(self.resolve(sr).size for sr in fc.key_sources)
                      if fc.key_sources else fi.keys[0][0].size)
                fi.key_names[fc.record_key.name] = (0, n0)
            fi.key_names = getattr(fi, 'key_names', {})
            for kref, dups, sources, supp in fc.alt_keys:
                if sources:
                    # the alternate key's name may not be a data item either
                    fi.keys.append((self.resolve(sources[0]), dups, sources, supp))
                else:
                    fi.keys.append((self.resolve(kref), dups, None, supp))
                nk = (sum(self.resolve(sr).size for sr in sources)
                      if sources else fi.keys[-1][0].size)
                fi.key_names[kref.name] = (len(fi.keys) - 1, nk)
            for k, _dups, _srcs, _sup in fi.keys:
                if getattr(k, 'file', None) is not fi:
                    raise CompileError(f"key '{k.name}' is not part of the record of file '{fc.name}'", fc.loc)
                for sr in (_srcs or []):
                    si = self.resolve(sr)
                    if getattr(si, 'file', None) is not fi:
                        raise CompileError(f"key source '{sr.name}' is not part of the "
                                           f"record of file '{fc.name}'", sr.loc)
        # Debug module (DEBUG-ITEM, USE FOR DEBUGGING subjects)
        self.dbg_analyze(prog)
        # VALUE NEXT / START OF: the places items occupy are known by now
        self.resolve_pos_consts(prog)
        # REPORT SECTION
        self.rw_analyze(prog)

    def resolve_pos_consts(self, prog):
        done = set()
        for d in (prog.constants, getattr(prog, 'global_constants', {})):
            for v in list(d.values()):
                if not isinstance(v, PosOf) or id(v) in done:
                    continue
                done.add(id(v))
                tgt = v.pos_ref
                if isinstance(tgt, DataRef):
                    tgt = self.resolve(tgt)
                if isinstance(tgt, DataItem) and v.pos_kind == 'NEXT':
                    v.set_offset(tgt.offset + tgt.size)
                    continue
                if tgt is None:
                    v.set_offset(0)
                    continue
                if not isinstance(tgt, DataItem):
                    raise CompileError("VALUE START OF names an item with no position", v.loc)
                v.set_offset(tgt.offset)

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

    def name_hint(self, name, loc=None):
        """Why a data name might not be found: it names a paragraph (a period
        missing before a paragraph header makes the header an operand of the
        statement before it), or it is a misspelling of a name in scope."""
        ctx = self.ctx
        if name in getattr(ctx, 'paras_by_name', {}) or name in getattr(ctx, 'secs_by_name', {}):
            return f"; '{name}' is a procedure name: is the period before it missing?"
        if loc is not None:
            text = (source_line(loc.file, loc.line) or '').strip().upper()
            if re.match(re.escape(name) + r'(\s+SECTION)?\s*\.', text):
                return (f"; it looks like a paragraph header: is the period missing "
                        f"at the end of the statement before it?")
        pool = set(ctx.names)
        pc = self.prog.parent if self.prog is not None else None
        while pc is not None:
            pool.update(self.global_items(pc))
            pc = pc.parent
        return did_you_mean(name, pool)

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
        it = self._resolve(ref, allow_cond)
        if self.xref_on and it is not None and getattr(ref, 'loc', None) is not None \
                and id(ref) not in self._xref_seen and not getattr(ref, 'implicit', False):
            self._xref_seen[id(ref)] = ref
            self.xref_refs.append((it, ref.loc, ref))
        return it

    def xref_receiving(self, ref):
        if self.xref_on and isinstance(ref, DataRef):
            self.xref_changed.add(id(ref))

    def data_checks(self, s):
        """EC-DATA-INCOMPATIBLE: before a statement that reads numeric DISPLAY
        or packed items as numbers, a check that each holds one -- the
        statements cobc checks (MOVE, the arithmetic verbs and their
        receiving items that are also read, COMPUTE, SET); comparisons and
        function arguments are not checked, as there."""
        if not self.checks_on(s.loc, 'data'):
            return
        refs = []

        def operand(x):
            if isinstance(x, Target):
                x = x.ref
            if isinstance(x, DataRef) and not x.refmod:
                refs.append(x)

        def expr(e):
            if isinstance(e, BinOp):
                expr(e.left)
                expr(e.right)
            elif isinstance(e, Neg):
                expr(e.e)
            else:
                operand(e)
        kind = type(s).__name__
        if kind == 'Move':
            operand(s.src)
        elif kind == 'Arith':
            for x in s.operands:
                operand(x)
            if s.by_or_into is not None:
                operand(s.by_or_into)
            # the TO / FROM / BY / INTO items are read too: as the receiving
            # items of ADD TO and the like, or as operands with GIVING
            for t in s.to:
                operand(t)
        elif kind == 'Compute':
            expr(s.expr)
        elif kind == 'SetStmt' and s.kind in ('TO', 'UPDOWN'):
            operand(s.value)
            if s.kind == 'UPDOWN':
                for t in s.targets:
                    operand(t)
        seen = set()
        for r in refs:
            try:
                it = self.resolve(r)
            except CompileError:
                continue
            if not isinstance(it, DataItem) or it.type not in (T_NUM_DISPLAY, T_NUM_PACKED):
                continue
            key = (r.name, tuple(map(repr, r.subs)))
            if key in seen:
                continue
            seen.add(key)
            self.em(f"cob_chk_data({self.field(r)}, {c_string(r.name)}, {self.locstr(r.loc)});")

    def xref_stores(self, s):
        """-Xref: mark the operands a statement stores into."""
        out = []

        def add(x):
            if isinstance(x, Target):
                x = x.ref
            if isinstance(x, DataRef):
                out.append(x)
        kind = type(s).__name__
        if kind == 'Move':
            for d in s.dsts:
                add(d)
        elif kind == 'Arith':
            for t in list(s.to) + list(s.giving):
                add(t)
            add(s.remainder)
        elif kind == 'Compute':
            for t in s.targets:
                add(t)
        elif kind == 'SetStmt' and s.kind in ('TO', 'UPDOWN', 'TRUE', 'FALSE'):
            for t in s.targets:
                add(t)
        elif kind == 'Initialize':
            for t in s.targets:
                add(t)
        elif kind == 'Accept':
            add(s.target)
        elif kind == 'StringStmt':
            add(s.into)
            add(s.pointer)
        elif kind == 'Unstring':
            for u in s.intos:
                add(u.target)
                add(u.delim_in)
                add(u.count_in)
            add(s.pointer)
            add(s.tallying)
        elif kind == 'Inspect':
            if s.replacing or s.converting:
                add(s.target)
            for op in s.tallying:
                add(op.counter)
        elif kind in ('Read', 'Return'):
            add(s.into)
        elif kind == 'Perform' and s.varying:
            for v in s.varying:
                add(v.var)
        elif kind == 'Search':
            add(s.varying)
        for r in out:
            self.xref_changed.add(id(r))

    def _resolve(self, ref, allow_cond=True):
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
            raise CompileError(f"'{ref.name}' is not defined{self.name_hint(ref.name, ref.loc)}", ref.loc)
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
        rn = getattr(item, 'report_name', None)
        if rn is not None:
            chain.append(rn)
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
        self.dbg_collect(prog)

    def next_id(self):
        self.n += 1
        return self.n

    XREF_HOW = {'Perform': 'P', 'GoTo': 'G', 'Alter': 'A', 'Sort': 'S', 'Merge': 'S', 'XmlParse': 'P'}

    def resolve_proc(self, pr):
        p = self._resolve_proc(pr)
        if self.xref_on and getattr(pr, 'loc', None) is not None and id(pr) not in self._xref_seen:
            self._xref_seen[id(pr)] = pr
            how = self.XREF_HOW.get(type(getattr(self, 'cur_stmt', None)).__name__, '')
            self.xref_procs.append((p, pr.loc, how))
        return p

    def _resolve_proc(self, pr):
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
        pool = set(ctx.paras_by_name) | set(ctx.secs_by_name)
        raise CompileError(f"procedure '{pr.name}' is not defined{did_you_mean(pr.name, pool)}", pr.loc)

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
                        self.cur_stmt = st
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
        self.cur_stmt = None
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
        self.rw_emit(prog)
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
        if self.dbg is not None:
            em(f"memset({self.dbg.sym}, ' ', {self.dbg.size});")
        for it in ctx.rw_init:
            em(f"cob_move(&cob_fig_zero, {self.rw_item_field(it)});")
        for g in getattr(ctx, 'rw_trees', ()):
            self.init_tree(g, 'init')
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
        for line in ctx.ptr_inits:
            em(line)
        for r in self.ws_roots(prog):
            if getattr(r, 'errno_alias', False):
                continue
            if r.external:
                flag = self.externals[r.external_name or r.name] + '_init'
                em(f"if (!{flag}) {{")
                em.ind += 1
                self.init_tree(r, mode='init')
                em(f"{flag} = 1;")
                em.ind -= 1
                em("}")
            else:
                self.init_tree(r, mode='init')
        for fi in ctx.files.values():
            if fi.external:
                continue
            for r in fi.fd.records[:1]:
                em(f"memset({fi.buf}, ' ', {fi.size});")
        self.scr_init(prog, em)
        # a new program starts its own CBL_GC_GETOPT scan over the arguments
        em("cob_getopt_reset();")
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
        gdecls = [sec for sec in prog.declaratives if sec.use_global or sec.use_reporting]
        if gdecls:
            em("if (cob_argc == COB_DECL_ENTRY) goto L_decl_entry;")
        entries = [st for st in self.all_stmts(prog) if isinstance(st, EntryStmt)]
        for k, st in enumerate(entries, 1):
            st._entry_no = k
        if entries:
            prog._entries = entries
            prog._entry_count = len(entries)
        active = self.sym('cob_active_')
        self.protos.append(f"static int {active};")
        prog._active_sym = active
        if not prog.is_recursive and getattr(self.opts, 'recursive_check', True):
            # a program that isn't RECURSIVE can't be called while it is active
            em(f"if ({active} && !cob_entry_reentry) {{ cob_call_rejected = 1; return 0; }}")
            em("cob_entry_reentry = 0;")
        em(f"{active}++;")
        em(f"cob_module_push({c_string(prog.ext_name)}, cob_argc);")
        if getattr(self.opts, 'stack_trace', True):
            em("cob_module_frames(cob_frames);")
        dump = self.gen_dump_table(prog)
        if dump is not None:
            src = getattr(prog.loc, 'file', None) or self.opts.source_name or ''
            em(f"cob_module_dump({dump[0]}, {dump[1]}, {c_string(str(src))});")
        if self.opts.trace:
            pd = getattr(prog, 'proc_loc', None) or prog.loc
            em(f'if (cob_trace_on) cob_trace_point({self.trace_args()}, "Entry", '
               f'{c_string(prog.ext_name)}, {pd.line});')
        em(f"cob_set_collating({ctx.coll or 'NULL'});")
        if prog.parent is None:
            # each outermost program has its own RETURN-CODE, zero on entry;
            # contained programs share their container's
            em("cob_set_int(&cob_return_code, 0);")
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
        sizes = getattr(prog, 'using_sizes', [])
        for i, (mode, ref) in enumerate(prog.using):
            it = self.resolve(ref)
            if it.section != 'LK' or it.level not in (1, 77):
                raise CompileError(f"USING item '{ref.name}' must be a level 01/77 LINKAGE item", ref.loc)
            if mode == 'VALUE':
                # BY VALUE: the caller passed the value itself, in the number
                # of bytes SIZE gave, so read it into the item here
                n = sizes[i] if i < len(sizes) else None
                em(f"{it.storage} = {it.storage}_dummy;")
                # want: the width this program reads (SIZE, else the item's own);
                # have: the width the caller actually passed, recorded in the
                # frame by cob_module_push (which clears the global)
                want = n or it.size
                have = (f"(cob_frame_param_size({i + 1}) ? cob_frame_param_size({i + 1}) : {want})")
                em(f"if (cob_argc > {i} && cob_argv[{i}]) "
                   f"cob_get_arg_value({want}, {have}, cob_argv[{i}], "
                   f"CF({it.storage}, {it.size}, &{self.item_attr(it)}));")
            else:
                # an argument left out binds NULL, as in GnuCOBOL: ADDRESS OF
                # the item is then NULL, which is how a program tests OMITTED;
                # with -fsticky-linkage it keeps the last call's argument
                if getattr(self.opts, 'sticky_linkage', False):
                    em(f"if (cob_argc > {i}) {it.storage} = cob_argv[{i}];")
                else:
                    em(f"{it.storage} = (cob_argc > {i} && cob_argv[{i}]) ? cob_argv[{i}] : NULL;")
            using_items.append(it.storage)
        ret_item = None
        if getattr(prog, 'is_function', False) and prog.returning is not None:
            ret_item = self.resolve(prog.returning)
        sticky = getattr(self.opts, 'sticky_linkage', False)
        for sym, size, r in ctx.link_blocks:
            self.glob.append(f"static unsigned char {sym}_dummy[{size}];")
            if sym not in using_items:
                # -fsticky-linkage: an item keeps the address it was given
                # (SET ADDRESS OF) from one call to the next
                em(f"if (!{sym}) {sym} = {sym}_dummy;" if sticky else f"{sym} = {sym}_dummy;")
        if entries:
            # A CALL to an ENTRY point asked to start there. This has to come
            # after the program's own initialisation: jumping to the label
            # before INIT has run left the program's WORKING-STORAGE blank.
            em("if (cob_entry_pending) {")
            em.ind += 1
            em("int cob_ep = cob_entry_pending;")
            em("cob_entry_pending = 0;")
            for k in range(1, len(entries) + 1):
                em(f"if (cob_ep == {k}) goto L_entry_{k};")
            em.ind -= 1
            em("}")
        if ret_item is not None:
            # the caller passes the result storage as the last argument
            nuse = len(prog.using)
            em(f"if (cob_argc > {nuse} && cob_argv[{nuse}]) {ret_item.storage} = cob_argv[{nuse}];")
        if getattr(prog, 'chaining', None):
            # CHAINING takes the command line: such a program is a main
            # program only, never the target of a CALL
            em(f'if (cob_argc >= 0) cob_fatal("CALL of program with CHAINING clause (%s)", '
               f'{c_string(prog.ext_name)});')
        for i, ref in enumerate(getattr(prog, 'chaining', []) or []):
            it = self.resolve(ref)
            if it.section not in ('WS', 'LS'):
                raise CompileError("a CHAINING item must be in WORKING-STORAGE", ref.loc)
            em(f'if (cob_chain_arg({i})) cob_move_text(CF({it.storage} + {it.offset}, '
               f'{it.size}, &{self.item_attr(it)}), cob_chain_arg({i}));')
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
        if self.opts.trace:
            em(f'if (cob_trace_on) cob_trace_point({self.trace_args()}, "Exit", '
               f'{c_string(prog.ext_name)}, -1);')
        em("cob_module_pop();")
        em(f"{prog._active_sym}--;")
        for sym, size, r in ctx.local_blocks:
            em(f"free({sym});")
        if prog.returning is not None:
            f = self.field(prog.returning)
            em(f"return (int)cob_get_int({f});")
        elif getattr(prog, 'returning_omitted', False):
            # a void PROCEDURE DIVISION returns nothing, whatever RETURN-CODE
            # was set to inside it
            em("return 0;")
        else:
            em("return (int)cob_get_int(&cob_return_code);")
        if gdecls:
            self.cur_section = None
            self.cur_para = None
            em.label("L_decl_entry")
            em("switch (cob_decl_which) {")
            for sec in gdecls:
                em(f"case {sec.id}:")
                em.ind += 1
                self.dbg_emit_cause('USE', 0)
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
        out.append('\tconst cob_perform *cob_frames[COB_STACK_SIZE + 1];')
        out.append('\tconst cob_perform **frame_ptr = cob_frames;')
        # the base frame returns nowhere (L_exit keeps clang happy)
        out.append('\tstatic const cob_perform cob_perform_base = { 0, &&L_exit, NULL };')
        out.extend('\t' + d for d in self.performs)
        self.performs = []
        for sym, size, r in ctx.local_blocks + ctx.link_blocks:
            if prog.is_recursive:
                out.append(f'\tunsigned char *{sym};')
            else:
                self.protos.append(f'static unsigned char *{sym};')
        for d in sorted(set(self.fn_locals)):
            out.append('\t' + d)
        for d in self.dbg_locals():
            out.append('\t' + d)
        if self.seg_tracking:
            out.append('\tint cob_seg = -1;')
        out.append('\t(void)cob_argv;')
        out.append('\tcob_frames[0] = &cob_perform_base;')
        if getattr(self.opts, 'stack_trace', True):
            out.append('\tmemset(cob_frames + 1, 0, COB_FRAMES_CLEAR * sizeof cob_frames[0]);')
        out.extend(body.lines)
        out.append('}')
        out.append('')

    def ws_roots(self, prog):
        out = []
        for r in prog.working:
            if r.redefines is not None or r.renames:
                continue
            if r.external:
                if (r.external_name or r.name) in self.ext_inited:
                    continue
                self.ext_inited.add(r.external_name or r.name)
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
        if self.variably_located(it):
            raise CompileError(f"'{ref.name}' follows a table with OCCURS DEPENDING ON, so its place "
                               f"varies; it can't be used here", ref.loc)
        key = id(it)
        if key in self.static_fields:
            return self.static_fields[key]
        s = self.sym('sf_')
        rec = getattr(it, 'record', None)
        if getattr(rec, 'based', False):
            # BASED storage: the address is only known once ALLOCATE has run, so
            # the field is bound where it is used (see g_Open)
            self.glob.append(f"static cob_field {s} = {{{it.size}, NULL, &{self.item_attr(it)}}};")
            expr = (f"cob_based_ptr({rec.based_sym}, {c_string(rec.name)}) + {it.offset}")
            self.dyn_fields.append((s, expr))
            self.static_fields[key] = '&' + s
            return '&' + s
        if it.section in ('LK', 'LS'):
            self.glob.append(f"static cob_field {s} = {{{it.size}, NULL, &{self.item_attr(it)}}};")
            self.ctx.rebinds.append(f"{s}.data = {it.storage} + {it.offset};")
            # a LINKAGE item can be re-pointed with SET ADDRESS OF between the
            # program's entry and the OPEN that names it
            self.dyn_fields.append((s, f"{it.storage} + {it.offset}"))
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
                                    or fi.fd.linage is not None or fi.fd.reports):
            org = 'LINE SEQUENTIAL'
            fc.organization = org
        em(f"{f}.organization = {ORG[org]};")
        em(f"{f}.access = {ACC[fc.access]};")
        em(f"{f}.optional = {1 if fc.optional else 0};")
        em(f"{f}.sharing = {getattr(fc, 'sharing', 0)};")
        em(f"{f}.lock_mode = {getattr(fc, 'lock_mode', 0)};")
        em(f"{f}.lock_multiple = {1 if getattr(fc, 'lock_multiple', False) else 0};")
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
        if not getattr(self.opts, 'filename_mapping', True):
            em(f"{f}.no_mapping = 1;")
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
        for k, _dups, _srcs, _sup in fi.keys:
            if k.size > 4096:
                raise CompileError(f"key '{k.name}' is longer than 4096 bytes", fc.loc)
            if self.variably_located(k):
                raise CompileError(f"key '{k.name}' follows a table with OCCURS DEPENDING ON, so "
                                   f"its place in the record varies", fc.loc)
        em(f"{f}.nkeys = {len(fi.keys)};")
        for i, (k, dups, srcs, supp) in enumerate(fi.keys):
            parts = [k] if not srcs else [self.resolve(sr) for sr in srcs]
            if len(parts) > 8:
                raise CompileError(f"key '{k.name}' has more than 8 parts", fc.loc)
            total = sum(p.size for p in parts)
            segs = ', '.join(f"{{{p.offset}, {p.size}}}" for p in parts)
            # designated initialisers: the struct has gained fields before
            em(f"{f}.keys[{i}] = (cob_file_key){{.offset = {k.offset}, .size = {k.size}, "
               f".attr = &{self.item_attr(k)}, .dups = {1 if dups else 0}, "
               f".nseg = {len(parts)}, .seg = {{{segs}}}, .total = {total}, "
               f".supp = {c_string(supp[0]) if supp else 'NULL'}, "
               f".supplen = {len(supp[0]) if supp else 0}, "
               f".supp_all = {1 if supp and supp[1] else 0}}};")
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
        if isinstance(e, FuncCall) and e.name in self.udf_names:
            # numeric if the function's RETURNING item is
            prog = self.udf_prog(e.name)
            it = self.resolve_in_prog(prog.returning, prog) if prog.returning else None
            return it is not None and getattr(it, 'type', None) in NUMERIC_TYPES
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
        if isinstance(e, PosOf):
            e.check()
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
        if isinstance(e, FuncCall) and e.name in self.udf_names:
            f = self.udf_field(e)
            if e.refmod:
                f = self.apply_refmod(f, e.refmod, e.loc)
            return f
        if isinstance(e, FuncCall):
            k = FUNCTIONS[e.name][0]
            if k == 'X' or (k == 'M' and not self.is_numeric(FuncCall(e.name, e.args, None, e.loc))):
                f = self.func_alnum(e)
            else:
                f = self.func_field(e)
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
        # 0 = no checks, 1 = bounds, 2 = bounds and no zero-length reference
        chk = 0
        if self.checks_on(loc, 'ref-mod'):
            chk = 2 if getattr(self.opts, 'refmod_zero', False) else 1
        return f"cob_refmod(&(cob_field){{0}}, {f}, {s}, {l}, {chk}, {c_string(str(loc))})"

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
        ctx = {}            # the subscripts so far, for a DEPENDING ON item in a table
        for occ, sub in zip(chain, subs):
            if sub == 'ALL':
                raise CompileError("ALL subscript is only allowed in function arguments", ref.loc)
            # the distance between elements: less than the static one when an
            # element holds a variable table (see odogen)
            stride = self.odo_stride(occ, ref.loc, ctx)
            if isinstance(sub, NumLit) and sub.scale == 0 and not sub.neg \
                    and occ.occurs.depending is None:
                # A literal subscript is folded when the upper bound is fixed.
                # With OCCURS DEPENDING ON the bound is a run-time value, so
                # even a literal has to be checked there.
                v = int(sub.digits)
                if v < 1 or v > occ.occurs.max:
                    raise CompileError(f"subscript {v} of '{ref.name}' out of range 1..{occ.occurs.max}", ref.loc)
                if stride == str(occ.size):
                    const += (v - 1) * occ.size
                elif v > 1:
                    terms.append(f"{v - 1} * {stride}")
                ctx[id(occ)] = f"{v}LL"
                continue
            s = self.int_expr(sub)
            ctx[id(occ)] = s
            dep = occ.occurs.depending
            if dep is not None and self.checks_on(ref.loc, 'odo'):
                # the upper bound is the current DEPENDING ON value
                dmax = 2147483647 if getattr(occ.occurs, 'unbounded', False) else occ.occurs.max
                count = self.odo_count(occ, ref.loc, ctx, check=False)
                if count is None:
                    # a DEPENDING ON item in an element: one per element
                    count = self.int_expr(dep)
                dobj = self.resolve(dep)
                dname = (dobj.name if isinstance(dobj, DataItem) else None) or dep.name
                s = (f"cob_chk_odo_sub({s}, {count}, {occ.occurs.min}, "
                     f"{dmax}, {c_string(ref.name)}, {c_string(dname)}, {c_string(str(ref.loc))})")
            elif self.checks_on(ref.loc, 'subscript'):
                s = f"cob_chk_sub({s}, {occ.occurs.max}, {c_string(ref.name)}, {c_string(str(ref.loc))})"
            terms.append(f"({s} - 1) * {stride}")
        expr = ' + '.join([str(const)] + terms)
        # what the variable tables before the item have shrunk by
        before = self.odo_before(it, ref.loc, ctx)
        if before:
            expr = f"({expr} - {' - '.join(before)})"
        return expr

    @staticmethod
    def pointer_call(it):
        """A CALL target that is a POINTER: the call invokes the address, not
        the bytes as a program name."""
        return it is not None and getattr(it, 'type', None) == T_POINTER

    def checks_on(self, loc, kind='subscript'):
        """Checks of a kind (subscript, ref-mod, odo; data, off unless asked
        for) at this source position: a >>TURN or $SET SSRANGE in the source
        overrides the compile-wide flags (--no-check, -fno-ec=EC-BOUND-...)."""
        if kind == 'data':
            return 'data' in getattr(self.opts, 'checks_extra', ())
        d = getattr(self.opts, 'directives', None)
        if d is not None and loc is not None:
            state = d.check_at(getattr(loc, 'file', None), getattr(loc, 'line', 0))
            if state is not None:
                return state
        return getattr(self.opts, 'check', True) and kind not in getattr(self.opts, 'checks_off', ())

    def size_expr(self, it, receiving=False, loc=None, ctx=None):
        """C expression for the size of item it as referenced: its static
        size less what the variable tables in it have shrunk by (odogen).
        ctx gives the reference's subscripts, for a DEPENDING ON item in a
        table element."""
        if not (it.children or it.occurs):
            return str(it.size)
        d = it.contains_odo()
        if d is not None and d is not it and getattr(d.occurs, 'unbounded', False):
            # OCCURS UNBOUNDED: no static extent, so the fixed part up to the
            # table plus what DEPENDING ON says is there
            cur = self.int_expr(d.occurs.depending)
            return f"({d.offset - it.offset} + ({cur}) * {d.size})"
        loc = loc or self.cur_loc
        if it.occurs:
            # one element of a table
            return self.odo_stride(it, loc, ctx)
        shrink = self.odo_shrink(it, loc, ctx)
        if shrink is None:
            return str(it.size)
        if receiving and self.odo_object_inside(it):
            # a receiving group that holds its own DEPENDING ON item is
            # moved to at its full size
            return str(it.size)
        return f"({it.size} - {shrink})"

    def ref_ctx(self, ref, it):
        """The subscript context of a reference (odogen), its subscripts'
        values without their checks: for the size of what it names."""
        chain = it.occurs_chain() if isinstance(it, DataItem) else []
        if not chain or not ref.subs or len(ref.subs) != len(chain) or 'ALL' in ref.subs:
            return None
        if not any(self.odo_may_vary(c) for c in chain):
            return None
        return {id(occ): self.int_expr(sub) for occ, sub in zip(chain, ref.subs)}

    def ref_field(self, ref, receiving=False):
        it = self.resolve(ref)
        if receiving:
            self.xref_receiving(ref)
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
        if getattr(it, 'any_length', False):
            # PIC X ANY LENGTH: the calling program's field decides the size
            n = self.any_length_param(self.prog, ref)
            f = (f"cob_field_for_any_length({it.storage}, "
                 f"cob_frame_param_size({n}), &{self.item_attr(it)})")
            if ref.refmod:
                f = self.apply_refmod(f, ref.refmod, ref.loc)
            return f
        base = it.storage
        if getattr(getattr(it, 'record', None), 'based', False):
            base = f'cob_based_ptr({base}, {c_string(it.record.name)})'
        elif getattr(it, 'section', None) == 'LK':
            base = (f"cob_lk_ptr({base}, {c_string(self.lk_root_name(it))}, "
                    f"{c_string(ref.name)}, {c_string(str(ref.loc))})")
        off = self.offset_expr(ref, it)
        size = self.size_expr(it, receiving, ref.loc, self.ref_ctx(ref, it))
        f = f"CF({base} + {off}, {size}, &{self.item_attr(it)})"
        if ref.refmod:
            f = self.apply_refmod(f, ref.refmod, ref.loc)
        return f

    @staticmethod
    def lk_root_name(it):
        p = it
        while p.parent is not None:
            p = p.parent
        return p.name or 'FILLER'

    def any_length_param(self, prog, ref):
        """The 1-based USING position of an ANY LENGTH item, for
        cob_frame_param_size. Items after it in the LINKAGE section do not
        shift it: each LINKAGE item is its own parameter."""
        it = self.resolve(ref)
        names = [self.resolve(r).name for _, r in prog.using]
        try:
            return names.index(it.name) + 1
        except ValueError:
            raise CompileError(f"ANY LENGTH item '{ref.name}' must be named in "
                               f"the PROCEDURE DIVISION USING list", ref.loc) from None

    def data_ptr(self, ref):
        """C expression for data pointer of a reference (no refmod)."""
        it = self.resolve(ref)
        if isinstance(it, IndexName):
            return f"((unsigned char *)&{it.cname})"
        if getattr(it, 'special', None):
            return f"({it.special})->data"
        base = it.storage
        if getattr(getattr(it, 'record', None), 'based', False):
            base = f'cob_based_ptr({base}, {c_string(it.record.name)})'
        elif getattr(it, 'section', None) == 'LK':
            base = (f"cob_lk_ptr({base}, {c_string(self.lk_root_name(it))}, "
                    f"{c_string(ref.name)}, {c_string(str(ref.loc))})")
        off = self.offset_expr(ref, it)
        return f"({base} + {off})"

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
            if it.flags & F_UNSIGNED_PACKED:
                return f"cob_pack6_get({p}, {it.size})"
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
        if isinstance(e, FuncCall) and e.name in self.udf_names:
            return None                 # the general path reads the result
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

    def fast_set(self, fk, val, vscale=0, wide=False, rounded=False, overflow_reports=False):
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
            if kind != 'BIN' or (it.flags & F_BINARY_TRUNC):
                if overflow_reports:
                    # arithmetic without ON SIZE ERROR still raises
                    # EC-SIZE-OVERFLOW; the value is stored truncated as usual
                    parts.append(f"if (cob_w >= {10 ** it.digits}LL) "
                                 f"cob_set_exception(\"EC-SIZE-OVERFLOW\");")
                parts.append(f"cob_w %= {10 ** it.digits}LL;")
            if kind == 'BIN':
                # without binary-truncate a BINARY item keeps whatever fits in
                # its USAGE: cob_bin_set writes it.size bytes and drops the rest
                parts.append(f"cob_bin_set({p}, {it.size}, (cob_s64)cob_w);")
            elif kind == 'DU':
                parts.append(f"cob_disp_set({p}, {it.size}, (cob_u64)cob_w);")
            elif kind == 'DS':
                parts.append(f"cob_disps_set({p}, {it.size}, (cob_s64)cob_w);")
            elif it.flags & F_UNSIGNED_PACKED:
                parts.append(f"cob_pack6_set({p}, {it.size}, (cob_s64)cob_w);")
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

    def g_AddressOf_field(self, e):
        return self.address_of(e.ref)

    def udf_field(self, e):
        """A call to a user-defined FUNCTION as a cob_field*.

        The call has to run before the value is read, and an expression cannot
        emit statements, so the whole call is one statement expression (a GNU
        extension this compiler already requires). The callee writes its
        RETURNING item into storage the caller provides, as an extra final
        argument."""
        prog = self.udf_prog(e.name)
        ret = prog.returning
        if ret is None:
            raise CompileError(f"function '{e.name}' has no RETURNING item", e.loc)
        it = self.resolve_in_prog(ret, prog)
        if it is None or not hasattr(it, 'storage'):
            raise CompileError(f"function '{e.name}' must return a LINKAGE item", e.loc)
        buf = self.sym('udfb_')
        attr = self.item_attr(it)
        args = ', '.join(self.field(a) for a in e.args)
        n = len(e.args)
        fn = self.prog_syms.get(id(prog))
        if fn is None:
            raise CompileError(f"function '{e.name}' is not compiled in", e.loc)
        # a static field, so that its initialiser needs no compound literal
        return (f"({{ static unsigned char {buf}[{max(it.size, 1)}];"
                f" static cob_field cob_udf_f = "
                f"{{ {it.size}, {buf}, &{attr} }};"
                f" {{ unsigned char *cob_av[{max(n + 1, 1)}];"
                f" {self.udf_args(e, n)}"
                f" {fn}({n + 1}, cob_av); }}"
                f" &cob_udf_f; }})")

    def udf_prog(self, name):
        for p in self.all_progs:
            if p.is_function and p.ext_name.upper() == name.upper():
                return p
        raise CompileError(f"'{name}' is not a function in this program", None)

    def udf_args(self, e, n):
        """Argument setup for a user-defined function call.

        A BY REFERENCE call passes an address, so the argument has to be laid
        out the way the callee's parameter expects: a literal or a value of a
        different PICTURE is converted into a temporary of the parameter's own
        type first. Passing the literal's bytes straight through made the
        callee read past its one byte as a two-digit field."""
        prog = self.udf_prog(e.name)
        params = [self.resolve_in_prog(r, prog) for _m, r in prog.using]
        parts = []
        for i, a in enumerate(e.args):
            f = self.field(a)
            parts.append(f"const cob_field *cob_f{i} = {f};")
            p = params[i] if i < len(params) else None
            if p is None or not hasattr(p, 'storage'):
                parts.append(f"cob_av[{i}] = cob_f{i}->data;")
                continue
            buf = self.sym('udfa_')
            parts.append(f"static unsigned char {buf}[{max(p.size, 1)}];")
            parts.append(f"cob_field cob_t{i} = "
                         f"{{ {p.size}, {buf}, &{self.item_attr(p)} }};")
            parts.append(f"cob_move(cob_f{i}, &cob_t{i});")
            parts.append(f"cob_av[{i}] = {buf};")
        parts.append(f"cob_av[{n}] = cob_udf_f.data;")
        return ' '.join(parts)

    def resolve_in_prog(self, ref, prog):
        save = getattr(self, 'prog', None)
        try:
            self.prog = prog
            return self.resolve(ref)
        except Exception:
            return None
        finally:
            self.prog = save

    @staticmethod
    def float_text(n):
        """A floating-point literal as a C double constant."""
        t = n.float_text
        # C accepts 1.5e+307 and 1.5E-307 alike; strip a leading '+'
        if t.startswith('+'):
            t = t[1:]
        if 'e' not in t.lower():
            t += 'e0'
        return t + '' if ('.' in t.lower().split('e')[0]) else ''

    def float_lit(self, e):
        """A floating-point literal as a C double constant, sign included
        (float_text carries the magnitude only)."""
        return ('-' if getattr(e, 'neg', False) else '') + self.float_text(e)

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
            if getattr(it, 'any_length', False):
                # PIC X ANY LENGTH: the caller's field decides it
                n = self.any_length_param(self.prog, r)
                return f"cob_frame_param_size({n})"
            return self.size_expr(it, False, r.loc, self.ref_ctx(r, it))
        return f"({self.field(r)})->size"

    def dec_osvs(self, e, wide, dmax, top):
        """(C cob_dec expression, scale) with OS/VS intermediate precision.

        Each operation's result is cut back to the scale OS/VS COBOL gives it:
        the larger operand scale for + and -, their sum for *, and for /
        the larger of the operand difference and dmax, the largest scale in
        the statement. Cutting happens on every result but the outermost,
        which the receiving item's own store deals with (and which ROUNDED
        must still see in full). Measured on cobc 3.1.2, which tracks the same
        scales in a stack across the expression."""
        if isinstance(e, BinOp):
            lc, ls = self.dec_osvs(e.left, wide, dmax, False)
            rc, rs = self.dec_osvs(e.right, wide, dmax, False)
            fn = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'div', '**': 'pow'}[e.op]
            if wide and e.op in ('*', '/'):
                fn += '_wide'
            t = f"cob_d_{fn}({lc}, {rc})"
            if e.op in ('+', '-'):
                p = max(ls, rs)
            elif e.op == '*':
                p = ls + rs
            elif e.op == '/':
                p = max(ls - rs, dmax)
            else:
                p = ls - rs
            p = max(0, p)
            if not top:
                t = f"cob_d_trunc({t}, {p})"
            return t, p
        if isinstance(e, Neg):
            c, sc = self.dec_osvs(e.e, wide, dmax, False)
            return f"cob_d_neg({c})", sc
        return self.dec(e, wide), self.expr_scale(e)

    def dec(self, e, wide=False):
        """A C cob_dec expression. `wide` keeps the decimal-float exponent
        range in / and *: a FLOAT-DECIMAL item can carry a value far below
        1e-38, which the ordinary 38-digit path would truncate to zero."""
        if isinstance(e, PosOf):
            e.check()
        if isinstance(e, NumLit) and getattr(e, 'float_text', None):
            if wide:
                sign = '-' if e.neg else ''
                return f"cob_d_exp_str({c_string(sign + e.float_text)})"
            return f"cob_d_from_double({self.float_lit(e)})"
        if isinstance(e, FuncCall) and e.name in self.udf_names:
            return f"cob_d_get({self.udf_field(e)})"
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
            if wide and e.op in ('*', '/'):
                fn += '_wide'
            return f"cob_d_{fn}({self.dec(e.left, wide)}, {self.dec(e.right, wide)})"
        if isinstance(e, Neg):
            return f"cob_d_neg({self.dec(e.e, wide)})"
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

    def is_dec_float_ref(self, ref):
        """True when a reference names a FLOAT-DECIMAL-16/34 data item."""
        try:
            it = self.resolve(ref)
        except Exception:
            return False
        return isinstance(it, DataItem) and it.type == T_NUM_DEC_FLOAT

    def uses_dec_float(self, e):
        """True when an expression reads a FLOAT-DECIMAL item (anywhere)."""
        if isinstance(e, DataRef):
            return self.is_dec_float_ref(e)
        if isinstance(e, BinOp):
            return self.uses_dec_float(e.left) or self.uses_dec_float(e.right)
        if isinstance(e, Neg):
            return self.uses_dec_float(e.e)
        if isinstance(e, FuncCall):
            return any(self.uses_dec_float(a) for a in e.args)
        return False

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
            fld = self.num_arg_field if kind == 'N' else self.field
            items = ', '.join(fld(a) for a in args)
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
                    fld = self.num_arg_field if kind == 'N' else self.field
                    code.append(f"{buf}v[{cnt}] = *({fld(a)}); {buf}[{cnt}] = &{buf}v[{cnt}]; {cnt}++;")
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

    def func_field(self, e):
        """The data item holding a numeric function result, described as
        GnuCOBOL describes it: DISPLAY and MOVE to alphanumeric items show
        these digits (ORD gives 000000066, MEAN of 1 and 2 gives 00000001.5)."""
        name = e.name
        a = e.args
        fl = F_DEC_COMMA if self.prog.decimal_comma else 0
        if name == 'ABS':
            if isinstance(a[0], (DataRef, NumLit)) and self.is_numeric(a[0]):
                return f"cob_fn_model_field({self.func_num(e)}, {self.field(a[0])})"
            return f"cob_fn_abs_field({self.dec(a[0])}, {fl})"
        if name in ('MAX', 'MIN', 'MEDIAN'):
            pre, n, arr = self.expand_all_args(a, 'N')
            if name == 'MEDIAN':
                call = f"cob_fn_median_num((int){n}, {arr}, {fl})"
            else:
                call = f"cob_fn_minmax_num({1 if name == 'MAX' else 0}, (int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        if name == 'RANDOM':
            seed = f"1, {self.dec(a[0])}" if a else "0, cob_d_int(0)"
            return f"cob_double_field(cob_fn_random_d({seed}))"
        if name in ('LENGTH', 'BYTE-LENGTH') and (isinstance(a[0], StrLit) or
                                                 (isinstance(a[0], DataRef) and not a[0].refmod and
                                                  self.static_length(a[0]))):
            return f"cob_fn_field({self.func_num(e)}, {fl}, -1)"     # a constant, as in GnuCOBOL
        digits = {'DATE-OF-INTEGER': 8, 'DAY-OF-INTEGER': 7}.get(name, 0)
        return f"cob_fn_field({self.func_num(e)}, {fl}, {digits})"

    def static_length(self, ref):
        """True if the item's length is known at compile time (no OCCURS DEPENDING ON)."""
        it = self.resolve(ref)
        return isinstance(it, DataItem) and it.contains_odo() is None and not getattr(it, 'special', None)

    def num_arg_field(self, a):
        """Field for a numeric function argument: data items and literals as they
        are, expressions as function results."""
        if isinstance(a, (DataRef, NumLit, FuncCall)):
            return self.field(a)
        fl = F_DEC_COMMA if self.prog.decimal_comma else 0
        return f"cob_fn_field({self.dec(a)}, {fl}, 0)"

    def pointer_arg(self, e):
        """A pointer-valued argument as an unsigned char*."""
        it = self.resolve(e) if isinstance(e, DataRef) else None
        if it is not None and getattr(it, 'type', None) == T_POINTER:
            return f"cob_pointer_get({self.field(e)})"
        if isinstance(e, AddressOf):
            return self.address_of(e.ref)
        raise CompileError("a POINTER item is needed here", getattr(e, 'loc', None))

    def func_num(self, e):
        if e.name == 'CONTENT-LENGTH':
            return f"cob_d_int((cob_s64)cob_fn_content_length({self.pointer_arg(e.args[0])}))"
        if e.name in self.udf_names:
            # a user-defined function: its RETURNING item decides the value
            return f"cob_d_get({self.udf_field(e)})"

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
        if name == 'STORED-CHAR-LENGTH':
            return f"cob_fn_length(cob_fn_trim({F(0)}, 2))"
        if name in ('LENGTH', 'BYTE-LENGTH'):
            if isinstance(a[0], DataRef) and not a[0].refmod:
                it = self.resolve(a[0])
                n = self.length_of(LengthOf(a[0]))
                if name == 'LENGTH' and getattr(it, 'national', False):
                    n = f"({n} / 2)"       # national: two bytes per character
                return f"cob_d_int((cob_s64)({n}))"
            if isinstance(a[0], StrLit):
                return f"cob_d_int({len(a[0].value)})"
            return f"cob_fn_length({F(0)})"
        if name == 'ORD':
            return f"cob_fn_ord({F(0)})"
        if name in ('ULENGTH', 'UVALID', 'USUPPLEMENTARY'):
            return f"cob_fn_{name.lower()}({F(0)})"
        if name in ('UPOS', 'UWIDTH'):
            return f"cob_fn_{name.lower()}({F(0)}, {D(1)})"
        if name in ('NUMVAL', 'NUMVAL-F', 'NUMVAL-C', 'TEST-NUMVAL', 'TEST-NUMVAL-F', 'TEST-NUMVAL-C'):
            kind = 2 if name.endswith('-F') else 1 if name.endswith('-C') else 0
            fn = 'cob_fn_test_numval' if name.startswith('TEST-') else 'cob_fn_numval'
            cur = F(1) if len(a) > 1 else 'NULL'
            dpc = 1 if self.prog.decimal_comma else 0
            return f"{fn}({F(0)}, {cur}, {c_string(self.prog.currency)}, {kind}, {dpc})"
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
        dpc = 1 if self.prog.decimal_comma else 0
        if name == 'COMBINED-DATETIME':
            return f"cob_fn_combined_datetime({D(0)}, {D(1)})"
        if name in ('INTEGER-OF-FORMATTED-DATE', 'SECONDS-FROM-FORMATTED-TIME', 'TEST-FORMATTED-DATETIME'):
            fn = 'cob_fn_' + name.lower().replace('-', '_')
            return f"{fn}({F(0)}, {F(1)}, {dpc})"
        if name in ('HIGHEST-ALGEBRAIC', 'LOWEST-ALGEBRAIC'):
            return self.algebraic_limit(a[0], name == 'HIGHEST-ALGEBRAIC', e.loc)
        if name == 'MODULE-DATE':
            return f"cob_d_int({self.now.strftime('%Y%m%d')})"
        if name == 'MODULE-TIME':
            return f"cob_d_int({int(self.now.strftime('%H%M%S'))})"
        raise CompileError(f"function {name} is not supported in numeric context", e.loc)

    def algebraic_limit(self, arg, highest, loc):
        """HIGHEST-ALGEBRAIC / LOWEST-ALGEBRAIC: the greatest / least value the
        argument's description allows."""
        it = self.resolve(arg) if isinstance(arg, DataRef) else None
        if not isinstance(it, DataItem) or it.type not in (T_NUM_DISPLAY, T_NUM_PACKED, T_NUM_BINARY,
                                                           T_NUM_COMP5, T_NUM_EDITED):
            raise CompileError("HIGHEST-ALGEBRAIC and LOWEST-ALGEBRAIC need a numeric data item", loc)
        signed = bool(it.flags & F_SIGNED)
        if it.pic is None:
            # BINARY-CHAR and the like: the range of the binary type
            bits = 8 * it.size
            hi = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
            lo = -(1 << (bits - 1)) if signed else 0
            return f"cob_d_str(\"{hi if highest else lo}\")"
        digits, scale = it.digits, it.scale
        text = '9' * digits
        if scale > 0:
            text = text[:digits - scale] + '.' + text[digits - scale:]
            if text.startswith('.'):
                text = '0' + text
        elif scale < 0:
            text += '0' * -scale
        if not highest:
            text = '-' + text if signed else '0'
        return f"cob_d_str(\"{text}\")"

    def func_alnum(self, e):
        name = e.name
        a = e.args
        F = lambda i: self.field(a[i])
        if name == 'CONTENT-OF':
            # the bytes at a pointer, up to its NUL or an explicit length
            n = f"cob_d_to_int({self.dec(a[1])})" if len(a) > 1 else "-1"
            return f"cob_fn_content_of({self.pointer_arg(a[0])}, {n})"
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
        if name in ('HEX-TO-CHAR', 'BIT-OF', 'BIT-TO-CHAR'):
            return f"cob_fn_{name.lower().replace('-', '_')}({F(0)})"
        if name == 'UUID4':
            return "cob_fn_uuid4()"
        if name == 'USUBSTR':
            n = self.dec(a[2]) if len(a) > 2 else 'cob_d_int(0)'
            return f"cob_fn_usubstr({F(0)}, {self.dec(a[1])}, {n}, {1 if len(a) > 2 else 0})"
        if name in ('CONCATENATE', 'CONCAT', 'SUBSTITUTE', 'SUBSTITUTE-CASE'):
            pre, n, arr = self.expand_all_args(a, 'F')
            fn = {'CONCATENATE': 'cob_fn_concatenate', 'CONCAT': 'cob_fn_concatenate',
                  'SUBSTITUTE': 'cob_fn_substitute', 'SUBSTITUTE-CASE': 'cob_fn_substitute_case'}[name]
            call = f"{fn}((int){n}, {arr})"
            return f"({{ {pre} {call}; }})" if pre else call
        dpc = 1 if self.prog.decimal_comma else 0
        D = lambda i: self.dec(a[i])
        if name == 'FORMATTED-DATE':
            return f"cob_fn_formatted_date({F(0)}, {D(1)}, {dpc})"
        def offset(i):
            if len(a) <= i:
                return "0, cob_d_int(0)"
            if isinstance(a[i], StrLit) and a[i].value == b'SYSTEM-OFFSET':
                return "2, cob_d_int(0)"
            return f"1, {D(i)}"
        if name == 'FORMATTED-TIME':
            return f"cob_fn_formatted_time({F(0)}, {D(1)}, {offset(2)}, {dpc})"
        if name == 'FORMATTED-DATETIME':
            return f"cob_fn_formatted_datetime({F(0)}, {D(1)}, {D(2)}, {offset(3)}, {dpc})"
        if name == 'FORMATTED-CURRENT-DATE':
            return f"cob_fn_formatted_current_date({F(0)}, {dpc})"
        if name in ('EXCEPTION-FILE', 'EXCEPTION-LOCATION', 'EXCEPTION-STATEMENT', 'EXCEPTION-STATUS',
                    'MODULE-CALLER-ID', 'MODULE-PATH'):
            return f"cob_fn_{name.lower().replace('-', '_')}()"
        if name == 'LOCALE-COMPARE':
            return f"cob_fn_locale_compare({F(0)}, {F(1)})"
        if name == 'LOCALE-DATE':
            return f"cob_fn_locale_date({F(0)})"
        if name == 'LOCALE-TIME':
            return f"cob_fn_locale_time({F(0)})"
        if name == 'LOCALE-TIME-FROM-SECONDS':
            return f"cob_fn_locale_time_from_seconds({D(0)})"
        info = {'CURRENCY-SYMBOL': 0, 'MONETARY-DECIMAL-POINT': 1, 'MONETARY-THOUSANDS-SEPARATOR': 2,
                'NUMERIC-DECIMAL-POINT': 3, 'NUMERIC-THOUSANDS-SEPARATOR': 4}
        if name in info:
            return f"cob_fn_locale_info({info[name]})"
        if name == 'MODULE-ID':
            return f"cob_fn_text({c_string(self.prog.ext_name)})"
        if name == 'MODULE-SOURCE':
            return f"cob_fn_text({c_string(self.prog.loc.file)})"
        if name == 'MODULE-FORMATTED-DATE':
            return f"cob_fn_text({c_string(self.now.strftime('%b %d %Y %H:%M:%S'))})"
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
        if isinstance(c, OmittedCond):
            return self.cond_omitted(c)
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
                    not getattr(it, 'any_length', False) and \
                    it.type in (T_ALNUM, T_ALPHA, T_GROUP, T_ALNUM_EDITED, T_NUM_EDITED) and \
                    (it.type != T_GROUP or it.contains_odo() is None):
                # ANY LENGTH is excluded: its size is known only at run time,
                # and comparing the PICTURE's size compares one character
                return (self.data_ptr(e), it.size)
        return None

    def float_item(self, e):
        """The USAGE of a floating-point data item operand, or None."""
        if not isinstance(e, DataRef) or e.refmod:
            return None
        try:
            it = self.resolve(e)
        except Exception:
            return None
        if isinstance(it, DataItem) and it.type in (T_NUM_FLOAT, T_NUM_DOUBLE):
            return it.type
        return None

    def rel(self, l, op, r):
        cop = CMP_OP[op]
        dec_float = self.uses_dec_float(l) or self.uses_dec_float(r)
        if not dec_float and (self.float_item(l) is not None or self.float_item(r) is not None):
            # a floating-point item compares with a relative tolerance, which
            # is why a COMP-1 and the literal it came from are equal
            dl = self.dbl(l)
            dr = self.dbl(r)
            if dl is not None and dr is not None:
                return f"(cob_cmp_dbl({dl}, {dr}) {cop} 0)"
            return f"(cob_cmp_float({self.field(l)}, {self.field(r)}) {cop} 0)"
        if not dec_float and (self.is_float_operand(l) or self.is_float_operand(r)):
            return f"(cob_operand_double({self.field(l)}) {cop} cob_operand_double({self.field(r)}))"

        if isinstance(l, AddressOf) or isinstance(r, AddressOf) or \
                self._is_pointer(l) or self._is_pointer(r):
            return f"({self._addr(l)} {cop} {self._addr(r)})"
        if getattr(self.opts, 'arithmetic_osvs', False) and not dec_float and \
                (self.op_count(l) > 1 or self.op_count(r) > 1) and self.is_numeric(l) and self.is_numeric(r):
            # OS/VS arithmetic in a condition: the intermediate results are cut
            # to the largest scale of its operands, as in a COMPUTE
            DIAG.warn("precision of result may change with arithmetic-osvs", self.cur_loc, 'arithmetic-osvs')
            dmax = max(self.expr_scale(l), self.expr_scale(r))
            dl = self.dec_osvs(l, False, dmax, True)[0] if self.op_count(l) > 1 else self.dec(l)
            dr = self.dec_osvs(r, False, dmax, True)[0] if self.op_count(r) > 1 else self.dec(r)
            return f"(cob_d_cmp({dl}, {dr}) {cop} 0)"
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
                return f"(cob_d_sign({self.dec(l, dec_float)}) {cop} 0)"
            return f"(cob_d_cmp({self.dec(l, dec_float)}, {self.dec(r, dec_float)}) {cop} 0)"
        return f"(cob_cmp({self.field(l)}, {self.field(r)}) {cop} 0)"

    def _is_pointer(self, e):
        if not isinstance(e, DataRef):
            return False
        try:
            it = self.resolve(e)
        except Exception:
            return False
        return getattr(it, 'type', None) == T_POINTER

    def is_float_operand(self, e):
        """A literal that only a double can hold, so the comparison has to be
        done in double.

        A COMP-1/COMP-2 item compared with an ordinary literal is NOT one of
        these: GnuCOBOL rounds the item to the 7 (or 15) significant digits its
        USAGE implies before comparing, and the decimal path already does that.
        Comparing in raw double instead made "ADD 360 TO x" fail for
        FLOAT-SHORT x, because 483.45599... is not 483.456."""
        return isinstance(e, NumLit) and getattr(e, 'float_text', None) is not None

    def _addr(self, e):
        """A pointer value as a C expression, for comparing ADDRESS OF."""
        if isinstance(e, AddressOf):
            return f"((void *){self.address_of(e.ref)})"
        if isinstance(e, Figurative) and e.kind == 'NULL':
            return "((void *)0)"
        it = self.resolve(e) if isinstance(e, DataRef) else None
        if it is not None and getattr(it, 'type', None) == T_POINTER:
            return f"((void *)cob_pointer_get({self.field(e)}))"
        if isinstance(e, NumLit) and int(e.digits or '0') == 0:
            return "((void *)0)"
        raise CompileError("ADDRESS OF can only be compared with NULL or "
                           "another ADDRESS OF", getattr(e, 'loc', None))

    def cond_omitted(self, c):
        """IF item OMITTED: the CALL argument in this USING position was not
        passed."""
        it = self.resolve(c.ref)
        n = self.any_length_param(self.prog, c.ref) if getattr(it, 'any_length', False) \
            else self.using_position(self.prog, c.ref)
        e = f"cob_param_omitted({n})"
        return f"(!{e})" if c.neg else f"({e})"

    def using_position(self, prog, ref):
        it = self.resolve(ref)
        names = [self.resolve(r).name for _m, r in prog.using]
        try:
            return names.index(it.name) + 1
        except ValueError:
            raise CompileError(f"'{ref.name}' must be named in the PROCEDURE "
                               f"DIVISION USING list to test OMITTED", ref.loc) from None

    def cond_name(self, ref):
        c = self.resolve(ref)
        if not (isinstance(c, DataItem) and c.level == 88):
            raise CompileError(f"'{ref.name}' is not a condition-name", ref.loc)
        var = c.parent
        vref = DataRef(var.name or 'FILLER', [], ref.subs, None, ref.loc)
        vref.item = var
        vref.implicit = True     # the condition's item: not named in the source
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
        self.dbg_label(sec)
        if self.opts.trace and sec.name:
            em(f'if (cob_trace_on) cob_trace_point({self.trace_args()}, "Section", '
               f'{c_string(sec.name)}, {sec.loc.line});')
        for para in sec.paragraphs:
            self.cur_para = para
            para.end_label = f"{para.label}_end"
            em(f"/* PARAGRAPH {para.name or '(unnamed)'} */")
            em.label(para.label)
            self.seg_enter(sec)
            self.dbg_label(para)
            if self.opts.trace and para.name:
                em(f'if (cob_trace_on) cob_trace_point({self.trace_args()}, "Paragraph", '
                   f'{c_string(para.name)}, {para.loc.line});')
            for sent in para.sentences:
                end = self.new_label('E')
                self.cur_sentence_end = end
                for st in sent.stmts:
                    self.stmt(st)
                em.label(end)
            em.label(para.end_label)
            em(self.perform_exit(para.id))
        em.label(sec.end_label)
        em(self.perform_exit(sec.id))

    def perform_exit(self, pid):
        """The end of a paragraph or section: the most recent PERFORM returns if
        its range ends here -- or, with -fperform-osvs (-std=ibm), the most
        recent one whose range ends here, those begun after it abandoned."""
        if getattr(self.opts, 'perform_osvs', False):
            return (f"if ((*frame_ptr)->through == {pid} || "
                    f"cob_perform_osvs(&frame_ptr, cob_frames, {pid})) goto *(*frame_ptr)->ret;")
        return f"if ((*frame_ptr)->through == {pid}) goto *(*frame_ptr)->ret;"

    def stmts(self, lst):
        if lst:
            for s in lst:
                self.stmt(s)

    STMT_NAMES = {'STOPRUN': 'STOP RUN', 'GOTO': 'GO TO', 'GOBACK': 'GOBACK', 'STOPLIT': 'STOP',
                  'EXITPROGRAM': 'EXIT', 'DELETEFILE': 'DELETE', 'SETCOND': 'SET'}

    def trace_args(self):
        """The source file and program a trace line names."""
        return f"{c_string(self.prog.loc.file)}, {c_string(self.prog.ext_name)}"

    def g_TraceStmt(self, s):
        # READY TRACE / RESET TRACE: switch the -ftrace output on and off
        self.em(f"cob_trace_on = {1 if s.on else 0};")

    def loc_sym(self, s):
        """Static cob_loc describing statement s (for EXCEPTION-LOCATION and -STATEMENT)."""
        kind = type(s).__name__.upper()
        name = self.STMT_NAMES.get(kind, kind)
        para = self.cur_para.name if getattr(self, 'cur_para', None) is not None else None
        sect = self.cur_section.name if getattr(self, 'cur_section', None) is not None else None
        key = (self.prog.ext_name, para, sect, s.loc.line, name)
        sym = self.locs.get(key)
        if sym is None:
            sym = self.sym('cob_loc_')
            cs = lambda v: c_string(v) if v else 'NULL'
            self.glob.append(f"static const cob_loc {sym} = {{{c_string(self.prog.ext_name)}, {cs(para)}, "
                             f"{cs(sect)}, {c_string(name)}, {s.loc.line}}};")
            self.locs[key] = sym
        return sym

    def stmt(self, s):
        self.cur_loc = s.loc
        errors.WHERE = s.loc
        self.cur_stmt = s
        if self.xref_on:
            self.xref_stores(s)
        if 'data' in getattr(self.opts, 'checks_extra', ()):
            self.data_checks(s)
        fn = getattr(self, 'g_' + type(s).__name__, None)
        if fn is None:
            raise CompileError(f"{type(s).__name__} is not supported", s.loc)
        self.em(f"/* line {s.loc.line}: {type(s).__name__.upper()} */")
        if self.opts.line_map and s.loc is not None:
            self.em.line_map(s.loc.file, s.loc.line)
        if self.opts.trace >= 2:
            verb = getattr(s, 'verb', None) or self.STMT_NAMES.get(type(s).__name__.upper(),
                                                                   type(s).__name__.upper())
            self.em(f"if (cob_trace_on) cob_trace_point({self.trace_args()}, NULL, "
                    f"{c_string(verb)}, {s.loc.line});")
        start = len(self.em.lines)
        ind = self.em.ind
        try:
            if self.dbg is not None and self.dbg_watching():
                saved = self.dbg_pending
                self.dbg_pending = self.dbg_plan(s)
                try:
                    fn(s)
                    self.dbg_flush()
                finally:
                    self.dbg_pending = saved
            else:
                fn(s)
        except ErrorsReported:
            raise
        except CompileError as e:
            # report it and go on with the next statement, so that one compile
            # finds every error; nothing is written while errors are pending
            DIAG.error(e)
            del self.em.lines[start:]
            self.em.ind = ind
            return
        # statements that call intrinsic functions say where they are, for the
        # exceptions those functions raise (EXCEPTION-LOCATION)
        for line in self.em.lines[start:]:
            if 'cob_fn_' in line and '/* line ' not in line:
                self.em.lines.insert(start, '\t' * ind + f"cob_cur_loc = &{self.loc_sym(s)};")
                break

    def block(self, stmts):
        self.em.ind += 1
        self.stmts(stmts)
        self.em.ind -= 1

    def handlers(self, cond_c, on, noton):
        em = self.em
        self.dbg_flush()
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
        self.xref_receiving(ref)
        if isinstance(it, DataItem) and it.level == 88:
            raise CompileError(f"condition-name '{ref.name}' cannot be a receiving item", ref.loc)
        return it

    def big_float_move(self, src, dst):
        """MOVE of a literal too large for a decimal into a COMP-1/COMP-2: the
        value only exists as a double, so it goes there directly."""
        if not isinstance(src, NumLit) or getattr(src, 'float_text', None) is None:
            return None
        try:
            it = self.resolve(dst)
        except Exception:
            return None
        if isinstance(it, DataItem) and it.type == T_NUM_DEC_FLOAT:
            sign = '-' if src.neg else ''
            return (f"cob_d_set({self.ref_field(dst, True)}, "
                    f"cob_d_exp_str({c_string(sign + src.float_text)}), 0);")
        if not isinstance(it, DataItem) or it.type not in (T_NUM_FLOAT, T_NUM_DOUBLE):
            return None
        return (f"cob_put_float({self.ref_field(dst, True)}, "
                f"{self.float_lit(src)});")

    def big_num_move(self, src, dst):
        """MOVE of a numeric literal whose fixed spelling does not fit the
        8-bit fields of a cob_attr (a scale past 127, as in 1.0E-398): go
        straight through the decimal, where it is a coefficient and a scale."""
        if not isinstance(src, NumLit):
            return None
        if len(src.digits) <= 255 and -128 <= src.scale <= 127:
            return None
        try:
            it = self.resolve(dst)
        except Exception:
            return None
        if not isinstance(it, DataItem) or it.type not in NUMERIC_TYPES:
            return None
        return f"cob_d_set({self.ref_field(dst, True)}, {self.dec(src)}, 0);"

    def g_Move(self, s):
        em = self.em
        if s.corr:
            if not isinstance(s.src, DataRef):
                raise CompileError("MOVE CORRESPONDING requires group items", s.loc)
            for d in s.dsts:
                self.gen_corr(s.src, d, 'MOVE', None)
            return
        # -std=mf: a non-numeric figurative constant or literal moved to a
        # numeric item moves zero instead
        src = s.src
        if getattr(self.opts, 'nonnum_zero', False) and (
                (isinstance(src, Figurative) and src.kind in ('SPACE', 'QUOTE', 'LOW-VALUE', 'HIGH-VALUE')) or
                (isinstance(src, StrLit) and not src.value.isdigit())):
            zero = Figurative('ZERO')
            for d in s.dsts:
                it = self.check_receiving(d)
                if isinstance(it, DataItem) and it.type in NUMERIC_TYPES:
                    DIAG.warn("source is non-numeric - substituting zero", s.loc)
                    em(f"cob_move({self.field(zero)}, {self.ref_field(d, True)});")
                else:
                    em(f"cob_move({self.field(src)}, {self.ref_field(d, True)});")
            return
        # GnuCOBOL stores the figurative's own byte in a numeric DISPLAY item
        # rather than converting it to zero: MOVE LOW-VALUES leaves x"00"x n,
        # which then fails IS NUMERIC and reads as 0
        if isinstance(s.src, Figurative) and (s.src.kind in ('LOW-VALUE', 'HIGH-VALUE') or
                                              (s.src.kind == 'SPACE' and getattr(self.opts, 'space_raw', False))):
            byte = {'LOW-VALUE': '0', 'HIGH-VALUE': '255', 'SPACE': '32'}[s.src.kind]
            for d in s.dsts:
                it = self.check_receiving(d)
                if isinstance(it, DataItem) and it.type == T_NUM_DISPLAY:
                    self.em(f"memset({self.data_ptr(d)}, {byte}, {it.size});")
                else:
                    self.em(f"cob_move({self.field(s.src)}, {self.ref_field(d, True)});")
            return
        for d in s.dsts:
            it = self.check_receiving(d)
            if isinstance(it, IndexName):
                raise CompileError(f"index '{d.name}' cannot be a MOVE target; use SET", d.loc)
        if len(s.dsts) == 1:
            big = self.big_num_move(s.src, s.dsts[0]) or self.big_float_move(s.src, s.dsts[0])
            if big is not None:
                em(big)
                return
            line = self.fast_move(s.src, s.dsts[0])
            em(line if line else f"cob_move({self.field(s.src)}, {self.ref_field(s.dsts[0], True)});")
            return
        em("{")
        em.ind += 1
        special = [self.big_num_move(s.src, d) or self.big_float_move(s.src, d) for d in s.dsts]
        if not all(special):
            em(f"const cob_field *cob_s = {self.field(s.src)};")
        for d, line in zip(s.dsts, special):
            em(line if line is not None else f"cob_move(cob_s, {self.ref_field(d, True)});")
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
            if getattr(it, 'any_length', False):
                return None         # the size is known only at run time
            if isinstance(it, DataItem) and it.type in (T_ALNUM, T_ALPHA, T_GROUP) and \
                    not (it.flags & F_JUSTIFIED) and it.level != 88 and not getattr(it, 'special', None) and \
                    (it.type != T_GROUP or it.contains_odo() is None):
                src_a = None
                if isinstance(src, StrLit):
                    src_a = self.alnum_fixed(src)
                elif isinstance(src, DataRef) and not src.refmod:
                    si = self.resolve(src)
                    if getattr(si, 'any_length', False):
                        si = None       # size known only at run time
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
            DIAG.warn("no corresponding items found", self.cur_loc, 'corresponding')
            return
        em("{")
        em.ind += 1
        em(f"unsigned char *cob_g1 = {self.data_ptr(src)};")
        em(f"unsigned char *cob_g2 = {self.data_ptr(dst)};")
        def place(x, g):
            # its offset in the group: after a variable table, where it is now
            before = self.odo_before(x, None, None, stop=g)
            off = str(x.offset - g.offset)
            return f"({off} - {' - '.join(before)})" if before else off
        for a, b in pairs:
            fa = f"CF(cob_g1 + {place(a, g1)}, {a.size}, &{self.item_attr(a)})"
            fb = f"CF(cob_g2 + {place(b, g2)}, {b.size}, &{self.item_attr(b)})"
            if verb == 'MOVE':
                em(f"cob_move({fa}, {fb});")
            else:
                fn = 'add' if verb == 'ADD' else 'sub'
                em(f"{err_var} |= cob_d_set({fb}, cob_d_{fn}(cob_d_get({fb}), cob_d_get({fa})), {target_opts});")
        em.ind -= 1
        em("}")

    # ---------------------------------------------------------------- arithmetic
    RMODE_C = {'NEAREST-AWAY-FROM-ZERO': 'COB_ROUNDED', 'AWAY-FROM-ZERO': 'COB_ROUNDED|COB_RM_AWAY',
               'NEAREST-EVEN': 'COB_ROUNDED|COB_RM_EVEN', 'NEAREST-TOWARD-ZERO': 'COB_ROUNDED|COB_RM_TOWARD0',
               'TOWARD-GREATER': 'COB_ROUNDED|COB_RM_GREATER', 'TOWARD-LESSER': 'COB_ROUNDED|COB_RM_LESSER',
               'PROHIBITED': 'COB_ROUNDED|COB_RM_PROHIBITED', 'TRUNCATION': None}

    def rounding(self, t):
        """Rounding mode of an arithmetic target (None: truncation)."""
        if not t.rounded:
            return None
        mode = t.rounded if isinstance(t.rounded, str) else self.prog.default_rounded
        return None if mode == 'TRUNCATION' else mode

    def fast_rounding(self, t):
        """Rounding flag for the inline fixed-point path; None if the mode needs the runtime."""
        mode = self.rounding(t)
        if mode is None:
            return False
        return True if mode == 'NEAREST-AWAY-FROM-ZERO' else None

    def raise_size_exceptions(self, cond_c, on, noton):
        """Without ON SIZE ERROR the size error condition still exists, and
        the standard's exception facility reports it: raise EC-SIZE-ZERO-DIVIDE
        for a division by zero, EC-SIZE-OVERFLOW for a result too big for its
        receiving item."""
        if on is not None or noton is not None:
            return                  # the program handles it itself
        em = self.em
        em(f"if ({cond_c}) {{")
        em.ind += 1
        em("if (cob_zero_div_seen) cob_set_exception(\"EC-SIZE-ZERO-DIVIDE\");")
        em("else cob_set_exception(\"EC-SIZE-OVERFLOW\");")
        em.ind -= 1
        em("}")

    def target_opt(self, t, chk):
        o = []
        mode = self.rounding(t)
        if mode is not None:
            o.append(self.RMODE_C[mode])
        # with ON SIZE ERROR the target must stay unchanged, so the check has
        # to stop before the store; without it the store happens and the
        # overflow is only reported, for EC-SIZE-OVERFLOW
        o.append('COB_SIZE_CHECK' if chk else 'COB_SIZE_REPORT')
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
        if any(self.fast_rounding(t) is None for t in targets):
            return False
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
            em(self.fast_set(fk, val, sc, wide, self.fast_rounding(t), overflow_reports=True))
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
        em(f"cob_cur_loc = &{self.loc_sym(s)};")
        chk = s.on_error is not None or s.not_on_error is not None
        if self.fast_arith(s):
            return
        for o in ([] if s.corr else s.operands):
            self.check_numeric_operand(o)
        if s.by_or_into is not None:
            self.check_numeric_operand(s.by_or_into)
        for t in ([] if s.corr else s.to + s.giving):
            self.check_numeric_target(t.ref)
        # FLOAT-DECIMAL operands carry exponents far outside the ordinary
        # 38-digit range, so their * and / must keep the wider scale
        wide = any(self.uses_dec_float(o) for o in ([] if s.corr else s.operands))
        if s.by_or_into is not None:
            wide = wide or self.uses_dec_float(s.by_or_into)
        wide = wide or any(self.is_dec_float_ref(t.ref) for t in s.to + s.giving)
        em("{")
        em.ind += 1
        em("int cob_err = 0;")
        if s.verb == 'DIVIDE' or s.verb == 'COMPUTE':
            em("cob_zero_div_seen = 0;")
        if s.corr:
            if len(s.operands) != 1 or len(s.to) != 1:
                raise CompileError(f"{s.verb} CORRESPONDING requires one group on each side", s.loc)
            self.gen_corr(s.operands[0], s.to[0].ref, s.verb, self.target_opt(s.to[0], chk), 'cob_err')
        elif s.verb in ('ADD', 'SUBTRACT'):
            ops = s.operands
            acc = self.dec(ops[0], wide)
            for o in ops[1:]:
                acc = f"cob_d_add({acc}, {self.dec(o, wide)})"
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
                    em(f"cob_dec cob_r = cob_d_sub({self.dec(s.by_or_into, wide)}, cob_t);")
                    for t in s.giving:
                        em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_r, {self.target_opt(t, chk)});")
        elif s.verb == 'MULTIPLY':
            mul = 'cob_d_mul_wide' if wide else 'cob_d_mul'
            em(f"cob_dec cob_t = {self.dec(s.operands[0], wide)};")
            for t in s.to:
                f = self.field(t.ref)
                em(f"cob_err |= cob_d_set({f}, {mul}(cob_t, cob_d_get({f})), {self.target_opt(t, chk)});")
            if s.giving:
                em(f"cob_dec cob_r = {mul}(cob_t, {self.dec(s.by_or_into, wide)});")
                for t in s.giving:
                    em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_r, {self.target_opt(t, chk)});")
        elif s.verb == 'DIVIDE':
            div = 'cob_d_div_wide' if wide else 'cob_d_div'
            em(f"cob_dec cob_t = {self.dec(s.operands[0], wide)};")
            for t in s.to:
                f = self.field(t.ref)
                em(f"cob_err |= cob_d_set({f}, {div}(cob_d_get({f}), cob_t), {self.target_opt(t, chk)});")
            if s.giving:
                if s.form == 'INTO':
                    em(f"cob_dec cob_dd = {self.dec(s.by_or_into, wide)}, cob_dv = cob_t;")
                else:
                    em(f"cob_dec cob_dd = cob_t, cob_dv = {self.dec(s.by_or_into, wide)};")
                em(f"cob_dec cob_q = {div}(cob_dd, cob_dv);")
                for t in s.giving:
                    em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_q, {self.target_opt(t, chk)});")
                if s.remainder is not None:
                    self.check_numeric_target(s.remainder)
                    g = self.resolve(s.giving[0].ref)
                    sc = g.scale if isinstance(g, DataItem) else 0
                    mul = 'cob_d_mul_wide' if wide else 'cob_d_mul'
                    em(f"cob_dec cob_qt = cob_d_trunc(cob_q, {sc});")
                    em(f"cob_err |= cob_d_set({self.field(s.remainder)}, cob_d_sub(cob_dd, {mul}(cob_qt, cob_dv)), {'COB_SIZE_CHECK' if chk else '0'});")
        self.handlers('cob_err', s.on_error, s.not_on_error)
        self.raise_size_exceptions('cob_err', s.on_error, s.not_on_error)
        em("(void)cob_err;")
        em.ind -= 1
        em("}")

    def dbl(self, e):
        """A C double expression for an arithmetic operand, or None when the
        expression is outside what this simple form can carry."""
        if isinstance(e, NumLit):
            if getattr(e, 'float_text', None) is not None:
                return f"({self.float_lit(e)})"
            return f"({e.text})"
        if isinstance(e, Neg):
            inner = self.dbl(e.e)
            return f"(-{inner})" if inner is not None else None
        if isinstance(e, DataRef):
            it = self.resolve(e)
            if isinstance(it, DataItem) and it.type in NUMERIC_TYPES and not e.refmod:
                return f"cob_operand_double({self.field(e)})"
            return None
        if isinstance(e, BinOp):
            a = self.dbl(e.left)
            b = self.dbl(e.right)
            if a is None or b is None:
                return None
            if e.op == '/':
                return f"cob_dbl_div({a}, {b})"
            if e.op in ('+', '-', '*', '**'):
                if e.op == '**':
                    return f"pow({a}, {b})"
                return f"({a} {e.op} {b})"
            return None
        return None

    def float_target_kind(self, t):
        """T_NUM_FLOAT / T_NUM_DOUBLE when the COMPUTE receiver is one."""
        try:
            it = self.resolve(t.ref)
        except Exception:
            return None
        if isinstance(it, DataItem) and it.type in (T_NUM_FLOAT, T_NUM_DOUBLE):
            return it.type
        return None

    def osvs_scale(self, expr, targets):
        """The scale OS/VS COBOL cuts every intermediate result back to, or
        None when the statement is not subject to it: a single operation has no
        intermediate to cut, and a floating-point receiver works in double."""
        if not getattr(self.opts, 'arithmetic_osvs', False):
            return None
        if self.op_count(expr) < 2:
            return None
        scale = 0
        for t in targets:
            try:
                it = self.resolve(t.ref)
            except Exception:
                return None
            # a numeric-edited receiver counts with its decimal places too
            if not isinstance(it, DataItem) or (it.type not in NUMERIC_TYPES and it.type != T_NUM_EDITED):
                return None
            if it.type in (T_NUM_FLOAT, T_NUM_DOUBLE):
                return None
            if it.scale > scale:
                scale = it.scale
        return max(scale, self.expr_scale(expr))

    def op_count(self, e):
        """Binary operators in an arithmetic expression."""
        if isinstance(e, BinOp):
            return 1 + self.op_count(e.left) + self.op_count(e.right)
        if isinstance(e, Neg):
            return self.op_count(e.e)
        return 0

    def expr_scale(self, e):
        """The largest decimal scale any operand of the expression carries."""
        if isinstance(e, NumLit):
            return e.scale
        if isinstance(e, DataRef):
            try:
                it = self.resolve(e)
            except Exception:
                return 0
            if isinstance(it, DataItem) and it.type in NUMERIC_TYPES:
                return max(0, it.scale)
            return 0
        if isinstance(e, BinOp):
            return max(self.expr_scale(e.left), self.expr_scale(e.right))
        if isinstance(e, Neg):
            return self.expr_scale(e.e)
        return 0

    def g_Compute(self, s):
        em = self.em
        em(f"cob_cur_loc = &{self.loc_sym(s)};")
        chk = s.on_error is not None or s.not_on_error is not None
        for t in s.targets:
            self.check_numeric_target(t.ref)
        if not chk and all(self.fast_rounding(t) is not None for t in s.targets):
            fks = [self.fast_kind(t.ref) for t in s.targets]
            if all(fk is not None and fk[0] != 'IX' for fk in fks):
                ts = max(self.fast_scale(fk) for fk in fks)
                fv = self.fast_value(s.expr, ts)
                if fv is not None:
                    if len(fks) == 1:
                        em(self.fast_set(fks[0], fv[0], fv[1], fv[2], self.fast_rounding(s.targets[0]), overflow_reports=True))
                    else:
                        em("{")
                        em.ind += 1
                        em(f"{'cob_s128' if fv[2] else 'cob_s64'} cob_fc = {fv[0]};")
                        for fk, t in zip(fks, s.targets):
                            em(self.fast_set(fk, 'cob_fc', fv[1], fv[2], self.fast_rounding(t), overflow_reports=True))
                        em.ind -= 1
                        em("}")
                    return
        fkinds = [self.float_target_kind(t) for t in s.targets]
        dexpr = self.dbl(s.expr) if all(fk is not None for fk in fkinds) else None
        if dexpr is not None:
            # a floating-point receiver takes the arithmetic in double: a
            # COMP-1 holds up to FLT_MAX, which a 38-digit decimal cannot
            em("{")
            em.ind += 1
            em("cob_zero_div_seen = 0;")
            em(f"double cob_fv = {dexpr};")
            em("int cob_err = 0;")
            for t in s.targets:
                em(f"cob_err |= cob_put_float({self.field(t.ref)}, cob_fv);")
            self.handlers('cob_err', s.on_error, s.not_on_error)
            self.raise_size_exceptions('cob_err', s.on_error, s.not_on_error)
            em("(void)cob_err;")
            em.ind -= 1
            em("}")
            return
        em("{")
        em.ind += 1
        em("int cob_err = 0;")
        wide = self.uses_dec_float(s.expr) or any(self.is_dec_float_ref(t.ref) for t in s.targets)
        osc = self.osvs_scale(s.expr, s.targets)
        if osc is not None:
            DIAG.warn("precision of result may change with arithmetic-osvs", s.loc, 'arithmetic-osvs')
        rhs = self.dec_osvs(s.expr, wide, osc, True)[0] if osc is not None else self.dec(s.expr, wide)
        em(f"cob_dec cob_t = {rhs};")
        for t in s.targets:
            em(f"cob_err |= cob_d_set({self.field(t.ref)}, cob_t, {self.target_opt(t, chk)});")
        self.handlers('cob_err', s.on_error, s.not_on_error)
        self.raise_size_exceptions('cob_err', s.on_error, s.not_on_error)
        em("(void)cob_err;")
        em.ind -= 1
        em("}")

    # ---------------------------------------------------------------- DISPLAY / ACCEPT
    # ---------------------------------------------------------------- pointers
    def g_Allocate(self, s):
        em = self.em
        em("{")
        em.ind += 1
        if s.target is None:
            n = self.dec(s.count) if s.count is not None else 'cob_d_int(0)'
            em("cob_s64 cob_n = (cob_s64)cob_d_to_int(" + n + ");")
            em("unsigned char *cob_a = cob_alloc_chars(cob_n);")
            if s.init_value is not None:
                # fill the whole block with the value, repeating it
                em(f"cob_fill_block(cob_a, (size_t)cob_n, {self.field(s.init_value)});")
            elif s.initialized:
                em("memset(cob_a, 0, (size_t)cob_n);")
            if s.returning is not None:
                em(f"cob_pointer_set({self.field(s.returning)}, cob_a);")
            em("(void)cob_a;")
            em.ind -= 1
            em("}")
            return
        it = self.resolve(s.target)
        if not getattr(it, 'based', False):
            raise CompileError(f"ALLOCATE needs a BASED item; '{s.target.name}' is not one",
                               s.target.loc)
        sym = it.storage
        em(f"{sym} = cob_alloc_chars({it.size});")
        if s.initialized:
            self.init_based(it, sym)
        em.ind -= 1
        em("}")

    def init_based(self, item, sym):
        """ALLOCATE ... INITIALIZED: the INITIALIZE semantics, so an
        alphanumeric item becomes spaces and a numeric one zeroes, with the
        VALUE clauses then applied."""
        em = self.em
        self.init_spec = None
        self.init_item(item, sym, '0', 'initialize', root=True, root_occurs=bool(item.occurs))
        for it in item.walk():
            if it.children or it.value is None:
                continue
            f = f"CF({sym} + {it.offset}, {it.size}, &{self.item_attr(it)})"
            em(f"cob_move({self.field(it.value)}, {f});")

    def g_FreeStmt(self, s):
        em = self.em
        it = self.resolve(s.target)
        if not getattr(it, 'based', False) and getattr(it, 'type', None) == T_POINTER:
            # FREE pointer: release what ALLOCATE ... RETURNING handed back
            em(f"cob_free_chars(cob_pointer_get({self.field(s.target)}));")
            em(f"cob_pointer_set({self.field(s.target)}, NULL);")
            return
        if not getattr(it, 'based', False):
            raise CompileError(f"FREE needs a BASED item; '{s.target.name}' is not one",
                               s.target.loc)
        em(f"cob_free_chars({it.storage});")
        em(f"{it.storage} = NULL;")

    def pointer_value(self, e):
        """A pointer-valued expression, as an unsigned char*."""
        if isinstance(e, AddressOf):
            return self.address_of(e.ref)
        if isinstance(e, Figurative) and e.kind == 'NULL':
            return "NULL"
        it = self.resolve(e) if isinstance(e, DataRef) else None
        if it is not None and getattr(it, 'type', None) == T_POINTER:
            return f"cob_pointer_get({self.field(e)})"
        raise CompileError("a pointer value is needed here: ADDRESS OF item, "
                           "a POINTER item, or NULL", getattr(e, 'loc', None))

    def address_of(self, ref):
        it = self.resolve(ref)
        if getattr(it, 'based', False):
            return f"((unsigned char *){it.storage})"
        if getattr(it, 'section', None) == 'LK':
            # ADDRESS OF is how a program tests whether an argument was passed:
            # it must yield NULL rather than fail like a reference would
            return f"((unsigned char *)({it.storage} + {self.offset_expr(ref, it)}))"
        return f"({self.data_ptr(ref)})"

    # ---------------------------------------------------------------- XML
    def g_EntryStmt(self, s):
        # a label the dispatch at the top of the function can jump to
        k = getattr(s, '_entry_no', None)
        if k:
            self.em.label(f"L_entry_{k}")
        if self.opts.trace and getattr(s, 'name', None):
            self.em(f'if (cob_trace_on) cob_trace_point({self.trace_args()}, "Entry", '
                    f'{c_string(s.name)}, -1);')
        # ENTRY ... USING: this entry point's own parameters, bound from the
        # caller's argument list
        for i, ref in enumerate(getattr(s, 'using', []) or []):
            it = self.resolve(ref)
            if it.section != 'LK' or it.level not in (1, 77):
                raise CompileError(f"ENTRY USING item '{ref.name}' must be a level "
                                   f"01/77 LINKAGE item", ref.loc)
            self.em(f"if (cob_argc > {i} && cob_argv[{i}]) {it.storage} = cob_argv[{i}];")
        return

    def g_XmlGenerate(self, s):
        em = self.em
        src = self.resolve(s.src)
        if isinstance(src, IndexName):
            raise CompileError("XML GENERATE needs a data item", s.loc)
        self.check_receiving(s.out)
        names = {id(self.resolve(r)): nm for r, nm in s.names}
        types = {id(self.resolve(r)): t for r, t in s.types}
        prefix = None
        if s.namespace_prefix is not None:
            prefix = self.sym('xpfx_')
            em("{")
            em.ind += 1
            # the prefix without its trailing spaces; none when the
            # namespace is all spaces
            ns = self.field(s.namespace) if s.namespace is not None else 'NULL'
            em(f"char {prefix}[256];")
            em(f"cob_xml_prefix({prefix}, sizeof {prefix}, {self.field(s.namespace_prefix)}, {ns});")
        em("{")
        em.ind += 1
        em("xmlw cob_xw;")
        em("cob_xml_code_reset();")
        em(f"cob_xml_init(&cob_xw, {self.field(s.out)});")
        if prefix is not None:
            # NAMESPACE-PREFIX must be an XML name: XML-CODE 419 otherwise
            em(f"if (cob_xml_bad_prefix({prefix})) cob_xml_abort(&cob_xw, 419);")
        if s.declaration:
            em("cob_xml_declaration(&cob_xw);")
        em(f"unsigned char *cob_gb = ({self.field(s.src)})->data;")
        self._gen_base = ('cob_gb', src.offset)
        self._gen_src = src
        self.xml_member(src, names, types, s, prefix, [], top=True)
        cin = self.field(s.count_in) if s.count_in is not None else 'NULL'
        em(f"cob_xml_finish(&cob_xw, {cin});")
        em("int cob_xcode = cob_xml_code_value();")
        self.handlers('cob_xcode', s.on_exc, s.not_on_exc)
        em("(void)cob_xcode;")
        em.ind -= 1
        em("}")
        if s.namespace_prefix is not None:
            em.ind -= 1
            em("}")

    def xml_dpc(self):
        prog = getattr(self.ctx, 'prog', None) or getattr(self, 'prog', None)
        if prog is not None and getattr(prog, 'decimal_comma', False) \
                and getattr(self.opts, 'dpc_in_data', 'none') in ('xml', 'all'):
            return "'\u002c'"
        return "'.'"

    def xml_pfx(self, prefix):
        return prefix or 'NULL'

    def xml_name(self, it, names):
        return names.get(id(it)) or getattr(it, 'src_name', None) or it.name

    def xml_suppressed(self, it, s, is_attribute, field_expr):
        """C condition: is this item suppressed by a SUPPRESS clause?

        A clause naming the item wins over a SUPPRESS EVERY ... clause, and a
        later clause for the same target replaces an earlier one."""
        rules = {}
        for ref, figs, every in s.suppress:
            key = ('item', id(self.resolve(ref))) if ref is not None else ('every', every)
            rules[key] = (ref, figs, every)
        chosen = rules.get(('item', id(it)))
        if chosen is None:
            applicable = []
            for (kind, sel), rule in rules.items():
                if kind != 'every':
                    continue
                ref, figs, every = rule
                if every is None:
                    applicable.append(rule)          # SUPPRESS WHEN f: every item
                elif every == 'ATTRIBUTE' and is_attribute:
                    applicable.append(rule)
                elif every == 'ELEMENT' and not is_attribute:
                    applicable.append(rule)
                elif every == 'NONNUMERIC' and it.type not in self.JSON_NUMERIC:
                    applicable.append(rule)
            tests = []
            for _ref, figs, _every in applicable:
                tests.extend(self.xml_fig_tests(figs, field_expr))
        else:
            tests = self.xml_fig_tests(chosen[1], field_expr)
        if not tests:
            return None
        return '(' + ' || '.join(tests) + ')'

    @staticmethod
    def xml_fig_tests(figs, field_expr):
        out = []
        for f in figs:
            ch = {'SPACE': ' ', 'SPACES': ' ', 'ZERO': '0', 'ZEROS': '0',
                  'ZEROES': '0', 'LOW-VALUE': '\\0', 'LOW-VALUES': '\\0',
                  'HIGH-VALUE': '\\xff', 'HIGH-VALUES': '\\xff'}.get(f)
            if ch is not None:
                out.append(f"cob_xml_all({field_expr}, '{ch}')")
        return out

    def xml_kind(self, it, types, all_attributes):
        t = types.get(id(it))
        if t in ('ATTRIBUTE', 'CONTENT'):
            return t
        return 'ATTRIBUTE' if all_attributes and not it.children else 'ELEMENT'

    def xml_member(self, it, names, types, s, prefix, subs, top=False):
        em = self.em
        name = self.xml_name(it, names)
        pfx = self.xml_pfx(prefix)
        occ = None if top else it.occurs     # a subscripted source is one element
        if occ is not None:
            # a table: its element once per occurrence
            _i, subs = self.gen_occurs_open(it, subs)
        if it.children:
            em("{")
            em.ind += 1
            em("size_t cob_xm = cob_xml_mark(&cob_xw);")
            em(f"cob_xml_elem_open(&cob_xw, {pfx}, {c_string(name)});")
            if top and s.namespace is not None:
                em(f"cob_xml_root_namespace(&cob_xw, {pfx}, {self.field(s.namespace)});")
            for c in self.xml_members(it, s):
                self.xml_member(c, names, types, s, prefix, subs)
            em(f"cob_xml_elem_close(&cob_xw, {pfx}, {c_string(name)});")
            if not top:
                em("cob_xml_rollback_if_empty(&cob_xw, cob_xm);")
            em.ind -= 1
            em("}")
            if occ is not None:
                self.gen_occurs_close()
            return
        kind = self.xml_kind(it, types, s.all_attributes)
        if occ is not None and kind == 'ATTRIBUTE':
            # an attribute appears once in an element: a table's are elements
            if types.get(id(it)) == 'ATTRIBUTE':
                DIAG.warn(f"XML GENERATE: '{name}' has OCCURS, so it is generated as elements, "
                          "not as an attribute", s.loc)
            kind = 'ELEMENT'
        field = self.json_field(it, subs)
        cond = self.xml_suppressed(it, s, kind == 'ATTRIBUTE', field)
        if cond is not None:
            em(f"if (!{cond}) {{")
            em.ind += 1
        text_fn = 'cob_xml_text_just' if (it.flags & F_JUSTIFIED) else 'cob_xml_text'
        if kind == 'ATTRIBUTE' and it.type in self.JSON_NUMERIC:
            em(f"cob_xml_attr_num(&cob_xw, {pfx}, {c_string(name)}, {field}, {self.xml_dpc()});")
        elif kind == 'ATTRIBUTE':
            em(f"cob_xml_attr(&cob_xw, {pfx}, {c_string(name)}, {field});")
        elif kind == 'CONTENT':
            if it.type in self.JSON_NUMERIC:
                em(f"cob_xml_num(&cob_xw, {field}, {self.xml_dpc()});")
            else:
                em(f"{text_fn}(&cob_xw, {field});")
        else:
            em(f"cob_xml_elem_open(&cob_xw, {pfx}, {c_string(name)});")
            if top and s.namespace is not None:
                em(f"cob_xml_root_namespace(&cob_xw, {pfx}, {self.field(s.namespace)});")
            if it.type in self.JSON_NUMERIC:
                em(f"cob_xml_num(&cob_xw, {field}, {self.xml_dpc()});")
            else:
                em(f"{text_fn}(&cob_xw, {field});")
            em(f"cob_xml_elem_close(&cob_xw, {pfx}, {c_string(name)});")
        if cond is not None:
            em.ind -= 1
            em("}")
        if occ is not None:
            self.gen_occurs_close()

    def xml_members(self, it, s):
        out = []
        for c in it.children:
            if c.level in (66, 88) or not c.name:
                continue
            if c.redefines is not None:
                continue
            out.append(c)
        return out

    # ---------------------------------------------------------------- JSON
    JSON_NUMERIC = (T_NUM_DISPLAY, T_NUM_PACKED, T_NUM_BINARY, T_NUM_COMP5,
                    T_NUM_FLOAT, T_NUM_DOUBLE, T_INDEX, T_NUM_DEC_FLOAT)

    def g_XmlParse(self, s):
        """XML PARSE: the runtime reads the document into events; the
        processing procedure is PERFORMed for each. The parser's state lives
        in the runtime, not here: a PERFORM leaves this block."""
        em = self.em
        em("{")
        em.ind += 1
        em(f"cob_xml_parse_start({self.field(s.doc)});")
        em("while (cob_xml_parse_next()) {")
        em.ind += 1
        self.perform_call(s.proc, s.thru, cause='XML')
        em("if (cob_xml_parse_after())")
        em("\tbreak;")
        em.ind -= 1
        em("}")
        em("int cob_xc = cob_xml_parse_finish();")
        self.handlers('cob_xc != 0', s.on_exc, s.not_on_exc)
        em("(void)cob_xc;")
        em.ind -= 1
        em("}")

    def g_JsonGenerate(self, s):
        em = self.em
        src = self.resolve(s.src)
        if isinstance(src, IndexName):
            raise CompileError("JSON GENERATE needs a data item", s.loc)
        self.check_receiving(s.out)
        names, omitted, suppress = {}, set(), set()
        for ref, nm in s.names:
            it = self.resolve(ref)
            if nm is None:
                omitted.add(id(it))
            else:
                names[id(it)] = nm
        for ref in s.suppress:
            suppress.add(id(self.resolve(ref)))
        em("{")
        em.ind += 1
        em("jsonw cob_jw;")
        em("cob_json_code_reset();")
        em(f"cob_json_init(&cob_jw, {self.field(s.out)});")
        # the items are found from the source's storage, which a subscript moves
        em(f"unsigned char *cob_gb = ({self.field(s.src)})->data;")
        self._gen_base = ('cob_gb', src.offset)
        self._gen_src = src
        em("cob_json_obj_open(&cob_jw);")
        self.json_member(src, names, omitted, suppress, [True], [], top=True)
        em("cob_json_obj_close(&cob_jw);")
        cin = self.field(s.count_in) if s.count_in is not None else 'NULL'
        em(f"cob_json_finish(&cob_jw, {cin});")
        em("int cob_jcode = cob_json_code_value();")
        self.handlers('cob_jcode', s.on_exc, s.not_on_exc)
        em("(void)cob_jcode;")
        em.ind -= 1
        em("}")

    def g_JsonParse(self, s):
        """JSON PARSE: the receiver goes to the runtime as a table of nodes,
        each subtree contiguous, and the runtime reads the text once, giving
        each value to the item its name matches."""
        em = self.em
        root = self.resolve(s.into)
        if not isinstance(root, DataItem) or root.level in (66, 88):
            raise CompileError("JSON PARSE needs a data item to receive the values", s.loc)
        self.check_receiving(s.into)
        names, suppress, conv, omitted = {}, set(), {}, False
        for ref, nm in s.names:
            it = self.resolve(ref)
            if nm is None:
                if it is not root:
                    raise CompileError(f"NAME OF {ref.name} IS OMITTED: only the receiver can be "
                                       "OMITTED", ref.loc)
                omitted = True
            else:
                names[id(it)] = nm
        for ref in s.suppress:
            suppress.add(id(self.resolve(ref)))
        for ref, spec in s.converting:
            it = self.resolve(ref)
            if not isinstance(it, DataItem) or it.children or it.level in (66, 88):
                raise CompileError(f"CONVERTING '{ref.name}': an elementary data item is needed",
                                   ref.loc)
            if spec[0] == 'LITS':
                conv[id(it)] = (self.lit_str(spec[1]), self.lit_str(spec[2]))
                continue
            conds = [self.resolve(r) for r in spec[1:]]
            for r, c in zip(spec[1:], conds):
                if not (isinstance(c, DataItem) and c.level == 88 and c.parent is it):
                    raise CompileError(f"CONVERTING '{ref.name}': '{r.name}' is not a "
                                       f"condition-name of it", r.loc)
            if len(conds) == 2:
                tv, fv = conds[0].values[0][0], conds[1].values[0][0]
            else:
                if conds[0].false_value is None:
                    raise CompileError(f"condition-name '{spec[1].name}' has no WHEN SET TO FALSE "
                                       "value, so false has nothing to set", spec[1].loc)
                tv, fv = conds[0].values[0][0], conds[0].false_value
            conv[id(it)] = (self.field(tv), self.field(fv))
        rows = []
        self.jp_node(root, root, names, suppress, conv, rows, omitted)
        em("{")
        em.ind += 1
        em(f"const cob_jp_node cob_jpn[{len(rows)}] = {{")
        for r in rows:
            em("\t{" + ", ".join(f".{k} = {v}" for k, v in r) + "},")
        em("};")
        detail = 1 if s.detail else 0
        em(f"int cob_jcode = cob_json_parse({self.field(s.text)}, {self.field(s.into)}, "
           f"cob_jpn, {detail});")
        self.handlers('cob_jcode', s.on_exc, s.not_on_exc)
        em("(void)cob_jcode;")
        em.ind -= 1
        em("}")

    def jp_node(self, it, root, names, suppress, conv, rows, omitted=False):
        """Describe it and what it holds to JSON PARSE, preorder; False when
        nothing in it can take a value: FILLER, condition names, RENAMES,
        the second and later items of a REDEFINES set, SUPPRESSed items,
        pointers, and groups left with none of the rest."""
        top = it is root
        if not top and (it.level in (66, 88) or not it.name or id(it) in suppress
                        or it.redefines is not None):
            return False
        at = len(rows)
        rows.append(None)
        if it.children:
            kept = [self.jp_node(c, root, names, suppress, conv, rows) for c in it.children]
            if not any(kept) and not top:
                del rows[at:]
                return False
            kind, attr = 'COB_JP_GROUP', 'NULL'
        else:
            if it.type == T_POINTER:
                if top:
                    raise CompileError("JSON PARSE cannot give a value to a pointer", it.loc)
                del rows[at:]
                return False
            kind = 'COB_JP_BOOL' if id(it) in conv else 'COB_JP_ITEM'
            attr = f"&{self.item_attr(it)}"
        if top and omitted:
            name = 'NULL'
        else:
            name = c_string(names[id(it)] if id(it) in names else self.json_name(it, names))
        occ = None if top else it.occurs
        tv, fv = conv.get(id(it), ('NULL', 'NULL'))
        rows[at] = [('name', name), ('exact', 1 if id(it) in names else 0), ('kind', kind),
                    ('span', len(rows) - at), ('offset', it.offset - root.offset),
                    ('size', it.size), ('occurs', occ.max if occ else 0),
                    ('odo', self.field(occ.depending) if occ and occ.depending else 'NULL'),
                    ('attr', attr), ('tv', tv), ('fv', fv)]
        return True

    def json_name(self, it, names):
        if id(it) in names:
            return names[id(it)]
        return getattr(it, 'src_name', None) or it.name

    def json_members(self, it, names, omitted, suppress):
        """The children of a group that JSON GENERATE writes: no FILLER, no
        condition names, no RENAMES, only the first item of a REDEFINES set,
        and no group left with nothing to write."""
        out = []
        for c in it.children:
            if c.level in (66, 88) or not c.name or id(c) in suppress:
                continue
            if c.redefines is not None:
                continue            # the item it redefines already covers it
            if c.children and not self.json_members(c, names, omitted, suppress):
                continue            # a group whose every member is suppressed
            out.append(c)
        return out

    def json_member(self, it, names, omitted, suppress, first, subs, top=False):
        em = self.em
        name = self.json_name(it, names)
        om = id(it) in omitted
        occ = None if top else it.occurs     # a subscripted source is one element
        if not om:
            if not first[0]:
                em("cob_json_comma(&cob_jw);")
            first[0] = False
            em(f'cob_json_key(&cob_jw, {c_string(name)});')
        if occ is not None:
            # a table -> an array, of objects for a group
            em("cob_json_arr_open(&cob_jw);")
            i, subs = self.gen_occurs_open(it, subs)
            em(f"if ({i}) cob_json_comma(&cob_jw);")
        if it.children:
            members = self.json_members(it, names, omitted, suppress)
            if not om or not top:
                em("cob_json_obj_open(&cob_jw);")
            inner = [True]
            for c in members:
                self.json_member(c, names, omitted, suppress, inner, subs)
            if not om or not top:
                em("cob_json_obj_close(&cob_jw);")
        else:
            self.json_value(it, subs)
        if occ is not None:
            self.gen_occurs_close()
            em("cob_json_arr_close(&cob_jw);")

    def gen_occurs_open(self, it, subs):
        """Open a C loop over the occurrences of the table it -- as many as
        its DEPENDING ON object says, when it has one -- for JSON and XML
        GENERATE; returns the loop variable and subs with it added."""
        em = self.em
        occ = it.occurs
        i = self.sym('gi_')
        em("{")
        em.ind += 1
        count = str(occ.max)
        ctx = {id(t): f"({v} + 1)" for v, _stride, t in subs}
        if occ.depending is not None:
            cur = self.odo_count(it, None, ctx, check=False)
            if cur is not None:
                count = self.sym('gn_')
                em(f"cob_s64 {count} = {cur};")
                em(f"if ({count} > {occ.max}) {count} = {occ.max}; else if ({count} < 0) {count} = 0;")
        stride = self.odo_stride(it, None, ctx)
        em(f"for (cob_s64 {i} = 0; {i} < {count}; {i}++) {{")
        em.ind += 1
        return i, subs + [(i, stride, it)]

    def gen_occurs_close(self):
        em = self.em
        em.ind -= 1
        em("}")
        em.ind -= 1
        em("}")

    def json_value(self, it, subs):
        em = self.em
        field = self.json_field(it, subs)
        if it.type in self.JSON_NUMERIC:
            em(f"cob_json_num(&cob_jw, {field}, {self.json_dpc()});")
        else:
            just = 1 if (it.flags & F_JUSTIFIED) else 0
            em(f"cob_json_str(&cob_jw, {field}, {just});")

    def json_dpc(self):
        """The decimal separator for JSON numbers: ',' only when a comma
        decimal point is in force and -fdpc-in-data asks for it in JSON."""
        prog = getattr(self.ctx, 'prog', None) or getattr(self, 'prog', None)
        if prog is not None and getattr(prog, 'decimal_comma', False) \
                and getattr(self.opts, 'dpc_in_data', 'none') in ('json', 'all'):
            return "','"
        return "'.'"

    def json_field(self, it, subs):
        """C expression for an elementary item of a JSON or XML GENERATE
        source, applying enclosing OCCURS: found from the source's storage."""
        base, root = self._gen_base
        term = [str(it.offset - root)] + [f"{v} * {stride}" for v, stride, _t in subs]
        total = ' + '.join(term)
        # after a variable table in the source: where it is now (odogen)
        ctx = {id(t): f"({v} + 1)" for v, _stride, t in subs}
        before = self.odo_before(it, None, ctx, stop=getattr(self, '_gen_src', None))
        if before:
            total = f"{total} - {' - '.join(before)}"
        return f"CF({base} + ({total}), {it.size}, &{self.item_attr(it)})"

    def g_Display(self, s):
        em = self.em
        if len(s.items) == 1 and self.screen_item(s.items[0]) is not None:
            return self.g_screen_display(s.parts[0] if s.parts else s, self.screen_item(s.items[0]))
        if getattr(s, 'screen', False) or any(self.screen_item(i) is not None for i in s.items):
            return self.g_display_at(s)
        upon = s.upon
        if upon in ('ENVIRONMENT-NAME', 'ENVIRONMENT-VALUE', 'ARGUMENT-NUMBER'):
            k = {'ENVIRONMENT-NAME': 0, 'ENVIRONMENT-VALUE': 1, 'ARGUMENT-NUMBER': 2}[upon]
            em(f"cob_display_env({k}, {self.field(s.items[0])});")
            return
        # UPON selects the device: CONSOLE (also the default) is stdout, SYSERR
        # is stderr, PRINTER and SYSPUNCH are files the environment names --
        # COB_DISPLAY_PRINT_FILE / COB_DISPLAY_PRINT_PIPE and
        # COB_DISPLAY_PUNCH_FILE. Without one, SYSPUNCH is skipped and its
        # ON EXCEPTION runs.
        DEV = {'SYSERR': 1, 'STDERR': 1, 'CONSOLE': 0, 'PRINTER': 2,
               'SYSPUNCH': 3, 'SYSPCH': 3}
        dev = DEV.get(upon, 0)
        if dev == 3 and s.on_exc is not None:
            # SYSPUNCH with no COB_DISPLAY_PUNCH_FILE: warn, skip, ON EXCEPTION
            em("{")
            em.ind += 1
            em(f"if (!cob_display_ok(3)) {{ cob_display_warn_punch({self.locstr()});")
            self.stmts(s.on_exc)
            em("} else {")
            em.ind += 1
        elif dev == 3:
            em("{")
            em.ind += 1
            em(f"if (!cob_display_ok(3)) cob_display_warn_punch({self.locstr()});")
            em("else {")
            em.ind += 1
        # operands that can fail (subscripts, reference modification) are all
        # evaluated before anything is displayed
        early = len(s.items) > 1 and any(
            isinstance(it, (DataRef, FuncCall)) and (getattr(it, 'subs', None) or it.refmod or isinstance(it, FuncCall))
            for it in s.items)
        fields = {}
        if early:
            em("{")
            em.ind += 1
            for i, it in enumerate(s.items):
                if isinstance(it, FuncCall) and it.name in self.udf_names:
                    fields[i] = self.udf_field(it)      # the call must run first
                elif isinstance(it, FuncCall) and self.is_numeric(it) and not it.refmod:
                    fields[i] = self.func_field(it)
                elif isinstance(it, (DataRef, FuncCall)):
                    fields[i] = self.field(it)
                else:
                    continue
                em(f"const cob_field *cob_dv{i} = {fields[i]};")
                fields[i] = f"cob_dv{i}"
        for i, it in enumerate(s.items):
            if i in fields:
                em(f"cob_display({dev}, {fields[i]});")
            elif isinstance(it, StrLit):
                v = it.value
                em(f"cob_display_lit({dev}, {c_string(v)}, {len(v)});")
            elif isinstance(it, NumLit):
                t = it.text.replace('.', ',') if self.prog.decimal_comma else it.text
                em(f"cob_display_lit({dev}, {c_string(t)}, {len(t)});")
            elif isinstance(it, Figurative):
                v = FIG_BYTES[it.kind]
                em(f"cob_display_lit({dev}, {c_string(v)}, 1);")
            elif isinstance(it, AllLit):
                em(f"cob_display_lit({dev}, {c_string(it.value)}, {len(it.value)});")
            elif isinstance(it, FuncCall) and self.is_numeric(it) and not it.refmod:
                em(f"cob_display({dev}, {self.func_field(it)});")
            elif isinstance(it, LengthOf) and not self.length_of(it).isdigit():
                em(f"cob_display_signed({dev}, (cob_s64)({self.length_of(it)}), 9);")
            elif isinstance(it, (LengthOf, BinOp, Neg)):
                em(f"cob_display_dec({dev}, {self.dec(it)});")
            else:
                em(f"cob_display({dev}, {self.field(it)});")
        em(f"cob_display_end({dev}, {0 if s.no_advancing else 1});")
        if dev == 3:
            em.ind -= 1
            em("}")
        if early:
            em.ind -= 1
            em("}")
        if dev == 3:
            em.ind -= 1
            em("}")
        if s.not_on_exc:
            self.dbg_flush()
            self.stmts(s.not_on_exc)

    def g_Exhibit(self, s):
        """EXHIBIT: display operands, with their names when NAMED, and only
        those that changed since the last time this statement ran when
        CHANGED."""
        em = self.em
        snap = None
        if s.changed:
            snap = self.sym('exh_')
            sizes = [self.exhibit_size(e) for e in s.items]
            total = sum(sizes) + len(sizes)
            em("{")
            em.ind += 1
            em(f"static unsigned char {snap}[{total}];")
            em(f"static int {snap}_init;")
            em(f"unsigned char {snap}_now[{total}];")
            em("size_t cob_o = 0;")
            for e, n in zip(s.items, sizes):
                f = self.field(e)
                em(f"memcpy({snap}_now + cob_o, ({f})->data, {n} > ({f})->size ? ({f})->size : {n});")
                em(f"if (({f})->size < {n}) memset({snap}_now + cob_o + ({f})->size, ' ', {n} - ({f})->size);")
                em("cob_o += " + str(n) + ";")
                em(f"{snap}_now[cob_o++] = 0x01;")
            em(f"int cob_ch = !{snap}_init || memcmp({snap}, {snap}_now, {total}) != 0;")
            em(f"memcpy({snap}, {snap}_now, {total});")
            em(f"{snap}_init = 1;")
            em("if (cob_ch) {")
            em.ind += 1
        for k, e in enumerate(s.items):
            if k:
                em('cob_display_lit(0, " ", 1);')
            if s.named:
                nm = e.name if isinstance(e, DataRef) else None
                if nm is not None:
                    em(f'cob_display_lit(0, {c_string(nm + " = ")}, {len(nm) + 3});')
            em(f"cob_display(0, {self.field(e)});")
        em("cob_display_end(0, 1);")
        if s.changed:
            em.ind -= 1
            em("}")
            em.ind -= 1
            em("}")

    def exhibit_size(self, e):
        if isinstance(e, DataRef):
            it = self.resolve(e)
            return max(1, getattr(it, 'size', 1))
        return max(1, len(e.value) if isinstance(e, StrLit) else 1)

    def g_Accept(self, s):
        em = self.em
        if s.source == 'OMITTED':
            em("cob_accept_discard();")
            return
        if self.screen_item(s.target) is not None:
            return self.g_screen_accept(s, self.screen_item(s.target))
        if s.source in ('ESCAPE', 'EXCEPTION'):
            # ACCEPT ... FROM ESCAPE KEY: the key that ended the last screen ACCEPT
            self.check_receiving(s.target)
            em(f"cob_set_int({self.field(s.target)}, cob_scr_escape_key());")
            return
        if getattr(s, 'screen', False):
            return self.g_accept_at(s)
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
        if ob.kind == 'RELOP':
            # "WHEN >= 10000": compare the subject with the object
            cop = CMP_OP[ob.a]
            if kind == 'V':
                c = f"(cob_d_cmp({self.dec(sv)}, {self.dec(ob.b)}) {cop} 0)"
            elif kind == 'C':
                c = self.rel(sv, ob.a, ob.b)
            else:
                raise CompileError("a relational WHEN object needs a value subject",
                                   self.cur_loc)
            return f"!{c}" if ob.neg else c
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
            if ob.kind == 'COND':
                # a condition subject compared with a condition object: the two
                # truth values must agree
                c = self.cond(ob.a)
                return f"(({sv}) == ({c}))"
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
    def cur_proc_desc(self):
        """'paragraph P' or 'section S': where the statement being generated is."""
        para = getattr(self, 'cur_para', None)
        sect = getattr(self, 'cur_section', None)
        if para is not None and para.name:
            return f"paragraph {para.name}"
        if sect is not None and sect.name:
            return f"section {sect.name}"
        return None

    def site(self, what, dynamic=False):
        """A static cob_site for the PERFORM or CALL being generated, for a
        runtime error's stack trace."""
        inn = self.cur_proc_desc()
        key = (str(self.cur_loc), what, inn, dynamic)
        sites = self.__dict__.setdefault('_sites', {})
        sym = sites.get(key)
        if sym is None:
            sym = self.sym('cob_site_')
            self.glob.append(f"static const cob_site {sym} = {{{self.locstr()}, {c_string(what)}, "
                             f"{c_string(inn) if inn else 'NULL'}, {1 if dynamic else 0}}};")
            sites[key] = sym
        return sym

    def frame_push(self, target, what, ret):
        em = self.em
        pf = self.sym('cob_pf_')
        self.performs.append(f"static const cob_perform {pf} = {{ {target.id}, &&{ret}, &{self.site(what)} }};")
        if getattr(self.opts, 'stack_trace', True):
            # the frames up to COB_FRAMES_CLEAR start NULL; past them, a push
            # clears the next itself
            em(f"if (++frame_ptr >= cob_frames + COB_FRAMES_CLEAR) {{")
            em(f"\tif (frame_ptr == cob_frames + COB_STACK_SIZE) cob_perform_overflow({self.locstr()});")
            em("\tframe_ptr[1] = NULL;")
            em("}")
        else:
            em(f"if (++frame_ptr == cob_frames + COB_STACK_SIZE) cob_perform_overflow({self.locstr()});")
        em(f"*frame_ptr = &{pf};")

    def frame_pop(self):
        # a return clears its frame, so a walk from the base stops at the top
        # (only the stack trace walks the frames)
        if getattr(self.opts, 'stack_trace', True):
            self.em("*frame_ptr-- = NULL;")
        else:
            self.em("frame_ptr--;")

    PERFORM_WHAT = {'PERFORM': 'PERFORM', 'SORT_IN': 'SORT INPUT PROCEDURE',
                    'SORT_OUT': 'SORT OUTPUT PROCEDURE', 'MERGE_OUT': 'MERGE OUTPUT PROCEDURE',
                    'XML': 'XML PARSE PROCESSING PROCEDURE'}

    def perform_call(self, first, last, cause='PERFORM'):
        em = self.em
        t1 = self.resolve_proc(first)
        t2 = self.resolve_proc(last) if last else t1
        ret = self.new_label('R')
        what = f"{self.PERFORM_WHAT.get(cause, 'PERFORM')} {t1.name}"
        if t2 is not t1:
            what += f" THRU {t2.name}"
        self.frame_push(t2, what, ret)
        self.dbg_emit_cause('PERFORM' if cause == 'XML' else cause)
        em(f"goto {t1.label};")
        em.label(ret)
        self.frame_pop()
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
                em("break; " + '}' * self.cond_open(s, s.until))
            body()
            em.label(cont)
            if s.test_after:
                em("break; " + '}' * self.cond_open(s, s.until))
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
            self.dbg_perf(s, v.var, v.frm)
        if not s.test_after:
            em.label(labels[0])
            em(f"goto {brk}; " + '}' * self.cond_open(s, vs[0].until))
            for k in range(1, n):
                em.label(labels[k])
                nb = self.cond_open(s, vs[k].until)
                em.ind += 1
                em(self.aug_var(vs[k - 1].var, vs[k - 1].by))
                self.dbg_perf(s, vs[k - 1].var, vs[k - 1].by)
                em(self.set_var(vs[k].var, vs[k].frm))
                self.dbg_perf(s, vs[k].var, vs[k].frm)
                em(f"goto {labels[k - 1]};")
                em.ind -= 1
                em('}' * nb)
            body()
            em.label(cont)
            em(self.aug_var(vs[n - 1].var, vs[n - 1].by))
            self.dbg_perf(s, vs[n - 1].var, vs[n - 1].by)
            em(f"goto {labels[n - 1]};")
        else:
            top = labels[0]
            em.label(top)
            body()
            em.label(cont)
            for k in range(n - 1, -1, -1):
                nb = self.cond_open(s, vs[k].until, neg=True)
                em.ind += 1
                em(self.aug_var(vs[k].var, vs[k].by))
                self.dbg_perf(s, vs[k].var, vs[k].by)
                for j in range(k + 1, n):
                    em(self.set_var(vs[j].var, vs[j].frm))
                    self.dbg_perf(s, vs[j].var, vs[j].frm)
                em(f"goto {top};")
                em.ind -= 1
                em('}' * nb)

    # ---------------------------------------------------------------- control flow
    def proc_label(self, pr):
        return self.resolve_proc(pr).label

    def g_GoTo(self, s):
        em = self.em
        if s.depending is None:
            var = self.alter_paras.get(id(self.cur_para))
            self.dbg_emit_cause('GOTO')
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
        self.dbg_flush('goto')
        em(f"switch ({self.int_expr(s.depending)}) {{")
        cause = self.dbg_cause('GOTO')
        for i, t in enumerate(s.targets):
            em(f"case {i + 1}: {cause + ' ' if cause else ''}goto {self.proc_label(t)};")
        em("default: break;")
        em("}")

    def g_Alter(self, s):
        for p1, p2 in s.pairs:
            t1 = self.resolve_proc(p1)
            var = self.alter_paras[id(t1)]
            self.em(f"{var} = &&{self.proc_label(p2)};")
            self.dbg_alter(t1, self.resolve_proc(p2))

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
            ret = getattr(s, 'returning', None)
            if ret is not None:
                em(f"if (cob_argc >= 0) {{ cob_set_int(&cob_return_code, {self.int_expr(ret)}); goto L_exit; }}")
            else:
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

    def g_Unlock(self, s):
        """UNLOCK file: its record locks go; COMMIT / ROLLBACK: every file's
        (each change is on disk as it is made: nothing to commit or undo)."""
        if s.file is None:
            self.em("cob_unlock_all();")
            return
        fi = self.file_info(s.file, s.loc)
        self.io_result(fi, f"cob_unlock(&{fi.sym})", flush=False)

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
                 'FIRST': 'COB_INSP_FIRST', 'TRAILING': 'COB_INSP_TRAILING'}
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
            if ref.refmod:
                # a reference-modified item is alphanumeric: spaces, or the
                # REPLACING ALPHANUMERIC value
                val = next((v for cat, v in s.replacing if cat == 'ALPHANUMERIC'), None)
                src = self.field(val) if val is not None else '&cob_fig_space'
                em(f"cob_move({src}, {self.ref_field(ref, True)});")
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
            # a group that holds the DEPENDING ON item of one of its variable
            # tables is initialized at its full size (as it is moved to)
            self.init_full = self.odo_object_inside(it)
            self.init_item(it, 'cob_ib', '0', 'initialize', root=True, root_occurs=whole_table,
                           ctx=self.ref_ctx(pref, it) or {})
            em.ind -= 1
            em("}")

    def init_tree(self, root, mode):
        self.init_spec = None
        if root.level == 66:
            return
        if getattr(root, 'based', False):
            # a BASED item has no storage until ALLOCATE; its VALUE clauses
            # apply when it is allocated INITIALIZED
            return
        self.init_item(root, root.storage, str(root.offset), mode, root=True, root_occurs=bool(root.occurs))

    def init_item(self, it, base, off, mode, root=False, root_occurs=False, ctx=None):
        em = self.em
        if it.level in (66, 88):
            return
        if not root and it.redefines is not None:
            return
        spec = self.init_spec
        if not root and it.is_filler and not it.children and mode == 'initialize' and \
                not (spec and spec.with_filler):
            return              # elementary FILLER items (the named items of a FILLER group are initialized)
        if it.occurs and (not root or root_occurs):
            occ = it.occurs
            v = self.sym('cob_i')
            self.local(f"cob_s64 {v};")
            stride = str(it.size)
            if getattr(occ, 'unbounded', False):
                # OCCURS UNBOUNDED: as many occurrences as DEPENDING ON says
                bound = self.int_expr(occ.depending)
            elif occ.depending is not None and mode == 'initialize':
                # INITIALIZE: the occurrences the table has now -- or all of
                # them, for a plain INITIALIZE of a table whose maximum is
                # kept in the layout or of a group that holds its counter
                plain = not (spec and (spec.to_value or spec.replacing))
                count = None
                if not (plain and (not self.odo_varies(it) or getattr(self, 'init_full', False))):
                    count = self.odo_count(it, None, ctx)
                if count is None:
                    bound = str(occ.max)
                else:
                    bound = self.sym('cob_n')
                    self.local(f"cob_s64 {bound};")
                    em(f"{bound} = {count};")
                    em(f"if ({bound} > {occ.max}) {bound} = {occ.max}; else if ({bound} < 0) {bound} = 0;")
            else:
                bound = str(occ.max)
            if mode == 'initialize' and not getattr(occ, 'unbounded', False):
                stride = self.odo_stride(it, None, ctx)
            if mode == 'initialize':
                ctx = dict(ctx or {})
                ctx[id(it)] = f"({v} + 1)"
            em(f"for ({v} = 0; {v} < {bound}; {v}++) {{")
            em.ind += 1
            self.init_one(it, base, f"{off} + {v} * {stride}", mode, ctx)
            em.ind -= 1
            em("}")
        else:
            self.init_one(it, base, off, mode, ctx)

    def init_one(self, it, base, off, mode, ctx=None):
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
                coff = f"{off} + {c.offset - it.offset}"
                if mode == 'initialize' and self.odo_may_vary(it):
                    # after a variable table: where it is now (odogen)
                    before = [x for x in (self.odo_shrink(b, None, ctx) for b in storage_children(it)
                                          if b.offset < c.offset) if x is not None]
                    if before:
                        coff = f"({coff} - {' - '.join(before)})"
                self.init_item(c, base, coff, mode, ctx=ctx)
            return
        t = it.type
        if t in (T_INDEX, T_POINTER):
            # INITIALIZE sets a pointer to NULL, in every mode
            em(f"memset({base} + {off}, 0, {it.size});")
            return
        cat = it.category()
        if mode == 'init':
            if it.value is not None:
                em(self.value_move(it.value, f, it))
                return
            if getattr(self.opts, 'defaultbyte', None) is not None and it.section == 'WS':
                # -fdefaultbyte: storage without a VALUE starts as this byte
                em(f"memset({base} + {off}, {self.opts.defaultbyte}, {it.size});")
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
        if isinstance(v, NumLit) and (len(v.digits) > 255 or not -128 <= v.scale <= 127):
            # the fixed spelling does not fit a cob_attr; use the decimal value
            return f"cob_d_set({f}, {self.dec(v)}, 0);"
        if isinstance(v, NumLit) or (isinstance(v, Figurative) and v.kind == 'ZERO' and
                                     (it.type in NUMERIC_TYPES or it.type == T_NUM_EDITED)):
            return f"cob_move({self.field(v)}, {f});"
        if isinstance(v, AllLit) and v.is_zero and (it.type in NUMERIC_TYPES or it.type == T_NUM_EDITED):
            return f"cob_move({self.field(v)}, {f});"
        if it.type in (T_NUM_PACKED, T_NUM_BINARY, T_NUM_COMP5, T_NUM_FLOAT, T_NUM_DOUBLE,
                       T_INDEX, T_NUM_DEC_FLOAT):
            return f"cob_move({self.field(v)}, {f});"
        return f"cob_move_raw({self.field(v)}, {f});"

    # ---------------------------------------------------------------- SET
    def g_SetStmt(self, s):
        em = self.em
        if s.kind == 'EXCEPTION':
            em("cob_clear_exception();")
            return
        if s.kind == 'TO_ENTRY':
            name = s.value.value.decode('latin-1')
            for t in s.targets:
                it = self.check_receiving(t)
                sym = self.find_program(name.strip())
                if sym and sym != 'NULL':
                    # a program of this compile: its C-convention entry
                    em(f"cob_pointer_set({self.field(t)}, (void *)cob_cw_{sym});")
                else:
                    em(f"cob_pointer_set({self.field(t)}, cob_entry_address({c_string(name.strip())}, "
                       f"{self.weak_symbol(name.strip())}));")
            return
        if s.kind == 'ENVIRONMENT':
            em(f"cob_set_env({self.field(s.addr_ref)}, {self.field(s.value)});")
            return
        if s.kind == 'ADDRESS':
            # SET ADDRESS OF item TO <pointer>: rebind a LINKAGE item's storage
            it = self.resolve(s.addr_ref)
            based = getattr(getattr(it, 'record', None), 'based', False)
            if it.section != 'LK' and not based:
                raise CompileError(f"SET ADDRESS OF needs a LINKAGE or BASED item; "
                                   f"'{s.addr_ref.name}' is neither", s.loc)
            em(f"{it.storage} = (unsigned char *){self.pointer_value(s.value)};")
            return
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
                vref.implicit = True     # the condition's item: not named in the source
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
                elif it.type == T_POINTER:
                    # SET pointer TO ADDRESS OF item / another pointer / NULL
                    em(f"cob_pointer_set({self.field(t)}, {self.pointer_value(s.value)});")
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
            elif getattr(it, 'type', None) == T_POINTER:
                # SET pointer UP BY n: the address moves n bytes (it used to
                # be added to as if it were a number in DISPLAY form)
                f = self.field(t)
                em(f"cob_pointer_set({f}, (void *)((char *)cob_pointer_get({f}) {op} "
                   f"(intptr_t)({self.int_expr(s.value)})));")
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
            vref.implicit = True     # the condition's item: not named in the source
            return (var, vref, cn.values[0][0])
        if isinstance(c, Rel) and c.op == 'EQ':
            for a, b in ((c.left, c.right), (c.right, c.left)):
                if isinstance(a, DataRef):
                    it = self.resolve(a)
                    if isinstance(it, DataItem) and tbl in [it] + list(it.ancestors()):
                        return (it, a, b)
        return None

    # ---------------------------------------------------------------- CALL
    def call_site(self, s):
        if isinstance(s.prog, StrLit):
            return self.site(f'CALL "{s.prog.value.decode("latin-1").strip()}"')
        name = getattr(s.prog, 'name', None) or 'program'
        return self.site(f"CALL {name}", dynamic=True)

    def g_Call(self, s):
        it = None
        if isinstance(s.prog, StrLit):
            name = s.prog.value.decode('latin-1').strip()
            if name in SYSTEM_ROUTINES:
                return self.call_system_routine(s, name)
        em = self.em
        em("{")
        em.ind += 1
        n = len(s.args)
        frees = []
        sizes = []
        omitted = []
        em(f"unsigned char *cob_av[{max(n, 1)}];")
        for i, a in enumerate(s.args):
            if a.value == 'OMITTED':
                em(f"cob_av[{i}] = NULL;")
                sizes.append('0')
                omitted.append(i)
                continue
            v = a.value
            if a.mode == 'REFERENCE' and isinstance(v, DataRef):
                em(f"const cob_field *cob_cf{i} = {self.field(v)};")
                em(f"cob_av[{i}] = cob_cf{i}->data;")
                sizes.append(f"(int)cob_cf{i}->size")
            elif a.mode == 'VALUE' and isinstance(v, DataRef) and self.pointer_call(self.ref_item(v)):
                # a POINTER or PROGRAM-POINTER BY VALUE: the address itself
                em(f"unsigned char cob_vi{i}[8];")
                em(f"cob_put_value(8, cob_vi{i}, (cob_s64)(intptr_t)cob_pointer_get({self.field(v)}));")
                em(f"cob_av[{i}] = cob_vi{i};")
                sizes.append('8')
            elif a.mode == 'VALUE' and self.is_numeric(v):
                nbytes = getattr(a, 'size', None) or 4
                em(f"unsigned char cob_vi{i}[{nbytes}] = {{0}};")
                em(f"cob_put_value({nbytes}, cob_vi{i}, (cob_s64){self.int_expr(v)});")
                em(f"cob_av[{i}] = cob_vi{i};")
                sizes.append(str(nbytes))
            elif isinstance(v, NumLit) and v.float_text is None and a.mode in ('REFERENCE', 'CONTENT'):
                # a numeric literal goes as a native binary integer of its
                # digits (scale dropped), 4 bytes when it fits and 8 otherwise,
                # as GnuCOBOL and Micro Focus pass one: what a C function
                # taking an int * expects
                val = int(v.digits or '0') * (-1 if v.neg else 1)
                ctype, nb = ('int32_t', 4) if -2**31 <= val < 2**31 else ('int64_t', 8)
                em(f"{ctype} cob_li{i} = {val}{'LL' if nb == 8 else ''};")
                em(f"cob_av[{i}] = (unsigned char *)&cob_li{i};")
                sizes.append(str(nb))
            elif isinstance(v, LengthOf) and a.mode in ('REFERENCE', 'CONTENT'):
                # LENGTH OF goes the same way, as a native int
                em(f"int32_t cob_li{i} = (int32_t)({self.int_expr(v)});")
                em(f"cob_av[{i}] = (unsigned char *)&cob_li{i};")
                sizes.append('4')
            else:
                f = self.field(v)
                em(f"const cob_field *cob_cf{i} = {f};")
                em(f"unsigned char *cob_cb{i} = cob_malloc(cob_cf{i}->size + 1);")
                em(f"memcpy(cob_cb{i}, cob_cf{i}->data, cob_cf{i}->size);")
                em(f"cob_av[{i}] = cob_cb{i};")
                frees.append(f"free(cob_cb{i});")
                sizes.append(f"(int)cob_cf{i}->size")
        if isinstance(s.prog, StrLit):
            name = s.prog.value.decode('latin-1').strip()
            if name.upper() == 'SYSTEM':
                if not s.args:
                    raise CompileError("CALL 'SYSTEM' requires an argument", s.loc)
                em(f"cob_call_system({self.field(s.args[0].value)});")
                self.dbg_flush()
                if s.not_on_exc:
                    self.block(s.not_on_exc)
                em.ind -= 1
                em("}")
                return
            sym = self.find_program(name)
            dynamic = not sym
            fn = sym
            if sym == 'NULL':
                fn = "(cob_prog_fn)NULL"
            if dynamic:
                # not in this compile: another object, a module, or C; with
                # -fstatic-call it must be linked in, so the link fails without it
                ref = self.static_symbol(name) if getattr(self.opts, 'static_call', False) \
                    else self.weak_symbol(name)
                em(f"cob_callee cob_ce = cob_lookup_name({c_string(name)}, {ref});")
        else:
            it = None
            try:
                it = self.resolve(s.prog)
            except Exception:
                it = None
            dynamic = True
            if self.pointer_call(it):
                # CALL of a PROGRAM-POINTER item invokes the address it holds,
                # with the C convention: a program's pointer is its C entry
                em(f"cob_callee cob_ce = {{ NULL, (void *)cob_pointer_get({self.field(s.prog)}) }};")
            else:
                em(f"cob_callee cob_ce = cob_lookup({self.field(s.prog)});")
        if dynamic:
            em("if (!cob_ce.fn && !cob_ce.cfn) {")
        else:
            em(f"cob_prog_fn cob_fn = {fn};")
            em("if (!cob_fn) {")
        em(f"\tcob_exc_where(&{self.loc_sym(s)});")
        em("\tcob_set_exception(\"EC-PROGRAM-NOT-FOUND\");")
        if s.on_exc is not None:
            self.block(s.on_exc)
        else:
            if isinstance(s.prog, StrLit):
                em(f"\tcob_call_not_found({self.locstr()}, {c_string(s.prog.value)});")
            elif self.pointer_call(it):
                em(f"\tcob_fatal(\"%s: CALL of a NULL program pointer\", {self.locstr()});")
            else:
                em(f"\tcob_call_not_found_field({self.locstr()}, {self.field(s.prog)});")
        em("} else {")
        em.ind += 1
        em("cob_call_rejected = 0;")
        keep_rc = getattr(s, 'returning_omitted', False) or s.returning is not None
        if keep_rc:
            # RETURNING item / NOTHING: the callee's result goes to the item (or
            # nowhere), and the caller's RETURN-CODE stays as it was
            em("cob_s64 cob_rc_kept = cob_get_int(&cob_return_code);")
        if sizes:
            em(f"cob_call_sizes = (const int[]){{{', '.join(sizes)}}};")
        em("cob_call_arg_omitted = NULL;")
        if omitted:
            flags = ', '.join('1' if k in omitted else '0' for k in range(n))
            em(f"cob_call_arg_omitted = (const unsigned char[]){{{flags}}};")
        if dynamic:
            # a C function gets each BY VALUE number as the value itself
            modes = []
            for a in s.args:
                if a.value != 'OMITTED' and a.mode == 'VALUE' and isinstance(a.value, DataRef) \
                        and self.pointer_call(self.ref_item(a.value)):
                    modes.append('8')
                elif a.value != 'OMITTED' and a.mode == 'VALUE' and self.is_numeric(a.value):
                    nb = getattr(a, 'size', None) or 4
                    modes.append(str(-nb if getattr(a, 'unsigned', False) else nb))
                else:
                    modes.append('0')
            if any(m != '0' for m in modes):
                em(f"cob_call_modes = (const signed char[]){{{', '.join(modes)}}};")
            else:
                em("cob_call_modes = NULL;")
            em(f"cob_call_site = &{self.call_site(s)};")
            em(f"cob_s64 cob_rc64 = cob_ce.fn ? (cob_s64)cob_ce.fn({n}, cob_av) : cob_call_c(cob_ce.cfn, {n}, cob_av);")
            em("int cob_rc = (int)cob_rc64;")
        else:
            em(f"cob_call_site = &{self.call_site(s)};")
            em(f"int cob_rc = cob_fn({n}, cob_av);")
        em("cob_call_site = NULL;")
        em("if (cob_call_rejected) {")
        em.ind += 1
        em(f"cob_exc_where(&{self.loc_sym(s)});")
        em("cob_set_exception(\"EC-PROGRAM-RECURSIVE-CALL\");")
        if s.on_exc is not None:
            self.stmts(s.on_exc)
        else:
            em(f"cob_fatal(\"%s: recursive CALL of an active program that is not RECURSIVE\", {self.locstr()});")
        em.ind -= 1
        em("} else {")
        em.ind += 1
        em(f"cob_set_collating({self.ctx.coll or 'NULL'});")
        rit = None
        if s.returning is not None:
            try:
                rit = self.resolve(s.returning)
            except CompileError:
                rit = None
        if keep_rc:
            em("cob_set_int(&cob_return_code, cob_rc_kept);")
        if rit is not None and getattr(rit, 'type', None) == T_POINTER:
            # a C function that returns an address
            em(f"cob_pointer_set({self.field(s.returning)}, (void *)(intptr_t)"
               f"{'cob_rc64' if dynamic else 'cob_rc'});")
        elif s.returning is not None:
            em(f"cob_set_int({self.field(s.returning)}, cob_rc);")
        elif not keep_rc:
            em("cob_set_int(&cob_return_code, cob_rc);")
        for fr in frees:
            em(fr)
        self.dbg_flush()
        if s.not_on_exc is not None:
            self.stmts(s.not_on_exc)
        em.ind -= 1
        em("}")
        em.ind -= 1
        em("}")
        em.ind -= 1
        em("}")

    def ref_item(self, ref):
        try:
            return self.resolve(ref)
        except CompileError:
            return None

    def weak_symbol(self, name):
        """A weak reference to the C function a CALL literal may name: the
        address when one is linked in, NULL otherwise."""
        cname = c_identifier(name)
        if cname is None:
            return 'NULL'
        if not hasattr(self, 'weak_syms'):
            self.weak_syms = {}
        sym = self.weak_syms.get(cname)
        if sym is None:
            sym = self.sym('cob_weak_')
            self.protos.append(f'extern void {sym}(void) COB_ASM_NAME("{cname}") __attribute__((weak));')
            self.weak_syms[cname] = sym
        return f"(void *){sym}"

    def static_symbol(self, name):
        """-fstatic-call: a reference to the C function a CALL literal names,
        which the link must find (in an object file, a library, or C code
        linked in), as cobc's static calls need it to; a name that is no C
        identifier stays a run-time lookup."""
        cname = c_identifier(name)
        if cname is None:
            return self.weak_symbol(name)
        if not hasattr(self, 'static_syms'):
            self.static_syms = {}
        sym = self.static_syms.get(cname)
        if sym is None:
            sym = self.sym('cob_static_')
            self.protos.append(f'extern void {sym}(void) COB_ASM_NAME("{cname}");')
            self.static_syms[cname] = sym
        return f"(void *){sym}"

    def call_system_routine(self, s, name):
        """CALL of a library routine (CBL_AND, C$JUSTIFY, ...): a direct call
        with the arguments as data items."""
        em = self.em
        lo, hi = SYSTEM_ROUTINES[name]
        n = len(s.args)
        if n < lo:
            raise CompileError(f"wrong number of CALL parameters for '{name}', {n} given, {lo} expected", s.loc)
        if n > hi:
            DIAG.warn(f"wrong number of CALL parameters for '{name}', {n} given, {hi} expected", s.loc,
                      'call-params')
        em("{")
        em.ind += 1
        em(f"cob_field *cob_sa[{max(n, 1)}];")
        for i, a in enumerate(s.args):
            v = a.value
            if v == 'OMITTED':
                em(f"cob_sa[{i}] = &cob_fig_space;")
            elif a.mode == 'REFERENCE' and isinstance(v, DataRef):
                em(f"cob_sa[{i}] = {self.field(v)};")
            elif a.mode == 'VALUE' and self.is_numeric(v):
                em(f"cob_sa[{i}] = cob_dec_field({self.dec(v)});")
            else:
                f = self.field(v)
                em(f"{{ const cob_field *cob_cf = {f}; cob_sa[{i}] = cob_tmp_field(cob_cf->size, cob_cf->attr); "
                   f"memcpy(cob_sa[{i}]->data, cob_cf->data, cob_cf->size); }}")
        fn = 'cob_sys_' + SYSTEM_ROUTINES_ALIAS.get(name, name).lower().replace('$', '_')
        em(f"int cob_rc = {fn}({n}, cob_sa);")
        if s.returning is not None:
            em(f"cob_set_int({self.field(s.returning)}, cob_rc);")
        else:
            em("cob_set_int(&cob_return_code, cob_rc);")
        self.dbg_flush()
        if s.not_on_exc is not None:
            self.stmts(s.not_on_exc)
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
                  on_ok=None, eop=None, not_eop=None, flush=True):
        em = self.em
        em("{")
        em.ind += 1
        if fi.external:
            for line in self.file_bindings(fi):
                em(line)
        em(f"int cob_io = {call};")
        if getattr(self, 'cur_stmt', None) is not None:
            em(f"if (cob_io != COB_IO_OK) cob_exc_where(&{self.loc_sym(self.cur_stmt)});")
        if on_ok or (self.dbg_pending and self.dbg_pending['read']):
            em("if (cob_io == COB_IO_OK) {")
            em.ind += 1
            for line in on_ok or []:
                em(line)
            self.dbg_flush('read')
            em.ind -= 1
            em("}")
        if flush:
            self.dbg_flush()
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
            self.dbg_emit_cause('USE')
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
                self.dbg_emit_cause('USE')
                self.perform_section(sec)
            else:
                em(f"cob_decl_which = {sec.id};")
                em(f"{self.prog_syms[id(owner)]}(COB_DECL_ENTRY, NULL);")
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

    def perform_section(self, sec, what='USE'):
        em = self.em
        ret = self.new_label('R')
        self.frame_push(sec, f"{what} section {sec.name}", ret)
        em(f"goto {sec.label};")
        em.label(ret)
        self.frame_pop()
        if getattr(self, 'seg_tracking', False) and self.cur_section is not None:
            em(f"cob_seg = {self.cur_section.segment};")

    def g_Open(self, s):
        for mode, files in s.modes:
            for fn in files:
                fi = self.file_info(fn, s.loc)
                if fi.is_sort:
                    raise CompileError(f"cannot OPEN sort file '{fn}'", s.loc)
                # BASED storage named in ASSIGN is allocated (or not) by now
                for sym, expr in self.dyn_fields:
                    self.em(f"{sym}.data = {expr};")
                # OPEN ... WITH LOCK / SHARING: for this OPEN only
                lock = fn in s.locked
                share = s.sharing.get(fn)
                if lock or share is not None:
                    self.em("{")
                    self.em.ind += 1
                    self.em(f"int cob_sh = {fi.sym}.sharing;")
                    if lock:
                        self.em(f"{fi.sym}.open_lock = 1;")
                    if share is not None:
                        self.em(f"{fi.sym}.sharing = {share};")
                self.io_result(fi, f"cob_open(&{fi.sym}, {OPEN_MODE[mode]})", flush=False)
                if lock or share is not None:
                    self.em(f"{fi.sym}.open_lock = 0;")
                    self.em(f"{fi.sym}.sharing = cob_sh;")
                    self.em.ind -= 1
                    self.em("}")

    def g_Close(self, s):
        for i, fn in enumerate(s.files):
            fi = self.file_info(fn, s.loc)
            opt = s.opts[i] if i < len(s.opts) else 0
            self.io_result(fi, f"cob_close_opt(&{fi.sym}, {opt})", flush=False)

    def file_record(self, s):
        """WRITE/REWRITE FILE file-name: the file's (first) record."""
        fname = getattr(s, 'file_name', None)
        if fname is not None and s.record.item is None:
            fi = self.file_info(fname, s.loc)
            if not fi.fd.records:
                raise CompileError(f"file '{fname}' has no record description", s.loc)
            s.record.item = fi.fd.records[0]
        return self.record_of(s.record)

    def record_of(self, ref):
        it = self.resolve(ref)
        fi = getattr(it, 'file', None)
        if fi is None or it.level != 1:
            raise CompileError(f"'{ref.name}' is not a record of a file", ref.loc)
        return it, fi

    def key_index(self, fi, ref):
        # a key-name need not be a data item: "START ... KEY IS PRIME-KEY"
        # names the key declared in SELECT
        # only for a key whose name is NOT a data item (a split key's name)
        named = getattr(fi, 'key_names', {})
        if ref.name in named and getattr(ref, 'item', None) is None:
            try:
                self.resolve(ref)
            except Exception:
                return named[ref.name]
        it = self.resolve(ref)
        for i, (k, _d, _s2, _sp) in enumerate(fi.keys):
            if k is it:
                return i, k.size
        for i, (k, _d, _s2, _sp) in enumerate(fi.keys):
            if getattr(it, 'file', None) is fi and it.offset == k.offset and it.size <= k.size:
                return i, it.size
        raise CompileError(f"'{ref.name}' is not a key of file '{fi.fc.name}'", ref.loc)

    def g_Read(self, s):
        fi = self.file_info(s.file, s.loc)
        next_ = 1 if s.direction == 'NEXT' or fi.fc.access == 'SEQUENTIAL' else 0
        if fi.fc.organization == 'LINE SEQUENTIAL' or fi.fc.organization == 'SEQUENTIAL':
            if s.direction == 'PREVIOUS':
                raise CompileError("READ PREVIOUS requires a relative or indexed file", s.loc)
            next_ = 1
        elif s.direction == 'PREVIOUS':
            next_ = 2
        kidx = -1
        if s.key is not None:
            kidx, _ = self.key_index(fi, s.key)
        on_ok = []
        if s.into is not None:
            self.check_receiving(s.into)
            on_ok.append(f"cob_move(CF({fi.buf}, {self.cur_rec_size(fi)}, &cob_attr_group), {self.into_field(s.into)});")
        call = (f"cob_read_lock(&{fi.sym}, {next_}, {kidx}, {s.lock})" if getattr(s, 'lock', 0)
                else f"cob_read(&{fi.sym}, {next_}, {kidx})")
        self.io_result(fi, call, s.at_end, s.not_at_end, s.invalid,
                       s.not_invalid, on_ok)

    def g_Write(self, s):
        em = self.em
        rec, fi = self.file_record(s)
        if fi.is_sort:
            raise CompileError("use RELEASE for sort files", s.loc)
        if s.frm is not None:
            em(f"cob_move({self.field(s.frm)}, {self.field(s.record)});")
        self.dbg_flush('before')
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
        rec, fi = self.file_record(s)
        if s.frm is not None:
            em(f"cob_move({self.field(s.frm)}, {self.field(s.record)});")
        self.dbg_flush('before')
        self.io_result(fi, f"cob_rewrite(&{fi.sym}, {self.size_expr(rec)})", None, None, s.invalid, s.not_invalid)

    def g_Delete(self, s):
        fi = self.file_info(s.file, s.loc)
        self.io_result(fi, f"cob_delete(&{fi.sym})", None, None, s.invalid, s.not_invalid)

    def g_DeleteFile(self, s):
        for fn in s.files:
            fi = self.file_info(fn, s.loc)
            if fi.is_sort:
                raise CompileError(f"cannot DELETE FILE sort file '{fn}'", s.loc)
            self.io_result(fi, f"cob_delete_file(&{fi.sym})", flush=False)

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
            if k.ref is None:
                if base_item is None:
                    raise CompileError("SORT key name expected", loc)
                parts.append(f"{{0, {base_item.size}, &{self.attr(T_ALNUM)}, {1 if k.descending else 0}}}")
                continue
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
                    if nm == tbl.name:
                        keys.append(SortKey(desc, None))    # KEY is the element itself
                        continue
                    r = DataRef(nm, [tbl.name] if tbl.name else [], [], None, s.loc)
                    found = [x for x in tbl.walk() if x.name == nm]
                    if len(found) == 1:
                        r.item = found[0]           # the key within this table
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
            coll = None
            if getattr(s, 'collating', None):
                res = self.collating_table(self.prog, s.collating, s.loc)
                coll = res[0] if res else 'NULL'
            if coll is not None:
                em(f"{{ const unsigned short *cob_sv = cob_get_collating(); cob_set_collating({coll});")
            em(f"cob_table_sort({self.data_ptr(r2)}, (size_t)({n}), {tbl.size}, {nk}, {arr});")
            if coll is not None:
                em("cob_set_collating(cob_sv); }")
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
            self.perform_call(*s.input_proc, cause='SORT_IN')
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
            self.perform_call(*s.output_proc, cause='MERGE_OUT' if s.merge else 'SORT_OUT')
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
            em("if (cob_io == COB_IO_OK) {")
            em(f"\tcob_move(CF({fi.buf}, {fi.size}, &cob_attr_group), {self.into_field(s.into)});")
            self.dbg_flush('read')
            em("}")
        self.dbg_flush()
        em("if (cob_io != COB_IO_OK) {")
        self.block(s.at_end or [])
        if s.not_at_end is not None:
            em("} else {")
            self.block(s.not_at_end)
        em("}")
        em.ind -= 1
        em("}")
