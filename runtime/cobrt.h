/* SPDX-License-Identifier: MIT */
/* cobrt.h - runtime library for the YACCC COBOL compiler */
#ifndef COBRT_H
#define COBRT_H

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>

typedef __int128 cob_s128;
typedef unsigned __int128 cob_u128;
typedef long long cob_s64;
typedef unsigned long long cob_u64;

enum cob_type {
	COB_GROUP = 1, COB_ALNUM, COB_ALPHA, COB_ALNUM_EDITED, COB_NUM_DISPLAY,
	COB_NUM_PACKED, COB_NUM_BINARY, COB_NUM_COMP5, COB_NUM_FLOAT, COB_NUM_DOUBLE,
	COB_NUM_EDITED, COB_INDEX, COB_ALL, COB_POINTER, COB_NUM_DEC_FLOAT
};

#define COB_F_SIGNED       0x01
#define COB_F_SIGN_SEP     0x02
#define COB_F_SIGN_LEAD    0x04
#define COB_F_JUSTIFIED    0x08
#define COB_F_BLANK_ZERO   0x10
#define COB_F_DEC_COMMA    0x20
#define COB_F_BINARY_TRUNC 0x40
#define COB_F_ZERO         0x80   /* COB_ALL: figurative ZERO */
#define COB_F_UNSIGNED_PACKED 0x100 /* COMP-6: packed with no sign nibble */
#define COB_F_NATIVE_BIN   0x200  /* BINARY in the machine's byte order */

typedef struct {
	unsigned char type;
	unsigned char digits;
	signed char scale;
	unsigned short flags;         /* COB_F_*: more than eight are defined */
	const char *pic;              /* edited picture (expanded) */
	unsigned char currency;
} cob_attr;

typedef struct {
	size_t size;
	unsigned char *data;
	const cob_attr *attr;
} cob_field;

typedef struct {
	cob_s128 v;
	int scale;
} cob_dec;

#define COB_DEC_ERR 0x7fffffff

#define CF(d, s, a) (&(cob_field){ (size_t)(s), (unsigned char *)(d), (a) })

static inline int cob_is_num_type(int t)
{
	return (t >= COB_NUM_DISPLAY && t <= COB_NUM_DOUBLE) || t == COB_INDEX
		|| t == COB_NUM_DEC_FLOAT;
}

/* PERFORM stack */
/* A PERFORM or CALL statement, for the stack a runtime error prints */
typedef struct {
	const char *where;          /* file:line */
	const char *what;           /* "PERFORM A THRU B", "CALL \"SUB\"", ... */
	const char *in;             /* "paragraph P" or "section S" it is in, or NULL */
	int dynamic;                /* a CALL of a data item: the name it held is added */
} cob_site;
/* A PERFORM statement: the paragraph or section whose end returns, where it
 * returns to, and the statement itself. One of these is static in the
 * program for each PERFORM, and a frame of the PERFORM stack is a pointer to
 * it. The frame above the top one is NULL (the first COB_FRAMES_CLEAR are
 * cleared at the program's start, a push past them clears the next, and a
 * return clears its own), so the stack can be walked from its base without
 * the program's frame pointer. */
typedef struct {
	int through;
	void *ret;
	const cob_site *site;
} cob_perform;
extern const cob_site *cob_call_site;   /* the CALL under way, until the callee starts */
void cob_module_frames(const cob_perform **base);

/* -fdump: a program's data, described for the dump after a runtime error.
 * The entries are its sections' items in order, each record followed by the
 * items under it (span counts them, the record included). */
enum { COB_DUMP_ITEM, COB_DUMP_SECTION, COB_DUMP_FILE, COB_DUMP_INDEX, COB_DUMP_NOTE };
typedef struct {
	unsigned char kind;
	unsigned char level;        /* an item: 1-49 or 77 */
	unsigned char depth;        /* an item: 0 for a record, 1 for the items in it, ... */
	unsigned char ptr;          /* a record: base is the address of its storage's pointer */
	unsigned int span;          /* an item: entries in its subtree, itself included */
	const char *name;           /* an item or index: its name (NULL: FILLER); a heading: its text */
	const char *desc;           /* an item: PICTURE, USAGE, OCCURS, REDEFINES */
	const void *base;           /* a record: its storage; an index: its int; a file: its cob_file */
	size_t offset;              /* an item: from the start of its record */
	size_t size;                /* an item: one occurrence */
	unsigned int occurs;        /* an item: the table's size (0: not a table) */
	int odo;                    /* an item: the entry of its DEPENDING ON item, or -1 */
	const cob_attr *attr;       /* an elementary item: how to show it */
} cob_dump_item;
void cob_module_dump(const cob_dump_item *t, int n, const char *src);
void cob_dump(void);
int cob_frame_depth(void);
int cob_frame_dump(int d, const char **name, const cob_dump_item **t, int *n, const char **src);
void cob_stack_trace(void);
#define COB_STACK_SIZE 512
#define COB_FRAMES_CLEAR 32     /* frames NULL from a program's start */

/* ------------------------------------------------------------ globals */
extern cob_field cob_fig_space, cob_fig_zero, cob_fig_high, cob_fig_low,
	cob_fig_quote, cob_fig_null, cob_fig_apos;
extern const cob_attr cob_attr_alnum, cob_attr_group;
extern cob_field cob_return_code, cob_tally, cob_sort_return_reg;
extern const char *cob_when_compiled;
extern const char *cob_source_name;

/* ------------------------------------------------------------ inline fast paths */
/* -fmove-ibm: a move whose receiving bytes begin inside the sending ones is
 * made left to right a byte at a time, as the IBM MVC instruction makes it,
 * so a byte propagates; any other move is memmove's */
static inline void cob_mvc(unsigned char *d, const unsigned char *s, size_t n)
{
	if (d > s && d < s + n) {
		for (size_t i = 0; i < n; i++)
			d[i] = s[i];
	} else
		memmove(d, s, n);
}

static inline cob_s64 cob_bin_get(const unsigned char *p, int size, int sgn)
{
	switch (size) {
	case 1:
		return sgn ? (cob_s64)(signed char)p[0] : (cob_s64)p[0];
	case 2: {
		uint16_t x;
		memcpy(&x, p, 2);
		x = __builtin_bswap16(x);
		return sgn ? (cob_s64)(int16_t)x : (cob_s64)x;
	}
	case 4: {
		uint32_t x;
		memcpy(&x, p, 4);
		x = __builtin_bswap32(x);
		return sgn ? (cob_s64)(int32_t)x : (cob_s64)x;
	}
	default: {
		uint64_t x;
		memcpy(&x, p, 8);
		x = __builtin_bswap64(x);
		return (cob_s64)x;
	}
	}
}

static inline void cob_bin_set(unsigned char *p, int size, cob_s64 v)
{
	switch (size) {
	case 1:
		p[0] = (unsigned char)v;
		break;
	case 2: {
		uint16_t x = __builtin_bswap16((uint16_t)v);
		memcpy(p, &x, 2);
		break;
	}
	case 4: {
		uint32_t x = __builtin_bswap32((uint32_t)v);
		memcpy(p, &x, 4);
		break;
	}
	default: {
		uint64_t x = __builtin_bswap64((uint64_t)v);
		memcpy(p, &x, 8);
		break;
	}
	}
}

static inline cob_s64 cob_c5_get(const unsigned char *p, int size, int sgn)
{
	switch (size) {
	case 1:
		return sgn ? (cob_s64)(signed char)p[0] : (cob_s64)p[0];
	case 2: {
		uint16_t x;
		memcpy(&x, p, 2);
		return sgn ? (cob_s64)(int16_t)x : (cob_s64)x;
	}
	case 4: {
		uint32_t x;
		memcpy(&x, p, 4);
		return sgn ? (cob_s64)(int32_t)x : (cob_s64)x;
	}
	default: {
		uint64_t x;
		memcpy(&x, p, 8);
		return (cob_s64)x;
	}
	}
}

