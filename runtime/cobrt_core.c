/* SPDX-License-Identifier: MIT */
/* cobrt_core.c - core runtime: decimal arithmetic, field access, MOVE,
 * comparison, editing, DISPLAY/ACCEPT, CALL registry. */
#include "cobrt.h"
#include <stdarg.h>
#include <ctype.h>
#include <math.h>
#include <time.h>
#include <unistd.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <strings.h>

/* ================================================================ globals */

const cob_attr cob_attr_alnum = { COB_ALNUM, 0, 0, 0, NULL, 0 };
const cob_attr cob_attr_group = { COB_GROUP, 0, 0, 0, NULL, 0 };
static const cob_attr attr_all = { COB_ALL, 0, 0, 0, NULL, 0 };
static const cob_attr attr_all_zero = { COB_ALL, 0, 0, COB_F_ZERO, NULL, 0 };

cob_field cob_fig_space = { 1, (unsigned char *)" ", &attr_all };
cob_field cob_fig_zero = { 1, (unsigned char *)"0", &attr_all_zero };
cob_field cob_fig_high = { 1, (unsigned char *)"\xff", &attr_all };
cob_field cob_fig_low = { 1, (unsigned char *)"", &attr_all };
cob_field cob_fig_quote = { 1, (unsigned char *)"\"", &attr_all };
cob_field cob_fig_null = { 1, (unsigned char *)"", &attr_all };

static unsigned char rc_data[4];
static const cob_attr attr_rc = { COB_NUM_BINARY, 9, 0, COB_F_SIGNED | COB_F_BINARY_TRUNC, NULL, 0 };
cob_field cob_return_code = { 4, rc_data, &attr_rc };
static unsigned char tally_data[4];
static const cob_attr attr_tally = { COB_NUM_BINARY, 5, 0, COB_F_BINARY_TRUNC, NULL, 0 };
cob_field cob_tally = { 4, tally_data, &attr_tally };
static unsigned char sortret_data[4];
static const cob_attr attr_sortret = { COB_NUM_BINARY, 4, 0, COB_F_SIGNED | COB_F_BINARY_TRUNC, NULL, 0 };
cob_field cob_sort_return_reg = { 4, sortret_data, &attr_sortret };

static int g_argc;
static char **g_argv;
static int g_arg_index = 1;
static cob_s128 P10[40];

extern void cob_close_all_files(void);

__attribute__((constructor)) static void init_pow10(void)
{
	P10[0] = 1;
	for (int i = 1; i < 39; i++)
		P10[i] = P10[i - 1] * 10;
	P10[39] = P10[38];   /* sentinel, never used for arithmetic */
}

void cob_init(int argc, char **argv)
{
	g_argc = argc;
	g_argv = argv;
	if (!isatty(1))
		setvbuf(stdout, NULL, _IOFBF, 1 << 16);
}

void cob_stop_run(int rc)
{
	fflush(stdout);
	cob_close_all_files();
	fflush(stdout);
	fflush(stderr);
	exit(rc & 0xff);
}

void cob_fatal(const char *fmt, ...)
{
	va_list ap;
	fflush(stdout);
	fprintf(stderr, "cobrt: runtime error: ");
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
	cob_close_all_files();
	fflush(stdout);
	exit(1);
}

void cob_perform_overflow(const char *loc)
{
	cob_fatal("%s: PERFORM stack overflow (recursive PERFORM?)", loc);
}

void *cob_malloc(size_t n)
{
	void *p = calloc(1, n ? n : 1);
	if (!p)
		cob_fatal("out of memory");
	return p;
}

void cob_sub_error(cob_s64 v, cob_s64 max, const char *name, const char *loc)
{
	cob_fatal("%s: subscript of '%s' out of bounds: %lld (maximum %lld)", loc, name, v, max);
}

/* a subscript of a table whose upper bound is OCCURS DEPENDING ON: the count
 * is the current value of the DEPENDING item, and the subscript must be within
 * 1..count, where count itself must be within the declared minimum..maximum */
cob_s64 cob_chk_odo_sub(cob_s64 sub, const cob_field *dep, cob_s64 dmin, cob_s64 dmax,
                        const char *name, const char *loc)
{
	cob_s64 n = cob_get_int(dep);
	if (n < dmin || n > dmax)
		cob_fatal("%s: OCCURS DEPENDING ON value of '%s' out of bounds: %lld "
		          "(minimum %lld, maximum %lld)", loc, name, (long long)n,
		          (long long)dmin, (long long)dmax);
	if (sub < 1 || sub > n) {
		/* GnuCOBOL's wording for the current (not declared) maximum */
		fflush(stdout);
		fprintf(stderr, "libcob: %s: error: subscript of '%s' out of bounds: %lld\n"
		        "note: current maximum subscript for '%s': %lld\n",
		        loc, name, (long long)sub, name, (long long)n);
		cob_close_all_files();
		exit(1);
	}
	return sub;
}

cob_s64 cob_chk_odo(cob_s64 v, cob_s64 min, cob_s64 max, const char *name, const char *loc)
{
	if (v < min || v > max)
		cob_fatal("%s: OCCURS DEPENDING ON value of '%s' out of range: %lld", loc, name, v);
	return v;
}

cob_field *cob_refmod(cob_field *out, const cob_field *f, cob_s64 start, cob_s64 len, int check, const char *loc)
{
	cob_s64 size = (cob_s64)f->size;
	if (len < 0)
		len = size - start + 1;
	if (check && (start < 1 || start > size || len < 1 || start + len - 1 > size))
		cob_fatal("%s: reference modification out of bounds: (%lld:%lld) for length %lld",
			  loc, start, len, size);
	if (start < 1)
		start = 1;
	if (start > size) {
		start = size;
		len = 0;
	}
	if (len < 0)
		len = 0;
	if (start + len - 1 > size)
		len = size - start + 1;
	out->data = f->data + (start - 1);
	out->size = (size_t)len;
	out->attr = &cob_attr_alnum;
	return out;
}

/* ================================================================ temp fields */

#define TMP_RING 64
static struct {
	cob_field f;
	cob_attr a;
	unsigned char *buf;
	size_t cap;
} tmp_ring[TMP_RING];
static int tmp_idx;

cob_field *cob_tmp_field(size_t size, const cob_attr *attr)
{
	int i = tmp_idx;
	tmp_idx = (tmp_idx + 1) % TMP_RING;
	if (tmp_ring[i].cap < size + 1) {
		free(tmp_ring[i].buf);
		tmp_ring[i].cap = size + 64;
		tmp_ring[i].buf = cob_malloc(tmp_ring[i].cap);
	}
	tmp_ring[i].a = attr ? *attr : cob_attr_alnum;
	tmp_ring[i].f.size = size;
	tmp_ring[i].f.data = tmp_ring[i].buf;
	tmp_ring[i].f.attr = &tmp_ring[i].a;
	memset(tmp_ring[i].buf, ' ', size);
	return &tmp_ring[i].f;
}

/* ================================================================ decimal helpers */

static inline cob_u128 uabs(cob_s128 v)
{
	return v < 0 ? -(cob_u128)v : (cob_u128)v;
}

static int ndigits(cob_s128 v)
{
	cob_u128 u = uabs(v);
	int n = 1;
	while (n <= 38 && u >= (cob_u128)P10[n])
		n++;
	return n;
}

static void dnorm(cob_dec *d)
{
	if (d->v == 0) {
		d->scale = d->scale > 0 ? 0 : d->scale;
		if (d->scale < 0)
			d->scale = 0;
		return;
	}
	while (d->scale > 0 && d->v % 10 == 0) {
		d->v /= 10;
		d->scale--;
	}
}

/* limit scale to 38 */
static void dclamp(cob_dec *d)
{
	if (d->scale > 38) {
		int k = d->scale - 38;
		d->v = k > 38 ? 0 : d->v / P10[k];
		d->scale = 38;
	}
}

/* bring a and b to the same scale, losing low-order digits if needed */
static void dalign(cob_dec *a, cob_dec *b)
{
	cob_dec *lo, *hi;
	if (a->scale == b->scale)
		return;
	if (a->scale < b->scale) {
		lo = a;
		hi = b;
	} else {
		lo = b;
		hi = a;
	}
	int k = hi->scale - lo->scale;
	int room = 37 - ndigits(lo->v);
	if (lo->v == 0) {
		lo->scale = hi->scale;
		return;
	}
	if (k <= room) {
		lo->v *= P10[k];
		lo->scale = hi->scale;
		return;
	}
	/* scale lo up as far as possible, truncate hi down to match */
	if (room > 0) {
		lo->v *= P10[room];
		lo->scale += room;
	}
	int drop = hi->scale - lo->scale;
	hi->v = drop > 38 ? 0 : hi->v / P10[drop];
	hi->scale = lo->scale;
}

cob_dec cob_d_add_slow(cob_dec a, cob_dec b)
{
	cob_dec r;
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return cob_d_err();
	dalign(&a, &b);
	while (__builtin_add_overflow(a.v, b.v, &r.v)) {
		if (a.scale <= -38)
			return cob_d_err();
		a.v /= 10;
		b.v /= 10;
		a.scale--;
		b.scale--;
	}
	r.scale = a.scale;
	return r;
}

cob_dec cob_d_neg(cob_dec a)
{
	if (a.scale != COB_DEC_ERR)
		a.v = -a.v;
	return a;
}

cob_dec cob_d_mul(cob_dec a, cob_dec b)
{
	cob_dec r;
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return cob_d_err();
	if (a.v == 0 || b.v == 0)
		return cob_d_int(0);
	while (ndigits(a.v) + ndigits(b.v) > 38 || __builtin_mul_overflow(a.v, b.v, &r.v)) {
		if (a.scale <= 0 && b.scale <= 0)
			return cob_d_err();
		if (a.scale >= b.scale) {
			a.v /= 10;
			a.scale--;
		} else {
			b.v /= 10;
			b.scale--;
		}
		if (a.v == 0 || b.v == 0)
			return cob_d_int(0);
	}
	r.scale = a.scale + b.scale;
	dclamp(&r);
	return r;
}

int cob_zero_div_seen;        /* set by cob_d_div, cleared per statement */

cob_dec cob_d_div(cob_dec a, cob_dec b)
{
	cob_dec r;
	if (a.scale != COB_DEC_ERR && b.scale != COB_DEC_ERR && b.v == 0)
		cob_zero_div_seen = 1;
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR || b.v == 0)
		return cob_d_err();
	if (a.v == 0)
		return cob_d_int(0);
	dnorm(&b);
	int shift = 37 - ndigits(a.v);
	if (shift < 0)
		shift = 0;
	cob_s128 av = a.v * P10[shift];
	r.v = av / b.v;
	r.scale = a.scale + shift - b.scale;
	if (r.scale < 0) {
		/* very large quotient: scale up if it fits */
		int k = -r.scale;
		if (ndigits(r.v) + k > 38)
			return cob_d_err();
		r.v *= P10[k];
		r.scale = 0;
	}
	dclamp(&r);
	dnorm(&r);
	return r;
}

