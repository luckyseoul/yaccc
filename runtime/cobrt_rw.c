/* SPDX-License-Identifier: MIT */
/* cobrt_rw.c - Report Writer Control System (RWCS)
 *
 * The compiler describes each report with static tables (groups and their
 * print lines) and four callbacks generated from the REPORT SECTION:
 *   fmt   formats one print line of a group into the line buffer and says
 *         whether the line is present at all (PRESENT WHEN on its LINE entry)
 *   sum   subtotals, crossfoots, rolls forward and resets sum counters
 *   ctl   saves, compares and swaps the CONTROL data items
 *   decl  runs a USE BEFORE REPORTING procedure
 * This file implements page and line positioning, control breaks and the
 * INITIATE / GENERATE / TERMINATE statements.
 *
 * Positioning. The report file is line sequential: a record is its text and a
 * newline, a blank line is a newline. Where the next record goes is decided by
 * one number, r->cur, the line of the page the report stands on. The rules for
 * it reproduce GnuCOBOL 3.1.2's output, which is what that version's testsuite
 * and NIST check; they were measured with tests/rw_oracle.py against a live
 * cobc, and docs/report-writer-page-model.md lists them. In short:
 *
 *  - INITIATE sets the cursor to 0. GENERATE adds one on entry and takes it
 *    off on exit, so the same LINE clause lands one line lower inside a
 *    GENERATE than in TERMINATE.
 *  - A record or a blank line moves the cursor down one.
 *  - Before a print line: past LAST DETAIL is a new page (not for a page or
 *    report footing); then a NEXT GROUP left by the group before, or failing
 *    that the line's own absolute LINE, places it; LINE PLUS n adds n - 1 blank
 *    lines unless the cursor is exactly on FIRST DETAIL; and past LAST DETAIL
 *    once more is a new page (not for page heading or footing, report footing).
 *  - A page ends with its page footing and blank lines down to PAGE LIMIT; the
 *    next starts with the blank line that completes the old one, then its page
 *    heading at HEADING and blank lines down to FIRST DETAIL.
 */
#include "cobrt.h"

int cob_rw_suppress;
int cob_rw_new_page;            /* the line being formatted starts a page */
int cob_rw_ctl_change;          /* control level that changed for that line */

static int group_of(cob_report *r, int type, int level)
{
	for (int i = 0; i < r->ngroups; i++)
		if (r->groups[i].type == type && (level < 0 || r->groups[i].level == level))
			return i;
	return -1;
}

static int is_body(int type)
{
	return type == COB_RW_CH || type == COB_RW_DE || type == COB_RW_CF;
}

/* ---------------------------------------------------------------- output */

static FILE *report_out(cob_report *r)
{
	FILE *fp = r->file->fp;
	if (fp == NULL)
		cob_fatal("report %s: file %s is not open for output", r->name, r->file->select_name);
	return fp;
}

/* n blank lines; the cursor goes down with them. A report with a CODE
 * clause has its code on every line, blank ones included (measured). */
static void blank_lines(cob_report *r, int n)
{
	if (n <= 0)
		return;
	FILE *fp = report_out(r);
	r->cur += n;
	while (n-- > 0) {
		if (r->code_len)
			fwrite(r->code, 1, (size_t)r->code_len, fp);
		fputc('\n', fp);
	}
}

static void down_to(cob_report *r, int line)
{
	blank_lines(r, line - r->cur);
}

/* the formatted line in r->buf, without its trailing spaces */
static void write_line(cob_report *r)
{
	FILE *fp = report_out(r);
	size_t n = (size_t)r->width;
	while (n > 0 && r->buf[n - 1] == ' ')
		n--;
	fwrite(r->buf, 1, n, fp);
	fputc('\n', fp);
	r->cur++;
}

