#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Runs the NIST CCVS85 COBOL test suite (as split by opensource COBOL's
expand.pl) with yaccc and tallies results like report.pl.

usage: run_nist.py [--all] SUITE_DIR [MODULE ...]
SUITE_DIR is the tests/cobol85 directory containing NC/, SM/, ... and copy/.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
YACCC = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'yaccc')

# Programs the reference GnuCOBOL/opensource COBOL summary does not run.
# All of them compile and run with yaccc; use --all to include them.
REF_SKIP = {'SQ207M', 'SG102A', 'SG103A', 'SG201A', 'SG202A', 'SG203A', 'OBNC1M', 'OBNC2M'}
SKIP = set(os.environ.get('NIST_SKIP', ' '.join(sorted(REF_SKIP))).split())
# Programs that need modules yaccc does not implement (Communication).
UNSUPPORTED = {'DB205A'}
# Debug module programs run with the object-time debugging switch on, except
# DB102A, which checks that debugging procedures stay inactive when it is off.
DEBUG_SWITCH_OFF = {'DB102A'}

PROGID = re.compile(r'^.{6}\s+PROGRAM-ID\.\s*\n?.{0,6}\s*([A-Z0-9-]+)', re.M)
CALLRE = re.compile(r'"([A-Z0-9-]+)"')


def program_id(path):
    txt = open(path, encoding='latin-1').read()
    lines = [l[6:72] if len(l) > 6 else '' for l in txt.split('\n')]
    flat = '\n'.join(lines)
    m = re.search(r'PROGRAM-ID\.\s*([A-Z0-9-]+)', flat)
    return m.group(1) if m else None


def calls(path):
    txt = open(path, encoding='latin-1').read()
    lines = [l[6:72] if len(l) > 6 and l[6:7] not in '*/' else '' for l in txt.split('\n')]
    return set(CALLRE.findall('\n'.join(lines)))


def run_module(suite, module, verbose=False):
    mdir = os.path.join(suite, module)
    if not os.path.isdir(mdir):
        print(f"no module {module}")
        return None
    # subprogram index: program-id -> file
    subs = {}
    for f in glob.glob(os.path.join(mdir, 'lib', '*.CBL')):
        pid = program_id(f)
        if pid:
            subs[pid] = f
    rows = []
    totals = dict(progs=0, ok=0, cerr=0, xerr=0, total=0, passed=0, failed=0, deleted=0, inspect=0)
    for src in sorted(glob.glob(os.path.join(mdir, '*.CBL')) + glob.glob(os.path.join(mdir, '*.SUB'))):
        name = os.path.splitext(os.path.basename(src))[0]
        second_phase = src.endswith('.SUB')
        if name in SKIP or name in UNSUPPORTED or re.match(r'^..[34]0', name):
            rows.append((name, 'skipped'))
            continue
        totals['progs'] += 1
        # collect subprograms transitively
        need = []
        todo = list(calls(src))
        seen = set()
        while todo:
            c = todo.pop()
            if c in seen:
                continue
            seen.add(c)
            if c in subs and subs[c] not in need:
                need.append(subs[c])
                todo.extend(calls(subs[c]))
        exe = os.path.join(mdir, name + '.exe')
        cmd = [YACCC, src] + need + ['-o', exe, '-I', os.path.join(suite, 'copy'), '-O1']
        if name == 'SM206A':
            cmd.append('--debugging-mode')
        r = subprocess.run(cmd, capture_output=True, cwd=mdir)
        if r.returncode != 0:
            totals['cerr'] += 1
            msg = (r.stderr.decode(errors='replace').strip().splitlines() or ['?'])[-1]
            rows.append((name, 'COMPILE ERROR: ' + msg[:150]))
            continue
        if not second_phase:
            for f in glob.glob(os.path.join(mdir, 'XXXXX*')):
                os.remove(f)
        if os.path.exists(os.path.join(mdir, 'report.log')):
            os.remove(os.path.join(mdir, 'report.log'))
        dat = os.path.join(mdir, name + '.DAT')
        stdin = open(dat, 'rb') if os.path.exists(dat) else subprocess.DEVNULL
        env = dict(os.environ, COB_SWITCH_1='ON', COB_SWITCH_2='OFF')
        env.pop('COB_SET_DEBUG', None)
        if module == 'DB' and name not in DEBUG_SWITCH_OFF:
            env['COB_SET_DEBUG'] = 'Y'
        try:
            x = subprocess.run([exe], stdin=stdin, capture_output=True, cwd=mdir, timeout=60, env=env)
            xrc = x.returncode
            xerr = x.stderr.decode(errors='replace').strip()
        except subprocess.TimeoutExpired:
            xrc = -1
            xerr = 'TIMEOUT'
        if xrc != 0:
            totals['xerr'] += 1
            rows.append((name, f'EXECUTE ERROR ({xrc}): {xerr[-200:]}'))
            continue
        total = passed = failed = deleted = inspect = 0
        rl = os.path.join(mdir, 'report.log')
        if os.path.exists(rl):
            for line in open(rl, encoding='latin-1'):
                m = re.match(r'^ *([0-9]+) *OF *([0-9]+) *TESTS WERE', line)
                if m:
                    total += int(m.group(2))
                    passed += int(m.group(1))
                    continue
                m = re.match(r'^ *([0-9NO]+) *TEST\(S\) ([A-Z]+)', line)
                if m:
                    n = 0 if m.group(1) == 'NO' else int(m.group(1))
                    if m.group(2) == 'FAILED':
                        failed += n
                    elif m.group(2) == 'DELETED':
                        deleted += n
                    elif m.group(2) == 'REQUIRE':
                        inspect += n
            shutil.copy(rl, os.path.join(mdir, name + '.log'))
        for k, v in (('total', total), ('passed', passed), ('failed', failed), ('deleted', deleted),
                     ('inspect', inspect)):
            totals[k] += v
        if failed == 0:
            totals['ok'] += 1
        rows.append((name, f"{total:5} {passed:4} {failed:4} {deleted:7} {inspect:7} {'OK' if failed == 0 else 'FAIL'}"))
    return rows, totals