cob_dec cob_d_trunc(cob_dec a, int scale)
{
	if (a.scale == COB_DEC_ERR)
		return a;
	if (a.scale > scale) {
		int k = a.scale - scale;
		a.v = k > 38 ? 0 : a.v / P10[k];
		a.scale = scale;
	}
	return a;
}

static long double d_to_ld(cob_dec d)
{
	long double x = (long double)d.v;
	if (d.scale > 0)
		x /= powl(10.0L, d.scale);
	else if (d.scale < 0)
		x *= powl(10.0L, -d.scale);
	return x;
}

static cob_dec d_from_ld(long double x, int sig)
{
	char buf[128];
	if (isnan(x) || isinf(x))
		return cob_d_err();
	snprintf(buf, sizeof buf, "%.*Le", sig - 1, x);
	/* parse mantissa and exponent */
	char *e = strchr(buf, 'e');
	int expo = e ? atoi(e + 1) : 0;
	if (e)
		*e = 0;
	cob_s128 v = 0;
	int neg = 0, frac = 0, after = 0;
	for (char *p = buf; *p; p++) {
		if (*p == '-')
			neg = 1;
		else if (*p == '.')
			after = 1;
		else if (isdigit((unsigned char)*p)) {
			v = v * 10 + (*p - '0');
			if (after)
				frac++;
		}
	}
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = frac - expo;
	if (r.scale < 0) {
		int k = -r.scale;
		if (ndigits(r.v) + k > 38)
			return cob_d_err();
		r.v *= P10[k];
		r.scale = 0;
	}
	dclamp(&r);
	dnorm(&r);
	return r;
}

double cob_d_to_double(cob_dec d)
{
	return (double)d_to_ld(d);
}

cob_dec cob_d_from_double(double x)
{
	return d_from_ld((long double)x, 15);
}

/* the binary value itself, to 38 significant digits */
cob_dec cob_d_from_double_exact(double x)
{
	return d_from_ld((long double)x, 38);
}

cob_dec cob_d_pow(cob_dec a, cob_dec b)
{
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return cob_d_err();
	dnorm(&b);
	if (b.scale <= 0 && ndigits(b.v) - b.scale <= 6) {
		cob_s64 e = (cob_s64)b.v;
		if (b.scale < 0)
			e *= (cob_s64)P10[-b.scale];
		int neg = e < 0;
		if (neg)
			e = -e;
		if (a.v == 0)
			return neg ? cob_d_err() : (e == 0 ? cob_d_int(1) : cob_d_int(0));
		cob_dec r = cob_d_int(1), base = a;
		while (e > 0) {
			if (e & 1) {
				r = cob_d_mul(r, base);
				if (r.scale == COB_DEC_ERR)
					return r;
			}
			e >>= 1;
			if (e) {
				base = cob_d_mul(base, base);
				if (base.scale == COB_DEC_ERR)
					return base;
			}
		}
		if (neg)
			r = cob_d_div(cob_d_int(1), r);
		return r;
	}
	return cob_hp_pow(a, b);
}

int cob_d_sign(cob_dec a)
{
	return a.v < 0 ? -1 : (a.v > 0 ? 1 : 0);
}

int cob_d_cmp_slow(cob_dec a, cob_dec b)
{
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return 0;
	if (a.scale == b.scale)
		return a.v < b.v ? -1 : (a.v > b.v ? 1 : 0);
	int sa = cob_d_sign(a), sb = cob_d_sign(b);
	if (sa != sb)
		return sa < sb ? -1 : 1;
	if (sa == 0)
		return 0;
	/* same sign, different scales */
	cob_dec lo = a.scale < b.scale ? a : b;
	cob_dec hi = a.scale < b.scale ? b : a;
	int k = hi.scale - lo.scale;
	if (ndigits(lo.v) + k <= 38) {
		cob_s128 x = lo.v * P10[k];
		int c = x < hi.v ? -1 : (x > hi.v ? 1 : 0);
		return a.scale < b.scale ? c : -c;
	}
	/* magnitudes too far apart for exact scaling: compare approximately */
	{
		long double x = d_to_ld(a), y = d_to_ld(b);
		return x < y ? -1 : (x > y ? 1 : 0);
	}
}

cob_dec cob_d_str(const char *s)
{
	cob_dec r = { 0, 0 };
	int neg = 0, after = 0;
	for (; *s; s++) {
		if (*s == '-')
			neg = 1;
		else if (*s == '.')
			after = 1;
		else if (isdigit((unsigned char)*s)) {
			r.v = r.v * 10 + (*s - '0');
			if (after)
				r.scale++;
		}
	}
	if (neg)
		r.v = -r.v;
	return r;
}

/* round/truncate v (scale from) to scale to. opt: COB_ROUNDED and a
 * COB_RM_* rounding mode. Sets *ovf bit 1 on overflow, bit 2 when
 * ROUNDED MODE PROHIBITED meets digits that would be lost. */
static cob_s128 rescale(cob_s128 v, int from, int to, int opt, int *ovf)
{
	if (from == to)
		return v;
	if (from < to) {
		int k = to - from;
		if (v == 0)
			return 0;
		if (k > 38 || ndigits(v) + k > 38) {
			*ovf = 1;
			return 0;
		}
		return v * P10[k];
	}
	int k = from - to;
	if (k > 38) {
		return 0;
	}
	cob_s128 p = P10[k];
	cob_s128 q = v / p;
	if (opt & COB_ROUNDED) {
		cob_s128 r = v % p;
		if (r < 0)
			r = -r;
		if (r) {
			int inc = 0;
			switch (opt & 0xF0) {
			case 0:                 inc = r >= p - r; break;          /* NEAREST-AWAY-FROM-ZERO */
			case COB_RM_AWAY:       inc = 1; break;
			case COB_RM_EVEN:       inc = r > p - r || (r == p - r && (q & 1)); break;
			case COB_RM_TOWARD0:    inc = r > p - r; break;
			case COB_RM_GREATER:    inc = v > 0; break;
			case COB_RM_LESSER:     inc = v < 0; break;
			case COB_RM_PROHIBITED: *ovf |= 2; break;
			}
			if (inc)
				q += (v < 0) ? -1 : 1;
		}
	}
	return q;
}

/* ================================================================ field access */

static int sign_char_neg(unsigned char c, unsigned char *digit)
{
	if (c >= '0' && c <= '9') {
		*digit = c - '0';
		return 0;
	}
	if (c >= 0x70 && c <= 0x79) {
		*digit = c - 0x70;
		return 1;
	}
	if (c == '{') {
		*digit = 0;
		return 0;
	}
	if (c >= 'A' && c <= 'I') {
		*digit = c - 'A' + 1;
		return 0;
	}
	if (c == '}') {
		*digit = 0;
		return 1;
	}
	if (c >= 'J' && c <= 'R') {
		*digit = c - 'J' + 1;
		return 1;
	}
	*digit = c & 0x0F;
	return 0;
}

static cob_dec get_display(const cob_field *f)
{
	const cob_attr *a = f->attr;
	const unsigned char *p = f->data;
	size_t n = f->size;
	int neg = 0;
	cob_s128 v = 0;
	if (a->flags & COB_F_SIGNED) {
		if (a->flags & COB_F_SIGN_SEP) {
			if (a->flags & COB_F_SIGN_LEAD) {
				neg = (*p == '-');
				p++;
			} else
				neg = (p[n - 1] == '-');
			n--;
			for (size_t i = 0; i < n; i++)
				v = v * 10 + (p[i] & 0x0F);
		} else {
			size_t spos = (a->flags & COB_F_SIGN_LEAD) ? 0 : n - 1;
			for (size_t i = 0; i < n; i++) {
				unsigned char c = p[i], d;
				if (i == spos) {
					neg = sign_char_neg(c, &d);
					v = v * 10 + d;
				} else
					v = v * 10 + (c & 0x0F);
			}
		}
	} else {
		for (size_t i = 0; i < n; i++)
			v = v * 10 + (p[i] & 0x0F);
	}
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = a->scale;
	return r;
}

static cob_dec get_packed(const cob_field *f)
{
	const unsigned char *p = f->data;
	size_t n = f->size;
	cob_s128 v = 0;
	cob_dec r;
	if (f->attr->flags & COB_F_UNSIGNED_PACKED) {
		/* COMP-6: every nibble is a digit, and there is no sign */
		for (size_t i = 0; i < n; i++) {
			unsigned char hi = p[i] >> 4, lo = p[i] & 0x0F;
			v = v * 10 + (hi > 9 ? 0 : hi);
			v = v * 10 + (lo > 9 ? 0 : lo);
		}
		r.v = v;
		r.scale = f->attr->scale;
		return r;
	}
	for (size_t i = 0; i < n; i++) {
		unsigned char hi = p[i] >> 4, lo = p[i] & 0x0F;
		v = v * 10 + (hi > 9 ? 0 : hi);
		if (i < n - 1)
			v = v * 10 + (lo > 9 ? 0 : lo);
	}
	unsigned char s = p[n - 1] & 0x0F;
	r.v = (s == 0x0D || s == 0x0B) ? -v : v;
	r.scale = f->attr->scale;
	return r;
}

static cob_s128 get_binary_raw(const cob_field *f, int bigendian, int is_signed)
{
	const unsigned char *p = f->data;
	size_t n = f->size;
	cob_u128 u = 0;
	if (bigendian) {
		for (size_t i = 0; i < n; i++)
			u = (u << 8) | p[i];
	} else {
		for (size_t i = n; i > 0; i--)
			u = (u << 8) | p[i - 1];
	}
	if (is_signed && n < 16 && (u >> (n * 8 - 1)) & 1)
		u |= ~(cob_u128)0 << (n * 8);
	return (cob_s128)u;
}

static void put_binary_raw(cob_field *f, cob_s128 v, int bigendian)
{
	unsigned char *p = f->data;
	size_t n = f->size;
	cob_u128 u = (cob_u128)v;
	if (bigendian) {
		for (size_t i = n; i > 0; i--) {
			p[i - 1] = (unsigned char)(u & 0xFF);
			u >>= 8;
		}
	} else {
		for (size_t i = 0; i < n; i++) {
			p[i] = (unsigned char)(u & 0xFF);
			u >>= 8;
		}
	}
}

static cob_dec deedit(const cob_field *f);
static cob_dec parse_alnum(const unsigned char *s, size_t n, int dec_comma);

cob_dec cob_d_get(const cob_field *f)
{
	cob_dec r;
	switch (f->attr->type) {
	case COB_NUM_DISPLAY:
		return get_display(f);
	case COB_NUM_PACKED:
		return get_packed(f);
	case COB_NUM_BINARY:
		r.v = get_binary_raw(f, 1, f->attr->flags & COB_F_SIGNED);
		r.scale = f->attr->scale;
		return r;
	case COB_NUM_COMP5:
		r.v = get_binary_raw(f, 0, f->attr->flags & COB_F_SIGNED);
		r.scale = f->attr->scale;
		return r;
	case COB_INDEX: {
		int32_t x;
		memcpy(&x, f->data, 4);
		return cob_d_int(x);
	}
	case COB_POINTER: {
		intptr_t x;
		memcpy(&x, f->data, sizeof x);
		return cob_d_int((cob_s64)x);
	}
	case COB_NUM_FLOAT: {
		float x;
		memcpy(&x, f->data, 4);
		return d_from_ld(x, 7);
	}
	case COB_NUM_DOUBLE: {
		double x;
		memcpy(&x, f->data, 8);
		return d_from_ld(x, 15);
	}
	case COB_NUM_EDITED:
		return deedit(f);
	case COB_ALL:
		if (f->attr->flags & COB_F_ZERO)
			return cob_d_int(0);
		return parse_alnum(f->data, f->size, 0);
	default:
		return parse_alnum(f->data, f->size, 0);
	}
}

