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
               'cobrt_call.c']
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


def safe_build_runtime(cc, verbose=False, force=False):
    try:
        return build_runtime(cc, verbose, force)
    except FileNotFoundError as e:
        print(f"yaccc: cannot run '{e.filename or cc}': install gcc or clang, or name one with --cc",
              file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"yaccc: building the runtime library failed: {' '.join(e.cmd)}", file=sys.stderr)
    return None


def compile_sources(paths, opts, fmt, include_dirs, debugging=False, defines=None):
    programs = []
    for p in paths:
        ss = SourceSet(include_dirs=include_dirs, fmt=fmt, debugging=debugging, defines=defines)
        toks = ss.load(p)
        parser = Parser(toks, ss.directives.vars)
        parser.bare_intrinsics = set(getattr(opts, 'bare_intrinsics', ()))
        parser.not_intrinsic = set(getattr(opts, 'not_intrinsic', ()))
        parser.dialect = opts.dialect
        parser.directives_state = ss.directives
        opts.directives = ss.directives
        parser.missing_period = getattr(opts, 'missing_period', False)
        if getattr(ss, 'dpc_in_data', None) and opts.dpc_in_data == 'none':
            opts.dpc_in_data = ss.dpc_in_data
        programs.extend(parser.parse_unit())
        DIAG.check()
    opts.source_name = paths[0]
    opts.debugging = debugging
    gen = CodeGen(programs, opts)
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


def translate(cobol, opts, fmt, args, defines):
    """COBOL sources to one C translation unit: (status, C text)."""
    try:
        csrc, _ = compile_sources(cobol, opts, fmt, args.include, args.debugging_mode, defines)
    except CompileError as e:
        return report(e), None
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
                cmd = [args.cc, '-std=gnu11', f'-O{args.opt}', '-fPIC', '-I', RUNTIME_DIR] + flags + [src, '-o', out]
            else:
                DIAG.items.clear()
                DIAG.nerrors = 0
                rc, csrc = translate([src], opts, fmt, args, defines)
                if rc:
                    return rc
                if args.syntax_only:
                    continue
                cpath = os.path.splitext(out)[0] + '.c' if args.keep_c else os.path.join(tmpdir, base + '.c')
                with open(cpath, 'w', encoding='latin-1') as f:
                    f.write(csrc)
                cmd = ([args.cc, '-std=gnu11', f'-O{args.opt}', '-w', '-fwrapv', '-fPIC', '-I', RUNTIME_DIR]
                       + flags + [cpath, '-o', out])
            if args.debug:
                cmd.insert(1, '-g')
            if not run_cc(cmd, args.verbose, f"C compilation of {src} failed"):
                return 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


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
    ap.add_argument('-fdefaultbyte', dest='defaultbyte', metavar='init|CHAR|0-255',
                    help='what WORKING-STORAGE without a VALUE clause starts as: init (spaces '
                         'and zeros by type, the default), one character, or a byte value')
    ap.add_argument('-fnot-intrinsic', dest='not_intrinsic', metavar='NAME,...',
                    help='intrinsic function names a FUNCTION-ID of the same name replaces')
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
    ap.add_argument('-free', '--free', dest='fmt', action='store_const', const='free', help='free-format source')
    ap.add_argument('-fixed', '--fixed', dest='fmt', action='store_const', const='fixed', help='fixed-format source')
    ap.add_argument('-I', dest='include', action='append', default=[], help='copybook directory')
    ap.add_argument('-D', dest='define', action='append', default=[], metavar='NAME[=VALUE]',
                    help='define a compilation variable for >>IF and >>DEFINE ... AS PARAMETER')
    ap.add_argument('-O', dest='opt', default='2', nargs='?', const='2', help='C optimisation level')
    ap.add_argument('-g', dest='debug', action='store_true', help='include C debug information')
    ap.add_argument('--no-check', dest='check', action='store_false', help='disable subscript/reference checks')
    ap.add_argument('--refmod-zero-length', dest='refmod_zero', action='store_true',
                    help='a zero-length reference modification is an error (cobc -fno-ref-mod-zero-length)')
    ap.add_argument('-std', '--std', dest='std', metavar='DIALECT',
                    help='dialect for the choices the standards leave open: '
                         + ', '.join(dialect.accepted_names()))
    ap.add_argument('--binary-size', default=None, choices=['2-4-8', '1-2-4-8'],
                    help='storage size scheme for BINARY/COMP items '
                         '(default: from the dialect)')
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
    args, unknown = ap.parse_known_args(argv)
    run_args = _split_run_args(ap, args, unknown)

    if args.build_runtime:
        if safe_build_runtime(args.cc, args.verbose, force=True) is None:
            return 1
        print(f"runtime library built: {os.path.join(runtime_lib_dir(), 'libcobrt.a')}")
        return 0
    if not args.sources:
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
    opts.binary_size = args.binary_size or d.binary_size
    opts.binary_truncate = d.binary_truncate if args.binary_truncate is None else args.binary_truncate
    opts.pretty_display = d.pretty_display if args.pretty_display is None else args.pretty_display
    opts.arithmetic_osvs = d.arithmetic_osvs
    if args.notrunc:
        opts.binary_truncate = False
        opts.pretty_display = False
    opts.missing_period = d.missing_period if args.missing_period is None else args.missing_period
    opts.host_sign = d.host_sign
    opts.nonnum_zero = d.nonnum_zero
    opts.space_raw = d.space_raw
    if args.dpc_in_data is not None:
        opts.dpc_in_data = args.dpc_in_data
    opts.check = args.check
    opts.refmod_zero = args.refmod_zero
    opts.line_map = args.debug
    opts.trace = args.trace
    opts.filename_mapping = args.filename_mapping
    opts.sign = args.sign
    opts.sticky_linkage = args.sticky_linkage
    opts.recursive_check = args.recursive_check
    if args.not_intrinsic:
        opts.not_intrinsic = {n.strip().upper() for n in args.not_intrinsic.split(',') if n.strip()}
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
            cpath = os.path.splitext(exe)[0] + '.c' if args.keep_c else os.path.join(tmpdir, base + '.c')
            with open(cpath, 'w', encoding='latin-1') as f:
                f.write(csrc)
            inputs.append(cpath)
        objs = []
        for i, c in enumerate(csrcs):
            # the user's own C: compiled with its own warnings, not the generated code's flags
            o = os.path.join(tmpdir, f"c{i}_" + os.path.splitext(os.path.basename(c))[0] + '.o')
            cmd = [args.cc, '-std=gnu11', f'-O{args.opt}', '-I', RUNTIME_DIR, '-c', c, '-o', o]
            if args.debug:
                cmd.insert(1, '-g')
            if not run_cc(cmd, args.verbose, f"C compilation of {c} failed"):
                return 1
            objs.append(o)
        cmd = ([args.cc, '-std=gnu11', f'-O{args.opt}', '-w', '-fwrapv', '-I', RUNTIME_DIR]
               + inputs + objs + linkin + ['-o', exe] + runtime_link_args(lib)
               + [f'-L{d}' for d in args.libdirs] + [f'-l{x}' for x in args.libs] + ['-lm', '-ldl'])
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
