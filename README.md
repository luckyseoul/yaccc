# YACCC

**Yet Another COBOL C compiler.** A COBOL compiler that translates COBOL 85
source (plus the common extensions from the 1989 intrinsic-function amendment
and later standards) into C, then builds a native executable with gcc or
clang, linked against a small C runtime library.

The name is the joke; the conformance results are not. It passes the NIST
CCVS85 suite — the one packaged by opensource COBOL — with zero failures:
every module matches the suite's reference summary exactly, including the
Report Writer and Debug modules. Its output matches GnuCOBOL 3.1.2 apart from
the deliberate differences listed below, and GnuCOBOL's own testsuite is run
as a compatibility check too.

```
$ ./yaccc examples/mandelbrot.cbl --run
```

## Results

### NIST CCVS85 conformance suite

Run with `make nist`. The first ten modules use the same program set as the
suite's reference `summary.txt`:

```
Module Programs Executed Error Crash   Pass Fail Deleted Inspect Total
------ -------- -------- ----- -----  ----- ---- ------- ------- -----
NC           92       92     0     0   4363    0       6      11  4380
SM           15       15     0     0    290    0       3       1   294
IC           24       24     0     0    246    0       4       0   250
SQ           81       81     0     0    512    0       6      81   599
RL           32       32     0     0   1827    0       5       0  1832
IX           39       39     0     0    507    0       1       0   508
ST           39       39     0     0    278    0       0       0   278
SG            5        5     0     0    193    0       0       0   193
OB            5        5     0     0     16    0       0       0    16
IF           42       42     0     0    732    0       0       0   732
RW            4        4     0     0     40    0       0       0    40
DB            9        9     0     0    386    0       4      27   417
Total       387      387     0     0   9390    0      29     120  9539
```

NC through IF match the reference summary line for line. "Deleted" tests are
removed by the suite itself. "Inspect" tests have no automatic pass/fail check:
their printed output has to be reviewed by eye, as for any compiler.

RW (Report Writer) and DB (Debug module) aren't part of the reference summary.
GnuCOBOL 3.1.2 gets the same counts on both. The DB programs run with the
object-time debugging switch on (`COB_SET_DEBUG=Y`), except DB102A, which
checks that debugging procedures stay inactive when it's off. DB205A needs the
Communication module and isn't run.

The reference run skips eight programs: SQ207M, SG102A, SG103A, SG201A–SG203A,
OBNC1M and OBNC2M. `make nist-all` includes them, and YACCC compiles and runs all
eight:

- **SG102A–SG203A** (ALTER and segmentation): 117 more tests pass.
- **OBNC2M**: 16 more tests pass.
- **OBNC1M**: 6 tests pass. Its 7th test executes `STOP "OPERATOR KILL OBNC1"`
  and passes only if an operator kills the job at that prompt, so it can't pass
  unattended.
- **SQ207M**: 8 tests that need visual inspection.

| | Programs | Pass | Fail | Deleted | Inspect | Total |
|---|---|---|---|---|---|---|
| `make nist-all` | 395 | 9529 | 1 | 29 | 128 | 9687 |

The NIST programs are module-split by opensource COBOL's `expand.pl`. They're
tracked in the opensourcecobol4j repository under `tests/cobol85`. `make nist`
fetches them into `third_party/` with a sparse clone (about 65 MB).

### Differential tests against GnuCOBOL

`tests/cases/` holds 63 programs covering moves, editing, arithmetic and
rounding modes, PERFORM, EVALUATE, STRING/UNSTRING/INSPECT, tables and SEARCH,
intrinsic functions (including the COBOL 2014 date functions and the
high-precision math), COPY and REPLACING, free format, DECIMAL-POINT IS COMMA,
ACCEPT, CALL and CANCEL, library routines and exception functions, ALTER,
declaratives, sequential, relative and indexed files (including READ PREVIOUS,
START FIRST/LAST and DELETE FILE), SORT, Report Writer and the Debug module,
conditional compilation inside a copybook, and report items placed without a
COLUMN clause.

- `make test` compares each program's output and every file it writes against
  recorded GnuCOBOL 3.1.2 baselines. The exceptions are `advmix`, `rw1`, `dbg2`
  and `dbg5`. They cover cases where YACCC deliberately differs from GnuCOBOL,
  so their baselines were verified by hand.
- Four tests added with the fixes below (`dirord`, `occurs01`, `rwsrc`, `rwlimit`)
  had no live `cobc` to record from, so their baselines were checked by hand
  against the standard. `rwlimit` is marked `.noref` because `cobc` rejects
  the program (it names a report group `PH`, which `cobc` reserves).
- Each case may add sidecars: `.in` (stdin), `.args` (the program's own
  arguments), `.flags` (compile flags), `.env` (environment), `.nocmp` (files
  not compared) and `.outfiles/` (files the program writes).
- `make test-ref` runs GnuCOBOL live instead (`cobc` must be on `PATH`); see
  `docs/gnucobol-oracle.md` for building one without root. Against GnuCOBOL
  3.1.2, 58 of the 63 run and all 58 pass; the five whose *test program*
  `cobc` itself rejects are skipped.

All 63 pass, built with gcc.

### GnuCOBOL 3.1.2 testsuite

`make gctest` runs the runtime tests of GnuCOBOL's own testsuite (the
`run_*.at` and `data_*.at` autotest files) with YACCC. It fetches them into
`third_party/` with a sparse clone of the 3.1.2 release tag.
`tests/gnucobol/run_gc.py` reads the autotest files directly and runs every
test that is built from COBOL sources with plain compile steps, comparing exit
status, standard output and the files the test checks.

```
Tests  Pass  Fail  Compile error  Skipped
  693   506     0              0      187
```

For comparison, GnuCOBOL 3.1.2's own cobc, run through the same harness
(`run_gc.py --cobc`), passes 441 and fails 22, mostly tests that depend on how
it was built or on the environment.

The run fails if a test recorded as passing in `tests/gnucobol/results.txt` no
longer passes. `make gctest-update` records a new baseline.

- **Skipped** tests need things the harness can't provide: cobc dialect options
  it has no equivalent for (`-fnotrunc` and so on), C code, a terminal (SCREEN
  SECTION), XML support, or shell scripting. `-std=` and JSON are provided, so
  tests gated on those now run.
- **Compile errors**: none. Every program the harness can build, YACCC builds.
- **Failures**: none. The last three were Report Writer page breaks; the
  Report Writer now builds its reports the way GnuCOBOL 3.1.2 does (a chain of
  print lines walked with a line cursor; see
  `docs/report-writer-page-model.md`) and matches `cobc` byte for byte on all
  24 runnable Report Writer tests and on the 527 report shapes
  `tests/rw_oracle.py --full` generates.

### Performance