cob_s64 cob_get_int(const cob_field *f)
{
	switch (f->attr->type) {
	case COB_INDEX: {
		int32_t x;
		memcpy(&x, f->data, 4);
		return x;
	}
	case COB_NUM_DISPLAY:
		if (f->attr->scale == 0 && !(f->attr->flags & COB_F_SIGNED) && f->size <= 18) {
			cob_s64 v = 0;
			for (size_t i = 0; i < f->size; i++)
				v = v * 10 + (f->data[i] & 0x0F);
			return v;
		}
		break;
	default:
		break;
	}
	return cob_d_to_int(cob_d_get(f));
}

cob_s64 cob_disps_get_slow(const unsigned char *p, int n)
{
	static const cob_attr a = { COB_NUM_DISPLAY, 18, 0, COB_F_SIGNED, NULL, 0 };
	cob_field f = { (size_t)n, (unsigned char *)p, &a };
	return cob_d_to_int(get_display(&f));
}

cob_s64 cob_d_to_int(cob_dec d)
{
	if (d.scale == COB_DEC_ERR)
		return 0;
	if (d.scale > 0)
		d.v = d.scale > 38 ? 0 : d.v / P10[d.scale];
	else if (d.scale < 0)
		d.v *= P10[-d.scale];
	return (cob_s64)d.v;
}

void cob_set_int(cob_field *f, cob_s64 v)
{
	if (f->attr->type == COB_INDEX) {
		int32_t x = (int32_t)v;
		memcpy(f->data, &x, 4);
		return;
	}
	cob_d_set(f, cob_d_int(v), 0);
}

static void edit_numeric(cob_field *f, cob_dec d);

static void put_display(cob_field *f, cob_s128 v)
{
	const cob_attr *a = f->attr;
	unsigned char *p = f->data;
	size_t n = f->size;
	int neg = v < 0;
	cob_u128 u = uabs(v);
	int sep = (a->flags & COB_F_SIGNED) && (a->flags & COB_F_SIGN_SEP);
	int lead = a->flags & COB_F_SIGN_LEAD;
	unsigned char *dp = p;
	size_t dn = n;
	if (sep) {
		dn--;
		if (lead)
			dp++;
	}
	for (size_t i = dn; i > 0; i--) {
		dp[i - 1] = (unsigned char)('0' + (int)(u % 10));
		u /= 10;
	}
	if (a->flags & COB_F_SIGNED) {
		if (sep) {
			if (lead)
				p[0] = neg ? '-' : '+';
			else
				p[n - 1] = neg ? '-' : '+';
		} else if (neg) {
			size_t spos = lead ? 0 : n - 1;
			p[spos] = (unsigned char)(p[spos] + 0x40);
		}
	}
}

static void put_packed(cob_field *f, cob_s128 v)
{
	unsigned char *p = f->data;
	size_t n = f->size;
	int neg = v < 0;
	cob_u128 u = uabs(v);
	if (f->attr->flags & COB_F_UNSIGNED_PACKED) {
		/* COMP-6: two digits per byte, no sign nibble */
		for (size_t i = n; i > 0; i--) {
			unsigned char lo = (unsigned char)(u % 10);
			u /= 10;
			unsigned char hi = (unsigned char)(u % 10);
			u /= 10;
			p[i - 1] = (unsigned char)((hi << 4) | lo);
		}
		return;
	}
	unsigned char sign = (f->attr->flags & COB_F_SIGNED) ? (neg ? 0x0D : 0x0C) : 0x0F;
	memset(p, 0, n);
	p[n - 1] = sign | (unsigned char)((u % 10) << 4);
	u /= 10;
	for (size_t i = n - 1; i > 0; i--) {
		unsigned char lo = (unsigned char)(u % 10);
		u /= 10;
		unsigned char hi = (unsigned char)(u % 10);
		u /= 10;
		p[i - 1] = (unsigned char)((hi << 4) | lo);
	}
	/* digits even: leading pad nibble must be zero */
	if ((f->attr->digits % 2) == 0 && n > 0)
		p[0] &= 0x0F;
}

int cob_d_set(cob_field *f, cob_dec d, int opt)
{
	const cob_attr *a = f->attr;
	if (d.scale == COB_DEC_ERR)
		return 1;
	int ovf = 0;
	cob_s128 v;
	switch (a->type) {
	case COB_NUM_DISPLAY:
	case COB_NUM_PACKED:
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_INDEX: {
		/* COB_SIZE_REPORT: the value is stored truncated, as without a size
		 * check, but the overflow is reported so the exception can be raised */
		int report = 0;
		if (d.scale < a->scale && !(opt & (COB_SIZE_CHECK | COB_SIZE_REPORT))) {
			/* drop the high-order digits no item can hold before scaling up */
			int k = a->scale - d.scale;
			if (k < 38 && ndigits(d.v) + k > 38)
				d.v %= P10[38 - k];
		}
		v = rescale(d.v, d.scale, a->scale, opt, &ovf);
		if (ovf) {
			if (opt & COB_SIZE_CHECK)
				return 1;
			report = 1;
			if (ovf & 1)
				v = 0;
		}
		if (!(a->flags & COB_F_SIGNED) && a->type != COB_INDEX && v < 0)
			v = -v;
		if (a->type == COB_NUM_COMP5 || a->type == COB_INDEX) {
			size_t n = a->type == COB_INDEX ? 4 : f->size;
			cob_s128 lim;
			int sgn = a->type == COB_INDEX || (a->flags & COB_F_SIGNED);
			if (n >= 16) {
				lim = 0;
			} else {
				lim = (cob_s128)1 << (n * 8 - (sgn ? 1 : 0));
			}
			if (lim && ((sgn && (v >= lim || v < -lim)) || (!sgn && v >= lim))) {
				if (opt & COB_SIZE_CHECK)
					return 1;
				report = 1;
			}
			if (a->type == COB_INDEX) {
				int32_t x = (int32_t)v;
				memcpy(f->data, &x, 4);
			} else
				put_binary_raw(f, v, 0);
			return 0;
		}
		int digits = a->digits;
		if (digits < 38 && (v >= P10[digits] || v <= -P10[digits])) {
			if (opt & COB_SIZE_CHECK)
				return 1;
			report = 1;
			if (a->type != COB_NUM_BINARY || (a->flags & COB_F_BINARY_TRUNC))
				v = v % P10[digits];
		}
		if (a->type == COB_NUM_DISPLAY)
			put_display(f, v);
		else if (a->type == COB_NUM_PACKED)
			put_packed(f, v);
		else
			put_binary_raw(f, v, 1);
		return report;
	}
	case COB_NUM_FLOAT: {
		float x = (float)d_to_ld(d);
		memcpy(f->data, &x, 4);
		return 0;
	}
	case COB_NUM_DOUBLE: {
		double x = (double)d_to_ld(d);
		memcpy(f->data, &x, 8);
		return 0;
	}
	case COB_NUM_EDITED: {
		if (opt & (COB_ROUNDED | COB_SIZE_CHECK)) {
			/* rounding / size check against the edited digits */
			int sc = a->scale;
			v = rescale(d.v, d.scale, sc, opt, &ovf);
			if (ovf || (a->digits < 38 && (v >= P10[a->digits] || v <= -P10[a->digits]))) {
				if (opt & COB_SIZE_CHECK)
					return 1;
			}
			d.v = v;
			d.scale = sc;
		}
		edit_numeric(f, d);
		return 0;
	}
	default: {
		/* numeric value to alphanumeric: digits of the value */
		char buf[96];
		cob_dec t = d;
		if (t.v < 0)
			t.v = -t.v;
		if (t.scale < 0) {
			t.v *= P10[-t.scale];
			t.scale = 0;
		}
		cob_u128 u = (cob_u128)t.v;
		int len = 0;
		char tmp[64];
		do {
			tmp[len++] = (char)('0' + (int)(u % 10));
			u /= 10;
		} while (u);
		while (len < t.scale + 1)
			tmp[len++] = '0';
		for (int i = 0; i < len; i++)
			buf[i] = tmp[len - 1 - i];
		cob_move_bytes((unsigned char *)buf, (size_t)len, f);
		return 0;
	}
	}
}

/* temporary numeric field holding a decimal value */
cob_field *cob_dec_field(cob_dec d)
{
	cob_attr at = { COB_NUM_DISPLAY, 0, 0, COB_F_SIGNED, NULL, 0 };
	if (d.scale == COB_DEC_ERR)
		d = cob_d_int(0);
	if (d.scale < 0) {
		d.v *= P10[-d.scale];
		d.scale = 0;
	}
	int nd = ndigits(d.v);
	if (nd < d.scale + 1)
		nd = d.scale + 1;
	if (nd > 38)
		nd = 38;
	at.digits = (unsigned char)nd;
	at.scale = (signed char)d.scale;
	cob_field *f = cob_tmp_field((size_t)nd, &at);
	cob_d_set(f, d, 0);
	return f;
}

/* The data item that holds a numeric function result, typed as GnuCOBOL
   types it: unsigned unless the value is negative (or force_sign), 9 digits
   when the value fits 32 bits with fewer than 10 decimals, 20 digits when it
   fits 64 bits with fewer than 19, otherwise as many digits as the value has.
   digits > 0 asks for that many instead (DATE-OF-INTEGER: 8), digits < 0 for
   just the digits of the value (a constant LENGTH). */
static cob_field *fn_field(cob_dec d, int flags, int digits, int force_sign)
{
	if (d.scale == COB_DEC_ERR)
		d = cob_d_int(0);
	if (d.scale < 0) {
		d.v *= P10[-d.scale];
		d.scale = 0;
	}
	dnorm(&d);
	int neg = d.v < 0;
	int sgn = neg || force_sign;
	cob_u128 u = uabs(d.v);
	int bits = 0;
	for (cob_u128 t = u; t; t >>= 1)
		bits++;
	if (digits < 0)
		digits = 1;
	else if (digits == 0) {
		if (bits < 33 - sgn && d.scale < 10)
			digits = 9;
		else if (bits < 65 - sgn && d.scale < 19)
			digits = 20;
		else
			digits = (int)floor(bits * 0.30102999566398119521) + 1;
	}
	int nd = ndigits(d.v);
	if (digits < nd)
		digits = nd;
	if (digits < d.scale)
		digits = d.scale;
	cob_attr at = { COB_NUM_DISPLAY, (unsigned char)digits, (signed char)d.scale,
			(unsigned char)((sgn ? COB_F_SIGNED | COB_F_SIGN_SEP | COB_F_SIGN_LEAD : 0) | flags),
			NULL, 0 };
	cob_field *f = cob_tmp_field((size_t)(digits + sgn), &at);
	cob_d_set(f, d, 0);
	return f;
}

