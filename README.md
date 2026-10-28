# cobolc

A COBOL compiler. `cobolc` translates COBOL 85 source (plus the common
extensions from the 1989 intrinsic-function amendment and later standards) into C,
then builds a native executable with gcc or clang, linked against a small C
runtime library.

It passes the NIST CCVS85 conformance suite as packaged by opensource COBOL.
Every module matches the suite's reference summary exactly, with zero
failures, and it also passes the suite's Report Writer and Debug modules. On
its own differential test programs, its output matches GnuCOBOL 3.1.2 apart
from the deliberate differences listed below. GnuCOBOL's own testsuite is run
as a compatibility check as well.

```
$ ./cobolc examples/mandelbrot.cbl --run
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
| `make nist-all` | 395 | 9529 | 1 | 29 | 128 | 9687 |

The NIST programs are module-split by opensource COBOL's `expand.pl`. They're
tracked in the opensourcecobol4j repository under `tests/cobol85`. `make nist`
fetches them into `third_party/` with a sparse clone (about 65 MB).

### Differential tests against GnuCOBOL

`tests/cases/` holds 42 programs covering moves, editing, arithmetic and
rounding modes, PERFORM, EVALUATE, STRING/UNSTRING/INSPECT, tables and SEARCH,
intrinsic functions (including the COBOL 2014 date functions and the
high-precision math), COPY and REPLACING, free format, DECIMAL-POINT IS COMMA,
ACCEPT, CALL and CANCEL, library routines and exception functions, ALTER,
declaratives, sequential, relative and indexed files (including READ PREVIOUS,
START FIRST/LAST and DELETE FILE), SORT, Report Writer and the Debug module.

- `make test` compares each program's output and every file it writes against
  recorded GnuCOBOL 3.1.2 baselines. The exceptions are `advmix`, the three
  Report Writer tests (`rw1`–`rw3`), `dbg2` and `dbg5`. They cover cases where
  cobolc deliberately differs from GnuCOBOL, so their baselines were verified
  by hand.
- `make test-ref` runs GnuCOBOL live instead (`cobc` must be on `PATH`).

All 42 pass in both modes, built with gcc and with clang.

### GnuCOBOL 3.1.2 testsuite

`make gctest` runs the runtime tests of GnuCOBOL's own testsuite (the
`run_*.at` and `data_*.at` autotest files) with cobolc. It fetches them into
`third_party/` with a sparse clone of the 3.1.2 release tag.
`tests/gnucobol/run_gc.py` reads the autotest files directly and runs every
test that is built from COBOL sources with plain compile steps, comparing exit
status, standard output and the files the test checks.

```
Tests  Pass  Fail  Compile error  Skipped
  693   362    20             96      215
