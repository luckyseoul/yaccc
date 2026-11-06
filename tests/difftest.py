#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Differential tester: compiles each COBOL test with yaccc and (if available)
GnuCOBOL, runs both and compares output. Tests with an .expected file are
checked against that file instead of (or in addition to) the reference."""
import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')


def run(cmd, stdin=None, cwd=None, timeout=60, env=None):
    """Run with a timeout and a cap on captured output (runaway programs)."""
    import resource

    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 << 20, 50 << 20))
        resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        try:
            r = subprocess.run(cmd, input=stdin, stdout=fo, stderr=fe, cwd=cwd, timeout=timeout,
                               preexec_fn=limits, env=env)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = -999
        fo.seek(0)
        fe.seek(0)
        out = fo.read(20 << 20)
        err = fe.read(1 << 20)
        if rc == -999:
            err += b'TIMEOUT'
        return rc, out, err


def compare_files(name, want_dir, mine_dir, names, nocmp):
    """Compare files the program wrote; returns text appended to the output on mismatch."""
    extra = b''
    for fn in sorted(names):
        if fn == name or fn in nocmp:
            continue
        rp, mp = os.path.join(want_dir, fn), os.path.join(mine_dir, fn)
        if not os.path.isfile(rp):
            continue
        if not os.path.exists(mp):
            print(f"FILE {name}: '{fn}' not created by yaccc")
            extra += b'<missing file ' + fn.encode() + b'>'
        elif open(rp, 'rb').read() != open(mp, 'rb').read():
            print(f"FILE {name}: '{fn}' differs")
            rd = open(rp, 'rb').read().decode('latin-1').splitlines()
            md = open(mp, 'rb').read().decode('latin-1').splitlines()
            for i, line in enumerate(difflib.unified_diff(rd, md, 'expected/' + fn, 'yaccc/' + fn,
                                                          lineterm='', n=1)):
                if i > 30:
                    break
                print('   ' + repr(line))
            extra += b'<file differs ' + fn.encode() + b'>'
    return extra


# An indexed or relative file needs an ISAM handler, and a cobc built without
# one compiles the program happily and then fails every I/O call with status
# 48. Detect that once, so those cases are reported as skipped rather than as
# YACCC failures.
ISAM_PROBE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ISAMPROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "isamprobe.dat" ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM RECORD KEY IS K.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  R.
           05 K PIC 9(4).
           05 V PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT F
           MOVE 1 TO K MOVE "AAAA" TO V
           WRITE R
           CLOSE F
           DISPLAY "STATUS=" FS
           STOP RUN.
"""


def reference_has_isam(cobc, work):
    """True when this cobc can open an indexed file."""
    d = tempfile.mkdtemp(prefix='isam_', dir=work)
    src = os.path.join(d, 'isamprobe.cbl')
    open(src, 'w').write(ISAM_PROBE)
    exe = os.path.join(d, 'p')
    rc, _out, _err = run([cobc, '-x', '-o', exe, src])
    if rc != 0:
        return False
    _rc, out, _err = run([exe], cwd=d)
    return b'STATUS=00' in out


def uses_isam(path):
    """True when a program declares an indexed or relative file."""
    try:
        text = open(path, encoding='latin-1').read()
    except OSError:
        return False
    return ('ORGANIZATION IS INDEXED' in text or 'ORGANIZATION INDEXED' in text
            or 'ORGANIZATION IS RELATIVE' in text or 'ORGANIZATION RELATIVE' in text)