cob_field *cob_fn_field(cob_dec d, int flags, int digits)
{
	return fn_field(d, flags, digits, 0);
}

/* ABS of an expression: the item the expression's value would get, signed
   if the value is negative, holding the absolute value */
cob_field *cob_fn_abs_field(cob_dec d, int flags)
{
	int neg = d.scale != COB_DEC_ERR && d.v < 0;
	if (neg)
		d.v = -d.v;
	return fn_field(d, flags, 0, neg);
}

/* ABS of a data item or literal: a result with the argument's description */
cob_field *cob_fn_model_field(cob_dec d, const cob_field *model)
{
	cob_field *f = cob_tmp_field(model->size, model->attr);
	cob_d_set(f, d, 0);
	return f;
}

/* numeric MAX / MIN: a copy of the first greatest / least argument */
cob_field *cob_fn_minmax_num(int is_max, int n, cob_field **f)
{
	int best = 0;
	for (int i = 1; i < n; i++) {
		int c = cob_d_cmp(cob_d_get(f[i]), cob_d_get(f[best]));
		if ((is_max && c > 0) || (!is_max && c < 0))
			best = i;
	}
	cob_field *r = cob_tmp_field(f[best]->size, f[best]->attr);
	memcpy(r->data, f[best]->data, f[best]->size);
	return r;
}

static int median_cmp(const void *a, const void *b)
{
	return cob_d_cmp(cob_d_get(*(cob_field *const *)a), cob_d_get(*(cob_field *const *)b));
}

/* numeric MEDIAN: the middle argument itself, or the mean of the middle two */
cob_field *cob_fn_median_num(int n, cob_field **f, int flags)
{
	cob_field **c = cob_malloc(sizeof(cob_field *) * (size_t)n);
	memcpy(c, f, sizeof(cob_field *) * (size_t)n);
	qsort(c, (size_t)n, sizeof(cob_field *), median_cmp);
	cob_field *r;
	if (n % 2) {
		cob_field *m = c[n / 2];
		r = cob_tmp_field(m->size, m->attr);
		memcpy(r->data, m->data, m->size);
	} else
		r = fn_field(cob_d_div(cob_d_add(cob_d_get(c[n / 2 - 1]), cob_d_get(c[n / 2])), cob_d_int(2)),
			     flags, 0, 0);
	free(c);
	return r;
}

cob_field *cob_double_field(double x)
{
	static const cob_attr at = { COB_NUM_DOUBLE, 17, 0, COB_F_SIGNED, NULL, 0 };
	cob_field *f = cob_tmp_field(sizeof x, &at);
	memcpy(f->data, &x, sizeof x);
	return f;
}

int cob_d_to_str(cob_dec d, char *buf, size_t bufsz)
{
	/* minimal textual representation: -123.45 */
	char tmp[96];
	int len = 0;
	if (d.scale == COB_DEC_ERR) {
		snprintf(buf, bufsz, "0");
		return 1;
	}
	if (d.scale < 0) {
		d.v *= P10[-d.scale];
		d.scale = 0;
	}
	dnorm(&d);
	int neg = d.v < 0;
	cob_u128 u = uabs(d.v);
	int k = 0;
	do {
		tmp[len++] = (char)('0' + (int)(u % 10));
		u /= 10;
		k++;
		if (k == d.scale)
			tmp[len++] = '.';
	} while (u || k < d.scale);
	if (tmp[len - 1] == '.')
		tmp[len++] = '0';
	if (neg)
		tmp[len++] = '-';
	int o = 0;
	for (int i = len - 1; i >= 0 && o < (int)bufsz - 1; i--)
		buf[o++] = tmp[i];
	buf[o] = 0;
	return o;
}

/* ================================================================ alphanumeric parse */

static cob_dec parse_alnum(const unsigned char *s, size_t n, int dec_comma)
{
	unsigned char dp = dec_comma ? ',' : '.', sep = dec_comma ? '.' : ',';
	size_t i = 0;
	int neg = 0, after = 0, scale = 0, nd = 0;
	cob_s128 v = 0;
	while (i < n && isspace(s[i]))
		i++;
	if (i < n && (s[i] == '+' || s[i] == '-')) {
		neg = s[i] == '-';
		i++;
	}
	for (; i < n; i++) {
		unsigned char c = s[i];
		if (c >= '0' && c <= '9') {
			if (nd < 37) {
				v = v * 10 + (c - '0');
				if (v)
					nd++;
				if (after)
					scale++;
			} else if (!after) {
				v = (v % P10[36]) * 10 + (c - '0');
			}
		} else if (c == dp) {
			if (after)
				break;
			after = 1;
		} else if (c == sep || isspace(c)) {
			continue;
		} else if (c == '-' || c == '+') {
			neg = (c == '-');
			break;
		} else if ((c == 'C' && i + 1 < n && s[i + 1] == 'R') || (c == 'D' && i + 1 < n && s[i + 1] == 'B')) {
			neg = 1;
			break;
		} else
			break;
	}
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = scale;
	return r;
}

/* ================================================================ editing */

static void edit_numeric(cob_field *f, cob_dec d)
{
	const cob_attr *a = f->attr;
	const char *pic = a->pic;
	int dec_comma = a->flags & COB_F_DEC_COMMA;
	char dp = dec_comma ? ',' : '.';
	char sep = dec_comma ? '.' : ',';
	unsigned char cur = a->currency ? a->currency : '$';
	int plen = (int)strlen(pic);
	unsigned char *out = f->data;
	size_t olen = f->size;
	int i, o;

	/* floating insertion symbol */
	char float_ch = 0;
	int float_first = -1;
	for (i = 0; i < plen; i++) {
		char c = pic[i];
		if (c == '$' || c == '+' || c == '-') {
			int cnt = 0;
			for (int j = 0; j < plen; j++)
				if (pic[j] == c)
					cnt++;
			if (cnt >= 2) {
				float_ch = c;
				float_first = i;
				break;
			}
		}
		if (c == '9' || c == 'Z' || c == '*' || c == dp || c == 'V')
			break;
	}
	/* count digit positions */
	int int_pos = 0, frac_pos = 0, seen_point = 0, has_nine = 0, has_star = 0;
	for (i = 0; i < plen; i++) {
		char c = pic[i];
		if (c == 'V' || c == dp) {
			seen_point = 1;
			continue;
		}
		if ((c == 'C' && pic[i + 1] == 'R') || (c == 'D' && pic[i + 1] == 'B')) {
			i++;
			continue;
		}
		int isd = (c == '9' || c == 'Z' || c == '*') || (c == float_ch && i != float_first);
		if (c == '9')
			has_nine = 1;
		if (c == '*')
			has_star = 1;
		if (isd) {
			if (seen_point)
				frac_pos++;
			else
				int_pos++;
		}
	}
	int ndig = int_pos + frac_pos;
	unsigned char dig[80];
	int ovf = 0;
	int escale = (a->scale < 0 || a->scale > frac_pos) ? a->scale : frac_pos;
	cob_s128 v = d.scale == COB_DEC_ERR ? 0 : rescale(d.v, d.scale, escale, 0, &ovf);
	if (ovf)
		v = 0;
	int neg = v < 0;
	cob_u128 u = uabs(v);
	int is_zero = 1;
	for (i = ndig - 1; i >= 0; i--) {
		dig[i] = (unsigned char)(u % 10);
		if (dig[i])
			is_zero = 0;
		u /= 10;
	}
	if (is_zero)
		neg = 0;
	if (is_zero && (a->flags & COB_F_BLANK_ZERO)) {
		memset(out, ' ', olen);
		return;
	}
	int di = 0, significant = 0, suppressing = 0;
	int first_sig = -1;
	unsigned char pad = has_star ? '*' : ' ';
#define MARK_SIG() do { if (first_sig < 0 && float_first >= 0 && i > float_first) first_sig = o; } while (0)
	for (i = 0, o = 0; i < plen && o < (int)olen; i++) {
		char c = pic[i];
		if (c == 'V')
			continue;
		if ((c == 'C' && pic[i + 1] == 'R') || (c == 'D' && pic[i + 1] == 'B')) {
			if (neg) {
				out[o++] = (unsigned char)c;
				if (o < (int)olen)
					out[o++] = (unsigned char)pic[i + 1];
			} else {
				out[o++] = ' ';
				if (o < (int)olen)
					out[o++] = ' ';
			}
			i++;
			continue;
		}
		if (c == float_ch) {
			if (i == float_first) {
				out[o++] = ' ';
				suppressing = 1;
			} else {
				int g = dig[di++];
				if (g || significant) {
					MARK_SIG();
					out[o++] = (unsigned char)('0' + g);
					significant = 1;
				} else {
					out[o++] = ' ';
				}
			}
			continue;
		}
		switch (c) {
		case '9':
			MARK_SIG();
			out[o++] = (unsigned char)('0' + dig[di++]);
			significant = 1;
			break;
		case 'Z':
		case '*': {
			int g = dig[di++];
			if (g || significant) {
				MARK_SIG();
				out[o++] = (unsigned char)('0' + g);
				significant = 1;
			} else {
				out[o++] = c == '*' ? '*' : ' ';
				suppressing = 1;
			}
			break;
		}
		case '+':
		case '-':
			out[o++] = neg ? '-' : (c == '+' ? '+' : ' ');
			break;
		case '$':
			out[o++] = cur;
			break;
		case 'B':
			out[o++] = (!significant && suppressing) ? pad : ' ';
			break;
		case '0':
		case '/':
			out[o++] = (!significant && suppressing) ? pad : (unsigned char)c;
			break;
		default:
			if (c == dp) {
				MARK_SIG();
				out[o++] = (unsigned char)dp;
				if (!is_zero || has_nine)
					significant = 1;
			} else if (c == sep) {
				out[o++] = (!significant && suppressing) ? pad : (unsigned char)sep;
			} else {
				out[o++] = (unsigned char)c;
			}
			break;
		}
	}
#undef MARK_SIG
	while (o < (int)olen)
		out[o++] = ' ';
	if (is_zero && !has_nine) {
		/* all digit positions suppressed and value zero */
		if (has_star) {
			for (o = 0; o < (int)olen; o++)
				if (out[o] != (unsigned char)dp)
					out[o] = '*';
		} else
			memset(out, ' ', olen);
		return;
	}
	if (float_ch) {
		int pos = first_sig >= 0 ? first_sig - 1 : o - 1;
		unsigned char fc;
		if (float_ch == '$')
			fc = cur;
		else if (float_ch == '+')
			fc = neg ? '-' : '+';
		else
			fc = neg ? '-' : ' ';
		if (pos >= 0 && pos < (int)olen)
			out[pos] = fc;
	}
}

