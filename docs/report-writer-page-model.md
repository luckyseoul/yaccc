# Report Writer: where every line goes

YACCC's Report Writer (`lib/yaccc/rwgen.py` builds the tables,
`runtime/cobrt_rw.c` runs them) reproduces the output of GnuCOBOL 3.1.2,
because that is what 3.1.2's testsuite and the NIST Report Writer programs
check. It matches `cobc` byte for byte on every runnable Report Writer test in
that testsuite, on all 527 report shapes `tests/rw_oracle.py --full`
generates, and on the differential tests in `tests/cases/rw*.cbl`.

The rules below were established by measuring `cobc`'s output, not by reading
its source. Two tools did the measuring:

- `tests/rw_oracle.py` generates report programs that vary every page setting
  (PAGE LIMIT, HEADING, FIRST DETAIL, LAST DETAIL, FOOTING, a page footing,
  NEXT GROUP, line spacing, record sequences) and compares the report files
  from both compilers;
- a probe that rewrites such a program so that every printed line also shows
  PAGE-COUNTER and LINE-COUNTER. The counters show what each compiler
  *thinks* the line is, not just where it landed, which is what separated the
  rules below from look-alikes.

## The tables

A report is a list of groups (one per 01 entry), each with its print lines (one
per LINE entry), its NEXT GROUP clause, a PRESENT WHEN condition and a flag for
a USE BEFORE REPORTING procedure.

- An 01 LINE clause is dropped when the 01's first subordinate entry has one
  too. The 01 then counts as a print line of its own that holds nothing (see
  *An empty 01 line* below), as does an 01 without LINE whose lines come from
  the entries below it.
- A second absolute `LINE n` in one group, with the same `n` as an earlier one,
  does not start a line: the entry joins the line before it.
- PRESENT WHEN / ABSENT WHEN on a LINE entry decides whether the whole line is
  there; on a group item below the line it decides whether that item's
  elementary items print; on the 01 it decides for the whole group.
- A group item below a line starts its own run of columns: `COLUMN PLUS n` and
  items without a COLUMN clause count from its first column. A `FILLER` group
  holding `COLUMN PLUS 1` prints in column 1.
- A print line with no items positions like any other and prints nothing.
- LINE-COUNTER and PAGE-COUNTER are unsigned 32-bit binary items, so DISPLAY
  shows ten digits.

## The cursor

`cur` is the line of the page the report stands on.

- INITIATE sets it to 0.
- GENERATE adds one on entry and takes it off again on exit. So the same LINE
  clause lands one line lower inside a GENERATE than inside TERMINATE, and
  between statements LINE-COUNTER shows the last line written.
- A record and a blank line each move it down one. A record is its text
  without trailing spaces, then a newline. With a CODE clause every line,
  blank ones included, starts with the code.

## Placing a print line

In this order:

1. Past LAST DETAIL: a new page. Not for a page footing or report footing.
2. A NEXT GROUP waiting from an earlier group places the line: `PLUS n` adds
   `n` blank lines; an absolute `n` takes a new page if the cursor is past `n`
   and goes down to `n`; NEXT PAGE takes a new page. Failing that, the line's
   own absolute `LINE n` takes a new page if the cursor is past `n` (a report
   footing only counts the page and goes back to line 1) and goes down to `n`.
   `LINE n ON NEXT PAGE` also takes a new page when the page already has body
   lines, except in the report footing.
3. `LINE PLUS n` adds `n - 1` blank lines, unless an absolute NEXT GROUP or
   NEXT PAGE was just taken, or the cursor is exactly on FIRST DETAIL.
4. Past LAST DETAIL again: a new page. Not for a page heading, page footing or
   report footing.

Then the line is formatted; if it is present it is written.

**NEXT GROUP** waits after the group that has it and is taken by the next
body line (control heading, detail, control footing), with four exceptions:

- after a page start within the same GENERATE it waits until a detail line
  (a report heading's `NEXT GROUP NEXT PAGE` skips the control heading that
  follows the first page heading and lands on the first detail);