def main():
    ap = argparse.ArgumentParser(
        description="Run the test programs with yaccc and compare their output with GnuCOBOL "
                    "(--ref) or with the recorded baselines (.expected / .outfiles).")
    ap.add_argument('tests', nargs='*')
    ap.add_argument('--ref', action='store_true', help='compare against GnuCOBOL (cobc) run live')
    ap.add_argument('--update', action='store_true',
                    help='record GnuCOBOL output as baselines for tests that have none')
    ap.add_argument('-v', action='store_true')
    args = ap.parse_args()
    tests = args.tests or sorted(os.path.join(HERE, 'cases', f) for f in os.listdir(os.path.join(HERE, 'cases'))
                                 if f.endswith('.cbl'))
    have_ref = shutil.which('cobc') is not None
    if (args.ref or args.update) and not have_ref:
        print("cobc (GnuCOBOL) not found; --ref/--update need it")
        return 2
    work = tempfile.mkdtemp(prefix='cobtest_')
    ref_isam = None
    passed = failed = 0
    for t in tests:
        base = os.path.splitext(t)[0]
        name = os.path.basename(base)
        stdin = open(base + '.in', 'rb').read() if os.path.exists(base + '.in') else b''
        extra = open(base + '.flags').read().split() if os.path.exists(base + '.flags') else []
        nocmp = set(open(base + '.nocmp').read().split()) if os.path.exists(base + '.nocmp') else set()
        env = dict(os.environ)
        env.pop('COB_SET_DEBUG', None)
        if os.path.exists(base + '.env'):       # NAME=value lines for both runs
            for line in open(base + '.env').read().splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
        tdir = os.path.join(work, name)
        mine_dir = os.path.join(tdir, 'mine')
        ref_dir = os.path.join(tdir, 'ref')
        os.makedirs(mine_dir)
        os.makedirs(ref_dir)
        datadir = base + '.data'
        for d in (mine_dir, ref_dir):
            if os.path.isdir(datadir):
                for f in os.listdir(datadir):
                    shutil.copy(os.path.join(datadir, f), d)
        exe = os.path.join(mine_dir, name)
        rc, out, err = run([YACCC, t, '-o', exe] + [x for x in extra if not x.startswith('@ref:')])
        if rc != 0:
            print(f"FAIL {name}: yaccc compile error\n{err.decode(errors='replace')}")
            failed += 1
            continue
        # a .args file holds the program's own arguments, one line each, for
        # programs whose behaviour depends on them
        pargs = open(base + '.args', 'rb').read().split() if os.path.exists(base + '.args') else []
        mrc, mout, merr = run([exe] + pargs, stdin, cwd=mine_dir, env=env)
        exp_path = base + '.expected'
        out_dir = base + '.outfiles'
        expected = open(exp_path, 'rb').read() if os.path.exists(exp_path) else None
        noref = os.path.exists(base + '.noref')   # deliberate deviation from GnuCOBOL
        if args.ref and ref_isam is None:
            ref_isam = reference_has_isam('cobc', work)
            if not ref_isam:
                print("note: this cobc has no ISAM handler; indexed and "
                      "relative file cases are skipped")
        if args.ref and not ref_isam and uses_isam(t):
            print(f"SKIP {name}: reference build has no ISAM")
            continue
        if not noref and (args.ref or (args.update and expected is None)):
            rexe = os.path.join(ref_dir, name)
            # copybooks sit next to the test: give cobc the same include path
            # yaccc derives from the source file's own directory
            rflags = [x[5:] for x in extra if x.startswith('@ref:')]
            rc, out, err = run(['cobc', '-x', '-fbinary-size=2-4-8', '-o', rexe, t,
                                '-I', os.path.dirname(os.path.abspath(t))] + rflags)
            if rc != 0:
                print(f"SKIP {name}: reference compile error\n{err.decode(errors='replace')}")
                continue
            rrc, rout, rerr = run([rexe] + pargs, stdin, cwd=ref_dir, env=env)
            written = [f for f in os.listdir(ref_dir) if f != name and os.path.isfile(os.path.join(ref_dir, f))]
            if args.update and expected is None:
                open(exp_path, 'wb').write(rout)
                cmp_files = [f for f in written if f not in nocmp]
                if cmp_files:
                    os.makedirs(out_dir, exist_ok=True)
                    for f in cmp_files:
                        shutil.copy(os.path.join(ref_dir, f), os.path.join(out_dir, f))
                print(f"REC  {name}: baseline recorded")
            if args.ref:
                # compare against what cobc just printed, not against a
                # recording of it: a baseline that drifted from the reference
                # is a test that cannot fail for the right reason
                expected = rout
            elif expected is None:
                expected = rout
            mout += compare_files(name, ref_dir, mine_dir, written, nocmp)
        elif os.path.isdir(out_dir):
            mout += compare_files(name, out_dir, mine_dir, os.listdir(out_dir), nocmp)
        if expected is None:
            print(f"???? {name}: no baseline (run with --update or --ref)")
            continue
        if mout == expected:
            passed += 1
            if args.v:
                print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}: output differs (exit {mrc})")
            if merr:
                print(merr.decode(errors='replace')[:2000])
            d = difflib.unified_diff(expected.decode('latin-1').splitlines(), mout.decode('latin-1').splitlines(),
                                     'expected', 'yaccc', lineterm='', n=1)
            for i, line in enumerate(d):
                if i > 60:
                    print('...')
                    break
                print(line)
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