static cob_dec deedit(const cob_field *f)
{
	const cob_attr *a = f->attr;
	const char *pic = a->pic;
	int dec_comma = a->flags & COB_F_DEC_COMMA;
	char dp = dec_comma ? ',' : '.';
	int plen = (int)strlen(pic);
	char float_ch = 0;
	int float_first = -1;
	int i, o;
	for (i = 0; i < plen; i++) {
		char c = pic[i];
		if (c == '$' || c == '+' || c == '-') {
			int cnt = 0;
			for (int j = 0; j < plen; j++)
				if (pic[j] == c)
					cnt++;
			if (cnt >= 2) {
				float_ch = c;
				float_first = i;
				break;
			}
		}
		if (c == '9' || c == 'Z' || c == '*' || c == dp || c == 'V')
			break;
	}
	cob_s128 v = 0;
	int scale = 0, after = 0, neg = 0;
	for (i = 0, o = 0; i < plen && o < (int)f->size; i++) {
		char c = pic[i];
		if (c == 'V') {
			after = 1;
			continue;
		}
		unsigned char ch = f->data[o];
		if ((c == 'C' && pic[i + 1] == 'R') || (c == 'D' && pic[i + 1] == 'B')) {
			if (ch == 'C' || ch == 'D')
				neg = 1;
			i++;
			o += 2;
			continue;
		}
		int isd = (c == '9' || c == 'Z' || c == '*') || (c == float_ch && i != float_first);
		if (isd) {
			v = v * 10 + ((ch >= '0' && ch <= '9') ? ch - '0' : 0);
			if (after)
				scale++;
		} else if (c == dp) {
			after = 1;
		}
		if (ch == '-' && (c == '-' || c == '+' || c == float_ch))
			neg = 1;
		o++;
	}
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = (a->scale < 0 || a->scale > scale) ? a->scale : scale;
	return r;
}

/* ================================================================ text view */

/* produce the alphanumeric representation of a field (numeric: unsigned digits) */
size_t cob_field_text(const cob_field *f, unsigned char *buf, size_t bufsz)
{
	const cob_attr *a = f->attr;
	switch (a->type) {
	case COB_NUM_DISPLAY: {
		size_t n = f->size;
		const unsigned char *p = f->data;
		size_t lead0 = 0;
		if ((a->flags & COB_F_SIGNED) && (a->flags & COB_F_SIGN_SEP)) {
			n--;
			if (a->flags & COB_F_SIGN_LEAD)
				p++;
		}
		if (a->scale > (int)n)
			lead0 = (size_t)a->scale - n;
		if (lead0 + n > bufsz)
			n = bufsz - lead0;
		memset(buf, '0', lead0);
		memcpy(buf + lead0, p, n);
		if ((a->flags & COB_F_SIGNED) && !(a->flags & COB_F_SIGN_SEP) && n > 0) {
			size_t spos = lead0 + ((a->flags & COB_F_SIGN_LEAD) ? 0 : n - 1);
			unsigned char d;
			sign_char_neg(buf[spos], &d);
			buf[spos] = '0' + d;
		}
		n += lead0;
		if (a->scale < 0) {
			size_t z = (size_t)(-a->scale);
			if (n + z > bufsz)
				z = bufsz - n;
			memset(buf + n, '0', z);
			n += z;
		}
		return n;
	}
	case COB_NUM_PACKED:
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_INDEX:
	case COB_NUM_FLOAT:
	case COB_NUM_DOUBLE: {
		cob_dec d = cob_d_get(f);
		int digits = a->digits ? a->digits : 18;
		int sc = a->scale;
		int ovf = 0;
		cob_s128 v = rescale(d.v, d.scale, sc, 0, &ovf);
		cob_u128 u = uabs(v);
		size_t n = (size_t)digits;
		if (n > bufsz)
			n = bufsz;
		for (size_t i = n; i > 0; i--) {
			buf[i - 1] = (unsigned char)('0' + (int)(u % 10));
			u /= 10;
		}
		return n;
	}
	default: {
		size_t n = f->size < bufsz ? f->size : bufsz;
		memcpy(buf, f->data, n);
		return n;
	}
	}
}

/* ================================================================ MOVE */

void cob_move_bytes(const unsigned char *src, size_t n, cob_field *dst)
{
	size_t dn = dst->size;
	int t = dst->attr->type;
	if (cob_is_num_type(t) || t == COB_NUM_EDITED) {
		cob_field tmp = { n, (unsigned char *)src, &cob_attr_alnum };
		cob_move(&tmp, dst);
		return;
	}
	if (t == COB_ALNUM_EDITED) {
		cob_field tmp = { n, (unsigned char *)src, &cob_attr_alnum };
		cob_move(&tmp, dst);
		return;
	}
	if ((dst->attr->flags & COB_F_JUSTIFIED) && t != COB_GROUP) {
		if (n >= dn)
			memmove(dst->data, src + (n - dn), dn);
		else {
			memmove(dst->data + (dn - n), src, n);
			memset(dst->data, ' ', dn - n);
		}
		return;
	}
	if (n >= dn)
		memmove(dst->data, src, dn);
	else {
		memmove(dst->data, src, n);
		memset(dst->data + n, ' ', dn - n);
	}
}

static void fill_pattern(unsigned char *d, size_t n, const unsigned char *pat, size_t pn)
{
	if (pn == 0) {
		memset(d, 0, n);
		return;
	}
	if (pn == 1) {
		memset(d, pat[0], n);
		return;
	}
	for (size_t i = 0; i < n; i++)
		d[i] = pat[i % pn];
}

static void edit_alnum(const unsigned char *s, size_t n, cob_field *dst)
{
	const char *pic = dst->attr->pic;
	size_t si = 0;
	size_t o = 0;
	for (const char *p = pic; *p && o < dst->size; p++) {
		char c = *p;
		if (c == 'X' || c == 'A' || c == '9')
			dst->data[o++] = si < n ? s[si++] : ' ';
		else if (c == 'B')
			dst->data[o++] = ' ';
		else
			dst->data[o++] = (unsigned char)c;
	}
	while (o < dst->size)
		dst->data[o++] = ' ';
}

void cob_move(const cob_field *src, cob_field *dst)
{
	int st = src->attr->type, dt = dst->attr->type;
	unsigned char buf[256];
	if (src == dst)
		return;
	if (st == COB_ALL) {
		if ((src->attr->flags & COB_F_ZERO) && (cob_is_num_type(dt) || dt == COB_NUM_EDITED)) {
			cob_d_set(dst, cob_d_int(0), 0);
			return;
		}
		if (dt == COB_ALNUM_EDITED) {
			unsigned char tmp[1024];
			size_t n = dst->size < sizeof tmp ? dst->size : sizeof tmp;
			fill_pattern(tmp, n, src->data, src->size);
			edit_alnum(tmp, n, dst);
			return;
		}
		if (dt == COB_NUM_EDITED || dt == COB_NUM_FLOAT || dt == COB_NUM_DOUBLE) {
			/* only ZERO is meaningful */
			fill_pattern(dst->data, dst->size, src->data, src->size);
			return;
		}
		fill_pattern(dst->data, dst->size, src->data, src->size);
		return;
	}
	if (st == COB_GROUP && dt != COB_GROUP && !cob_is_num_type(dt) && dt != COB_NUM_EDITED) {
		if (dt == COB_ALNUM_EDITED || dt == COB_ALNUM || dt == COB_ALPHA) {
			/* non-elementary move: no editing; JUSTIFIED honoured */
			size_t n = src->size, dn = dst->size;
			if ((dst->attr->flags & COB_F_JUSTIFIED) && n < dn) {
				memmove(dst->data + (dn - n), src->data, n);
				memset(dst->data, ' ', dn - n);
			} else if ((dst->attr->flags & COB_F_JUSTIFIED) && n > dn) {
				memmove(dst->data, src->data + (n - dn), dn);
			} else if (n >= dn) {
				memmove(dst->data, src->data, dn);
			} else {
				memmove(dst->data, src->data, n);
				memset(dst->data + n, ' ', dn - n);
			}
		} else
			cob_move_bytes(src->data, src->size, dst);
		return;
	}
	if (st == COB_GROUP || dt == COB_GROUP) {
		size_t n = src->size;
		const unsigned char *p = src->data;
		if (st != COB_GROUP && cob_is_num_type(st) && st != COB_NUM_DISPLAY) {
			/* binary/packed source into group: raw bytes */
		}
		if (n >= dst->size)
			memmove(dst->data, p, dst->size);
		else {
			memmove(dst->data, p, n);
			memset(dst->data + n, ' ', dst->size - n);
		}
		return;
	}
	if (cob_is_num_type(st)) {
		if (cob_is_num_type(dt) || dt == COB_NUM_EDITED) {
			cob_d_set(dst, cob_d_get(src), 0);
			return;
		}
		size_t n = cob_field_text(src, buf, sizeof buf);
		if (dt == COB_ALNUM_EDITED)
			edit_alnum(buf, n, dst);
		else
			cob_move_bytes(buf, n, dst);
		return;
	}
	if (st == COB_NUM_EDITED) {
		if (cob_is_num_type(dt) || dt == COB_NUM_EDITED) {
			cob_d_set(dst, deedit(src), 0);
			return;
		}
		if (dt == COB_ALNUM_EDITED) {
			edit_alnum(src->data, src->size, dst);
			return;
		}
		cob_move_bytes(src->data, src->size, dst);
		return;
	}
	/* alphanumeric source */
	if (cob_is_num_type(dt) || dt == COB_NUM_EDITED) {
		cob_d_set(dst, parse_alnum(src->data, src->size, dst->attr->flags & COB_F_DEC_COMMA), 0);
		return;
	}
	if (dt == COB_ALNUM_EDITED) {
		edit_alnum(src->data, src->size, dst);
		return;
	}
	cob_move_bytes(src->data, src->size, dst);
}

/* VALUE clause initialisation: bytes are placed without editing or
 * justification (left-justified, space filled) */
void cob_move_raw(const cob_field *src, cob_field *dst)
{
	if (src->attr->type == COB_ALL) {
		fill_pattern(dst->data, dst->size, src->data, src->size);
		return;
	}
	size_t n = src->size < dst->size ? src->size : dst->size;
	memmove(dst->data, src->data, n);
	if (dst->size > n)
		memset(dst->data + n, ' ', dst->size - n);
}

/* ================================================================ compare */

static const unsigned short *coll_tbl;

const unsigned short *cob_get_collating(void)
{
	return coll_tbl;
}

void cob_set_collating(const unsigned short *tbl)
{
	coll_tbl = tbl;
}

static int cmp_coll(const unsigned char *a, size_t al, const unsigned char *b, size_t bl)
{
	size_t n = al > bl ? al : bl;
	for (size_t i = 0; i < n; i++) {
		unsigned wa = coll_tbl[i < al ? a[i] : ' '];
		unsigned wb = coll_tbl[i < bl ? b[i] : ' '];
		if (wa != wb)
			return wa < wb ? -1 : 1;
	}
	return 0;
}

int cob_cmp_alnum(const unsigned char *a, size_t al, const unsigned char *b, size_t bl)
{
	if (coll_tbl)
		return cmp_coll(a, al, b, bl);
	size_t n = al < bl ? al : bl;
	int c = memcmp(a, b, n);
	if (c)
		return c < 0 ? -1 : 1;
	if (al > bl) {
		for (size_t i = n; i < al; i++)
			if (a[i] != ' ')
				return a[i] < ' ' ? -1 : 1;
	} else if (bl > al) {
		for (size_t i = n; i < bl; i++)
			if (b[i] != ' ')
				return ' ' < b[i] ? -1 : 1;
	}
	return 0;
}

