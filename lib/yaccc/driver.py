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
from .errors import CompileError, DIAG
from .lexer import SourceSet
from .parser import Parser

HERE = os.path.dirname(os.path.abspath(__file__))        # .../lib/yaccc
PKG_ROOT = os.path.dirname(os.path.dirname(HERE))       # the project root
RUNTIME_DIR = os.path.join(PKG_ROOT, 'runtime')
RUNTIME_SRC = ['cobrt_core.c', 'cobrt_str.c', 'cobrt_fn.c', 'cobrt_math.c', 'cobrt_dt.c',
               'cobrt_sys.c', 'cobrt_io.c', 'cobrt_rw.c', 'cobrt_json.c', 'cobrt_xml.c']
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
        opts.directives = ss.directives
        parser.missing_period = getattr(opts, 'missing_period', False)
        if getattr(ss, 'dpc_in_data', None) and opts.dpc_in_data == 'none':
            opts.dpc_in_data = ss.dpc_in_data
        programs.extend(parser.parse_unit())
    opts.source_name = paths[0]
    opts.debugging = debugging
    gen = CodeGen(programs, opts)
    return gen.generate(), programs


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


def _looks_like_source(path):
    return path.lower().endswith(SOURCE_EXT)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='yaccc', description='COBOL compiler (COBOL -> C -> native executable)')
    ap.add_argument('sources', nargs='*', help='COBOL source files')
    ap.add_argument('-o', dest='output', help='output file name')
    ap.add_argument('-x', action='store_true', help='build an executable (default)')
    ap.add_argument('-C', dest='emit_c', action='store_true', help='translate only: write C source')
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

    opts = Options()
    try:
        opts.dialect = dialect.Dialect(args.std or 'default')
    except KeyError:
        ap.error(f"unknown dialect '{args.std}'; known: "
                 + ', '.join(dialect.accepted_names()))
    d = opts.dialect
    opts.binary_size = args.binary_size or d.binary_size
    opts.binary_truncate = d.binary_truncate if args.binary_truncate is None else args.binary_truncate
    opts.missing_period = d.missing_period if args.missing_period is None else args.missing_period
    if args.dpc_in_data is not None:
        opts.dpc_in_data = args.dpc_in_data
    opts.check = args.check
    opts.refmod_zero = args.refmod_zero
    opts.line_map = args.debug
    fmt = args.fmt or 'auto'
    try:
        defines = {}
        for d in args.define:
            name, eq, value = d.partition('=')
            defines[name] = value if eq else True
        csrc, programs = compile_sources(args.sources, opts, fmt, args.include, args.debugging_mode, defines)
    except CompileError as e:
        DIAG.flush()
        print(str(e), file=sys.stderr)
        return 1
    DIAG.flush()

    base = os.path.splitext(os.path.basename(args.sources[0]))[0]
    if args.emit_c:
        out = args.output or base + '.c'
        with open(out, 'w', encoding='latin-1') as f:
            f.write(csrc)
        return 0

    exe = args.output or base
    lib = safe_build_runtime(args.cc, args.verbose)
    if lib is None:
        return 1
    if args.keep_c:
        cpath = os.path.splitext(exe)[0] + '.c'
        tmpdir = None
    else:
        tmpdir = tempfile.mkdtemp(prefix='yaccc_')
        cpath = os.path.join(tmpdir, base + '.c')
    try:
        with open(cpath, 'w', encoding='latin-1') as f:
            f.write(csrc)
        cmd = [args.cc, '-std=gnu11', f'-O{args.opt}', '-w', '-fwrapv', '-I', RUNTIME_DIR, cpath, '-o', exe, lib, '-lm']
        if args.debug:
            cmd.insert(1, '-g')
        if args.verbose:
            print(' '.join(cmd), file=sys.stderr)
        try:
            r = subprocess.run(cmd)
        except FileNotFoundError:
            print(f"yaccc: cannot run '{args.cc}': install gcc or clang, or name one with --cc", file=sys.stderr)
            return 1
        if r.returncode != 0:
            print("yaccc: C compilation failed (generated code error)", file=sys.stderr)
            return 1
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if args.run:
        path = exe if os.path.dirname(exe) else os.path.join('.', exe)
        return subprocess.run([path] + run_args).returncode
    return 0
