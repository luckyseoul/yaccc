#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write the large source used for the compile-time measurement.

    ./tests/bench/gen_big.py /tmp/big            # 4,200 lines by default
    ./tests/bench/gen_big.py /tmp/big --lines 8000

The program is generated rather than checked in: four thousand lines of
near-identical paragraphs would be 100 KB of noise in every clone, and the
thing being measured is the compiler's behaviour on a large source, not the
arithmetic it performs. The generator is deterministic, so the line count and
the compile time are reproducible from the commands in docs/benchmarks.md.

Every paragraph has the same shape, and the shapes rotate so the front end
cannot succeed by matching one pattern several hundred times: plain arithmetic,
a nested IF, an indexed MOVE, and a PERFORM VARYING over a table.
"""
import argparse
import os

# each paragraph is exactly this many lines, header and blank separator included
PARAGRAPH_LINES = 12
DRIVER_LINES = 13

COPYBOOK = """      *> Big-record layout, so the compile-time measurement includes COPY.
       01  BIG-RECORD.
           05  BR-KEY              PIC 9(9) COMP.
           05  BR-NAME             PIC X(40).
           05  BR-AMOUNT           PIC S9(9)V99 COMP-3.
           05  BR-RATE             PIC S9(3)V9(6) COMP-3.
           05  BR-FLAGS.
               10  BR-FLAG-A       PIC X.
               10  BR-FLAG-B       PIC X.
           05  BR-COUNTERS.
               10  BR-HITS         PIC 9(7) COMP.
               10  BR-MISSES       PIC 9(7) COMP.
           05  BR-TABLE OCCURS 20 TIMES.
               10  BR-T-CODE       PIC 9(3) COMP.
               10  BR-T-TEXT       PIC X(12).
       01  BIG-TOTAL               PIC S9(13)V99 COMP-3.
       01  BIG-INDEX               PIC 9(9) COMP.
       01  BIG-SWITCH              PIC X VALUE "N".
"""


def body(n):
    """The statements of one paragraph, chosen by shape."""
    if n % 11 == 0:
        return [
            "           IF BIG-SWITCH = \"Y\"",
            "               COMPUTE BIG-TOTAL = BIG-TOTAL * 2",
            "           ELSE",
            "               COMPUTE BIG-TOTAL = BIG-TOTAL + 1",
            "           END-IF",
            "           MOVE \"Y\" TO BIG-SWITCH",
            "           MOVE \"N\" TO BIG-SWITCH",
        ]
    if n % 7 == 0:
        return [
            "           MOVE BIG-INDEX TO BR-KEY",
            "           ADD 1 TO BR-HITS",
            "           COMPUTE BR-RATE = BR-AMOUNT / 100",
            "           COMPUTE BR-RATE ROUNDED = BR-AMOUNT / 100",
            "           MOVE BR-RATE TO BR-RATE",
            "           COMPUTE BIG-TOTAL = BIG-TOTAL + BR-RATE",
        ]
    if n % 5 == 0:
        return [
            "           PERFORM VARYING BIG-INDEX FROM 1 BY 1",
            "                   UNTIL BIG-INDEX > 20",
            "               MOVE BIG-INDEX TO BR-T-CODE (BIG-INDEX)",
            "               MOVE BR-T-TEXT (BIG-INDEX) TO BR-NAME",
            "           END-PERFORM",
            "           MOVE 1 TO BIG-INDEX",
        ]
    return [
        "           ADD BR-AMOUNT TO BIG-TOTAL",
        "           MOVE BIG-TOTAL TO BR-AMOUNT",
        "           MOVE BR-KEY TO BIG-INDEX",
        "           ADD BR-MISSES TO BR-MISSES",
        "           SUBTRACT 1 FROM BR-MISSES",
    ]


def paragraph(n):
    """One paragraph. The last statement carries the full stop: a paragraph
    header ends the previous sentence only if that sentence was terminated,
    and GnuCOBOL rejects the file outright when it is not."""
    lines = [f"       P{n:04d}-STEP."]
    lines.extend(body(n))
    while len(lines) < PARAGRAPH_LINES - 1:
        lines.append(f"           MOVE {n} TO BR-KEY")
    if not lines[-1].rstrip().endswith('.'):
        lines[-1] = lines[-1].rstrip() + '.'
    lines.append("")                       # blank separator
    return lines


def build(target):
    driver = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. BIGPROG.",
        "       ENVIRONMENT DIVISION.",
        "       CONFIGURATION SECTION.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       COPY BIGCOPY.",
        "       PROCEDURE DIVISION.",
        "           MOVE 0 TO BIG-TOTAL",
        "           MOVE \"N\" TO BIG-SWITCH",
        "",                                # PERFORM range, filled in below
        "           DISPLAY BIG-TOTAL",
        "           STOP RUN.",
    ]
    assert len(driver) == DRIVER_LINES
    cpy = COPYBOOK.splitlines()
    room = target - DRIVER_LINES - len(cpy)
    n_par = max(1, room // PARAGRAPH_LINES)
    lines = list(driver)
    for n in range(1, n_par + 1):
        lines.extend(paragraph(n))
    lines[10] = f"           PERFORM P0001-STEP THRU P{n_par:04d}-STEP"
    # anything left over becomes a remark, so the total is exact
    while len(lines) + len(cpy) < target:
        lines.insert(11, "      *> padding to the requested line count")
    while len(lines) + len(cpy) > target:
        lines.pop()
    return lines, cpy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="/tmp/big")
    ap.add_argument("--lines", type=int, default=4207,
                    help='total lines across the program and its copybook')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    lines, cpy = build(a.lines)
    main_cbl = os.path.join(a.out, 'big.cbl')
    with open(main_cbl, 'w') as f:
        f.write("\n".join(lines) + "\n")
    # GnuCOBOL folds a COPY operand to upper case and then looks for a file
    # of exactly that name, so the copybook is written under both spellings.
    for name in ('bigcopy.cpy', 'BIGCOPY.cpy'):
        with open(os.path.join(a.out, name), 'w') as f:
            f.write(COPYBOOK)

    print(f"{main_cbl}: {len(lines)} lines")
    print(f"{os.path.join(a.out, 'bigcopy.cpy')}: {len(cpy)} lines")
    print(f"together: {len(lines) + len(cpy)} lines")


if __name__ == "__main__":
    main()