static int cmp_all(const cob_field *f, const cob_field *pat)
{
	unsigned char buf[256];
	const unsigned char *p = f->data;
	size_t n = f->size;
	if (cob_is_num_type(f->attr->type) && f->attr->type != COB_NUM_DISPLAY) {
		n = cob_field_text(f, buf, sizeof buf);
		p = buf;
	}
	size_t pn = pat->size;
	for (size_t i = 0; i < n; i++) {
		unsigned char c = pn ? pat->data[i % pn] : 0;
		if (p[i] != c) {
			if (coll_tbl) {
				if (coll_tbl[p[i]] != coll_tbl[c])
					return coll_tbl[p[i]] < coll_tbl[c] ? -1 : 1;
				continue;
			}
			return p[i] < c ? -1 : 1;
		}
	}
	return 0;
}

int cob_cmp(const cob_field *a, const cob_field *b)
{
	int at = a->attr->type, bt = b->attr->type;
	unsigned char ba[256], bb[256];
	if (bt == COB_ALL) {
		if ((b->attr->flags & COB_F_ZERO) && cob_is_num_type(at))
			return cob_d_sign(cob_d_get(a));
		return cmp_all(a, b);
	}
	if (at == COB_ALL) {
		if ((a->attr->flags & COB_F_ZERO) && cob_is_num_type(bt))
			return -cob_d_sign(cob_d_get(b));
		return -cmp_all(b, a);
	}
	if (cob_is_num_type(at) && cob_is_num_type(bt))
		return cob_d_cmp(cob_d_get(a), cob_d_get(b));
	const unsigned char *pa = a->data, *pb = b->data;
	size_t al = a->size, bl = b->size;
	if (cob_is_num_type(at) && at != COB_GROUP) {
		al = cob_field_text(a, ba, sizeof ba);
		pa = ba;
	}
	if (cob_is_num_type(bt) && bt != COB_GROUP) {
		bl = cob_field_text(b, bb, sizeof bb);
		pb = bb;
	}
	return cob_cmp_alnum(pa, al, pb, bl);
}

/* ================================================================ class tests */

int cob_is_numeric(const cob_field *f)
{
	const cob_attr *a = f->attr;
	size_t n = f->size;
	const unsigned char *p = f->data;
	switch (a->type) {
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_NUM_FLOAT:
	case COB_NUM_DOUBLE:
	case COB_INDEX:
		return 1;
	case COB_NUM_PACKED: {
		if (a->flags & COB_F_UNSIGNED_PACKED) {
			/* COMP-6: every nibble is a digit, there is no sign to check */
			for (size_t i = 0; i < n; i++) {
				if ((p[i] >> 4) > 9 || (p[i] & 0x0F) > 9)
					return 0;
			}
			return 1;
		}
		for (size_t i = 0; i < n; i++) {
			unsigned char hi = p[i] >> 4, lo = p[i] & 0x0F;
			if (hi > 9)
				return 0;
			if (i < n - 1 && lo > 9)
				return 0;
		}
		unsigned char s = p[n - 1] & 0x0F;
		if (a->flags & COB_F_SIGNED)
			return s == 0x0C || s == 0x0D || s == 0x0F;
		return s == 0x0F;
	}
	case COB_NUM_DISPLAY: {
		if (a->flags & COB_F_SIGNED) {
			if (a->flags & COB_F_SIGN_SEP) {
				unsigned char sc;
				if (a->flags & COB_F_SIGN_LEAD) {
					sc = p[0];
					p++;
				} else
					sc = p[n - 1];
				n--;
				if (sc != '+' && sc != '-')
					return 0;
			} else {
				size_t spos = (a->flags & COB_F_SIGN_LEAD) ? 0 : n - 1;
				for (size_t i = 0; i < n; i++) {
					unsigned char c = p[i];
					if (i == spos) {
						if (!((c >= '0' && c <= '9') || (c >= 0x70 && c <= 0x79)))
							return 0;
					} else if (c < '0' || c > '9')
						return 0;
				}
				return 1;
			}
		}
		for (size_t i = 0; i < n; i++)
			if (p[i] < '0' || p[i] > '9')
				return 0;
		return 1;
	}
	default:
		for (size_t i = 0; i < n; i++)
			if (p[i] < '0' || p[i] > '9')
				return 0;
		return 1;
	}
}

