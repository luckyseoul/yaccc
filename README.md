# cobolc

A COBOL compiler. `cobolc` translates COBOL 85 source (plus the common
extensions from the 1989 intrinsic-function amendment and later standards) into C,
then builds a native executable with gcc or clang, linked against a small C
runtime library.

It passes the NIST CCVS85 conformance suite as packaged by opensource COBOL.
Every module matches the suite's reference summary exactly, with zero
failures. On its own differential test programs, its output matches GnuCOBOL
3.1.2 apart from the deliberate differences listed below.

```
$ ./cobolc examples/mandelbrot.cbl --run
```

## Results

### NIST CCVS85 conformance suite

Run with `make nist`, which uses the same program set as the suite's reference
`summary.txt`:

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
Total       374      374     0     0   8964    0      25      93  9082
```

This table matches the reference summary line for line. "Deleted" tests are
removed by the suite itself. "Inspect" tests have no automatic pass/fail check:
their printed output has to be reviewed by eye, as for any compiler.

The reference run skips eight programs: SQ207M, SG102A, SG103A, SG201A–SG203A,
OBNC1M and OBNC2M. `make nist-all` includes them, and cobolc compiles and runs all
eight:

- **SG102A–SG203A** (ALTER and segmentation): 117 more tests pass.
- **OBNC2M**: 16 more tests pass.
- **OBNC1M**: 6 tests pass. Its 7th test executes `STOP "OPERATOR KILL OBNC1"`
  and passes only if an operator kills the job at that prompt, so it can't pass
  unattended.
- **SQ207M**: 8 tests that need visual inspection.

| | Programs | Pass | Fail | Deleted | Inspect | Total |
|---|---|---|---|---|---|---|
| `make nist-all` | 382 | 9103 | 1 | 25 | 101 | 9230 |

The NIST programs are module-split by opensource COBOL's `expand.pl`. They're
tracked in the opensourcecobol4j repository under `tests/cobol85`. `make nist`
fetches them into `third_party/` with a sparse clone (about 65 MB).

### Differential tests against GnuCOBOL

`tests/cases/` holds 27 programs covering moves, editing, arithmetic, PERFORM,
EVALUATE, STRING/UNSTRING/INSPECT, tables and SEARCH, intrinsic functions, COPY
and REPLACING, free format, ACCEPT, CALL and CANCEL, ALTER, declaratives,
sequential, relative and indexed files, and SORT.

- `make test` compares each program's output and every file it writes against
  recorded GnuCOBOL 3.1.2 baselines. The exception is `advmix`, which tests a
  deliberate difference and has its own baseline.
- `make test-ref` runs GnuCOBOL live instead (`cobc` must be on `PATH`).

All 27 pass in both modes, built with gcc and with clang.

### Performance

`examples/mandelbrot.cbl` (COMP-5 and fixed-point arithmetic in tight loops) runs
in about 40 ms with cobolc. The GnuCOBOL 3.1.2 build at `-O2` takes about 133 ms.

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
./cobolc examples/payroll.cbl                 # builds ./payroll
./cobolc examples/payroll.cbl -o payroll      # explicit output name
./cobolc examples/mandelbrot.cbl --run        # build and run
./cobolc -C examples/bank.cbl                 # translate only: writes bank.c
./cobolc tests/cases/copy1.cbl -I tests/cases # copybook directory
```

To make an executable from several programs, pass all the sources on one
command line. The first source is the main program, and CALL / CANCEL resolve
the others by PROGRAM-ID, whether the name is a literal or held in a data item:

```
./cobolc examples/dayname.cbl examples/datefmt.cbl --run
```

| Option | Meaning |
|---|---|
| `-o FILE` | output file |
| `-C` | write the generated C and stop |
| `-free` / `-fixed` | source format; otherwise detected per file, and `>>SOURCE FORMAT` / `$SET SOURCEFORMAT` switch it |
| `-I DIR` | copybook directory (also `$COBCPY`) |
| `-O N` | C optimisation level (default 2) |
| `-g` | C debug information |
| `--no-check` | drop subscript and reference-modification range checks |
| `--binary-size 2-4-8 \| 1-2-4-8` | storage sizes for BINARY/COMP items (default 2-4-8, as IBM) |
| `--debugging-mode` | compile `D` debugging lines |
| `--keep-c` | keep the generated C file next to the executable |
| `--cc CC` | C compiler (default `$CC`, then gcc, then cc) |
| `--run` | run the program after building; remaining arguments are passed to it |

Runtime environment:

