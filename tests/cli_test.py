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
    crashes(work)
    dumps(work)
    listings(work)
    cobc_options(work)
    variable_files(work)
    static_calls(work)
    runner(work)
    cobc_options2(work)
    data_checks(work)
    odo_options(work)
    binary_options(work)
    register_literal_assign(work)
    move_ibm(work)
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


STACK = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRMAIN.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "START".
           PERFORM DO-CALL.
           STOP RUN.
       DO-CALL.
           CALL "TRSUB".
       END PROGRAM TRMAIN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRSUB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "no-such-dir/x.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(10).
       PROCEDURE DIVISION.
       S-MAIN.
           PERFORM S-OPEN THRU S-OPEN-EXIT.
           GOBACK.
       S-OPEN.
           PERFORM S-REAL.
       S-OPEN-EXIT.
           EXIT.
       S-REAL.
           OPEN INPUT F.
       END PROGRAM TRSUB.
'''

LOOPS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPS.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM AGAIN.
           STOP RUN.
       AGAIN.
           PERFORM AGAIN.
'''

# a bad address: what was displayed before the crash still comes out
CRASH = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. CRASH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 P USAGE POINTER.
       LINKAGE SECTION.
       01 L PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "BEFORE".
           SET P TO NULL.
           SET P UP BY 16.
           SET ADDRESS OF L TO P.
           PERFORM BOOM.
           DISPLAY "AFTER".
           STOP RUN.
       BOOM.
           MOVE "XXXXXXXXXX" TO L.
'''

# writes a record, says it is ready, and sleeps: a signal then ends it
SLEEPER = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. SLEEPER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "kept.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT G ASSIGN TO "ready.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(20).
       FD G.
       01 RG PIC X(5).
       WORKING-STORAGE SECTION.
       01 SECS PIC 9(3).
       PROCEDURE DIVISION.
           ACCEPT SECS FROM ARGUMENT-VALUE.
           OPEN OUTPUT F.
           MOVE "RECORD ONE" TO R.
           WRITE R.
           OPEN OUTPUT G.
           MOVE "READY" TO RG.
           WRITE RG.
           CLOSE G.
           CALL "C$SLEEP" USING SECS.
           CLOSE F.
           DISPLAY "SLEPT".
           STOP RUN.
'''


def crashes(work):
    """A runtime error lists the PERFORMs and CALLs that led to it; a crash
    or a signal says what ended the program, and what it wrote is kept."""
    import signal
    import time

    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)

    def notes(r):
        return [l for l in r.stderr.splitlines() if ': note: ' in l]

    write('stack.cbl', STACK)
    r = run(['stack.cbl', '--run'], work)
    check('runtime error names the error', r, 1, 'file not found (status = 35) for file F')
    want = ['stack.cbl:27: note: PERFORM S-REAL in paragraph S-OPEN of TRSUB',
            'stack.cbl:24: note: PERFORM S-OPEN THRU S-OPEN-EXIT in paragraph S-MAIN of TRSUB',
            'stack.cbl:9: note: CALL "TRSUB" in paragraph DO-CALL of TRMAIN',
            'stack.cbl:6: note: PERFORM DO-CALL in paragraph MAIN-PARA of TRMAIN']
    got = notes(r)
    check('stack trace: PERFORMs and CALLs, innermost first',
          r if got == want else subprocess.CompletedProcess(r.args, -1, r.stdout,
                                                            r.stderr + f"\ngot {got}"), 1)
    exe = os.path.join(work, 'stackx')
    run(['stack.cbl', '-o', exe], work)
    env = dict(os.environ, COB_STACKTRACE='N')
    r = subprocess.run([exe], capture_output=True, text=True, env=env, cwd=work)
    check('COB_STACKTRACE=N leaves the trace out', r, 1, 'status = 35', ': note: ')
    r = run(['-fno-stack-trace', 'stack.cbl', '--run'], work)
    check('-fno-stack-trace: no PERFORMs', r, 1, None, 'note: PERFORM')
    check('-fno-stack-trace: still the CALL', r, 1, 'note: CALL "TRSUB"')

    write('loops.cbl', LOOPS)
    r = run(['loops.cbl', '--run'], work)
    check('PERFORM overflow', r, 1, 'PERFORM stack overflow')
    check('a PERFORM repeated in a row is counted, not listed',
          r, 1, 'loops.cbl:8: note: PERFORM AGAIN in paragraph AGAIN of LOOPS, 510 times')

    write('crash.cbl', CRASH)
    exe = os.path.join(work, 'crashx')
    run(['crash.cbl', '-o', exe], work)
    r = subprocess.run([exe], capture_output=True, text=True, cwd=work)
    check('SIGSEGV: a message', r, -signal.SIGSEGV,
          'cobrt: runtime error: attempt to reference unallocated memory (signal SIGSEGV)')
    check('SIGSEGV: where', r, -signal.SIGSEGV, 'crash.cbl:14: note: PERFORM BOOM')
    check('SIGSEGV: output before it is kept', r, -signal.SIGSEGV, 'BEFORE')

    write('sleeper.cbl', SLEEPER)
    exe = os.path.join(work, 'sleeper')
    run(['sleeper.cbl', '-o', exe], work)

    def started(secs, preexec=None):
        ready = os.path.join(work, 'ready.txt')
        if os.path.exists(ready):
            os.unlink(ready)
        p = subprocess.Popen([exe, str(secs)], cwd=work, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, preexec_fn=preexec)
        for _ in range(300):
            if os.path.exists(ready) and os.path.getsize(ready) > 0:
                break
            time.sleep(0.1)
        return p

    p = started(60)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=60)
    r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
    check('SIGTERM: a message', r, -signal.SIGTERM, 'cobrt: terminated (signal SIGTERM)')
    with open(os.path.join(work, 'kept.txt'), encoding='latin-1') as f:
        kept = f.read()
    check('SIGTERM: the record written is kept',
          r if kept == 'RECORD ONE\n' else subprocess.CompletedProcess(p.args, -1, kept, ''),
          -signal.SIGTERM)
    # a signal the program was started with ignored stays ignored (nohup)
    p = started(2, lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN))
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=60)
    check('an ignored SIGTERM stays ignored',
          subprocess.CompletedProcess(p.args, p.returncode, out, err), 0, 'SLEPT')


