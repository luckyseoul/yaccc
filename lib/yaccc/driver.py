# SPDX-License-Identifier: MIT
"""Command-line driver: parse, generate C, invoke the C compiler."""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from . import dialect
from .codegen import CodeGen, Options
from . import errors
from .errors import CompileError, DIAG, ErrorsReported
from .lexer import SourceSet
from .parser import Parser

HERE = os.path.dirname(os.path.abspath(__file__))        # .../lib/yaccc
PKG_ROOT = os.path.dirname(os.path.dirname(HERE))       # the project root
RUNTIME_DIR = os.path.join(PKG_ROOT, 'runtime')
RUNTIME_SRC = ['cobrt_core.c', 'cobrt_str.c', 'cobrt_fn.c', 'cobrt_math.c', 'cobrt_dt.c',
               'cobrt_sys.c', 'cobrt_io.c', 'cobrt_rw.c', 'cobrt_json.c', 'cobrt_xml.c',
               'cobrt_call.c', 'cobrt_scr.c', 'cobrt_xmlp.c', 'cobrt_sql.c', 'cobrt_dump.c', 'cobrt_conf.c',
               'cobrt_prof.c']
VERSION = '1.0'


def runtime_lib_dir():
    """runtime/ next to the sources, or a per-user cache when that is read-only."""
    if os.access(RUNTIME_DIR, os.W_OK):
        return RUNTIME_DIR
    cache = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    d = os.path.join(cache, 'yaccc')
    os.makedirs(d, exist_ok=True)
    return d


def build_runtime(cc, verbose=False, force=False):
    libdir = runtime_lib_dir()
    lib = os.path.join(libdir, 'libcobrt.a')
    srcs = [os.path.join(RUNTIME_DIR, s) for s in RUNTIME_SRC] + [os.path.join(RUNTIME_DIR, 'cobrt.h')]
    if not force and os.path.exists(lib):
        lt = os.path.getmtime(lib)
        if all(os.path.getmtime(s) <= lt for s in srcs):
            return lib
    objdir = tempfile.mkdtemp(prefix='cobrt_')
    objs = []
    try:
        for s in RUNTIME_SRC:
            o = os.path.join(objdir, s[:-2] + '.o')
            cmd = [cc, '-O2', '-std=gnu11', '-fPIC', '-c', os.path.join(RUNTIME_DIR, s), '-o', o]
            if verbose:
                print(' '.join(cmd), file=sys.stderr)
            subprocess.run(cmd, check=True)
            objs.append(o)
        # unique temporary name + atomic rename: concurrent builds never see a partial archive
        fd, tmp = tempfile.mkstemp(dir=libdir, prefix='libcobrt.', suffix='.tmp')
        os.close(fd)
        os.remove(tmp)
        try:
            subprocess.run(['ar', 'rcs', tmp] + objs, check=True)
            os.replace(tmp, lib)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(objdir, ignore_errors=True)
    return lib


def build_runner(cc, verbose=False):
    """yacccrun, the program that runs a module's program (cobcrun's job):
    built beside the runtime library, again whenever that is newer."""
    lib = build_runtime(cc, verbose)
    runner = os.path.join(os.path.dirname(lib), 'yacccrun')
    src = os.path.join(RUNTIME_DIR, 'yacccrun.c')
    if os.path.exists(runner) and os.path.getmtime(runner) >= max(os.path.getmtime(lib),
                                                                  os.path.getmtime(src)):
        return runner
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(lib), prefix='yacccrun.', suffix='.tmp')
    os.close(fd)
    try:
        cmd = [cc, '-O2', '-std=gnu11', '-I', RUNTIME_DIR, src, '-o', tmp] + runtime_link_args(lib) \
            + ['-lm', '-ldl']
        if verbose:
            print(' '.join(cmd), file=sys.stderr)
        subprocess.run(cmd, check=True)
        os.replace(tmp, runner)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return runner


def show_info(cc):
    """-i / -info: how this YACCC is set up, as cobc -info shows its own."""
    import platform
    print(f"YACCC {VERSION}")
    print(f"  compiler     {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
    print(f"  runtime      {RUNTIME_DIR} (library in {runtime_lib_dir()})")
    try:
        first = subprocess.run([cc, '--version'], capture_output=True, text=True).stdout.splitlines()
        print(f"  C compiler   {cc}: {first[0] if first else '?'}")
    except OSError:
        print(f"  C compiler   {cc}: not found")
    print(f"  Python       {platform.python_version()} on {platform.system()} {platform.machine()}")
    print(f"  modules      {MODULE_EXT}")
    print("  environment")
    for name in ('COBCPY', 'COB_LIBRARY_PATH', 'COB_PRE_LOAD', 'COB_FILE_PATH', 'COB_RUNTIME_CONFIG',
                 'COB_CONFIG_DIR', 'COB_VARSEQ_FORMAT', 'COB_LS_FIXED', 'COB_LS_NULLS', 'COB_LS_SPLIT',
                 'COB_SYNC', 'COB_STACKTRACE', 'COB_DUMP_FILE', 'COB_SET_TRACE', 'COB_TRACE_FILE',
                 'COB_CURRENT_DATE', 'CC'):
        v = os.environ.get(name)
        print(f"    {name:<20} {v if v is not None else '(not set)'}")
    return 0


def run_module(argv):
    """yacccrun [-c FILE] PROGRAM|PATH [ARGUMENT...]: run a program from a
    module yaccc -m built, as cobcrun does."""
    usage = ("usage: yacccrun [-c FILE] PROGRAM [ARGUMENT...]\n"
             "  run PROGRAM from the module PROGRAM.so (found in COB_LIBRARY_PATH, then the\n"
             "  current directory; a path to the module names its directory too), as a\n"
             "  main program with the ARGUMENTs as its command line\n"
             "  -c FILE, --config=FILE   runtime configuration (as COB_RUNTIME_CONFIG)")
    args = list(argv)
    env = dict(os.environ)
    while args and args[0].startswith('-'):
        a = args.pop(0)
        if a in ('-h', '--help'):
            print(usage)
            return 0
        if a in ('-V', '--version'):
            print(f'yacccrun (YACCC {VERSION})')
            return 0
        if a == '-c' and args:
            env['COB_RUNTIME_CONFIG'] = args.pop(0)
        elif a.startswith('--config='):
            env['COB_RUNTIME_CONFIG'] = a.split('=', 1)[1]
        elif a == '--':
            break
        else:
            print(f"yacccrun: unknown option '{a}'\n{usage}", file=sys.stderr)
            return 2
    if not args:
        print(usage, file=sys.stderr)
        return 2
    prog = args.pop(0)
    if '/' in prog or prog.endswith(MODULE_EXT):
        # a path: its directory goes first in COB_LIBRARY_PATH
        d = os.path.dirname(os.path.abspath(prog))
        prog = os.path.basename(prog)
        if prog.endswith(MODULE_EXT):
            prog = prog[:-len(MODULE_EXT)]
        env['COB_LIBRARY_PATH'] = d + (os.pathsep + env['COB_LIBRARY_PATH']
                                       if env.get('COB_LIBRARY_PATH') else '')
    cc = os.environ.get('CC') or (shutil.which('gcc') and 'gcc') or 'cc'
    try:
        runner = build_runner(cc)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"yacccrun: building the runner failed: {e}", file=sys.stderr)
        return 1
    os.execve(runner, [runner, prog] + args, env)


