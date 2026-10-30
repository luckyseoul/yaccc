/* SPDX-License-Identifier: MIT */
/* cobrt_rw.c - Report Writer Control System (RWCS)
 *
 * The page model follows GnuCOBOL 3.1.2's observable behaviour, which is what
 * its testsuite and the NIST RW programs check: a report is a chain of print
 * lines (one per 01 group and per LINE entry), walked by group type, with a
 * line cursor that each GENERATE advances on entry and steps back on exit.
 * The tables come from the compiler (lib/yaccc/rwgen.py), which builds them the
 * same way cobc does; docs/report-writer-page-model.md describes the rules.
 *
 * Each print line is one record of the report file, written "before
 * advancing n lines": its text without trailing spaces, then n newlines. A
 * skip of n blank lines is a blank record written before advancing n.
 */
#include "cobrt.h"

#define NOT_DETAIL (COB_RWF_RH | COB_RWF_RF | COB_RWF_PH | COB_RWF_PF | \
                    COB_RWF_CH | COB_RWF_CH_FINAL | COB_RWF_CF | COB_RWF_CF_FINAL)

static cob_report *suppress_rep;        /* report whose USE procedure is running */

static void print_line(cob_report *r, cob_rwline *l);
static int print_kind(cob_report *r, cob_rwline *l, unsigned kind);

/* ---------------------------------------------------------------- output */

static void blank_rec(cob_report *r)
{
	memset(r->rec, ' ', (size_t)r->recsz);
}

/* one record, then `n` line advances */
static void put_rec(cob_report *r, int n)
{
	FILE *fp = r->file->fp;
	if (!fp)
		cob_fatal("report %s: file %s is not open for output", r->name, r->file->select_name);
	size_t size = (size_t)r->recsz;
	if (size > (size_t)r->cols)
		size = (size_t)r->cols;
	if (r->code_len > 0) {
		/* CODE: every physical line starts with the code, blank ones too */
		int k = n > 1 ? n : 1;
		for (int i = 0; i < k; i++) {
			fwrite(r->code, 1, (size_t)r->code_len, fp);
			size_t m = size;
			while (m && r->rec[m - 1] == ' ')
				m--;
			fwrite(r->rec, 1, m, fp);
			int nl = n > 1 ? 1 : n;
			for (int j = 0; j < nl; j++)
				fputc('\n', fp);
			if (n > 1)
				memset(r->rec, ' ', size);
		}
	} else {
		size_t m = size;
		while (m && r->rec[m - 1] == ' ')
			m--;
		fwrite(r->rec, 1, m, fp);
		for (int j = 0; j < n; j++)
			fputc('\n', fp);
	}
	if (fp == stdout)
		fflush(stdout);
}

/* LINE-COUNTER and PAGE-COUNTER as the program sees them */
static void show_counters(cob_report *r)
{
	int ln = r->cur;
	if (ln > r->lines || ln < 0)
		ln = 0;
	cob_set_int(r->page_counter, r->page);
	cob_set_int(r->line_counter, ln);
}

/* ---------------------------------------------------------------- tables */

/* the line whose item list actually prints: a group line that has none of
 * its own leaves them on the line below it */
static cob_rwline *with_fields(cob_rwline *l)
{
	if (l == NULL || l->fields != NULL || l->first_line == NULL)
		return l;
	return with_fields(l->first_line);
}

static void each_line(cob_rwline *l, void (*fn)(cob_rwline *))
{
	for (; l; l = l->next_line) {
		fn(l);
		if (l->first_line)
			each_line(l->first_line, fn);
	}
}

static void reset_gi(cob_rwline *l)
{
	for (cob_rwfld *f = l->fields; f; f = f->next)
		f->gi = 0;
}

static void reset_sup(cob_rwline *l)
{
	l->sup = 0;
	for (cob_rwfld *f = l->fields; f; f = f->next)
		if (!(f->flags & COB_RWF_GROUP))
			f->sup = 0;
}

static cob_rwline *find_kind(cob_rwline *l, unsigned kind)
{
	for (; l; l = l->next_line) {
		if (l->flags & kind)
			return l;
		if (l->first_line) {
			cob_rwline *t = find_kind(l->first_line, kind);
			if (t)
				return t;
		}
	}
	return NULL;
}

