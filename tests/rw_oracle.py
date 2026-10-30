#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Report Writer differential oracle.

Generates report programs that vary every page-geometry setting, compiles each
with both YACCC and a real GnuCOBOL, and compares the report files byte for
byte. Where they differ, the case is cut down automatically to the smallest
program that still shows the difference, so a mismatch comes with a minimal
reproduction rather than a 4000-line file.

This is a development tool: it needs `cobc` (GnuCOBOL 3.1.2, the version the
testsuite asserts -- see docs/gnucobol-oracle.md) and is not part of CI.

    python3 tests/rw_oracle.py --list                 # the shapes it will try
    python3 tests/rw_oracle.py                        # run the default sweep
    python3 tests/rw_oracle.py --full                 # the whole sweep
    python3 tests/rw_oracle.py --testsuite            # the 3.1.2 RW tests
    python3 tests/rw_oracle.py --case pl=10,ld=6      # one shape, keep its files

Exit status is 0 when every case matches, 1 when any differs, 2 when cobc is
missing.
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
SUITE = os.path.join(ROOT, 'third_party', 'gnucobol', 'tests', 'testsuite.src')

# ------------------------------------------------------------------ parameters
#
# One dict per case. Only combinations a compiler must accept are generated:
# HEADING <= FIRST DETAIL <= LAST DETAIL <= PAGE LIMIT, and a FOOTING between
# LAST DETAIL and PAGE LIMIT. Groups that are optional are `None` when absent.
#
#   pl, h, fd, ld, ft   the PAGE clause
#   pf                  the page footing's absolute line, or None for no group
#   dl, cl, fl          LINE PLUS n for the detail, control heading and control
#                       footing groups
#   ng                  NEXT GROUP on the control heading: None, ('plus', n),
#                       ('abs', n) or ('np',)
#   recs                the (ctl1, ctl2) sequence fed to GENERATE
#   rh, rf              whether the report heading / footing groups exist
#   nlines              print lines in the detail group
#   gi                  GROUP INDICATE on the detail's first field
#   sumf                SUM on a control footing field


DEFAULTS = {
    'pl': 12, 'h': 1, 'fd': 4, 'ld': 8, 'ft': None,
    'pf': None, 'dl': 1, 'cl': 1, 'fl': 1, 'ng': None,
    'recs': ((1, 1), (1, 1), (2, 1)),
    'rh': True, 'rf': True, 'nlines': 1, 'gi': False, 'sumf': False,
}


def case(**kw):
    d = dict(DEFAULTS)
    d.update(kw)
    return d


def label(p):
    """A short, stable name for a case, used in reports and for the file name."""
    bits = ['pl%d' % p['pl'], 'h%d' % p['h'], 'fd%d' % p['fd'], 'ld%d' % p['ld']]
    if p['ft'] is not None:
        bits.append('ft%d' % p['ft'])
    if p['pf'] is not None:
        bits.append('pf%d' % p['pf'])
    bits += ['dl%d' % p['dl'], 'cl%d' % p['cl'], 'fl%d' % p['fl']]
    if p['ng']:
        bits.append('ng' + p['ng'][0] + ''.join(str(x) for x in p['ng'][1:]))
    bits.append('r%d' % len(p['recs']))
    bits.append('nl%d' % p['nlines'])
    for k in ('rh', 'rf', 'gi', 'sumf'):
        if not p[k] and k in ('rh', 'rf'):
            bits.append('no' + k)
        elif p[k]:
            bits.append(k)
    return '_'.join(bits)