`examples/mandelbrot.cbl` (COMP-5 and fixed-point arithmetic in tight loops) runs
in about 40 ms with YACCC. The GnuCOBOL 3.1.2 build at `-O2` takes about 133 ms.

A loop of 100,000 iterations of `Y ** 12.5`, `FUNCTION SQRT` and `FUNCTION SIN`
takes 4.2 seconds with YACCC and 136 seconds with GnuCOBOL, with identical
results.

## Requirements

- Python 3.11 or newer (tested with 3.11, 3.12 and 3.13). The compiler uses only
  the standard library.
- A C compiler with GNU extensions: gcc (tested with 13.3) or clang. The
  generated code uses computed `goto`, `__int128` and statement expressions.
- GnuCOBOL is **not** needed. It is used only as a reference by `make test-ref`.

The runtime library is built automatically into `runtime/libcobrt.a` the first
time you compile. `make` builds it ahead of time.

## Usage

```
./yaccc examples/payroll.cbl                 # builds ./payroll
./yaccc examples/payroll.cbl -o payroll      # explicit output name
./yaccc examples/mandelbrot.cbl --run        # build and run
./yaccc -C examples/bank.cbl                 # translate only: writes bank.c
./yaccc tests/cases/copy1.cbl -I tests/cases # copybook directory
```

To make an executable from several programs, pass all the sources on one
command line. The first source is the main program, and CALL / CANCEL resolve
the others by PROGRAM-ID, whether the name is a literal or held in a data item:

```
./yaccc examples/dayname.cbl examples/datefmt.cbl --run
```

| Option | Meaning |
|---|---|
| `-o FILE` | output file |
| `-C` | write the generated C and stop |
| `-free` / `-fixed` | source format; otherwise detected per file, and `>>SOURCE FORMAT` / `$SET SOURCEFORMAT` switch it |
| `-I DIR` | copybook directory (also `$COBCPY`) |
| `-D NAME[=VALUE]` | define a compilation variable for `>>IF` / `>>DEFINE ... AS PARAMETER` / `CONSTANT FROM` |
| `-O N` | C optimisation level (default 2) |
| `-g` | C debug information, with `#line` mapping so a debugger shows COBOL source |
| `--no-check` | drop subscript and reference-modification range checks |
| `-std DIALECT` | the choices the standards leave open (see below; default `default`) |
| `--binary-size 2-4-8 \| 1-2-4-8` | storage sizes for BINARY/COMP items (default: from the dialect) |
| `-fbinary-truncate` / `-fno-binary-truncate` | whether a BINARY item is limited to its PICTURE's digits |
| `-fmissing-period` / `-fno-missing-period` | whether a statement may stand where a `.` is required |
| `--debugging-mode` | compile as if `WITH DEBUGGING MODE` were specified: debugging lines and USE FOR DEBUGGING |
| `--keep-c` | keep the generated C file next to the executable |
| `--cc CC` | C compiler (default `$CC`, then gcc, then cc) |
| `--run` | run the program after building; its arguments follow, and ones that begin with `-` go after `--` |

An option this compiler does not implement is an error, never a silent no-op,
and neither is an unknown dialect name. A `-f` option overrides the same
setting from `-std`.

Arguments for the program being run follow `--run`; those that begin with `-`
follow `--`:

```
./yaccc prog.cbl --run 2026-10-28      # one argument to the program
./yaccc prog.cbl --run -- --verbose    # an option-like argument to the program
```

### Dialects

`-std` selects the choices a compiler has to make where the standards leave one
open, or where implementations have long differed. A dialect is not a claim of
conformance to a vendor's implementation: it sets the settings below, and
`-f` overrides the first three individually.

| Dialect | `binary-size` | `binary-truncate` | `missing-period` | `host-sign` | `non-numeric-zero` | `space-raw` | `pretty-display` | `arithmetic-osvs` |
|---|---|---|---|---|---|---|---|---|
| `default` (also `cobol85`, `cobol2002`, `cobol2014`) | 2-4-8 | on | no | no | no | no | on | no |
| `gnu` (GnuCOBOL) | 2-4-8 | on | yes | no | no | no | on | no |
| `ibm` | 2-4-8 | off | yes | yes | no | no | off | yes |
| `mf` (Micro Focus) | 1-2-4-8 | off | yes | no | yes | no | on | no |
| `acu` (ACUCOBOL) | 1-2-4-8 | on | yes | no | no | yes | on | no |

- **`binary-size`** — the byte widths `PIC 9(n) COMP` uses. Under `2-4-8`
  (IBM and the default here) a 2-digit COMP item occupies 2 bytes; under
  `1-2-4-8` (Micro Focus) it occupies 1.
- **`binary-truncate`** — whether a COMP item holds only the digits of its
  PICTURE. With truncation on, `PIC 9(2) COMP` given 12345 holds 45. With it
  off, the item holds what its bytes can represent (12345 in two bytes is
  0x3039, which reads back as 57) — the Micro Focus behaviour.
- **`missing-period`** — whether a statement may stand at a point where a `.`
  is required. The standards require the period; several implementations accept
  its absence, and so does YACCC under these dialects.
- **`host-sign`** — whether a signed PACKED-DECIMAL item whose sign nibble is
  `F` passes the NUMERIC class test, as on IBM mainframes.
- **`non-numeric-zero`** — whether MOVE of SPACE, QUOTE, LOW-VALUE, HIGH-VALUE
  or an alphanumeric literal that isn't all digits to a numeric item moves zero
  (with a warning), as Micro Focus does.
- **`space-raw`** — whether MOVE SPACE to a numeric DISPLAY item stores spaces,
  the way MOVE LOW-VALUE and HIGH-VALUE store their bytes.
- **`pretty-display`** — whether `DISPLAY` of a numeric item writes its decimal
  point and a leading sign. With it off the stored digits are written as they
  stand, a `SIGN LEADING` item puts its sign first and any other signed DISPLAY
  item puts it last, and a BINARY item is printed at the width of its storage
  rather than of its PICTURE. `-fnotrunc` turns this off too, as `cobc` does.
- **`arithmetic-osvs`** — whether a `COMPUTE` of more than one operation cuts
  each intermediate result back to a scale OS/VS COBOL derives from the
  operands: the larger operand scale for `+` and `-`, their sum for `*`, and
  for `/` the larger of the operand difference and the largest scale in the
  statement. `20500 / 0.9 / 33.45` into `PIC S9(7)V99` is 680.94 with it on
  and 680.95 with it off, and `cobc` warns about every statement it changes.

`yaccc -std=ibm prog.cbl` and `yaccc -std=mf prog.cbl` therefore produce
different binaries for the same source. Anything not listed above is the same
in every dialect.

Runtime environment:

