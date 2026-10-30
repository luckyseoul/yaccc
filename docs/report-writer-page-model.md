# Report Writer page geometry: GnuCOBOL's model

This note records how GnuCOBOL 3.2 advances pages in the Report Writer, taken
from its own `libcob/reportio.c` (functions `write_to_line`, `do_page_footing`,
`do_page_heading`, `write_rec`). It exists because yaccc's `runtime/cobrt_rw.c`
differs from it in a way that costs eight conformance tests, and re-deriving the
rule from expected output alone was not conclusive.

Nothing here is copied code; it is a description of the algorithm so the next
attempt does not have to reverse-engineer it again.

## The model

> **This section describes a function that does not exist.** `write_to_line`
> appears nowhere in the GnuCOBOL 3.1.2 tarball this project measures against
> (`grep -r write_to_line libcob cobc` finds nothing; `reportio.c` is 1,835
> lines). Two ports were written from this section and both scored below the
> existing heuristic -- as they would, implementing a primitive the reference
> never had. The 3.1.2 algorithm, read from its actual source, is in
> "The 3.1.2 algorithm, exactly" below; that is the one to implement, and
> `tests/rw_oracle.py` is how to check it.

Page position is a 1-based line number, `curr_line`, not a byte offset.

`write_to_line(r, linen)` is the only primitive that puts a record on the page:

```
if curr_line <= linen:
    advance = linen - curr_line + 1      # blanks, then the record
    write `advance` lines, the record on the last one
    curr_line = linen + 1
    if curr_line > PAGE LIMIT:
        curr_page += 1
        curr_line = 1                     # roll over, no extra blank line
```

So the page has exactly PAGE LIMIT lines, and writing to the last of them rolls
the page in the same operation. There is no separate "finish the page" step.

## Page heading

`do_page_heading` is entered at the start of a page:

- if this is not the first GENERATE and `curr_line` is past the heading but
  still inside the page, skip to the end of the page and reset to line 1;
- if `curr_line < HEADING`, `write_to_line(HEADING - 1)` so the heading record
  lands on the HEADING line;
- write the heading record;
- if `curr_line < FIRST DETAIL`, `write_to_line(FIRST DETAIL - 1)` so that the
  first detail line lands on FIRST DETAIL.

## Page footing

`do_page_footing` is entered on page overflow:

- if `LAST DETAIL` is set and `curr_line <= LAST DETAIL`, skip to LAST DETAIL;
- write the PAGE FOOTING record at whatever line its own `LINE` clause gives;
- if `curr_line` is still inside the page and past line 1, `write_to_line(PAGE
  LIMIT)` — that is, pad the page out to its last line, with a blank record on
  it — and the page rolls over;
- otherwise reset `curr_line = 1`.

~~The consequence worth noting: the page always ends on PAGE LIMIT, and the
page footing does **not** shorten the page.~~

**Corrected by measurement (see "Observing the real cursor" below):** that
holds only while the footing leaves the cursor inside the page. Run against a
live 3.1.2, `run_reportwriter.at:23` (`PAGE LIMIT 12`, `HEADING 1`,
`FIRST DETAIL 4`, `LAST DETAIL 7`, page footing at `LINE 10`) writes 11 lines
on page 1 -- the page-2 heading lands on output line 12 -- so the page ended at
the footing's own line plus one, not at `PAGE LIMIT`. The same report's
recorded fixture is what yaccc's current heuristic reproduces, and a port of the
`write_to_line` model above regressed it. The footing rule therefore depends on
where the cursor stands, and no single "page is N lines" statement covers both
shapes.

## Where yaccc differs

`runtime/cobrt_rw.c` tracks `pos` as a physical newline count from the start of
the report and `page_start` as the offset of the current page, and pads with an
explicit `finish_page` before advancing `page_start`. That is equivalent only
when `finish_page` and the advance agree on the page length.

An attempt to change the advance to `PAGE LIMIT - 1` (on the theory that a page
holds one line fewer than its limit) made page 1 and page 2 of
`run_reportwriter.at:23` match GnuCOBOL byte for byte, but broke five
differential baselines and did not fix the rest of the cluster, so it was
reverted. `tests/cases/rwlimit.outfiles/rwlimit.txt` — output recorded from
GnuCOBOL 3.1.2 — is six lines for `PAGE LIMIT 6`, which is what the model above
predicts and what the unchanged code already produces.

