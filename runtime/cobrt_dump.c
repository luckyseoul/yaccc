/* SPDX-License-Identifier: MIT */
/* cobrt_dump.c - the data of the run unit after a runtime error (-fdump)
 *
 * A program compiled with -fdump describes its data in a table (codegen's
 * DumpGen), and registers it when it starts. After a runtime error, a crash,
 * or SIGQUIT (Ctrl-\ on a program that seems stuck), the data of every active
 * program that has a table is written out, the innermost program first:
 * each item of the sections it asked for, with its PICTURE and USAGE, and
 * its value -- a number as DISPLAY shows it, text in quotes, anything else
 * in hexadecimal, and a number whose bytes aren't one said to be so.
 *
 * A table's occurrences are written one by one, those the same as the one
 * before as a single line, and at most SHOW_OCCURS of them.
 *
 * COB_DUMP_FILE names a file to append the dump to instead of standard
 * error; COB_DUMP_FILE=NONE leaves it out.
 */
#include "cobrt.h"
#include <strings.h>
#include <time.h>
#include <unistd.h>
#include <sys/mman.h>

#define SHOW_BYTES 64           /* of a long value, the bytes written */
#define SHOW_OCCURS 100         /* of a table, the occurrences written */
#define NAME_COL 38             /* where the PICTURE starts */
#define DESC_COL 18             /* the PICTURE's width before the value */
#define MAX_SUBS 16

typedef struct {
	FILE *o;
	const cob_dump_item *t;
	int n;
} dumper;

static unsigned char *record_base(const cob_dump_item *e)
{
	if (!e->base)
		return NULL;
	if (e->ptr)
		return *(unsigned char *const *)e->base;
	return (unsigned char *)e->base;
}

/* a record's storage is there to read: a LINKAGE item's address may be what
 * crashed the program, and the dump must not crash on it again */
static int mapped(const void *p, size_t n)
{
	long pg = sysconf(_SC_PAGESIZE);
	if (pg <= 0)
		return 1;
	uintptr_t end = (uintptr_t)p + (n ? n : 1);
	unsigned char v;
	for (uintptr_t q = (uintptr_t)p & ~(uintptr_t)(pg - 1); q < end; q += (uintptr_t)pg)
		if (mincore((void *)q, (size_t)pg, &v) != 0)
			return 0;
	return 1;
}

static void put_bytes(FILE *o, const unsigned char *p, size_t n)
{
	size_t m = n < SHOW_BYTES ? n : SHOW_BYTES;
	int text = 1, some = 0;
	for (size_t i = 0; i < m; i++) {
		if (p[i] < 0x20 || p[i] == 0x7f)
			text = 0;
		else
			some = 1;
	}
	if (text) {
		fputc('"', o);
		fwrite(p, 1, m, o);
		fputc('"', o);
	} else {
		fputs("x\"", o);
		for (size_t i = 0; i < m; i++)
			fprintf(o, "%02X", p[i]);
		fputc('"', o);
		if (some) {
			/* the characters too, a dot for each that isn't one */
			fputs(" \"", o);
			for (size_t i = 0; i < m; i++)
				fputc(p[i] < 0x20 || p[i] == 0x7f ? '.' : p[i], o);
			fputc('"', o);
		}
	}
	if (m < n)
		fprintf(o, "... (%zu bytes)", n);
}

/* a number as DISPLAY shows it with the decimal point: every digit of the
 * PICTURE, the point where it is, a sign if the item has one */
static void put_number(FILE *o, const cob_field *f)
{
	const cob_attr *a = f->attr;
	if ((a->type == COB_NUM_DISPLAY || a->type == COB_NUM_PACKED) && !cob_is_numeric(f)) {
		put_bytes(o, f->data, f->size);
		fputs(" (not numeric)", o);
		return;
	}
	cob_dec d = cob_d_get(f);
	int scale = a->type == COB_INDEX ? 0 : a->scale;
	int pt = scale > 0 ? scale : 0;
	int int_digits = a->digits - pt + (scale < 0 ? -scale : 0);
	if (int_digits < 1)
		int_digits = 1;
	cob_s128 v = d.v;
	int ds = d.scale;
	while (ds < pt) {
		v *= 10;
		ds++;
	}
	while (ds > pt) {
		v /= 10;
		ds--;
	}
	cob_u128 u = v < 0 ? (cob_u128)(-(v + 1)) + 1 : (cob_u128)v;
	char dig[64];
	int nd = 0;
	do {
		dig[nd++] = (char)('0' + (int)(u % 10));
		u /= 10;
	} while (u && nd < 60);
	while (nd < int_digits + pt && nd < 60)
		dig[nd++] = '0';
	if ((a->flags & COB_F_SIGNED) || a->type == COB_INDEX || v < 0)
		fputc(v < 0 ? '-' : '+', o);
	for (int i = nd - 1; i >= 0; i--) {
		if (i == pt - 1)
			fputc((a->flags & COB_F_DEC_COMMA) ? ',' : '.', o);
		fputc(dig[i], o);
	}
}