```

For comparison, GnuCOBOL 3.1.2's own cobc, run through the same harness
(`run_gc.py --cobc`), passes 441 and fails 22, mostly tests that depend on how
it was built or on the environment.

The run fails if a test recorded as passing in `tests/gnucobol/results.txt` no
longer passes. `make gctest-update` records a new baseline.

- **Skipped** tests need things the harness can't provide: cobc dialect options
  (`-std=ibm`, `-fnotrunc` and so on), C code, a terminal (SCREEN SECTION),
  XML or JSON support, or shell scripting.
- **Compile errors** are mostly GnuCOBOL extensions and COBOL 2002/2014
  features cobolc doesn't have yet: pointers and BASED items, ANY LENGTH,
  CONSTANT entries and constant expressions, `>>IF`/`>>DEFINE`, FUNCTION-ID,
  TYPEDEF, COMP-6 and some Report Writer syntax.
- **Failures** include the deliberate differences listed below (WRITE
  ADVANCING, Debug module, LINAGE page geometry), national (UTF-16) data,
  file sharing between processes and a few library routines.

### Performance

`examples/mandelbrot.cbl` (COMP-5 and fixed-point arithmetic in tight loops) runs
in about 40 ms with cobolc. The GnuCOBOL 3.1.2 build at `-O2` takes about 133 ms.

A loop of 100,000 iterations of `Y ** 12.5`, `FUNCTION SQRT` and `FUNCTION SIN`
takes 4.2 seconds with cobolc and 136 seconds with GnuCOBOL, with identical
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
| `--debugging-mode` | compile as if `WITH DEBUGGING MODE` were specified: debugging lines and USE FOR DEBUGGING |
| `--keep-c` | keep the generated C file next to the executable |
| `--cc CC` | C compiler (default `$CC`, then gcc, then cc) |
| `--run` | run the program after building; remaining arguments are passed to it |

Runtime environment:

| Variable | Meaning |
|---|---|
| `DD_name`, `dd_name`, `name` | file name for `ASSIGN TO name` when *name* is not a literal |
| `COB_SWITCH_n=ON\|OFF` | external switches (SPECIAL-NAMES `SWITCH-n`/`UPSI-n`) |
| `COB_SET_DEBUG=Y` | object-time debugging switch: USE FOR DEBUGGING procedures run only when it's set (`Y`, `YES`, `ON`, `TRUE` or `1`), as in GnuCOBOL |
| `COB_CURRENT_DATE` | fixed date and time for ACCEPT FROM DATE/DAY/TIME and the date functions, for reproducible test runs: `YYYY/MM/DD hh:mm:ss`, optionally followed by `+hhmm` (the time part is optional) |

Runtime errors, such as a subscript out of range or an I/O error with no FILE
STATUS or USE procedure, print `cobrt: runtime error: file:line: ...` and exit
with status 1.

## Language coverage

**Source.** Fixed, free and variable reference formats, continuation lines,
`*>` comments, debugging lines, comment-entries. COPY ... REPLACING (pseudo-text,
identifiers, literals, LEADING/TRAILING) and REPLACE / REPLACE OFF. Boolean
literals (`B"0101"`, `BX"5A"`) and floating-point literals (`1.5E3`).

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
- USAGE: DISPLAY, BINARY/COMP/COMP-4, COMP-5, COMP-X, PACKED-DECIMAL/COMP-3,
  COMP-1/COMP-2, INDEX.
- SIGN LEADING/TRAILING [SEPARATE].
- USAGE ... PIC X(n) COMP-5 / COMP-X: Micro Focus n-byte binary numbers.
- Structure: OCCURS (nested, DEPENDING ON, ASCENDING/DESCENDING KEY, INDEXED BY),
  REDEFINES, RENAMES (66), condition names (88) with THRU and FALSE.
- VALUE clauses, GLOBAL and EXTERNAL items and files.
- FD: RECORD VARYING ... DEPENDING ON, LINAGE (FOOTING, TOP, BOTTOM, LINAGE-COUNTER),
  REPORT IS.

**Report Writer.**
- RD entries: CONTROLS (with FINAL), PAGE LIMIT with HEADING, FIRST DETAIL,
  LAST DETAIL and FOOTING, and CODE.
- Report groups: REPORT HEADING, PAGE HEADING, CONTROL HEADING, DETAIL,
  CONTROL FOOTING, PAGE FOOTING and REPORT FOOTING, with:
  - LINE (absolute, PLUS, ON NEXT PAGE), NEXT GROUP, COLUMN, SOURCE, VALUE;
  - SUM ... UPON ... RESET ON, with subtotaling, crossfooting and rolling
    forward;
  - GROUP INDICATE.
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
- Control flow: IF, EVALUATE (ALSO, THRU, ANY, TRUE/FALSE), all PERFORM formats
  (THRU, TIMES, UNTIL, VARYING/AFTER, WITH TEST AFTER, inline), GO TO /
  DEPENDING ON, ALTER, NEXT SENTENCE, CONTINUE, EXIT [PARAGRAPH / SECTION /
  PERFORM [CYCLE] / PROGRAM [RETURNING]], STOP RUN [RETURNING / WITH ERROR or
  NORMAL STATUS], STOP literal, GOBACK [RETURNING].
- Strings and tables: STRING, UNSTRING, INSPECT (TALLYING / REPLACING /
  CONVERTING, BEFORE/AFTER), SEARCH, SEARCH ALL.
- Terminal I/O and program calls: DISPLAY, ACCEPT (incl. FROM DATE/DAY/TIME/
  DAY-OF-WEEK/ENVIRONMENT), CALL (BY REFERENCE/CONTENT/VALUE, ON EXCEPTION,
  `CALL "SYSTEM"`), CANCEL.
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

**Intrinsic functions (101).** ABS, ACOS, ANNUITY, ASIN, ATAN, BYTE-LENGTH,
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
EXCEPTION for both).

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
- Report Writer features added by the 2002 standard, such as PRESENT WHEN,
  COLUMN RIGHT/CENTER and LINE LIMIT.
- Pointers: ADDRESS OF, BASED, SET ADDRESS OF.
- Split keys, ENTRY, object-oriented COBOL, EXEC SQL/CICS.
- Dynamic loading: a CALLed program must be compiled into the same executable.
- Relative and indexed files are held in memory while open and written back on
  CLOSE. That's fine for batch-sized files, but there's no record locking or
  sharing between processes, and the indexed format is cobolc's own (not
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
   standard leaves the result undefined. cobolc reads the value the way NUMVAL
   does, so `" -42"` becomes -42. GnuCOBOL copies the characters as an
   unsigned integer.
4. **Numeric intrinsic function results** are described as in GnuCOBOL, with
   two exceptions. A value of 10 digits that fits in 32 bits keeps all its
   digits (GnuCOBOL 3.1.2 shows only the last nine). The irrational results
   (SQRT, LOG, SIN, ...) have 38 significant digits; GnuCOBOL computes about 96,
   so a DISPLAY of one shows fewer digits, and their last digits can differ.
5. **Report Writer.** cobolc follows the standard's presentation rules. Each page
   of a report with a PAGE clause occupies exactly PAGE LIMIT lines of the file.
   GnuCOBOL 3.1.2 differs in these ways:
   - it loses a line at each page break when the report has no page footing;
   - it prints the last page footing one line too low;
   - it doesn't present CONTROL HEADING FINAL;
   - it ignores `SUM ... UPON` and `RESET ON`.

   At TERMINATE, cobolc presents the control footings with the control values
   of the last GENERATE, as the standard requires. GnuCOBOL uses whatever the
   program has moved into those fields since, which defeats the usual
   end-of-file HIGH-VALUES idiom.
6. **Debug module.** Before each debugging procedure cobolc space-fills
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
| `compiler/source.py` | 272 | reference formats, continuations, directives, comment-entries, debugging lines |
| `compiler/lexer.py` | 515 | tokens, PICTURE strings, literals, COPY/REPLACE expansion |
| `compiler/parser.py` | 2,602 | recursive-descent parser to the AST (`nodes.py`, 638) |
| `compiler/data.py` | 510 | PICTURE analysis, USAGE resolution, storage layout |
| `compiler/codegen.py` | 3,627 | name resolution, C generation, typed fast paths |
| `compiler/rwgen.py` | 500 | REPORT SECTION analysis, report tables and callbacks |
| `compiler/dbggen.py` | 466 | Debug module: DEBUG-ITEM and the USE FOR DEBUGGING hooks |
| `runtime/cobrt_core.c` | 2,573 | fields, moves, editing, decimal arithmetic, compare, DISPLAY/ACCEPT, CALL, exceptions, DEBUG-ITEM |
| `runtime/cobrt_io.c` | 1,555 | sequential, line sequential, relative, indexed, LINAGE, SORT/MERGE |
| `runtime/cobrt_rw.c` | 417 | Report Writer control system: paging, control breaks, INITIATE/GENERATE/TERMINATE |
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
cobolc               compiler entry point
LICENSE              MIT licence
compiler/            front end and code generator (Python)
runtime/             C runtime library
examples/            payroll report with control breaks, indexed-file bank ledger,
                     word-frequency count (table SORT), Mandelbrot set,
                     two-program CALL example (dayname + datefmt)
tests/cases/         differential tests and recorded GnuCOBOL baselines
tests/difftest.py    differential test runner
tests/nist/          NIST CCVS85 runner and the result logs of the runs above
tests/gnucobol/      GnuCOBOL testsuite runner and the recorded results
Makefile             make test | test-ref | nist | nist-all | gctest | examples | clean
```

## License

MIT. See [LICENSE](LICENSE).