/* LINE-COUNTER: the cursor while it is on the page, otherwise 0 */
static void show_cursor(cob_report *r)
{
	int v = r->cur;
	if (r->pl == 0 || v < 0 || v > r->pl)
		v = 0;
	cob_set_int(r->line_counter, v);
}

/* ---------------------------------------------------------------- pages */

static void present(cob_report *r, int gi);

static void count_page(cob_report *r)
{
	cob_set_int(r->page_counter, cob_get_int(r->page_counter) + 1);
}

/* The page footing, then blank lines down to PAGE LIMIT. A page end asked
 * for while the page footing itself is being presented does nothing. */
static void end_page(cob_report *r)
{
	if (r->ending)
		return;
	r->heading_due = 1;
	if (r->pf >= 0) {
		r->ending = 1;
		present(r, r->pf);
		r->ending = 0;
	}
	if (r->cur < r->pl)
		blank_lines(r, r->pl - r->cur);
	else
		r->cur = 1;
}

/* The top of a page: outside the first GENERATE, a cursor still between
 * HEADING and PAGE LIMIT finishes the old page's last line and returns to
 * line 1, and the page is counted; then the page heading at HEADING and blank
 * lines down to FIRST DETAIL. A page start asked for while the page heading
 * is being presented does nothing.
 *
 * The first GENERATE neither counts the page nor brings the cursor back up,
 * so its page heading finds the cursor past LAST DETAIL and asks for another
 * page: that end (a page footing printed where the cursor stands, no blank
 * lines since the cursor is at PAGE LIMIT) puts the cursor on line 1, and the
 * heading prints there. Measured: such a heading shows PAGE-COUNTER 1 and
 * LINE-COUNTER 1 whatever HEADING says. */
static void start_page(cob_report *r)
{
	if (r->starting)
		return;
	r->starting = 1;
	r->heading_due = 0;
	r->just_set = 1;
	if (!r->first_gen) {
		if (r->cur > r->h && r->cur <= r->pl) {
			blank_lines(r, r->pl - r->cur + 1);
			r->cur = 1;
		}
		count_page(r);
	}
	down_to(r, r->h);
	if (r->ph >= 0)
		present(r, r->ph);
	down_to(r, r->fd);
	for (int i = 0; i < r->ngroups; i++)
		if (r->groups[i].type == COB_RW_DE)
			r->gi[i] = 1;
	r->body_on_page = 0;
	r->starting = 0;
}

/* a page change while a line is being placed */
static void new_page(cob_report *r)
{
	end_page(r);
	start_page(r);
}

/* A page change that is not part of placing a line (GENERATE finding the page
 * already full, a detail group that will not fit): the cursor restarts at the
 * top without finishing the old page's last line. */
static void fresh_page(cob_report *r)
{
	end_page(r);
	r->cur = 1;
	start_page(r);
}

static int beyond_last_detail(const cob_report *r)
{
	return r->pl > 0 && r->cur > r->ld;
}

/* Take the NEXT GROUP waiting for this line, if it may have it: only a body
 * line takes one, and not after a page has been started in the same GENERATE
 * until a detail line comes (measured: a report heading's NEXT GROUP NEXT
 * PAGE skips the control heading that follows the first page heading and
 * lands on the first detail). A NEXT PAGE from a control footing waits for
 * the last footing of the break. */
static int take_next_group(cob_report *r, const cob_rw_group *g, int *num)
{
	int kind = r->pend_kind;
	if (!kind || !is_body(g->type) || r->just_set)
		return 0;
	if (kind == COB_RW_NP && g->type == COB_RW_CF && r->breaking)
		return 0;
	r->pend_kind = 0;
	*num = r->pend_num;
	return kind;
}

/* Put the cursor on the line where print line i of group g goes, changing
 * page first where the rules call for it. Once an absolute position has been
 * taken (an absolute NEXT GROUP, or NEXT PAGE), the line's own LINE PLUS adds
 * no blank lines. */