static void put_value(FILE *o, const cob_field *f)
{
	switch (f->attr->type) {
	case COB_NUM_DISPLAY:
	case COB_NUM_PACKED:
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_INDEX:
		put_number(o, f);
		return;
	case COB_NUM_FLOAT: {
		float x;
		memcpy(&x, f->data, sizeof x);
		fprintf(o, "%.8G", (double)x);
		return;
	}
	case COB_NUM_DOUBLE: {
		double x;
		memcpy(&x, f->data, sizeof x);
		fprintf(o, "%.16G", x);
		return;
	}
	case COB_NUM_DEC_FLOAT: {
		char t[160];
		int k = cob_dec_float_str(f, t, sizeof t);
		fwrite(t, 1, (size_t)(k > 0 ? k : 0), o);
		return;
	}
	case COB_POINTER: {
		void *x;
		memcpy(&x, f->data, sizeof x);
		if (x)
			fprintf(o, "%p", x);
		else
			fputs("NULL", o);
		return;
	}
	default:
		put_bytes(o, f->data, f->size);
		return;
	}
}

static int put_subs(FILE *o, const int *subs, int nsub)
{
	int c = 0;
	if (nsub > 0) {
		c += fprintf(o, " (");
		for (int k = 0; k < nsub; k++)
			c += fprintf(o, k ? ", %d" : "%d", subs[k]);
		c += fprintf(o, ")");
	}
	return c;
}

static void pad(FILE *o, int at, int col)
{
	if (at < col)
		fprintf(o, "%*s", col - at, "");
	else
		fputc(' ', o);
}

/* an item's line: level, name, subscripts, PICTURE ..., then its value or,
 * for a group, nothing; a table's PICTURE is given for its first occurrence */
static void put_head(FILE *o, const cob_dump_item *e, const int *subs, int nsub, int more, int desc)
{
	int c = fprintf(o, "%*s%02d %s", 2 + 3 * e->depth, "", e->level, e->name ? e->name : "FILLER");
	c += put_subs(o, subs, nsub);
	const char *d = desc && e->desc && *e->desc ? e->desc : NULL;
	if (!d && !more)
		return;
	pad(o, c, NAME_COL);
	int w = d ? fprintf(o, "%s", d) : 0;
	if (more)
		pad(o, w, DESC_COL);
}

static void dump_items(dumper *dp, int from, int to, unsigned char *rec, size_t add, int *subs, int nsub);

static void dump_entry(dumper *dp, int i, unsigned char *rec, size_t add, int *subs, int nsub, int desc)
{
	const cob_dump_item *e = &dp->t[i];
	put_head(dp->o, e, subs, nsub, e->attr != NULL, desc);
	if (e->attr) {
		cob_field f = { e->size, rec + e->offset + add, e->attr };
		put_value(dp->o, &f);
	}
	fputc('\n', dp->o);
	if (e->span > 1)
		dump_items(dp, i + 1, i + (int)e->span, rec, add, subs, nsub);
}

/* how many times a table with OCCURS DEPENDING ON occurs now */
static unsigned int odo_count(dumper *dp, const cob_dump_item *e)
{
	int j = e->odo;
	if (j < 0 || j >= dp->n || !dp->t[j].attr)
		return e->occurs;
	int r = j;
	while (r > 0 && !(dp->t[r].kind == COB_DUMP_ITEM && dp->t[r].depth == 0))
		r--;
	unsigned char *base = record_base(&dp->t[r]);
	if (!base)
		return e->occurs;
	cob_field f = { dp->t[j].size, base + dp->t[j].offset, dp->t[j].attr };
	if (!cob_is_numeric(&f))
		return e->occurs;
	cob_s64 v = cob_get_int(&f);
	if (v < 0)
		v = 0;
	if (v > (cob_s64)e->occurs)
		v = e->occurs;
	return (unsigned int)v;
}