/* the order (1 = minor) of the control a line belongs to, -1 for none */
static int control_order(cob_report *r, cob_rwline *l)
{
	for (int i = 0; i < r->ncontrols; i++) {
		cob_rwctl *c = &r->controls[i];
		for (int k = 0; k < c->nrefs; k++)
			if (c->refs[k] == l)
				return c->seq;
	}
	return -1;
}

/* NEXT GROUP of a line takes effect at the next group */
static void note_next_group(cob_report *r, cob_rwline *l)
{
	if (l->flags & COB_RWF_NG_LINE) {
		r->next_value = l->ngl;
		r->next_line = 1;
		r->just_set = 1;
		r->next_plus = 0;
	}
	if (l->flags & COB_RWF_NG_PLUS) {
		r->next_value = l->ngl;
		r->next_line = 0;
		r->next_plus = 1;
		r->just_set = 1;
	}
	if (l->flags & COB_RWF_NG_PAGE) {
		r->next_value = l->ngl;
		r->next_line = 0;
		r->next_page = 1;
		r->just_set = 1;
	}
}

/* PRESENT / ABSENT AFTER: a new page (ctl < 0) or a control break */
static void present_after(cob_report *r, cob_rwline *l, int ctl)
{
	for (; l; l = l->next_line) {
		for (cob_rwfld *f = l->fields; f; f = f->next) {
			if (!(f->flags & COB_RWF_PRESENT))
				continue;
			int hit = ctl < 0 ? (f->flags & COB_RWF_PAGE) != 0 : f->ctl == ctl;
			if (!(f->flags & COB_RWF_NEGATE)) {
				if (!f->now && hit)
					f->now = 1;
			} else if (f->now && hit) {
				f->now = 0;
			}
		}
		if (l->first_line)
			present_after(r, l->first_line, ctl);
	}
	(void)r;
}

/* ---------------------------------------------------------------- sums */

static void zero_counter(cob_rwsum *s)
{
	cob_move(&cob_fig_zero, s->counter);
}

/* a counter is about to be reset: the counters that SUM it take its value */
static void roll_forward(cob_report *r, int k)
{
	const cob_rwsum *s = &r->sums[k];
	for (int i = 0; i < s->nroll; i++)
		r->sumadd(s->roll[i]);
}

static void reset_counters(cob_report *r, unsigned kind, cob_rwline *l)
{
	l = with_fields(l);
	for (int k = 0; k < r->nsums; k++) {
		cob_rwsum *s = &r->sums[k];
		/* once per operand of the counter, as the reference does */
		for (int op = 0; op < s->nops; op++) {
			if (kind & COB_RWF_CF_FINAL) {
				if (s->final)
					zero_counter(s);
			} else if (s->ctl >= 0) {
				cob_rwctl *c = &r->controls[s->ctl];
				for (int i = 0; i < c->nrefs; i++) {
					cob_rwline *rl = c->refs[i];
					if (rl->flags & (COB_RWF_CH | COB_RWF_CH_FINAL))
						continue;
					if (l != NULL && l != with_fields(rl))
						continue;
					if (rl->flags & kind) {
						roll_forward(r, k);
						zero_counter(s);
					}
				}
			}
		}
	}
}

static void add_detail_sums(cob_report *r, cob_rwline *l)
{
	for (int k = 0; k < r->nsums; k++) {
		cob_rwsum *s = &r->sums[k];
		if (s->subtotal || s->nops <= 0)
			continue;
		if (s->nupon > 0) {
			/* SUM ... UPON: only a GENERATE of one of those DETAIL groups */
			int hit = 0;
			for (int i = 0; i < s->nupon; i++)
				if (s->upon[i] == l)
					hit = 1;
			if (!hit)
				continue;
		}
		r->sumadd(k);
	}
}

/* ---------------------------------------------------------------- pages */

static void page_end(cob_report *r)
{
	if (r->in_pf)
		return;
	r->in_pf = 1;
	print_kind(r, r->first, COB_RWF_PF);
	blank_rec(r);
	if (r->cur < r->lines) {
		put_rec(r, r->lines - r->cur);
		r->cur = r->lines;
		r->incr = 0;
	} else {
		r->cur = 1;
	}
	show_counters(r);
	r->fdflag = 1;
	r->in_pf = 0;
}