static inline void cob_c5_set(unsigned char *p, int size, cob_s64 v)
{
	switch (size) {
	case 1:
		p[0] = (unsigned char)v;
		break;
	case 2: {
		uint16_t x = (uint16_t)v;
		memcpy(p, &x, 2);
		break;
	}
	case 4: {
		uint32_t x = (uint32_t)v;
		memcpy(p, &x, 4);
		break;
	}
	default: {
		uint64_t x = (uint64_t)v;
		memcpy(p, &x, 8);
		break;
	}
	}
}

static inline cob_s64 cob_disp_get(const unsigned char *p, int n)
{
	cob_s64 v = 0;
	for (int i = 0; i < n; i++)
		v = v * 10 + (p[i] & 0x0F);
	return v;
}

cob_s64 cob_disps_get_slow(const unsigned char *p, int n);

/* signed DISPLAY with trailing embedded (overpunch) sign */
static inline cob_s64 cob_disps_get(const unsigned char *p, int n)
{
	cob_s64 v = 0;
	for (int i = 0; i < n - 1; i++)
		v = v * 10 + (p[i] & 0x0F);
	unsigned char c = p[n - 1];
	if (c >= '0' && c <= '9')
		return v * 10 + (c - '0');
	if (c >= 0x70 && c <= 0x79)
		return -(v * 10 + (c - 0x70));
	return cob_disps_get_slow(p, n);
}

static inline void cob_disp_set(unsigned char *p, int n, cob_u64 u)
{
	for (int i = n; i > 0; i--) {
		p[i - 1] = (unsigned char)('0' + (int)(u % 10));
		u /= 10;
	}
}

/* -fsign=ebcdic: an embedded sign is written as the EBCDIC overpunch letters
 * ({ A-I positive, } J-R negative) instead of 0x70-0x79 for negatives */
extern int cob_sign_ebcdic;
static inline unsigned char cob_overpunch(unsigned char digit, int neg)
{
	if (!cob_sign_ebcdic)
		return neg ? (unsigned char)(digit + 0x40) : digit;
	int d = digit - '0';
	if (neg)
		return d ? (unsigned char)('J' + d - 1) : '}';
	return d ? (unsigned char)('A' + d - 1) : '{';
}

static inline void cob_disps_set(unsigned char *p, int n, cob_s64 v)
{
	int neg = v < 0;
	cob_disp_set(p, n, neg ? (cob_u64)(-v) : (cob_u64)v);
	if (neg || cob_sign_ebcdic)
		p[n - 1] = cob_overpunch(p[n - 1], neg);
}

/* packed decimal (COMP-3), up to 18 digits */
static inline cob_s64 cob_pack_get(const unsigned char *p, int n)
{
	cob_s64 v = 0;
	for (int i = 0; i < n - 1; i++)
		v = v * 100 + (p[i] >> 4) * 10 + (p[i] & 0x0F);
	v = v * 10 + (p[n - 1] >> 4);
	int sg = p[n - 1] & 0x0F;
	return (sg == 0x0D || sg == 0x0B) ? -v : v;
}

/* COMP-6: every nibble is a digit, so the last byte holds two */
static inline cob_s64 cob_pack6_get(const unsigned char *p, int n)
{
	cob_s64 v = 0;
	for (int i = 0; i < n; i++)
		v = v * 100 + (p[i] >> 4) * 10 + (p[i] & 0x0F);
	return v;
}

static inline void cob_pack_set(unsigned char *p, int n, cob_s64 v, int sgn, int even)
{
	int neg = v < 0;
	cob_u64 u = neg ? (cob_u64)(-v) : (cob_u64)v;
	p[n - 1] = (unsigned char)(((u % 10) << 4) | (sgn ? (neg ? 0x0D : 0x0C) : 0x0F));
	u /= 10;
	for (int i = n - 1; i > 0; i--) {
		unsigned lo = (unsigned)(u % 10);
		u /= 10;
		unsigned hi = (unsigned)(u % 10);
		u /= 10;
		p[i - 1] = (unsigned char)((hi << 4) | lo);
	}
	if (even)
		p[0] &= 0x0F;
}

/* COMP-6: the digits fill every nibble and there is no sign nibble, so the
 * last byte holds two digits rather than a digit and a sign */
static inline void cob_pack6_set(unsigned char *p, int n, cob_s64 v)
{
	cob_u64 u = v < 0 ? (cob_u64)(-v) : (cob_u64)v;
	for (int i = n; i > 0; i--) {
		unsigned lo = (unsigned)(u % 10);
		u /= 10;
		unsigned hi = (unsigned)(u % 10);
		u /= 10;
		p[i - 1] = (unsigned char)((hi << 4) | lo);
	}
}

static inline cob_s64 cob_round_div(cob_s128 v, cob_s64 p, int rounded)
{
	if (rounded) {
		cob_s64 h = p / 2;
		return (cob_s64)(v >= 0 ? (v + h) / p : (v - h) / p);
	}
	return (cob_s64)(v / p);
}

void cob_sub_error(cob_s64 v, cob_s64 max, const char *name, const char *loc) __attribute__((noreturn, cold));

static inline cob_s64 cob_chk_sub(cob_s64 v, cob_s64 max, const char *name, const char *loc)
{
	if (__builtin_expect(v < 1 || v > max, 0))
		cob_sub_error(v, max, name, loc);
	return v;
}