DUMPED = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUMPMAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-NAME     PIC X(10) VALUE "ALICE".
          05 WS-AMT      PIC S9(5)V99 VALUE -12.5.
          05 WS-PACK     PIC S9(7) COMP-3 VALUE 1234567.
          05 WS-BADX     PIC X(3) VALUE "1A3".
          05 WS-BAD REDEFINES WS-BADX PIC 9(3).
          05 WS-TAB OCCURS 5 INDEXED BY TX.
             10 WS-ITEM  PIC 9(3).
             10 WS-FLAG  PIC X.
       01 WS-N           PIC 99 VALUE 2.
       01 WS-ODO.
          05 WS-E PIC X(2) OCCURS 1 TO 9 DEPENDING ON WS-N.
       01 WS-LOW         PIC X(6) VALUE LOW-VALUES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-ITEM (1)
           MOVE 7 TO WS-ITEM (2) WS-ITEM (3) WS-ITEM (4)
           MOVE "Y" TO WS-FLAG (2) WS-FLAG (3) WS-FLAG (4)
           SET TX TO 2
           MOVE "AA" TO WS-E (1)
           MOVE "BB" TO WS-E (2)
           MOVE "XYZ" TO WS-LOW (2:3)
           CALL "DUMPSUB" USING WS-REC.
           STOP RUN.
       END PROGRAM DUMPMAIN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUMPSUB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "no-such-dir/x.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(10).
       LOCAL-STORAGE SECTION.
       01 LS-COUNT PIC 9(4) VALUE 17.
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-NAME PIC X(10).
       01 LK-MISSING PIC X(5).
       PROCEDURE DIVISION USING LK-REC LK-MISSING.
       S-MAIN.
           OPEN INPUT F.
           GOBACK.
       END PROGRAM DUMPSUB.
'''


def dumps(work):
    """-fdump: after a runtime error, the data of each active program."""
    import signal
    with open(os.path.join(work, 'dumped.cbl'), 'w', encoding='latin-1') as f:
        f.write(DUMPED)
    exe = os.path.join(work, 'dumped')
    r = run(['-fdump', 'dumped.cbl', '-o', exe], work)
    check('-fdump builds', r, 0)
    r = subprocess.run([exe], capture_output=True, text=True, cwd=work)
    err = r.stderr
    want = [
        'cobrt: data of DUMPSUB (dumped.cbl)',
        "  FD F ('no-such-dir/x.dat'), closed, status 35",
        '  01 LS-COUNT                         9(4)              0017',
        '     05 LK-NAME                       X(10)             "ALICE     "',
        '  01 LK-MISSING                       X(5)              (no storage: not passed, or not allocated)',
        'cobrt: data of DUMPMAIN (dumped.cbl)',
        '     05 WS-AMT                        S9(5)V99          -00012.50',
        '     05 WS-PACK                       S9(7) COMP-3      +1234567',
        '     05 WS-BAD                        9(3) REDEFINES WS-BADX "1A3" (not numeric)',
        '     05 WS-TAB (3 to 4): the same as (2)',
        '        10 WS-ITEM (5)                9(3)              000',
        '     05 WS-E (2)                                        "BB"',
        '  01 WS-LOW                           X(6)              x"0058595A0000" ".XYZ.."',
        '  INDEX TX                            of WS-TAB         2',
    ]
    lines = err.splitlines()
    missing = [w for w in want if w not in lines]
    check('the dump: every section, values as DISPLAY shows them',
          r if not missing else subprocess.CompletedProcess(r.args, -1, '', '\n'.join(
              ['missing: ' + m for m in missing] + lines)), 1)
    heads = [l for l in lines if l.startswith('cobrt: data of ')]
    check('the dump: the innermost program first',
          r if heads == ['cobrt: data of DUMPSUB (dumped.cbl)', 'cobrt: data of DUMPMAIN (dumped.cbl)']
          else subprocess.CompletedProcess(r.args, -1, '', '\n'.join(heads)), 1)
    check('the dump: a table only as far as DEPENDING ON says', r, 1, None, 'WS-E (3)')
    # COB_DUMP_FILE: appended to a file instead
    dfile = os.path.join(work, 'dump.txt')
    if os.path.exists(dfile):
        os.unlink(dfile)
    r = subprocess.run([exe], capture_output=True, text=True, cwd=work,
                       env=dict(os.environ, COB_DUMP_FILE=dfile))
    check('COB_DUMP_FILE: a note where it is', r, 1, f'cobrt: the data is in {dfile}', 'data of DUMPSUB')
    text = open(dfile, encoding='latin-1').read() if os.path.exists(dfile) else ''
    check('COB_DUMP_FILE: the dump is in the file',
          r if 'cobrt: data of DUMPSUB (dumped.cbl)' in text else
          subprocess.CompletedProcess(r.args, -1, text, ''), 1)
    r = subprocess.run([exe], capture_output=True, text=True, cwd=work,
                       env=dict(os.environ, COB_DUMP_FILE='NONE'))
    check('COB_DUMP_FILE=NONE: no dump', r, 1, 'status = 35', 'data of')
    # one section only
    r = run(['-fdump=WS', 'dumped.cbl', '--run'], work)
    check('-fdump=WS: WORKING-STORAGE', r, 1, 'WORKING-STORAGE SECTION')
    check('-fdump=WS: nothing else', r, 1, None, 'LINKAGE SECTION')
    r = run(['dumped.cbl', '--run'], work)
    check('no dump without -fdump', r, 1, None, 'data of')
    r = run(['-fdump=RD', 'dumped.cbl'], work)
    check('-fdump=RD is refused', r, 2, 'REPORT SECTION is not dumped')
    r = run(['-fdump=XX', 'dumped.cbl'], work)
    check('-fdump: an unknown scope is refused', r, 2, "unknown scope 'XX'")
    # Ctrl-\ (SIGQUIT) on a program that seems stuck: where it is, and its data
    with open(os.path.join(work, 'sleeper.cbl'), 'w', encoding='latin-1') as f:
        f.write(SLEEPER)
    exe = os.path.join(work, 'sleeperd')
    run(['-fdump=WS', 'sleeper.cbl', '-o', exe], work)
    ready = os.path.join(work, 'ready.txt')
    if os.path.exists(ready):
        os.unlink(ready)
    p = subprocess.Popen([exe, '60'], cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, preexec_fn=lambda: __import__('resource').setrlimit(
                             __import__('resource').RLIMIT_CORE, (0, 0)))
    import time
    for _ in range(300):
        if os.path.exists(ready) and os.path.getsize(ready) > 0:
            break
        time.sleep(0.1)
    p.send_signal(signal.SIGQUIT)
    out, err = p.communicate(timeout=60)
    r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
    check('SIGQUIT: the data', r, -signal.SIGQUIT, '  01 SECS')


CUSTREC = '''       01 CUST-REC.
          05 CUST-ID      PIC 9(5).
          05 CUST-NAME    PIC X(20).
