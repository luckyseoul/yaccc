#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of the compiler's own command line.

These are not COBOL semantics tests (tests/difftest.py covers those): they
check that options are honoured, that a misspelt or unsupported option is
reported instead of silently ignored, and that arguments meant for the
program being run reach it and nothing else does.

usage: cli_test.py [-v]
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')

# a program that reports how many arguments it was given, so that a test can
# tell the compiler's own options from the program's
PROG = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLIARG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 9(2).
       PROCEDURE DIVISION.
           DISPLAY "NARGS=" NUMBER-OF-CALL-PARAMETERS.
           STOP RUN.
"""

passed = failed = 0


def run(args, cwd):
    return subprocess.run([YACCC] + args, cwd=cwd, capture_output=True, text=True)


def check(name, res, want_rc, want_in=None, want_not_in=None):
    global passed, failed
    out = res.stdout + res.stderr
    ok = res.returncode == want_rc
    if want_in is not None and want_in not in out:
        ok = False
    if want_not_in is not None and want_not_in in out:
        ok = False
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name}")
        print(f"     exit {res.returncode}, wanted {want_rc}")
        if want_in is not None and want_in not in out:
            print(f"     wanted {want_in!r} in the output")
        if want_not_in is not None and want_not_in in out:
            print(f"     did not want {want_not_in!r} in the output")
        for line in out.splitlines()[:6]:
            print(f"     | {line}")


def main():
    verbose = '-v' in sys.argv[1:]
    work = tempfile.mkdtemp(prefix='yaccli_')
    src = os.path.join(work, 'cliarg.cbl')
    with open(src, 'w', encoding='latin-1') as f:
        f.write(PROG)
    exe = os.path.join(work, 'cliarg')

    cases = [
        # a build with no options at all
        ('build', ['cliarg.cbl', '-o', 'cliarg'], 0, None),
        # a misspelt option is a mistake, not a silent no-op: building with
        # the wrong configuration and saying nothing is the failure to avoid
        ('misspelt option', ['cliarg.cbl', '--no-chek', '-o', 'x'], 2, 'unrecognized option'),
        ('unknown option', ['cliarg.cbl', '--nonsense', '-o', 'x'], 2, 'unrecognized option'),
        # dialects are implemented, so they are accepted; a name it does not
        # know is a mistake
        ('-std=ibm', ['cliarg.cbl', '-std=ibm', '-o', 'cliarg4'], 0, None),
        ('-std=mf', ['cliarg.cbl', '-std=mf', '-o', 'cliarg5'], 0, None),
        ('-std=cobol2014', ['cliarg.cbl', '-std=cobol2014', '-o', 'cliarg6'], 0, None),
        ('unknown dialect', ['cliarg.cbl', '-std=nosuch', '-o', 'x'], 2, 'unknown dialect'),
        ('-f option', ['cliarg.cbl', '-fno-binary-truncate', '-o', 'cliarg7'], 0, None),
        ('unknown -f option', ['cliarg.cbl', '-fno-such-thing', '-o', 'x'], 2, 'unrecognized option'),
        # options it does implement are accepted
        ('--no-check', ['cliarg.cbl', '--no-check', '-o', 'cliarg2'], 0, None),
        ('-O0', ['cliarg.cbl', '-O0', '-o', 'cliarg3'], 0, None),
        # --run passes arguments to the program
        ('--run', ['cliarg.cbl', '--run'], 0, 'NARGS=+000000000'),
        ('--run plain args', ['cliarg.cbl', '--run', '42', 'hello'], 0, 'NARGS=+000000002'),
        # arguments beginning with '-' need the '--' separator, because
        # otherwise they are indistinguishable from a misspelt option
        ('--run dash arg needs --', ['cliarg.cbl', '--run', '--bogus'], 2, 'unrecognized option'),
        ('--run --', ['cliarg.cbl', '--run', '--', '--bogus', '-x'], 0, 'NARGS=+000000002'),
        # nothing to compile
        ('no sources', [], 2, 'no source files'),
        ('--version', ['--version'], 0, 'YACCC'),
    ]

    for name, args, want_rc, want_in in cases:
        res = run(args, work)
        check(name, res, want_rc, want_in)
        if verbose:
            print(f"{'ok  ' if res.returncode == want_rc else 'FAIL'} {name}")

    if os.path.exists(exe):
        res = subprocess.run([exe], capture_output=True, text=True)
        check('built program runs', res, 0, 'NARGS=+000000000')

    # a dialect has to change what the compiler does, not just be accepted:
    # PIC 9(2) COMP is 2 bytes with binary-size 2-4-8 and 1 byte with 1-2-4-8,
    # which shows as the size of the group that contains it
    size_src = os.path.join(work, 'dsize.cbl')
    with open(size_src, 'w', encoding='latin-1') as f:
        f.write('       IDENTIFICATION DIVISION.\n'
                '       PROGRAM-ID. DSIZE.\n'
                '       DATA DIVISION.\n'
                '       WORKING-STORAGE SECTION.\n'
                '       01 G.\n'
                '          05 A PIC 9(2) COMP.\n'
                '          05 B PIC X VALUE "Z".\n'
                '       PROCEDURE DIVISION.\n'
                '           DISPLAY "SIZE=" LENGTH OF G.\n'
                '           STOP RUN.\n')
    for std, want in (('ibm', 'SIZE=3'), ('mf', 'SIZE=2')):
        out = os.path.join(work, 'dsize_' + std)
        r = run(['dsize.cbl', '-std=' + std, '-o', out], work)
        if r.returncode == 0:
            run_res = subprocess.run([out], capture_output=True, text=True)
            check(f'-std={std} changes storage', run_res, 0, want)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