## What a correct fix looks like

Replace the `pos`/`page_start` pair with GnuCOBOL's `curr_line` and implement
`write_to_line` as the single primitive, so page rollover happens inside it.
`finish_page` then disappears: padding to PAGE LIMIT is `write_to_line(PAGE
LIMIT - 1)` followed by writing the last record. This is a change to the page
state machine only; it does not touch record layout, so it cannot affect stored
data.

It is not done here because the eight failing tests could not be reconciled with
the recorded `rwlimit` baseline without running GnuCOBOL itself as an oracle,
and installing it was outside what this session could verify.

## Observing the real cursor

Guessing at this from expected output has now failed twice, so the next attempt
should watch the reference implementation instead. GnuCOBOL 3.1.2 can print
every cursor decision it makes ("Line# 7 of Page# 2; PAGE FOOTING LINE 24"),
which is enough to see the machine rather than infer it.

Build a tracing `cobc` (this is a local oracle only; no GnuCOBOL code goes into
this repository):

```sh
tar xJf gc.tar.xz && cd gnucobol-3.1.2
./configure --enable-debuglog --prefix=/tmp/gctrace-inst --disable-nls \
    --without-db --without-xml2 --with-json=no \
    CFLAGS="-O1 -w -std=gnu17"
make -j"$(nproc)" && make install
```

Two things bite here and are worth knowing before starting:

- GCC 15 defaults to C23, where GnuCOBOL 3.1.2's `call.c` does not compile
  (`-Wincompatible-pointer-types` is an error); `-std=gnu17` in `CFLAGS` is
  what makes it build. `--without-xml2` is also needed, or `mlio.c` fails on
  `implicit declaration of xmlCleanupParser`.
- **`M=` does not work in 3.1.2.** `cob_debug_modules` is initialised to `""`
  but the registration guard tests for `' '`, so the loop never runs, no module
  is ever registered, and `DEBUG_ISON("rw")` is always false -- a `--enable-
  debuglog` build still prints nothing until the guard is changed from
  `== ' '` to `<= ' '` in `libcob/common.c`. That is why an earlier attempt at
  this concluded the trace "never compiled in".

Then run any report program with

```sh
COB_DEBUG_LOG="M=RW,L=A,O=/tmp/rw.log" ./prog
```

and read the trace. Useful lines are the `Line# n of Page# m;` events (each
one is a print line being written), `Eject Page` (an overflow), `Present now`
(PRESENT AFTER evaluation), and the rendered record that follows each event,
which is what actually landed in the file.

`docs/` also carries two throwaway helpers used for this: `tests/gnucobol/
run_gc.py -k "<title>" --log` for a single test, and the trace decoder in this
note's history, which matches each event's rendered record to its line in the
output file and so recovers the page offsets directly.

### What the trace has already shown

- Page offsets are **not** a property of the report: `Sample Inventory Report`
  (`PAGE LIMIT 25`, `FOOTING 20`, page footing at `LINE 24`) puts its page
  footings at output lines 24, 49 and 73, i.e. pages of 24, 25 and 24 lines
  within one report.
- `Report Line Order` (`PAGE LIMIT 12`, footing at `LINE 10`) ends page 1 at
  line 11.
- Both are consistent with the footing/pad rules in this note, and not with a
  constant page length; the drift comes from the cursor being able to sit on a
  line the file has already passed.

### The 3.1.2 algorithm, exactly

Decoded from `libcob/reportio.c` and `libcob/fileio.c` in the 3.1.2 tarball
(this is the version whose output the suite asserts). Four pieces, and the
non-obvious parts are marked.

**State**: `curr_line` (0-based at INITIATE), `curr_page`, and a one-bit
`incr_line`.

**INITIATE**: `curr_page = 1; curr_line = 0; incr_line = TRUE`.

**Around every GENERATE** -- this is the part no output-based derivation
finds:

```
generate():
    if (incr_line) { incr_line = FALSE; curr_line++; }   # start
    ... headings, control breaks, the detail group ...
    curr_line--;                                         # end
    incr_line = TRUE;
```

The `--` at the end and the `++` at the start cancel, **except** when
`do_page_footing` cleared `incr_line` -- then the increment is skipped and the
next line lands one higher than a naive model predicts.