static void page_start(cob_report *r)
{
	if (r->in_ph)
		return;
	blank_rec(r);
	if (!r->first_gen && r->lines > 0 && r->heading > 0 &&
	    r->cur <= r->lines && r->cur > r->heading) {
		/* the rest of the page is blank */
		while (r->cur <= r->lines) {
			put_rec(r, 1);
			r->cur++;
		}
		if (r->cur > r->lines)
			r->cur = 1;
		show_counters(r);
	}
	r->in_ph = 1;
	if (!r->first_gen)
		r->page++;
	r->fdflag = 0;
	while (r->cur < r->heading) {
		put_rec(r, 1);
		r->cur++;
		show_counters(r);
	}
	print_kind(r, r->first, COB_RWF_PH);
	blank_rec(r);
	while (r->cur < r->first_detail) {
		put_rec(r, 1);
		r->cur++;
		show_counters(r);
	}
	each_line(r->first, reset_gi);
	r->in_ph = 0;
	present_after(r, r->first, -1);
}

/* ---------------------------------------------------------------- one line */

/* the text of an item, without trailing spaces, aligned as COLUMN
 * LEFT / RIGHT / CENTER ask, into the record */
static void place_field(cob_report *r, cob_rwfld *rf)
{
	const cob_field *f = rf->f;
	size_t n = f->size;
	while (n && (f->data[n - 1] == ' ' || f->data[n - 1] == 0))
		n--;
	const unsigned char *t = f->data;
	/* the text ends at a NUL, as a C string would */
	for (size_t i = 0; i < n; i++)
		if (t[i] == 0) {
			n = i;
			break;
		}
	size_t dest = (size_t)(rf->column - 1);
	if (rf->flags & COB_RWF_RIGHT) {
		if (n < f->size)
			dest += f->size - n;
	} else if (rf->flags & COB_RWF_CENTER) {
		while (n > 0 && t[0] == ' ') {
			t++;
			n--;
		}
		size_t odd = (n & 1) ? 0 : 1;
		if (n < f->size)
			dest += (f->size - n - odd) / 2;
	} else if (rf->flags & COB_RWF_LEFT) {
		while (n > 0 && t[0] == ' ') {
			t++;
			n--;
		}
	}
	if (dest + n > (size_t)r->recsz)
		n = dest < (size_t)r->recsz ? (size_t)r->recsz - dest : 0;
	memcpy(r->rec + dest, t, n);
}

/* the last item that belongs to the group starting at g */
static cob_rwfld *last_of_group(cob_rwfld *g)
{
	cob_rwfld *it = g;

	while (it->next != NULL && it->next->level > g->level)
		it = it->next;
	return it;
}