| Variable | Meaning |
|---|---|
| `DD_name`, `dd_name`, `name` | file name for `ASSIGN TO name` when *name* is not a literal |
| `COB_SWITCH_n=ON\|OFF` | external switches (SPECIAL-NAMES `SWITCH-n`/`UPSI-n`) |

Runtime errors, such as a subscript out of range or an I/O error with no FILE
STATUS or USE procedure, print `cobrt: runtime error: file:line: ...` and exit
with status 1.

## Language coverage

**Source.** Fixed, free and variable reference formats, continuation lines,
`*>` comments, debugging lines, comment-entries. COPY ... REPLACING (pseudo-text,
identifiers, literals, LEADING/TRAILING) and REPLACE / REPLACE OFF.

**Environment division.**
- SPECIAL-NAMES: DECIMAL-POINT IS COMMA, CURRENCY SIGN, CLASS (with THRU), SYMBOLIC
  CHARACTERS, ALPHABET (NATIVE, STANDARD-1/2 or literal lists with THRU/ALSO),
  switches with ON/OFF STATUS, mnemonic names.
- OBJECT-COMPUTER PROGRAM COLLATING SEQUENCE.
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
- USAGE: DISPLAY, BINARY/COMP/COMP-4, COMP-5, COMP-X, PACKED-DECIMAL/COMP-3,
  COMP-1/COMP-2, INDEX.
- SIGN LEADING/TRAILING [SEPARATE].
- Structure: OCCURS (nested, DEPENDING ON, ASCENDING/DESCENDING KEY, INDEXED BY),
  REDEFINES, RENAMES (66), condition names (88) with THRU and FALSE.
- VALUE clauses, GLOBAL and EXTERNAL items and files.
- FD: RECORD VARYING ... DEPENDING ON, LINAGE (FOOTING, TOP, BOTTOM, LINAGE-COUNTER).

**Procedure division.**
- Arithmetic and data movement: MOVE (incl. CORRESPONDING), ADD, SUBTRACT,
  MULTIPLY, DIVIDE (REMAINDER), COMPUTE (ROUNDED, ON SIZE ERROR), INITIALIZE
  (REPLACING), SET (index, condition, switch).
- Control flow: IF, EVALUATE (ALSO, THRU, ANY, TRUE/FALSE), all PERFORM formats
  (THRU, TIMES, UNTIL, VARYING/AFTER, WITH TEST AFTER, inline), GO TO /
  DEPENDING ON, ALTER, NEXT SENTENCE, CONTINUE, EXIT [PARAGRAPH / SECTION /
  PERFORM / PROGRAM], STOP RUN, STOP literal, GOBACK.
- Strings and tables: STRING, UNSTRING, INSPECT (TALLYING / REPLACING /
  CONVERTING, BEFORE/AFTER), SEARCH, SEARCH ALL.
- Terminal I/O and program calls: DISPLAY, ACCEPT (incl. FROM DATE/DAY/TIME/
  DAY-OF-WEEK/ENVIRONMENT), CALL (BY REFERENCE/CONTENT/VALUE, ON EXCEPTION,
  `CALL "SYSTEM"`), CANCEL.
- File I/O: OPEN, CLOSE (REEL/UNIT, NO REWIND, LOCK), READ, WRITE (ADVANCING,
  END-OF-PAGE), REWRITE, DELETE, START.
- SORT / MERGE: USING, GIVING, INPUT/OUTPUT PROCEDURE, RELEASE, RETURN,
  COLLATING SEQUENCE; table SORT.
- Declaratives: USE [GLOBAL] AFTER ERROR on files and open modes.

**Files.**
- Organizations: sequential (fixed and variable length), line sequential,
  relative, and indexed with alternate keys and duplicates (duplicates are
  returned in WRITE/REWRITE order).
- Access modes: sequential, random and dynamic.
- FILE STATUS codes follow the standard, including 04/05/07/14/24/35/38/41–49.

**Programs.** Nested and contained programs (COMMON, INITIAL, GLOBAL names, USE
GLOBAL), RECURSIVE, several source files and programs built into one
executable. Segmentation: an independent segment (50–99) returns to its initial
state whenever it's entered from another segment.