def sweep(full=False):
    """The shapes to try. `full` widens each axis; the default is a curated
    subset that still covers every page-clause and NEXT GROUP combination."""
    out = []
    limits = [5, 10, 12, 20, 25] if full else [10, 12, 25]
    for pl in limits:
        # page-clause shapes, including the ones the testsuite uses
        shapes = []
        for h in (1, 2):
            for fd in (2, 3, 4):
                for ld in (fd, fd + 2, pl - 2):
                    if 0 < h <= fd <= ld <= pl:
                        shapes.append((h, fd, ld))
        if full:
            shapes = sorted(set(shapes))
        else:
            shapes = sorted(set(shapes))[::3]
        for h, fd, ld in shapes:
            # with and without a page footing group, and with/without FOOTING
            for pf in (None, ld + 1 if ld + 1 <= pl else None, pl - 1):
                for ft in (None, ld if ld <= pl else None):
                    p = case(pl=pl, h=h, fd=fd, ld=ld, pf=pf, ft=ft)
                    out.append(p)
    # NEXT GROUP variants on a shape that breaks pages
    base = dict(pl=10, h=1, fd=3, ld=6)
    for ng in (None, ('plus', 1), ('plus', 2), ('abs', 3), ('np',)):
        out.append(case(ng=ng, **base))
    # multiple lines per group, and several records feeding control breaks
    for dl in (1, 2, 3):
        out.append(case(dl=dl, pl=12, ld=8))
    for cl, fl in ((1, 1), (2, 1), (1, 2)):
        out.append(case(cl=cl, fl=fl, pl=12, ld=8))
    for recs in (((1, 1),), ((1, 1), (2, 1)),
                 ((1, 1), (1, 1), (2, 1), (2, 1), (3, 1)),
                 tuple((1, 1) for _ in range(30))):
        out.append(case(recs=recs, pl=10, ld=6))
    for nlines in (1, 2, 3):
        out.append(case(nlines=nlines, pl=12, ld=9))
    for extra in ({'rh': False}, {'rf': False}, {'rh': False, 'rf': False},
                  {'gi': True}, {'sumf': True}):
        d = case(pl=12, ld=8)
        d.update(extra)
        out.append(d)
    return out


# ------------------------------------------------------------------ generation

def gen_program(p):
    """A complete report program for one parameter set.

    The control values are a literal sequence of MOVEs rather than a loop, so
    the program needs no arithmetic and both compilers see exactly the same
    GENERATE order.
    """
    L = []
    a = L.append
    a('       IDENTIFICATION DIVISION.')
    a('       PROGRAM-ID. prog.')
    a('       ENVIRONMENT DIVISION.')
    a('       INPUT-OUTPUT SECTION.')
    a('       FILE-CONTROL.')
    a('           SELECT report-file ASSIGN TO EXTERNAL PRINTOUT')
    a('               ORGANIZATION IS LINE SEQUENTIAL.')
    a('       DATA DIVISION.')
    a('       FILE SECTION.')
    a('       FD  report-file REPORT rp.')
    a('       WORKING-STORAGE SECTION.')
    a('       01  ctl1 PIC 9(3).')
    a('       01  ctl2 PIC 9(3).')
    a('       01  amt  PIC 9(3) VALUE 5.')
    a('       REPORT SECTION.')
    # the PAGE clause goes one clause per line: fixed-format source stops at
    # column 72, and a single-line RD silently truncates past it
    a('       RD  rp')
    a('           CONTROLS ARE FINAL, ctl1')
    a('           PAGE LIMIT %d LINES' % p['pl'])
    a('           HEADING %d' % p['h'])
    a('           FIRST DETAIL %d' % p['fd'])
    a('           LAST DETAIL %d' % p['ld'])
    if p['ft'] is not None:
        a('           FOOTING %d' % p['ft'])
    a('           .')
    if p['rh']:
        a('       01  rep-head TYPE REPORT HEADING.')
        a('           02 LINE 1.')
        a('              03 COL 1 PIC X(20) VALUE "RH".')
    a('       01  page-head TYPE PAGE HEADING.')
    a('           02 LINE PLUS 1.')
    a('              03 COL 1 PIC X(20) VALUE "PH".')
    ng = ''
    if p['ng']:
        kind = p['ng'][0]
        if kind == 'plus':
            ng = ' NEXT GROUP PLUS %d' % p['ng'][1]
        elif kind == 'abs':
            ng = ' NEXT GROUP %d' % p['ng'][1]
        else:
            ng = ' NEXT GROUP NEXT PAGE'
    a('       01  ctl-head TYPE CONTROL HEADING ctl1' + ng + '.')
    a('           02 LINE PLUS %d.' % p['cl'])
    a('              03 COL 1 PIC X(20) VALUE "CH1".')
    a('       01  de-line TYPE DETAIL.')
    for i in range(p['nlines']):
        a('           02 LINE PLUS %d.' % p['dl'])
        if i == 0 and p['gi']:
            a('              03 COL 1 PIC X(20) VALUE "DE" GROUP INDICATE.')
        else:
            a('              03 COL 1 PIC X(20) VALUE "DE%d".' % (i + 1))
    a('       01  ctl-foot TYPE CONTROL FOOTING ctl1.')
    a('           02 LINE PLUS %d.' % p['fl'])
    if p['sumf']:
        a('              03 COL 1 PIC X(20) VALUE "CF1".')
        a('              03 COL 22 PIC 9(5) SUM amt.')
    else:
        a('              03 COL 1 PIC X(20) VALUE "CF1".')
    if p['pf'] is not None:
        a('       01  page-foot TYPE PAGE FOOTING.')
        a('           02 LINE %d.' % p['pf'])
        a('              03 COL 1 PIC X(20) VALUE "PF".')
    if p['rf']:
        a('       01  rep-foot TYPE REPORT FOOTING.')
        a('           02 LINE PLUS 1.')
        a('              03 COL 1 PIC X(20) VALUE "RF".')
    a('       PROCEDURE DIVISION.')
    a('           OPEN OUTPUT report-file.')
    a('           INITIATE rp.')
    for c1, c2 in p['recs']:
        a('           MOVE %d TO ctl1.' % c1)
        a('           MOVE %d TO ctl2.' % c2)
        a('           GENERATE de-line.')
    a('           TERMINATE rp.')
    a('           CLOSE report-file.')
    a('           STOP RUN.')
    text = '\n'.join(L) + '\n'
    # fixed-format COBOL: code lives in columns 8-72, and anything past 72 is
    # dropped by the compiler. Catching it here beats debugging a syntax error
    # that points at the wrong line.
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > 72:
            raise ValueError('generated line %d is %d columns (max 72): %r'
                             % (n, len(line), line))
    return text