static void print_line(cob_report *r, cob_rwline *l)
{
	int plus_ok = 0;
	blank_rec(r);
	if (r->cur > r->last_detail && !r->in_rf && !r->in_pf) {
		page_end(r);
		page_start(r);
	}
	if (!r->just_set && r->next_plus) {
		put_rec(r, r->next_value);
		r->cur += r->next_value;
		r->next_plus = 0;
		plus_ok = 1;
	} else if (!r->just_set && r->next_line) {
		r->next_line = 0;
		if (r->cur > r->next_value) {
			page_end(r);
			page_start(r);
		}
		while (r->cur < r->next_value) {
			put_rec(r, 1);
			r->cur++;
		}
		plus_ok = 1;
	} else if (!r->just_set && r->next_page) {
		r->next_page = 0;
		page_end(r);
		page_start(r);
	} else if (!(l->flags & COB_RWF_LINE_PLUS) && (l->flags & COB_RWF_LINE)) {
		if (r->cur > l->line) {
			page_end(r);
			if (r->in_rf) {
				r->page++;
				r->cur = 1;
			} else {
				page_start(r);
			}
			r->fdflag = 0;
		}
		while (r->cur < l->line) {
			put_rec(r, 1);
			r->cur++;
		}
	} else {
		plus_ok = 1;
	}
	if (plus_ok && (l->flags & COB_RWF_LINE_PLUS) && l->line > 1) {
		if (r->cur != r->first_detail || r->first_detail == 0) {
			put_rec(r, l->line - 1);
			r->cur += l->line - 1;
		}
	}
	if (r->cur > r->last_detail && !r->in_rf && !r->in_ph && !r->in_pf) {
		page_end(r);
		page_start(r);
	}
	show_counters(r);
	if (l->fields == NULL || l->sup) {
		note_next_group(r, l);
		return;
	}
	for (cob_rwfld *rf = l->fields; rf; rf = rf->next) {
		if (rf->flags & COB_RWF_GROUP) {
			if (rf->sup) {
				/* a suppressed group: none of its items print */
				rf->sup = 0;
				rf = last_of_group(rf);
			}
			continue;
		}
		if ((rf->flags & COB_RWF_PRESENT) && !rf->now)
			continue;
		if (rf->sup || rf->gi)
			continue;
		if (rf->src) {
			r->src(rf->src);
			place_field(r, rf);
		} else if (rf->lit) {
			cob_field lf = { (size_t)rf->litlen, (unsigned char *)rf->lit, &cob_attr_alnum };
			cob_move(&lf, rf->f);
			size_t n = (size_t)rf->litlen;
			size_t dest = (size_t)(rf->column - 1);
			if (dest + n > (size_t)r->recsz)
				n = dest < (size_t)r->recsz ? (size_t)r->recsz - dest : 0;
			memcpy(r->rec + dest, rf->lit, n);
		} else {
			place_field(r, rf);
		}
		if (rf->flags & COB_RWF_GI)
			rf->gi = 1;
	}
	for (cob_rwfld *rf = l->fields; rf; rf = rf->next)
		rf->now = (rf->flags & COB_RWF_NEGATE) ? 1 : 0;
	put_rec(r, 1);
	r->cur++;
	show_counters(r);
	note_next_group(r, l);
}

/* a control heading or footing group: its own line first when the group's
 * items hang below it, then the ordinary line walk */
static void print_group(cob_report *r, cob_rwline *l, unsigned kind)
{
	if (l == NULL)
		return;
	if (l->fields != NULL || l->first_line == NULL) {
		print_kind(r, l, kind);
		return;
	}
	if (!(l->flags & kind)) {
		print_kind(r, l->first_line, kind);
		return;
	}
	print_line(r, l);
	print_kind(r, l->first_line, COB_RWF_LINE);
}

/* the first line of `kind` in the chain from l, with its own lines and the
 * lines of that kind that follow it */
static int print_kind(cob_report *r, cob_rwline *l, unsigned kind)
{
	for (; l; l = l->next_line) {
		if (l->flags & kind) {
			print_line(r, l);
			if (l->first_line)
				print_kind(r, l->first_line, COB_RWF_LINE);
			for (cob_rwline *s = l->next_line; s; s = s->next_line) {
				/* a control footing chain stops at a more major control */
				if (kind == COB_RWF_CF && (s->flags & COB_RWF_CF)) {
					int a = control_order(r, l), b = control_order(r, s);
					if (a > 0 && b > 0 && b > a)
						return 1;
				}
				print_kind(r, s, kind);
				break;
			}
			return 1;
		}
		if (l->first_line && print_kind(r, l->first_line, kind))
			return 1;
	}
	return 0;
}

/* ---------------------------------------------------------------- declaratives */

static void run_use(cob_report *r, cob_rwline *l, int id)
{
	cob_report *saved = suppress_rep;
	cob_rwline *saved_line = r->use_line;
	suppress_rep = r;
	r->use_line = l;
	r->decl(id);
	r->use_line = saved_line;
	suppress_rep = saved;
	/* the statement continues as if re-entered after the procedure */
	if (!r->terminating)
		r->foot_np = 0;
	r->moves(r->terminating);
}

/* the USE procedure for a control line, if it has one */
static void use_for(cob_report *r, cob_rwline *l)
{
	if (l->decl) {
		run_use(r, l, l->decl);
		return;
	}
	cob_rwline *pl = with_fields(l);
	if (pl != l && pl->decl)
		run_use(r, pl, pl->decl);
}

/* SUPPRESS PRINTING in a USE BEFORE REPORTING procedure */
void cob_rw_suppress_printing(void)
{
	cob_report *r = suppress_rep;
	if (r == NULL || r->use_line == NULL)
		return;
	cob_rwline *l = r->use_line;
	l->sup = 1;
	for (int i = 0; i < r->ncontrols; i++) {
		cob_rwctl *c = &r->controls[i];
		for (int k = 0; k < c->nrefs; k++) {
			if (c->refs[k] == l || with_fields(c->refs[k]) == l) {
				c->sup = 1;
				return;
			}
		}
	}
}

