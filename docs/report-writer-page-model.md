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

The consequence worth noting: the page always ends on PAGE LIMIT, and the page
footing does **not** shorten the page. `LAST DETAIL` moves the footing, it does
not cap the page.

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