/* ------------------------------------------------------------ runtime control */
void cob_init(int argc, char **argv);
int cob_arg_count(void);                /* the process's argument count */
const char *cob_arg_value(int i);       /* argument i, NULL if out of range */
void cob_getopt_reset(void);            /* start CBL_GC_GETOPT over from argv[1] */
void cob_stop_run(int rc) __attribute__((noreturn));
void cob_fatal(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
/* a second line for the next cob_fatal, saying why (kept out of the message
 * itself, which error procedures and tests compare) */
void cob_fatal_note(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void cob_perform_overflow(const char *loc) __attribute__((noreturn));

/* -fprof (runtime/cobrt_prof.c): an entry per section and paragraph */
typedef struct {
	const char *prog, *source, *section, *para;
	int line;
	int kind;                     /* 1 a section, 0 a paragraph */
	unsigned long long calls, ns;
} cob_prof_entry;
void cob_prof_register(cob_prof_entry *t, int n, int *done);
void cob_prof_switch(cob_prof_entry *e, int count);
int cob_perform_osvs(const cob_perform ***fp, const cob_perform **base, int id);
cob_s64 cob_chk_odo(cob_s64 v, cob_s64 min, cob_s64 max, const char *obj, const char *table,
                    const char *loc);
cob_s64 cob_chk_odo_sub(cob_s64 sub, cob_s64 n, cob_s64 dmin, cob_s64 dmax, const char *name,
                        const char *obj, const char *loc);
cob_field *cob_refmod(cob_field *out, const cob_field *f, cob_s64 start, cob_s64 len, int check, const char *loc);
void *cob_malloc(size_t n);

/* ------------------------------------------------------------ decimal */
static inline cob_dec cob_d_lit(cob_s64 v, int scale) { cob_dec d; d.v = v; d.scale = scale; return d; }
static inline cob_dec cob_d_int(cob_s64 v) { cob_dec d; d.v = v; d.scale = 0; return d; }
static inline cob_dec cob_d_err(void) { cob_dec d; d.v = 0; d.scale = COB_DEC_ERR; return d; }
cob_dec cob_d_str(const char *s);
/* a literal in exponent form ("1.0E+369"): kept as coefficient and scale,
 * never expanded, so its digits and exponent range survive */
cob_dec cob_d_exp_str(const char *s);
cob_dec cob_d_get(const cob_field *f);
cob_dec cob_d_add_slow(cob_dec a, cob_dec b);
static inline cob_dec cob_d_add(cob_dec a, cob_dec b)
{
	if (a.scale == b.scale && a.scale != COB_DEC_ERR) {
		cob_dec r;
		if (!__builtin_add_overflow(a.v, b.v, &r.v)) {
			r.scale = a.scale;
			return r;
		}
	}
	return cob_d_add_slow(a, b);
}
static inline cob_dec cob_d_sub(cob_dec a, cob_dec b)
{
	if (a.scale == b.scale && a.scale != COB_DEC_ERR) {
		cob_dec r;
		if (!__builtin_sub_overflow(a.v, b.v, &r.v)) {
			r.scale = a.scale;
			return r;
		}
	}
	if (b.scale == COB_DEC_ERR)
		return b;
	b.v = -b.v;
	return cob_d_add_slow(a, b);
}
cob_dec cob_d_mul(cob_dec a, cob_dec b);
cob_dec cob_d_div(cob_dec a, cob_dec b);
/* the same at the decimal-float exponent range (scale well past 38): used by
 * expressions whose operands or receiver are FLOAT-DECIMAL-16/34 */
cob_dec cob_d_mul_wide(cob_dec a, cob_dec b);
cob_dec cob_d_div_wide(cob_dec a, cob_dec b);
cob_dec cob_d_pow(cob_dec a, cob_dec b);
cob_dec cob_d_neg(cob_dec a);
cob_dec cob_d_trunc(cob_dec a, int scale);
int cob_d_cmp_slow(cob_dec a, cob_dec b);
static inline int cob_d_cmp(cob_dec a, cob_dec b)
{
	if (a.scale == b.scale && a.scale != COB_DEC_ERR)
		return a.v < b.v ? -1 : (a.v > b.v ? 1 : 0);
	return cob_d_cmp_slow(a, b);
}
int cob_d_sign(cob_dec a);
#define COB_ROUNDED    1
#define COB_SIZE_CHECK 2
#define COB_SIZE_REPORT 0x100   /* store the truncated value but report the overflow */
/* ROUNDED MODE (with COB_ROUNDED; NEAREST-AWAY-FROM-ZERO is the default) */
#define COB_RM_AWAY       (1 << 4)
#define COB_RM_EVEN       (2 << 4)
#define COB_RM_TOWARD0    (3 << 4)   /* NEAREST-TOWARD-ZERO */
#define COB_RM_GREATER    (4 << 4)
#define COB_RM_LESSER     (5 << 4)
#define COB_RM_PROHIBITED (6 << 4)
int cob_d_set(cob_field *f, cob_dec d, int opt);
cob_s64 cob_d_to_int(cob_dec d);
double cob_d_to_double(cob_dec d);
/* a field as a C double, for comparisons that a 38-digit decimal cannot hold */
static inline double cob_operand_double(const cob_field *f)
{
	if (f->attr->type == COB_NUM_FLOAT && f->size == 4) {
		float x;
		memcpy(&x, f->data, sizeof x);
		return (double)x;
	}
	if (f->attr->type == COB_NUM_DOUBLE && f->size == 8) {
		double x;
		memcpy(&x, f->data, sizeof x);
		return x;
	}
	return cob_d_to_double(cob_d_get((cob_field *)f));
}
cob_dec cob_d_from_double(double x);
cob_s64 cob_get_int(const cob_field *f);
void cob_set_int(cob_field *f, cob_s64 v);
cob_field *cob_dec_field(cob_dec d);
cob_field *cob_tmp_field(size_t size, const cob_attr *attr);

/* PIC X ANY LENGTH: the field is as long as the caller's argument */
static inline cob_field *cob_field_for_any_length(unsigned char *data, int n,
                                                 const cob_attr *a)
{
	cob_field *f = cob_tmp_field((size_t)(n > 0 ? n : 0), a);
	f->data = data;
	return f;
}
int cob_d_to_str(cob_dec d, char *buf, size_t bufsz);

/* ------------------------------------------------------------ move / compare */
void cob_move(const cob_field *src, cob_field *dst);
void cob_move_ibm(const cob_field *src, cob_field *dst);
void cob_move_bytes(const unsigned char *src, size_t n, cob_field *dst);
void cob_move_text(cob_field *dst, const char *s);
/* read an integer of n bytes, big-endian, into a field: CALL/READ BY VALUE */
static inline void cob_get_value(int n, const unsigned char *p, cob_field *f)
{
	cob_s64 v = 0;
	int neg = n > 0 && (p[0] & 0x80);
	for (int i = 0; i < n; i++)
		v = (v << 8) | p[i];
	if (neg && n < 8)
		v -= (cob_s64)1 << (n * 8);
	cob_set_int(f, v);
}

/* Read a BY VALUE argument the way GnuCOBOL passes one: as a native integer,
 * so the bytes that exist are the LOW-order ones. `want` is the width the
 * callee asked for and `have` the width the caller supplied; when the callee
 * asks for more than was passed, the bytes that are there are the low ones. */
static inline void cob_get_arg_value(int want, int have, const unsigned char *p, cob_field *f)
{
	if (want <= 0)
		want = have;
	if (have <= 0) {
		cob_set_int(f, 0);
		return;
	}
	if (want >= have) {
		cob_get_value(have, p, f);
		return;
	}
	cob_get_value(want, p + (have - want), f);
}

/* store an integer in n bytes of C storage, big-endian, for CALL BY VALUE */
static inline void cob_put_value(int n, unsigned char *p, cob_s64 v)
{
	cob_u64 u = (cob_u64)v;
	for (int i = n - 1; i >= 0; i--) {
		p[i] = (unsigned char)(u & 0xFF);
		u >>= 8;
	}
}
void cob_move_raw(const cob_field *src, cob_field *dst);
void cob_set_collating(const unsigned short *tbl);
const unsigned short *cob_get_collating(void);
int cob_cmp(const cob_field *a, const cob_field *b);
int cob_cmp_alnum(const unsigned char *a, size_t al, const unsigned char *b, size_t bl);
int cob_is_numeric(const cob_field *f);
void cob_chk_data(const cob_field *f, const char *name, const char *loc);
extern int cob_host_sign;
extern int cob_pretty_display;
extern int cob_settings_fixed;
void cob_module_settings(int pretty, int host_sign, int sign_ebcdic, const char *when);
int cob_cmp_float(const cob_field *a, const cob_field *b);
int cob_cmp_dbl(double x, double y);
double cob_dbl_div(double a, double b);
double cob_dbl_pow(double a, double b);
double cob_dbl_sqrt(double a);
double cob_dbl_math(int which, double a);
static inline double cob_dbl_abs(double a) { return a < 0 ? -a : a; }
int cob_put_float(cob_field *f, double v);
int cob_is_alpha(const cob_field *f);
int cob_is_lower(const cob_field *f);
int cob_is_upper(const cob_field *f);
int cob_is_class(const cob_field *f, const unsigned char *table);
size_t cob_field_text(const cob_field *f, unsigned char *buf, size_t bufsz);

/* ------------------------------------------------------------ display / accept */
void cob_display(int dev, const cob_field *f);
int cob_display_ok(int dev);
void cob_display_warn_punch(const char *loc);
void cob_display_lit(int dev, const char *s, size_t n);
void cob_display_dec(int dev, cob_dec d);
/* DISPLAY's text for a FLOAT-DECIMAL-16/34 item (GnuCOBOL's decimal format:
 * all significant digits, or a mantissa and E exponent) */
int cob_dec_float_str(const cob_field *f, char *buf, size_t bufsz);
void cob_display_signed(int dev, cob_s64 v, int digits);
void cob_display_end(int dev, int newline);
int cob_accept(cob_field *f);
struct tm;
void cob_now(struct tm *tm, int *hundredths, long *utc_off);
void cob_accept_date(cob_field *f, int fmt);
void cob_accept_time(cob_field *f);
void cob_accept_cmdline(cob_field *f);
int cob_accept_env(cob_field *f, const cob_field *name);
void cob_accept_discard(void);
void cob_accept_argv(cob_field *f, int what);
void cob_display_env(int what, const cob_field *f);

/* ------------------------------------------------------------ string / unstring / inspect */
void cob_string_init(cob_field *dst, cob_field *ptr);
void cob_string_delimited(const cob_field *dlm);
void cob_string_append(const cob_field *src);
int cob_string_finish(void);
void cob_unstring_init(cob_field *src, cob_field *ptr);
void cob_unstring_delim(const cob_field *d, int all);
void cob_unstring_into(cob_field *dst, cob_field *dlm, cob_field *cnt);
void cob_unstring_tallying(cob_field *f);
int cob_unstring_finish(void);
#define COB_INSP_CHARACTERS 0
#define COB_INSP_ALL        1
#define COB_INSP_LEADING    2
#define COB_INSP_FIRST      3
#define COB_INSP_TRAILING   4
void cob_inspect_start(cob_field *target);
void cob_inspect_tally(cob_field *counter, int mode, const cob_field *pat, const cob_field *before, const cob_field *after);
void cob_inspect_replace(int mode, const cob_field *pat, const cob_field *by, const cob_field *before, const cob_field *after);
void cob_inspect_end(void);
void cob_inspect_converting(cob_field *target, const cob_field *from, const cob_field *to, const cob_field *before, const cob_field *after);

/* ------------------------------------------------------------ CALL */
typedef int (*cob_prog_fn)(int, unsigned char **);
typedef void (*cob_cancel_fn)(void);
#define COB_DECL_ENTRY (-2)
extern int cob_decl_which;
extern int cob_call_rejected;     /* set by a program entered while active */
void cob_register_program(const char *name, cob_prog_fn fn, cob_cancel_fn cancel);
void cob_cancel(const cob_field *name);
void cob_cancel_name(const char *name);
cob_prog_fn cob_resolve(const cob_field *name);
cob_prog_fn cob_resolve_name(const char *name);
/* a reference to a C symbol under another C name: a weak reference to a
 * function that a CALL literal may name, without clashing with a header's
 * declaration of it */
#define COB_STR2_(x) #x
#define COB_STR_(x) COB_STR2_(x)
#define COB_ASM_NAME(n) __asm__(COB_STR_(__USER_LABEL_PREFIX__) n)
/* what a CALL by name reaches: a COBOL program, or else a C function (cobrt_call.c) */
typedef struct {
	cob_prog_fn fn;
	void *cfn;
} cob_callee;
cob_callee cob_lookup_name(const char *name, void *weak);
void cob_register_entry(const char *name, cob_prog_fn fn, cob_cancel_fn cancel, void *cw);
void *cob_entry_address(const char *name, void *weak);
cob_callee cob_lookup(const cob_field *name);
cob_s64 cob_call_c(void *fn, int n, unsigned char **av);
extern const signed char *cob_call_modes;
extern int cob_call_params;
int cob_c_name(const char *name, char *out, size_t sz);
void cob_call_not_found(const char *where, const char *name) __attribute__((noreturn));
void cob_call_not_found_field(const char *where, const cob_field *name) __attribute__((noreturn));
extern int cob_initialized;
void cob_ensure_init(void);
int cob_c_argc(int declared);
void cob_call_init(void);
void cob_close_all_files(void);
void cob_flush_files(void);         /* a signal ends the run unit: written data kept */
void cob_runtime_config(void);      /* COB_RUNTIME_CONFIG / runtime.cfg (cobrt_conf.c) */
void cob_call_system(const cob_field *cmd);
int cob_switch_get(int n);
void cob_switch_set(int n, int v);

/* ------------------------------------------------------------ Debug module */
/* Object-time debugging switch: USE FOR DEBUGGING procedures of programs
 * compiled WITH DEBUGGING MODE run only when COB_SET_DEBUG is set (Y, YES,
 * ON, TRUE or 1). DEBUG-ITEM layout: DEBUG-LINE 0, DEBUG-NAME 7,
 * DEBUG-SUB-1/2/3 38/44/50, DEBUG-CONTENTS 56. */
extern int cob_debug_on;
int cob_debug_enabled(void);
enum { COB_DBG_FALL, COB_DBG_START, COB_DBG_PERFORM, COB_DBG_GOTO, COB_DBG_SORT_IN,
       COB_DBG_SORT_OUT, COB_DBG_MERGE_OUT, COB_DBG_USE };
void cob_dbg_proc(unsigned char *di, int dilen, int line, const char *name, int cause);
void cob_dbg_alter(unsigned char *di, int dilen, int line, const char *name, const char *target);
void cob_dbg_data(unsigned char *di, int dilen, int line, const char *name,
                  const unsigned char *data, size_t size, int nsubs, cob_s64 s1, cob_s64 s2, cob_s64 s3);

/* ------------------------------------------------------------ intrinsic functions */
typedef struct { int n; cob_dec *v; cob_field **f; } cob_args;
cob_dec cob_fn_abs(cob_dec a);
cob_dec cob_fn_integer(cob_dec a);
cob_dec cob_fn_integer_part(cob_dec a);
cob_dec cob_fn_fraction_part(cob_dec a);
cob_dec cob_fn_mod(cob_dec a, cob_dec b);
cob_dec cob_fn_rem(cob_dec a, cob_dec b);
cob_dec cob_fn_sign(cob_dec a);
cob_dec cob_fn_sqrt(cob_dec a);
cob_dec cob_fn_math(int which, cob_dec a);
cob_dec cob_fn_pi(void);
cob_dec cob_fn_e(void);
cob_dec cob_fn_factorial(cob_dec a);
cob_dec cob_fn_random(int has_seed, cob_dec seed);
cob_dec cob_fn_length(const cob_field *f);
cob_dec cob_fn_ord(const cob_field *f);
cob_dec cob_fn_numval(const cob_field *f, const cob_field *cur, const char *defcur, int kind, int dpc);
cob_dec cob_fn_test_numval(const cob_field *f, const cob_field *cur, const char *defcur, int kind, int dpc);
cob_dec cob_fn_aggregate(int which, int n, const cob_dec *v);
cob_dec cob_fn_annuity(cob_dec rate, cob_dec periods);
cob_dec cob_fn_present_value(int n, const cob_dec *v);
cob_dec cob_fn_variance(int n, const cob_dec *v, int sd);
cob_dec cob_hp_pow(cob_dec a, cob_dec b);
double cob_fn_random_d(int has_seed, cob_dec seed);
cob_field *cob_fn_field(cob_dec d, int flags, int digits);
cob_field *cob_fn_abs_field(cob_dec d, int flags);
cob_field *cob_fn_model_field(cob_dec d, const cob_field *model);
cob_field *cob_fn_minmax_num(int is_max, int n, cob_field **f);
cob_field *cob_fn_median_num(int n, cob_field **f, int flags);
cob_field *cob_double_field(double x);
cob_dec cob_d_from_double_exact(double x);
cob_dec cob_fn_integer_of_date(cob_dec a);
cob_dec cob_fn_date_of_integer(cob_dec a);
cob_dec cob_fn_integer_of_day(cob_dec a);
cob_dec cob_fn_day_of_integer(cob_dec a);
cob_dec cob_fn_test_date(cob_dec a);
cob_dec cob_fn_test_day(cob_dec a);
cob_dec cob_fn_date_to_yyyymmdd(int n, cob_dec a, cob_dec b, cob_dec c);
cob_dec cob_fn_day_to_yyyyddd(int n, cob_dec a, cob_dec b, cob_dec c);
cob_dec cob_fn_year_to_yyyy(int n, cob_dec a, cob_dec b, cob_dec c);
cob_dec cob_fn_seconds_past_midnight(void);
cob_field *cob_fn_upper(const cob_field *f);
cob_field *cob_fn_lower(const cob_field *f);
cob_field *cob_fn_reverse(const cob_field *f);
cob_field *cob_fn_trim(const cob_field *f, int mode);
cob_field *cob_fn_char(cob_dec a);
cob_field *cob_fn_current_date(void);
cob_field *cob_fn_when_compiled(void);
cob_field *cob_fn_concatenate(int n, cob_field **f);
cob_field *cob_fn_substitute(int n, cob_field **f);
cob_field *cob_fn_substitute_case(int n, cob_field **f);
cob_field *cob_fn_hex_of(const cob_field *f);
cob_field *cob_fn_hex_to_char(const cob_field *f);
cob_field *cob_fn_bit_of(const cob_field *f);
cob_field *cob_fn_bit_to_char(const cob_field *f);
cob_field *cob_fn_uuid4(void);
cob_dec cob_fn_ulength(const cob_field *f);
cob_dec cob_fn_upos(const cob_field *f, cob_dec n);
cob_dec cob_fn_uwidth(const cob_field *f, cob_dec n);
cob_field *cob_fn_usubstr(const cob_field *f, cob_dec start, cob_dec count, int has_count);
cob_dec cob_fn_uvalid(const cob_field *f);
cob_dec cob_fn_usupplementary(const cob_field *f);
cob_field *cob_fn_minmax_alnum(int is_max, int n, cob_field **f);
cob_dec cob_fn_ord_minmax(int is_max, int n, const cob_dec *v);
cob_dec cob_fn_ord_minmax_alnum(int is_max, int n, cob_field **f);
cob_field *cob_fn_module_name(const char *name);

/* ------------------------------------------------------------ files */
#define COB_ORG_SEQUENTIAL 0
#define COB_ORG_LINE_SEQ   1
#define COB_ORG_RELATIVE   2
#define COB_ORG_INDEXED    3
#define COB_ACC_SEQUENTIAL 0
#define COB_ACC_RANDOM     1
#define COB_ACC_DYNAMIC    2
#define COB_OPEN_INPUT     1
#define COB_OPEN_OUTPUT    2
#define COB_OPEN_IO        3
#define COB_OPEN_EXTEND    4
#define COB_IO_OK      0
#define COB_IO_ATEND   1
#define COB_IO_INVALID 2
#define COB_IO_ERROR   3
#define COB_IO_EOP     4
#define COB_MAX_KEYS   64

#define COB_KEY_MAX_SEGS 8

/* A key is one or more segments of a record, taken in order. An ordinary key
 * has one; a split key (RECORD KEY ... SOURCE IS a, b, c) has several, and its
 * value is their concatenation. `offset`/`size` describe the first segment so
 * the single-segment case stays a plain memcmp. */
typedef struct {
	size_t offset;
	size_t size;
	const cob_attr *attr;
	int dups;
	int nseg;
	struct { size_t offset; size_t size; } seg[COB_KEY_MAX_SEGS];
	size_t total;              /* length of the concatenation */
	const unsigned char *supp; /* SUPPRESS WHEN: keys not indexed */
	size_t supplen;
	int supp_all;              /* SUPPRESS WHEN ALL c: every byte equals c */
} cob_file_key;

typedef struct cob_irec cob_irec;

/* COBOL 2002 exception information (EXCEPTION-STATUS and friends): the last
   exception condition raised and where */
typedef struct {
	const char *prog, *para, *sect, *stmt;
	int line;
} cob_loc;
extern const cob_loc *cob_cur_loc;       /* statement being executed, where tracked */
void cob_set_exception(const char *name);
void cob_exc_where(const cob_loc *loc);
cob_field *cob_fn_exception_file(void);
cob_field *cob_fn_exception_location(void);
cob_field *cob_fn_exception_statement(void);
cob_field *cob_fn_exception_status(void);
size_t cob_fn_content_length(const unsigned char *p);
cob_field *cob_fn_content_of(const unsigned char *p, cob_s64 len);
void cob_clear_exception(void);
void cob_set_env(const cob_field *name, const cob_field *value);
const char *cob_chain_arg(int n);   /* CHAINING argument n, or NULL */
int cob_param_omitted(int n);       /* was CALL argument n left out? */
void cob_enter_at(int n);           /* CALL to an ENTRY point: start there */
/* a POINTER item holds the address itself */
static inline unsigned char *cob_pointer_get(const cob_field *f)
{
	unsigned char *p = NULL;
	memcpy(&p, f->data, f->size < sizeof p ? f->size : sizeof p);
	return p;
}
static inline void cob_pointer_set(cob_field *f, const void *v)
{
	unsigned char *p = (unsigned char *)v;
	memset(f->data, 0, f->size);
	memcpy(f->data, &p, f->size < sizeof p ? f->size : sizeof p);
}
/* ALLOCATE / FREE */
/* a BASED item that was never allocated is a clean error, not a wild write */
static inline unsigned char *cob_based_ptr(unsigned char *p, const char *name)
{
	if (!p)
		cob_fatal("BASED item '%s' used before ALLOCATE", name);
	return p;
}
/* a LINKAGE item whose CALL argument was left out has a NULL address: touching
   it is an error, not a wild read (GnuCOBOL reports the same) */
static inline unsigned char *cob_lk_ptr(unsigned char *p, const char *item,
                                        const char *by, const char *loc)
{
	if (!p)
		cob_fatal("%s: error: LINKAGE item '%s' (accessed by '%s') not passed by caller",
		          loc, item, by);
	return p;
}
unsigned char *cob_alloc_chars(cob_s64 n);
void cob_free_chars(unsigned char *p);
void cob_fill_block(unsigned char *p, size_t n, const cob_field *v);
extern int cob_zero_div_seen;          /* a DIVIDE by zero ran in this statement */

/* JSON GENERATE */
typedef struct cob_jsonw {
	unsigned char *dst;
	size_t cap;
	size_t len;
	int overflow;
} jsonw;
void cob_json_code_reset(void);
int cob_json_code_value(void);
void cob_json_code_set(int v);
void cob_json_init(jsonw *w, cob_field *out);
void cob_json_obj_open(jsonw *w);
void cob_json_obj_close(jsonw *w);
void cob_json_arr_open(jsonw *w);
void cob_json_arr_close(jsonw *w);
void cob_json_comma(jsonw *w);
void cob_json_key(jsonw *w, const char *name);
void cob_json_str(jsonw *w, cob_field *f, int justified);
void cob_json_num(jsonw *w, cob_field *f, int dpc);
void cob_json_finish(jsonw *w, cob_field *count_in);
extern cob_field cob_json_code_reg;       /* JSON-CODE */
/* JSON PARSE: the receiver described node by node, each subtree contiguous */
enum { COB_JP_GROUP, COB_JP_ITEM, COB_JP_BOOL };
typedef struct {
	const char *name;          /* the JSON name; NULL for a receiver NAMEd OMITTED */
	unsigned char exact;       /* a NAME phrase literal: matched case and all */
	unsigned char kind;        /* COB_JP_* */
	int span;                  /* nodes in its subtree, itself included */
	size_t offset;             /* from the receiver's start, first occurrences */
	size_t size;               /* the item's size; a table's, one occurrence's */
	int occurs;                /* a table's occurrences; 0 for no table */
	const cob_field *odo;      /* OCCURS DEPENDING ON object */
	const cob_attr *attr;
	const cob_field *tv, *fv;  /* COB_JP_BOOL: what true and false MOVE */
} cob_jp_node;
int cob_json_parse(cob_field *text, cob_field *into, const cob_jp_node *nodes, int detail);
extern cob_field cob_json_status_reg;     /* JSON-STATUS */

/* embedded SQL (cobrt_sql.c): a host variable, where a statement's outcome
 * goes (the items of the program's SQLCA, or its SQLCODE and SQLSTATE; NULL
 * for those it lacks), and the statements */
typedef struct {
	cob_field *f;              /* the host variable; a VARCHAR's text */
	cob_field *ind;            /* its indicator variable, or NULL */
	cob_field *len;            /* a VARCHAR's length item, or NULL */
} cob_sql_hv;
typedef struct {
	cob_field *caid, *cabc, *code, *errml, *errmc, *errp;
	cob_field *errd;           /* SQLERRD(1); the others follow it */
	int nerrd;
	cob_field *warn;           /* SQLWARN: SQLWARN0, SQLWARN1, ... */
	cob_field *state;
} cob_sql_ca;
void cob_sql_connect(const cob_sql_ca *ca, cob_field *target, cob_field *user, cob_field *pass, cob_field *name);
void cob_sql_disconnect(const cob_sql_ca *ca, cob_field *name, int all);
void cob_sql_set_connection(const cob_sql_ca *ca, cob_field *name);
void cob_sql_end_work(const cob_sql_ca *ca, int rollback, int release);
void cob_sql_exec(const cob_sql_ca *ca, const char *sql, int nin, const cob_sql_hv *in, int nout,
                  const cob_sql_hv *out);
void cob_sql_current(const cob_sql_ca *ca, const char *sql, const char *cursor, int nin, const cob_sql_hv *in);
void cob_sql_open(const cob_sql_ca *ca, const char *cursor, const char *sql, const char *prepared, int keyed,
                  int hold, int nin, const cob_sql_hv *in);
void cob_sql_fetch(const cob_sql_ca *ca, const char *cursor, int nout, const cob_sql_hv *out);
void cob_sql_close(const cob_sql_ca *ca, const char *cursor);
void cob_sql_prepare(const cob_sql_ca *ca, const char *name, const cob_sql_hv *text);
void cob_sql_execute(const cob_sql_ca *ca, const char *name, int nin, const cob_sql_hv *in, int nout,
                     const cob_sql_hv *out);
void cob_sql_immediate(const cob_sql_ca *ca, const cob_sql_hv *text);
int cob_sql_code(void);                 /* SQLCODE of the last statement, for WHENEVER */
int cob_sql_warn(void);
void cob_sql_end(int abnormal);

/* XML GENERATE */
typedef struct {
	unsigned char *dst;
	size_t cap;
	size_t len;
	int overflow;
	int pending[258];           /* per depth: open tag not closed yet */
	size_t open_at[258];
	int depth;
	size_t empty_start;
	int last_was_empty;
	int abort;                  /* a name or namespace was rejected: stop */
	int hex[258];               /* per depth: content written as hex (417) */
	int attrs[258];             /* per depth: the open element has attributes */
} xmlw;
void cob_xml_code_reset(void);
int cob_xml_code_value(void);
void cob_xml_init(xmlw *w, cob_field *out);
void cob_xml_declaration(xmlw *w);
void cob_xml_root_namespace(xmlw *w, const char *prefix, cob_field *uri);
void cob_xml_prefix(char *out, size_t cap, const cob_field *prefix, const cob_field *uri);
void cob_xml_elem_open(xmlw *w, const char *prefix, const char *name);
void cob_xml_elem_close(xmlw *w, const char *prefix, const char *name);
void cob_xml_text(xmlw *w, cob_field *f);
void cob_xml_text_just(xmlw *w, cob_field *f);
void cob_xml_num(xmlw *w, cob_field *f, int dpc);
void cob_xml_attr(xmlw *w, const char *prefix, const char *name, cob_field *f);
void cob_xml_attr_num(xmlw *w, const char *prefix, const char *name, cob_field *f, int dpc);
void cob_xml_finish(xmlw *w, cob_field *count_in);
int cob_xml_bad_uri(const cob_field *f);
void cob_xml_abort(xmlw *w, int code);
int cob_xml_bad_prefix(const char *p);
int cob_xml_all(const cob_field *f, int c);
int cob_xml_nonnumeric(const cob_field *f);
size_t cob_xml_mark(xmlw *w);
void cob_xml_rollback_if_empty(xmlw *w, size_t mark);
extern cob_field cob_xml_code_reg;       /* XML-CODE */
/* XML PARSE (cobrt_xmlp.c): the registers, and the loop the statement runs */
extern cob_field cob_xml_event_reg, cob_xml_text_reg, cob_xml_ns_reg, cob_xml_nsprefix_reg;
void cob_xml_parse_start(cob_field *doc);
int cob_xml_parse_next(void);
int cob_xml_parse_after(void);
int cob_xml_parse_finish(void);

/* SCREEN SECTION and DISPLAY / ACCEPT ... AT (cobrt_scr.c) */
#define COB_SCR_HIGHLIGHT    0x00001
#define COB_SCR_LOWLIGHT     0x00002
#define COB_SCR_BLINK        0x00004
#define COB_SCR_REVERSE      0x00008
#define COB_SCR_UNDERLINE    0x00010
#define COB_SCR_SECURE       0x00020
#define COB_SCR_AUTO         0x00040
#define COB_SCR_REQUIRED     0x00080
#define COB_SCR_FULL         0x00100
#define COB_SCR_BLANK_SCREEN 0x00200
#define COB_SCR_BLANK_LINE   0x00400
#define COB_SCR_ERASE_EOL    0x00800
#define COB_SCR_ERASE_EOS    0x01000
#define COB_SCR_BELL         0x02000
#define COB_SCR_UPDATE       0x04000
#define COB_SCR_INPUT        0x08000   /* TO or USING: takes input */
#define COB_SCR_OUTPUT       0x10000   /* FROM, USING or VALUE: displayed */
#define COB_SCR_INITIAL      0x20000   /* INITIAL: the field an ACCEPT starts in */
#define COB_SCR_REPEAT       0x40000   /* DISPLAY of a figurative constant or ALL literal */
#define COB_SCR_OVERLINE     0x80000
/* DISPLAY of a figurative constant with an effect of its own (as Micro Focus) */
enum { COB_SCR_SP_CURSOR,      /* LOW-VALUE: only the position */
       COB_SCR_SP_EOS,         /* SPACE: erase to the end of the screen */
       COB_SCR_SP_EOL,         /* ALL X'01': erase to the end of the line */
       COB_SCR_SP_CLEAR,       /* ALL X'02': erase the screen */
       COB_SCR_SP_BELL };      /* ALL X'07': the bell */
enum { COB_SCR_GROUP, COB_SCR_LITERAL, COB_SCR_FIELD };
enum { COB_SCR_NONE, COB_SCR_ABS, COB_SCR_PLUS, COB_SCR_MINUS };
typedef struct {
	unsigned char kind;               /* COB_SCR_GROUP / LITERAL / FIELD */
	unsigned char line_mode, col_mode;
	int line, col;
	cob_field *line_f, *col_f;        /* LINE / COLUMN from a data item */
	const unsigned char *value;       /* VALUE literal */
	int vlen;
	cob_field *field;                 /* the screen item's own storage */
	int attrs;                        /* COB_SCR_* */
	signed char fg, bg;               /* colour 0-15, -1 none */
	unsigned char prompt;             /* PROMPT character, 0 for '_' */
} cob_scr_item;
void cob_scr_display(const cob_scr_item *items, int first, int n, int at_line, int at_col);
int cob_scr_accept(const cob_scr_item *items, int first, int n, int at_line, int at_col);
void cob_scr_at(const cob_field *at, int *line, int *col);
void cob_scr_display_field(const cob_field *f, int line, int col, int attrs, int fg, int bg, int size);
void cob_scr_display_special(int what, int line, int col, int fg, int bg);
int cob_scr_accept_field(cob_field *f, int line, int col, int attrs, int fg, int bg, int prompt,
			 int size);
void cob_scr_set_timeout(int seconds);
void cob_scr_color(int v, int *attrs, int *fg, int *bg);
void cob_scr_color_item(cob_scr_item *it, int v);
void cob_scr_set_crt_status(cob_field *f);
void cob_scr_set_cursor(cob_field *f);
int cob_scr_escape_key(void);
void cob_scr_signal(void);          /* a signal ends the run unit: the terminal back */
extern cob_field cob_crt_status_reg;
size_t cob_display_text(const cob_field *f, char *buf, size_t sz);

/* -ftrace / -ftraceall: READY TRACE, RESET TRACE, COB_SET_TRACE, COB_TRACE_FILE */
extern int cob_trace_on;
void cob_trace_point(const char *src, const char *prog, const char *label, const char *name, int line);

/* calling chain for MODULE-ID / MODULE-CALLER-ID */
void cob_module_push(const char *name, int argc);
void cob_module_pop(void);
extern const int *cob_call_sizes;
extern const unsigned char *cob_call_arg_omitted;
extern int cob_entry_pending;
extern int cob_entry_reentry;
extern cob_field cob_ncp_reg;            /* NUMBER-OF-CALL-PARAMETERS */
int cob_frame_nargs(void);
int cob_frame_param_size(int i);
const char *cob_frame_caller(void);
void cob_warning(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void cob_map_filename(const char *in, char *out, size_t sz);
cob_field *cob_fn_module_caller_id(void);
cob_field *cob_fn_module_path(void);
cob_field *cob_fn_text(const char *s);

/* library routines called by name (cobrt_sys.c) */
int cob_sys_cbl_and(int n, cob_field **a);
int cob_sys_cbl_gc_hosted(int n, cob_field **a);
char **cob_arg_vector(void);
int cob_sys_cbl_or(int n, cob_field **a);
int cob_sys_cbl_nor(int n, cob_field **a);
int cob_sys_cbl_xor(int n, cob_field **a);
int cob_sys_cbl_imp(int n, cob_field **a);
int cob_sys_cbl_nimp(int n, cob_field **a);
int cob_sys_cbl_eq(int n, cob_field **a);
int cob_sys_cbl_not(int n, cob_field **a);
int cob_sys_cbl_toupper(int n, cob_field **a);
int cob_sys_cbl_tolower(int n, cob_field **a);
int cob_sys_c_toupper(int n, cob_field **a);
int cob_sys_c_tolower(int n, cob_field **a);
int cob_sys_c_justify(int n, cob_field **a);
int cob_sys_c_printable(int n, cob_field **a);
int cob_sys_cbl_oc_dump(int n, cob_field **a);
int cob_sys_c_narg(int n, cob_field **a);
int cob_sys_c_paramsize(int n, cob_field **a);
int cob_sys_c_calledby(int n, cob_field **a);
int cob_sys_c_getpid(int n, cob_field **a);
int cob_sys_c_sleep(int n, cob_field **a);
int cob_sys_cbl_gc_nanosleep(int n, cob_field **a);
int cob_sys_cbl_gc_fork(int n, cob_field **a);
int cob_sys_cbl_gc_getopt(int n, cob_field **a);
int cob_sys_cbl_error_proc(int n, cob_field **a);
int cob_sys_cbl_alloc_mem(int n, cob_field **a);
int cob_sys_cbl_free_mem(int n, cob_field **a);
int cob_sys_cbl_exit_proc(int n, cob_field **a);
void cob_run_exit_procs(void);
int cob_sys_x_f4(int n, cob_field **a);
int cob_sys_x_f5(int n, cob_field **a);
int cob_sys_x_e4(int n, cob_field **a);
int cob_sys_x_e5(int n, cob_field **a);
int cob_sys_cbl_get_scr_size(int n, cob_field **a);
int cob_sys_cbl_get_csr_pos(int n, cob_field **a);
int cob_sys_cbl_set_csr_pos(int n, cob_field **a);
int cob_sys_cbl_read_kbd_char(int n, cob_field **a);
int cob_sys_cbl_get_kbd_status(int n, cob_field **a);
void cob_error_proc_set(void *fn);
int cob_sys_cbl_gc_waitpid(int n, cob_field **a);
int cob_sys_cbl_create_dir(int n, cob_field **a);
int cob_sys_cbl_delete_dir(int n, cob_field **a);
int cob_sys_cbl_change_dir(int n, cob_field **a);
int cob_sys_c_makedir(int n, cob_field **a);
int cob_sys_c_chdir(int n, cob_field **a);
int cob_sys_cbl_get_current_dir(int n, cob_field **a);
int cob_sys_cbl_delete_file(int n, cob_field **a);
int cob_sys_c_delete(int n, cob_field **a);
int cob_sys_cbl_rename_file(int n, cob_field **a);
int cob_sys_cbl_copy_file(int n, cob_field **a);
int cob_sys_c_copy(int n, cob_field **a);
int cob_sys_cbl_check_file_exist(int n, cob_field **a);
int cob_sys_c_fileinfo(int n, cob_field **a);
int cob_sys_cbl_open_file(int n, cob_field **a);
int cob_sys_cbl_create_file(int n, cob_field **a);
int cob_sys_cbl_read_file(int n, cob_field **a);
int cob_sys_cbl_write_file(int n, cob_field **a);
int cob_sys_cbl_close_file(int n, cob_field **a);
int cob_sys_cbl_flush_file(int n, cob_field **a);

/* date and time (cobrt_dt.c) */
cob_field *cob_fn_formatted_date(const cob_field *fmt, cob_dec date, int dpc);
cob_field *cob_fn_formatted_time(const cob_field *fmt, cob_dec secs, int has_off, cob_dec off, int dpc);
cob_field *cob_fn_formatted_datetime(const cob_field *fmt, cob_dec date, cob_dec secs, int has_off,
				     cob_dec off, int dpc);
cob_field *cob_fn_formatted_current_date(const cob_field *fmt, int dpc);
cob_dec cob_fn_test_formatted_datetime(const cob_field *fmt, const cob_field *val, int dpc);
cob_dec cob_fn_integer_of_formatted_date(const cob_field *fmt, const cob_field *val, int dpc);
cob_dec cob_fn_seconds_from_formatted_time(const cob_field *fmt, const cob_field *val, int dpc);
cob_dec cob_fn_combined_datetime(cob_dec date, cob_dec secs);
cob_field *cob_fn_locale_compare(const cob_field *a, const cob_field *b);
cob_field *cob_fn_locale_date(const cob_field *f);
cob_field *cob_fn_locale_time(const cob_field *f);
cob_field *cob_fn_locale_time_from_seconds(cob_dec secs);
cob_field *cob_fn_locale_info(int which);

typedef struct cob_file {
	const char *select_name;
	int organization;
	int access;
	int optional;
	int assign_kind;          /* 0 file, 1 stdin, 2 stdout, 3 printer */
	int assign_literal;
	int variable;
	cob_field *assign_field;
	const char *assign_name;
	unsigned char *record;
	size_t record_max;
	size_t record_min;
	cob_field *size_field;    /* RECORD VARYING DEPENDING ON */
	cob_field *status;
	cob_field *relative_key;
	int nkeys;
	cob_file_key keys[COB_MAX_KEYS];
	int is_sort;
	int has_declarative;
	int sharing;             /* 0 none, 1 READ ONLY, 2 exclusive (SHARING NO) */
	/* state */
	int lockfd;              /* open while SHARING holds a lock on the file */
	int open_mode;
	FILE *fp;
	char path[1024];
	int last_read_ok;
	long last_pos;
	size_t cur_size;
	char stat[2];
	int at_end;
	int no_current;          /* last START failed: no current record (46) */
	int linage_lines;
	void *ix;               /* relative / indexed state */
	/* sort */
	unsigned char **sbuf;
	size_t scount, scap, sret;
	int sort_nkeys;
	const void *sort_keys;
	struct cob_file *next_open;
	int use_mode;             /* mode of the last OPEN attempt (USE procedures) */
	/* LINAGE */
	cob_field *linage_ctr;
	cob_field *lin_src[4];    /* LINAGE, FOOTING, TOP, BOTTOM data items (or NULL) */
	int lin_const[4];         /* ... or integer values */
	int lin_lines, lin_foot, lin_top, lin_bot;
	int lin_need_top;
	int eop;                  /* end-of-page condition raised by last WRITE */
	int locked;               /* CLOSE WITH LOCK */
	const unsigned short *sort_coll;  /* SORT/MERGE COLLATING SEQUENCE */
	int no_mapping;           /* -fno-filename-mapping: the name is used as it stands */
	char given[256];          /* the name ASSIGN gave, before mapping (for messages) */
	int lock_mode;            /* LOCK MODE: 0 none, 1 MANUAL, 2 AUTOMATIC, 3 EXCLUSIVE */
	int lock_multiple;        /* LOCK MODE ... WITH LOCK ON MULTIPLE RECORDS */
	int open_lock;            /* OPEN ... WITH LOCK: this OPEN has the file to itself */
	int read_lock;            /* the lock phrase of the READ under way (COB_LOCK_*) */
	void *holder;             /* the process's file-level locks (cobrt_io.c) */
	unsigned char *ls_carry;  /* LINE SEQUENTIAL, COB_LS_SPLIT: the rest of a long line */
	size_t ls_carry_len, ls_carry_at;
	unsigned char varfmt;     /* variable-length SEQUENTIAL: COB_VARSEQ_FORMAT of this file */
} cob_file;
/* SHARING (cob_file.sharing) */
#define COB_SHARE_NONE      0   /* no clause: INPUT shares, a sequential file opened
				   otherwise is the opener's alone */
#define COB_SHARE_READ_ONLY 1
#define COB_SHARE_NO        2
#define COB_SHARE_ALL       3
/* the lock phrase of a READ */
#define COB_LOCK_DEFAULT 0      /* none: as LOCK MODE says */
#define COB_LOCK_WITH    1      /* WITH LOCK */
#define COB_LOCK_NONE    2      /* WITH NO LOCK, IGNORING LOCK */
#define COB_LOCK_KEPT    3      /* WITH KEPT LOCK */

void cob_exc_io(cob_file *f, const char *status);
int cob_open(cob_file *f, int mode);
int cob_close(cob_file *f);
int cob_close_opt(cob_file *f, int opt);
int cob_delete_file(cob_file *f);
void cob_close_quiet(cob_file *f);
int cob_read(cob_file *f, int next, int key_index);
int cob_write(cob_file *f, size_t recsize, int adv_when, int adv_lines);
int cob_rewrite(cob_file *f, size_t recsize);
int cob_delete(cob_file *f);
int cob_start(cob_file *f, int op, int key_index, size_t keylen);
int cob_read_lock(cob_file *f, int next, int key_index, int lock);
int cob_unlock(cob_file *f);
int cob_io_retry(cob_file *f, int how, cob_s64 n, cob_s64 *tries, unsigned long long *since);
void cob_unlock_all(void);
void cob_io_unhandled(cob_file *f, int rc, const char *loc);
#define COB_ADV_NONE   0
#define COB_ADV_BEFORE 1
#define COB_ADV_AFTER  2
#define COB_ADV_PAGE   (-1)

/* sort */
typedef struct {
	size_t offset;
	size_t size;
	const cob_attr *attr;
	int desc;
} cob_sort_key;
void cob_sort_init(cob_file *sd, int nkeys, const cob_sort_key *keys, int dups);
void cob_sort_using(cob_file *sd, cob_file *in);
void cob_sort_release(cob_file *sd);
void cob_sort_sort(cob_file *sd);
void cob_sort_giving(cob_file *sd, cob_file *out);
int cob_sort_return(cob_file *sd);
void cob_sort_end(cob_file *sd);
void cob_table_sort(unsigned char *base, size_t n, size_t elem, int nkeys, const cob_sort_key *keys);

/* ---------------------------------------------------------------- Report Writer */
enum { COB_RW_RH = 1, COB_RW_PH, COB_RW_CH, COB_RW_DE, COB_RW_CF, COB_RW_PF, COB_RW_RF };
enum { COB_RW_ABS = 1, COB_RW_REL, COB_RW_ABSNP, COB_RW_NP };   /* LINE / NEXT GROUP kinds */
#define COB_RW_MAX_LINES 256

typedef struct {
	short kind;
	short num;
} cob_rw_lspec;

typedef struct {
	int type;                  /* COB_RW_RH ... COB_RW_RF */
	int level;                 /* CH/CF: 0 = FINAL, 1..n = CONTROL data items */
	int nlines;
	const cob_rw_lspec *lines;
	short ng_kind, ng_num;     /* NEXT GROUP */
	int has_decl;              /* USE BEFORE REPORTING */
	int (*present_when)(void); /* PRESENT WHEN: NULL when unconditional */
	int absent;                /* ABSENT WHEN: invert the condition */
	int hdr;                   /* the 01 is a print line of its own, with nothing on it */
} cob_rw_group;

typedef struct cob_report {
	const char *name;
	cob_file *file;
	int pl, h, fd, ld, ft;     /* PAGE LIMIT (0: no PAGE clause), HEADING ... FOOTING */
	int ld_decl, ft_decl;      /* LAST DETAIL / FOOTING actually declared? */
	int fd_decl;               /* FIRST DETAIL declared? */
	int ft_clause;             /* a FOOTING n clause (not a page footing group) */
	int width;                 /* print line width including CODE */
	const unsigned char *code;
	int code_len;
	int ngroups;
	const cob_rw_group *groups;
	int ncontrols;
	cob_field *line_counter;
	cob_field *page_counter;
	int (*fmt)(int group, int line, unsigned char *buf, int gi);  /* 0: line absent */
	void (*sum)(int op, int arg);
	int (*ctl)(int op);
	void (*decl)(int group);
	/* state */
	int initiated, generated, terminating;
	int cur;                   /* the page line cursor (see cobrt_rw.c) */
	int pend_kind, pend_num;   /* a NEXT GROUP waiting for the next group */
	int breaking;              /* control footings are being presented */
	int first_gen;             /* the first GENERATE is running */
	int ending, starting;      /* a page footing / page heading is being presented */
	int heading_due;           /* a page has ended and the next has no heading yet */
	int just_set;              /* a page was started since the last detail line */
	int body_on_page;          /* a body group has printed on this page */
	unsigned char *buf;
	unsigned char *gi;
	int *ch, *cf;
	int rh, ph, pf, rf;
} cob_report;

extern int cob_rw_suppress;
/* set by the runtime for the line being formatted: is this the first detail
   line of a page, and which control level changed for it (0: none) */
extern int cob_rw_new_page;
extern int cob_rw_ctl_change;
void cob_rw_initiate(cob_report *r, const char *loc);
void cob_rw_generate(cob_report *r, int group, const char *loc);
void cob_rw_terminate(cob_report *r, const char *loc);
void cob_rw_justify(unsigned char *p, int size, int mode);

#endif
