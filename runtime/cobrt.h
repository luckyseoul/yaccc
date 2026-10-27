/* cobrt.h - runtime library for the cobolc COBOL compiler */
#ifndef COBRT_H
#define COBRT_H

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef __int128 cob_s128;
typedef unsigned __int128 cob_u128;
typedef long long cob_s64;
typedef unsigned long long cob_u64;

enum cob_type {
	COB_GROUP = 1, COB_ALNUM, COB_ALPHA, COB_ALNUM_EDITED, COB_NUM_DISPLAY,
	COB_NUM_PACKED, COB_NUM_BINARY, COB_NUM_COMP5, COB_NUM_FLOAT, COB_NUM_DOUBLE,
	COB_NUM_EDITED, COB_INDEX, COB_ALL, COB_POINTER
};

#define COB_F_SIGNED       0x01
#define COB_F_SIGN_SEP     0x02
#define COB_F_SIGN_LEAD    0x04
#define COB_F_JUSTIFIED    0x08
#define COB_F_BLANK_ZERO   0x10
#define COB_F_DEC_COMMA    0x20
#define COB_F_BINARY_TRUNC 0x40
#define COB_F_ZERO         0x80   /* COB_ALL: figurative ZERO */

typedef struct {
	unsigned char type;
	unsigned char digits;
	signed char scale;
	unsigned char flags;
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
	return (t >= COB_NUM_DISPLAY && t <= COB_NUM_DOUBLE) || t == COB_INDEX;
}

/* PERFORM stack */
struct cob_frame {
	int perform_through;
	void *return_address;
};
#define COB_STACK_SIZE 512

/* ------------------------------------------------------------ globals */
extern cob_field cob_fig_space, cob_fig_zero, cob_fig_high, cob_fig_low,
	cob_fig_quote, cob_fig_null;
extern const cob_attr cob_attr_alnum, cob_attr_group;
extern cob_field cob_return_code, cob_tally, cob_sort_return_reg;
extern const char *cob_when_compiled;
extern const char *cob_source_name;

/* ------------------------------------------------------------ inline fast paths */
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

