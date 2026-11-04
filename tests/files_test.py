#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Files shared between processes: OPEN sharing, record locks, and the
journal that relative and indexed files are kept in.

Each scenario compiles small COBOL programs with yaccc into a scratch
directory and runs them -- one after another, side by side, or one from
another through CALL "SYSTEM" -- and checks what they report.

usage: files_test.py [-v] [names...]
"""
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')

passed = failed = 0
verbose = False


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        if verbose:
            print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name}")
        print(f"     wanted {want!r}")
        print(f"     got    {got!r}")


def build(work, name, text):
    src = os.path.join(work, name + '.cbl')
    with open(src, 'w') as f:
        f.write(text)
    r = subprocess.run([YACCC, src, '-o', os.path.join(work, name)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{name}: compile error\n{r.stdout}{r.stderr}")


def run(work, name, *args, timeout=60):
    r = subprocess.run([os.path.join(work, name)] + list(args), cwd=work, capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout


def lines(out):
    return [l.rstrip() for l in out.splitlines() if l.strip()]


def select(org, clauses=''):
    """FILE-CONTROL for a file "shared.dat" of 4-byte records keyed on the first."""
    o = {'seq': '',
         'idx': 'ORGANIZATION INDEXED ACCESS DYNAMIC RECORD KEY K',
         'rel': 'ORGANIZATION RELATIVE ACCESS DYNAMIC RELATIVE KEY RK'}[org]
    return f"""           SELECT F ASSIGN "shared.dat"
               {o}
               {clauses}
               FILE STATUS FS."""


def program(name, org, clauses, body, extra_ws=''):
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
{select(org, clauses)}
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 REC.
          05 K PIC X.
          05 D PIC X(3).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 RK PIC 9(4) VALUE 1.
{extra_ws}       PROCEDURE DIVISION.
{body}           STOP RUN.
"""


def make_file(work, org, keys='XYZ'):
    """shared.dat with records X, Y, Z (relative: numbers 1, 2, 3)."""
    body = "           OPEN OUTPUT F\n"
    for i, k in enumerate(keys, 1):
        body += f'           MOVE {i} TO RK\n           MOVE "{k}abc" TO REC\n           WRITE REC\n'
    body += "           CLOSE F\n"
    build(work, 'mk', program('MK', org, '', body))
    run(work, 'mk')


# ---------------------------------------------------------------- sharing
def sharing(work):
    """Two programs: P1 opens, runs P2, which opens too. INPUT shares;
    without a clause a sequential file opened otherwise is P1's alone (as
    with cobc), a relative or indexed one is shared; SHARING NO, LOCK MODE
    EXCLUSIVE, OPEN WITH LOCK and OPEN OUTPUT keep it alone; SHARING READ
    ONLY lets others read only."""
    cases = [
        # org, P1 open, P1 clause, P2 open, P2 clause, P2's status
        ('seq', 'OUTPUT', '', 'INPUT', '', '61'),
        ('seq', 'I-O', '', 'I-O', '', '61'),
        ('seq', 'INPUT', '', 'OUTPUT', '', '61'),
        ('seq', 'INPUT', '', 'INPUT', '', '00'),
        ('seq', 'EXTEND', '', 'INPUT', '', '61'),
        ('seq', 'INPUT', 'SHARING NO', 'INPUT', '', '61'),
        ('seq', 'INPUT', 'SHARING READ ONLY', 'INPUT', '', '00'),
        ('seq', 'INPUT', 'SHARING READ ONLY', 'I-O', '', '61'),
        ('seq', 'INPUT', 'LOCK MODE EXCLUSIVE', 'INPUT', '', '61'),
        ('seq', 'INPUT WITH LOCK', '', 'INPUT', '', '61'),
        ('seq', 'INPUT', '', 'INPUT WITH LOCK', '', '61'),
        ('idx', 'I-O', '', 'I-O', '', '00'),
        ('idx', 'INPUT', '', 'I-O', '', '00'),
        ('idx', 'OUTPUT', '', 'INPUT', '', '61'),
        ('idx', 'I-O', 'SHARING NO', 'INPUT', '', '61'),
        ('idx', 'INPUT', 'SHARING READ ONLY', 'I-O', '', '61'),
        ('idx', 'INPUT', 'SHARING READ ONLY', 'INPUT', '', '00'),
        ('idx', 'I-O', 'SHARING ALL', 'I-O', 'SHARING ALL', '00'),
        ('idx', 'I-O', '', 'I-O', 'SHARING NO', '61'),
        ('rel', 'I-O', '', 'I-O', '', '00'),
        ('rel', 'I-O', 'LOCK MODE EXCLUSIVE', 'INPUT', '', '61'),
    ]
    def opening(m):
        mode, _, phrase = m.partition(' ')      # INPUT WITH LOCK: OPEN INPUT F WITH LOCK
        return f"OPEN {mode} F {phrase}".rstrip()
    for org, m1, c1, m2, c2, want in cases:
        make_file(work, org)
        build(work, 'p2', program('P2', org, c2, f'           {opening(m2)}\n           DISPLAY FS\n'))
        build(work, 'p1', program('P1', org, c1, f'''           {opening(m1)}
           CALL "SYSTEM" USING "./p2"
           CLOSE F
'''))
        check(f"sharing {org} {m1} {c1 or '-'} / {m2} {c2 or '-'}", lines(run(work, 'p1')), [want])


