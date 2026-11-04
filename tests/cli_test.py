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

# BOTTOM is reserved (LINAGE ... LINES AT BOTTOM), HELLO isn't
WORDS = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WORDS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BOTTOM PIC 9 VALUE 3.
       01 HELLO PIC 9 VALUE 4.
       PROCEDURE DIVISION.
           DISPLAY BOTTOM HELLO.
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

    diagnostics(work)
    interop(work)
    tracing(work)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


ERRS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERRS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL     PIC 9(5) VALUE 0.
       01 WS-BAD       PIC 9(3) VALU 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLY "HELLO".
           COMPUTE WS-TOTAL = FUNCTION SQRTT(4).
           STOP RUN.
'''

SEMANTIC = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL     PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-TOTL.
           PERFORM SHOW-TOTL.
           DISPLAY WS-TOTAL.
       SHOW-TOTAL.
           DISPLAY WS-TOTAL
       DONE-PARA.
           STOP RUN.
'''

MARGIN = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. MARGIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 R PIC X(10) VALUE "A".
       PROCEDURE DIVISION.
                 DISPLAY "[" R "]" " len " FUNCTION LENGTH(FUNCTION TRIM(R))
           STOP RUN.
'''


CALLS_C = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLSC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BUF   PIC X(8) VALUE "abc".
       01 N     PIC S9(9) COMP-5.
       01 PTR   USAGE POINTER.
       PROCEDURE DIVISION.
           CALL "shout" USING BUF
           CALL "add3" USING BY VALUE 40 BY VALUE 2 RETURNING N
           CALL "strlen" USING BY REFERENCE Z"hello" RETURNING PTR
           DISPLAY BUF " " N
           STOP RUN.
'''

HELPER_C = '''#include <ctype.h>
int shout(char *p) { for (int i = 0; i < 8 && p[i]; i++) p[i] = toupper((unsigned char)p[i]); return 0; }
int add3(int a, int b) { return a + b + 3; }
'''

SUB = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. GREET-SUB.
       DATA DIVISION.
       LINKAGE SECTION.
       01 L-NAME PIC X(5).
       01 L-NUM  PIC S9(9) COMP-5.
       PROCEDURE DIVISION USING L-NAME BY VALUE L-NUM.
           DISPLAY "HELLO " L-NAME " " L-NUM
           MOVE "DONE!" TO L-NAME
           MOVE 7 TO RETURN-CODE
           GOBACK.
'''

C_MAIN = '''#include <stdio.h>
#include <stdint.h>
extern int GREET__SUB(void *name, intptr_t num);
int main(void) {
    char name[5] = "FROMC";
    int rc = GREET__SUB(name, 42);
    printf("rc=%d name=%.5s\\n", rc, name);
    return 0;
}
'''

DYN_MAIN = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNMAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 NM    PIC X(5) VALUE "COBOL".
       01 PNAME PIC X(20) VALUE "GREET-SUB".
       PROCEDURE DIVISION.
           CALL PNAME USING NM BY VALUE 99
           DISPLAY "BACK " NM " " RETURN-CODE
           CALL "NO-SUCH-PROG"
           STOP RUN.
'''