**Each print line** (`report_line`):

```
if (curr_line > LAST DETAIL && !in_report_footing && !in_page_footing)
        { page_footing(); page_heading(); }
... position the line: an ABS line already passed by the cursor ejects the
    page first; then `while (curr_line < line) write blank; curr_line++` ...
if (curr_line > LAST DETAIL && !in_report_footing && !in_page_heading
                          && !in_page_footing)
        { page_footing(); page_heading(); }
write record; curr_line++;          # write_rec itself never moves the cursor
```

Two things worth noting: the overflow test compares **`curr_line`**, not the
line being placed, and it runs **before and after** positioning -- so a group
can carry the cursor past LAST DETAIL and the ejection happens on the next
line, one page later than a group-granularity model ejects.

**Page footing**:

```
if (curr_line < PAGE LIMIT)
        { write (PAGE LIMIT - curr_line) lines; curr_line = PAGE LIMIT;
          incr_line = FALSE; }
else    { curr_line = 1; }        # no padding at all
```

The `else` is why a page is not always PAGE LIMIT long: once the footing's own
line has reached the limit, nothing is padded and the page simply ends there.

**Page heading**:

```
if (!first_generate && curr_line <= PAGE LIMIT && curr_line > HEADING)
        { while (curr_line <= PAGE LIMIT) { write; curr_line++; }
          if (curr_line > PAGE LIMIT) curr_line = 1; }
curr_page++;
while (curr_line < HEADING)       { write; curr_line++; }
print the page heading;
while (curr_line < FIRST DETAIL)  { write; curr_line++; }
```

**Predicted page lengths**, to check a port against before running the suite:
`Sample Control Break` (PAGE LIMIT 25, FOOTING 23, no page footing group) is
25, 24, 25; `Sample Inventory Report` (25, LAST DETAIL 18, page footing at
LINE 24) is 24, 25, 24; `Sample Charge Report 3` is a single 66-line page. All
three were measured from the file cobc writes.

### Measured scoreboard (the thing to beat)

Every model below was implemented and run against the full suite. The measured
heuristic that is in the tree wins every time:

| model | Report Writer tests | whole suite |
|---|---|---|
| measured heuristic in `cobrt_rw.c` (current) | 21 of 25 | 503 / 3 |
| full cursor port (`curr_line`, `write_at`, footing/heading branches) | 10 of 23 | 485 |
| `write_to_line` as the only primitive, per this note | -- | 492 / 14 |
| `page_start = file position` (drop the computed stride) | -- | 494 / 12 |

The last one is the most informative: "each page starts wherever the file
actually is" is *true of GnuCOBOL* -- the trace shows page 2 of
`run_reportwriter.at:23` starting at file line 12, exactly after page 1 ended at
line 11 -- and implementing it still loses nine tests. The reason is that the
heuristic's padding (`pad_page` filling to `PAGE LIMIT`) happens to reproduce
the *file* geometry of most shapes even though its page arithmetic is wrong, so
correcting the arithmetic alone removes the compensation without adding the
reproduction.

So a fourth attempt has to replace the padding and the stride **together**, in
one change, and be scored against this table rather than against a single test.

### What a third attempt should not repeat

- Porting `write_to_line` alone is not enough: a version that made it the only
  writer, with rollover inside it, scored 492 pass / 14 fail against the
  current heuristic's 503 / 3, because the page-footing and page-heading pad
  endpoints and the `incr_line = FALSE` case are what actually decide the
  end of a page.
- Treating `incr_line` as "the cursor does not advance on this write" makes
  `seek`-style loops spin forever. In 3.1.2 `write_rec` never touches the
  cursor at all; only the report-line writer advances it, unconditionally.

## The differential oracle (`tests/rw_oracle.py`)

Guessing from a handful of failing tests is what let three wrong models look
plausible. `tests/rw_oracle.py` replaces that with thousands of shapes:

```sh
export PATH=/tmp/gcinst/bin:$PATH LD_LIBRARY_PATH=/tmp/gcinst/lib
python3 tests/rw_oracle.py                  # the generated sweep
python3 tests/rw_oracle.py --full           # the whole sweep
python3 tests/rw_oracle.py --testsuite --no-sweep   # just the 3.1.2 RW tests
python3 tests/rw_oracle.py --case pl=10,fd=2,ld=2   # one shape, keep files
```