# ---------------------------------------------------------------- record locks
def locks(work):
    """P1 reads record X in I-O mode, then runs P2, which reads, rewrites
    and deletes it."""
    p2body = '''           OPEN {mode} F
           MOVE "X" TO K
           MOVE 1 TO RK
           READ F {phrase}
           DISPLAY "read " FS
           IF "{mode}" = "I-O"
               MOVE "new" TO D
               REWRITE REC
               DISPLAY "rewrite " FS
               DELETE F
               DISPLAY "delete " FS
           END-IF
           CLOSE F
'''
    cases = [
        # P1 clause, P1 READ phrase, P2 clause, P2 open, P2 READ phrase, P2 says
        ('', '', '', 'I-O', '', ['read 00', 'rewrite 00', 'delete 00']),
        ('LOCK MODE AUTOMATIC', '', 'LOCK MODE AUTOMATIC', 'I-O', '',
         ['read 51', 'rewrite 51', 'delete 51']),
        ('LOCK MODE MANUAL', 'WITH LOCK', 'LOCK MODE MANUAL', 'I-O', '',
         ['read 51', 'rewrite 51', 'delete 51']),
        ('LOCK MODE MANUAL', '', 'LOCK MODE MANUAL', 'I-O', '', ['read 00', 'rewrite 00', 'delete 00']),
        ('LOCK MODE AUTOMATIC', '', '', 'I-O', 'WITH NO LOCK', ['read 00', 'rewrite 51', 'delete 51']),
        ('LOCK MODE AUTOMATIC', '', '', 'INPUT', '', ['read 00']),
        ('', 'WITH LOCK', '', 'I-O', '', ['read 51', 'rewrite 51', 'delete 51']),
    ]
    for org in ('idx', 'rel'):
        for c1, r1, c2, m2, r2, want in cases:
            make_file(work, org)
            build(work, 'p2', program('P2', org, c2, p2body.format(mode=m2, phrase=r2)))
            build(work, 'p1', program('P1', org, c1, f'''           OPEN I-O F
           MOVE "X" TO K
           MOVE 1 TO RK
           READ F {r1}
           CALL "SYSTEM" USING "./p2"
           CLOSE F
'''))
            check(f"locks {org} {c1 or '-'} {r1 or '-'} / {c2 or '-'} {m2} {r2 or '-'}",
                  lines(run(work, 'p1')), want)
    # UNLOCK lets the other in; a lock taken WITH KEPT LOCK stays through the
    # next READ, a single one doesn't
    for org in ('idx', 'rel'):
        make_file(work, org)
        build(work, 'p2', program('P2', org, 'LOCK MODE MANUAL', '''           OPEN I-O F
           MOVE "X" TO K
           MOVE 1 TO RK
           READ F WITH LOCK
           DISPLAY "X " FS
           MOVE "Y" TO K
           MOVE 2 TO RK
           READ F WITH LOCK
           DISPLAY "Y " FS
           CLOSE F
'''))
        build(work, 'p1', program('P1', org, 'LOCK MODE MANUAL', '''           OPEN I-O F
           MOVE "X" TO K
           MOVE 1 TO RK
           READ F WITH KEPT LOCK
           MOVE "Y" TO K
           MOVE 2 TO RK
           READ F WITH KEPT LOCK
           CALL "SYSTEM" USING "./p2"
           UNLOCK F
           CALL "SYSTEM" USING "./p2"
           MOVE "X" TO K
           MOVE 1 TO RK
           READ F WITH LOCK
           MOVE "Y" TO K
           MOVE 2 TO RK
           READ F WITH LOCK
           CALL "SYSTEM" USING "./p2"
           CLOSE F
'''))
        check(f"locks {org} KEPT LOCK, UNLOCK, single lock", lines(run(work, 'p1')),
              ['X 51', 'Y 51', 'X 00', 'Y 00', 'X 00', 'Y 51'])


