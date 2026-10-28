#!/usr/bin/env python3
"""Differential tester: compiles each COBOL test with cobolc and (if available)
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
COBOLC = os.path.join(ROOT, 'cobolc')


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
            print(f"FILE {name}: '{fn}' not created by cobolc")
            extra += b'<missing file ' + fn.encode() + b'>'
        elif open(rp, 'rb').read() != open(mp, 'rb').read():
            print(f"FILE {name}: '{fn}' differs")
            rd = open(rp, 'rb').read().decode('latin-1').splitlines()
            md = open(mp, 'rb').read().decode('latin-1').splitlines()
            for i, line in enumerate(difflib.unified_diff(rd, md, 'expected/' + fn, 'cobolc/' + fn,
                                                          lineterm='', n=1)):
                if i > 30:
                    break
                print('   ' + repr(line))
            extra += b'<file differs ' + fn.encode() + b'>'
    return extra


def main():
    ap = argparse.ArgumentParser(
        description="Run the test programs with cobolc and compare their output with GnuCOBOL "
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
        rc, out, err = run([COBOLC, t, '-o', exe] + [x for x in extra if not x.startswith('@ref:')])
        if rc != 0:
            print(f"FAIL {name}: cobolc compile error\n{err.decode(errors='replace')}")
            failed += 1
            continue
        mrc, mout, merr = run([exe], stdin, cwd=mine_dir, env=env)
        exp_path = base + '.expected'
        out_dir = base + '.outfiles'
        expected = open(exp_path, 'rb').read() if os.path.exists(exp_path) else None
        noref = os.path.exists(base + '.noref')   # deliberate deviation from GnuCOBOL
        if not noref and (args.ref or (args.update and expected is None)):
            rexe = os.path.join(ref_dir, name)
            rflags = [x[5:] for x in extra if x.startswith('@ref:')]
            rc, out, err = run(['cobc', '-x', '-fbinary-size=2-4-8', '-o', rexe, t] + rflags)
            if rc != 0:
                print(f"SKIP {name}: reference compile error\n{err.decode(errors='replace')}")
                continue
            rrc, rout, rerr = run([rexe], stdin, cwd=ref_dir, env=env)
            written = [f for f in os.listdir(ref_dir) if f != name and os.path.isfile(os.path.join(ref_dir, f))]
            if args.update and expected is None:
                open(exp_path, 'wb').write(rout)
                cmp_files = [f for f in written if f not in nocmp]
                if cmp_files:
                    os.makedirs(out_dir, exist_ok=True)
                    for f in cmp_files:
                        shutil.copy(os.path.join(ref_dir, f), os.path.join(out_dir, f))
                print(f"REC  {name}: baseline recorded")
            if expected is None:
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
                                     'expected', 'cobolc', lineterm='', n=1)
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