| Variable | Meaning |
|---|---|
| `DD_name`, `dd_name`, `name` | file name for `ASSIGN TO name` when *name* is not a literal |
| `COB_SWITCH_n=ON\|OFF` | external switches (SPECIAL-NAMES `SWITCH-n`/`UPSI-n`) |
| `COB_SET_DEBUG=Y` | object-time debugging switch: USE FOR DEBUGGING procedures run only when it's set (`Y`, `YES`, `ON`, `TRUE` or `1`), as in GnuCOBOL |
| `COB_CURRENT_DATE` | fixed date and time for ACCEPT FROM DATE/DAY/TIME and the date functions, for reproducible test runs: `YYYY/MM/DD hh:mm:ss`, optionally followed by `+hhmm` (the time part is optional) |

Compile errors name the file and line and print the offending source line:

```
tests/cases/copy1.cbl:12: error: statement expected, found 'DISPLY'
  12 |            DISPLY "hi".
```

Runtime errors, such as a subscript out of range or an I/O error with no FILE
STATUS or USE procedure, print `cobrt: runtime error: file:line: ...` and exit
with status 1.

With `-g`, the generated C carries `#line` directives, so a debugger shows and
steps the COBOL source rather than the generated C:

```
$ ./yaccc -g examples/payroll.cbl
$ gdb ./payroll
(gdb) break payroll.cbl:120
Breakpoint 1 at 0x2bea: file payroll.cbl, line 120.
(gdb) run
Breakpoint 1, prog_1 (...) at payroll.cbl:120
120            DISPLAY "TOTAL: " WS-TOTAL.
```

## Language coverage

**Source.** Fixed, free and variable reference formats, continuation lines,
`*>` comments, debugging lines, comment-entries. COPY ... REPLACING (pseudo-text,
identifiers, literals, LEADING/TRAILING) and REPLACE / REPLACE OFF. Boolean
literals (`B"0101"`, `BX"5A"`), hexadecimal numeric literals (`H"FFFFFF"` is
16777215) and floating-point literals (`1.5E3`).

COPY is textual inclusion, and a copybook is expanded where it is written. A
`>>IF` inside a copybook therefore sees the compilation variables as they stand
at that COPY line, and a `>>DEFINE` in a copybook is visible to the lines that
follow it, exactly as if the text had been typed at that point.
Compiler directives: `>>DEFINE`, `>>IF` / `>>ELIF` / `>>ELSE` / `>>END-IF`,
`>>EVALUATE` / `>>WHEN` / `>>END-EVALUATE`, `>>SET CONSTANT`, `>>SOURCE FORMAT`,
and the Micro Focus forms `$IF` / `$ELSE` / `$END` / `$DISPLAY` / `$SET`.

**Environment division.**
- SPECIAL-NAMES: DECIMAL-POINT IS COMMA, CURRENCY SIGN, CLASS (with THRU), SYMBOLIC
  CHARACTERS, ALPHABET (NATIVE, STANDARD-1/2, EBCDIC or literal lists with
  THRU/ALSO), switches with ON/OFF STATUS, mnemonic names.
- OBJECT-COMPUTER PROGRAM COLLATING SEQUENCE.
- OPTIONS paragraph: DEFAULT ROUNDED MODE.
- FILE-CONTROL: ASSIGN, OPTIONAL, ORGANIZATION, ACCESS MODE, RECORD KEY,
  ALTERNATE RECORD KEY [WITH DUPLICATES], RELATIVE KEY, FILE STATUS (other
  clauses such as RESERVE and PADDING are accepted and ignored).
- I-O-CONTROL SAME RECORD AREA.

**Data division.**
- FILE, WORKING-STORAGE, LOCAL-STORAGE and LINKAGE sections.
- PICTURE with editing:
  - insertion, floating insertion, zero suppression, check protection, CR/DB;
  - `P` scaling in numeric and edited pictures;
  - BLANK WHEN ZERO, JUSTIFIED.
- USAGE: DISPLAY, BINARY/COMP/COMP-4, COMP-5/COMP-N, COMP-X,
  PACKED-DECIMAL/COMP-3, COMP-6, COMP-1/COMP-2, FLOAT-SHORT/FLOAT-LONG,
  BINARY-CHAR/SHORT/LONG/DOUBLE and their UNSIGNED- forms, INDEX, POINTER.
- SIGN LEADING/TRAILING [SEPARATE].
- USAGE ... PIC X(n) COMP-5 / COMP-X: Micro Focus n-byte binary numbers.
- Structure: OCCURS (nested, DEPENDING ON, ASCENDING/DESCENDING KEY, INDEXED BY),
  REDEFINES, RENAMES (66), condition names (88) with THRU and FALSE.
- VALUE clauses, GLOBAL and EXTERNAL items and files; `EXTERNAL AS "name"`
  shares storage under another name. A GLOBAL constant is visible to the
  programs contained in the one that declares it.
- RECURSIVE, INITIAL, COMMON, GLOBAL and EXTERNAL are context words: after
  PROGRAM-ID they are clauses, elsewhere they are ordinary data names.
- Constants: level 78 and `01 name CONSTANT AS ...` (COBOL 2002) with a literal,
  an arithmetic expression of literals and constants (integer valued, as in
  GnuCOBOL), `LENGTH OF` / `BYTE-LENGTH OF`, or `FROM` a compilation variable;
  constants can be used in PICTURE repetitions and OCCURS.
- FD: RECORD VARYING ... DEPENDING ON, LINAGE (FOOTING, TOP, BOTTOM, LINAGE-COUNTER),
  REPORT IS.

**Report Writer.**
- RD entries: CONTROLS (with FINAL), PAGE LIMIT with HEADING, FIRST DETAIL,
  LAST DETAIL and FOOTING, LINE LIMIT, and CODE.
- Report groups: REPORT HEADING, PAGE HEADING, CONTROL HEADING, DETAIL,
  CONTROL FOOTING, PAGE FOOTING and REPORT FOOTING, with:
  - LINE (absolute, PLUS, ON NEXT PAGE), NEXT GROUP, COLUMN (absolute, PLUS,
    LEFT / RIGHT / CENTER), SOURCE, VALUE;
  - an item with no COLUMN clause is placed directly after the previous item
    of its line;
  - report groups described by entries subordinate to an 01 entry without
    TYPE (a GnuCOBOL extension);
  - SUM ... UPON ... RESET ON, with subtotaling and rolling forward;
  - PRESENT WHEN / ABSENT WHEN, PRESENT / ABSENT AFTER [NEW] PAGE or a
    control, GROUP INDICATE, OCCURS with STEP and COLUMN lists.
- Statements: INITIATE, GENERATE (detail or summary reporting), TERMINATE,
  USE BEFORE REPORTING with SUPPRESS PRINTING.
- LINE-COUNTER and PAGE-COUNTER, qualified by report name when several
  reports are active.

**Debug module.**
- WITH DEBUGGING MODE compiles debugging lines and debugging sections; without
  it, both are treated as comments. Contained programs inherit it from the
  program that contains them.
