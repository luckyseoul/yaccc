#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Runs the runtime tests of the GnuCOBOL 3.1.2 testsuite (autotest .at files)
with yaccc and compares exit status and standard output with the
testsuite's expectations.

usage: run_gc.py [--cobc] [-k TEXT] [-v] [--log FILE] [--expect RESULTS] [--xfail]
                 TESTSUITE_SRC [FILE.at ...]

TESTSUITE_SRC is GnuCOBOL's tests/testsuite.src directory. Only tests built
from COBOL sources with plain $COMPILE / $COMPILE_MODULE steps and run with
$COBCRUN_DIRECT are executed; tests that need C code, cobc dialect options,
shell scripting or terminal input are reported as skipped.

Results: PASS; FAIL (wrong output or exit status); CERR (yaccc rejected the
program); XERR (timeout); SKIP (not runnable by this harness).
-v prints one line per test; that output is the results file read by
--expect, which prints only the tests whose result changed and exits with
status 1 if a test recorded as PASS no longer passes.
--cobc runs the same steps with GnuCOBOL's cobc instead, to tell apart tests
that depend on the environment.
"""
import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
YACCC = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'yaccc')

STATUSES = ('PASS', 'FAIL', 'CERR', 'XERR', 'SKIP')

QUADRIGRAPHS = (('@<:@', '['), ('@:>@', ']'), ('@S|@', '$'), ('@%:@', '#'), ('@&t@', ''),
                ('@{:@', '('), ('@:}@', ')'))

# cobc options that do not change behavior here, and translations
# tests whose GnuCOBOL behaviour YACCC improves on deliberately
DELIBERATE = {
    'CALL in from C with init missing / implicit':
        'deliberate difference: a COBOL program called from C starts the runtime itself',
}

IGNORED_FLAGS = {'-x', '-w', '-g', '-v', '-debug', '-d', '-O', '-O2', '-Os', '-Wall', '-Wextra',
                 # programs are linked into the executable that calls them, which
                 # is what -static asks for
                 '-static'}
FLAG_MAP = {'-free': ['-free'], '--free': ['-free'], '-fixed': ['-fixed'],
            '--fixed': ['-fixed'], '-fdebugging-line': ['--debugging-mode'],
            # yaccc has these as its own options
            '-fnotrunc': ['-fnotrunc'],
            '-fbinary-truncate': [],        # yaccc's default
            '-fno-ref-mod-zero-length': ['--refmod-zero-length'],
            # $SET CONSTANT is always defined here; the flag only switches it on
            '-fdefine-constant-directive=ok': [], '-fdefine-constant-directive': [],
            '-std=mf': ['-std', 'mf'], '-std=default': ['-std', 'default'],
            '-std=ibm': ['-std', 'ibm'], '-std=gnu': ['-std', 'gnu'],
            '-std=acu': ['-std', 'acu'],
            '-fno-ec=BOUND': ['--no-check'],
            '-fno-ec=BOUND-REF-MOD': ['--no-check'],
            '-fno-ec=BOUND-REF-MOD-ALL': ['--no-check'],
            '-fno-ec=ALL': ['--no-check'],
            '-fbinary-size=2-4-8': ['--binary-size', '2-4-8'],
            '-fbinary-size=1-2-4-8': ['--binary-size', '1-2-4-8'],
            '-fdpc-in-data=none': ['-fdpc-in-data', 'none'],
            '-fdpc-in-data=json': ['-fdpc-in-data', 'json'],
            '-fdpc-in-data=xml': ['-fdpc-in-data', 'xml'],
            '-fdpc-in-data=all': ['-fdpc-in-data', 'all'],
            '-ffilename-mapping': ['-ffilename-mapping'],
            '-fno-filename-mapping': ['-fno-filename-mapping'],
            '-ftrace': ['-ftrace'], '-ftraceall': ['-ftraceall'],
            '-fimplicit-init': ['-fimplicit-init'],
            '-fsign=ascii': ['-fsign', 'ascii'], '-fsign=ebcdic': ['-fsign', 'ebcdic'],
            '-fintrinsics=all': ['-fintrinsics', 'all'], '-fintrinsics=pi,e': ['-fintrinsics', 'pi,e'],
            '-fsticky-linkage': ['-fsticky-linkage'], '-fentry-statement=ok': ['-fentry-statement=ok'],
            '-fdefaultbyte=A': ['-fdefaultbyte', 'A'],
            '-fno-recursive-check': ['-fno-recursive-check'],
            '-fnot-intrinsic=substitute': ['-fnot-intrinsic', 'substitute']}


class Test:
    def __init__(self, title, path, line):
        self.title = title
        self.path = path
        self.line = line
        self.steps = []         # ('data', name, text) | ('check', args)
        self.skip_reason = None


# ---------------------------------------------------------------- m4 / autotest parsing
def unquote(s):
    """One level of m4 quote removal."""
    out = []
    depth = 0
    for c in s:
        if c == '[':
            if depth:
                out.append(c)
            depth += 1
        elif c == ']':
            depth -= 1
            if depth:
                out.append(c)
        else:
            out.append(c)
    return ''.join(out)


def expand(s):
    s = unquote(s)
    for q, r in QUADRIGRAPHS:
        s = s.replace(q, r)
    return s


def parse_args(text, i):
    """Arguments of a macro call; text[i] is just past '('. Returns (args, end)."""
    args = []
    cur = []
    depth = 0
    paren = 0
    n = len(text)
    # m4 drops unquoted leading whitespace of each argument
    while i < n and text[i] in ' \t\n':
        i += 1
    while i < n:
        c = text[i]
        if depth:
            if c == '[':
                depth += 1
                cur.append(c)
            elif c == ']':
                depth -= 1
                if depth:
                    cur.append(c)
            else:
                cur.append(c)
            i += 1
            continue
        if c == '[':
            depth = 1
        elif c == '(':
            paren += 1
            cur.append(c)
        elif c == ')':
            if paren == 0:
                args.append(''.join(cur))
                return args, i + 1
            paren -= 1
            cur.append(c)
        elif c == ',' and paren == 0:
            args.append(''.join(cur))
            cur = []
            i += 1
            while i < n and text[i] in ' \t\n':
                i += 1
            continue
        else:
            cur.append(c)
        i += 1
    raise ValueError("unterminated macro call")


MACRO = re.compile(r'\b(AT_[A-Z_]+|m4_[a-z_]+|AS_[A-Z_]+|dnl)\b')


TEMPLATE_SED = re.compile(r"sed -e 's/@USAGE@/([^/]*)/' \"\$\{TEMPLATE\}/([\w.-]+)\" > ([\w.-]+)")


def parse_file(path):
    text = open(path, encoding='latin-1').read()
    tests = []
    cur = None
    i = 0
    n = len(text)
    while i < n:
        m = MACRO.search(text, i)
        if not m:
            break
        if cur is not None:
            # a program made from one of the suite's templates by a shell line
            # between the macros: sed -e 's/@USAGE@/X/' "${TEMPLATE}/t.cob" > prog.cob
            for tm in TEMPLATE_SED.finditer(text, i, m.start()):
                tpath = os.path.join(os.path.dirname(path), tm.group(2))
                if os.path.isfile(tpath):
                    body = open(tpath, encoding='latin-1').read().replace('@USAGE@', tm.group(1))
                    cur.steps.append(('data', tm.group(3), body))
        name = m.group(1)
        ls = text.rfind('\n', 0, m.start()) + 1
        if name == 'dnl' or text[ls:m.start()].lstrip().startswith('#'):
            # comment: skip the rest of the line
            k = text.find('\n', m.end())
            i = n if k < 0 else k + 1
            continue
        line = text.count('\n', 0, m.start()) + 1
        j = m.end()
        args = []
        if j < n and text[j] == '(':
            args, j = parse_args(text, j + 1)
        i = j
        if name == 'AT_SETUP':
            cur = Test(expand(args[0]) if args else '?', path, line)
            continue
        if cur is None:
            continue
        if name == 'AT_CLEANUP':
            tests.append(cur)
            cur = None
        elif name == 'AT_DATA':
            cur.steps.append(('data', expand(args[0]).strip(), expand(args[1]) if len(args) > 1 else ''))
        elif name == 'AT_CHECK':
            cur.steps.append(('check', [expand(a) for a in args]))
        elif name in ('AT_KEYWORDS', 'AT_CAPTURE_FILE'):
            pass
        elif name == 'AT_SKIP_IF':
            cond = expand(args[0]) if args else ''
            # features yaccc provides; a test gated on one of these is run
            HAVE = ('ISAM', 'JSON', 'XML2')
            m = re.search(r'COB_HAS_(\w+)', cond)
            if not (m and m.group(1) in HAVE):
                cur.skip_reason = cur.skip_reason or (f'needs {m.group(1).lower()}' if m else 'AT_SKIP_IF')
        elif name == 'AT_XFAIL_IF':
            cur.skip_reason = cur.skip_reason or 'expected failure in GnuCOBOL'
        else:
            cur.skip_reason = cur.skip_reason or f'uses {name}'
    return tests


# ---------------------------------------------------------------- execution
def run(cmd, cwd, env=None, timeout=20, stdin=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL if stdin is None else stdin)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, b'', b'TIMEOUT'


class Runner:
    def __init__(self, use_cobc, keep=False, static_modules=False):
        self.use_cobc = use_cobc
        self.keep = keep
        # $COMPILE_MODULE: build a loadable module that CALL finds at run time
        # (as cobc -m does), or link its source into each executable
        self.static_modules = static_modules

    def compile(self, main, modules, flags, out, cwd, env=None):
        if env is not None:
            # the step's variables on top of the real environment: the compiler
            # is a #!/usr/bin/env python3 script and needs PATH
            env = dict(os.environ, **env)
        if self.use_cobc:
            cmd = ['cobc', '-x', '-o', out, main] + flags
            for m in modules:
                cmd.append(m)
        else:
            cmd = [YACCC, main] + modules + ['-o', out, '--binary-size', '1-2-4-8'] + flags
        return run(cmd, cwd, env=env, timeout=120)

    def translate_flags(self, words):
        """cobc options -> yaccc options; None if a test depends on one we lack."""
        out = []
        it = iter(words)
        for w in it:
            if w in FLAG_MAP:
                # a flag the compiler understands changes the program's
                # behaviour and has to be passed on; the mapped ones are the
                # runtime-check switches, which must not be dropped
                if not self.use_cobc:
                    out.extend(FLAG_MAP[w])
                else:
                    out.append(w)
                continue
            if w in IGNORED_FLAGS or w.startswith('-W') or w.startswith('-fno-ec') or w == '-fec=all':
                continue
            if w.startswith(('-fnot-reserved=', '-freserved=')) and '=' not in w.split('=', 1)[1]:
                out.append(w)               # the same option in both compilers
                continue
            if w == '-I':
                d = next(it, None)
                out.extend(['-I', d])
                continue
            if w == '-D':
                out.extend(['-D', next(it, '')])
                continue
            if w.startswith('-D') and len(w) > 2:
                out.extend(['-D', w[2:]])
                continue
            if w.startswith('-I'):
                out.extend(['-I', w[2:]])
                continue
            return None
        return out

    def run_test(self, t):
        if t.skip_reason:
            return 'SKIP', t.skip_reason
        if t.title in DELIBERATE and not self.use_cobc:
            return 'SKIP', DELIBERATE[t.title]
        tmp = tempfile.mkdtemp(prefix='gctest_')
        try:
            return self._run(t, tmp)
        finally:
            if self.keep:
                print(f"      kept {tmp}")
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    def _run(self, t, tmp):
        files = {}
        modules = []
        module_srcs = []        # built as real modules: each can still be run by $COBCRUN
        main = None
        built = {}
        checks = 0
        for step in t.steps:
            if step[0] == 'data':
                _, name, text = step
                files[name] = text
                p = os.path.join(tmp, name)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'w', encoding='latin-1') as f:
                    f.write(text)
                continue
            args = step[1]
            cmd = args[0].strip()
            status = args[1].strip() if len(args) > 1 else '0'
            want_out = args[2] if len(args) > 2 else ''
            stdin_file = None
            m = re.match(r'^(.*\S)\s*<\s*(\S+)$', cmd)
            if m:
                cmd, stdin_file = m.group(1), m.group(2)
            if '|' in cmd or ';' in cmd or '>' in cmd or '<' in cmd or '`' in cmd:
                return 'SKIP', 'shell command'
            # a backslash-newline is a line continuation, not a shell operator
            cmd = cmd.replace('\\\n', ' ').replace('\n', ' ')
            # atlocal's settings for a Unix host, expanded before the quotes that
            # delimit them are removed ("prog"$PATHSEP"prog1")
            for var, val in (('PATHSEP', ':'), ('COB_OBJECT_EXT', 'o'), ('COB_MODULE_EXT', 'so')):
                cmd = cmd.replace('${' + var + '}', val).replace('$' + var, val)
            try:
                words = shlex.split(cmd)
            except ValueError:
                return 'SKIP', 'shell command'
            env = dict(os.environ)
            env.pop('COB_SET_DEBUG', None)
            # GnuCOBOL 3.1.2 prints no stack trace after a runtime error, and
            # its tests compare standard error
            env.setdefault('COB_STACKTRACE', 'N')

            while words and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]):
                k, v = words.pop(0).split('=', 1)
                # the .at files write PATH=.:$PATH and expect the shell to have
                # expanded it; shlex does not, so expand it here
                v = re.sub(r'\$\{?(\w+)\}?', lambda m: env.get(m.group(1), ''), v)
                env[k] = v
            if not words:
                return 'SKIP', 'shell command'
            verb = words[0]
            if verb in ('$COMPILE', '$COMPILE_MODULE', '$COMPILE_ONLY'):
                srcs = [w for w in words[1:] if not w.startswith('-')
                        and w.endswith(('.cob', '.cbl', '.COB', '.CBL', '.c', '.o'))]
                rest = [w for w in words[1:] if w not in srcs]
                if '-o' in rest:
                    k = rest.index('-o')
                    out_name = rest[k + 1] if k + 1 < len(rest) else None
                    del rest[k:k + 2]
                else:
                    out_name = None
                compile_only = '-c' in rest
                if compile_only:
                    rest.remove('-c')
                if any(w.endswith('.so') for w in rest) or not srcs:
                    return 'SKIP', 'C code or object files'
                flags = self.translate_flags(rest)
                if flags is None:
                    return 'SKIP', 'cobc option ' + ' '.join(rest)
                if self.use_cobc and (compile_only or any(w.endswith(('.c', '.o')) for w in srcs)):
                    return 'SKIP', 'C code or object files'
                if compile_only and verb != '$COMPILE_ONLY':
                    # cobc -c: an object file now; $COMPILE adds -x, so its object holds main()
                    for src in srcs:
                        cmd = [YACCC, '-c'] + (['-x'] if verb == '$COMPILE' else []) + [src] \
                            + (['-o', out_name] if out_name else []) + ['--binary-size', '1-2-4-8'] + flags
                        rc, _, err = run(cmd, tmp, env=env, timeout=120)
                        if rc != 0:
                            return build_failure(err)
                    checks += 1
                    continue
                if verb == '$COMPILE_MODULE' and not self.use_cobc and not self.static_modules \
                        and status == '0':
                    # a real module: CALL loads it from the current directory
                    for src in srcs:
                        cmd = [YACCC, '-m', src] + (['-o', out_name] if out_name else []) \
                            + ['--binary-size', '1-2-4-8'] + flags
                        rc, _, err = run(cmd, tmp, env=env, timeout=120)
                        if rc != 0:
                            return build_failure(err)
                        if src.endswith(('.cob', '.cbl', '.COB', '.CBL')):
                            module_srcs.append(src)
                    checks += 1
                    continue
                if status != '0':
                    # a compile that must fail
                    rc, _, err = self.compile(srcs[0], srcs[1:], flags, 'xx_' + os.path.basename(srcs[0]) + '.exe', tmp, env)
                    if rc == 0:
                        return 'FAIL', f"compile of {srcs[0]} succeeded; GnuCOBOL rejects it"
                    checks += 1
                    continue
                if verb == '$COMPILE_MODULE':
                    modules.extend(srcs)
                    continue
                if verb == '$COMPILE_ONLY':
                    rc, _, err = run([YACCC, '-C', '-o', os.path.join(tmp, 'xx.c')] + srcs + flags, tmp)
                    if rc != 0 and not self.use_cobc:
                        return 'CERR', err.decode('latin-1', 'replace').strip()[-300:]
                    continue
                main = srcs[0]
                out = out_name or os.path.splitext(os.path.basename(main))[0]
                built[out] = (srcs[0], srcs[1:] + modules, flags)
                if os.path.exists(os.path.join(tmp, out)):
                    os.remove(os.path.join(tmp, out))      # recompiled: rebuild before the next run
                continue
            if verb in ('cat', 'diff') and len(words) == (2 if verb == 'cat' else 3):
                try:
                    texts = [open(os.path.join(tmp, w), 'rb').read().decode('latin-1') for w in words[1:]]
                except OSError:
                    texts = None
                rc = 2 if texts is None else 0 if verb == 'cat' or texts[0] == texts[1] else 1
                want_rc = int(status) if status.isdigit() else None
                if want_rc is not None and rc != want_rc:
                    return 'FAIL', f"{cmd}: exit status {rc}, expected {want_rc}"
                if verb == 'cat' and texts is not None:
                    if want_out in ('expout',):
                        want_out = files.get(want_out, '')
                    if want_out not in ('ignore', 'stdout', 'ignore-no-diff') and texts[0] != want_out:
                        return 'FAIL', f"{cmd}:\n" + diff_text(want_out, texts[0], b'')
                checks += 1
                continue
            if verb.startswith('./') and verb[2:] in built:
                words.insert(0, '$COBCRUN_DIRECT')     # a program built by an earlier step
                verb = words[0]
            if verb in ('$COBCRUN_DIRECT', '$COBCRUN'):
                if len(words) < 2:
                    return 'SKIP', 'shell command'
                prog = words[1]
                if verb == '$COBCRUN':
                    target = prog
                else:
                    target = prog[2:] if prog.startswith('./') else prog
                if target not in built:
                    src = None
                    for m in modules + module_srcs:
                        if os.path.splitext(os.path.basename(m))[0] == target:
                            src = m
                    if src is None:
                        return 'SKIP', f'runs {prog}, not built from COBOL here'
                    built[target] = (src, [m for m in modules if m != src], [])
                exe = os.path.join(tmp, target)
                # build every program compiled so far: one may run another with CALL "SYSTEM"
                for name, (srcm, mods, flags) in built.items():
                    path = os.path.join(tmp, name)
                    if os.path.exists(path):
                        continue
                    rc, _, err = self.compile(srcm, mods + [m for m in modules if m not in mods and m != srcm],
                                              flags, path, tmp, env)
                    if rc != 0:
                        return build_failure(err)
                fin = open(os.path.join(tmp, stdin_file), 'rb') if stdin_file else None
                try:
                    rc, out, err = run([exe] + words[2:], tmp, env=env, stdin=fin)
                finally:
                    if fin:
                        fin.close()
                if rc == -999:
                    return 'XERR', 'timeout'
                want_rc = int(status) if status.isdigit() else None
                if want_out in ('expout', 'experr'):
                    want_out = files.get(want_out, '')
                if want_out in ('ignore', 'stdout', 'ignore-no-diff') or status == 'ignore':
                    pass
                elif out.decode('latin-1') != want_out:
                    return 'FAIL', diff_text(want_out, out.decode('latin-1'), err)
                if want_rc is not None and rc != want_rc:
                    return 'FAIL', f"exit status {rc}, expected {want_rc}\n{err.decode('latin-1', 'replace')[-300:]}"
                checks += 1
                continue
            return 'SKIP', f'command {verb}'
        if checks == 0:
            return 'SKIP', 'nothing run'
        return 'PASS', ''


def build_failure(err):
    """CERR, unless the test's C code uses GnuCOBOL's own C interface,
    which this runtime does not provide (a test of libcob, not of COBOL)."""
    msg = err.decode('latin-1', 'replace')
    m = re.search(r"undefined reference to `(cob_\w+)'", msg, re.ASCII)
    if m:
        return 'SKIP', f"uses GnuCOBOL's C API ({m.group(1)})"
    m = re.search(r"(unknown type name|implicit declaration of function)\W+(cob_\w+)", msg, re.ASCII)
    if m:
        return 'SKIP', f"uses GnuCOBOL's C API ({m.group(2)})"
    if 'libcob.h' in msg or 'libcob/' in msg:
        return 'SKIP', "uses GnuCOBOL's C API (its headers)"
    return 'CERR', msg.strip()[-400:]


def diff_text(want, got, err):
    import difflib
    d = list(difflib.unified_diff(want.splitlines(), got.splitlines(), 'expected', 'yaccc', lineterm='', n=1))
    s = '\n'.join(d[:40])
    if err:
        s += '\nstderr: ' + err.decode('latin-1', 'replace')[-300:]
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('suite')
    ap.add_argument('files', nargs='*')
    ap.add_argument('--cobc', action='store_true', help='run with GnuCOBOL cobc instead of yaccc')
    ap.add_argument('-k', dest='pattern', help='only tests whose title contains this text')
    ap.add_argument('-v', action='store_true', help='print every test')
    ap.add_argument('--keep', action='store_true', help='keep each test directory and print its path')
    ap.add_argument('--static-modules', action='store_true',
                    help='link $COMPILE_MODULE sources into each executable instead of '
                         'building loadable modules')
    ap.add_argument('--log', help='write failure details to this file')
    ap.add_argument('--xfail', action='store_true',
                    help='also run the tests GnuCOBOL marks as expected to fail (AT_XFAIL_IF), '
                         'which are otherwise skipped')
    ap.add_argument('--expect', help='results file written by -v (tests/gnucobol/results.txt): '
                    'report only the tests whose result changed, and fail if a passing test no longer passes')
    ap.add_argument('-j', '--jobs', type=int, default=0,
                    help='run this many tests at once (default: CPU count, capped at 16). '
                         'Each test builds and runs in its own directory, so they are independent')
    a = ap.parse_args()
    files = a.files or sorted(f for f in os.listdir(a.suite) if f.startswith(('run_', 'data_')) and f.endswith('.at'))
    want = {}
    if a.expect:
        for line in open(a.expect):
            parts = line.split()
            if len(parts) >= 2 and parts[0] in STATUSES:
                want[parts[1]] = parts[0]
    jobs = a.jobs or min(os.cpu_count() or 1, 16)
    # collect first, so the work can be handed out in one go and reported in a
    # stable order whatever order it finishes in
    todo = []
    for fn in files:
        path = fn if os.path.isabs(fn) else os.path.join(a.suite, fn)
        for t in parse_file(path):
            if a.pattern and a.pattern.lower() not in t.title.lower():
                continue
            if a.xfail and t.skip_reason == 'expected failure in GnuCOBOL':
                t.skip_reason = None
            todo.append(t)

    def work(t):
        # a Runner per test: its state is per-test and this keeps it thread-safe
        return Runner(a.cobc, a.keep, a.static_modules).run_test(t)

    counts = {}
    changed = []
    log = open(a.log, 'w') if a.log else None
    from concurrent.futures import ThreadPoolExecutor
    if jobs > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(work, todo))
    else:
        results = [work(t) for t in todo]
    for t, (res, info) in zip(todo, results):
            key = f"{os.path.basename(t.path)}:{t.line}"
            counts[res] = counts.get(res, 0) + 1
            if a.expect:
                if want.get(key) != res:
                    changed.append((key, want.get(key), res))
                    print(f"{res:5} {key:28} {t.title}   (was {want.get(key) or 'not run'})")
                    if res != 'PASS' and info:
                        print('      ' + info.replace('\n', '\n      '))
            elif a.v or res in ('FAIL', 'CERR', 'XERR'):
                print(f"{res:5} {key:28} {t.title}")
            if log and res != 'PASS':
                log.write(f"==== {res} {key} {t.title}\n{info}\n\n")
    print()
    print('  '.join(f"{k} {counts.get(k, 0)}" for k in STATUSES))
    if a.expect:
        lost = [k for k, w, r in changed if w == 'PASS']
        print(f"{len(changed)} changed, {len(lost)} no longer passing")
        return 1 if lost else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