**Intrinsic functions (67).** ABS, ACOS, ANNUITY, ASIN, ATAN, BYTE-LENGTH,
CHAR, CONCATENATE, COS, CURRENT-DATE, DATE-OF-INTEGER, DATE-TO-YYYYMMDD,
DAY-OF-INTEGER, DAY-TO-YYYYDDD, E, EXP, EXP10, FACTORIAL, FRACTION-PART, HEX-OF,
INTEGER, INTEGER-OF-BOOLEAN, INTEGER-OF-DATE, INTEGER-OF-DAY, INTEGER-PART,
LENGTH, LOG, LOG10, LOWER-CASE, MAX, MEAN, MEDIAN, MIDRANGE, MIN, MOD,
MODULE-NAME, NUMVAL, NUMVAL-C, NUMVAL-F, ORD, ORD-MAX, ORD-MIN, PI,
PRESENT-VALUE, RANDOM, RANGE, REM, REVERSE, SECONDS-PAST-MIDNIGHT, SIGN, SIN,
SQRT, STANDARD-DEVIATION, STORED-CHAR-LENGTH, SUBSTITUTE, SUM, TAN,
TEST-DATE-YYYYMMDD, TEST-DAY-YYYYDDD, TEST-NUMVAL, TRIM, TRIML, TRIMR,
UPPER-CASE, VARIANCE, WHEN-COMPILED, YEAR-TO-YYYY.

### Not implemented

- REPORT SECTION (Report Writer), SCREEN SECTION and COMMUNICATION SECTION.
- Pointers: ADDRESS OF, BASED, SET ADDRESS OF.
- READ PREVIOUS, START FIRST/LAST, split keys, the EBCDIC alphabet, ENTRY,
  object-oriented COBOL, EXEC SQL/CICS.
- Dynamic loading: a CALLed program must be compiled into the same executable.
- Relative and indexed files are held in memory while open and written back on
  CLOSE. That's fine for batch-sized files, but there's no record locking or
  sharing between processes, and the indexed format is cobolc's own (not
  BDB/VBISAM compatible).

## Differences from GnuCOBOL

All of these were checked against GnuCOBOL 3.1.2:

1. **WRITE without ADVANCING after WRITE ... AFTER ADVANCING** starts a new
   line, as ISO's default AFTER ADVANCING 1 requires. GnuCOBOL appends the
   record to the line still open (`tests/cases/advmix.cbl`).
2. **NUMVAL-C with CR or DB** returns a negative value, as the standard
   requires. GnuCOBOL 3.1.2 returns a positive one.
3. **Alphanumeric data with signs or non-digits moved to a numeric item**: the
   standard leaves the result undefined. cobolc reads the value the way NUMVAL
   does, so `" -42"` becomes -42. GnuCOBOL copies the characters as an
   unsigned integer.
4. **DISPLAY of a numeric intrinsic function result** prints the value in its
   shortest form (`3`, `1.4142135623730950472`). GnuCOBOL prints a fixed width
   or up to 96 digits.

## How it works

```
source ─► source.py ─► lexer.py ─► parser.py ─► codegen.py ─► C ─► gcc/clang ─► executable
          formats,     tokens,     AST           C with             + runtime/libcobrt.a
          continuation COPY/                     runtime calls
                       REPLACE
```

| File | Lines | Role |
|---|---|---|
| `compiler/source.py` | 238 | reference formats, continuations, directives, comment-entries |
| `compiler/lexer.py` | 507 | tokens, PICTURE strings, literals, COPY/REPLACE expansion |
| `compiler/parser.py` | 2,312 | recursive-descent parser to the AST (`nodes.py`, 582) |
| `compiler/data.py` | 486 | PICTURE analysis, USAGE resolution, storage layout |
| `compiler/codegen.py` | 3,161 | name resolution, C generation, typed fast paths |
| `runtime/cobrt_core.c` | 2,065 | fields, moves, editing, decimal arithmetic, compare, DISPLAY/ACCEPT, CALL |
| `runtime/cobrt_io.c` | 1,457 | sequential, line sequential, relative, indexed, LINAGE, SORT/MERGE |
| `runtime/cobrt_str.c` | 424 | STRING, UNSTRING, INSPECT |
| `runtime/cobrt_fn.c` | 734 | intrinsic functions |
| `runtime/cobrt.h` | 543 | runtime interface and inline fast paths |

Design choices:

- **Decimal arithmetic.** Arithmetic uses 128-bit scaled integers carrying an
  explicit scale (up to 38 digits), so results are exact; it never touches
  binary floating point except for the COMP-1/COMP-2 types and the
  transcendental functions.
  - ROUNDED rounds half away from zero.
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
cobolc               compiler entry point
compiler/            front end and code generator (Python)
runtime/             C runtime library
examples/            payroll report with control breaks, indexed-file bank ledger,
                     word-frequency count (table SORT), Mandelbrot set,
                     two-program CALL example (dayname + datefmt)
tests/cases/         differential tests and recorded GnuCOBOL baselines
tests/difftest.py    differential test runner
tests/nist/          NIST CCVS85 runner and the result logs of the runs above
Makefile             make test | test-ref | nist | nist-all | examples | clean
```