static void place(cob_report *r, const cob_rw_group *g, int i)
{
	const cob_rw_lspec *l = &g->lines[i];
	int footer = g->type == COB_RW_PF || g->type == COB_RW_RF;
	int relative_ok = 1;
	int num = 0;

	/* Without a PAGE clause there is no page to place on: every line follows
	 * the one before, whatever its LINE clause (measured: LINE PLUS 2 groups
	 * print on consecutive lines and LINE-COUNTER stays 0). */
	if (r->pl == 0)
		return;
	if (g->type == COB_RW_DE)
		r->just_set = 0;

	if (!footer && beyond_last_detail(r))
		new_page(r);

	switch (take_next_group(r, g, &num)) {
	case COB_RW_REL:
		blank_lines(r, num);
		break;
	case COB_RW_ABS:
		if (r->cur > num)
			new_page(r);
		down_to(r, num);
		relative_ok = 0;
		break;
	case COB_RW_NP:
		new_page(r);
		relative_ok = 0;
		break;
	default:
		if (l->kind == COB_RW_ABS || l->kind == COB_RW_ABSNP) {
			/* LINE n ON NEXT PAGE takes a new page when the page already
			 * has body lines; a report footing, which TERMINATE presents
			 * after ending the page, only moves to line n (measured) */
			if (r->cur > l->num || (l->kind == COB_RW_ABSNP && r->body_on_page &&
			                        g->type != COB_RW_RF)) {
				if (g->type == COB_RW_RF) {
					/* a report footing that needs a fresh page takes
					 * only the page number with it */
					end_page(r);
					count_page(r);
					r->cur = 1;
				} else {
					new_page(r);
				}
			}
			down_to(r, l->num);
		} else if (l->kind == COB_RW_NP && r->body_on_page) {
			new_page(r);
			relative_ok = 0;
		}
		break;
	}

	if (relative_ok && l->kind == COB_RW_REL && l->num > 1 &&
	    !(r->fd > 0 && r->cur == r->fd))
		blank_lines(r, l->num - 1);

	if (!footer && g->type != COB_RW_PH && beyond_last_detail(r))
		new_page(r);
}

/* ---------------------------------------------------------------- groups */

/* The 01 entry of a group whose lines come from LINE entries below it is a
 * print line with nothing on it: it gets the page checks a line gets before
 * and after placing, and prints nothing. A DETAIL group goes straight to its
 * LINE entries. Only a report whose page heading sits on its one body line
 * can tell the difference (measured: four page changes for such a control
 * footing, two for a detail). */
static void group_line(cob_report *r, const cob_rw_group *g)
{
	if (g->type == COB_RW_PF || g->type == COB_RW_RF)
		return;
	if (beyond_last_detail(r))
		new_page(r);
	if (g->type != COB_RW_PH && beyond_last_detail(r))
		new_page(r);
}

/* USE BEFORE REPORTING; returns 1 if the group is to be suppressed */
static int before_reporting(cob_report *r, int gi)
{
	if (!r->groups[gi].has_decl)
		return 0;
	cob_rw_suppress = 0;
	r->decl(gi);
	int s = cob_rw_suppress;
	cob_rw_suppress = 0;
	return s;
}