'''

LISTED = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. LPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTREC.
       01 WS-TOTAL        PIC 9(7) VALUE 0.
       01 WS-UNUSED       PIC X.
       01 WS-TAB.
          05 WS-ENT PIC 9(3) OCCURS 5 INDEXED BY WX.
       01 WS-FLAG PIC X VALUE "N".
          88 IS-DONE VALUE "Y".
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 42 TO CUST-ID
           PERFORM ADD-IT 3 TIMES
           SET WX TO 1
           SET IS-DONE TO TRUE
           IF IS-DONE
               GO TO END-PARA
           END-IF.
       ADD-IT.
           ADD CUST-ID TO WS-TOTAL
           MOVE WS-TOTAL TO WS-ENT (WX).
       END-PARA.
           DISPLAY WS-TOTAL " " CUST-NAME
           STOP RUN.
'''

LIST_ERR = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. LERR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL        PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
           MOVE 1 TO WS-TOTL.
           STOP RUN.
'''


def listings(work):
    """-t / -T: the listing; -Xref: its cross-reference."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)

    def lines_of(path):
        try:
            with open(os.path.join(work, path), encoding='latin-1') as f:
                return [' '.join(l.split()) for l in f.read().splitlines()]
        except OSError:
            return []

    def has(name, path, want, r):
        got = lines_of(path)
        missing = [w for w in want if ' '.join(w.split()) not in got]
        check(name, r if not missing else subprocess.CompletedProcess(
            r.args, -1, '', '\n'.join(['missing: ' + m for m in missing] + got[:40])), r.returncode)

    write('CUSTREC.cpy', CUSTREC)
    write('listed.cbl', LISTED)
    r = run(['-t', 'listed.lst', '-Xref', 'listed.cbl', '-o', 'listed'], work)
    check('-t -Xref builds', r, 0)
    has('the listing: the source, a copybook after its COPY', 'listed.lst', [
        '5 COPY CUSTREC.',
        '--- COPY CUSTREC.cpy',
        '2C 05 CUST-ID PIC 9(5).',
        '--- end of CUSTREC.cpy',
        '6 01 WS-TOTAL PIC 9(7) VALUE 0.',
        '0 errors, 0 warnings'], r)
    has('the listing: a data map', 'listed.lst', [
        'DATA MAP OF LPROG',
        'CUSTREC.cpy:3 05 CUST-NAME 5 20 X(20)',
        '9 05 WS-ENT 0 15 9(3) OCCURS 5'], r)
    has('the listing: the cross-reference', 'listed.lst', [
        'CROSS-REFERENCE OF LPROG',
        'CUST-ID CUSTREC.cpy:2 14* 22',
        'WS-TOTAL 6 22* 23 25',
        'IS-DONE 11 17* 18',
        'WS-UNUSED 7 (not referenced)',
        'WX (index) 9 16* 23',
        'ADD-IT 21 15P',
        'END-PARA 24 19G'], r)
    r = run(['-T', 'wide.lst', 'listed.cbl', '-o', 'listed'], work)
    has('-T: the same listing', 'wide.lst', ['5 COPY CUSTREC.'], r)
    check('-t without -Xref: no cross-reference',
          r if 'CROSS-REFERENCE OF LPROG' not in lines_of('wide.lst') else
          subprocess.CompletedProcess(r.args, -1, '', 'a cross-reference without -Xref'), 0)
    if os.path.exists(os.path.join(work, 'listed.lst')):
        os.unlink(os.path.join(work, 'listed.lst'))
    r = run(['-Xref', 'listed.cbl', '-o', 'listed'], work)
    has('-Xref alone: SOURCE.lst', 'listed.lst', ['CROSS-REFERENCE OF LPROG'], r)
    write('lerr.cbl', LIST_ERR)
    r = run(['-t', 'lerr.lst', 'lerr.cbl', '-o', 'lerr'], work)
    check('a listing of a compile that fails', r, 1)
    has('the listing: an error under its line', 'lerr.lst', [
        "7 MOVE 1 TO WS-TOTL.",
        "*** error: 'WS-TOTL' is not defined; did you mean 'WS-TOTAL'?",
        '1 error, 0 warnings'], r)


WARNS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. WARNS.
       PROCEDURE DIVISION.
           DISPLAY "A".                                                           XXXXXXXXXXXXX
           STOP RUN.
'''

QUOTED = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUOT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 Q1 PIC X(3) VALUE QUOTE.
       PROCEDURE DIVISION.
           DISPLAY "[" Q1 "][" QUOTE "]"
           STOP RUN.
'''

COLSEQ = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. COLSEQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X VALUE "a".
       01 B PIC X VALUE "A".
       PROCEDURE DIVISION.
           IF A < B DISPLAY "a<A" ELSE DISPLAY "a>A" END-IF
           STOP RUN.
'''

MFCOMMENT = '''*A MICRO FOCUS COMMENT IN COLUMN 1
/AND A PAGE EJECT
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MFC.
       PROCEDURE DIVISION.
           DISPLAY "MFC OK".
           STOP RUN.
'''

PASTEND = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. PASTEND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 T.
          05 E PIC X OCCURS 3.
       01 S PIC X(5) VALUE "ABCDE".
       01 I PIC 9 VALUE 4.
       PROCEDURE DIVISION.
           MOVE "Z" TO E (I)
           DISPLAY "SUBSCRIPT PASSED"
           DISPLAY S (I:3)
           DISPLAY "REFMOD PASSED"
           STOP RUN.