It generates programs that vary PAGE LIMIT, HEADING, FIRST/LAST DETAIL,
FOOTING and a page-footing group, all seven group types, `LINE` and
`NEXT GROUP` in their absolute, PLUS and NEXT PAGE forms, several print lines
per group, control breaks, `SUM`, `GROUP INDICATE` and the record count. Each
program is compiled with both compilers and the report files compared byte for
byte; a mismatch is cut down to the smallest shape that still shows it. It
needs `cobc`, so it is a development tool and not a CI step.

Its first run, before any fix, found **128 of 131** generated shapes differing
-- while the testsuite flagged only three. The testsuite was never a broad
enough sample to tell models apart, which is exactly why three wrong ones
survived review.

### What it has already established

Three generator bugs, each of which would have looked like a compiler bug:

- **Fixed-format column 72.** A single-line `RD ... PAGE LIMIT ... HEADING ...
  FIRST DETAIL ... LAST DETAIL ...` truncates at column 72 and fails to
  compile, with an error pointing at the *following* line. Every `RD` in the
  testsuite is written one clause per line for this reason. The generator now
  asserts no line exceeds 72 columns.
- **`RH` and `PH` are reserved words** (the report/page-heading abbreviations),
  so `01 rh TYPE REPORT HEADING` is a syntax error. Group names in the
  generator are `rep-head`, `page-head`, `ctl-head`, `de-line`, `ctl-foot`,
  `page-foot`, `rep-foot`.
- **A `CONTROLS` entry with no report group of that name breaks cobc itself**:
  `CONTROLS ARE FINAL, ctl1, ctl2` with no `ctl2` group emits C that references
  an undeclared `f_11` and fails to compile. Not a YACCC issue; worth knowing
  before declaring controls that never appear.

One real step towards the page rule. Replacing the stride heuristic with
"the page is `PAGE LIMIT` lines if the next free line is still short of it,
otherwise it ends on its last written line" (the shape of 3.1.2's
padding-or-reset) moved the generated sweep from 128 differing shapes to 117 --
but took the testsuite from 503 to 497, so it was reverted. The trace shows why
the two disagree: for `LINE PLUS n`, cobc's internal `line` is `n + 1`, and the
pre-overflow skip it performs (`curr_line += line - 1`) runs even when the
group would not fit, which moves the footing by one line. The stride rule and
that skip are entangled, so the next attempt must change both together -- the
same conclusion as before, now with a measurement behind each half.

### Step 2, attempted: a fresh 3.1.2 engine

A rewrite following the algorithm above was implemented on a branch and scored
three times. It is not in the tree; the measurements are worth keeping.

**What improved.** With the cursor rules in place (every print line positions
itself from its own `LINE` clause; `LINE PLUS n` skips `n-1` lines and writes on
the next; the overflow test runs before and after positioning), the generated
sweep went from **128 differing shapes to 85** -- the best any model has scored
on that axis.

**What regressed.** The same engine took the Report Writer testsuite from 21 to
13, and after folding the footing and heading into one atomic `page_advance`,
to 3 (and 131/131 on the sweep: the fill-to-end-of-page branch fired on every
page end, not only on overflow).

**Three things the attempt established:**

- **The page advance must be atomic.** Doing the footing and the heading as two
  calls lets a line placed inside the footing eject a page of its own: the
  footing appeared twice on page 1 of `run_reportwriter.at:23`. One function
  that foots, pads, bumps the page, heads and skips to FIRST DETAIL avoids it --
  but it then has to know *why* it was called (an overflow, not the first
  GENERATE), so the caller has to say so rather than the callee inferring it.
- **Padding has to consume the rest of the page.** After the footing pads, the
  next page's heading lands directly after the last padding line; leaving the
  cursor on `PAGE LIMIT` makes the heading write one more line and every
  following page drifts by one. Measured on `run_reportwriter.at:23`:
  `PAGE LIMIT 12`, footing at `LINE 10`, one padding line, heading next.