- USE FOR DEBUGGING ON procedure-names, ALL PROCEDURES, file-names and
  identifiers, with or without ALL REFERENCES OF.
- DEBUG-ITEM: DEBUG-LINE, DEBUG-NAME (qualifiers joined by OF), DEBUG-SUB-1 to
  DEBUG-SUB-3 and DEBUG-CONTENTS (as long as the largest monitored item or
  record).
- Every cause of execution is reported: START PROGRAM, FALL THROUGH, PERFORM
  LOOP, GO TO, ALTER, SORT INPUT, SORT OUTPUT, MERGE OUTPUT and USE PROCEDURE.

**Procedure division.**
- Arithmetic and data movement: MOVE (incl. CORRESPONDING), ADD, SUBTRACT,
  MULTIPLY, DIVIDE (REMAINDER), COMPUTE (ON SIZE ERROR), INITIALIZE
  (REPLACING), SET (index, condition, switch).
- ROUNDED and the COBOL 2014 ROUNDED MODE phrase: AWAY-FROM-ZERO,
  NEAREST-AWAY-FROM-ZERO (the default), NEAREST-EVEN, NEAREST-TOWARD-ZERO,
  TOWARD-GREATER, TOWARD-LESSER, TRUNCATION and PROHIBITED.
- Entry: PROCEDURE DIVISION CHAINING items receive the command-line arguments.
- Control flow: IF, EVALUATE (ALSO, THRU, ANY, TRUE/FALSE), all PERFORM formats
  (THRU, TIMES, UNTIL, UNTIL EXIT, FOREVER, VARYING/AFTER, WITH TEST AFTER,
  inline), GO TO /
  DEPENDING ON, ALTER, NEXT SENTENCE, CONTINUE, EXIT [PARAGRAPH / SECTION /
  PERFORM [CYCLE] / PROGRAM [RETURNING]], STOP RUN [RETURNING / WITH ERROR or
  NORMAL STATUS], STOP literal, GOBACK [RETURNING].
- JSON: JSON GENERATE with NAME OF ... IS, SUPPRESS, COUNT IN, ON EXCEPTION /
  NOT ON EXCEPTION, OCCURS as arrays, REDEFINES resolved to the first item,
  JSON-CODE, and the `$SET DPC-IN-DATA` / `-fdpc-in-data` decimal comma.
- Strings and tables: STRING, UNSTRING (a literal or figurative constant is
  accepted as the sending item, as GnuCOBOL and Micro Focus do), INSPECT
  (TALLYING / REPLACING / CONVERTING, ALL / LEADING / FIRST / TRAILING,
  BEFORE/AFTER), SEARCH, SEARCH ALL.
- Terminal I/O and program calls: DISPLAY, EXHIBIT (NAMED / CHANGED),
  ACCEPT (OMITTED, and incl. FROM DATE/DAY/TIME/DAY-OF-WEEK/ENVIRONMENT),
  CALL (BY REFERENCE/CONTENT/VALUE, ON EXCEPTION, `CALL "SYSTEM"`,
  OPTIONAL parameters with `IF item OMITTED`), CANCEL.
- File I/O: OPEN, CLOSE (REEL/UNIT, NO REWIND, LOCK), READ (NEXT, PREVIOUS),
  WRITE (ADVANCING, END-OF-PAGE), REWRITE, DELETE, START (KEY, FIRST, LAST),
  WRITE FILE / REWRITE FILE, DELETE FILE.
- SORT / MERGE: USING, GIVING, INPUT/OUTPUT PROCEDURE, RELEASE, RETURN,
  COLLATING SEQUENCE; table SORT.
- Declaratives: USE [GLOBAL] AFTER ERROR on files and open modes, USE BEFORE
  REPORTING, USE FOR DEBUGGING.

**Files.**
- Organizations: sequential (fixed and variable length), line sequential,
  relative, and indexed with alternate keys and duplicates (duplicates are
  returned in WRITE/REWRITE order).
- Access modes: sequential, random and dynamic.
- FILE STATUS codes follow the standard, including 04/05/07/14/24/35/38/41–49.

**Programs.** Nested and contained programs (COMMON, INITIAL, GLOBAL names, USE
GLOBAL, and the standard's scope rules for CALL), RECURSIVE (CALL of an active
program that isn't RECURSIVE raises EC-PROGRAM-RECURSIVE-CALL, CANCEL of one is
an error), PROGRAM-ID ... AS "name", several source files and programs built
into one executable. Special registers RETURN-CODE, TALLY, SORT-RETURN,
WHEN-COMPILED and NUMBER-OF-CALL-PARAMETERS. Segmentation: an independent segment (50–99) returns to its initial
state whenever it's entered from another segment.

**CONTENT functions.** `FUNCTION CONTENT-LENGTH(pointer)` is the number of
bytes a POINTER addresses before its NUL, and 0 for a null pointer;
`FUNCTION CONTENT-OF(pointer[, length])` is those bytes, raising
EC-DATA-PTR-NULL for a null pointer and clearing the last exception on
success. A `Z"..."` literal ends with a NUL, which is what makes them useful
together.

**Intrinsic functions (103).** ABS, ACOS, ANNUITY, ASIN, ATAN, BYTE-LENGTH,
CHAR, COMBINED-DATETIME, CONCAT, CONCATENATE, COS, CURRENCY-SYMBOL, CURRENT-
DATE, DATE-OF-INTEGER, DATE-TO-YYYYMMDD, DAY-OF-INTEGER, DAY-TO-YYYYDDD, E,
EXCEPTION-FILE, EXCEPTION-LOCATION, EXCEPTION-STATEMENT, EXCEPTION-STATUS, EXP,
EXP10, FACTORIAL, FORMATTED-CURRENT-DATE, FORMATTED-DATE, FORMATTED-DATETIME,
FORMATTED-TIME, FRACTION-PART, HEX-OF, HIGHEST-ALGEBRAIC, INTEGER, INTEGER-OF-
BOOLEAN, INTEGER-OF-DATE, INTEGER-OF-DAY, INTEGER-OF-FORMATTED-DATE, INTEGER-
PART, LENGTH, LOCALE-COMPARE, LOCALE-DATE, LOCALE-TIME, LOCALE-TIME-FROM-
SECONDS, LOG, LOG10, LOWER-CASE, LOWEST-ALGEBRAIC, MAX, MEAN, MEDIAN, MIDRANGE,
MIN, MOD, MODULE-CALLER-ID, MODULE-DATE, MODULE-FORMATTED-DATE, MODULE-ID,
MODULE-NAME, MODULE-PATH, MODULE-SOURCE, MODULE-TIME, MONETARY-DECIMAL-POINT,
MONETARY-THOUSANDS-SEPARATOR, NUMERIC-DECIMAL-POINT, NUMERIC-THOUSANDS-
SEPARATOR, NUMVAL, NUMVAL-C, NUMVAL-F, ORD, ORD-MAX, ORD-MIN, PI, PRESENT-VALUE,
RANDOM, RANGE, REM, REVERSE, SECONDS-FROM-FORMATTED-TIME, SECONDS-PAST-MIDNIGHT,
SIGN, SIN, SQRT, STANDARD-DEVIATION, STORED-CHAR-LENGTH, SUBSTITUTE, SUBSTITUTE-
CASE, SUM, TAN, TEST-DATE-YYYYMMDD, TEST-DAY-YYYYDDD, TEST-FORMATTED-DATETIME,
TEST-NUMVAL, TEST-NUMVAL-C, TEST-NUMVAL-F, TRIM, TRIML, TRIMR, UPPER-CASE,
VARIANCE, WHEN-COMPILED, YEAR-TO-YYYY.