'''

APOS3 = "'" * 3
APOS1 = "'"


def cobc_options(work):
    """cobc's options that build scripts use: warnings, the C compiler's and
    the link's options, intermediate files, checks, QUOTE, the collating
    sequence, column-1 comments."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('warns.cbl', WARNS)
    r = run(['warns.cbl', '-o', 'warns'], work)
    check('a warning names its -W option', r, 0, '[-Wcolumn-overflow]')
    r = run(['-w', 'warns.cbl', '-o', 'warns'], work)
    check('-w: no warnings', r, 0, None, 'warning')
    r = run(['-Wno-column-overflow', 'warns.cbl', '-o', 'warns'], work)
    check('-Wno-NAME: not that warning', r, 0, None, 'warning')
    r = run(['-Wall', '-W', '-Wextra', 'warns.cbl', '-o', 'warns'], work)
    check('-Wall, -W, -Wextra: every warning', r, 0, '[-Wcolumn-overflow]')
    r = run(['-Werror', 'warns.cbl', '-o', 'warns'], work)
    check('-Werror: a warning fails the compile', r, 1, '[-Werror=column-overflow]')
    r = run(['-Wnosuch', 'warns.cbl', '-o', 'warns'], work)
    check('-W with a name cobc does not have', r, 2, 'unknown warning')
    r = run(['-Wtruncate', 'warns.cbl', '-o', 'warns'], work)
    check('-W with a warning YACCC does not issue', r, 0, 'has no such warning')
    # -A and -Q reach the C compiler and the link (-v shows the command)
    r = run(['-v', '-A', '-DYACCC_A_OPTION', '-Q', '-Wl,-zmuldefs', 'cliarg.cbl', '-o', 'acq'], work)
    check('-A: options for the C compiler', r, 0, '-DYACCC_A_OPTION')
    check('-Q: options for the link', r, 0, '-Wl,-zmuldefs')
    r = run(['-save-temps=keep', 'cliarg.cbl', '-o', 'saved'], work)
    check('-save-temps=DIR keeps the C',
          r if os.path.exists(os.path.join(work, 'keep', 'cliarg.c')) else
          subprocess.CompletedProcess(r.args, -1, '', 'no keep/cliarg.c'), 0)
    write('quoted.cbl', QUOTED)
    r = run(['-fsingle-quote', 'quoted.cbl', '--run'], work)
    check('-fsingle-quote: QUOTE is an apostrophe', r, 0, f"[{APOS3}][{APOS1}]")
    r = run(['quoted.cbl', '--run'], work)
    check('QUOTE is a double quote otherwise', r, 0, '["""]["]')
    write('colseq.cbl', COLSEQ)
    r = run(['-fdefault-colseq=EBCDIC', 'colseq.cbl', '--run'], work)
    check('-fdefault-colseq=EBCDIC', r, 0, 'a<A')
    r = run(['colseq.cbl', '--run'], work)
    check('the native sequence otherwise', r, 0, 'a>A')
    write('mfc.cbl', MFCOMMENT)
    r = run(['-fmfcomment', 'mfc.cbl', '--run'], work)
    check('-fmfcomment: column 1 comments', r, 0, 'MFC OK', 'warning')
    write('pastend.cbl', PASTEND)
    r = run(['pastend.cbl', '--run'], work)
    check('a subscript past the end is caught', r, 1, "subscript of 'E' out of bounds")
    r = run(['-fno-ec=EC-BOUND-SUBSCRIPT', 'pastend.cbl', '--run'], work)
    check('-fno-ec=EC-BOUND-SUBSCRIPT: that check off', r, 1, 'SUBSCRIPT PASSED')
    check('... the reference modification check still on', r, 1, 'reference modification out of bounds')
    r = run(['--no-check', 'pastend.cbl', '--run'], work)
    check('--no-check: past the end reaches the next storage, as with cobc', r, 0, 'REFMOD PASSED')
    check('... not a C library abort', r, 0, None, 'buffer overflow')
    r = run(['--no-check', '-debug', 'pastend.cbl', '--run'], work)
    check('-debug: every check', r, 1, "subscript of 'E' out of bounds")
    r = run(['-fec=EC-SIZE', 'pastend.cbl'], work)
    check('-fec of a check YACCC does not compile in or out', r, 2, 'range checks')
    r = run(['-fstack-check', '-fsource-location', '-ffold-copy=LOWER', 'cliarg.cbl', '--run'], work)
    check('-fstack-check, -fsource-location, -ffold-copy', r, 0, 'NARGS=')


VARREAD = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARREAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "old.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F RECORD VARYING FROM 1 TO 20 DEPENDING ON L.
       01 R PIC X(20).
       WORKING-STORAGE SECTION.
       01 L PIC 99.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN I-O F.
           READ F.
           READ F.
           MOVE "defghij" TO R.
           REWRITE R.
           CLOSE F.
           OPEN EXTEND F.
           MOVE "END" TO R. MOVE 3 TO L. WRITE R.
           CLOSE F.
           OPEN INPUT F.
           PERFORM UNTIL EOF-FLAG = "Y"
               READ F AT END MOVE "Y" TO EOF-FLAG
                 NOT AT END DISPLAY L " [" R (1:L) "]"
               END-READ
           END-PERFORM.
           CLOSE F.
           STOP RUN.
'''


def variable_files(work):
    """Variable-length SEQUENTIAL files: a file in the format YACCC wrote
    before it followed GnuCOBOL's is still read, extended and rewritten in
    that format; REWRITE keeps each format's header."""
    import struct
    with open(os.path.join(work, 'varread.cbl'), 'w', encoding='latin-1') as f:
        f.write(VARREAD)
    exe = os.path.join(work, 'varread')
    r = run(['varread.cbl', '-o', exe], work)
    check('a variable-length file program builds', r, 0)
    want = '03 [ABC]\n07 [defghij]\n03 [END]\n'
    headers = {
        'the old format (four bytes, machine order)': lambda n: struct.pack('<I', n),
        'format 0 (the default)': lambda n: struct.pack('>H', n) + b'\0\0',
    }
    for label, hdr in headers.items():
        data = hdr(3) + b'ABC' + hdr(7) + b'DEFGHIJ'
        path = os.path.join(work, 'old.dat')
        with open(path, 'wb') as f:
            f.write(data)
        r = subprocess.run([exe], capture_output=True, text=True, cwd=work)
        check(f'variable-length records in {label}: read, rewritten, extended',
              r if r.stdout == want else subprocess.CompletedProcess(r.args, -1, r.stdout, r.stderr), 0)
        with open(path, 'rb') as f:
            back = f.read()
        check(f'... and still in {label}',
              r if back == hdr(3) + b'ABC' + hdr(7) + b'defghij' + hdr(3) + b'END' else
              subprocess.CompletedProcess(r.args, -1, repr(back), ''), 0)
    # COB_VARSEQ_FORMAT=3: two-byte headers, REWRITE at the right place
    path = os.path.join(work, 'old.dat')
    with open(path, 'wb') as f:
        f.write(struct.pack('>H', 3) + b'ABC' + struct.pack('>H', 7) + b'DEFGHIJ')
    r = subprocess.run([exe], capture_output=True, text=True, cwd=work,
                       env=dict(os.environ, COB_VARSEQ_FORMAT='3'))
    check('COB_VARSEQ_FORMAT=3: read, rewritten, extended',
          r if r.stdout == want else subprocess.CompletedProcess(r.args, -1, r.stdout, r.stderr), 0)


STATIC_MAIN = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. SMAIN.
       PROCEDURE DIVISION.
           CALL "SSUB-ONE"
           DISPLAY "BACK IN MAIN"
           STOP RUN.
'''

STATIC_SUB = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. SSUB-ONE.
       PROCEDURE DIVISION.
           DISPLAY "IN SSUB-ONE"
           GOBACK.
'''