static void dump_table(dumper *dp, int i, unsigned char *rec, size_t add, int *subs, int nsub)
{
	const cob_dump_item *e = &dp->t[i];
	FILE *o = dp->o;
	unsigned int cnt = e->odo >= 0 ? odo_count(dp, e) : e->occurs;
	if (cnt == 0 || nsub >= MAX_SUBS) {
		put_head(o, e, subs, nsub, 1, 1);
		fputs(cnt == 0 ? "(none now)\n" : "\n", o);
		return;
	}
	const unsigned char *at = rec + e->offset + add;
	for (unsigned int k = 1; k <= cnt; k++) {
		if (k > 1 && memcmp(at + (k - 1) * e->size, at + (k - 2) * e->size, e->size) == 0) {
			unsigned int m = k;
			while (m < cnt && memcmp(at + m * e->size, at + (k - 2) * e->size, e->size) == 0)
				m++;
			fprintf(o, "%*s%02d %s", 2 + 3 * e->depth, "", e->level, e->name ? e->name : "FILLER");
			fputs(" (", o);
			for (int s = 0; s < nsub; s++)
				fprintf(o, "%d, ", subs[s]);
			if (m > k)
				fprintf(o, "%u to %u): the same as (%u)\n", k, m, k - 1);
			else
				fprintf(o, "%u): the same as (%u)\n", k, k - 1);
			k = m;
			continue;
		}
		if (k > SHOW_OCCURS) {
			fprintf(o, "%*s... and %u more of %s\n", 2 + 3 * e->depth, "", cnt - k + 1,
			        e->name ? e->name : "FILLER");
			break;
		}
		subs[nsub] = (int)k;
		dump_entry(dp, i, rec, add + (k - 1) * e->size, subs, nsub + 1, k == 1);
	}
}

static void dump_items(dumper *dp, int from, int to, unsigned char *rec, size_t add, int *subs, int nsub)
{
	FILE *o = dp->o;
	for (int i = from; i < to && i < dp->n; ) {
		const cob_dump_item *e = &dp->t[i];
		int step = e->kind == COB_DUMP_ITEM && e->span > 0 ? (int)e->span : 1;
		switch (e->kind) {
		case COB_DUMP_SECTION:
			fprintf(o, "  %s\n", e->name);
			break;
		case COB_DUMP_NOTE:
			fprintf(o, "  (%s)\n", e->name);
			break;
		case COB_DUMP_FILE: {
			const cob_file *f = (const cob_file *)e->base;
			static const char *const modes[] = { "closed", "open INPUT", "open OUTPUT", "open I-O",
			                                     "open EXTEND" };
			fprintf(o, "  %s %s", e->name, f->select_name ? f->select_name : "?");
			if (f->path[0])
				fprintf(o, " ('%s')", f->path);
			fprintf(o, ", %s", f->open_mode >= 0 && f->open_mode <= 4 ? modes[f->open_mode] : "open");
			if (f->stat[0] >= '0' && f->stat[0] <= '9')
				fprintf(o, ", status %c%c", f->stat[0], f->stat[1]);
			fputc('\n', o);
			break;
		}
		case COB_DUMP_INDEX: {
			int c = fprintf(o, "  INDEX %s", e->name);
			pad(o, c, NAME_COL);
			fprintf(o, "%-*s%d\n", DESC_COL, e->desc ? e->desc : "", *(const int *)e->base);
			break;
		}
		default: {
			unsigned char *r = rec;
			size_t a = add;
			if (e->depth == 0) {
				r = record_base(e);
				a = 0;
				if (!r) {
					put_head(o, e, subs, nsub, 1, 1);
					fputs("(no storage: not passed, or not allocated)\n", o);
					break;
				}
				if (e->ptr && !mapped(r, e->occurs ? e->size * e->occurs : e->size)) {
					put_head(o, e, subs, nsub, 1, 1);
					fprintf(o, "(its address, %p, is not memory the program has)\n", (void *)r);
					break;
				}
			}
			if (e->occurs)
				dump_table(dp, i, r, a, subs, nsub);
			else
				dump_entry(dp, i, r, a, subs, nsub, 1);
			break;
		}
		}
		i += step;
	}
}

void cob_dump(void)
{
	const char *dest = getenv("COB_DUMP_FILE");
	if (dest && !strcasecmp(dest, "NONE"))
		return;
	int depth = cob_frame_depth();
	FILE *o = NULL;
	int to_file = 0;
	for (int d = depth - 1; d >= 0; d--) {
		const char *name, *src;
		const cob_dump_item *t;
		int n;
		if (!cob_frame_dump(d, &name, &t, &n, &src) || !t || n <= 0)
			continue;
		if (!o) {
			fflush(stdout);
			o = stderr;
			if (dest && *dest) {
				FILE *f = fopen(dest, "a");
				if (f) {
					o = f;
					to_file = 1;
					fprintf(stderr, "cobrt: the data is in %s\n", dest);
				} else {
					fprintf(stderr, "cobrt: cannot write the dump to %s: %s\n", dest, strerror(errno));
				}
			}
			if (to_file) {
				char when[64];
				time_t now = time(NULL);
				struct tm tmv;
				strftime(when, sizeof when, "%Y-%m-%d %H:%M:%S", localtime_r(&now, &tmv));
				fprintf(o, "cobrt: dump of %s\n", when);
			}
		}
		fprintf(o, "cobrt: data of %s (%s)\n", name ? name : "?", src ? src : "?");
		dumper dp = { o, t, n };
		int subs[MAX_SUBS + 1];
		dump_items(&dp, 0, n, NULL, 0, subs, 0);
	}
	if (to_file)
		fclose(o);
	else if (o)
		fflush(o);
}