/* ---------------------------------------------------------------- controls */

static cob_field ctl_copy(cob_report *r, int i, unsigned char *buf)
{
	cob_field *f = r->ctlf(i);
	cob_field c = { f->size, buf, f->attr };
	return c;
}

static void ctl_store(cob_report *r, int i, unsigned char *buf)
{
	cob_field *f = r->ctlf(i);
	memcpy(buf, f->data, f->size);
}

static void ctl_load(cob_report *r, int i, const unsigned char *buf)
{
	cob_field *f = r->ctlf(i);
	memcpy(f->data, buf, f->size);
}

/* ---------------------------------------------------------------- statements */

static int limits_ok(cob_report *r, cob_rwline *l)
{
	for (; l; l = l->next_line) {
		if (l->line > 0 && r->lines > 0 && l->line > r->lines)
			return 0;
		if (l->ngl > 0 && r->lines > 0 && l->ngl > r->lines)
			return 0;
		for (cob_rwfld *f = l->fields; f; f = f->next) {
			if (f->line && f->line > r->lines)
				return 0;
			if (f->ngl && f->ngl > r->lines)
				return 0;
		}
		if (l->first_line && !limits_ok(r, l->first_line))
			return 0;
	}
	return 1;
}

void cob_rw_initiate(cob_report *r, const char *loc)
{
	if (r->initiated) {
		/* EC-REPORT-ACTIVE: the INITIATE is not executed */
		cob_set_exception("EC-REPORT-ACTIVE");
		cob_warning("%s: INITIATE for report %s that is already initiated", loc, r->name);
		return;
	}
	if (r->lines > 9999)
		r->lines = 9999;
	if (r->cols > 999 || r->cols < 1)
		r->cols = 999;
	if ((r->first_detail > 0 && !(r->first_detail >= r->heading)) ||
	    (r->last_detail > 0 && !(r->last_detail >= r->first_detail)) ||
	    (r->footing > 0 && !(r->footing >= r->heading)) ||
	    (r->footing > 0 && !(r->footing >= r->last_detail)) ||
	    (r->lines > 0 && !(r->lines >= r->heading)) ||
	    (r->lines > 0 && !(r->lines >= r->footing))) {
		cob_set_exception("EC-REPORT-PAGE-LIMIT");
		cob_warning("%s: INITIATE %s: PAGE LIMIT problem", loc, r->name);
		return;
	}
	if (!r->rec)
		r->rec = cob_malloc((size_t)r->recsz + 1);
	r->page = 1;
	r->cur = 0;
	r->incr = 1;
	show_counters(r);
	if (!limits_ok(r, r->first)) {
		cob_set_exception("EC-REPORT-PAGE-LIMIT");
		cob_warning("%s: INITIATE %s: a LINE exceeds the PAGE LIMIT", loc, r->name);
		return;
	}
	r->initiated = 1;
	r->fdflag = 1;
	r->first_gen = 1;
	r->next_value = 0;
	r->next_line = 0;
	r->next_plus = 0;
	r->next_page = 0;
	for (int i = 0; i < r->ncontrols; i++) {
		cob_rwctl *c = &r->controls[i];
		cob_field *f = r->ctlf(i);
		free(c->val);
		free(c->save);
		c->val = cob_malloc(f->size + 1);
		c->save = cob_malloc(f->size + 1);
		memcpy(c->val, f->data, f->size);
		memcpy(c->save, f->data, f->size);
	}
	for (int k = 0; k < r->nsums; k++)
		zero_counter(&r->sums[k]);
}

/* A detail group that starts on its 01 line and continues on LINE entries
 * below it arrives at GENERATE pointing at the 01, whose item list is empty.
 * The run then starts at that first LINE entry and covers its whole chain. */
static cob_rwline *detail_run_start(cob_rwline *l, int *chained)
{
	cob_rwline *below = l->first_line;

	*chained = l->fields == NULL && below != NULL && below->next_line != NULL;
	return *chained ? below : l;
}