The trigonometric, logarithmic and exponential functions, SQRT, ANNUITY,
PRESENT-VALUE, VARIANCE, STANDARD-DEVIATION and `**` with a non-integer
exponent are computed in 640-bit fixed point and truncated to the 38
significant digits a result can hold, so a MOVE to an item with fewer
decimals gets the digits of the exact value. Function results are described
as GnuCOBOL describes them, so DISPLAY and MOVE to an alphanumeric item give
the same characters (`FUNCTION ORD("A")` displays `000000066`).

**Exceptions.** EXCEPTION-STATUS, EXCEPTION-STATEMENT, EXCEPTION-LOCATION and
EXCEPTION-FILE report the last exception condition: EC-I-O-* for unsuccessful
I/O statements, EC-ARGUMENT-FUNCTION for invalid function arguments,
EC-PROGRAM-NOT-FOUND and EC-PROGRAM-RECURSIVE-CALL for CALL (which takes ON
EXCEPTION for both), and EC-SIZE-OVERFLOW / EC-SIZE-ZERO-DIVIDE for arithmetic.

The size error condition exists whether or not the statement has ON SIZE
ERROR. With it, the receiving item is left unchanged; without it the value is
stored truncated and the exception is still raised, so `COMPUTE X = 10` on
`PIC 9` sets X to 0 and EXCEPTION-STATUS to EC-SIZE-OVERFLOW. `SET LAST
EXCEPTION TO OFF` clears the last condition.

**Pointers, BASED items.** A `USAGE POINTER` item holds an address.
`SET ADDRESS OF item TO <pointer>` rebinds a LINKAGE item to storage chosen at
run time, where the pointer is `ADDRESS OF x`, another POINTER item, or NULL;
`SET pointer TO ...` does the same for the pointer itself, and `INITIALIZE`
sets a pointer to NULL. Pointers compare against each other, against
`ADDRESS OF`, and against NULL, and can be passed to a CALL.

**Pointers, BASED items.** A level 01/77 item may be `BASED`: its storage is
allocated by `ALLOCATE item [INITIALIZED]` (the VALUE clauses apply when
`INITIALIZED` is given) and released by `FREE item`, which also clears the
pointer so `ADDRESS OF item = NULL` tests it. Using a BASED item before it is
allocated is a runtime error naming the item, not a wild write. `ALLOCATE n
CHARACTERS` allocates a block that is not bound to any item. `ADDRESS OF item`
compares against `NULL` or another `ADDRESS OF`, and may be passed to a CALL.

**User-defined functions.** `FUNCTION-ID` declares a program that returns a
value: its `RETURNING` item is a LINKAGE item, and a caller that names it in
`REPOSITORY. FUNCTION f.` may write `f(x)` or `f` wherever a value is expected,
including inside `COMPUTE`. Arguments are converted into temporaries of the
callee's parameter types before the call, because a BY REFERENCE call passes an
address and a literal of a different PICTURE would otherwise be read past its
end. A `FUNCTION-ID` program is not an entry point: the first `PROGRAM-ID` in
the file is the program that runs.

**XML GENERATE.** Writes the XML document for a data item into an
alphanumeric field. Groups become elements, `TYPE OF x IS ATTRIBUTE` makes an
item an attribute of its parent and `WITH ATTRIBUTES` does so for every
elementary item, `TYPE OF x IS CONTENT` writes the value into the parent's
content without a tag, `WITH XML-DECLARATION` prefixes `<?xml version="1.0"?>`,
and `NAMESPACE` / `NAMESPACE-PREFIX` put `xmlns:` on the root. Element names
keep the source case, with a leading `_` when the name starts with a digit.
`SUPPRESS [item | EVERY ELEMENT | EVERY ATTRIBUTE | EVERY NONNUMERIC] WHEN
<figurative>` omits items whose value is that figurative constant, and a group
left with nothing inside is written as `<x/>` or, at the top of a suppressed
subtree, omitted altogether. `XML PARSE` is not implemented, and the XML
exception conditions are not reported through `XML-CODE` beyond overflow.

**JSON GENERATE.** Writes the JSON document for a data item into an
alphanumeric receiving field. A group becomes an object, an elementary item a
string or a number according to its USAGE, OCCURS an array, and FILLER,
condition names, RENAMES and the later items of a REDEFINES set are not
generated. `NAME OF x IS 'y'` renames an item (and `NAME OF x IS OMITTED`
leaves out its name while keeping its members), `SUPPRESS` omits items, and a
group left with nothing to write is itself omitted. Alphanumeric values lose
their trailing spaces (leading ones for a JUSTIFIED item) and are escaped as
the standard requires; numeric values are written without leading zeros and
with the digits their PICTURE declares, so `PIC 99V999` holding 0.12 is
`0.120`. `COUNT IN` reports the length the document needed and JSON-CODE is 1
when it did not fit the receiving field. `JSON PARSE` is not implemented.

**Library routines.** CALL by name reaches these routines directly:
- bytes and text: CBL_AND, CBL_OR, CBL_NOR, CBL_XOR, CBL_IMP, CBL_NIMP, CBL_EQ,
  CBL_NOT, CBL_TOUPPER, CBL_TOLOWER, C$TOUPPER, C$TOLOWER, C$JUSTIFY,
  C$PRINTABLE, CBL_OC_DUMP;
- files and directories: CBL_CREATE_DIR, CBL_DELETE_DIR, CBL_CHANGE_DIR,
  CBL_GET_CURRENT_DIR, C$MAKEDIR, C$CHDIR, CBL_DELETE_FILE, C$DELETE,
  CBL_RENAME_FILE, CBL_COPY_FILE, C$COPY, CBL_CHECK_FILE_EXIST, C$FILEINFO, and
  the byte-stream files CBL_OPEN_FILE, CBL_CREATE_FILE, CBL_READ_FILE,
  CBL_WRITE_FILE, CBL_FLUSH_FILE, CBL_CLOSE_FILE;