static inline void cob_disps_set(unsigned char *p, int n, cob_s64 v)
{
	int neg = v < 0;
	cob_disp_set(p, n, neg ? (cob_u64)(-v) : (cob_u64)v);
	if (neg)
		p[n - 1] = (unsigned char)(p[n - 1] + 0x40);
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
void cob_stop_run(int rc) __attribute__((noreturn));
void cob_fatal(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
void cob_perform_overflow(const char *loc) __attribute__((noreturn));
cob_s64 cob_chk_odo(cob_s64 v, cob_s64 min, cob_s64 max, const char *name, const char *loc);
cob_field *cob_refmod(cob_field *out, const cob_field *f, cob_s64 start, cob_s64 len, int check, const char *loc);
void *cob_malloc(size_t n);

/* ------------------------------------------------------------ decimal */
static inline cob_dec cob_d_lit(cob_s64 v, int scale) { cob_dec d; d.v = v; d.scale = scale; return d; }
static inline cob_dec cob_d_int(cob_s64 v) { cob_dec d; d.v = v; d.scale = 0; return d; }
static inline cob_dec cob_d_err(void) { cob_dec d; d.v = 0; d.scale = COB_DEC_ERR; return d; }
cob_dec cob_d_str(const char *s);
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
int cob_d_set(cob_field *f, cob_dec d, int opt);
cob_s64 cob_d_to_int(cob_dec d);
double cob_d_to_double(cob_dec d);
cob_dec cob_d_from_double(double x);
cob_s64 cob_get_int(const cob_field *f);
void cob_set_int(cob_field *f, cob_s64 v);
cob_field *cob_dec_field(cob_dec d);
cob_field *cob_tmp_field(size_t size, const cob_attr *attr);
int cob_d_to_str(cob_dec d, char *buf, size_t bufsz);

/* ------------------------------------------------------------ move / compare */
void cob_move(const cob_field *src, cob_field *dst);
void cob_move_bytes(const unsigned char *src, size_t n, cob_field *dst);
void cob_move_raw(const cob_field *src, cob_field *dst);
void cob_set_collating(const unsigned short *tbl);
const unsigned short *cob_get_collating(void);
int cob_cmp(const cob_field *a, const cob_field *b);
int cob_cmp_alnum(const unsigned char *a, size_t al, const unsigned char *b, size_t bl);
int cob_is_numeric(const cob_field *f);
int cob_is_alpha(const cob_field *f);
int cob_is_lower(const cob_field *f);
int cob_is_upper(const cob_field *f);
int cob_is_class(const cob_field *f, const unsigned char *table);
size_t cob_field_text(const cob_field *f, unsigned char *buf, size_t bufsz);

/* ------------------------------------------------------------ display / accept */
void cob_display(int dev, const cob_field *f);
void cob_display_lit(int dev, const char *s, size_t n);
void cob_display_dec(int dev, cob_dec d);
void cob_display_end(int dev, int newline);
int cob_accept(cob_field *f);
void cob_accept_date(cob_field *f, int fmt);
void cob_accept_time(cob_field *f);
void cob_accept_cmdline(cob_field *f);
int cob_accept_env(cob_field *f, const cob_field *name);
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
void cob_register_program(const char *name, cob_prog_fn fn, cob_cancel_fn cancel);
void cob_cancel(const cob_field *name);
void cob_cancel_name(const char *name);
cob_prog_fn cob_resolve(const cob_field *name);
cob_prog_fn cob_resolve_name(const char *name);
void cob_call_system(const cob_field *cmd);
int cob_switch_get(int n);
void cob_switch_set(int n, int v);

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
cob_dec cob_fn_numval(const cob_field *f);
cob_dec cob_fn_numval_c(const cob_field *f, const cob_field *cur);
cob_dec cob_fn_test_numval(const cob_field *f);
cob_dec cob_fn_aggregate(int which, int n, const cob_dec *v);
cob_dec cob_fn_annuity(cob_dec rate, cob_dec periods);
cob_dec cob_fn_present_value(int n, const cob_dec *v);
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
cob_field *cob_fn_hex_of(const cob_field *f);
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

typedef struct {
	size_t offset;
	size_t size;
	const cob_attr *attr;
	int dups;
} cob_file_key;

typedef struct cob_irec cob_irec;

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
	/* state */
	int open_mode;
	FILE *fp;
	char path[1024];
	int last_read_ok;
	long last_pos;
	size_t cur_size;
	char stat[2];
	int at_end;
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
} cob_file;

int cob_open(cob_file *f, int mode);
int cob_close(cob_file *f);
int cob_close_opt(cob_file *f, int opt);
void cob_close_quiet(cob_file *f);
int cob_read(cob_file *f, int next, int key_index);
int cob_write(cob_file *f, size_t recsize, int adv_when, int adv_lines);
int cob_rewrite(cob_file *f, size_t recsize);
int cob_delete(cob_file *f);
int cob_start(cob_file *f, int op, int key_index, size_t keylen);
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
} cob_rw_group;

typedef struct cob_report {
	const char *name;
	cob_file *file;
	int pl, h, fd, ld, ft;     /* PAGE LIMIT (0: no PAGE clause), HEADING ... FOOTING */
	int width;                 /* print line width including CODE */
	const unsigned char *code;
	int code_len;
	int ngroups;
	const cob_rw_group *groups;
	int ncontrols;
	cob_field *line_counter;
	cob_field *page_counter;
	void (*fmt)(int group, int line, unsigned char *buf, int gi);
	void (*sum)(int op, int arg);
	int (*ctl)(int op);
	void (*decl)(int group);
	/* state */
	int initiated, generated, terminating;
	int page_start, pos, open;
	int next_page, body_on_page;
	unsigned char *buf;
	unsigned char *gi;
	int *ch, *cf;
	int rh, ph, pf, rf;
} cob_report;

extern int cob_rw_suppress;
void cob_rw_initiate(cob_report *r, const char *loc);
void cob_rw_generate(cob_report *r, int group, const char *loc);
void cob_rw_terminate(cob_report *r, const char *loc);

#endif