/* How many print lines one GENERATE of a detail group emits, and the extra
 * line steps its LINE PLUS clauses add. A group that is not chained is a
 * single line and takes no steps. */
static int detail_run_size(cob_rwline *run, int chained, int *steps)
{
	int lines;

	*steps = 0;
	if (!chained)
		return 1;
	lines = 0;
	for (cob_rwline *pl = run; pl != NULL; pl = pl->next_line) {
		if (pl->flags & NOT_DETAIL)
			break;
		lines++;
		if ((pl->flags & COB_RWF_LINE_PLUS) && pl->line > 1)
			*steps += pl->line;
	}
	return lines;
}

static void print_detail_run(cob_report *r, cob_rwline *run, int lines)
{
	cob_rwline *pl = run;

	while (lines-- > 0) {
		cob_rwline *body;

		if (pl == NULL || (pl->flags & NOT_DETAIL))
			break;
		body = with_fields(pl);
		if (!body->sup) {
			r->just_set = 0;
			print_line(r, body);
		}
		body->sup = 0;
		pl = pl->next_line;
	}
}

/* GENERATE of a detail group: sum it, then print it. A group whose print was
 * SUPPRESSed consumes that and prints nothing; a GENERATE that names only the
 * report (l == NULL) just sums. A chained group takes a fresh page first when
 * its run would not fit above LAST DETAIL. */
static void generate_detail(cob_report *r, cob_rwline *l)
{
	int chained = 0;
	int steps = 0;
	int lines;

	add_detail_sums(r, l);
	if (l == NULL)
		return;
	if (l->sup) {
		l->sup = 0;
		return;
	}
	l = detail_run_start(l, &chained);
	lines = detail_run_size(l, chained, &steps);
	if (lines > 1 && r->cur + steps > r->last_detail) {
		page_end(r);
		r->cur = 1;
		page_start(r);
		r->fdflag = 0;
		show_counters(r);
	}
	print_detail_run(r, l, lines);
}

void cob_rw_generate(cob_report *r, cob_rwline *l, const char *loc)
{
	if (!r->initiated)
		cob_fatal("%s: GENERATE for report %s that is not initiated", loc, r->name);
	r->terminating = 0;
	r->moves(0);
	r->foot_np = 0;
	if (r->incr) {
		r->incr = 0;
		r->cur++;
		show_counters(r);
	}
	if (r->first_gen) {
		print_kind(r, r->first, COB_RWF_RH);
		page_start(r);
		/* CONTROL HEADING FINAL (which cobc 3.1.2 never prints): the most
		 * major heading, before those of the CONTROL data items */
		cob_rwline *chf = find_kind(r->first, COB_RWF_CH_FINAL);
		if (chf) {
			if (chf->decl)
				run_use(r, chf, chf->decl);
			if (!chf->sup)
				print_kind(r, r->first, COB_RWF_CH_FINAL);
			chf->sup = 0;
		}
		for (int i = 0; i < r->ncontrols; i++) {
			cob_rwctl *c = &r->controls[i];
			for (int k = 0; k < c->nrefs; k++) {
				cob_rwline *rl = c->refs[k];
				if (rl->flags & COB_RWF_CH) {
					use_for(r, rl);
					print_group(r, rl, COB_RWF_CH);
				}
			}
			ctl_store(r, i, c->val);
			c->changed = 0;
		}
	} else {
		if (r->cur > r->last_detail) {
			page_end(r);
			r->cur = 1;
			page_start(r);
			r->fdflag = 0;
		} else if (r->cur <= 1 || r->fdflag) {
			if (r->fdflag)
				r->cur = 1;
			page_start(r);
			r->fdflag = 0;
		}
		int top = 0;
		for (int i = 0; i < r->ncontrols; i++) {
			cob_rwctl *c = &r->controls[i];
			unsigned char *v = c->val;
			cob_field old = ctl_copy(r, i, v);
			c->changed = cob_cmp(r->ctlf(i), &old) != 0;
			if (c->changed) {
				ctl_store(r, i, c->save);     /* the new value, for later */
				ctl_load(r, i, c->val);       /* the old one, for the footing */
				if (c->seq > top)
					top = c->seq;
			}
		}
		if (top > 0) {
			for (int i = 0; i < r->ncontrols; i++) {
				cob_rwctl *c = &r->controls[i];
				if (c->seq < top && !c->changed) {
					c->changed = 1;
					ctl_store(r, i, c->save);
					ctl_load(r, i, c->val);
				}
			}
		}
		for (int i = 0; i < r->ncontrols; i++)
			if (r->controls[i].changed)
				present_after(r, r->first, i);
		for (int i = 0; i < r->ncontrols; i++) {
			cob_rwctl *c = &r->controls[i];
			if (!c->changed)
				continue;
			for (int k = 0; k < c->nrefs; k++) {
				cob_rwline *rl = c->refs[k];
				if (!(rl->flags & COB_RWF_CF))
					continue;
				use_for(r, rl);
				if (!c->sup && !rl->sup)
					print_group(r, rl, COB_RWF_CF);
				c->sup = 0;
				rl->sup = 0;
				reset_counters(r, COB_RWF_CF, with_fields(rl));
				each_line(r->first, reset_gi);
				r->just_set = 0;
				if (r->next_page) {
					r->foot_np = 1;
					r->next_page = 0;
				}
			}
			ctl_load(r, i, c->save);          /* the new value back */
		}
		if (r->foot_np) {
			r->next_page = 0;
			r->foot_np = 0;
			page_end(r);
			page_start(r);
		}
		for (int i = 0; i < r->ncontrols; i++) {
			cob_rwctl *c = &r->controls[i];
			if (c->changed) {
				for (int k = 0; k < c->nrefs; k++) {
					cob_rwline *rl = c->refs[k];
					if (!(rl->flags & COB_RWF_CH))
						continue;
					use_for(r, rl);
					if (!rl->sup)
						print_group(r, rl, COB_RWF_CH);
					rl->sup = 0;
				}
				ctl_store(r, i, c->val);
			}
			c->changed = 0;
		}
	}
	generate_detail(r, l);
	reset_counters(r, COB_RWF_DE, NULL);
	each_line(r->first, reset_sup);
	r->first_gen = 0;
	r->just_set = 0;
	r->cur--;
	r->incr = 1;
	show_counters(r);
}