- a `NEXT GROUP NEXT PAGE` from a control footing waits for the last footing
  of the break;
- the footings TERMINATE presents leave none;
- a DETAIL group whose lines are LINE entries below its 01 leaves none,
  whether it has one line or several. A DETAIL 01 with its own LINE clause
  leaves its NEXT GROUP like any other group.

**An empty 01 line.** A control heading or footing whose lines come from LINE
entries below its 01 gets the checks of steps 1 and 4 once more, for the 01
itself, before its first line. A detail group goes straight to its lines. Only
a report whose page heading sits on its single body line can tell the
difference: there each such group costs four page changes instead of two.

## Ending and starting a page

**Ending a page:** the page footing, then blank lines down to PAGE LIMIT; a
cursor already at or past PAGE LIMIT goes back to 1 instead. A page end asked
for while the page footing itself is printing does nothing.

**Starting a page:** a cursor still between HEADING and PAGE LIMIT finishes the
old page's last line with one more blank line and goes back to line 1. The page
is counted, the cursor goes down to HEADING, the page heading prints, and the
cursor goes down to FIRST DETAIL. GROUP INDICATE starts over. A page start asked
for while the page heading itself is printing does nothing.

**A page change while placing a line** is an end and a start. A page change
that is not part of placing a line — GENERATE finding the page already past
LAST DETAIL, or a detail group of several lines that will not fit — ends the
page, puts the cursor on line 1 and starts the next, so the old page's last
line is not finished.

**During the first GENERATE** a page start neither counts the page nor brings
the cursor back up. Its page heading then finds the cursor past LAST DETAIL
and asks for another page: that end prints the page footing where the cursor
stands (no blank lines, since the cursor is at PAGE LIMIT) and puts the cursor
on line 1, and the heading prints there. Measured: such a heading shows
PAGE-COUNTER 1 and LINE-COUNTER 1, whatever HEADING says. Because its own page
start never ran, the next GENERATE begins with that heading — on line 1, no
footing, no blank lines.

## GENERATE and TERMINATE

**First GENERATE:** the report heading, the first page start, the control
headings (FINAL first), then the control values are saved.

**Later GENERATEs:** a page change if the cursor is past LAST DETAIL (or the
pending heading described above). If a control changed, the footings from the
most minor control up to the one that changed are presented with the previous
control values, each crossfooted, rolled forward and reset; then the headings
from the changed control down; then the new values are saved.

Then the sums are added and the detail prints. A detail of several lines first
takes a new page if the cursor plus its `LINE PLUS` steps greater than one
would pass LAST DETAIL.

**TERMINATE** presents every control footing, FINAL last, with the control
values of the last GENERATE; ends the page; then the report footing.

**Without a PAGE clause** nothing is positioned: every line follows the one
before, whatever its LINE clause, and LINE-COUNTER stays 0.

## Where YACCC differs on purpose

GnuCOBOL 3.1.2 never prints CONTROL HEADING FINAL, ignores `SUM ... UPON` and
`RESET ON`, and at TERMINATE presents the control footings with whatever the
CONTROL fields hold by then. YACCC follows the standard on these four; no test
in either suite depends on them, and `tests/cases/rw1.cbl` covers them.

PRESENT WHEN and ABSENT WHEN on an elementary report item follow the standard
too. GnuCOBOL 3.1.2's are erratic (measured: a PRESENT WHEN item never
printed, and an ABSENT WHEN item printed one GENERATE after its condition
turned false), and no test depends on them. On a LINE entry or a group item
the two compilers agree.

## Checking a change

```
python3 tests/rw_oracle.py --full       # every generated shape (needs cobc 3.1.2)
python3 tests/rw_oracle.py --testsuite  # the 3.1.2 Report Writer tests
python3 tests/gnucobol/compare.py "Sample Payroll Report"
make test gctest nist provenance-deep
```