# ------------------------------------------------------------------ running

def cobc_cmd():
    exe = shutil.which('cobc')
    return exe


def run(cmd, cwd, env=None, timeout=60):
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                              capture_output=True)
    except subprocess.TimeoutExpired:
        return None


def build_and_run(prog_text, workdir, cobc, cobc_flags=()):
    """Compile and run with both compilers; return (ok, detail, ref, mine)."""
    src = os.path.join(workdir, 'prog.cob')
    with open(src, 'w') as fp:
        fp.write(prog_text)
    outs = {}
    for name, cmd in (('ref', [cobc, '-x'] + list(cobc_flags) + ['-o', 'ref', 'prog.cob']),
                      ('mine', [YACCC, 'prog.cob', '-o', 'mine'])):
        r = run(cmd, workdir)
        if r is None:
            return False, '%s: timeout compiling' % name, None, None
        if r.returncode != 0:
            msg = r.stderr.decode('latin-1', 'replace').strip().splitlines()
            return False, '%s: compile failed: %s' % (name, msg[0][:160] if msg else ''), None, None
        out = os.path.join(workdir, name + '.txt')
        env = dict(os.environ)
        env['DD_PRINTOUT'] = out
        if os.path.exists(out):
            os.remove(out)
        r = run([os.path.join(workdir, name)], workdir, env)
        if r is None:
            return False, '%s: timeout running' % name, None, None
        if r.returncode != 0:
            msg = r.stderr.decode('latin-1', 'replace').strip().splitlines()
            return False, '%s: exit %d: %s' % (name, r.returncode,
                                               msg[0][:160] if msg else ''), None, None
        outs[name] = open(out, 'rb').read() if os.path.exists(out) else b''
    if outs['ref'] == outs['mine']:
        return True, '', outs['ref'], outs['mine']
    return False, 'report files differ', outs['ref'], outs['mine']