# ---------------------------------------------------------------- side by side
WRITER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRITER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN "counted.dat"
               ORGANIZATION INDEXED ACCESS DYNAMIC
               RECORD KEY F-KEY
               ALTERNATE RECORD KEY F-GRP WITH DUPLICATES
               LOCK MODE IS AUTOMATIC
               FILE STATUS FS.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 F-REC.
          05 F-KEY.
             10 F-ID  PIC X.
             10 F-SEQ PIC 9(4).
          05 F-GRP    PIC 9.
          05 F-CNT    PIC 9(8).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 ID-ARG PIC X.
       01 I PIC 9(4).
       PROCEDURE DIVISION.
           ACCEPT ID-ARG FROM COMMAND-LINE
           OPEN I-O F
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 300
               MOVE ID-ARG TO F-ID
               MOVE I TO F-SEQ
               COMPUTE F-GRP = FUNCTION MOD(I, 7)
               MOVE 0 TO F-CNT
               WRITE F-REC
               IF FS NOT = "00" DISPLAY "write " FS END-IF
      *        the counter: read with a lock, add one, rewrite
               MOVE "*" TO F-ID
               MOVE 0 TO F-SEQ
               READ F
               PERFORM UNTIL FS NOT = "51"
                   MOVE "*" TO F-ID
                   MOVE 0 TO F-SEQ
                   READ F
               END-PERFORM
               ADD 1 TO F-CNT
               REWRITE F-REC
               IF FS NOT = "00" DISPLAY "rewrite " FS END-IF
               UNLOCK F
           END-PERFORM
           CLOSE F
           STOP RUN.
"""

COUNT = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN "counted.dat"
               ORGANIZATION INDEXED ACCESS DYNAMIC
               RECORD KEY F-KEY
               ALTERNATE RECORD KEY F-GRP WITH DUPLICATES
               FILE STATUS FS.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 F-REC.
          05 F-KEY.
             10 F-ID  PIC X.
             10 F-SEQ PIC 9(4).
          05 F-GRP    PIC 9.
          05 F-CNT    PIC 9(8).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 N PIC 9(6) VALUE 0.
       01 G PIC 9(6) VALUE 0.
       01 PREV PIC 9 VALUE 0.
       01 BAD PIC 9(6) VALUE 0.
       01 MODE-ARG PIC X(4).
       PROCEDURE DIVISION.
           ACCEPT MODE-ARG FROM COMMAND-LINE
           IF MODE-ARG = "init"
               OPEN OUTPUT F
               MOVE "*" TO F-ID MOVE 0 TO F-SEQ MOVE 9 TO F-GRP
               MOVE 0 TO F-CNT
               WRITE F-REC
               CLOSE F
               STOP RUN
           END-IF
           OPEN INPUT F
           PERFORM UNTIL FS NOT = "00"
               READ F NEXT
               IF FS = "00" ADD 1 TO N END-IF
           END-PERFORM
           MOVE "*" TO F-ID MOVE 0 TO F-SEQ
           READ F KEY F-KEY
           DISPLAY "records " N " counter " F-CNT
           MOVE 0 TO F-GRP
           START F KEY >= F-GRP
           PERFORM UNTIL FS NOT = "00"
               READ F NEXT
               IF FS = "00"
                   ADD 1 TO G
                   IF F-GRP < PREV ADD 1 TO BAD END-IF
                   MOVE F-GRP TO PREV
               END-IF
           END-PERFORM
           DISPLAY "by group " G " out of order " BAD
           CLOSE F
           STOP RUN.
"""


