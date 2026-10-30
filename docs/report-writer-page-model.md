# Report Writer: the page and control-break model

YACCC's Report Writer (`lib/yaccc/rwgen.py` builds the tables,
`runtime/cobrt_rw.c` runs them) reproduces GnuCOBOL 3.1.2's behaviour, because
that is what GnuCOBOL's testsuite and the NIST RW programs check. It matches
`cobc` byte for byte on all 24 runnable Report Writer tests in the 3.1.2
testsuite and on every shape `tests/rw_oracle.py --full` generates (527), and
passes NIST RW101A–RW104A.

This note describes the model in its own terms. No GnuCOBOL code is in this
tree; the behaviour was established by reading what cobc does, dumping the
report tables it generates (`cobc -C`), and comparing output with a live cobc.

## Why earlier attempts failed

Three ports of a "page cursor" scored worse than a set of measured rules, and
for the same two reasons:

- they modelled a report as a typed tree of groups, where cobc walks **one
  chain of print lines** and dispatches on flags. Most of cobc's surprising
  output — a control heading printed twice, a NEXT GROUP that is ignored, a
  footing one line late — follows from walking that chain, not from page
  arithmetic;
- they worked from a description of a later GnuCOBOL (a `write_to_line`
  primitive that 3.1.2 does not have), and were scored against three tests,
  which cannot tell page models apart. `tests/rw_oracle.py` generates hundreds
  of shapes; the first run of the old rules against it disagreed on 128 of 131.

## The tables

**Print lines.** There is one print line for every 01 entry and for every
entry with a LINE clause. The 01 lines form a single chain (`sister`) in
source order. An 01 whose first subordinate entry has a LINE clause points to
it (`child`), and LINE entries at the same level chain through `sister` as
long as the next entry also has a LINE clause. Lower LINE entries never get a
`child`. Two adjustments are made first:

- an 01 LINE clause is dropped when its first subordinate entry has one too
  (a "nested LINE");
- a second absolute `LINE n` among the entries of one group, with the same `n`
  as an earlier one, is dropped: that entry joins the line before it.

**Report items.** A print line lists the items that print on it: for a line
entry with subordinates, those subordinates and everything under them, in
source order, stopping at the next entry with its own LINE clause; for an
elementary line entry, itself and the entries after it that have no LINE
clause. Group items stay in the list, flagged, so that PRESENT WHEN on a
group can skip everything under it. An OCCURS item is listed once per
occurrence (its subordinates are not listed; the occurrence prints as a whole).