def static_calls(work):
    """-fstatic-call: a CALL literal's program has to be linked in."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('smain.cbl', STATIC_MAIN)
    write('ssub.cbl', STATIC_SUB)
    r = run(['-c', 'ssub.cbl', '-o', 'ssub.o'], work)
    check('-c a subprogram', r, 0)
    r = run(['-fstatic-call', '-c', '-x', 'smain.cbl', '-o', 'smain.o'], work)
    check('-fstatic-call: the main program', r, 0)
    r = run(['smain.o', 'ssub.o', '-o', 'smain'], work)
    check('-fstatic-call: linked with its subprogram', r, 0)
    if r.returncode == 0:
        res = subprocess.run([os.path.join(work, 'smain')], capture_output=True, text=True, cwd=work)
        check('-fstatic-call: the CALL reaches it', res, 0, 'IN SSUB-ONE')
    r = run(['smain.o', '-o', 'smain2'], work)
    check('-fstatic-call: without it the link fails', r, 1, 'SSUB__ONE')
    r = run(['smain.cbl', '-o', 'smain3'], work)
    check('without -fstatic-call it links', r, 0)
    res = subprocess.run([os.path.join(work, 'smain3')], capture_output=True, text=True, cwd=work)
    check('... and the CALL fails when it runs', res, 1, 'SSUB-ONE')
    r = run(['-std=ibm-strict', 'cliarg.cbl', '-o', 'strict'], work)
    check('-std=ibm-strict: ibm, with a note', r, 0, 'the choices of ibm')
    r = run(['-std=mvs', 'cliarg.cbl', '-o', 'mvs'], work)
    check('-std=mvs: ibm', r, 0)


YACCCRUN = os.path.join(ROOT, 'yacccrun')

HELLOMOD = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLOMOD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(10).
       01 N PIC S9(3)V9 VALUE -12.5.
       PROCEDURE DIVISION.
           ACCEPT A FROM ARGUMENT-VALUE
           DISPLAY "HELLO [" A "] " N
           MOVE 7 TO RETURN-CODE
           STOP RUN.
'''

CFGPROG = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. CFGPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "out.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(6).
       PROCEDURE DIVISION.
           OPEN OUTPUT F. MOVE "AB" TO R. WRITE R. CLOSE F.
           DISPLAY "RAN".
           STOP RUN.
'''


def runner(work):
    """yacccrun runs a module's program; COB_RUNTIME_CONFIG reads settings."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)

    def yrun(args, cwd=work, env=None):
        return subprocess.run([YACCCRUN] + args, capture_output=True, text=True, cwd=cwd,
                              env=dict(os.environ, **(env or {})))
    write('hellomod.cbl', HELLOMOD)
    r = run(['-m', 'hellomod.cbl'], work)
    check('-m builds a module', r, 0)
    r = yrun(['hellomod', 'world'])
    check('yacccrun PROGRAM ARG: the program runs, its RETURN-CODE the status', r, 7,
          'HELLO [world     ] -012.5')
    os.makedirs(os.path.join(work, 'mods'), exist_ok=True)
    r = run(['-m', '-std=ibm', 'hellomod.cbl', '-o', os.path.join('mods', 'hellomod' + module_ext())], work)
    r = yrun([os.path.join('mods', 'hellomod' + module_ext()), 'ibm'])
    check('yacccrun PATH: the module there, with its own compile settings', r, 7, 'HELLO [ibm       ] 0125-')
    r = yrun(['nosuchmod'])
    check('yacccrun: a program that is nowhere', r, 1, "module 'nosuchmod' not found")
    write('mods.cfg', f"library_path {os.path.join(work, 'mods')}\n")
    r = yrun(['-c', os.path.join(work, 'mods.cfg'), 'hellomod', 'cfg'])
    check('yacccrun -c FILE: a runtime configuration', r, 7, 'HELLO [cfg       ] 0125-')

    # COB_RUNTIME_CONFIG with an executable, as cobc's runtime.cfg
    write('cfgprog.cbl', CFGPROG)
    exe = os.path.join(work, 'cfgprog')
    run(['cfgprog.cbl', '-o', exe], work)
    os.makedirs(os.path.join(work, 'cfgout'), exist_ok=True)
    write('good.cfg', '# settings\nls_fixed true   # keep the spaces\n'
                      'file_path ${CFG_OUT_DIR:-cfgout}\n')
    write('top.cfg', 'include "good.cfg"\n')
    out = os.path.join(work, 'cfgout', 'out.txt')

    def cfg_run(cfg, extra=None):
        if os.path.exists(out):
            os.unlink(out)
        env = dict(os.environ, COB_RUNTIME_CONFIG=cfg, **(extra or {}))
        return subprocess.run([exe], capture_output=True, text=True, cwd=work, env=env)

    def content():
        return open(out, 'rb').read() if os.path.exists(out) else b''
    r = cfg_run('top.cfg')
    check('COB_RUNTIME_CONFIG: included settings, ${VAR:-default}',
          r if content() == b'AB    \n' else subprocess.CompletedProcess(r.args, -1, repr(content()), r.stderr), 0)
    r = cfg_run('top.cfg', {'COB_LS_FIXED': 'false'})
    check('... the environment wins over the file',
          r if content() == b'AB\n' else subprocess.CompletedProcess(r.args, -1, repr(content()), r.stderr), 0)
    write('bad.cfg', '\nnosuchtag 1\nls_fixed maybe\n')
    r = cfg_run('bad.cfg')
    check('an unknown tag ends the run unit, every problem said', r, 1,
          "bad.cfg:2: unknown configuration tag 'nosuchtag'")
    check('... a bad value too', r, 1, "invalid value 'maybe' for configuration tag 'ls_fixed'")
    write('loop.cfg', 'include "loop2.cfg"\n')
    write('loop2.cfg', 'include "loop.cfg"\n')
    r = cfg_run('loop.cfg')
    check('a recursive include', r, 1, 'loop.cfg: recursive inclusion')
    r = cfg_run('nothere.cfg')
    check('a configuration file that is not there', r, 1, 'nothere.cfg: No such file or directory')


WIDE = ('       IDENTIFICATION DIVISION.\n'
        '       PROGRAM-ID. WIDE.\n'
        '       PROCEDURE DIVISION.\n'
        '           DISPLAY "COLUMNS SEVENTY-THREE TO EIGHTY ARE PROGRAM TEXT" "-OK"\n'
        '           STOP RUN.\n')

THREE_ERRS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERRS3.
       PROCEDURE DIVISION.
           MOVE 1 TO NOPE1.
           MOVE 1 TO NOPE2.
           MOVE 1 TO NOPE3.
           STOP RUN.