def side_by_side(work):
    """Four writers at once on one indexed file: every record written is
    there, in alternate key order, and a counter they all update under a
    record lock loses no update."""
    build(work, 'writer', WRITER)
    build(work, 'count', COUNT)
    run(work, 'count', 'init')
    procs = [subprocess.Popen([os.path.join(work, 'writer'), w], cwd=work, stdout=subprocess.PIPE,
                              text=True) for w in 'ABCD']
    outs = [p.communicate(timeout=120)[0] for p in procs]
    check("side by side: writers report nothing", ''.join(outs), '')
    check("side by side: records, counter, alternate key order", lines(run(work, 'count')),
          ['records 001201 counter 00001200', 'by group 001201 out of order 000000'])


# ---------------------------------------------------------------- the journal
def journal(work):
    # a program killed without CLOSE: what it wrote is in the file
    build(work, 'killed', program('KILLED', 'idx', '', '''           OPEN OUTPUT F
           MOVE "Aone" TO REC
           WRITE REC
           MOVE "Btwo" TO REC
           WRITE REC
           OPEN I-O F
           CLOSE F
           OPEN I-O F
           MOVE "A" TO K
           DELETE F
           MOVE "Cnew" TO REC
           WRITE REC
           CALL "SYSTEM" USING "kill -9 $PPID"
           DISPLAY "not reached"
'''))
    build(work, 'list', program('LIST', 'idx', '', '''           OPEN INPUT F
           PERFORM UNTIL FS NOT = "00"
               READ F NEXT
               IF FS = "00" DISPLAY REC END-IF
           END-PERFORM
           CLOSE F
'''))
    if os.path.exists(os.path.join(work, 'shared.dat')):
        os.unlink(os.path.join(work, 'shared.dat'))
    run(work, 'killed')
    check("journal: killed before CLOSE, nothing lost", lines(run(work, 'list')), ['Btwo', 'Cnew'])

    # many REWRITEs of one record: the last CLOSE writes the journal afresh
    build(work, 'churn', program('CHURN', 'idx', '', '''           OPEN OUTPUT F
           MOVE "Kone" TO REC
           WRITE REC
           CLOSE F
           OPEN I-O F
           PERFORM 20000 TIMES
               MOVE "K" TO K
               READ F
               MOVE "two" TO D
               REWRITE REC
           END-PERFORM
           CLOSE F
'''))
    run(work, 'churn')
    size = os.path.getsize(os.path.join(work, 'shared.dat'))
    check("journal: compacted at CLOSE", size < 1024, True)
    check("journal: compacted content", lines(run(work, 'list')), ['Ktwo'])

    # a file in the format of the previous version: read; opened for update,
    # rewritten as a journal
    path = os.path.join(work, 'shared.dat')
    with open(path, 'wb') as f:
        f.write(b'CIX2' + struct.pack('<I', 1))
        for i, rec in enumerate([b'Pold', b'Qold']):
            f.write(struct.pack('<I', 4) + rec + struct.pack('<Q', i + 1))
    check("journal: earlier format read", lines(run(work, 'list')), ['Pold', 'Qold'])
    build(work, 'addr', program('ADDR', 'idx', '', '''           OPEN I-O F
           MOVE "Rnew" TO REC
           WRITE REC
           DISPLAY FS
           CLOSE F
'''))
    check("journal: earlier format updated", lines(run(work, 'addr')), ['00'])
    with open(path, 'rb') as f:
        magic = f.read(4)
    check("journal: earlier format rewritten as a journal", magic, b'CIXJ')
    check("journal: content kept", lines(run(work, 'list')), ['Pold', 'Qold', 'Rnew'])

    # the previous relative format: a flag byte and the record per slot
    with open(path, 'wb') as f:
        f.write(b'\x01Uone' + b'\x00    ' + b'\x01Wthr')
    build(work, 'rlist', program('RLIST', 'rel', '', '''           OPEN I-O F
           PERFORM UNTIL FS NOT = "00"
               READ F NEXT
               IF FS = "00" DISPLAY RK " " REC END-IF
           END-PERFORM
           MOVE 2 TO RK
           MOVE "Vtwo" TO REC
           WRITE REC
           CLOSE F
'''))
    check("journal: earlier relative format", lines(run(work, 'rlist')), ['0001 Uone', '0003 Wthr'])
    with open(path, 'rb') as f:
        magic = f.read(4)
    check("journal: relative file rewritten as a journal", magic, b'CIXJ')