- **The two axes disagree, and the sweep is the one that generalises.** The
  layout engine halved the generated mismatches while making the curated tests
  worse. That is not a contradiction: the testsuite exercises report headings,
  `NEXT GROUP` and control footings heavily, and those paths were the ones left
  unported. A complete port has to carry all of them, which is why partial ones
  lose to a heuristic tuned on exactly those shapes.

**Next step is therefore narrower than "port the engine":** port the *complete*
set -- report heading, page heading, control heading/footing, detail, page
footing, report footing, plus `NEXT GROUP` in all three forms and `PRESENT WHEN`
-- and score on both axes after each one, starting from the 85-shape engine
rather than from the heuristic.

### Step 2, second attempt: surgical swap of the geometry core

Rather than rewriting the engine, the page-geometry core (`page_stride`,
`bare_advance`, `pad_page`, `finish_page`) was replaced with the cursor model
while keeping the existing group handling (`present`, `print_group`). Scored
21 -> 3 -> 6 of 25 and reverted.

What it pinned down, in the order the scores moved:

- **`curr_line` is incremented at the start of a GENERATE and decremented at the
  end** -- without the pair, `first_body_line` computes `lc + num - 1` from `lc`
  pointing at the last line written instead of the next free one, every group
  lands one line early, and `PAGE LIMIT REPORT` loses its trailing blank line.
  Adding the pair moved 3 -> 6.
- **The final page is padded while `curr_line < PAGE LIMIT`**, not `<=`: `<=`
  adds one record too many at TERMINATE.
- **`PAGE LIMIT REPORT` then matches cobc byte for byte** (`hello`, `goodbye`,
  blank), and `Report Line Order` matches in length but not in content --
  fifteen lines offset by one.

The remaining gap is not geometry. `Sample Charge Report 3` writes 46 lines
where cobc writes 67, and the offset in `Report Line Order` starts at the first
detail line after a page heading. That points at `present()`'s per-group
positioning still computing absolute page lines (`base = lc < h - 1 ? h - 1 :
lc`) while `put_line` now works in cursor lines -- the two only agree while a
page and its cursor are in step, which is exactly what is not true any more.

So the next attempt must convert `present()` for all seven group types to the
cursor model in the same change; swapping the writer alone leaves two
coordinate systems in one file.

### Step 2, third attempt: one coordinate system, all seven group types

The whole engine was rewritten so that every position is a cursor line (no
absolute page offsets anywhere), with `present()` for all seven group types
converted in the same edit. Scored 10 -> 12 of 25 against the baseline's 21 and
was reverted. This was the closest of the three rewrites to behaving, and it
pinned down four things worth keeping.

**The cursor is the next free line during a GENERATE, and the last written line
between them.** That is the whole trick, and it is why `curr_line` is incremented
at the start of a GENERATE and decremented at the end: the +1/-1 pair moves the
meaning, not the position. `LINE n` therefore fits when `curr_line <= n`; testing
`<` drops a line every time a group lands exactly on its clause's line, which is
what `Report Line Order` was showing (RH one line late).

**`NEXT GROUP` belongs to the group after which it is declared** -- usually the
control footing, not the detail. The 3.1.2 trace of `Sample Charge Report 3`
shows it plainly: detail on line 5, `Execute NEXT GROUP PLUS 2` at cursor 6,
next detail on line 8. So `NEXT GROUP PLUS n` writes n blank lines from the
cursor and leaves the next line at `cursor + n`. A group with no print lines
still carries its `NEXT GROUP`; `report_line_and` sets it even when nothing is
written, so an early `return` on `nlines == 0` silently drops every skip.

