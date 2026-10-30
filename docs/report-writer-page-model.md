# Report Writer page geometry: GnuCOBOL's model

This note records how GnuCOBOL 3.2 advances pages in the Report Writer, taken
from its own `libcob/reportio.c` (functions `write_to_line`, `do_page_footing`,
`do_page_heading`, `write_rec`). It exists because yaccc's `runtime/cobrt_rw.c`
differs from it in a way that costs eight conformance tests, and re-deriving the
rule from expected output alone was not conclusive.

Nothing here is copied code; it is a description of the algorithm so the next
attempt does not have to reverse-engineer it again.

## The model

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