# ---------------------------------------------------------------- one process
def one_process(work):
    """A program with the file open twice, and a program it CALLs, and one
    it runs: each sees what the others wrote."""
    build(work, 'twice', f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWICE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN "shared.dat"
               ORGANIZATION INDEXED ACCESS DYNAMIC RECORD KEY K
               FILE STATUS FS.
           SELECT G ASSIGN "shared.dat"
               ORGANIZATION INDEXED ACCESS DYNAMIC RECORD KEY GK
               FILE STATUS GS.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 REC.
          05 K PIC X.
          05 D PIC X(3).
       FD G.
       01 GREC.
          05 GK PIC X.
          05 GD PIC X(3).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 GS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT F
           MOVE "Aone" TO REC
           WRITE REC
           CLOSE F
           OPEN I-O F
           OPEN INPUT G
           MOVE "Btwo" TO REC
           WRITE REC
           MOVE "B" TO GK
           READ G
           DISPLAY "G sees " GS " " GREC
           CALL "SUB"
           MOVE "C" TO GK
           READ G
           DISPLAY "G sees " GS " " GREC
           CALL "SYSTEM" USING "./child"
           MOVE "D" TO K
           READ F
           DISPLAY "F sees " FS " " REC
           CLOSE G
           CLOSE F
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT H ASSIGN "shared.dat"
               ORGANIZATION INDEXED ACCESS DYNAMIC RECORD KEY HK
               FILE STATUS HS.
       DATA DIVISION.
       FILE SECTION.
       FD H.
       01 HREC.
          05 HK PIC X.
          05 HD PIC X(3).
       WORKING-STORAGE SECTION.
       01 HS PIC XX.
       PROCEDURE DIVISION.
           OPEN I-O H
           MOVE "Cthr" TO HREC
           WRITE HREC
           CLOSE H
           GOBACK.
       END PROGRAM SUB.
       END PROGRAM TWICE.
""")
    build(work, 'child', program('CHILD', 'idx', '', '''           OPEN I-O F
           MOVE "A" TO K
           READ F
           DISPLAY "child sees " FS " " REC
           MOVE "Dfou" TO REC
           WRITE REC
           CLOSE F
'''))
    check("one process: connectors, CALL, child", lines(run(work, 'twice')),
          ['G sees 00 Btwo', 'G sees 00 Cthr', 'child sees 00 Aone', 'F sees 00 Dfou'])


SCENARIOS = [('sharing', sharing), ('locks', locks), ('side_by_side', side_by_side),
             ('journal', journal), ('one_process', one_process)]


def main():
    global verbose
    args = sys.argv[1:]
    verbose = '-v' in args
    names = [a for a in args if not a.startswith('-')]
    for name, fn in SCENARIOS:
        if names and name not in names:
            continue
        with tempfile.TemporaryDirectory(prefix='yaccfiles_') as work:
            fn(work)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