'''

FREEFMT = '''IDENTIFICATION DIVISION.
PROGRAM-ID. FREEF.
PROCEDURE DIVISION.
DISPLAY "FREE OK".
STOP RUN.
'''


def cobc_options2(work):
    """More of cobc's command line: -j, -q, -info, -P, -F, -ftext-column,
    -fmax-errors, -ftsymbols."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    r = run(['-j', 'cliarg.cbl'], work)
    check('-j: build and run', r, 0, 'NARGS=+000000000')
    r = run(['-job=one two', 'cliarg.cbl'], work)
    check('-job=ARGS: its arguments, one string', r, 0, 'NARGS=+000000002')
    r = run(['-q', '-brief', 'cliarg.cbl', '-o', 'quiet'], work)
    check('-q, -brief', r, 0)
    r = run(['-info'], work)
    check('-info: how YACCC is set up, no source needed', r, 0, 'COB_LIBRARY_PATH')
    r = run(['-P', 'cliarg.cbl', '-o', 'plist'], work)
    check('-P: the listing as SOURCE.lst',
          r if os.path.exists(os.path.join(work, 'cliarg.lst')) else
          subprocess.CompletedProcess(r.args, -1, '', 'no cliarg.lst'), 0)
    os.makedirs(os.path.join(work, 'lists'), exist_ok=True)
    r = run(['-P=lists', '-ftsymbols', 'cliarg.cbl', '-o', 'plist'], work)
    check('-P=DIR: the listing in DIR',
          r if os.path.exists(os.path.join(work, 'lists', 'cliarg.lst')) else
          subprocess.CompletedProcess(r.args, -1, '', 'no lists/cliarg.lst'), 0)
    write('freef.cbl', FREEFMT)
    r = run(['-F', 'freef.cbl', '--run'], work)
    check('-F: free format', r, 0, 'FREE OK')
    write('wide.cbl', WIDE)
    r = run(['wide.cbl', '--run'], work)
    check('past column 72 is cut without -ftext-column', r, 1, 'outside the program text')
    r = run(['-ftext-column=80', 'wide.cbl', '--run'], work)
    check('-ftext-column=80: columns 73-80 are program text', r, 0,
          'COLUMNS SEVENTY-THREE TO EIGHTY ARE PROGRAM TEXT-OK')
    r = run(['-ftext-column=60', 'wide.cbl'], work)
    check('-ftext-column below 72 is refused', r, 2, 'from 72 to 255')
    write('errs3.cbl', THREE_ERRS)
    r = run(['errs3.cbl'], work)
    check('three errors, all reported', r, 1, "'NOPE3' is not defined")
    r = run(['-fmax-errors=2', 'errs3.cbl'], work)
    check('-fmax-errors=2: two, then it stops', r, 1, 'too many errors (2)')
    check('... and not the third', r, 1, None, "'NOPE3'")


BADDATA = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. BADDATA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 G.
          05 X PIC 9(3).
       01 Y PIC S9(5) COMP-3.
       01 YX REDEFINES Y PIC X(3).
       01 Z PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
           MOVE SPACES TO G.
           IF X > 5 DISPLAY "COMPARED" ELSE DISPLAY "COMPARED" END-IF.
           MOVE "ABC" TO YX.
           IF FUNCTION ARG-VALUE-COUNT = 0
               ADD X TO Z
           ELSE
               ADD Y TO Z
           END-IF.
           DISPLAY "Z=" Z.
           STOP RUN.
'''


def data_checks(work):
    """EC-DATA-INCOMPATIBLE: a numeric item that holds no number, read by
    MOVE or arithmetic, is a runtime error (the mainframe's S0C7)."""
    with open(os.path.join(work, 'baddata.cbl'), 'w', encoding='latin-1') as f:
        f.write(BADDATA.replace('FUNCTION ARG-VALUE-COUNT = 0', 'Z = 0'))
    r = run(['baddata.cbl', '--run'], work)
    check('without the check: the arithmetic goes on', r, 0, 'Z=')
    r = run(['-fec=EC-DATA-INCOMPATIBLE', 'baddata.cbl', '--run'], work)
    check('-fec=EC-DATA-INCOMPATIBLE: a DISPLAY item that holds no number', r, 1,
          "baddata.cbl:15: 'X' (Type: NUMERIC DISPLAY) not numeric: '   '")
    check('... a comparison is not checked, as with cobc', r, 1, 'COMPARED')
    r = run(['-debug', 'baddata.cbl', '--run'], work)
    check('-debug turns it on', r, 1, "'X' (Type: NUMERIC DISPLAY) not numeric")
    with open(os.path.join(work, 'badpack.cbl'), 'w', encoding='latin-1') as f:
        f.write(BADDATA.replace('PROGRAM-ID. BADDATA.', 'PROGRAM-ID. BADPACK.')
                .replace('FUNCTION ARG-VALUE-COUNT = 0', 'Z = 1'))
    r = run(['-fec=EC-DATA', 'badpack.cbl', '--run'], work)
    check('a packed item that holds no number', r, 1,
          "badpack.cbl:17: 'Y' (Type: PACKED-DECIMAL) not numeric: '0x414243'")
    r = run(['-debug', '-fno-ec=EC-DATA-INCOMPATIBLE', 'baddata.cbl', '--run'], work)
    check('-fno-ec=EC-DATA-INCOMPATIBLE turns it off again', r, 0, 'Z=')


ODO_BOUNDS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9 VALUE 7.
       01 R.
          05 A PIC X OCCURS 1 TO 3 DEPENDING ON I.
       PROCEDURE DIVISION.
           DISPLAY "[" R "]".
           STOP RUN.
'''

ODO_ROWS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOROWS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 99.
       01 TBL.
          05 ROW OCCURS 3.
             10 RN PIC 9.
             10 RC PIC X OCCURS 1 TO 5 DEPENDING ON RN.
       PROCEDURE DIVISION.
           MOVE ALL "A" TO TBL.
           MOVE 2 TO RN (1).
           MOVE 4 TO RN (2).
           MOVE "Q" TO RC (2, 4).
           MOVE LENGTH OF ROW (2) TO N.
           DISPLAY "[" ROW (2) "] " N.
           STOP RUN.
'''

ODO_SLIDE = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOSLIDE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9 VALUE 2.
       01 R VALUE "ABCDEFGH".
          05 A PIC X OCCURS 1 TO 3 DEPENDING ON I.
          05 B PIC X(2).
       PROCEDURE DIVISION.
           DISPLAY R ":" B.
           STOP RUN.
