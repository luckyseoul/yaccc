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
