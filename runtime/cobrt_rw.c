/* SPDX-License-Identifier: MIT */
/* cobrt_rw.c - Report Writer Control System (RWCS)
 *
 * The compiler describes each report with static tables (groups, print line
 * positions) and four callbacks generated from the REPORT SECTION:
 *   fmt   formats one print line of a group into the line buffer
 *   sum   subtotals, crossfoots, rolls forward and resets sum counters
 *   ctl   saves, compares and swaps the CONTROL data items
 *   decl  runs a USE BEFORE REPORTING procedure
 * This file implements page and line positioning, control breaks and the
 * INITIATE / GENERATE / TERMINATE statements.
 *
 * Physical layout: every page of a report with a PAGE clause occupies
 * exactly PAGE LIMIT lines of the (line sequential) report file; lines are
 * positioned with newlines, never form feeds.
 */
#include "cobrt.h"

int cob_rw_suppress;

static int lc_get(cob_report *r)
{
	return (int)cob_get_int(r->line_counter);
}

static void lc_set(cob_report *r, int v)
{
	cob_set_int(r->line_counter, v);
}

static int group_of(cob_report *r, int type, int level)
{
	for (int i = 0; i < r->ngroups; i++)
		if (r->groups[i].type == type && (level < 0 || r->groups[i].level == level))
			return i;
	return -1;
}

/* ---------------------------------------------------------------- output */

static void put_line(cob_report *r, int line, const unsigned char *buf)
{
	FILE *fp = r->file->fp;
	if (!fp)
		cob_fatal("report %s: file %s is not open for output", r->name, r->file->select_name);
	int target = r->page_start + line - 1;
	if (target < r->pos || (target == r->pos && r->open))
		target = r->pos + (r->open ? 1 : 0);   /* never overprint */
	while (r->pos < target) {
		fputc('\n', fp);
		r->pos++;
	}
	size_t n = (size_t)r->width;
	while (n && buf[n - 1] == ' ')
		n--;
	fwrite(buf, 1, n, fp);
	r->open = 1;
	r->file->linage_lines = 1;     /* CLOSE terminates the open line */
}

/* pad the current page to its last line and terminate it */
static void finish_page(cob_report *r)
{
	FILE *fp = r->file->fp;
	if (!fp)
		return;
	if (r->pl) {
		int end = r->page_start + r->pl - 1;
		while (r->pos < end) {
			fputc('\n', fp);
			r->pos++;
		}
		fputc('\n', fp);
		r->pos++;
		r->open = 0;
	} else if (r->open) {
		fputc('\n', fp);
		r->pos++;
		r->open = 0;
	}
	r->file->linage_lines = 0;
	if (fp == stdout)
		fflush(stdout);
}

/* positions of every print line of group g, the first one at `first` */
static int line_positions(const cob_rw_group *g, int first, int *pos)
{
	int cur = first;
	for (int i = 0; i < g->nlines; i++) {
		const cob_rw_lspec *l = &g->lines[i];
		if (i > 0) {
			if (l->kind == COB_RW_ABS || l->kind == COB_RW_ABSNP)
				cur = l->num > cur ? l->num : cur + 1;
			else
				cur = cur + l->num;
		}
		pos[i] = cur;
	}
	return cur;
}