**That fix alone was not enough for the Charge Report family**, and the reason
is the remaining unknown: with `NEXT GROUP` applied, yaccc still packs the
detail lines adjacent (55 lines against cobc's 67). Something earlier in
`present_body` is resetting the cursor between the footing and the next detail.
That is the first thing the next attempt should instrument -- a trace of
`Sample Charge Report 3` with `COB_DEBUG_LOG` plus a fprintf in `emit_group`
answers it in one run.

**Two tests now match where the heuristic did not** on the way through
(`PAGE LIMIT REPORT 2`, `Report Line Order` in content and length), which is
what the cursor model buys; the loss is in the control-break paths, which the
heuristic had been tuned on.

### Where this leaves the port

Three rewrites, three regressions against the measured heuristic. The pattern is
consistent and now well understood: the heuristic encodes a lot of *empirical
compensation* for paths the rewrites did not finish, so any partial port scores
worse than the thing it replaces. The port is worth finishing only as a whole,
and the concrete next steps are, in order:

1. Instrument `emit_group`/`next_group` and find what resets the cursor between
   a control footing and the next detail (`Sample Charge Report 3`, 55 vs 67
   lines).
2. Re-run the generator sweep after each fix -- it catches generality that the
   25 testsuite programs cannot.
3. Ship only when both axes beat the baseline: 21+ of 25 tests, and fewer than
   128 differing generated shapes.

## The reference's report tree, recovered from its generated C

`cobc -C` emits the report tables as static C, which is the densest description
of the reference's structure available short of reading the compiler. Decoded
against `cob_report_line` in `libcob/common.h`, for `Sample Charge Report 3`:

```
typedef struct __cob_report_line {
        struct __cob_report_line *sister;   /* next line at this level */
        struct __cob_report_line *child;    /* first line below this one */
        cob_report_field *fields;
        cob_field        *control;          /* the CONTROL data item, if any */
        int               use_decl;
        unsigned int      flags;            /* COB_REPORT_*: the group type */
        int               line;             /* the LINE value */
        int               step_count;
        int               next_group_line;  /* NEXT GROUP's value */
        unsigned int      report_flags;
        unsigned int      suppress:1;
} cob_report_line;
```

So a generated table looks like

```c
rl_42 = {&rl_53, &rl_43, NULL, NULL, 0,    64, 0, 196, 0,    64, 0};
rl_58 = {&rl_68, &rl_59, NULL, &f_9, 0, 17408, 0, 196, 2, 17408, 0};
```

and three structural facts follow, none of which is visible in the output:

- **Groups are one flat `sister` chain in source order, with the type in
  `flags`** (`64` = `COB_REPORT_PAGE_HEADING`, `17408` =
  `COB_REPORT_CONTROL_FOOTING | COB_REPORT_NEXT_GROUP_PLUS`). The reference does
  not walk "all report headings, then all page headings"; it walks one list and
  dispatches on the flag. A port that models groups as a typed tree walks them
  in a different order and only notices when a group is absent.
- **`NEXT GROUP` is a flag plus `next_group_line` on the group's own line
  record** -- `rl_58` is the control footing, and the `2` is its NEXT GROUP
  value. It is not a property of the group it precedes, and not held in a
  separate table.
- **`control` is per line**, not per group (`&f_9` on `rl_58`), which is how the
  reference decides whether a control break applies to a particular print line
  without consulting the group's level.

### Why "copy the shape" is the right method, and reading output is not

The three failed ports all worked from output diffs, and diffs are lossy: they
say two files differ at line 6, never which decision produced line 6. The three
sources above are ordered by how much they constrain the answer:

1. the reference's source (rules, directly),
2. the reference's intermediate tables (structure, directly),
3. the reference's output (only the product of both),
4. our own tests (only a sample of that product).

Every attempt that started at 4 and worked upwards lost to the heuristic. The
finding recorded here came from 2 in a few minutes.

### Method note: what "deriving" this actually is

There is no specification to derive from -- the 3.1.2 Report Writer is original
work dated 2013 in `libcob/ChangeLog` ("Report Writer Module initial
development"), written by one author, not a port of IBM's or Micro Focus's. The
behaviour is therefore recoverable only from artifacts, and the standard methods
are: read the source; instrument the reference (a black box that can narrate
itself is not a black box); read the intermediate representation rather than its
output; differential-test at a scale the hand-written tests cannot reach; and
delta-debug a failing case down to something small enough to read.

Two rules of thumb learned the hard way in this file's history:

- **Suspect the probe before the subject.** Three "reference bugs" here were
  ours: an `RD` clause past column 72, `RH`/`PH` being reserved words, and a
  `CONTROLS` entry with no matching group breaking the reference's own codegen.
- **A wrong model with empirical compensation can beat a correct model that is
  incomplete.** `page_start = file position` is true of the reference and scored
  494 against a heuristic whose page arithmetic is wrong. Legacy behaviour
  encodes years of per-symptom patches; a principled rewrite has to clear all of
  them at once or it scores worse. That is why partial ports of this kind fail,
  and why the port must replace the padding and the stride together.
