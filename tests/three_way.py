#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Three-way differential: YACCC against two independent COBOL compilers.

YACCC's compatibility target is GnuCOBOL, and much of its behaviour was
established by running `cobc` and matching what it does. That leaves a blind
spot: where YACCC and GnuCOBOL agree but an independent implementation of the
same standard disagrees, it is impossible to tell whether the standard was
matched or a GnuCOBOL quirk was copied.

This runs each program through all three and reports the shapes of
disagreement. It is a development tool, not part of CI: it needs `cobc`
(GnuCOBOL 3.1.2) and `gcobol` (GCC's COBOL front end) on PATH, or named by
$COBC and $GCOBOL.

    python3 tests/three_way.py                 # tests/cases
    python3 tests/three_way.py --dir DIR       # any directory of .cbl
    python3 tests/three_way.py --only NAME     # one program

The report groups every program into one of four outcomes:

    all agree            nothing to see
    yaccc ~ cobc, gcobol differs      the case worth looking at
    yaccc ~ gcobol, cobc differs      a GnuCOBOL quirk YACCC does not copy
    no majority          all three disagree, or one refuses the program

Exit status is 0 always: this is a survey, not a gate.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')


def compilers():
    return {
        'yaccc': os.environ.get('YACCC', YACCC),
        'cobc': os.environ.get('COBC') or shutil.which('cobc'),
        'gcobol': os.environ.get('GCOBOL') or shutil.which('gcobol'),
    }


def flags_for(src, kind):
    """A case's .flags sidecar: plain words go to yaccc, `@ref:` words to the
    reference compilers, which is the convention tests/difftest.py uses."""
    base = os.path.splitext(src)[0]
    if not os.path.exists(base + '.flags'):
        return []
    words = open(base + '.flags').read().split()
    if kind == 'yaccc':
        return [w for w in words if not w.startswith('@ref:')]
    return [w[5:] for w in words if w.startswith('@ref:')]


def compiles(cc, src, cwd, kind):
    """Compile to an executable; return (exe, message)."""
    exe = os.path.join(cwd, 'p_' + os.path.basename(cc).replace('.', '_'))
    extra = flags_for(src, kind)
    if kind == 'yaccc':
        cmd = [cc, src, '-o', exe, '-I', os.path.join(ROOT, 'tests', 'cases')] + extra
    elif kind == 'gcobol':
        cmd = [cc, src, '-o', exe] + extra
    else:
        cmd = [cc, '-x', '-o', exe, src] + extra
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=180)
    if r.returncode != 0:
        err = (r.stderr or r.stdout).decode('latin-1', 'replace').strip()
        return None, err.splitlines()[0][:110] if err else 'failed'
    return exe, ''


def run(exe, cwd, args=(), stdin=None):
    """Return ((exit code, stdout), msg). A non-zero exit is a result, not a
    failure: several cases test error handling and finish with one."""
    try:
        r = subprocess.run([exe, *args], cwd=cwd, capture_output=True,
                           timeout=30, input=stdin)
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    return (r.returncode, r.stdout), ''