def safe_build_runtime(cc, verbose=False, force=False):
    try:
        return build_runtime(cc, verbose, force)
    except FileNotFoundError as e:
        print(f"yaccc: cannot run '{e.filename or cc}': install gcc or clang, or name one with --cc",
              file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"yaccc: building the runtime library failed: {' '.join(e.cmd)}", file=sys.stderr)
    return None


# the C compiler's flags for the generated code: no warnings (it is not the
# user's to fix), wrapping integer arithmetic, and no _FORTIFY_SOURCE, which
# distributions turn on by default: the range checks in COBOL are the
# runtime's own (on unless --no-check or -fno-ec), and with them off a
# subscript past a table's end must reach the storage after it, as with
# cobc, not abort the program with "buffer overflow detected"
GENERATED_C_FLAGS = ['-w', '-fwrapv', '-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=0']

# the -fec names that select the checks YACCC compiles in or out, and the
# kinds of check each one is
_RANGE = frozenset({'subscript', 'ref-mod', 'odo'})
_ALL_CHECKS = _RANGE | {'data'}
EC_RANGE = {'ALL': _ALL_CHECKS, 'EC-ALL': _ALL_CHECKS, 'EC-BOUND': _RANGE,
            'EC-BOUND-SUBSCRIPT': frozenset({'subscript'}), 'EC-BOUND-REF-MOD': frozenset({'ref-mod'}),
            'EC-BOUND-ODO': frozenset({'odo'}),
            'EC-DATA': frozenset({'data'}), 'EC-DATA-INCOMPATIBLE': frozenset({'data'})}
# the checks that are off until asked for
_OFF_BY_DEFAULT = frozenset({'data'})


def compile_sources(paths, opts, fmt, include_dirs, debugging=False, defines=None):
    programs = []
    opts.includes = []
    opts.programs = programs
    opts.codegen = None
    for p in paths:
        ss = SourceSet(include_dirs=include_dirs, fmt=fmt, debugging=debugging, defines=defines)
        ss.includes = opts.includes
        if getattr(opts, 'binary_comp1', False):
            ss.directives.comp1_binary = True   # until a $SET COMP-1 says otherwise
        toks = ss.load(p)
        parser = Parser(toks, ss.directives.vars)
        parser.bare_intrinsics = set(getattr(opts, 'bare_intrinsics', ()))
        parser.not_intrinsic = set(getattr(opts, 'not_intrinsic', ()))
        parser.dialect = opts.dialect
        parser.directives_state = ss.directives
        opts.directives = ss.directives
        parser.missing_period = getattr(opts, 'missing_period', False)
        parser.relax_syntax = getattr(opts, 'relax_syntax', False)
        parser.implicit_assign = getattr(opts, 'implicit_assign', True)
        if getattr(ss, 'dpc_in_data', None) and opts.dpc_in_data == 'none':
            opts.dpc_in_data = ss.dpc_in_data
        if ss.directives.odoslide is not None and not getattr(opts, 'odoslide_set', False):
            # $SET ODOSLIDE / NOODOSLIDE in the source, unless the command line says
            opts.odoslide = ss.directives.odoslide
        programs.extend(parser.parse_unit())
        DIAG.check()
    opts.source_name = paths[0]
    opts.debugging = debugging
    gen = CodeGen(programs, opts)
    opts.codegen = gen
    return gen.generate(), programs


def _literal_text(b):
    """A literal's bytes as COBOL source: quoted when printable, hex otherwise."""
    if all(32 <= c < 127 or c >= 160 for c in b):
        return '"' + b.decode('latin-1').replace('"', '""') + '"'
    return 'X"' + b.hex().upper() + '"'


def preprocess_sources(paths, fmt, include_dirs, debugging=False, defines=None):
    """The token stream the parser sees, written back as free-format source:
    copybooks expanded, REPLACE and REPLACING applied, directives evaluated.
    Each source line keeps its own line, and a comment marks where the text
    comes from whenever the file changes."""
    out = ['       >>SOURCE FORMAT FREE']
    for p in paths:
        ss = SourceSet(include_dirs=include_dirs, fmt=fmt, debugging=debugging, defines=defines)
        toks = ss.load(p)
        cur = None
        line = []
        comma = False           # DECIMAL-POINT IS COMMA: numbers go back out with ','
        for i, t in enumerate(toks):
            if t.kind == 'EOF':
                break
            if t.kind == 'WORD' and t.up == 'DECIMAL-POINT' and \
                    any(u.kind == 'WORD' and u.up == 'COMMA' for u in toks[i + 1:i + 3]):
                comma = True
            key = (t.loc.file, t.loc.line)
            if key != cur:
                if line:
                    out.append(_join(line))
                    line = []
                if cur is None or key[0] != cur[0]:
                    out.append(f"*> {key[0]}:{key[1]}")
                cur = key
            if t.kind == 'STR':
                text = _literal_text(t.val)
            elif t.kind == 'EXECSQL':
                text = f"EXEC SQL {t.val} END-EXEC"
            elif t.kind == 'NUM' and comma:
                text = str(t.val).replace('.', ',')
            else:
                text = str(t.val)
            line.append((t.kind, text))
        if line:
            out.append(_join(line))
    return '\n'.join(out) + '\n'


def _join(parts):
    s = ''
    for i, (kind, text) in enumerate(parts):
        if i and not (kind in ('.', ')', ',') or parts[i - 1][0] == '('):
            s += ' '
        s += text
    return s


def report(e):
    """Print the diagnostics after a compile error; the exit status."""
    if not isinstance(e, ErrorsReported):
        DIAG.items.append(('error', e))
        DIAG.nerrors += 1
    DIAG.flush()
    return 1