- calls and processes: C$NARG, C$PARAMSIZE, C$CALLEDBY, C$GETPID, C$SLEEP,
  CBL_GC_NANOSLEEP, CBL_GC_FORK, CBL_GC_WAITPID, and `SYSTEM`.

### Not implemented

- SCREEN SECTION and COMMUNICATION SECTION.
- Report Writer: VARYING in report groups (GnuCOBOL 3.1.2 doesn't have it
  either).
- SYNCHRONIZED alignment: items are laid out packed, so a `POINTER, SYNC`
  item in a group is not aligned as it should be.
- ANY LENGTH is implemented for LINKAGE items: the size comes from the
  calling program's argument.
- JSON PARSE, XML PARSE, and `EXEC SQL`/CICS.
- Split keys on indexed files (a key made of several SOURCE items).
- Split keys, ENTRY, object-oriented COBOL, EXEC SQL/CICS.
- Dynamic loading: a CALLed program must be compiled into the same executable.
- Relative and indexed files are held in memory while open and written back on
  CLOSE. That's fine for batch-sized files, but there's no record locking or
  sharing between processes, and the indexed format is YACCC's own (not
  BDB/VBISAM compatible).

## Differences from GnuCOBOL

All of these were checked against GnuCOBOL 3.1.2:

1. **WRITE without ADVANCING after WRITE ... AFTER ADVANCING** starts a new
   line, as ISO's default AFTER ADVANCING 1 requires. GnuCOBOL appends the
   record to the line still open. (WRITE ... BEFORE ADVANCING after AFTER
   ADVANCING prints on that open line in both, as on a printer;
   `tests/cases/advmix.cbl`.)
2. **NUMVAL and NUMVAL-C with CR or DB** return a negative value, as the
   standard requires. GnuCOBOL 3.1.2 returns a positive one. NUMVAL-C also
   accepts a currency string of several characters (`"EUR"`), which GnuCOBOL
   3.1.2 rejects.
3. **Alphanumeric data with signs or non-digits moved to a numeric item**: the
   standard leaves the result undefined. YACCC reads the value the way NUMVAL
   does, so `" -42"` becomes -42. GnuCOBOL copies the characters as an
   unsigned integer.
4. **Numeric intrinsic function results** are described as in GnuCOBOL, with
   two exceptions. A value of 10 digits that fits in 32 bits keeps all its
   digits (GnuCOBOL 3.1.2 shows only the last nine). The irrational results
   (SQRT, LOG, SIN, ...) have 38 significant digits; GnuCOBOL computes about 96,
   so a DISPLAY of one shows fewer digits, and their last digits can differ.
5. **Report Writer.** Page layout, control breaks and the order groups print in
   are GnuCOBOL 3.1.2's, quirks included, since its testsuite and NIST both
   check them. Four standard rules that GnuCOBOL 3.1.2 doesn't apply are kept:
   - CONTROL HEADING FINAL is presented (GnuCOBOL never prints it);
   - `SUM ... UPON` adds only on GENERATEs of the named DETAIL groups, and
     `RESET ON` resets a counter at the named control (GnuCOBOL ignores both);
   - at TERMINATE the control footings see the control values of the last
     GENERATE, as the standard requires. GnuCOBOL uses whatever the program
     has moved into those fields since, which defeats the usual end-of-file
     HIGH-VALUES idiom.

   No test in either suite depends on these (`tests/cases/rw1.cbl` covers
   them).
6. **Debug module.** Before each debugging procedure YACCC space-fills
   DEBUG-ITEM, as the standard requires, and DEBUG-LINE always names the
   statement that caused it (`tests/cases/dbg2.cbl`). GnuCOBOL 3.1.2 differs in
   these ways:
   - it keeps DEBUG-SUB-n and DEBUG-CONTENTS from the previous debugging
     procedure, so a later PERFORM can report the contents of a data item
     instead of PERFORM LOOP;
   - it leaves DEBUG-LINE blank for START PROGRAM, and for a repeated PERFORM
     or a SORT OUTPUT PROCEDURE it reports the last statement executed instead
     of the PERFORM or SORT statement;
   - it doesn't run the debugging procedure of a READ ... INTO identifier;
   - it rejects USE FOR DEBUGGING in contained programs (`tests/cases/dbg5.cbl`).
7. **Micro Focus binary items.** `PIC X(n) COMP-X` shows all the digits its n
   bytes can hold (`PIC X(2) COMP-X` is 5 digits). GnuCOBOL shows fewer
   (4 digits for 2 bytes) and truncates values to them.
8. **WHEN-COMPILED register** has IBM's `MM/DD/YYhh.mm.ss` format; GnuCOBOL
   puts the day first.

## How it works

```
source ─► source.py ─► lexer.py ─► parser.py ─► codegen.py ─► C ─► gcc/clang ─► executable
          formats,     tokens,     AST           C with             + runtime/libcobrt.a
          continuation COPY/                     runtime calls
                       REPLACE
```

| File | Lines | Role |
|---|---|---|
| `lib/yaccc/source.py` | 272 | reference formats, continuations, directives, comment-entries, debugging lines |
| `lib/yaccc/lexer.py` | 515 | tokens, PICTURE strings, literals, COPY/REPLACE expansion |
| `lib/yaccc/parser.py` | 2,602 | recursive-descent parser to the AST (`nodes.py`, 638) |
| `lib/yaccc/data.py` | 510 | PICTURE analysis, USAGE resolution, storage layout |
| `lib/yaccc/codegen.py` | 3,627 | name resolution, C generation, typed fast paths |
| `lib/yaccc/rwgen.py` | 820 | REPORT SECTION analysis: print lines, report items, controls and SUM counters as tables, plus callbacks |
| `lib/yaccc/dbggen.py` | 466 | Debug module: DEBUG-ITEM and the USE FOR DEBUGGING hooks |
| `runtime/cobrt_core.c` | 2,573 | fields, moves, editing, decimal arithmetic, compare, DISPLAY/ACCEPT, CALL, exceptions, DEBUG-ITEM |
| `runtime/cobrt_io.c` | 1,555 | sequential, line sequential, relative, indexed, LINAGE, SORT/MERGE |
| `runtime/cobrt_rw.c` | 856 | Report Writer control system: the line cursor, paging, control breaks, INITIATE/GENERATE/TERMINATE |
| `runtime/cobrt_str.c` | 424 | STRING, UNSTRING, INSPECT |
| `runtime/cobrt_fn.c` | 678 | intrinsic functions |
| `runtime/cobrt_math.c` | 728 | 640-bit fixed point for SQRT, EXP, LOG, the trigonometric functions and `**` |
| `runtime/cobrt_dt.c` | 728 | FORMATTED-DATE/TIME/DATETIME and the other COBOL 2014 date functions, locale functions |
| `runtime/cobrt_sys.c` | 653 | library routines (CBL_..., C$...) |
| `runtime/cobrt.h` | 716 | runtime interface and inline fast paths |