void cob_rw_terminate(cob_report *r, const char *loc)
{
	if (!r->initiated)
		cob_fatal("%s: TERMINATE for report %s that is not initiated", loc, r->name);
	r->terminating = 1;
	r->moves(1);
	if (r->first_gen) {
		/* no GENERATE: nothing is printed, and the report stays initiated */
		r->terminating = 0;
		return;
	}
	/* the footings see the CONTROL values of the last GENERATE, as the
	 * standard requires (cobc 3.1.2 uses whatever the fields hold now, which
	 * defeats the usual MOVE HIGH-VALUES at end of file) */
	for (int i = 0; i < r->ncontrols; i++) {
		ctl_store(r, i, r->controls[i].save);
		ctl_load(r, i, r->controls[i].val);
	}
	for (int i = 0; i < r->ncontrols; i++) {
		cob_rwctl *c = &r->controls[i];
		for (int k = 0; k < c->nrefs; k++) {
			cob_rwline *rl = c->refs[k];
			if (!(rl->flags & COB_RWF_CF))
				continue;
			use_for(r, rl);
			if (!c->sup)
				print_group(r, rl, COB_RWF_CF);
			c->sup = 0;
			reset_counters(r, COB_RWF_CF, with_fields(rl));
		}
	}
	cob_rwline *pl = find_kind(r->first, COB_RWF_CF_FINAL);
	if (pl) {
		if (pl->decl)
			run_use(r, pl, pl->decl);
		print_kind(r, r->first, COB_RWF_CF_FINAL);
	}
	reset_counters(r, COB_RWF_CF_FINAL, NULL);
	page_end(r);
	pl = find_kind(r->first, COB_RWF_RF);
	if (pl) {
		if (pl->decl)
			run_use(r, pl, pl->decl);
		r->in_rf = 1;
		print_kind(r, r->first, COB_RWF_RF);
		r->in_rf = 0;
	}
	for (int i = 0; i < r->ncontrols; i++) {
		ctl_load(r, i, r->controls[i].save);  /* the program's own values back */
		free(r->controls[i].val);
		free(r->controls[i].save);
		r->controls[i].val = r->controls[i].save = NULL;
	}
	r->initiated = 0;
	r->terminating = 0;
}