def sidecars(src):
    """The .in, .args and .env files a case may carry."""
    base = os.path.splitext(src)[0]
    stdin = None
    if os.path.exists(base + '.in'):
        stdin = open(base + '.in', 'rb').read()
    args = []
    if os.path.exists(base + '.args'):
        args = open(base + '.args', encoding='latin-1').read().split()
    env = {}
    if os.path.exists(base + '.env'):
        for line in open(base + '.env', encoding='latin-1'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip()
    return stdin, args, env


def normalise(out):
    """Compare printed output, ignoring trailing spaces and CRLF."""
    if out is None:
        return None
    text = out.decode('latin-1', 'replace')
    return '\n'.join(l.rstrip() for l in text.replace('\r\n', '\n').split('\n')).strip()


def payload(src):
    """The files a case expects to find beside it: a .data directory, and the
    other sidecars difftest knows about."""
    base = os.path.splitext(src)[0]
    datadir = base + '.data'
    return datadir if os.path.isdir(datadir) else None


def try_one(src):
    """Return {compiler: ('ok', text) | ('refused', msg) | ('crashed', msg)}."""
    stdin, args, env = sidecars(src)
    saved = dict(os.environ)
    os.environ.update(env)
    try:
        result = {}
        for name, cc in compilers().items():
            d = tempfile.mkdtemp(prefix='3w_')
            try:
                exe, msg = compiles(cc, os.path.abspath(src), d, name)
                if exe is None:
                    result[name] = ('refused', msg)
                    continue
                # run in an empty directory holding only the case's own data,
                # so a program that writes files beside itself cannot touch the
                # checkout
                rundir = os.path.join(d, 'run')
                os.makedirs(rundir)
                data = payload(src)
                if data:
                    for f in os.listdir(data):
                        shutil.copy(os.path.join(data, f), rundir)
                got, msg = run(exe, rundir, args, stdin)
                if got is None:
                    result[name] = ('crashed', msg)
                else:
                    rc, out = got
                    # the exit code is part of the observable behaviour
                    result[name] = ('ok', 'exit %d\n%s' % (rc, normalise(out)))
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return result
    finally:
        os.environ.clear()
        os.environ.update(saved)


def has_reference(src):
    """A .noref marker says GnuCOBOL 3.1.2 has no equivalent of whatever the
    program exercises, so its output is not a reference to compare against --
    the same convention tests/difftest.py uses."""
    return not os.path.exists(os.path.splitext(src)[0] + '.noref')


def classify(result):
    names = list(result)
    if any(result[n][0] != 'ok' for n in names):
        return 'incomplete', result
    texts = {n: result[n][1] for n in names}
    if len(set(texts.values())) == 1:
        return 'all agree', result
    y, c, g = texts['yaccc'], texts['cobc'], texts['gcobol']
    if y == c:
        return 'yaccc=cobc, gcobol differs', result
    if y == g:
        return 'yaccc=gcobol, cobc differs', result
    if c == g:
        return 'cobc=gcobol, yaccc differs', result
    return 'all differ', result


def firstdiff(a, b):
    """First differing line, for the report."""
    la, lb = a.split('\n'), b.split('\n')
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else '<end>'
        y = lb[i] if i < len(lb) else '<end>'
        if x != y:
            return f'line {i + 1}: {x[:44]!r} vs {y[:44]!r}'
    return 'identical after trim'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(ROOT, 'tests', 'cases'))
    ap.add_argument('--only', action='append', default=[])
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()

    have = compilers()
    missing = [n for n, p in have.items() if not p]
    if missing:
        print('missing compiler(s): ' + ', '.join(missing))
        print('set YACCC / COBC / GCOBOL, or put them on PATH')
        return 2

    srcs = sorted(f for f in os.listdir(a.dir) if f.endswith('.cbl'))
    if a.only:
        srcs = [f for f in srcs if any(o in f for o in a.only)]

    buckets = {}
    for f in srcs:
        res = try_one(os.path.join(a.dir, f))
        kind, _ = classify(res)
        if not has_reference(os.path.join(a.dir, f)):
            kind = 'no GnuCOBOL reference (.noref)'
        buckets.setdefault(kind, []).append((f, res))
        if a.verbose:
            print(f'  {kind:28s} {f}')

    # why a program is incomplete, grouped by compiler and first error line
    if 'incomplete' in buckets:
        reasons = {}
        for f, res in buckets['incomplete']:
            bad = [n for n in res if res[n][0] != 'ok']
            for n in bad:
                reasons.setdefault((n, res[n][0]), []).append(f)
        print('\nwhy the incomplete ones are incomplete:')
        for (name, state), files in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
            print(f'  {len(files):3d}  {name} {state}')

    print(f'\n{len(srcs)} programs through yaccc, cobc and gcobol\n')
    for kind in ('all agree', 'yaccc=cobc, gcobol differs',
                 'yaccc=gcobol, cobc differs', 'cobc=gcobol, yaccc differs',
                 'all differ', 'incomplete', 'no GnuCOBOL reference (.noref)'):
        items = buckets.get(kind, [])
        if not items:
            continue
        print(f'{len(items):4d}  {kind}')
        for f, res in items[:6 if kind != 'all agree' else 2]:
            if kind == 'all agree':
                print(f'        {f}')
                continue
            for n in ('yaccc', 'cobc', 'gcobol'):
                st, val = res[n]
                if st == 'ok':
                    print(f'        {n:7s} ok')
                else:
                    print(f'        {n:7s} {st}: {val}')
            if all(res[n][0] == 'ok' for n in res):
                base = res['yaccc'][1]
                for n in ('cobc', 'gcobol'):
                    if res[n][1] != base:
                        print(f'        yaccc vs {n}: {firstdiff(base, res[n][1])}')
            print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
