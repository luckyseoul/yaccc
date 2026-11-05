# Conformance history

How the last GnuCOBOL 3.1.2 testsuite failures were fixed (items 1-5), a defect
no suite covered (item 6), and the measurements the fixes were built on.

## 1. Report Writer page breaks *(fixed)*

`Sample Payroll Report` and `Sample Inventory Report` were the last two
failures, and 391 of the 527 shapes `tests/rw_oracle.py --full` generates
disagreed with `cobc`. YACCC's Report Writer decided where a page ended with a
page length fitted to the testsuite (`page_stride()`): one line short of PAGE
LIMIT here, the full length there. No single fit could be right, because
`cobc`'s page length is not a property of the report: it follows from a line
cursor that GENERATE raises by one on entry and lowers on exit. The same LINE
clause therefore lands one line lower inside a GENERATE than in TERMINATE,
and a page ended in the middle of one is a line shorter.

The fix replaced the fitted length with that cursor and the rules around it,
each measured on 3.1.2 with the oracle and with probes that print
PAGE-COUNTER and LINE-COUNTER on every line. Among them:

- a page change inside the first GENERATE neither counts the page nor brings
  the cursor back up; the page heading then finds the cursor past LAST DETAIL,
  ends the page in place and prints on line 1 (PAGE-COUNTER and LINE-COUNTER
  both 1, whatever HEADING says), and the next GENERATE starts with the
  heading it never got;
- a NEXT GROUP waits for the next body line, but after a page start in the
  same GENERATE only a detail line takes it; footings presented by TERMINATE
  leave none;
- a control heading or footing whose lines sit under its 01 gets the page
  checks once more for the 01 itself;
- without a PAGE clause nothing is positioned and LINE-COUNTER stays 0, and a
  CODE clause starts every line, blank ones included.

*Inventory* also needed a second absolute `LINE 2` in its report heading to
join the first line instead of starting a page; *Payroll* needed PRESENT WHEN
on a LINE entry and on a group item, and a group item's own run of columns
(`COLUMN PLUS 1` inside a `FILLER` group prints in column 1). The two
differential tests that had hand-made baselines, `rw2` and `rw3`, now match
`cobc` and are recorded from it.

Measured after the change: GnuCOBOL testsuite 506 pass / 0 fail, all 527
oracle shapes identical to `cobc`, NIST 9,390 pass / 0 fail.
`docs/report-writer-page-model.md` lists every rule.

![A page as the Report Writer counts it: page heading, first detail, last detail, footing and page limit, beside the group tables the compiler builds](docs/img/page-model.svg)

## 2. FLOAT-DECIMAL-16 / FLOAT-DECIMAL-34 *(fixed)*

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

## 3. CALL BY VALUE numeric literal WITH SIZE *(fixed)*

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

## 4. COMP-4 No Truncate *(fixed)*

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

## 5. OS/VS arithmetic, error procedures, and INITIATE *(fixed)*

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

## 6. A division by an inexact intrinsic result gave 0 *(fixed)*

Found while building [SPACE.cob](https://github.com/luckyseoul/SPACE.cob). No
program in NIST CCVS85 or GnuCOBOL's testsuite divides by an intrinsic
function, so both stayed green over it:

```cobol
COMPUTE A = 1 / FUNCTION PI          *> was 0; now 0.318309886, as cobc
COMPUTE B = 1 / FUNCTION SQRT(2)     *> was 0; now 0.707106781, as cobc
COMPUTE C = 1 / FUNCTION SQRT(4)     *> 0.5 before and after (exact)
```

**Cause.** `d_div` in `runtime/cobrt_core.c` scales the dividend to 37 digits
whatever the divisor, and an irrational intrinsic result carries 38
significant digits, so the integer quotient was 0. More generally a divisor of
more than 19 digits left fewer than 18 digits in the quotient.

**Fix.** Unless the division is exact, a divisor of more than 19 significant
digits is rounded to 19 first, which keeps 18 or more digits in the quotient.
`tests/cases/divirr.cbl` checks eight such divisions against `cobc`; a COMP-2
receiver can still differ from `cobc` in its 16th digit.

## Things in this area that are *not* worth "fixing"

- `cobc`'s `-fnotrunc` on a scaled PICTURE is a quirk the standard does not
  describe; matching it is only worth it because a test asserts it.
- NATIONAL (`PIC N`) is stored one byte per character with two bytes per
  character of width, because that is what 3.1.2 does and what its tests
  compare against; it is not UTF-16.
- GnuCOBOL 3.1.2's Report Writer page quirks (a page change in the first
  GENERATE that does not count the page; a NEXT GROUP on a DETAIL whose lines
  are LINE entries below its 01, which is ignored; a LINE clause that lands a
  line lower inside GENERATE than in TERMINATE) are reproduced, not fixed: the
  testsuite and NIST were written against them.