static void print_group(cob_report *r, int gi, int first)
{
	const cob_rw_group *g = &r->groups[gi];
	int pos[COB_RW_MAX_LINES];
	if (g->nlines > COB_RW_MAX_LINES)
		cob_fatal("report %s: too many lines in one report group", r->name);
	line_positions(g, first, pos);
	for (int i = 0; i < g->nlines; i++) {
		lc_set(r, pos[i]);
		memset(r->buf, ' ', (size_t)r->width);
		if (r->code_len)
			memcpy(r->buf, r->code, (size_t)r->code_len);
		r->fmt(gi, i, r->buf, r->gi[gi]);
		put_line(r, pos[i], r->buf);
	}
	if (g->type == COB_RW_DE)
		r->gi[gi] = 0;
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

static void present(cob_report *r, int gi, int apply_ng);

/* NEXT GROUP after a group has been presented */
static void next_group(cob_report *r, const cob_rw_group *g)
{
	int lc = lc_get(r);
	switch (g->ng_kind) {
	case COB_RW_ABS:
		if (g->ng_num > lc)
			lc_set(r, g->ng_num);
		else if (r->pl)
			r->next_page = 1;
		break;
	case COB_RW_REL:
		lc_set(r, lc + g->ng_num);
		break;
	case COB_RW_NP:
		if (r->pl)
			r->next_page = 1;
		break;
	}
}

/* start a new page without page footing / heading (report heading or footing alone) */
static void bare_advance(cob_report *r)
{
	r->page_start += r->pl;
	cob_set_int(r->page_counter, cob_get_int(r->page_counter) + 1);
	lc_set(r, 0);
	r->body_on_page = 0;
	r->next_page = 0;
}

static void page_advance(cob_report *r)
{
	if (r->pf >= 0)
		present(r, r->pf, 0);
	bare_advance(r);
	for (int i = 0; i < r->ngroups; i++)
		if (r->groups[i].type == COB_RW_DE)
			r->gi[i] = 1;
	if (r->ph >= 0)
		present(r, r->ph, 0);
}

static int first_body_line(cob_report *r, const cob_rw_group *g, int lc)
{
	const cob_rw_lspec *l = &g->lines[0];
	switch (l->kind) {
	case COB_RW_ABS:
	case COB_RW_ABSNP:
		return lc < l->num ? l->num : -1;
	case COB_RW_NP:
		return r->pl ? (lc < r->fd ? r->fd : lc + 1) : lc + 1;
	default:
		if (r->pl && lc < r->fd)
			return r->fd;
		return lc + l->num;
	}
}

static void present_body(cob_report *r, int gi, int apply_ng)
{
	const cob_rw_group *g = &r->groups[gi];
	if (g->nlines == 0) {
		if (apply_ng)
			next_group(r, g);
		return;
	}
	int lc = lc_get(r);
	int first;
	if (r->pl) {
		int limit = g->type == COB_RW_CF ? r->ft : r->ld;
		int adv = r->next_page;
		int k = g->lines[0].kind;
		if ((k == COB_RW_ABSNP || k == COB_RW_NP) && r->body_on_page)
			adv = 1;
		if (!adv) {
			first = first_body_line(r, g, lc);
			if (first < 0)
				adv = 1;
			else {
				int pos[COB_RW_MAX_LINES];
				int last = line_positions(g, first, pos);
				if (last > limit && !(lc < r->fd && first == r->fd))
					adv = 1;
			}
		}
		if (adv) {
			page_advance(r);
			lc = lc_get(r);
		}
		first = first_body_line(r, g, lc);
		if (first < 0)
			first = lc + 1;
	} else {
		first = first_body_line(r, g, lc);
		if (first < 0)
			first = lc + 1;
	}
	print_group(r, gi, first);
	r->body_on_page = 1;
	if (apply_ng)
		next_group(r, g);
}

static void present(cob_report *r, int gi, int apply_ng)
{
	const cob_rw_group *g = &r->groups[gi];
	if (before_reporting(r, gi))
		return;
	int lc = lc_get(r);
	int first;
	const cob_rw_lspec *l0 = g->nlines ? &g->lines[0] : NULL;
	switch (g->type) {
	case COB_RW_PH:
	case COB_RW_RH:
		if (!l0)
			break;
		if (l0->kind == COB_RW_ABS || l0->kind == COB_RW_ABSNP)
			first = l0->num;
		else {
			int base = r->pl && lc < r->h - 1 ? r->h - 1 : lc;
			first = base + (l0->kind == COB_RW_NP ? 1 : l0->num);
		}
		print_group(r, gi, first);
		if (g->type == COB_RW_RH && apply_ng) {
			if (g->ng_kind == COB_RW_NP && r->pl)
				bare_advance(r);
			else
				next_group(r, g);
		}
		return;
	case COB_RW_PF:
		if (!l0)
			return;
		if (l0->kind == COB_RW_ABS || l0->kind == COB_RW_ABSNP)
			first = l0->num;
		else
			first = (r->pl ? r->ft : lc) + (l0->kind == COB_RW_NP ? 1 : l0->num);
		print_group(r, gi, first);
		return;
	case COB_RW_RF:
		if (!l0)
			return;
		if (l0->kind == COB_RW_ABSNP || l0->kind == COB_RW_NP) {
			if (r->pl)
				bare_advance(r);
			first = l0->kind == COB_RW_ABSNP ? l0->num : (r->pl ? r->h : lc + 1);
		} else if (l0->kind == COB_RW_ABS) {
			if (r->pl && lc >= l0->num)
				bare_advance(r);
			first = l0->num;
		} else {
			int pos[COB_RW_MAX_LINES];
			first = lc + l0->num;
			if (r->pl && line_positions(g, first, pos) > r->pl) {
				bare_advance(r);
				first = r->h - 1 + l0->num;
			}
		}
		print_group(r, gi, first);
		return;
	default:
		present_body(r, gi, apply_ng);
		return;
	}
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
	if (!r->file->open_mode || !r->file->fp)
		cob_fatal("%s: INITIATE for report %s: file %s is not open", loc, r->name, r->file->select_name);
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
	lc_set(r, 0);
	/* the report starts on a fresh page of the file */
	if (r->file->fp != stdout && ftell(r->file->fp) == 0) {
		r->pos = 0;
		r->open = 0;
	}
	if (r->open) {
		fputc('\n', r->file->fp);
		r->pos++;
		r->open = 0;
	}
	r->page_start = r->pos;
	r->body_on_page = 0;
	r->next_page = 0;
	r->terminating = 0;
	r->generated = 0;
	r->initiated = 1;
	r->sum(3, -1);     /* all sum counters to zero */
}

/* control footing processing for level `lev` */
static void footing(cob_report *r, int lev, int apply_ng)
{
	int gi = r->cf[lev];
	if (gi >= 0) {
		r->sum(1, gi);             /* crossfoot */
		present(r, gi, apply_ng);
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
	if (!r->generated) {
		r->generated = 1;
		if (r->rh >= 0)
			present(r, r->rh, 1);
		if (r->ph >= 0)
			present(r, r->ph, 0);
		for (int lev = 0; lev <= n; lev++)
			if (r->ch[lev] >= 0)
				present(r, r->ch[lev], 1);
		r->ctl(0);
	} else if (n > 0) {
		int lev = r->ctl(1);
		if (lev > 0) {
			r->ctl(2);             /* prior control values for the footings */
			for (int l = n; l >= lev; l--)
				footing(r, l, l == lev);
			r->ctl(2);
			for (int i = 0; i < r->ngroups; i++)
				if (r->groups[i].type == COB_RW_DE)
					r->gi[i] = 1;
			for (int l = lev; l <= n; l++)
				if (r->ch[l] >= 0)
					present(r, r->ch[l], 1);
			r->ctl(0);
		}
	}
	r->sum(0, gi);                     /* subtotaling */
	if (gi >= 0)
		present(r, gi, 1);
}

void cob_rw_terminate(cob_report *r, const char *loc)
{
	if (!r->initiated)
		cob_fatal("%s: TERMINATE for report %s that is not initiated", loc, r->name);
	if (r->generated) {
		r->terminating = 1;
		if (r->ncontrols)
			r->ctl(2);             /* values as of the last GENERATE */
		for (int l = r->ncontrols; l >= 0; l--)
			footing(r, l, 0);
		if (r->ncontrols)
			r->ctl(2);
		if (r->pf >= 0)
			present(r, r->pf, 0);
		if (r->rf >= 0)
			present(r, r->rf, 0);
		finish_page(r);
		r->terminating = 0;
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