'''

ODO_KEY = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOKEY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "odokey.dat" ORGANIZATION INDEXED
               ACCESS DYNAMIC RECORD KEY IS K.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 FR.
          05 N PIC 9.
          05 T PIC X OCCURS 1 TO 3 DEPENDING ON N.
          05 K PIC X(4).
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           CLOSE F.
           STOP RUN.
'''

ODO_SELF = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOSELF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 R.
          05 T PIC X OCCURS 1 TO 3 DEPENDING ON N.
          05 N PIC 9.
       PROCEDURE DIVISION.
           MOVE 2 TO N.
           DISPLAY R.
           STOP RUN.
'''

PERF_OSVS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. POSVS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MYOCC PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       ASTART SECTION.
       A01.
           PERFORM BTEST.
           DISPLAY "BACK " MYOCC.
           STOP RUN.
       BTEST SECTION.
       B01.
           PERFORM B02 VARYING MYOCC FROM 1 BY 1 UNTIL MYOCC > 5.
           GO TO B99.
       B02.
           IF MYOCC > 1
              GO TO B99
           END-IF.
       B99.
           EXIT.
'''

ARITH_OSVS = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. AOSVS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 NUM-A  PIC 9(3) VALUE 399.
       01 NUM-B  PIC 9(3) VALUE 211.
       01 RSLT   PIC 9(3).
       01 RSLTV1 PIC 9(3).9.
       PROCEDURE DIVISION.
           COMPUTE RSLTV1, RSLT = ((NUM-A / 100) - (NUM-B / 100)) * 100.
           DISPLAY "RSLT " RSLT " " RSLTV1.
           STOP RUN.
'''

INLINE_PERIOD = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. INLP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 INDVAL PIC 9(4).
       PROCEDURE DIVISION.
           PERFORM VARYING INDVAL FROM 1 BY 1 UNTIL INDVAL > 2.
           DISPLAY "INDVAL " INDVAL.
           STOP RUN.
'''

REFMOD_ZERO = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. RMZ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC X(4) VALUE "abcd".
       01 I PIC 9 VALUE 0.
       PROCEDURE DIVISION.
           DISPLAY "[" X(1:I) "]".
           STOP RUN.
'''


def odo_options(work):
    """OCCURS DEPENDING ON at run time: the DEPENDING ON item checked where a
    variable group's size needs it, a count per table element, -fodoslide and
    $SET ODOSLIDE, and what can't be variably located; cobc's -fperform-osvs,
    -farithmetic-osvs, -frelax-syntax-checks, -f[no-]ref-mod-zero-length and
    the options that allow what YACCC allows anyway."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('odob.cbl', ODO_BOUNDS)
    r = run(['odob.cbl', '--run'], work)
    check('a group whose DEPENDING ON item is past its maximum', r, 1,
          "odob.cbl:9: OCCURS DEPENDING ON 'I' out of bounds: 7")
    check('... with the maximum noted, as cobc -debug words it', r, 1, "maximum subscript for 'A': 3")
    write('odob0.cbl', ODO_BOUNDS.replace('VALUE 7', 'VALUE 0').replace('ODOB.', 'ODOB0.'))
    r = run(['odob0.cbl', '--run'], work)
    check('... and below its minimum', r, 1, "minimum subscript for 'A': 1")
    r = run(['--no-check', 'odob0.cbl', '--run'], work)
    check('--no-check: not checked', r, 0, '[]')
    write('odorows.cbl', ODO_ROWS)
    r = run(['odorows.cbl', '--run'], work)
    check('a DEPENDING ON item in each element: the count of that element', r, 0, '[4AAAQ] 05')
    write('odoslide.cbl', ODO_SLIDE)
    r = run(['odoslide.cbl', '--run'], work)
    check('a table with an item after it in its group keeps its maximum', r, 0, 'ABCDE:DE')
    r = run(['-fodoslide', 'odoslide.cbl', '--run'], work)
    check('-fodoslide: the item after it moves up', r, 0, 'ABCD:CD')
    r = run(['-fcomplex-odo', 'odoslide.cbl', '--run'], work)
    check('-fcomplex-odo is accepted', r, 0, 'ABCDE:DE')
    write('odoset.cbl', '      $SET ODOSLIDE\n' + ODO_SLIDE.replace('ODOSLIDE.', 'ODOSET.'))
    r = run(['odoset.cbl', '--run'], work)
    check('$SET ODOSLIDE in the source', r, 0, 'ABCD:CD')
    r = run(['-fno-odoslide', 'odoset.cbl', '--run'], work)
    check('-fno-odoslide over $SET ODOSLIDE', r, 0, 'ABCDE:DE')
    write('odokey.cbl', ODO_KEY)
    r = run(['odokey.cbl'], work)
    check('a RECORD KEY after a table that keeps its maximum', r, 0)
    r = run(['-fodoslide', 'odokey.cbl'], work)
    check('-fodoslide: a RECORD KEY whose place varies is refused', r, 1,
          "key 'K' follows a table with OCCURS DEPENDING ON")
    write('odoself.cbl', ODO_SELF)
    r = run(['-fodoslide', 'odoself.cbl'], work)
    check('-fodoslide: a DEPENDING ON item placed after its own table', r, 1,
          "'N' follows the table 'T' whose size it gives")
    write('posvs.cbl', PERF_OSVS)
    r = run(['posvs.cbl', '--run'], work)
    check('only the most recent PERFORM returns at the end of its range', r, 0, None, 'BACK')
    r = run(['-fperform-osvs', 'posvs.cbl', '--run'], work)
    check('-fperform-osvs: an earlier one returns where its range ends', r, 0, 'BACK 0002')
    r = run(['-std=ibm', 'posvs.cbl', '--run'], work)
    check('... which -std=ibm sets', r, 0, 'BACK 0002')
    r = run(['-std=ibm', '-fno-perform-osvs', 'posvs.cbl', '--run'], work)
    check('-fno-perform-osvs over -std=ibm', r, 0, None, 'BACK')
    write('aosvs.cbl', ARITH_OSVS)
    r = run(['aosvs.cbl', '--run'], work)
    check('intermediate results at full precision', r, 0, 'RSLT 188 188.0')
    r = run(['-farithmetic-osvs', 'aosvs.cbl', '--run'], work)
    check('-farithmetic-osvs: cut to the largest scale, an edited receiver\'s too', r, 0,
          'RSLT 180 180.0')
    write('inlp.cbl', INLINE_PERIOD)
    r = run(['inlp.cbl'], work)
    check('an inline PERFORM needs END-PERFORM', r, 1, 'expected END-PERFORM')
    r = run(['-frelax-syntax-checks', 'inlp.cbl', '--run'], work)
    check('-frelax-syntax-checks: a period ends it, with a warning', r, 0,
          "inline PERFORM ended by '.'")
    check('... and the loop runs', r, 0, 'INDVAL 0003')
    write('rmz.cbl', REFMOD_ZERO)
    r = run(['rmz.cbl', '--run'], work)
    check('a reference modification of length zero names no bytes', r, 0, '[]')
    r = run(['-std=cobol2002', 'rmz.cbl', '--run'], work)
    check('... an error in the named dialects, as cobc', r, 1, 'reference modification out of bounds')
    r = run(['-fno-ref-mod-zero-length', 'rmz.cbl', '--run'], work)
    check('-fno-ref-mod-zero-length', r, 1, 'reference modification out of bounds')
    r = run(['-std=ibm', '-fref-mod-zero-length', 'rmz.cbl', '--run'], work)
    check('-fref-mod-zero-length over the dialect', r, 0, '[]')
    r = run(['-fmissing-statement=ok', '-flarger-redefines-ok', '-ftop-level-occurs-clause=ok',
             '-fno-constant-folding', 'rmz.cbl', '--run'], work)
    check('cobc options for what YACCC allows anyway are accepted', r, 0, '[]')


BIN_ORDER = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. BINORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 G.
          05 B PIC 9(4) BINARY VALUE 258.
       01 S PIC S9(6) BINARY VALUE -123456.
       01 C1 COMP-1.
       PROCEDURE DIVISION.
           DISPLAY FUNCTION HEX-OF (G) " " LENGTH OF S.
           ADD 1 TO B.
           DISPLAY B " " S.
           MOVE 3.5 TO C1.
           DISPLAY C1.
           STOP RUN.
'''