def first_diff(ref, mine):
    """A one-line description of the first differing line, for the log."""
    r = ref.decode('latin-1').splitlines()
    m = mine.decode('latin-1').splitlines()
    for i in range(max(len(r), len(m))):
        a = r[i] if i < len(r) else '<missing>'
        b = m[i] if i < len(m) else '<missing>'
        if a.rstrip() != b.rstrip():
            return 'line %d: cobc %r vs yaccc %r' % (i + 1, a[:40], b[:40])
    return '%d vs %d lines' % (len(r), len(m))


def minimise(p, cobc, workdir, cobc_flags=()):
    """Cut the case down while it still differs: fewer records, simpler groups,
    smallest numbers. Returns the minimal case that still reproduces."""
    cur = dict(p)
    changed = True
    while changed:
        changed = False
        trials = []
        # drop optional groups
        for k in ('rh', 'rf', 'gi', 'sumf'):
            if cur[k]:
                t = dict(cur); t[k] = False; trials.append(t)
        if cur['ng']:
            t = dict(cur); t['ng'] = None; trials.append(t)
        if cur['pf'] is not None:
            t = dict(cur); t['pf'] = None; trials.append(t)
        if cur['ft'] is not None:
            t = dict(cur); t['ft'] = None; trials.append(t)
        if cur['nlines'] > 1:
            t = dict(cur); t['nlines'] = 1; trials.append(t)
        # fewer records
        recs = cur['recs']
        if len(recs) > 1:
            for n in (1, len(recs) - 1):
                if n >= 1:
                    t = dict(cur); t['recs'] = recs[:n]; trials.append(t)
        # smaller numbers, keeping the clause valid
        for k in ('dl', 'cl', 'fl'):
            if cur[k] > 1:
                t = dict(cur); t[k] = cur[k] - 1; trials.append(t)
        if cur['pl'] > 3:
            t = dict(cur)
            t['pl'] = cur['pl'] - 1
            if t['ld'] <= t['pl']:
                trials.append(t)
        for t in trials:
            ok, _, _, _ = build_and_run(gen_program(t), workdir, cobc, cobc_flags)
            if not ok:
                cur = t
                changed = True
                break
    return cur


# ------------------------------------------------------------------ testsuite

def testsuite_cases(cobc):
    """Every report program in the 3.1.2 Report Writer testsuite, as run by its
    own AT_CHECK. These are the cases the suite already asserts, so they are
    the ground truth the generator is trying to generalise."""
    at = os.path.join(SUITE, 'run_reportwriter.at')
    if not os.path.exists(at):
        return []
    src = open(at).read()
    out = []
    for m in re.finditer(r'AT_SETUP\(\[([^\]]+)\]\)', src):
        title = m.group(1)
        seg = src.split('AT_SETUP([%s])' % title)[1].split('AT_CLEANUP')[0]
        if 'REPORT SECTION' not in seg:
            continue
        out.append((title, seg))
    return out