def write_listing(cobol, opts):
    """-t / -T / -Xref: the listing, whether the compile worked or not."""
    path = getattr(opts, 'listing', None)
    if not path and getattr(opts, 'xref', False):
        path = os.path.splitext(os.path.basename(cobol[0]))[0] + '.lst'
    if not path:
        return
    from .listing import Listing
    gen = getattr(opts, 'codegen', None) if getattr(opts, 'xref', False) else None
    try:
        Listing(cobol, getattr(opts, 'includes', []), list(DIAG.items),
                getattr(opts, 'programs', []), gen, VERSION).write(path)
    except OSError as e:
        print(f"yaccc: cannot write the listing {path}: {e.strerror}", file=sys.stderr)


def translate(cobol, opts, fmt, args, defines):
    """COBOL sources to one C translation unit: (status, C text)."""
    try:
        csrc, _ = compile_sources(cobol, opts, fmt, args.include, args.debugging_mode, defines)
    except CompileError as e:
        if not isinstance(e, ErrorsReported):
            DIAG.items.append(('error', e))
            DIAG.nerrors += 1
        write_listing(cobol, opts)
        DIAG.flush()
        return 1, None
    except Exception as e:     # a bug in the compiler, not in the program
        DIAG.flush()
        where = f"{errors.WHERE}: " if errors.WHERE else ''
        print(f"{where}internal compiler error: {type(e).__name__}: {e}", file=sys.stderr)
        if os.environ.get('YACCC_TRACEBACK'):
            import traceback
            traceback.print_exc()
        else:
            print("yaccc: this is a bug in yaccc, not in your program; "
                  "YACCC_TRACEBACK=1 shows where it happened", file=sys.stderr)
        return 3, None
    write_listing(cobol, opts)
    DIAG.flush()
    return 0, csrc


def build_parts(args, opts, fmt, defines, cobol, csrcs):
    """-c and -m: each source on its own, to an object file or a module
    whose programs C code and CALL by name can reach."""
    opts.export_c = True
    opts.emit_main = bool(args.compile_only and args.x)
    ext = '.o' if args.compile_only else MODULE_EXT
    flags = ['-c'] if args.compile_only else module_link_args()
    for src in cobol + csrcs:
        base = os.path.splitext(os.path.basename(src))[0]
        out = args.output or base + ext
        tmpdir = tempfile.mkdtemp(prefix='yaccc_')
        try:
            if src in csrcs:
                cmd = ([args.cc, '-std=gnu11', f'-O{args.opt}', '-fPIC', '-I', RUNTIME_DIR] + cc_options(args)
                       + flags + [src, '-o', out] + ([] if args.compile_only else ld_options(args)))
            else:
                DIAG.items.clear()
                DIAG.nerrors = 0
                rc, csrc = translate([src], opts, fmt, args, defines)
                if rc:
                    return rc
                if args.syntax_only:
                    continue
                cpath = kept_c_path(args, out, base) or os.path.join(tmpdir, base + '.c')
                with open(cpath, 'w', encoding='latin-1') as f:
                    f.write(csrc)
                cmd = ([args.cc, '-std=gnu11', f'-O{args.opt}'] + GENERATED_C_FLAGS + ['-fPIC', '-I', RUNTIME_DIR]
                       + cc_options(args) + flags + [cpath, '-o', out]
                       + ([] if args.compile_only else ld_options(args)))
            if args.debug:
                cmd.insert(1, '-g')
            if not run_cc(cmd, args.verbose, f"C compilation of {src} failed"):
                return 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


def cc_options(args):
    """-A: options for the C compiler, each split as a shell would."""
    import shlex
    return [w for o in getattr(args, 'cc_opts', []) for w in shlex.split(o)]


def ld_options(args):
    """-Q: options for the link."""
    import shlex
    return [w for o in getattr(args, 'ld_opts', []) for w in shlex.split(o)]


def kept_c_path(args, out, base):
    """Where --keep-c or -save-temps keeps the generated C, or None."""
    if getattr(args, 'save_temps', None):
        d = args.save_temps
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, base + '.c')
    if args.keep_c:
        return os.path.splitext(out)[0] + '.c'
    return None


def _split_run_args(ap, args, unknown):
    """Arguments for the program being run, from the tokens argparse did not
    claim. A token that looks like an option is a mistake in the compiler's
    own command line, not a program argument: silently dropping "--no-chek"
    or "-std=ibm" built the program with the wrong configuration and said
    nothing, which is worse than refusing. Program arguments that begin with
    "-" go after "--"."""
    if not unknown:
        return []
    if '--' in unknown:
        cut = unknown.index('--')
        before, after = unknown[:cut], unknown[cut + 1:]
    else:
        before, after = unknown, []
    bad = [t for t in before if t.startswith('-') and t != '-']
    if bad:
        ap.error("unrecognized option%s: %s (program arguments that begin with '-' "
                 "go after '--')" % ("s" if len(bad) > 1 else "", ' '.join(bad)))
    if not args.run and (before or after):
        ap.error("unexpected argument%s: %s (needs --run)"
                 % ("s" if len(before) + len(after) > 1 else "", ' '.join(before + after)))
    if not args.run:
        return []
    return before + after


SOURCE_EXT = ('.cbl', '.cob', '.cpy', '.cbx', '.copy', '.cobol')
C_EXT = ('.c',)
LINK_EXT = ('.o', '.a', '.so', '.dylib')
MODULE_EXT = '.dylib' if sys.platform == 'darwin' else '.so'


def _looks_like_source(path):
    return path.lower().endswith(SOURCE_EXT + C_EXT + LINK_EXT)


def runtime_link_args(lib):
    """The whole runtime goes into an executable, with its symbols exported,
    so that a module loaded at run time (yaccc -m) finds every runtime
    function in the executable that loads it."""
    if sys.platform == 'darwin':
        return [f'-Wl,-force_load,{lib}', '-rdynamic']
    return ['-Wl,--whole-archive', lib, '-Wl,--no-whole-archive', '-rdynamic']


def module_link_args():
    if sys.platform == 'darwin':
        return ['-dynamiclib', '-undefined', 'dynamic_lookup']
    return ['-shared']