def interop(work):
    """COBOL and C call each other, programs compile to object files and to
    modules that CALL loads, and a CALL that finds nothing says where it looked."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('callsc.cbl', CALLS_C)
    write('helper.c', HELPER_C)
    write('greet-sub.cbl', SUB)
    write('cmain.c', C_MAIN)
    write('dynmain.cbl', DYN_MAIN)
    r = run(['callsc.cbl', 'helper.c', '--run'], work)
    check('COBOL calls C', r, 0, 'ABC      +0000000045')
    r = run(['-c', 'greet-sub.cbl'], work)
    check('-c writes an object file', r, 0)
    if not os.path.exists(os.path.join(work, 'greet-sub.o')):
        check('-c object exists', r, -1)
    r = run(['cmain.c', 'greet-sub.o', '-o', 'cmain'], work)
    check('C main linked with a COBOL object', r, 0)
    if r.returncode == 0:
        res = subprocess.run([os.path.join(work, 'cmain')], capture_output=True, text=True)
        check('C calls COBOL', res, 0, 'rc=7 name=DONE!')
        check('C passes a value', res, 0, 'HELLO FROMC +0000000042')
    os.makedirs(os.path.join(work, 'mods'), exist_ok=True)
    r = run(['-m', 'greet-sub.cbl', '-o', os.path.join('mods', 'GREET-SUB' + module_ext())], work)
    check('-m builds a module', r, 0)
    r = run(['dynmain.cbl', '-o', 'dynmain'], work)
    check('program that loads a module', r, 0)
    if r.returncode == 0:
        env = dict(os.environ, COB_LIBRARY_PATH=os.path.join(work, 'mods'))
        res = subprocess.run([os.path.join(work, 'dynmain')], capture_output=True, text=True,
                             cwd=work, env=env)
        check('CALL loads the module from COB_LIBRARY_PATH', res, 1, 'BACK DONE! +000000007')
        check('a missing program is reported with the search path', res, 1,
              "module 'NO-SUCH-PROG' not found")
        check('... and where it looked', res, 1, 'mods:.')


TRACED = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRDEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READY TRACE
           PERFORM WORK-PARA 2 TIMES
           RESET TRACE
           DISPLAY "N=" N
           STOP RUN.
       WORK-PARA.
           ADD 1 TO N.
'''


def tracing(work):
    """-ftraceall: paragraphs and statements while READY TRACE has it on."""
    with open(os.path.join(work, 'traced.cbl'), 'w', encoding='latin-1') as f:
        f.write(TRACED)
    r = run(['-ftraceall', 'traced.cbl', '--run'], work)
    check('-ftraceall traces statements', r, 0,
          'Program-Id:  TRDEMO                      ADD                             Line:     14')
    check('-ftraceall traces paragraphs', r, 0, 'Paragraph: WORK-PARA')
    check('RESET TRACE stops it', r, 0, 'RESET TRACE')
    check('... and nothing after', r, 0, None, 'DISPLAY')
    r = run(['traced.cbl', '--run'], work)
    check('no trace without -ftrace', r, 0, None, 'Program-Id:')


def module_ext():
    return '.dylib' if sys.platform == 'darwin' else '.so'


def diagnostics(work):
    """One compile reports every error it can, with the help a reader needs
    to fix each one."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('errs.cbl', ERRS)
    write('sem.cbl', SEMANTIC)
    write('margin.cbl', MARGIN)
    r = run(['errs.cbl', '-o', 'errs'], work)
    # three syntax errors in three statements, all reported, each with a fix
    check('every syntax error reported', r, 1, '3 errors')
    check('suggests a clause', r, 1, "found 'VALU'; did you mean 'VALUE'?")
    check('suggests a verb', r, 1, "found 'DISPLY'; did you mean 'DISPLAY'?")
    check('suggests a function', r, 1, "'SQRTT'; did you mean 'SQRT'?")
    r = run(['sem.cbl', '-o', 'sem'], work)
    check('suggests a data name', r, 1, "'WS-TOTL' is not defined; did you mean 'WS-TOTAL'?")
    check('suggests a paragraph', r, 1, "procedure 'SHOW-TOTL' is not defined; did you mean 'SHOW-TOTAL'?")
    check('names a missing period', r, 1, 'is the period missing')
    r = run(['margin.cbl', '-o', 'margin'], work)
    check('says text past column 72 is ignored', r, 1, "'(R))' is outside the program text")
    # -fsyntax-only checks and writes nothing
    r = run(['cliarg.cbl', '-fsyntax-only', '-o', 'nothing'], work)
    check('-fsyntax-only', r, 0)
    if os.path.exists(os.path.join(work, 'nothing')):
        check('-fsyntax-only writes nothing', r, -1)
    r = run(['sem.cbl', '-fsyntax-only'], work)
    check('-fsyntax-only reports errors', r, 1, 'WS-TOTL')
    # -E: the source the parser sees, which compiles to the same program
    r = run(['-E', 'cliarg.cbl', '-o', 'cliarg_pre.cob'], work)
    check('-E', r, 0)
    r = run(['cliarg_pre.cob', '--run'], work)
    check('-E output compiles and runs', r, 0, 'NARGS=+000000000')
    # -fnot-reserved / -freserved move words in and out of the reserved set
    write('words.cbl', WORDS)
    r = run(['words.cbl', '--run'], work)
    check('a reserved word as a name is an error', r, 1, "'BOTTOM'")
    r = run(['-fnot-reserved=bottom,volatile', 'words.cbl', '--run'], work)
    check('-fnot-reserved frees words', r, 0, '34')
    r = run(['-fnot-reserved=bottom', '-freserved=hello', 'words.cbl'], work)
    check('-freserved reserves a word', r, 1, "'HELLO'")
    r = run(['-fnot-reserved=display', 'words.cbl'], work)
    check('-fnot-reserved keeps verbs', r, 2, "'DISPLAY' begins a statement")


if __name__ == '__main__':
    sys.exit(main())