**Columns.** A running position starts at 1 at every 01 entry and every entry
with a LINE or a TYPE of DETAIL / RH / RF / PH / PF. For any other entry:
`COLUMN PLUS n` is that position plus `n - 1`; no COLUMN clause is the position
itself; and the position then moves past the item (`COLUMN RIGHT n`: the item
ends at `n`; `COLUMN CENTER n`: centred on `n`, with cobc's rounding, after
which the position moves only half the item's width). `PLUS` on the first item
of a line is ignored. A group item resets the position for its own items. Later
occurrences of an OCCURS item take the next value of the COLUMN list, or step
by `STEP` (at least the item's width).

**Controls** are listed **minor first**, numbered from 1 in that order. Each
lists the CH and CF lines that name it, the last-declared first.

**SUM counters.** Every SUM entry gets a hidden counter `S9(n+2)V9(s)` (18
digits at most) in source order. An operand that is itself a SUM entry is that
entry's counter, and marks the counter a *subtotal*. A counter is reset by the
footing of the control whose group contains it; one inside CF FINAL only at
the end.

## The cursor

`cur` is the page line. Writing a print line means writing the record (without
trailing spaces) followed by `n` newlines; a skip of `n` lines is a blank
record followed by `n` newlines. Writing never moves `cur`; the callers do.

`cur` is 0 after INITIATE. Each GENERATE adds 1 on entry and takes 1 away on
exit, so between statements it is the last written line and during one it is
the next free one. A page footing that pads the page clears the entry
increment.

**Printing one line**, in this order:

1. If `cur` is past LAST DETAIL (and no RF or PF is being printed): end the
   page and start a new one.
2. A pending NEXT GROUP from an earlier group: PLUS `n` skips `n` lines; an
   absolute `n` starts a new page if `cur` is past it and skips to it; NEXT
   PAGE ends the page and starts a new one. Otherwise an absolute LINE `n`
   starts a new page if `cur` is past `n` (in the report footing only the page
   number moves) and skips to `n`.
3. LINE PLUS `n`, unless an absolute NEXT GROUP or LINE was just applied,
   skips `n - 1` lines, except when `cur` is exactly on FIRST DETAIL.
4. If `cur` is now past LAST DETAIL (outside RF, PH and PF): new page.
5. A line with no items, or a suppressed one, prints nothing; otherwise each
   item is placed (SOURCE moved in, VALUE literal copied, GROUP INDICATE and
   PRESENT honoured), the record is written and `cur` moves on.
6. The line's own NEXT GROUP is noted for the next group.

**Ending a page:** print the PAGE FOOTING lines; then, if `cur` is short of
PAGE LIMIT, write one blank record followed by `PAGE LIMIT - cur` newlines and
set `cur` to PAGE LIMIT, otherwise set `cur` to 1.

**Starting a page:** after the first GENERATE, if `cur` is past HEADING and not
past PAGE LIMIT, fill the rest of the page with blank lines and wrap `cur` to 1.
Count the page, skip to HEADING, print the PAGE HEADING lines, skip to FIRST
DETAIL, clear GROUP INDICATE, and evaluate PRESENT AFTER NEW PAGE.

**Printing a group of one type** walks the chain: the first line of that type
prints, then its own LINE entries, then the next line in the chain is tried
for the same type. That is why a CONTROL HEADING for a major control prints the
headings of the minor controls declared after it too. A CF chain stops at a
more major control's footing.

## GENERATE and TERMINATE

Before each GENERATE (and after each USE BEFORE REPORTING procedure) the
report takes snapshots of indexed or reference-modified SOURCE items and
evaluates PRESENT WHEN: for every group at GENERATE, for footing groups only at
TERMINATE. Indexed SOURCEs therefore print the value they had when the
statement began.

**First GENERATE:** report heading, a page start, then for each control (minor
first) its CH lines, then the control values are saved.

**Later GENERATEs:** a new page if `cur` is past LAST DETAIL or the page has no
detail yet. Controls that changed are found; a change also counts for every
more minor control. For those (minor first) the old value is put back, the CF
lines print, their counters roll forward and reset, and the new value is
restored. A NEXT GROUP NEXT PAGE from a footing takes effect after all the
footings. Then the CH lines of the changed controls print.

Then every counter that is not a subtotal adds its operands, and the detail
line prints. A detail whose 01 has several LINE entries prints them all,
starting a new page first if they would pass LAST DETAIL; a detail with a
single LINE entry prints just that line, so a NEXT GROUP on its 01 has no
effect.

**TERMINATE** prints every control footing (changed or not), then CF FINAL,
ends the page, then the report footing.
A TERMINATE with no GENERATE prints nothing and leaves the report initiated.

**USE BEFORE REPORTING** runs before the group prints; in a report item's
name in COMPUTE, ADD and the other arithmetic statements and as a MOVE's
sending item, a SUM entry stands for its counter, so a procedure can use the
total that is about to print. DISPLAY and conditions see the item as last
printed.

## Where YACCC differs on purpose

GnuCOBOL 3.1.2 never prints CONTROL HEADING FINAL, ignores `SUM ... UPON` and
`RESET ON`, and at TERMINATE prints the control footings with whatever the
CONTROL fields hold by then. YACCC follows the standard on these four: it
prints CH FINAL as the first heading of the first page, adds an UPON counter
only on GENERATEs of the named DETAIL groups, resets a counter with RESET ON at
the named control's footing (or only at the end, for FINAL), and gives the
footings at TERMINATE the CONTROL values of the last GENERATE (so the usual
`MOVE HIGH-VALUES` at end of file does not show). No test in either suite
depends on them; `tests/cases/rw1.cbl` covers the first three.

## Checking a change

```
python3 tests/rw_oracle.py              # the default sweep (needs cobc 3.1.2)
python3 tests/rw_oracle.py --full       # every generated shape
python3 tests/rw_oracle.py --testsuite  # the 3.1.2 Report Writer tests
make gctest nist test
```

`cobc -C prog.cob` writes the tables cobc builds (`prog.c.l.h`: `cob_report_line`,
`cob_report_field`, `cob_report_control`, `cob_report_sum_ctr`), which is the
quickest way to see what a new shape of REPORT SECTION should turn into.
