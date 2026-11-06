# Three-way differential

YACCC's compatibility target is GnuCOBOL, and much of its behaviour was
established by running `cobc` and matching what it does. That leaves a blind
spot. Where YACCC and GnuCOBOL agree but a third implementation of the same
standard disagrees, it is impossible to tell from a two-way comparison whether
the standard was matched or a GnuCOBOL quirk was copied.

`tests/three_way.py` closes it. It compiles each program with YACCC, with
GnuCOBOL, and with **gcobol**, GCC's COBOL front end — an implementation with a
different lineage and no shared code — then compares exit status and output.

```
python3 tests/three_way.py            # tests/cases
python3 tests/three_way.py --dir DIR
python3 tests/three_way.py --only NAME -v
```

It needs all three on `PATH` (or `YACCC`, `COBC`, `GCOBOL` pointing at them).
It is a survey, not a gate: exit status is 0 whatever the outcome. A case's
`.flags` sidecar is honoured, with `@ref:` words going to the reference
compilers, as `tests/difftest.py` does.

## What it reported

At the time of writing, over `tests/cases` (84 programs):

```
15  all three agree
11  YACCC = cobc, gcobol differs
45  incomplete -- a compiler refused the program or crashed on it
13  no GnuCOBOL reference: the case is marked .noref
```

Most of the incompleteness is gcobol's: **41 programs** are refused outright,
including every Report Writer program, because `REPORT IS` does not parse in
GCC 15.2's front end. YACCC compiled everything GnuCOBOL compiled.

No case is left where YACCC is the odd one out, which is the outcome that
would point at a YACCC defect. One case was, before it was marked:

```
$ ./yaccc tests/cases/udf.cbl -o p && ./p
ADDONE(1)=02        YACCC
ADDONE(1)=79        GnuCOBOL 3.1.2 — an uninitialised return value
                    gcobol — segmentation fault
```

`udf` calls a user-defined function. YACCC returns the arithmetically right
answer and it matches the recorded baseline; GnuCOBOL returns an uninitialised
value and gcobol crashes. The case carries a `.noref` marker now, since
YACCC's answer deliberately differs from GnuCOBOL's here and comparing the two
would only record the difference — which is why it no longer appears among the
all-differ results above.

Finding this also turned up a gap in `make test-ref`, which the README
described as running GnuCOBOL live. It does, but it compares the *files a
program writes* against `cobc`, while standard output is still compared against
the recorded baseline. So a case whose stdout differs from GnuCOBOL passed
`test-ref` unnoticed, which is how `udf` came to be missing its marker. The
three-way harness compares stdout, which is why it showed up.

So on this corpus the question "did we copy a GnuCOBOL bug rather than
implement the standard" has not yet had a yes.

## Where the three disagree, checked individually

Each of the eleven `YACCC = cobc` cases was reduced to a minimal reproduction
and judged against the standard. All three below are gcobol defects, not YACCC
ones.

**Parentheses in `COMPUTE`.** gcobol evaluates `((1 + 2) * (3 + 4)) - 5` as
**7**, dropping the outer group and the subtraction:

```cobol
COMPUTE X = ((1 + 2) * (3 + 4)) - 5.
DISPLAY X        *> 16 everywhere; gcobol prints 7
```

**P-edited pictures.** `PIC VPPP999` holds three stored digits with three
implied leading zeros. Moving `0.000123` into it and scaling back by a million
loses the leading digit in gcobol:

```cobol
01 PSCAL PIC VPPP999.
MOVE 0.000123 TO PSCAL
COMPUTE R = PSCAL * 1000000
DISPLAY R        *> 000000123.000000 everywhere; gcobol prints 000000023
```

**`UNSTRING` with alternative delimiters.** When a field is terminated by one
of several delimiters, `DELIMITER IN` must name the one that terminated it.
gcobol reports the last alternative rather than the matching one:

```cobol
UNSTRING S DELIMITED BY "," OR ALL SPACE
    INTO F DELIMITER IN D
DISPLAY D        *> if S is "APPLE,BANANA", D is "," — gcobol prints a space
```

One case diverges without a reduced reproduction: `relative1`, where a record
rewritten during an `OPEN I-O` session is still read back stale by gcobol
afterwards. The rewrite works in isolation, so the fault is in its sequencing
rather than in `REWRITE` itself.

## Where YACCC follows GnuCOBOL deliberately

Not every `YACCC = cobc` disagreement is a gcobol bug. Some are places the
standard leaves open, or extensions GnuCOBOL defines and YACCC mirrors on
purpose. `COMP-5` is the clearest:

```cobol
01 A PIC S9(4) COMP-5.
MOVE 12345 TO A
DISPLAY A        *> [+12345] — the full 16-bit value; gcobol truncates to [+2345]
```

`COMP-5` is not in COBOL 85. GnuCOBOL treats it as native binary, so a
four-digit `COMP-5` field holds a two-byte integer and `DISPLAY` shows the
whole value. YACCC does the same, because programs written for GnuCOBOL expect
it. This is the compatibility target being met, not a copied defect — but it is
the category to watch, since the difference between "the standard is silent"
and "GnuCOBOL is wrong" is exactly what a third implementation reveals.

## Caveats

- gcobol was tested as packaged for Ubuntu 24.10 (`gcobol-15-x86-64-linux-gnu`
  15.2.0-16ubuntu1), which is GCC 15.2's front end. It is young software and
  these defects will presumably be fixed; the value here is the comparison, not
  the verdict on any one compiler.
- The corpus is YACCC's own test set, which was written against GnuCOBOL
  behaviour. A corpus written against the standard alone would be a stronger
  test, and would likely surface more of the "follows GnuCOBOL deliberately"
  category.
- gcobol refuses so many programs that the three-way comparison only covers a
  third of the corpus. That is itself the finding: for the parts of COBOL
  gcobol implements, agreement with an independent implementation is
  meaningful; for the rest there is nothing to compare against yet.