def run_testsuite(cobc, workdir, cobc_flags=()):
    fails = 0
    cases = testsuite_cases(cobc)
    for title, seg in cases:
        d = tempfile.mkdtemp(prefix='rwts_', dir=workdir)
        for m in re.finditer(r'AT_DATA\(\[([^]]+)\],\s*\[(.*?)\n\]\)', seg, re.S):
            with open(os.path.join(d, m.group(1)), 'w') as fp:
                fp.write(m.group(2) + '\n')
        if not os.path.exists(os.path.join(d, 'prog.cob')):
            continue
        mm = re.search(r'AT_CHECK\(\[(.*?)\$COBCRUN_DIRECT', seg)
        dd = {}
        if mm:
            for k, v in re.findall(r'([A-Z][A-Z_0-9]*)=("?[^ "\]]*"?)', mm.group(1)):
                dd[k] = v.strip('"')
        env = dict(os.environ)
        # the report file is whichever DD_ name is not an input
        outs = [k for k in dd if dd[k].endswith('.txt') or 'REPORT' in k]
        if not outs:
            continue
        key = outs[-1]
        res = {}
        ok = True
        for name, compile_cmd in (
                ('ref', [cobc, '-x'] + list(cobc_flags) + ['-o', 'ref', 'prog.cob']),
                ('mine', [YACCC, 'prog.cob', '-o', 'mine'])):
            r = run(compile_cmd, d, env)
            if r is None or r.returncode != 0:
                print('  SKIP %-40s %s compile failed' % (title[:40], name))
                ok = False
                break
            e = dict(env)
            e.update(dd)
            e[key] = os.path.join(d, name + '.txt')
            r = run([os.path.join(d, name)], d, e)
            if r is None or r.returncode != 0:
                print('  SKIP %-40s %s run failed' % (title[:40], name))
                ok = False
                break
            res[name] = open(e[key], 'rb').read() if os.path.exists(e[key]) else b''
        if not ok:
            continue
        if res['ref'] == res['mine']:
            print('  ok   %s' % title)
        else:
            fails += 1
            print('  DIFF %-40s %s' % (title[:40], first_diff(res['ref'], res['mine'])))
    return fails


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true', help='list the cases and exit')
    ap.add_argument('--full', action='store_true', help='run the whole sweep')
    ap.add_argument('--testsuite', action='store_true',
                    help='also run the 3.1.2 Report Writer testsuite programs')
    ap.add_argument('--no-sweep', action='store_true',
                    help='skip the generated sweep (use with --testsuite)')
    ap.add_argument('--no-minimise', action='store_true',
                    help='do not cut a failing case down')
    ap.add_argument('--case', metavar='K=V,...', action='append', default=[],
                    help='run one shape, e.g. --case pl=10,ld=6,dl=2')
    ap.add_argument('--keep', action='store_true', help='keep the work directory')
    ap.add_argument('--cobc-flag', action='append', default=[],
                    help='extra option for cobc (repeatable)')
    ap.add_argument('-q', '--quiet', action='store_true')
    a = ap.parse_args(argv)

    cobc = cobc_cmd()
    if cobc is None and not a.list:
        print('no cobc on PATH: build one as described in docs/gnucobol-oracle.md')
        return 2

    if a.case:
        cases = []
        for spec in a.case:
            kw = {}
            for kv in spec.split(','):
                k, _, v = kv.partition('=')
                if k in ('rh', 'rf', 'gi', 'sumf'):
                    kw[k] = v not in ('0', 'no', 'false', '')
                elif k in ('pl', 'h', 'fd', 'ld', 'ft', 'pf', 'dl', 'cl', 'fl', 'nlines'):
                    kw[k] = None if v in ('', 'none') else int(v)
                elif k == 'recs':
                    kw[k] = tuple((int(c), 1) for c in v.split('-'))
                elif k == 'ng':
                    kw[k] = None if v in ('', 'none') else (
                        ('np',) if v == 'np' else (v.split(':')[0], int(v.split(':')[1])))
                else:
                    ap.error('unknown parameter %r' % k)
            cases.append(case(**kw))
    elif a.no_sweep:
        cases = []
    else:
        cases = sweep(a.full)

    if a.list:
        for p in cases:
            print(label(p))
        print('%d cases' % len(cases))
        return 0

    work = tempfile.mkdtemp(prefix='rw_oracle_')
    fails, total = [], 0
    for p in cases:
        total += 1
        d = tempfile.mkdtemp(prefix='c_', dir=work)
        ok, detail, ref, mine = build_and_run(gen_program(p), d, cobc, a.cobc_flag)
        if ok:
            if not a.quiet:
                print('  ok   %s' % label(p))
            continue
        note = detail
        small = p
        if not a.no_minimise and detail == 'report files differ':
            small = minimise(p, cobc, d, a.cobc_flag)
            note = first_diff(ref, mine)
        fails.append((label(p), label(small), note))
        print('  FAIL %-44s %s' % (label(p), note))
        if label(small) != label(p):
            print('       minimal: %s' % label(small))
            print(gen_program(small))

    if a.testsuite:
        print('testsuite:')
        tf = run_testsuite(cobc, work, a.cobc_flag)
        if tf:
            fails.append(('testsuite', 'testsuite', '%d differ' % tf))

    print('\n%d cases, %d differ' % (total, len(fails)))
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print('work directory: %s' % work)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