static void present(cob_report *r, int gi)
{
	const cob_rw_group *g = &r->groups[gi];
	if (before_reporting(r, gi))
		return;
	if (g->present_when) {
		int on = g->present_when() != 0;
		if (g->absent)
			on = !on;
		if (!on)
			return;
	}
	if (g->nlines > COB_RW_MAX_LINES)
		cob_fatal("report %s: too many lines in one report group", r->name);
	int body = is_body(g->type);
	if (g->hdr && g->type != COB_RW_DE && r->pl > 0)
		group_line(r, g);
	for (int i = 0; i < g->nlines; i++) {
		place(r, g, i);
		show_cursor(r);
		memset(r->buf, ' ', (size_t)r->width);
		if (r->code_len)
			memcpy(r->buf, r->code, (size_t)r->code_len);
		cob_rw_new_page = body && !r->body_on_page;
		int shown = r->fmt(gi, i, r->buf, r->gi[gi]);
		cob_rw_new_page = 0;
		if (!shown)
			continue;
		write_line(r);
		if (body)
			r->body_on_page = 1;
	}
	if (g->type == COB_RW_DE)
		r->gi[gi] = 0;
	/* NEXT GROUP waits for the next body group. The footings TERMINATE
	 * presents leave none (measured: a customer footing with NEXT GROUP PLUS 2
	 * is followed directly by the final footing), and neither does a DETAIL
	 * group whose lines are LINE entries below its 01, one or several
	 * (measured: its NEXT GROUP PLUS 2 adds nothing anywhere). */
	if (g->ng_kind && (is_body(g->type) || g->type == COB_RW_RH) && !r->terminating &&
	    !(g->type == COB_RW_DE && g->hdr)) {
		r->pend_kind = g->ng_kind;
		r->pend_num = g->ng_num;
	}
}

/* A detail group of several lines starts a new page when the LINE PLUS steps
 * greater than one would carry it past LAST DETAIL. */
static void present_detail(cob_report *r, int gi)
{
	const cob_rw_group *g = &r->groups[gi];
	if (r->pl > 0 && g->nlines > 1) {
		int steps = 0;
		for (int i = 0; i < g->nlines; i++)
			if (g->lines[i].kind == COB_RW_REL && g->lines[i].num > 1)
				steps += g->lines[i].num;
		if (r->cur + steps > r->ld)
			fresh_page(r);
	}
	present(r, gi);
}

/* ---------------------------------------------------------------- statements */

void cob_rw_initiate(cob_report *r, const char *loc)
{
	if (r->initiated) {
		/* EC-REPORT-ACTIVE: the INITIATE is not executed */
		cob_set_exception("EC-REPORT-ACTIVE");
		cob_warning("%s: INITIATE for report %s that is already initiated", loc, r->name);
		return;
	}
	/* GnuCOBOL's INITIATE does not look at the file, and neither does this
	 * one: a program may INITIATE a report before it OPENs the file and
	 * GENERATE into it afterwards (run_reportwriter.at's "Report PRESENT
	 * AFTER" does exactly that). The write path reports a closed file if the
	 * report is still unopened when a line is due. */
	if (!r->buf) {
		r->buf = cob_malloc((size_t)r->width + 1);
		r->gi = cob_malloc((size_t)r->ngroups + 1);
		r->ch = cob_malloc(sizeof(int) * (size_t)(r->ncontrols + 1));
		r->cf = cob_malloc(sizeof(int) * (size_t)(r->ncontrols + 1));
		for (int lev = 0; lev <= r->ncontrols; lev++) {
			r->ch[lev] = group_of(r, COB_RW_CH, lev);
			r->cf[lev] = group_of(r, COB_RW_CF, lev);
		}
		r->rh = group_of(r, COB_RW_RH, -1);
		r->ph = group_of(r, COB_RW_PH, -1);
		r->pf = group_of(r, COB_RW_PF, -1);
		r->rf = group_of(r, COB_RW_RF, -1);
	}
	for (int i = 0; i < r->ngroups; i++)
		r->gi[i] = 1;
	cob_set_int(r->page_counter, 1);
	r->cur = 0;
	r->pend_kind = 0;
	r->just_set = 0;
	r->heading_due = 0;
	r->breaking = 0;
	r->body_on_page = 0;
	r->terminating = 0;
	r->generated = 0;
	r->initiated = 1;
	show_cursor(r);
	r->sum(3, -1);     /* all sum counters to zero */
}

/* control footing processing for level `lev` */
static void footing(cob_report *r, int lev)
{
	int gi = r->cf[lev];
	if (gi >= 0) {
		r->sum(1, gi);             /* crossfoot */
		present(r, gi);
		r->sum(2, gi);             /* roll forward */
	}
	if (!r->terminating)
		r->sum(4, lev);            /* reset counters of this level */
}