Design choices:

- **Decimal arithmetic.** Arithmetic uses 128-bit scaled integers carrying an
  explicit scale (up to 38 digits), so results are exact; it never touches
  binary floating point except for the COMP-1/COMP-2 types and the
  transcendental functions.
  - ROUNDED rounds half away from zero unless a ROUNDED MODE says otherwise.
  - Division keeps 37 significant digits.
  - ON SIZE ERROR leaves the target unchanged; without it, high-order digits
    are truncated.
- **Typed fast paths.** When the operand types are known at compile time,
  COMPUTE/ADD/MOVE/compare on DISPLAY, COMP, COMP-5 and COMP-3 items compile to
  inline int64/int128 code with scales aligned statically. The general runtime
  path handles everything else.
- **PERFORM** uses an explicit frame stack and computed `goto` (a GCC/clang
  extension) within one C function per program. This gives exact COBOL semantics for PERFORM THRU, GO TO
  out of a performed range, overlapping performs and fall-through, and supports
  ALTER and segmentation resets.
- **Storage.** Data items live at fixed offsets in static records, as COBOL
  requires, with REDEFINES overlays and big-endian BINARY. Each field reference
  compiles to a pointer, a size and a static attribute record.

## Repository layout

```
yaccc                compiler entry point
LICENSE              MIT licence
lib/yaccc/           front end and code generator (Python)
runtime/             C runtime library
examples/            payroll report with control breaks, indexed-file bank ledger,
                     word-frequency count (table SORT), Mandelbrot set,
                     two-program CALL example (dayname + datefmt)
tests/cases/         differential tests and recorded GnuCOBOL baselines
tests/difftest.py    differential test runner
tests/nist/          NIST CCVS85 runner and the result logs of the runs above
tests/gnucobol/      GnuCOBOL testsuite runner, comparison tool and recorded results
tests/cli_test.py    compiler command-line tests
tests/provenance_test.py  licence checks: nothing GPL is vendored, every source
                     file carries SPDX, README credits GnuCOBOL (make provenance)
Makefile             make test | cli-test | provenance | test-ref | nist | nist-all | gctest | examples | clean
```

## Acknowledgements

YACCC's compatibility target is **GnuCOBOL**, and that debt deserves to be
stated plainly rather than implied.

- **No GnuCOBOL code is in this repository.** The compiler, the C runtime and
  every test program here were written for YACCC. GnuCOBOL is GPL-3.0 and
  YACCC is MIT; the two never mix in one tree, and that is deliberate.
- **Behaviour was learned by measuring GnuCOBOL, and in places by reading
  it.** Most of the compatibility work here was empirical: build GnuCOBOL 3.1.2
  from source, run the same program through `cobc` and through YACCC, and diff
  the results (that is what `tests/gnucobol/compare.py` does). For the Report
  Writer, GnuCOBOL's runtime and the report tables `cobc -C` generates were
  also read, because output alone did not explain where a page break lands.
  The model is written up in our own words in
  `docs/report-writer-page-model.md`, YACCC's implementation was written from
  that description, and `tests/rw_oracle.py` checks it against a live `cobc`.
  Reading a program to understand its behaviour, then writing your own
  implementation of that behaviour, is how every compatible reimplementation is
  built. Understanding is not copying: no GnuCOBOL source text, function body
  or comment was translated into this tree.
- **That claim is checked, not asserted.** `make provenance` fails the build on
  a vendored file, a GPL notice, a missing SPDX tag, or a distinctive GnuCOBOL
  function name. A grep cannot see a translation that renamed everything, so
  `make provenance-deep` measures the code itself: for every file under
  `runtime/`, the fraction of its 12-token runs that also occur anywhere in
  GnuCOBOL's `libcob`, failing above 1.5%. Idiom — a linked-list walk, two
  adjacent setters — stays under 1%; the first Report Writer port measured
  2.1% and was restructured until it did not. It reads `third_party/gnucobol`
  (fetched by `make gctest`) or whatever `GNUSRC` names, and skips when
  neither is present.
- **GnuCOBOL's testsuite is fetched, not vendored.** `make gctest` sparse-clones
  the 3.1.2 release tag into `third_party/`, which is `.gitignore`d and contains
  zero tracked files (checked: `git ls-files third_party` is empty). That suite
  is GnuCOBOL's copyrighted work under GPL-3.0; if you run it, GPL-3.0 code
  lands on your disk and GnuCOBOL's licence governs it, not this one. The
  recorded results in `tests/gnucobol/results.txt` are YACCC's own run log,
  keyed by that suite's test titles.
- **The oracle.** `docs/gnucobol-oracle.md` explains how to build GnuCOBOL
  locally so `make test-ref` and `tests/gnucobol/compare.py` can diff YACCC
  against the real thing. GnuCOBOL's authors built the reference against which
  every claim in this README was measured.
- **NIST CCVS85** likewise supplies the conformance suite under
  `third_party/opensourcecobol4j`; it is fetched for the same reason, with the
  same distinction between running it and distributing it.

If you redistribute a build of YACCC, nothing here obliges you to credit
GnuCOBOL -- it is not a derivative work of GnuCOBOL and its licence does not
reach this code. Crediting it is still the honest thing to do, because without
GnuCOBOL there would have been nothing to be compatible *with*.

## License

MIT. See [LICENSE](LICENSE).

## Open conformance work

No test in the GnuCOBOL 3.1.2 testsuite fails. The notes below record how the
last failures were fixed, because the measurements in them are what the fixes
were built on.

To see any test side by side with `cobc`:

```
export PATH=/tmp/gcinst/bin:$PATH LD_LIBRARY_PATH=/tmp/gcinst/lib
python3 tests/gnucobol/compare.py "Sample Payroll Report"
make gctest          # the gate: fails if a recorded PASS stops passing
```

### 1. Report Writer page breaks *(fixed)*

`Sample Payroll Report`, `Sample Inventory Report` and `Next Group Next Page`
were the last three failures. YACCC's Report Writer used to place page breaks
with rules measured from `cobc`'s output; they fit 21 of the 25 Report Writer
tests and disagreed with `cobc` on 128 of the 131 shapes `tests/rw_oracle.py`
generates. Three ports of a page cursor scored lower still, because they kept
YACCC's model of a report as a typed tree of groups and worked from a
description of a later GnuCOBOL.

What fixed it was building the report the way 3.1.2 does: one chain of print
lines (an 01 entry or a LINE entry each) walked by group type, item lists that
stop at the next LINE entry, controls minor first, a hidden counter per SUM
entry, and a line cursor that each GENERATE advances on entry and steps back on
exit. `cobc -C` shows those tables directly, and a live `cobc` 3.1.2 checks
every shape. Three non-geometry rules turned out to matter as much as the
cursor:

- a report item with SUM, used in arithmetic or as a MOVE's sending item, is
  its sum counter (a USE BEFORE REPORTING procedure computes from the total
  about to print), while DISPLAY and SOURCE see the item as last printed;
- a second absolute `LINE n` in one group is dropped and joins the line
  before it;
- indexed SOURCE items are taken when the GENERATE starts, for every group.

`docs/report-writer-page-model.md` describes the model in full.

### 2. FLOAT-DECIMAL-16 / FLOAT-DECIMAL-34 *(fixed)*

`run_misc.at:11767`. YACCC maps both to `double` (`lib/yaccc/data.py:392`), so
it prints double precision. `cobc` holds a real IEEE 754 decimal64/decimal128
and prints every digit:

```
A: 9216586.861751152073732718894009216     (FLOAT-DECIMAL-34, 34 digits)
A: 9216586.861751152                       (FLOAT-DECIMAL-16, 16 digits)
FD34: 99.33333333333333333333333333333333 IS OK
FD16: 99.33333333333333 IS OK
FD16: after 99E369  SIZE ERROR     (overflow; underflow 99E-398)
FD34: after 99E6111 SIZE ERROR     (underflow 99E-6176)
```

This needs a real decimal-float type (BID or DPD in `runtime/`), arithmetic on
it, and DISPLAY printing all its digits -- a genuine feature, not a bug fix.
Everything else in the float family already passes, so the current `double`
mapping is only wrong for these two USAGEs.

### 3. CALL BY VALUE numeric literal WITH SIZE *(fixed)*

`run_extensions.at:1889`. The caller passes `BY VALUE 4 0 0 1 0` (automatic
size) or `BY VALUE 1 SIZE 1 2 0 0 0`; the callee declares
`USING BY VALUE LEN SIZE 1 VAR-1 SIZE 2 VAR-2 SIZE 4 VAR-4 SIZE 8 VAR-8` and
selects on `LEN`. YACCC prints `1: +000` twice; expected is
`4: +0000000001`, then `1: +002`, `2: +00003`, `4: +0000000004`,
`8: +00000000000000000005`, ... (12 lines). The first argument's automatic size
is being computed as 1 byte instead of the literal's natural width, so the
callee takes its `WHEN 1` branch. Involved: the `BY VALUE ... SIZE` clauses in
`lib/yaccc/parser.py` (around line 1560 for the callee, 2800 for the caller),
`prog.using_sizes`, and the `BY VALUE` argument sizing in `g_Call`
(`lib/yaccc/codegen.py`). Note that GnuCOBOL's own documentation calls its
parameter passing here unfinished, so match `cobc`'s observed behaviour rather
than the standard.

### 4. COMP-4 No Truncate *(fixed)*

`data_binary.at:1322`, compiled with `-fnotrunc`. Under that flag `cobc` ignores
the PICTURE's decimal point for a BINARY item, both when storing and when
reading back:

```
PIC 9V99 COMP-4   MOVE 0.12 -> "00012"   MOVE 9.85 -> "00985"   (5 digits: capacity)
PIC  V99 COMP-4   MOVE 0.12 -> "012"     MOVE 9.85 -> "217"     (985 truncated to 1 byte)
PIC 9V99 DISPLAY  MOVE 0.12 -> "0.12"    (unaffected)
```

So `MOVE 9.85` stores the digits `985` (not the rounded value), `DISPLAY` prints
them with no point, and a comparison against a DISPLAY item sees `217`, not
`0.85`. YACCC applies the scale, so it prints `0.85`/`9.85` and reports the two
values as equal. The flag's model is "a scaled BINARY item behaves as its
digits without the point", which has to apply to MOVE, DISPLAY and comparison
alike; the pieces are `binary_truncate` in `lib/yaccc/data.py` (the capacity
digits rule already there for unscaled items) and the scale used by
`cob_display`/`cob_d_get` in `runtime/cobrt_core.c`.

### 5. OS/VS arithmetic, error procedures, and INITIATE *(fixed)*

Three failures that had nothing to do with Report Writer page geometry:

- **`OSVS Arithmetic Test (2)`** (`run_misc.at:11235`, `-std=ibm`). `cobc`
  truncates each intermediate result of a `COMPUTE` to a scale derived from the
  operands and the receiver; YACCC kept full precision and so ended up with a
  different last digit. The scales were read out of `decimal_compute` in
  `cobc/typeck.c`: the larger operand scale for `+` and `-`, the sum for `*`,
  and for `/` the larger of the operand difference and the largest scale in the
  statement (the receiver included). Only *intermediate* results are cut --
  the outermost one must reach the receiving item intact, or `ROUNDED` has
  nothing left to round. Measured both ways: `20500 / 0.9 / 33.45` into
  `PIC S9(7)V99` is 680.94 cut, 680.95 uncut, and `RES ROUNDED` over the same
  chain is 680.95, which is only reachable if the last division keeps its
  digits. Now `arithmetic-osvs` in `lib/yaccc/dialect.py`, with `cobc`'s
  warning; `dec_osvs()` in `lib/yaccc/codegen.py` does the cutting.
- **`System routine CBL_ERROR_PROC (2)`** (`run_extensions.at:4592`). The
  error procedure ran and printed the right six lines, and then the runtime
  carried on: it called the next handler and printed `libcob: error:` as well.
  `cob_runtime_error` treats a handler's return value as "keep going": the
  generated ENTRY returns its program's `RETURN-CODE`, so a handler that exits
  with zero has handled the error. `cob_fatal` in `runtime/cobrt_core.c` now
  stops the chain and suppresses the standard message in that case, and exits
  with status 1 as `cobc` does.
- **`Report PRESENT AFTER`** (`run_reportwriter.at:8948`). YACCC required the
  report's file to be open at `INITIATE` and stopped with "file OUT-FILE is not
  open"; the program `INITIATE`s the report first and `OPEN`s the file after.
  `cob_report_initiate` in `cobc`'s `reportio.c` never looks at the file, so
  neither does YACCC's now: the write path still reports a file that is closed
  when a line is actually due.

### Things in this area that are *not* worth "fixing"

- `cobc`'s `-fnotrunc` on a scaled PICTURE is a quirk the standard does not
  describe; matching it is only worth it because a test asserts it.
- NATIONAL (`PIC N`) is stored one byte per character with two bytes per
  character of width, because that is what 3.1.2 does and what its tests
  compare against; it is not UTF-16.
- GnuCOBOL 3.1.2's Report Writer quirks (a control heading for a major control
  also prints the minor controls' headings; a NEXT GROUP on a DETAIL with a
  single LINE entry is ignored; ABSENT WHEN prints when the condition is
  *true*) are reproduced, not fixed: the testsuite and NIST were written
  against them.