int cob_is_alpha(const cob_field *f)
{
	for (size_t i = 0; i < f->size; i++) {
		unsigned char c = f->data[i];
		if (!(c == ' ' || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')))
			return 0;
	}
	return 1;
}

int cob_is_lower(const cob_field *f)
{
	for (size_t i = 0; i < f->size; i++) {
		unsigned char c = f->data[i];
		if (!(c == ' ' || (c >= 'a' && c <= 'z')))
			return 0;
	}
	return 1;
}

int cob_is_upper(const cob_field *f)
{
	for (size_t i = 0; i < f->size; i++) {
		unsigned char c = f->data[i];
		if (!(c == ' ' || (c >= 'A' && c <= 'Z')))
			return 0;
	}
	return 1;
}

int cob_is_class(const cob_field *f, const unsigned char *table)
{
	for (size_t i = 0; i < f->size; i++)
		if (!table[f->data[i]])
			return 0;
	return 1;
}

/* ================================================================ DISPLAY */

static FILE *dev_fp(int dev)
{
	return dev == 1 ? stderr : stdout;
}

static int disp_digits(const cob_field *f)
{
	const cob_attr *a = f->attr;
	if (a->type == COB_NUM_COMP5) {
		/* as many digits as the largest value of the size */
		static const unsigned char dig[17] = { 1, 3, 5, 8, 10, 13, 15, 17, 20, 22, 25, 27, 29, 32, 34, 37, 39 };
		return f->size <= 16 ? dig[f->size] : 39;
	}
	if (a->type == COB_INDEX)
		return 9;
	return a->digits;
}

void cob_display(int dev, const cob_field *f)
{
	FILE *fp = dev_fp(dev);
	const cob_attr *a = f->attr;
	char buf[128];
	switch (a->type) {
	case COB_NUM_DISPLAY:
	case COB_NUM_PACKED:
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_INDEX: {
		cob_dec d = cob_d_get(f);
		int digits = disp_digits(f);
		int scale = a->type == COB_INDEX ? 0 : a->scale;
		int sgn = (a->flags & COB_F_SIGNED) || a->type == COB_INDEX;
		int o = 0;
		int ovf = 0;
		cob_s128 v = rescale(d.v, d.scale, scale < 0 ? 0 : scale, 0, &ovf);
		if (scale < 0) {
			digits -= scale;
			scale = 0;
		} else if (scale > digits) {
			digits = scale;   /* PICTURE VP9: the P positions print as zeros after the point */
		}
		int trailing = a->type == COB_NUM_DISPLAY && (a->flags & COB_F_SIGN_SEP) && !(a->flags & COB_F_SIGN_LEAD);
		if (sgn && !trailing)
			buf[o++] = v < 0 ? '-' : '+';
		cob_u128 u = uabs(v);
		char tmp[64];
		for (int i = 0; i < digits; i++) {
			tmp[i] = (char)('0' + (int)(u % 10));
			u /= 10;
		}
		for (int i = digits - 1; i >= 0; i--) {
			if (i == scale - 1)
				buf[o++] = (a->flags & COB_F_DEC_COMMA) ? ',' : '.';
			buf[o++] = tmp[i];
		}
		if (sgn && trailing)
			buf[o++] = v < 0 ? '-' : '+';
		fwrite(buf, 1, (size_t)o, fp);
		return;
	}
	case COB_NUM_FLOAT: {
		float x;
		memcpy(&x, f->data, 4);
		fprintf(fp, "%.8G", (double)x);
		return;
	}
	case COB_NUM_DOUBLE: {
		double x;
		memcpy(&x, f->data, 8);
		fprintf(fp, "%.16G", x);
		return;
	}
	case COB_POINTER: {
		void *x;
		memcpy(&x, f->data, sizeof x);
		fprintf(fp, "%p", x);
		return;
	}
	case COB_ALL:
		fwrite(f->data, 1, f->size, fp);
		return;
	default:
		fwrite(f->data, 1, f->size, fp);
		return;
	}
}

void cob_display_lit(int dev, const char *s, size_t n)
{
	fwrite(s, 1, n, dev_fp(dev));
}

void cob_display_dec(int dev, cob_dec d)
{
	char buf[100];
	cob_d_to_str(d, buf, sizeof buf);
	fputs(buf, dev_fp(dev));
}

/* the value of a signed binary item of `digits` digits, as DISPLAY shows it
   (LENGTH OF an item of variable size, as in GnuCOBOL) */
void cob_display_signed(int dev, cob_s64 v, int digits)
{
	fprintf(dev_fp(dev), "%c%0*lld", v < 0 ? '-' : '+', digits, (long long)(v < 0 ? -v : v));
}

void cob_display_end(int dev, int newline)
{
	FILE *fp = dev_fp(dev);
	if (newline)
		fputc('\n', fp);
	if (dev == 1 || !newline)
		fflush(fp);
}

/* ================================================================ exceptions */

const cob_loc *cob_cur_loc;
int cob_call_rejected;
static const char *exc_name;            /* NULL: no exception */
static const cob_loc *exc_loc;
static cob_file *exc_file;
static int exc_is_io;

void cob_set_exception(const char *name)
{
	exc_name = name;
	exc_loc = cob_cur_loc;
	exc_is_io = 0;
}

/* the statement that raised the exception being recorded */
void cob_exc_where(const cob_loc *loc)
{
	cob_cur_loc = loc;
	if (exc_name)
		exc_loc = loc;
}

/* every I/O status: an unsuccessful one raises the EC-I-O condition of its
   class, a successful one clears the last exception (as in GnuCOBOL) */
void cob_exc_io(cob_file *f, const char *st)
{
	static const char *names[10] = {
		NULL, "EC-I-O-AT-END", "EC-I-O-INVALID-KEY", "EC-I-O-PERMANENT-ERROR",
		"EC-I-O-LOGIC-ERROR", "EC-I-O-RECORD-OPERATION", "EC-I-O-FILE-SHARING",
		"EC-I-O", "EC-I-O", "EC-I-O-IMP"
	};
	int k = st[0] - '0';
	exc_file = f;
	if (k <= 0 || k > 9) {
		exc_name = NULL;
		return;
	}
	exc_name = names[k];
	exc_loc = cob_cur_loc;
	exc_is_io = 1;
}

cob_field *cob_fn_text(const char *s)
{
	size_t n = strlen(s);
	cob_field *r = cob_tmp_field(n, &cob_attr_alnum);
	memcpy(r->data, s, n);
	return r;
}

static cob_field *padded(const char *s, size_t width)
{
	cob_field *r = cob_tmp_field(width, &cob_attr_alnum);
	size_t n = s ? strlen(s) : 0;
	memcpy(r->data, s, n < width ? n : width);
	return r;
}

/* EXCEPTION-FILE: I/O status and file name of the last I/O exception, else "00" */
cob_field *cob_fn_exception_file(void)
{
	if (!exc_name || !exc_is_io || !exc_file)
		return cob_fn_text("00");
	size_t n = strlen(exc_file->select_name);
	cob_field *r = cob_tmp_field(n + 2, &cob_attr_alnum);
	memcpy(r->data, exc_file->stat, 2);
	memcpy(r->data + 2, exc_file->select_name, n);
	return r;
}

/* EXCEPTION-LOCATION: "program; paragraph OF section; line" */
cob_field *cob_fn_exception_location(void)
{
	if (!exc_name || !exc_loc)
		return cob_fn_text(" ");
	char buf[512];
	const cob_loc *l = exc_loc;
	if (l->para && l->sect)
		snprintf(buf, sizeof buf, "%s; %s OF %s; %d", l->prog, l->para, l->sect, l->line);
	else if (l->para || l->sect)
		snprintf(buf, sizeof buf, "%s; %s; %d", l->prog, l->para ? l->para : l->sect, l->line);
	else
		snprintf(buf, sizeof buf, "%s; ; %d", l->prog, l->line);
	return cob_fn_text(buf);
}

cob_field *cob_fn_exception_statement(void)
{
	return padded(exc_name && exc_loc ? exc_loc->stmt : NULL, 31);
}

/* FUNCTION CONTENT-LENGTH(pointer): the bytes before the NUL, 0 for NULL */
size_t cob_fn_content_length(const unsigned char *p)
{
	return p ? strlen((const char *)p) : 0;
}

/* FUNCTION CONTENT-OF(pointer[, length]): those bytes; a NULL pointer raises
 * EC-DATA-PTR-NULL and yields an empty value */
cob_field *cob_fn_content_of(const unsigned char *p, cob_s64 len)
{
	if (!p) {
		cob_set_exception("EC-DATA-PTR-NULL");
		return padded(NULL, 0);
	}
	/* a successful call leaves no exception behind */
	cob_clear_exception();
	size_t n = strlen((const char *)p);
	if (len >= 0 && (cob_u64)len < n)
		n = (size_t)len;
	cob_field *r = cob_tmp_field(n, &cob_attr_alnum);
	memcpy(r->data, p, n);
	return r;
}

cob_field *cob_fn_exception_status(void)
{
	return padded(exc_name, 31);
}

/* SET LAST EXCEPTION TO OFF */
void cob_clear_exception(void)
{
	exc_name = NULL;
	exc_loc = NULL;
	exc_is_io = 0;
	exc_file = NULL;
}

/* ================================================================ calling chain */

/* the active programs, innermost last: name, number of parameters received
   and their sizes (for C$NARG, C$PARAMSIZE, C$CALLEDBY, MODULE-CALLER-ID and
   NUMBER-OF-CALL-PARAMETERS) */
typedef struct {
	const char *name;
	int nargs;
	const int *sizes;
} cob_frame_info;

static cob_frame_info frames[256];
static int frame_depth;
const int *cob_call_sizes;                  /* set by a CALL for the program it enters */
const unsigned char *cob_call_arg_omitted;  /* per argument: 1 when OMITTED */
static unsigned char ncp_data[4];
static const cob_attr attr_ncp = { COB_NUM_BINARY, 9, 0, COB_F_SIGNED, NULL, 0 };
cob_field cob_ncp_reg = { 4, ncp_data, &attr_ncp };
static int *main_sizes;

static void set_ncp(void)
{
	cob_set_int(&cob_ncp_reg, frame_depth > 0 && frame_depth <= 256 ? frames[frame_depth - 1].nargs : 0);
}

void cob_module_push(const char *name, int argc)
{
	if (frame_depth < 256) {
		cob_frame_info *fr = &frames[frame_depth];
		fr->name = name;
		if (argc >= 0) {
			fr->nargs = argc;
			fr->sizes = cob_call_sizes;
		} else {
			/* the main program: its parameters are the command-line arguments */
			fr->nargs = g_argc > 1 ? g_argc - 1 : 0;
			if (!main_sizes && fr->nargs) {
				main_sizes = cob_malloc(sizeof(int) * (size_t)fr->nargs);
				for (int i = 0; i < fr->nargs; i++)
					main_sizes[i] = (int)strlen(g_argv[i + 1]);
			}
			fr->sizes = main_sizes;
		}
	}
	cob_call_sizes = NULL;
	/* cob_call_arg_omitted is deliberately not cleared here: the caller sets it
	 * immediately before the call, and this push happens inside the callee */
	frame_depth++;
	set_ncp();
}

void cob_module_pop(void)
{
	if (frame_depth > 0)
		frame_depth--;
	set_ncp();
}

int cob_frame_nargs(void)
{
	return frame_depth > 0 && frame_depth <= 256 ? frames[frame_depth - 1].nargs : 0;
}

int cob_frame_param_size(int i)
{
	if (frame_depth <= 0 || frame_depth > 256)
		return 0;
	const cob_frame_info *fr = &frames[frame_depth - 1];
	if (i < 1 || i > fr->nargs || !fr->sizes)
		return 0;
	return fr->sizes[i - 1];
}

/* the program that called the running one; NULL for the main program */
const char *cob_frame_caller(void)
{
	if (frame_depth >= 2 && frame_depth - 2 < 256)
		return frames[frame_depth - 2].name;
	return NULL;
}

/* MODULE-CALLER-ID: the program that called the running one; spaces for the main program */
cob_field *cob_fn_module_caller_id(void)
{
	const char *c = cob_frame_caller();
	return cob_fn_text(c ? c : " ");
}

void cob_warning(const char *fmt, ...)
{
	va_list ap;
	fflush(stdout);
	fputs("cobrt: warning: ", stderr);
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
}

/* MODULE-PATH: the full path of the executable */
cob_field *cob_fn_module_path(void)
{
	static char path[4096];
	if (!path[0]) {
		ssize_t n = readlink("/proc/self/exe", path, sizeof path - 1);
		if (n > 0)
			path[n] = 0;
		else if (g_argc > 0 && !realpath(g_argv[0], path))
			snprintf(path, sizeof path, "%s", g_argv[0]);
	}
	return cob_fn_text(path[0] ? path : " ");
}

/* ================================================================ ACCEPT */

static int read_line(char *buf, size_t sz)
{
	fflush(stdout);
	if (!fgets(buf, (int)sz, stdin))
		return -1;
	size_t n = strlen(buf);
	if (n && buf[n - 1] != '\n' && n == sz - 1) {
		int c;
		while ((c = getchar()) != EOF && c != '\n')
			;
	}
	while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r'))
		buf[--n] = 0;
	return (int)n;
}

int cob_accept(cob_field *f)
{
	char buf[8192];
	int n = read_line(buf, sizeof buf);
	if (n < 0) {
		return 1;
	}
	if (f->attr->type == COB_NUM_DISPLAY && (size_t)n > f->size)
		n = (int)f->size;
	cob_move_bytes((unsigned char *)buf, (size_t)n, f);
	return 0;
}

void cob_move_text(cob_field *f, const char *s)
{
	cob_field tmp = { strlen(s), (unsigned char *)s, &cob_attr_alnum };
	cob_move(&tmp, f);
}

/* The current date and time: the system clock, or the fixed moment given by
   COB_CURRENT_DATE ("YYYY/MM/DD hh:mm:ss[.nn] [+hhmm]" or the same digits
   without separators; the parts after the date are optional), as GnuCOBOL. */
static int fixed_now = -1;
static struct tm fixed_tm;
static int fixed_hs;
static long fixed_off;
static int fixed_has_off;

static void parse_fixed_now(void)
{
	const char *s = getenv("COB_CURRENT_DATE");
	fixed_now = 0;
	if (!s || !*s)
		return;
	static const int width[7] = { 4, 2, 2, 2, 2, 2, 2 };
	long v[7] = { 0, 1, 1, 0, 0, 0, 0 };
	int n = 0;
	const char *p = s;
	while (*p && n < 7) {
		while (*p == ' ' || *p == '/' || *p == '-' || *p == ':' || *p == '.' || *p == 'T')
			p++;
		if (!isdigit((unsigned char)*p))
			break;
		long x = 0;
		int k = 0;
		while (isdigit((unsigned char)p[k]) && k < width[n])
			x = x * 10 + (p[k++] - '0');
		v[n++] = x;
		p += k;
		while (n == 7 && isdigit((unsigned char)*p))   /* finer fractions */
			p++;
		if (*p == ' ' && (p[1] == '+' || p[1] == '-'))
			p++;
		if (*p == '+' || (*p == '-' && n >= 6))
			break;
	}
	if (n < 3)
		return;
	while (*p == ' ')
		p++;
	if ((*p == '+' || *p == '-') && isdigit((unsigned char)p[1])) {
		int sg = *p == '-' ? -1 : 1;
		long hh = 0, mm = 0;
		p++;
		for (int k = 0; k < 2 && isdigit((unsigned char)*p); k++)
			hh = hh * 10 + (*p++ - '0');
		if (*p == ':')
			p++;
		for (int k = 0; k < 2 && isdigit((unsigned char)*p); k++)
			mm = mm * 10 + (*p++ - '0');
		fixed_off = sg * (hh * 60 + mm);
		fixed_has_off = 1;
	}
	memset(&fixed_tm, 0, sizeof fixed_tm);
	fixed_tm.tm_year = (int)v[0] - 1900;
	fixed_tm.tm_mon = (int)v[1] - 1;
	fixed_tm.tm_mday = (int)v[2];
	fixed_tm.tm_hour = (int)v[3];
	fixed_tm.tm_min = (int)v[4];
	fixed_tm.tm_sec = (int)v[5];
	fixed_tm.tm_isdst = -1;
	fixed_hs = (int)v[6];
	struct tm t = fixed_tm;
	time_t tt = mktime(&t);              /* fills in the day of week and of year */
	fixed_tm.tm_wday = t.tm_wday;
	fixed_tm.tm_yday = t.tm_yday;
	if (!fixed_has_off && tt != (time_t)-1) {
		fixed_off = t.tm_gmtoff / 60;
		fixed_has_off = 1;
	}
	fixed_now = 1;
}

/* local time, hundredths of a second and the UTC offset in minutes */
void cob_now(struct tm *tm, int *hundredths, long *utc_off)
{
	if (fixed_now < 0)
		parse_fixed_now();
	if (fixed_now) {
		*tm = fixed_tm;
		if (hundredths)
			*hundredths = fixed_hs;
		if (utc_off)
			*utc_off = fixed_off;
		return;
	}
	struct timeval tv;
	gettimeofday(&tv, NULL);
	localtime_r(&tv.tv_sec, tm);
	if (hundredths)
		*hundredths = (int)(tv.tv_usec / 10000);
	if (utc_off)
		*utc_off = tm->tm_gmtoff / 60;
}

void cob_accept_date(cob_field *f, int fmt)
{
	struct tm tm;
	char buf[32];
	cob_now(&tm, NULL, NULL);
	switch (fmt) {
	case 0: /* YYMMDD */
		snprintf(buf, sizeof buf, "%02d%02d%02d", tm.tm_year % 100, tm.tm_mon + 1, tm.tm_mday);
		break;
	case 1: /* YYYYMMDD */
		snprintf(buf, sizeof buf, "%04d%02d%02d", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday);
		break;
	case 2: /* YYDDD */
		snprintf(buf, sizeof buf, "%02d%03d", tm.tm_year % 100, tm.tm_yday + 1);
		break;
	case 3: /* YYYYDDD */
		snprintf(buf, sizeof buf, "%04d%03d", tm.tm_year + 1900, tm.tm_yday + 1);
		break;
	case 4: /* day of week 1=Monday */
		snprintf(buf, sizeof buf, "%d", tm.tm_wday == 0 ? 7 : tm.tm_wday);
		break;
	default:
		buf[0] = 0;
	}
	cob_move_text(f, buf);
}

void cob_accept_time(cob_field *f)
{
	struct tm tm;
	int hs;
	char buf[16];
	cob_now(&tm, &hs, NULL);
	snprintf(buf, sizeof buf, "%02d%02d%02d%02d", tm.tm_hour, tm.tm_min, tm.tm_sec, hs);
	cob_move_text(f, buf);
}

void cob_accept_cmdline(cob_field *f)
{
	char buf[8192];
	size_t o = 0;
	buf[0] = 0;
	for (int i = 1; i < g_argc; i++) {
		size_t l = strlen(g_argv[i]);
		if (o + l + 2 >= sizeof buf)
			break;
		if (i > 1)
			buf[o++] = ' ';
		memcpy(buf + o, g_argv[i], l);
		o += l;
	}
	buf[o] = 0;
	cob_move_text(f, buf);
}

/* PROCEDURE DIVISION CHAINING: the nth argument after the program name, or
 * NULL. chaining items keep their VALUE when no such argument was given. */
unsigned char *cob_alloc_chars(cob_s64 n)
{
	if (n <= 0)
		return cob_malloc(1);
	return cob_malloc((size_t)n);
}

/* ALLOCATE ... INITIALIZED TO value: the value repeated over the block */
void cob_fill_block(unsigned char *p, size_t n, const cob_field *v)
{
	size_t vl = v->size ? v->size : 1;
	for (size_t i = 0; i < n; i++)
		p[i] = v->data[i % vl];
}

void cob_free_chars(unsigned char *p)
{
	free(p);
}

/* IF item OMITTED: a CALL passed no argument in this position */
int cob_param_omitted(int n)
{
	if (frame_depth <= 0 || frame_depth > 256)
		return 0;
	const cob_frame_info *fr = &frames[frame_depth - 1];
	if (n < 1 || n > fr->nargs)
		return 1;
	return cob_call_arg_omitted && cob_call_arg_omitted[n - 1];
}

const char *cob_chain_arg(int n)
{
	if (n < 0 || n + 1 >= g_argc)
		return NULL;
	return g_argv[n + 1];
}

static char env_name[256];

/* ACCEPT OMITTED: read one line and throw it away */
void cob_accept_discard(void)
{
	char fbuf[8192];
	if (fgets(fbuf, sizeof fbuf, stdin))
		;
}

int cob_accept_env(cob_field *f, const cob_field *name)
{
	char nm[256];
	const char *val;
	if (name) {
		size_t n = name->size < 255 ? name->size : 255;
		memcpy(nm, name->data, n);
		while (n && nm[n - 1] == ' ')
			n--;
		nm[n] = 0;
		val = getenv(nm);
	} else
		val = getenv(env_name);
	if (!val) {
		cob_move_text(f, "");
		return 1;
	}
	cob_move_text(f, val);
	return 0;
}

void cob_accept_argv(cob_field *f, int what)
{
	char buf[32];
	if (what == 0) {
		/* ARGUMENT-NUMBER */
		snprintf(buf, sizeof buf, "%d", g_argc - 1);
		cob_move_text(f, buf);
	} else {
		if (g_arg_index < g_argc)
			cob_move_text(f, g_argv[g_arg_index++]);
		else
			cob_move_text(f, "");
	}
}

void cob_display_env(int what, const cob_field *f)
{
	char val[4096];
	size_t n = f->size < sizeof val - 1 ? f->size : sizeof val - 1;
	memcpy(val, f->data, n);
	while (n && val[n - 1] == ' ')
		n--;
	val[n] = 0;
	if (what == 0) {
		size_t l = strlen(val);
		if (l >= sizeof env_name)
			l = sizeof env_name - 1;
		memcpy(env_name, val, l);
		env_name[l] = 0;
	} else if (what == 1) {
		setenv(env_name, val, 1);
	} else if (what == 2) {
		g_arg_index = atoi(val);
	}
}

/* ================================================================ switches */

static signed char switches[100];

int cob_switch_get(int n)
{
	if (n < 0 || n >= 100)
		return 0;
	if (switches[n] == 0) {
		char nm[32];
		snprintf(nm, sizeof nm, "COB_SWITCH_%d", n);
		const char *v = getenv(nm);
		switches[n] = (v && (strcasecmp(v, "ON") == 0 || strcmp(v, "1") == 0 ||
		                     strcasecmp(v, "TRUE") == 0 || strcasecmp(v, "YES") == 0)) ? 1 : -1;
	}
	return switches[n] == 1;
}

void cob_switch_set(int n, int v)
{
	if (n >= 0 && n < 100)
		switches[n] = v ? 1 : -1;
}

/* ================================================================ Debug module */

int cob_debug_on;

__attribute__((constructor)) static void init_debug_switch(void)
{
	const char *v = getenv("COB_SET_DEBUG");
	cob_debug_on = v && (strcasecmp(v, "Y") == 0 || strcasecmp(v, "YES") == 0 || strcasecmp(v, "ON") == 0 ||
	                     strcasecmp(v, "TRUE") == 0 || strcmp(v, "1") == 0);
}

#define DBG_NAME 7
#define DBG_SUB 38
#define DBG_CONTENTS 56

/* DEBUG-ITEM is space-filled, then DEBUG-LINE and DEBUG-NAME are set. */
static void dbg_head(unsigned char *di, int dilen, int line, const char *name)
{
	memset(di, ' ', (size_t)dilen);
	if (line > 0) {
		char b[24];
		int n = snprintf(b, sizeof b, "%6d", line);
		memcpy(di, b + n - 6, 6);
	}
	size_t n = strlen(name);
	memcpy(di + DBG_NAME, name, n > 30 ? 30 : n);
}

static void dbg_contents(unsigned char *di, int dilen, const void *p, size_t n)
{
	size_t cap = (size_t)(dilen - DBG_CONTENTS);
	memcpy(di + DBG_CONTENTS, p, n > cap ? cap : n);
}

void cob_dbg_proc(unsigned char *di, int dilen, int line, const char *name, int cause)
{
	static const char *const text[] = {
		"FALL THROUGH", "START PROGRAM", "PERFORM LOOP", "", "SORT INPUT",
		"SORT OUTPUT", "MERGE OUTPUT", "USE PROCEDURE"
	};
	dbg_head(di, dilen, line, name);
	if (cause >= 0 && cause < (int)(sizeof text / sizeof text[0]))
		dbg_contents(di, dilen, text[cause], strlen(text[cause]));
}

void cob_dbg_alter(unsigned char *di, int dilen, int line, const char *name, const char *target)
{
	dbg_head(di, dilen, line, name);
	dbg_contents(di, dilen, target, strlen(target));
}

void cob_dbg_data(unsigned char *di, int dilen, int line, const char *name,
                  const unsigned char *data, size_t size, int nsubs, cob_s64 s1, cob_s64 s2, cob_s64 s3)
{
	const cob_s64 subs[3] = { s1, s2, s3 };
	dbg_head(di, dilen, line, name);
	for (int i = 0; i < nsubs && i < 3; i++) {
		char b[24];
		cob_s64 v = subs[i] < 0 ? -subs[i] : subs[i];
		snprintf(b, sizeof b, "%c%04lld", subs[i] < 0 ? '-' : '+', (long long)(v % 10000));
		memcpy(di + DBG_SUB + 6 * i, b, 5);
	}
	if (data)
		dbg_contents(di, dilen, data, size);
}

/* ================================================================ CALL registry */

#define MAX_PROGS 512
static struct {
	const char *name;
	cob_prog_fn fn;
	cob_cancel_fn cancel;
} progs[MAX_PROGS];
static int nprogs;
int cob_decl_which;


void cob_register_program(const char *name, cob_prog_fn fn, cob_cancel_fn cancel)
{
	if (nprogs < MAX_PROGS) {
		progs[nprogs].name = name;
		progs[nprogs].fn = fn;
		progs[nprogs].cancel = cancel;
		nprogs++;
	}
}

void cob_cancel_name(const char *name)
{
	int k = -1;
	for (int i = 0; i < nprogs && k < 0; i++)
		if (strcmp(progs[i].name, name) == 0)
			k = i;
	for (int i = 0; i < nprogs && k < 0; i++)
		if (strcasecmp(progs[i].name, name) == 0)
			k = i;
	if (k >= 0 && progs[k].cancel)
		progs[k].cancel();
}

void cob_cancel(const cob_field *name)
{
	char nm[256];
	size_t n = name->size < 255 ? name->size : 255;
	memcpy(nm, name->data, n);
	while (n && (nm[n - 1] == ' ' || nm[n - 1] == 0))
		n--;
	size_t s = 0;
	while (s < n && nm[s] == ' ')
		s++;
	nm[n] = 0;
	cob_cancel_name(nm + s);
}

cob_prog_fn cob_resolve_name(const char *name)
{
	/* the exact name first: literal PROGRAM-IDs are case-sensitive */
	for (int i = 0; i < nprogs; i++)
		if (strcmp(progs[i].name, name) == 0)
			return progs[i].fn;
	for (int i = 0; i < nprogs; i++)
		if (strcasecmp(progs[i].name, name) == 0)
			return progs[i].fn;
	return NULL;
}

cob_prog_fn cob_resolve(const cob_field *name)
{
	char nm[256];
	size_t n = name->size < 255 ? name->size : 255;
	memcpy(nm, name->data, n);
	while (n && (nm[n - 1] == ' ' || nm[n - 1] == 0))
		n--;
	size_t s = 0;
	while (s < n && nm[s] == ' ')
		s++;
	nm[n] = 0;
	return cob_resolve_name(nm + s);
}

void cob_call_system(const cob_field *cmdf)
{
	char cmd[8192];
	size_t n = cmdf->size < sizeof cmd - 1 ? cmdf->size : sizeof cmd - 1;
	memcpy(cmd, cmdf->data, n);
	for (size_t i = 0; i < n; i++)
		if (cmd[i] == 0) {
			n = i;
			break;
		}
	while (n && cmd[n - 1] == ' ')
		n--;
	cmd[n] = 0;
	fflush(stdout);
	int rc = system(cmd);
	if (rc != -1 && WIFEXITED(rc))
		rc = WEXITSTATUS(rc);
	cob_set_int(&cob_return_code, rc);
}