void cob_rw_generate(cob_report *r, int gi, const char *loc)
{
	if (!r->initiated)
		cob_fatal("%s: GENERATE for report %s that is not initiated", loc, r->name);
	int n = r->ncontrols;
	int changed = 0;                   /* control level that changed, for PRESENT AFTER */
	r->cur++;                          /* the line GENERATE stands on */
	r->just_set = 0;
	if (!r->generated) {
		r->generated = 1;
		r->first_gen = 1;
		if (r->rh >= 0)
			present(r, r->rh);
		if (r->pl > 0)
			start_page(r);
		for (int lev = 0; lev <= n; lev++)
			if (r->ch[lev] >= 0)
				present(r, r->ch[lev]);
		r->ctl(0);
		/* the first detail of a report follows every control heading */
		changed = n > 0 ? 1 : 0;
	} else {
		if (beyond_last_detail(r)) {
			fresh_page(r);
		} else if (r->heading_due) {
			/* a page ended whose heading never ran (the first GENERATE's
			 * page heading asked for it while it was itself printing):
			 * the heading comes now, with no footing and no blank lines */
			r->cur = 1;
			start_page(r);
		}
		if (n > 0) {
			int lev = r->ctl(1);
			changed = lev;
			if (lev > 0) {
				r->ctl(2);             /* prior control values for the footings */
				r->breaking = 1;
				for (int l = n; l >= lev; l--)
					footing(r, l);
				r->breaking = 0;
				r->ctl(2);
				for (int i = 0; i < r->ngroups; i++)
					if (r->groups[i].type == COB_RW_DE)
						r->gi[i] = 1;
				for (int l = lev; l <= n; l++)
					if (r->ch[l] >= 0)
						present(r, r->ch[l]);
				r->ctl(0);
			}
		}
	}
	r->sum(0, gi);                     /* subtotaling */
	if (gi >= 0) {
		cob_rw_ctl_change = changed;
		present_detail(r, gi);
		cob_rw_ctl_change = 0;
	}
	r->cur--;
	r->first_gen = 0;
	show_cursor(r);
}

void cob_rw_terminate(cob_report *r, const char *loc)
{
	if (!r->initiated)
		cob_fatal("%s: TERMINATE for report %s that is not initiated", loc, r->name);
	if (r->generated) {
		r->terminating = 1;
		if (r->ncontrols)
			r->ctl(2);             /* values as of the last GENERATE */
		r->breaking = 1;
		for (int l = r->ncontrols; l >= 0; l--)
			footing(r, l);
		r->breaking = 0;
		if (r->ncontrols)
			r->ctl(2);
		if (r->pl > 0)
			end_page(r);
		if (r->rf >= 0)
			present(r, r->rf);
		r->terminating = 0;
		show_cursor(r);
	}
	r->initiated = 0;
	r->generated = 0;
}

/* COLUMN LEFT / RIGHT / CENTER: the printable part of a report item (without
   leading and trailing spaces) aligned within the item's columns, with
   GnuCOBOL's rounding for CENTER. */
void cob_rw_justify(unsigned char *p, int size, int mode)
{
    int b = 0, e = size;
    while (b < e && p[b] == ' ')
        b++;
    while (e > b && (p[e - 1] == ' ' || p[e - 1] == 0))
        e--;
    int n = e - b, at = 0;
    if (mode == 'R')
        at = size - n;
    else if (mode == 'C')
        at = n < size ? (size - n - (1 - (n & 1))) / 2 : 0;
    if (at < 0)
        at = 0;
    if (b == at && e == size)
        return;
    memmove(p + at, p + b, (size_t)n);
    memset(p, ' ', (size_t)at);
    memset(p + at + n, ' ', (size_t)(size - at - n));
}