def run_cc(cmd, verbose, what):
    if verbose:
        print(' '.join(cmd), file=sys.stderr)
    try:
        r = subprocess.run(cmd)
    except FileNotFoundError:
        print(f"yaccc: cannot run '{cmd[0]}': install gcc or clang, or name one with --cc", file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"yaccc: {what}", file=sys.stderr)
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog='yaccc', description='COBOL compiler (COBOL -> C -> native executable)')
    ap.add_argument('sources', nargs='*', help='COBOL source files')
    ap.add_argument('-o', dest='output', help='output file name')
    ap.add_argument('-x', action='store_true', help='build an executable (default)')
    ap.add_argument('-C', dest='emit_c', action='store_true', help='translate only: write C source')
    ap.add_argument('-c', dest='compile_only', action='store_true',
                    help='compile each source to an object file (.o) and do not link; '
                         'with -x the object holds main()')
    ap.add_argument('-m', dest='module', action='store_true',
                    help=f'build each source as a loadable module ({MODULE_EXT}) that CALL finds '
                         'in COB_LIBRARY_PATH or the current directory')
    ap.add_argument('-ftrace', dest='trace', action='store_const', const=1, default=0,
                    help='trace program entry and exit, sections and paragraphs to standard '
                         'error while READY TRACE or COB_SET_TRACE=Y has it on')
    ap.add_argument('-ftraceall', dest='trace', action='store_const', const=2,
                    help='-ftrace, and every statement too')
    ap.add_argument('-fintrinsics', dest='intrinsics', metavar='ALL|NAME,...',
                    help='intrinsic functions that may be called without the FUNCTION keyword, '
                         'as REPOSITORY. FUNCTION ... INTRINSIC allows')
    ap.add_argument('-fsticky-linkage', dest='sticky_linkage', action='store_true',
                    help='a LINKAGE item keeps its address from one call to the next when '
                         'the caller passes no argument for it')
    ap.add_argument('-fentry-statement=ok', dest='entry_ok', action='store_true',
                    help='accept ENTRY (always accepted; for cobc command lines)')
    ap.add_argument('-fno-recursive-check', dest='recursive_check', action='store_false', default=True,
                    help='allow a CALL of an active program that is not RECURSIVE '
                         '(it shares its storage with the active call)')
    ap.add_argument('-fno-stack-trace', dest='stack_trace', action='store_false', default=True,
                    help="leave out the bookkeeping that lets a runtime error list the "
                         "PERFORMs that led to it (a little faster PERFORM)")
    ap.add_argument('-fstack-trace', dest='stack_trace', action='store_true',
                    help='list the PERFORMs and CALLs that led to a runtime error (the default)')
    # cobc's options that build scripts use, done the same way here
    ap.add_argument('-t', dest='listing', metavar='FILE',
                    help='write a listing of the compile to FILE: the source with its copybooks '
                         'and messages, and a data map')
    ap.add_argument('-T', dest='listing_wide', metavar='FILE',
                    help='the same as -t (the listing is never cut to a page width)')
    ap.add_argument('-Xref', dest='xref', action='store_true',
                    help='a cross-reference in the listing: where each data item, index and '
                         'procedure is used (with no -t, the listing is SOURCE.lst)')
    ap.add_argument('-A', dest='cc_opts', action='append', default=[], metavar='OPTIONS',
                    help='options for the C compiler (may be repeated)')
    ap.add_argument('-Q', dest='ld_opts', action='append', default=[], metavar='OPTIONS',
                    help='options for the link (may be repeated)')
    ap.add_argument('-save-temps', dest='save_temps', metavar='DIR',
                    help='keep the generated C, in DIR (-save-temps alone: the current directory)')
    ap.add_argument('-w', dest='no_warnings', action='store_true', help='no warnings')
    ap.add_argument('-W', dest='warnings', action='append', default=[], metavar='NAME',
                    help='-Wall, -Wextra, -W: every warning (the default); -Wno-NAME: not that '
                         'one; -Werror: warnings fail the compile')
    ap.add_argument('-d', '-debug', dest='debug_checks', action='store_true',
                    help='every run-time check: subscripts, reference modification, OCCURS '
                         'DEPENDING ON, numeric data (EC-DATA-INCOMPATIBLE), and the PERFORM '
                         'stack trace (overrides --no-check)')
    ap.add_argument('-fec', dest='ec_on', action='append', default=[], metavar='EC-NAME',
                    help='EC-ALL, EC-BOUND, EC-BOUND-SUBSCRIPT, EC-BOUND-REF-MOD or EC-BOUND-ODO: '
                         'those range checks on (they are, unless --no-check or -fno-ec); '
                         'EC-DATA-INCOMPATIBLE: numeric items checked for numbers where read')
    ap.add_argument('-fno-ec', dest='ec_off', action='append', default=[], metavar='EC-NAME',
                    help='the same names: those range checks off')
    ap.add_argument('-fstack-check', dest='stack_check', action='store_true',
                    help='PERFORM stack checking (always on)')
    ap.add_argument('-fsource-location', dest='source_location', action='store_true',
                    help='source locations in run-time errors (always on)')
    ap.add_argument('-ffold-copy', dest='fold_copy', type=str.upper, choices=['UPPER', 'LOWER'],
                    help="a copybook's name is looked for as written, in upper case and in lower "
                         "case, whichever this says")
    ap.add_argument('-fstatic-call', dest='static_call', action='store_true', default=False,
                    help='a CALL literal names a program or C function that is linked in: '
                         'the link fails without it, rather than the CALL')
    ap.add_argument('-fno-static-call', dest='static_call', action='store_false',
                    help='a CALL literal that is not in the compile is looked for when it runs '
                         '(the default)')
    ap.add_argument('-fsingle-quote', dest='single_quote', action='store_true',
                    help="QUOTE is an apostrophe (')")
    ap.add_argument('-fdefault-colseq', dest='default_colseq', type=str.upper,
                    choices=['ASCII', 'EBCDIC', 'NATIVE'],
                    help='the collating sequence of a program that names none')
    ap.add_argument('-fmfcomment', dest='mfcomment', action='store_true',
                    help="'*' or '/' in column 1 makes a fixed-format line a comment")
    ap.add_argument('-j', '-job', dest='job', nargs='?', const='', default=None, metavar='ARGS',
                    help='run the program after building it, with ARGS (one string, split as a '
                         'shell would) as its arguments: cobc\'s -j; --run takes them as words')
    ap.add_argument('-q', '-brief', dest='brief', action='store_true',
                    help='no display of the commands run (the default; -v shows them)')
    ap.add_argument('-i', '-info', dest='info', action='store_true',
                    help='show how YACCC is set up: its version, C compiler, runtime and the '
                         'environment variables it reads, then exit')
    ap.add_argument('-P', dest='plisting', nargs='?', const='', default=None, metavar='DIR|FILE',
                    help='write the listing (as -t) to FILE, or SOURCE.lst in DIR or here')
    ap.add_argument('-ftsymbols', dest='tsymbols', action='store_true',
                    help='the data map in the listing (it always has one)')
    ap.add_argument('-ftext-column', dest='text_column', type=int, metavar='72..255',
                    help='the right margin of fixed-format source: the program text is columns '
                         '8 to this one (72 by default)')
    ap.add_argument('-fmax-errors', dest='max_errors', type=int, metavar='N',
                    help='the errors a compile reports before it stops (20 by default)')
    ap.add_argument('-fdump', dest='dump', metavar='ALL|WS,LO,LS,FD',
                    help='after a runtime error or a crash, write out the data of the '
                         'program: ALL (also -fdump alone), or WORKING-STORAGE (WS), '
                         'LOCAL-STORAGE (LO), LINKAGE (LS) and the files\' records (FD)')
    ap.add_argument('-fno-dump', dest='no_dump', metavar='ALL|WS,LO,LS,FD',
                    help='leave these out of the -fdump dump (all of it with no value)')
    ap.add_argument('-fimplicit-assign-dynamic-var', dest='implicit_assign', action='store_true',
                    default=True,
                    help='ASSIGN word, a word no data item has: a PIC X item holding it, which '
                         'the program can MOVE another name into (the default)')
    ap.add_argument('-fno-implicit-assign-dynamic-var', dest='implicit_assign', action='store_false',
                    help='... or the file\'s external name, IBM label parts dropped')
    ap.add_argument('-fno-program-name-redefinition', '-fprogram-name-redefinition',
                    dest='accepted_cobc', action='append_const', const=True,
                    help='accepted: CALL and CANCEL of a name that no data item has but a '
                         'program, or a REPOSITORY prototype, does name that program')
    ap.add_argument('-fassign-ext-dyn=ok', dest='accepted_cobc', action='append_const', const=True,
                    help='accepted: ASSIGN EXTERNAL and ASSIGN DYNAMIC are always allowed')
    ap.add_argument('-fdefaultbyte', dest='defaultbyte', metavar='init|CHAR|0-255',
                    help='what WORKING-STORAGE without a VALUE clause starts as: init (spaces '
                         'and zeros by type, the default), one character, or a byte value')
    ap.add_argument('-fnot-intrinsic', dest='not_intrinsic', metavar='NAME,...',
                    help='intrinsic function names a FUNCTION-ID of the same name replaces')
    ap.add_argument('-fnot-reserved', dest='not_reserved', metavar='WORD,...', action='append',
                    default=[], help='reserved words the program may use as names of its own')
    ap.add_argument('-freserved', dest='reserved', metavar='WORD,...', action='append',
                    default=[], help='words to reserve besides the standard ones')
    ap.add_argument('-fsign', dest='sign', choices=['ascii', 'ebcdic'], default='ascii',
                    help='how a signed DISPLAY item stores an embedded sign: ascii (negative '
                         'digits 0x70-0x79, the default) or ebcdic (overpunch letters {A-I }J-R)')
    ap.add_argument('-ffilename-mapping', dest='filename_mapping', action='store_true', default=True,
                    help='map ASSIGN names at OPEN: DD_name, dd_name or name from the '
                         'environment, a leading $VAR/, and COB_FILE_PATH (default)')
    ap.add_argument('-fno-filename-mapping', dest='filename_mapping', action='store_false',
                    help='use ASSIGN names as they stand')
    ap.add_argument('-fimplicit-init', dest='implicit_init', action='store_true',
                    help='a COBOL program called from C starts the runtime itself '
                         '(always the case here; accepted for cobc command lines)')
    ap.add_argument('-l', dest='libs', action='append', default=[], metavar='LIB',
                    help='link with library LIB')
    ap.add_argument('-L', dest='libdirs', action='append', default=[], metavar='DIR',
                    help='directory to search for -l libraries')
    ap.add_argument('-E', dest='preprocess', action='store_true',
                    help='preprocess only: write the source after COPY, REPLACE and '
                         'directives, as free-format COBOL (to -o FILE or standard output)')
    ap.add_argument('-fsyntax-only', dest='syntax_only', action='store_true',
                    help='check the program and report errors; write nothing')
    ap.add_argument('-free', '--free', '-F', dest='fmt', action='store_const', const='free', help='free-format source')
    ap.add_argument('-fixed', '--fixed', dest='fmt', action='store_const', const='fixed', help='fixed-format source')
    ap.add_argument('-I', dest='include', action='append', default=[], help='copybook directory')
    ap.add_argument('-D', dest='define', action='append', default=[], metavar='NAME[=VALUE]',
                    help='define a compilation variable for >>IF and >>DEFINE ... AS PARAMETER')
    ap.add_argument('-O', dest='opt', default='2', nargs='?', const='2', help='C optimisation level')
    ap.add_argument('-g', dest='debug', action='store_true', help='include C debug information')
    ap.add_argument('--no-check', dest='check', action='store_false', help='disable subscript/reference checks')
    ap.add_argument('--refmod-zero-length', '-fno-ref-mod-zero-length', dest='refmod_zero',
                    action='store_true', default=None,
                    help='a zero-length reference modification is an error (the default in every '
                         'dialect but the default one)')
    ap.add_argument('-fref-mod-zero-length', dest='refmod_zero', action='store_false',
                    help='a reference modification may have length zero, and names no bytes')
    ap.add_argument('-fperform-osvs', dest='perform_osvs', action='store_true', default=None,
                    help='a PERFORM returns when control reaches the end of its range even while a '
                         'later PERFORM is active, as OS/VS and IBM COBOL do (-std=ibm sets it)')
    ap.add_argument('-fno-perform-osvs', dest='perform_osvs', action='store_false',
                    help='only the most recent PERFORM returns at the end of its range (the default)')
    ap.add_argument('-farithmetic-osvs', dest='arithmetic_osvs', action='store_true', default=None,
                    help="each intermediate result of a COMPUTE is cut to the statement's largest "
                         "scale, as OS/VS COBOL does (-std=ibm sets it)")
    ap.add_argument('-fno-arithmetic-osvs', dest='arithmetic_osvs', action='store_false',
                    help='intermediate results keep their precision (the default)')
    ap.add_argument('-frelax-syntax-checks', dest='relax_syntax', action='store_true',
                    help='accept an inline PERFORM ended by a period instead of END-PERFORM, with '
                         'a warning; YACCC accepts the other things this cobc option allows anyway')
    ap.add_argument('-fmissing-statement=ok', '-flarger-redefines-ok', '-ftop-level-occurs-clause=ok',
                    '-fno-constant-folding', '-fconstant-folding', dest='accepted_cobc',
                    action='append_const', const=True,
                    help='accepted, as what they allow YACCC always allows: an empty inline '
                         'PERFORM or IF branch, a REDEFINES larger than what it redefines, OCCURS '
                         'at level 01; constant folding is the C compiler\'s')
    ap.add_argument('-std', '--std', dest='std', metavar='DIALECT',
                    help='dialect for the choices the standards leave open: '
                         + ', '.join(dialect.accepted_names()))
    ap.add_argument('--binary-size', '-fbinary-size', dest='binary_size', default=None,
                    choices=['2-4-8', '1-2-4-8', '1--8'],
                    help='storage size scheme for BINARY/COMP items: 2, 4 or 8 bytes, 1, 2, 4 or '
                         '8, or the fewest bytes that hold the digits (default: from the dialect)')
    ap.add_argument('-fbinary-byteorder', dest='binary_byteorder', default='big-endian',
                    choices=['big-endian', 'native'],
                    help='the byte order of BINARY/COMP items: big-endian (the default, as on '
                         'mainframes) or the machine\'s own, as COMP-5')
    ap.add_argument('-fbinary-comp-1', dest='binary_comp1', action='store_true',
                    help='COMP-1 is a binary integer of two bytes, as $SET COMP-1(BINARY) makes it')
    ap.add_argument('-fbinary-truncate', dest='binary_truncate', action='store_true', default=None,
                    help='a BINARY item is limited to the digits of its PICTURE (default)')
    ap.add_argument('-fno-binary-truncate', dest='binary_truncate', action='store_false',
                    help='a BINARY item may use the whole capacity of its USAGE')
    ap.add_argument('-fnotrunc', dest='notrunc', action='store_true',
                    help='cobc -fnotrunc: -fno-binary-truncate and -fno-pretty-display together')
    ap.add_argument('-fpretty-display', dest='pretty_display', action='store_true', default=None,
                    help='DISPLAY writes a numeric item with its decimal point (default)')
    ap.add_argument('-fno-pretty-display', dest='pretty_display', action='store_false',
                    help='DISPLAY writes the stored digits as they stand')
    ap.add_argument('-fassign-clause', dest='assign_clause', default=None,
                    choices=['dynamic', 'mf', 'external', 'ibm'],
                    help='ASSIGN word, for a word a data item has as its name: the file the '
                         'item names (dynamic, mf: the default) or the name itself, IBM label '
                         'parts dropped (external, ibm: -std=ibm sets it)')
    ap.add_argument('-fmove-ibm', dest='move_ibm', action='store_true', default=None,
                    help='an alphanumeric MOVE whose receiving bytes begin inside the sending ones '
                         'copies a byte at a time, so a byte propagates, as IBM\'s MVC does '
                         '(-std=ibm sets it)')
    ap.add_argument('-fno-move-ibm', dest='move_ibm', action='store_false',
                    help='an overlapping MOVE moves the bytes as they were (the default)')
    ap.add_argument('-fsystem-name', dest='system_names', action='append', default=[],
                    metavar='NAMES', help='accepted: the switch names it would add (SWn, SWITCH n, '
                                          'SWITCH A to Z, USW-n) are always known')
    ap.add_argument('-fnot-register', dest='not_registers', action='append', default=[],
                    metavar='NAME', help='NAME (TALLY, RETURN-CODE, ...) is no special register, '
                                         'but an ordinary word a program may declare')
    ap.add_argument('-facu-literals', dest='acu_literals', default=None,
                    choices=['ok', 'warning', 'error'],
                    help='B#101, O#777, X#FF and H#FF as numeric literals, as ACUCOBOL has them '
                         '(-std=acu allows them)')
    ap.add_argument('--lsp', action='store_true',
                    help='run as a Language Server Protocol server on standard input and output, '
                         'for an editor: diagnostics, definitions, references, hover, outline; '
                         'the other options given apply to every document')
    ap.add_argument('-fprof', dest='prof', action='store_true',
                    help='profile the run: the calls and the time of every section and paragraph '
                         'written as CSV when it ends, to prof-PROGRAM.csv or $COB_PROF_FILE')
    ap.add_argument('-fodoslide', dest='odoslide', action='store_true', default=None,
                    help='every table with OCCURS DEPENDING ON takes its current size, and what '
                         'follows it in the record moves up with it: IBM Enterprise COBOL\'s '
                         'layout, Micro Focus\'s ODOSLIDE')
    ap.add_argument('-fno-odoslide', dest='odoslide', action='store_false',
                    help='a variable table with items after it in its group keeps its maximum '
                         'size (the default, as cobc)')
    ap.add_argument('-fcomplex-odo', dest='complex_odo', action='store_true',
                    help='accepted: OCCURS DEPENDING ON tables may be followed by other items, '
                         'and nested, as cobc allows with this option')
    ap.add_argument('-fdpc-in-data', dest='dpc_in_data', default=None,
                    choices=['none', 'json', 'xml', 'all'],
                    help='use the decimal comma in JSON/XML numbers when '
                         'DECIMAL-POINT IS COMMA (default: none)')
    ap.add_argument('-fmissing-period', dest='missing_period', action='store_true', default=None,
                    help="accept a statement where a '.' is required")
    ap.add_argument('-fno-missing-period', dest='missing_period', action='store_false',
                    help="require '.' (default)")
    ap.add_argument('--debugging-mode', action='store_true', help="compile as if WITH DEBUGGING MODE were specified")
    ap.add_argument('--keep-c', action='store_true', help='keep the generated C file next to the output')
    ap.add_argument('--run', action='store_true', help='run the program after building it')
    ap.add_argument('--cc', default=os.environ.get('CC') or (shutil.which('gcc') and 'gcc') or 'cc',
                    help='C compiler to use (gcc or clang; default $CC, then gcc, then cc)')
    ap.add_argument('--build-runtime', action='store_true', help='(re)build the runtime library and exit')
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('--version', action='version', version=f'YACCC {VERSION}')
    # -fdump alone is -fdump=ALL: an optional value would take the source
    # file's name that follows it
    argv = list(sys.argv[1:] if argv is None else argv)
    bare = {'-fdump': '-fdump=ALL', '-fno-dump': '-fno-dump=ALL', '-W': '-Wall',
            '-save-temps': '-save-temps=.',
            '-j': '-job=', '-job': '-job=', '-P': '-P='}
    k = argv.index('--run') if '--run' in argv else len(argv)
    head = []
    i = 0
    while i < k:
        a = argv[i]
        if a in ('-A', '-Q') and i + 1 < k:
            # -A -g: the C compiler's options begin with '-', which would
            # otherwise read as one of ours
            head.append(a + argv[i + 1])
            i += 2
            continue
        head.append(bare.get(a, a))
        i += 1
    argv = head + argv[k:]
    args, unknown = ap.parse_known_args(argv)
    run_args = _split_run_args(ap, args, unknown)

    if args.build_runtime:
        if safe_build_runtime(args.cc, args.verbose, force=True) is None:
            return 1
        print(f"runtime library built: {os.path.join(runtime_lib_dir(), 'libcobrt.a')}")
        return 0
    if args.info:
        return show_info(args.cc)
    if not args.sources and not args.lsp:
        ap.error('no source files given')
    # a positional token that is not a readable file is usually an argument
    # meant for the program being run, or a misspelt option's value
    missing = [p for p in args.sources if p != '-' and not os.path.isfile(p)]
    if missing:
        names = ' '.join(missing)
        if any(not _looks_like_source(p) for p in missing):
            ap.error(f"no such source file: {names}; arguments for the program "
                     f"being run go after --run")
        ap.error(f"no such source file: {names}")
    if args.compile_only and args.module:
        ap.error("-c and -m: choose an object file or a module")
    csrcs = [p for p in args.sources if p.lower().endswith(C_EXT)]
    linkin = [p for p in args.sources if p.lower().endswith(LINK_EXT)]
    cobol = [p for p in args.sources if p not in csrcs and p not in linkin]
    if (args.emit_c or args.preprocess or args.syntax_only) and not cobol:
        ap.error("no COBOL source files given")
    if (args.compile_only or args.module) and linkin:
        ap.error(f"{'-c' if args.compile_only else '-m'} compiles sources; "
                 f"object files and libraries are linked into an executable")
    if (args.compile_only or args.module) and args.output and len(cobol) + len(csrcs) > 1:
        ap.error("-o names one output: with -c or -m it needs a single source")

    opts = Options()
    try:
        opts.dialect = dialect.Dialect(args.std or 'default')
    except KeyError:
        ap.error(f"unknown dialect '{args.std}'; known: "
                 + ', '.join(dialect.accepted_names()))
    d = opts.dialect
    if (args.std or '').lower().strip() in dialect.STRICT:
        print(f"yaccc: note: -std={args.std}: the choices of {d.name}; extensions a strict "
              f"dialect rejects are still accepted", file=sys.stderr)
    opts.binary_size = args.binary_size or d.binary_size
    opts.binary_byteorder = args.binary_byteorder
    opts.binary_comp1 = args.binary_comp1
    opts.binary_truncate = d.binary_truncate if args.binary_truncate is None else args.binary_truncate
    opts.pretty_display = d.pretty_display if args.pretty_display is None else args.pretty_display
    opts.arithmetic_osvs = d.arithmetic_osvs if args.arithmetic_osvs is None else args.arithmetic_osvs
    opts.perform_osvs = d.perform_osvs if args.perform_osvs is None else args.perform_osvs
    opts.assign_clause = args.assign_clause or d.assign_clause
    opts.move_ibm = d.move_ibm if args.move_ibm is None else args.move_ibm
    opts.implicit_assign = args.implicit_assign
    opts.not_registers = {n.strip().upper() for spec in args.not_registers
                          for n in spec.split(',') if n.strip()}
    from . import lexer
    lexer.ACU_LITERALS = d.acu_literals if args.acu_literals is None else args.acu_literals != 'error'
    opts.relax_syntax = args.relax_syntax
    if args.notrunc:
        opts.binary_truncate = False
        opts.pretty_display = False
    opts.missing_period = d.missing_period if args.missing_period is None else args.missing_period
    opts.host_sign = d.host_sign
    opts.nonnum_zero = d.nonnum_zero
    opts.space_raw = d.space_raw
    if args.dpc_in_data is not None:
        opts.dpc_in_data = args.dpc_in_data
    opts.prof = args.prof
    opts.odoslide = bool(args.odoslide)
    opts.odoslide_set = args.odoslide is not None
    opts.check = args.check
    opts.refmod_zero = d.refmod_zero if args.refmod_zero is None else args.refmod_zero
    opts.line_map = args.debug
    opts.trace = args.trace
    opts.filename_mapping = args.filename_mapping
    opts.sign = args.sign
    opts.sticky_linkage = args.sticky_linkage
    opts.recursive_check = args.recursive_check
    opts.stack_trace = args.stack_trace
    # -debug, then -fno-ec / -fec in order: a kind of check out or (back) in
    opts.checks_off = set()         # range checks, on unless turned off
    opts.checks_extra = set()       # the data check, off unless turned on
    if args.debug_checks:
        opts.check = True
        opts.checks_extra = set(_OFF_BY_DEFAULT)
        opts.stack_trace = True
    for on, spec in [(False, x) for x in args.ec_off] + [(True, x) for x in args.ec_on]:
        for name in (n.strip().upper() for n in spec.split(',') if n.strip()):
            if name not in EC_RANGE:
                ap.error(f"-fec/-fno-ec: {name}: YACCC compiles the range checks and the data check in or out "
                         f"({', '.join(sorted(EC_RANGE))}); its other checks are always made")
            kinds = EC_RANGE[name]
            if on:
                opts.checks_off -= kinds
                opts.checks_extra |= kinds & _OFF_BY_DEFAULT
                if kinds - _OFF_BY_DEFAULT:
                    opts.check = True
            else:
                opts.checks_off |= kinds
                opts.checks_extra -= kinds

    DIAG.no_warnings = args.no_warnings
    for w in args.warnings:
        if w in ('all', 'extra'):
            continue
        if w == 'error':
            DIAG.warn_errors = True
            continue
        name = w[3:] if w.startswith('no-') else w
        if name not in errors.WARNINGS:
            ap.error(f"-W{w}: unknown warning (cobc's names: {', '.join(sorted(errors.WARNINGS))})")
        if w.startswith('no-'):
            DIAG.warn_off.add(name)
        elif name not in errors.ISSUED:
            print(f"yaccc: note: -W{w}: YACCC has no such warning to turn on", file=sys.stderr)
    if args.single_quote:
        from . import codegen, words
        words.FIG_BYTES['QUOTE'] = b"'"
        codegen.FIG_FIELD['QUOTE'] = '&cob_fig_apos'
    opts.default_colseq = args.default_colseq
    opts.static_call = args.static_call
    if args.mfcomment:
        from . import source
        source.MF_COMMENT = True
    opts.xref = args.xref
    opts.listing = args.listing or args.listing_wide
    if args.plisting is not None and not opts.listing:
        # -P[=DIR|FILE]: the listing, beside the source's name in DIR
        base = os.path.splitext(os.path.basename(args.sources[0]))[0] + '.lst' if args.sources else 'yaccc.lst'
        pl = args.plisting
        opts.listing = os.path.join(pl, base) if pl and os.path.isdir(pl) else (pl or base)
    if args.text_column is not None:
        if not 72 <= args.text_column <= 255:
            ap.error(f"-ftext-column={args.text_column}: the margin is a column from 72 to 255")
        from . import source
        source.set_text_column(args.text_column)
    if args.max_errors is not None:
        if args.max_errors < 1:
            ap.error(f"-fmax-errors={args.max_errors}: at least 1")
        DIAG.max_errors = args.max_errors
    if args.job is not None:
        # -j: build and run, the ARGS one string as cobc takes them
        import shlex
        args.run = True
        run_args[:0] = shlex.split(args.job)
    if args.dump:
        from .dumpgen import parse_dump_scopes
        try:
            opts.dump = parse_dump_scopes(args.dump)
        except ValueError as e:
            ap.error(str(e))
    if args.no_dump and getattr(opts, 'dump', None):
        # -fno-dump[=scopes]: out of the dump again (RD and SC never are in it)
        from .dumpgen import parse_dump_scopes
        wanted = [w for w in args.no_dump.replace(' ', '').upper().split(',') if w not in ('RD', 'SC')]
        try:
            drop = parse_dump_scopes(','.join(wanted)) if wanted else set()
        except ValueError as e:
            ap.error(str(e).replace('-fdump', '-fno-dump'))
        opts.dump = (set(opts.dump) - drop) or None
    if args.not_intrinsic:
        opts.not_intrinsic = {n.strip().upper() for n in args.not_intrinsic.split(',') if n.strip()}
    if args.not_reserved or args.reserved:
        # the reserved-word set is the parser's, for every source of this run
        from .words import RESERVED, VERBS
        for spec in args.reserved:
            for w in (x.strip().upper() for x in spec.split(',') if x.strip()):
                if '=' in w or ':' in w:
                    ap.error(f"-freserved: '{w}': only words can be reserved, not aliases")
                RESERVED.add(w)
        for spec in args.not_reserved:
            for w in (x.strip().upper() for x in spec.split(',') if x.strip()):
                if w in VERBS:
                    ap.error(f"-fnot-reserved: '{w}' begins a statement and stays reserved")
                RESERVED.discard(w)
    if args.defaultbyte is not None and args.defaultbyte.lower() != 'init':
        db = args.defaultbyte
        if db.isdigit() and int(db) <= 255:
            opts.defaultbyte = int(db)
        elif len(db) == 1:
            opts.defaultbyte = ord(db)
        elif len(db) == 3 and db[0] == db[2] and db[0] in '"\'':
            opts.defaultbyte = ord(db[1])
        else:
            ap.error(f"-fdefaultbyte: '{db}' is not init, one character or a byte value 0-255")
    if args.intrinsics:
        from .words import FUNCTIONS
        names = {n.strip().upper() for n in args.intrinsics.split(',') if n.strip()}
        if 'ALL' in names:
            names = set(FUNCTIONS)
        bad = sorted(n for n in names if n not in FUNCTIONS)
        if bad:
            ap.error(f"-fintrinsics: no intrinsic function {', '.join(bad)}")
        opts.bare_intrinsics = names
    fmt = args.fmt or 'auto'
    defines = {}
    for d in args.define:
        name, eq, value = d.partition('=')
        defines[name] = value if eq else True
    if args.preprocess:
        try:
            text = preprocess_sources(cobol, fmt, args.include, args.debugging_mode, defines)
        except CompileError as e:
            return report(e)
        DIAG.flush()
        if args.output:
            with open(args.output, 'w', encoding='latin-1') as f:
                f.write(text)
        else:
            sys.stdout.write(text)
        return 0

    if args.lsp:
        from .lsp import serve
        return serve(opts, fmt, args.include, defines, VERSION)
    if args.compile_only or args.module:
        return build_parts(args, opts, fmt, defines, cobol, csrcs)

    opts.export_c = bool(csrcs or linkin)
    # as with cobc -x, the first source is the main program: when it is C or
    # an object file, main() is that one's, and the COBOL is called from it
    opts.emit_main = bool(cobol) and args.sources[0] in cobol
    csrc = None
    if cobol:
        rc, csrc = translate(cobol, opts, fmt, args, defines)
        if rc:
            return rc
    if args.syntax_only:
        return 0

    base = os.path.splitext(os.path.basename((cobol or csrcs or linkin)[0]))[0]
    if args.emit_c:
        out = args.output or base + '.c'
        with open(out, 'w', encoding='latin-1') as f:
            f.write(csrc)
        return 0

    exe = args.output or base
    lib = safe_build_runtime(args.cc, args.verbose)
    if lib is None:
        return 1
    tmpdir = tempfile.mkdtemp(prefix='yaccc_')
    try:
        inputs = []
        if csrc is not None:
            cpath = kept_c_path(args, exe, base) or os.path.join(tmpdir, base + '.c')
            with open(cpath, 'w', encoding='latin-1') as f:
                f.write(csrc)
            inputs.append(cpath)
        objs = []
        for i, c in enumerate(csrcs):
            # the user's own C: compiled with its own warnings, not the generated code's flags
            o = os.path.join(tmpdir, f"c{i}_" + os.path.splitext(os.path.basename(c))[0] + '.o')
            cmd = [args.cc, '-std=gnu11', f'-O{args.opt}', '-I', RUNTIME_DIR] + cc_options(args) + ['-c', c, '-o', o]
            if args.debug:
                cmd.insert(1, '-g')
            if not run_cc(cmd, args.verbose, f"C compilation of {c} failed"):
                return 1
            objs.append(o)
        cmd = ([args.cc, '-std=gnu11', f'-O{args.opt}'] + GENERATED_C_FLAGS + ['-I', RUNTIME_DIR] + cc_options(args)
               + inputs + objs + linkin + ['-o', exe] + runtime_link_args(lib)
               + [f'-L{d}' for d in args.libdirs] + [f'-l{x}' for x in args.libs] + ['-lm', '-ldl']
               + ld_options(args))
        if args.debug:
            cmd.insert(1, '-g')
        what = "C compilation failed (generated code error)" if csrc is not None and not (objs or linkin) \
            else "linking failed"
        if not run_cc(cmd, args.verbose, what):
            return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if args.run:
        path = exe if os.path.dirname(exe) else os.path.join('.', exe)
        return subprocess.run([path] + run_args).returncode
    return 0