def binary_options(work):
    """cobc's -fbinary-byteorder, -fbinary-size=1--8 and -fbinary-comp-1."""
    with open(os.path.join(work, 'binord.cbl'), 'w', encoding='latin-1') as f:
        f.write(BIN_ORDER)
    r = run(['binord.cbl', '--run'], work)
    check('BINARY is big-endian by default', r, 0, '0102 4')
    check('... and holds its value', r, 0, '0259 -123456')
    r = run(['-fbinary-byteorder=native', 'binord.cbl', '--run'], work)
    check('-fbinary-byteorder=native: the machine\'s order', r, 0, '0201 4')
    check('... and the same values', r, 0, '0259 -123456')
    r = run(['-fbinary-size=1--8', 'binord.cbl', '--run'], work)
    check('-fbinary-size=1--8: three bytes for six digits', r, 0, '0102 3')
    check('... which hold them', r, 0, '0259 -123456')
    r = run(['-fbinary-size=1--8', '-fno-pretty-display', 'binord.cbl', '--run'], work)
    check('... shown at the width of three bytes without pretty-display', r, 0, '-00123456')
    r = run(['binord.cbl', '--run'], work)
    check('COMP-1 is a float', r, 0, '3.5')
    r = run(['-fbinary-comp-1', 'binord.cbl', '--run'], work)
    check('-fbinary-comp-1: a two-byte binary integer', r, 0, '+00003')


TALLY_PROG = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. TALLYR.
       PROCEDURE DIVISION.
           ADD 1 TO TALLY.
           DISPLAY "TALLY " TALLY.
           STOP RUN.
'''

ACU_LIT = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACULIT.
       PROCEDURE DIVISION.
           DISPLAY B#101 " " O#17777777777 " " X#ffFFFFff " " H#10.
           STOP RUN.
'''

ASSIGN_IBM = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASGIBM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO UT-S-OUTDD ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(4).
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           WRITE R FROM "HI".
           CLOSE F.
           STOP RUN.
'''


def register_literal_assign(work):
    """cobc's -fnot-register, -facu-literals (and -std=acu's literals),
    -fassign-clause."""
    def write(name, text):
        with open(os.path.join(work, name), 'w', encoding='latin-1') as f:
            f.write(text)
    write('tallyr.cbl', TALLY_PROG)
    r = run(['tallyr.cbl', '--run'], work)
    check('TALLY is a special register', r, 0, 'TALLY 00001')
    r = run(['-fnot-register=TALLY', 'tallyr.cbl'], work)
    check('-fnot-register=TALLY: an ordinary word', r, 1, "'TALLY' is not defined")
    write('aculit.cbl', ACU_LIT)
    r = run(['aculit.cbl'], work)
    check('B#101 is no literal by default', r, 1, "unexpected character '#'")
    r = run(['-facu-literals=ok', 'aculit.cbl', '--run'], work)
    check('-facu-literals=ok: B#, O#, X# and H# literals', r, 0, '5 2147483647 4294967295 16')
    r = run(['-std=acu', 'aculit.cbl', '--run'], work)
    check('... which -std=acu allows', r, 0, '5 2147483647 4294967295 16')
    write('asgibm.cbl', ASSIGN_IBM)
    r = run(['-std=ibm', 'asgibm.cbl', '--run'], work)
    check('-std=ibm: UT-S-OUTDD is the DD name OUTDD', r, 0, "ASSIGN UT-S-OUTDD interpreted as 'OUTDD'")
    check('... and the file is OUTDD', r if os.path.exists(os.path.join(work, 'OUTDD'))
          else subprocess.CompletedProcess(r.args, -1, '', 'no OUTDD'), 0)
    r = run(['-fassign-clause=ibm', 'asgibm.cbl', '--run'], work)
    check('-fassign-clause=ibm does the same', r, 0, "interpreted as 'OUTDD'")


MVC_PROG = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MVC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC PIC X(8) VALUE "ABCDEFGH".
       PROCEDURE DIVISION.
           MOVE "*" TO REC (1:1).
           MOVE REC (1:7) TO REC (2:7).
           DISPLAY "[" REC "]".
           STOP RUN.
"""


def move_ibm(work):
    """-fmove-ibm (-std=ibm): an overlapping MOVE copies as IBM's MVC does."""
    with open(os.path.join(work, 'mvc.cbl'), 'w', encoding='latin-1') as f:
        f.write(MVC_PROG)
    r = run(['mvc.cbl', '--run'], work)
    check('an overlapping MOVE moves the bytes as they were', r, 0, '[**BCDEFG]')
    r = run(['-fmove-ibm', 'mvc.cbl', '--run'], work)
    check('-fmove-ibm: a byte at a time, so the first propagates', r, 0, '[********]')
    r = run(['-std=ibm', 'mvc.cbl', '--run'], work)
    check('... which -std=ibm sets', r, 0, '[********]')
    r = run(['-std=ibm', '-fno-move-ibm', 'mvc.cbl', '--run'], work)
    check('-fno-move-ibm over -std=ibm', r, 0, '[**BCDEFG]')


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