def main():
    global SKIP
    args = sys.argv[1:]
    if '--all' in args:
        args.remove('--all')
        SKIP = set()
    suite = os.path.abspath(args[0])   # programs are compiled from inside each module directory
    mods = args[1:] or ['NC', 'SM', 'IC', 'SQ', 'RL', 'IX', 'ST', 'SG', 'OB', 'IF', 'RW', 'DB']
    grand = dict(progs=0, ok=0, cerr=0, xerr=0, total=0, passed=0, failed=0, deleted=0, inspect=0)
    summary = []
    # Modules are independent of each other -- each compiles and runs inside its
    # own directory -- so they can go at once. Programs *within* a module cannot:
    # the second-phase .SUB tests read the files the first phase wrote, so
    # shuffling them changes what is tested. Verified by comparing the totals
    # of a parallel run against a serial one.
    jobs = int(os.environ.get('NIST_JOBS', '0') or 0) or min(len(mods), os.cpu_count() or 1)
    if jobs > 1 and len(mods) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(lambda m: run_module(suite, m), mods))
    else:
        results = [run_module(suite, m) for m in mods]
    for m, res in zip(mods, results):
        if res is None:
            continue
        rows, t = res
        print(f"===== {m}")
        for name, info in rows:
            if 'OK' not in info or os.environ.get('NIST_VERBOSE'):
                print(f"  {name:10} {info}")
        summary.append((m, t))
        for k in grand:
            grand[k] += t[k]
    print()
    print("Module Programs Executed Error Crash   Pass Fail Deleted Inspect Total")
    print("------ -------- -------- ----- -----  ----- ---- ------- ------- -----")
    for m, t in summary + [('Total', grand)]:
        executed = t['progs'] - t['cerr'] - t['xerr']
        print(f"{m:6} {t['progs']:8} {executed:8} {t['cerr']:5} {t['xerr']:5}  {t['passed']:5} {t['failed']:4} "
              f"{t['deleted']:7} {t['inspect']:7} {t['total']:5}")
    return 1 if grand['failed'] or grand['cerr'] or grand['xerr'] else 0


if __name__ == '__main__':
    sys.exit(main())
