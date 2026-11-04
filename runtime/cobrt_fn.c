/* SPDX-License-Identifier: MIT */
/* cobrt_fn.c - intrinsic functions */
#include "cobrt.h"
#include <ctype.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>
#include <unistd.h>

/* an invalid argument: EC-ARGUMENT-FUNCTION, and zero as the result (as GnuCOBOL) */
static cob_dec arg_error(void)
{
	cob_set_exception("EC-ARGUMENT-FUNCTION");
	return cob_d_int(0);
}

static int dec_is_int(cob_dec d)
{
	if (d.scale <= 0)
		return 1;
	cob_s128 p = 1;
	for (int i = 0; i < d.scale; i++)
		p *= 10;
	return d.v % p == 0;
}

cob_dec cob_fn_abs(cob_dec a)
{
	if (a.scale != COB_DEC_ERR && a.v < 0)
		a.v = -a.v;
	return a;
}

cob_dec cob_fn_integer_part(cob_dec a)
{
	return cob_d_trunc(a, 0);
}

cob_dec cob_fn_integer(cob_dec a)
{
	cob_dec t = cob_d_trunc(a, 0);
	if (a.scale != COB_DEC_ERR && a.v < 0 && !dec_is_int(a))
		t.v -= 1;
	return t;
}

cob_dec cob_fn_fraction_part(cob_dec a)
{
	return cob_d_sub(a, cob_d_trunc(a, 0));
}

cob_dec cob_fn_mod(cob_dec a, cob_dec b)
{
	if (b.v == 0 || a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return arg_error();
	cob_dec q = cob_fn_integer(cob_d_div(a, b));
	return cob_d_sub(a, cob_d_mul(b, q));
}

cob_dec cob_fn_rem(cob_dec a, cob_dec b)
{
	if (b.v == 0 || a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR)
		return arg_error();
	cob_dec q = cob_d_trunc(cob_d_div(a, b), 0);
	return cob_d_sub(a, cob_d_mul(b, q));
}

cob_dec cob_fn_sign(cob_dec a)
{
	return cob_d_int(cob_d_sign(a));
}

cob_dec cob_fn_factorial(cob_dec a)
{
	if (a.scale == COB_DEC_ERR)
		return a;
	cob_s64 n = cob_d_to_int(a);
	if (n < 0 || n > 33)
		return arg_error();
	cob_s128 r = 1;
	for (cob_s64 i = 2; i <= n; i++)
		r *= i;
	cob_dec d;
	d.v = r;
	d.scale = 0;
	return d;
}

/* RANDOM: the C library generator, as GnuCOBOL: a seed restarts it (a
   negative seed counts as 0); the value is rand() / RAND_MAX */
double cob_fn_random_d(int has_seed, cob_dec seed)
{
	if (has_seed) {
		cob_s64 s = cob_d_to_int(seed);
		srand((unsigned int)(s < 0 ? 0 : s));
	}
	return (double)rand() / RAND_MAX;
}

cob_dec cob_fn_random(int has_seed, cob_dec seed)
{
	return cob_d_from_double_exact(cob_fn_random_d(has_seed, seed));
}

cob_dec cob_fn_length(const cob_field *f)
{
	return cob_d_int((cob_s64)f->size);
}

cob_dec cob_fn_ord(const cob_field *f)
{
	return cob_d_int(f->size ? f->data[0] + 1 : 1);
}

/* NUMVAL (kind 0), NUMVAL-C (kind 1) and NUMVAL-F (kind 2) arguments:
     [sp][+|-][sp][cs][sp]{digits[.[digits]] | .digits}[sp][+|-|CR|DB][sp]
   with the currency string cs and thousands separators only for NUMVAL-C,
   the sign either leading or trailing, and for NUMVAL-F an exponent
   E[sp]{+|-}[sp]digits after the mantissa instead of CR/DB. Returns 0 for a
   valid argument and stores its value; otherwise the position of the first
   character in error (the length + 1 when the argument ends too early). */
static int numval_scan(const unsigned char *s, size_t n, int kind, const unsigned char *cs, size_t csl,
		       int dpc, cob_dec *res)
{
	unsigned char dp = dpc ? ',' : '.', sep = dpc ? '.' : ',';
	size_t i = 0;
	int lead = 0, neg = 0, digits = 0, point = 0, scale = 0, sig = 0, big = 0;
	cob_s128 v = 0;
	*res = cob_d_int(0);
#define SKIP_SP() while (i < n && s[i] == ' ') i++
	SKIP_SP();
	if (i < n && (s[i] == '+' || s[i] == '-')) {
		lead = 1;
		neg = s[i] == '-';
		i++;
		SKIP_SP();
	}
	if (kind == 1 && csl && i + csl <= n && memcmp(s + i, cs, csl) == 0) {
		i += csl;
		SKIP_SP();
		if (!lead && i < n && (s[i] == '+' || s[i] == '-')) {     /* "$ -1.5", as GnuCOBOL */
			lead = 1;
			neg = s[i] == '-';
			i++;
			SKIP_SP();
		}
	}
	for (; i < n; i++) {
		unsigned char c = s[i];
		if (c >= '0' && c <= '9') {
			digits++;
			if (sig || c != '0')
				sig++;
			if (sig <= 38) {
				v = v * 10 + (c - '0');
				if (point)
					scale++;
			} else if (!point)
				big = 1;                /* more than 38 integer digits */
		} else if (c == dp && !point)
			point = 1;
		else if (kind == 1 && c == sep && !point && digits)
			continue;
		else
			break;
	}
	if (!digits)
		return i < n && s[i] != ' ' ? (int)i + 1 : (int)n + 1;
	SKIP_SP();
	if (kind == 2 && i < n && (s[i] == 'E' || s[i] == 'e')) {
		i++;
		SKIP_SP();
		if (i >= n)
			return (int)n + 1;
		if (s[i] != '+' && s[i] != '-')
			return (int)i + 1;
		int eneg = s[i] == '-', ex = 0;
		i++;
		SKIP_SP();
		if (i >= n)
			return (int)n + 1;
		if (s[i] < '0' || s[i] > '9')
			return (int)i + 1;
		while (i < n && s[i] >= '0' && s[i] <= '9') {
			if (ex < 10000)
				ex = ex * 10 + (s[i] - '0');
			i++;
		}
		SKIP_SP();
		scale += eneg ? ex : -ex;
	} else if (!lead && i < n) {
		if (s[i] == '+' || s[i] == '-') {
			neg = s[i] == '-';
			i++;
		} else if (kind != 2 && (s[i] == 'C' || s[i] == 'D')) {
			if (i + 1 >= n || s[i + 1] != (s[i] == 'C' ? 'R' : 'B'))
				return (int)i + 2;
			neg = 1;
			i += 2;
		}
		SKIP_SP();
	}
#undef SKIP_SP
	if (i < n)
		return (int)i + 1;
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = scale;
	while (r.scale > 38) {
		r.v /= 10;
		r.scale--;
	}
	while (r.scale < 0 && !big) {
		if (r.v >= (cob_s128)1e37 || r.v <= -(cob_s128)1e37)
			big = 1;
		else {
			r.v *= 10;
			r.scale++;
		}
	}
	*res = big ? cob_d_err() : r;
	return 0;
}

static int numval_arg(const cob_field *f, const cob_field *cur, const char *defcur, int kind, int dpc,
		      cob_dec *res)
{
	unsigned char b[512];
	size_t n = cob_field_text(f, b, sizeof b);
	const unsigned char *cs = (const unsigned char *)defcur;
	size_t csl = defcur ? strlen(defcur) : 0;
	if (cur && cur->size) {
		cs = cur->data;
		csl = cur->size;
		while (csl > 1 && cs[csl - 1] == ' ')
			csl--;
	}
	return numval_scan(b, n, kind, cs, csl, dpc, res);
}

/* NUMVAL / NUMVAL-F (kind 2) / NUMVAL-C (kind 1); 0 for an invalid argument */
cob_dec cob_fn_numval(const cob_field *f, const cob_field *cur, const char *defcur, int kind, int dpc)
{
	cob_dec r;
	if (kind != 1 && cob_is_num_type(f->attr->type))
		return cob_d_get(f);
	if (numval_arg(f, cur, defcur, kind, dpc, &r) != 0)
		return cob_d_int(0);
	return r;
}

/* TEST-NUMVAL / TEST-NUMVAL-C / TEST-NUMVAL-F */
cob_dec cob_fn_test_numval(const cob_field *f, const cob_field *cur, const char *defcur, int kind, int dpc)
{
	cob_dec r;
	return cob_d_int(numval_arg(f, cur, defcur, kind, dpc, &r));
}

static int dcmp_qsort(const void *a, const void *b)
{
	return cob_d_cmp(*(const cob_dec *)a, *(const cob_dec *)b);
}

/* which: 0 sum 1 mean 2 median 3 midrange 4 range 5 variance 6 stddev 7 max 8 min */
cob_dec cob_fn_aggregate(int which, int n, const cob_dec *v)
{
	if (n <= 0)
		return cob_d_err();
	cob_dec s = cob_d_int(0);
	for (int i = 0; i < n; i++)
		s = cob_d_add(s, v[i]);
	cob_dec mx = v[0], mn = v[0];
	for (int i = 1; i < n; i++) {
		if (cob_d_cmp(v[i], mx) > 0)
			mx = v[i];
		if (cob_d_cmp(v[i], mn) < 0)
			mn = v[i];
	}
	switch (which) {
	case 0:
		return s;
	case 1:
		return cob_d_div(s, cob_d_int(n));
	case 2: {
		cob_dec *c = cob_malloc(sizeof(cob_dec) * (size_t)n);
		memcpy(c, v, sizeof(cob_dec) * (size_t)n);
		qsort(c, (size_t)n, sizeof(cob_dec), dcmp_qsort);
		cob_dec r = (n % 2) ? c[n / 2] : cob_d_div(cob_d_add(c[n / 2 - 1], c[n / 2]), cob_d_int(2));
		free(c);
		return r;
	}
	case 3:
		return cob_d_div(cob_d_add(mx, mn), cob_d_int(2));
	case 4:
		return cob_d_sub(mx, mn);
	case 5:
	case 6:
		return cob_fn_variance(n, v, which == 6);
	case 7:
		return mx;
	case 8:
		return mn;
	}
	return cob_d_err();
}

cob_dec cob_fn_ord_minmax(int is_max, int n, const cob_dec *v)
{
	int best = 0;
	for (int i = 1; i < n; i++) {
		int c = cob_d_cmp(v[i], v[best]);
		if ((is_max && c > 0) || (!is_max && c < 0))
			best = i;
	}
	return cob_d_int(best + 1);
}

cob_dec cob_fn_ord_minmax_alnum(int is_max, int n, cob_field **f)
{
	int best = 0;
	for (int i = 1; i < n; i++) {
		int c = cob_cmp(f[i], f[best]);
		if ((is_max && c > 0) || (!is_max && c < 0))
			best = i;
	}
	return cob_d_int(best + 1);
}

cob_field *cob_fn_minmax_alnum(int is_max, int n, cob_field **f)
{
	int best = 0;
	for (int i = 1; i < n; i++) {
		int c = cob_cmp(f[i], f[best]);
		if ((is_max && c > 0) || (!is_max && c < 0))
			best = i;
	}
	cob_field *r = cob_tmp_field(f[best]->size, &cob_attr_alnum);
	memcpy(r->data, f[best]->data, f[best]->size);
	return r;
}

/* ---------------------------------------------------------------- dates */

static int leap(int y)
{
	return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
}

static const int mdays[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };

static cob_s64 days_before_year(int y)
{
	cob_s64 n = 0;
	for (int yy = 1601; yy < y; yy++)
		n += leap(yy) ? 366 : 365;
	return n;
}

cob_dec cob_fn_integer_of_date(cob_dec a)
{
	cob_s64 d = cob_d_to_int(a);
	int y = (int)(d / 10000), m = (int)(d / 100 % 100), dd = (int)(d % 100);
	if (y < 1601 || y > 9999 || m < 1 || m > 12 || dd < 1)
		return arg_error();
	int ml = mdays[m - 1] + (m == 2 && leap(y));
	if (dd > ml)
		return arg_error();
	cob_s64 n = days_before_year(y);
	for (int i = 1; i < m; i++)
		n += mdays[i - 1] + (i == 2 && leap(y));
	return cob_d_int(n + dd);
}

cob_dec cob_fn_date_of_integer(cob_dec a)
{
	cob_s64 n = cob_d_to_int(a);
	if (n < 1 || n > 3067671)
		return arg_error();
	int y = 1601;
	while (n > (leap(y) ? 366 : 365)) {
		n -= leap(y) ? 366 : 365;
		y++;
	}
	int m = 1;
	while (n > mdays[m - 1] + (m == 2 && leap(y))) {
		n -= mdays[m - 1] + (m == 2 && leap(y));
		m++;
	}
	return cob_d_int((cob_s64)y * 10000 + m * 100 + n);
}

cob_dec cob_fn_integer_of_day(cob_dec a)
{
	cob_s64 d = cob_d_to_int(a);
	int y = (int)(d / 1000), dd = (int)(d % 1000);
	if (y < 1601 || y > 9999 || dd < 1 || dd > (leap(y) ? 366 : 365))
		return arg_error();
	return cob_d_int(days_before_year(y) + dd);
}

cob_dec cob_fn_day_of_integer(cob_dec a)
{
	cob_s64 n = cob_d_to_int(a);
	if (n < 1 || n > 3067671)
		return arg_error();
	int y = 1601;
	while (n > (leap(y) ? 366 : 365)) {
		n -= leap(y) ? 366 : 365;
		y++;
	}
	return cob_d_int((cob_s64)y * 1000 + n);
}

cob_dec cob_fn_test_date(cob_dec a)
{
	cob_s64 d = cob_d_to_int(a);
	int y = (int)(d / 10000), m = (int)(d / 100 % 100), dd = (int)(d % 100);
	if (y < 1601 || y > 9999)
		return cob_d_int(1);
	if (m < 1 || m > 12)
		return cob_d_int(2);
	if (dd < 1 || dd > mdays[m - 1] + (m == 2 && leap(y)))
		return cob_d_int(3);
	return cob_d_int(0);
}

cob_dec cob_fn_test_day(cob_dec a)
{
	cob_s64 d = cob_d_to_int(a);
	int y = (int)(d / 1000), dd = (int)(d % 1000);
	if (y < 1601 || y > 9999)
		return cob_d_int(1);
	if (dd < 1 || dd > (leap(y) ? 366 : 365))
		return cob_d_int(2);
	return cob_d_int(0);
}

static int current_year(void)
{
	struct tm tm;
	cob_now(&tm, NULL, NULL);
	return tm.tm_year + 1900;
}

static cob_s64 window_year(cob_s64 yy, int n, cob_dec win, cob_dec yr)
{
	cob_s64 w = n >= 2 ? cob_d_to_int(win) : 50;
	cob_s64 cy = n >= 3 ? cob_d_to_int(yr) : current_year();
	cob_s64 maxy = cy + w;
	cob_s64 y = (maxy / 100) * 100 + yy;
	if (y > maxy)
		y -= 100;
	return y;
}

cob_dec cob_fn_year_to_yyyy(int n, cob_dec a, cob_dec b, cob_dec c)
{
	return cob_d_int(window_year(cob_d_to_int(a) % 100, n, b, c));
}

cob_dec cob_fn_date_to_yyyymmdd(int n, cob_dec a, cob_dec b, cob_dec c)
{
	cob_s64 d = cob_d_to_int(a);
	cob_s64 y = window_year(d / 10000, n, b, c);
	return cob_d_int(y * 10000 + d % 10000);
}

cob_dec cob_fn_day_to_yyyyddd(int n, cob_dec a, cob_dec b, cob_dec c)
{
	cob_s64 d = cob_d_to_int(a);
	cob_s64 y = window_year(d / 1000, n, b, c);
	return cob_d_int(y * 1000 + d % 1000);
}

cob_dec cob_fn_seconds_past_midnight(void)
{
	struct tm tm;
	cob_now(&tm, NULL, NULL);
	return cob_d_int(tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec);
}

/* ---------------------------------------------------------------- alphanumeric */

static cob_field *copy_text(const cob_field *f)
{
	unsigned char b[4096];
	size_t n;
	if (f->attr->type == COB_ALL || f->attr->type == COB_GROUP || !cob_is_num_type(f->attr->type)) {
		cob_field *r = cob_tmp_field(f->size, &cob_attr_alnum);
		memcpy(r->data, f->data, f->size);
		return r;
	}
	n = cob_field_text(f, b, sizeof b);
	cob_field *r = cob_tmp_field(n, &cob_attr_alnum);
	memcpy(r->data, b, n);
	return r;
}

cob_field *cob_fn_upper(const cob_field *f)
{
	cob_field *r = copy_text(f);
	for (size_t i = 0; i < r->size; i++)
		r->data[i] = (unsigned char)toupper(r->data[i]);
	return r;
}

cob_field *cob_fn_lower(const cob_field *f)
{
	cob_field *r = copy_text(f);
	for (size_t i = 0; i < r->size; i++)
		r->data[i] = (unsigned char)tolower(r->data[i]);
	return r;
}

cob_field *cob_fn_reverse(const cob_field *f)
{
	cob_field *r = copy_text(f);
	for (size_t i = 0, j = r->size; i + 1 < j; i++, j--) {
		unsigned char t = r->data[i];
		r->data[i] = r->data[j - 1];
		r->data[j - 1] = t;
	}
	return r;
}

/* mode: 0 both, 1 leading, 2 trailing */
cob_field *cob_fn_trim(const cob_field *f, int mode)
{
	cob_field *t = copy_text(f);
	size_t s = 0, e = t->size;
	if (mode != 2)
		while (s < e && t->data[s] == ' ')
			s++;
	if (mode != 1)
		while (e > s && t->data[e - 1] == ' ')
			e--;
	cob_field *r = cob_tmp_field(e - s, &cob_attr_alnum);
	memcpy(r->data, t->data + s, e - s);
	return r;
}

cob_field *cob_fn_char(cob_dec a)
{
	cob_s64 n = cob_d_to_int(a);
	cob_field *r = cob_tmp_field(1, &cob_attr_alnum);
	r->data[0] = (unsigned char)((n - 1) & 0xFF);
	return r;
}

cob_field *cob_fn_current_date(void)
{
	struct tm tm;
	int hs;
	long off;
	char buf[96];
	cob_now(&tm, &hs, &off);
	char sg = off < 0 ? '-' : '+';
	if (off < 0)
		off = -off;
	snprintf(buf, sizeof buf, "%04d%02d%02d%02d%02d%02d%02d%c%02ld%02ld",
		 tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec,
		 hs, sg, off / 60, off % 60);
	cob_field *r = cob_tmp_field(21, &cob_attr_alnum);
	memcpy(r->data, buf, 21);
	return r;
}

const char *cob_when_compiled = "";

cob_field *cob_fn_when_compiled(void)
{
	size_t n = strlen(cob_when_compiled);
	cob_field *r = cob_tmp_field(n, &cob_attr_alnum);
	memcpy(r->data, cob_when_compiled, n);
	return r;
}

cob_field *cob_fn_module_name(const char *name)
{
	size_t n = strlen(name);
	cob_field *r = cob_tmp_field(n, &cob_attr_alnum);
	memcpy(r->data, name, n);
	return r;
}

cob_field *cob_fn_concatenate(int n, cob_field **f)
{
	unsigned char b[4096];
	size_t total = 0;
	for (int i = 0; i < n; i++) {
		size_t l = f[i]->size;
		if (cob_is_num_type(f[i]->attr->type))
			l = cob_field_text(f[i], b, sizeof b);
		total += l;
	}
	cob_field *r = cob_tmp_field(total, &cob_attr_alnum);
	size_t o = 0;
	for (int i = 0; i < n; i++) {
		if (cob_is_num_type(f[i]->attr->type)) {
			size_t l = cob_field_text(f[i], b, sizeof b);
			memcpy(r->data + o, b, l);
			o += l;
		} else {
			memcpy(r->data + o, f[i]->data, f[i]->size);
			o += f[i]->size;
		}
	}
	return r;
}

static cob_field *substitute(int n, cob_field **f, int nocase);

cob_field *cob_fn_substitute(int n, cob_field **f)
{
	return substitute(n, f, 0);
}

/* SUBSTITUTE-CASE: SUBSTITUTE matching regardless of case */
cob_field *cob_fn_substitute_case(int n, cob_field **f)
{
	return substitute(n, f, 1);
}

static int match_at(const unsigned char *s, const unsigned char *pat, size_t n, int nocase)
{
	if (!nocase)
		return memcmp(s, pat, n) == 0;
	for (size_t i = 0; i < n; i++)
		if (toupper(s[i]) != toupper(pat[i]))
			return 0;
	return 1;
}

static cob_field *substitute(int n, cob_field **f, int nocase)
{
	/* f[0] = source, then pairs (from, to) */
	const cob_field *src = f[0];
	size_t cap = src->size * 4 + 64, o = 0;
	unsigned char *out = cob_malloc(cap);
	size_t i = 0;
	while (i < src->size) {
		int done = 0;
		for (int k = 1; k + 1 < n; k += 2) {
			const cob_field *a = f[k], *b = f[k + 1];
			if (a->size && i + a->size <= src->size && match_at(src->data + i, a->data, a->size, nocase)) {
				if (o + b->size >= cap) {
					cap = (cap + b->size) * 2;
					out = realloc(out, cap);
				}
				memcpy(out + o, b->data, b->size);
				o += b->size;
				i += a->size;
				done = 1;
				break;
			}
		}
		if (!done) {
			if (o + 1 >= cap) {
				cap *= 2;
				out = realloc(out, cap);
			}
			out[o++] = src->data[i++];
		}
	}
	cob_field *r = cob_tmp_field(o, &cob_attr_alnum);
	memcpy(r->data, out, o);
	free(out);
	return r;
}

cob_field *cob_fn_hex_of(const cob_field *f)
{
	static const char hx[] = "0123456789ABCDEF";
	cob_field *r = cob_tmp_field(f->size * 2, &cob_attr_alnum);
	for (size_t i = 0; i < f->size; i++) {
		r->data[2 * i] = (unsigned char)hx[f->data[i] >> 4];
		r->data[2 * i + 1] = (unsigned char)hx[f->data[i] & 15];
	}
	return r;
}

/* ================================================================ COBOL 2023 / IBM 6.4
 *
 * HEX-TO-CHAR undoes HEX-OF; BIT-OF and BIT-TO-CHAR are the same for bits.
 * UUID4 is a random (version 4) UUID, as Enterprise COBOL writes one.
 */
static int hexval(unsigned char c)
{
	return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
	       c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* the bytes a string of hex digit pairs stands for; a digit that isn't one
 * counts as 0, a trailing odd digit as its high half */
cob_field *cob_fn_hex_to_char(const cob_field *f)
{
	size_t n = f->size;
	while (n > 0 && f->data[n - 1] == ' ')
		n--;
	cob_field *r = cob_tmp_field((n + 1) / 2, &cob_attr_alnum);
	for (size_t i = 0; i < r->size; i++) {
		int hi = hexval(f->data[2 * i]);
		int lo = 2 * i + 1 < n ? hexval(f->data[2 * i + 1]) : 0;
		r->data[i] = (unsigned char)(((hi < 0 ? 0 : hi) << 4) | (lo < 0 ? 0 : lo));
	}
	return r;
}

cob_field *cob_fn_bit_of(const cob_field *f)
{
	cob_field *r = cob_tmp_field(f->size * 8, &cob_attr_alnum);
	for (size_t i = 0; i < f->size; i++)
		for (int b = 0; b < 8; b++)
			r->data[8 * i + (size_t)b] = (f->data[i] >> (7 - b)) & 1 ? '1' : '0';
	return r;
}

/* the bytes a string of 0 and 1 stands for, eight bits a byte (the last one
 * filled out with zeros) */
cob_field *cob_fn_bit_to_char(const cob_field *f)
{
	size_t n = f->size;
	while (n > 0 && f->data[n - 1] == ' ')
		n--;
	cob_field *r = cob_tmp_field((n + 7) / 8, &cob_attr_alnum);
	memset(r->data, 0, r->size);
	for (size_t i = 0; i < n; i++)
		if (f->data[i] == '1')
			r->data[i / 8] |= (unsigned char)(0x80 >> (i % 8));
	return r;
}

cob_field *cob_fn_uuid4(void)
{
	unsigned char b[16];
	FILE *fp = fopen("/dev/urandom", "rb");
	size_t got = fp ? fread(b, 1, sizeof b, fp) : 0;
	if (fp)
		fclose(fp);
	if (got != sizeof b) {
		/* no /dev/urandom: the clock and the process, mixed */
		struct timeval tv;
		gettimeofday(&tv, NULL);
		unsigned long long x = (unsigned long long)tv.tv_sec * 1000003u ^ (unsigned long long)tv.tv_usec ^
				       ((unsigned long long)getpid() << 32);
		for (size_t i = 0; i < sizeof b; i++) {
			x ^= x << 13;
			x ^= x >> 7;
			x ^= x << 17;
			b[i] = (unsigned char)(x >> 24);
		}
	}
	b[6] = (unsigned char)((b[6] & 0x0F) | 0x40);      /* version 4 */
	b[8] = (unsigned char)((b[8] & 0x3F) | 0x80);      /* the RFC 4122 variant */
	static const char hx[] = "0123456789abcdef";
	cob_field *r = cob_tmp_field(36, &cob_attr_alnum);
	size_t o = 0;
	for (int i = 0; i < 16; i++) {
		if (i == 4 || i == 6 || i == 8 || i == 10)
			r->data[o++] = '-';
		r->data[o++] = (unsigned char)hx[b[i] >> 4];
		r->data[o++] = (unsigned char)hx[b[i] & 15];
	}
	return r;
}

/* ---------------------------------------------------------------- UTF-8
 *
 * Enterprise COBOL's functions for UTF-8 data in alphanumeric items: ULENGTH
 * counts characters, UPOS gives the byte where the nth begins and UWIDTH its
 * bytes, USUBSTR takes characters, UVALID gives the byte of the first that
 * isn't valid UTF-8 (0 when all are) and USUPPLEMENTARY the byte of the first
 * outside the Basic Multilingual Plane (four bytes; 0 when there is none). A
 * byte that doesn't begin a valid character counts as one character.
 */
static int u8_len(const unsigned char *p, size_t n)
{
	unsigned c = p[0], cp;
	int len;
	if (c < 0x80)
		return 1;
	if (c >= 0xC2 && c <= 0xDF) {
		len = 2;
		cp = c & 0x1F;
	} else if (c >= 0xE0 && c <= 0xEF) {
		len = 3;
		cp = c & 0x0F;
	} else if (c >= 0xF0 && c <= 0xF4) {
		len = 4;
		cp = c & 0x07;
	} else {
		return 0;
	}
	if ((size_t)len > n)
		return 0;
	for (int i = 1; i < len; i++) {
		if ((p[i] & 0xC0) != 0x80)
			return 0;
		cp = cp << 6 | (p[i] & 0x3F);
	}
	if (len == 3 && (cp < 0x800 || (cp >= 0xD800 && cp <= 0xDFFF)))
		return 0;
	if (len == 4 && (cp < 0x10000 || cp > 0x10FFFF))
		return 0;
	return len;
}

static size_t u8_step(const unsigned char *p, size_t n)
{
	int l = u8_len(p, n);
	return l ? (size_t)l : 1;
}

/* the byte offset of character k (0-based) and its width; -1 past the end */
static long u8_offset(const cob_field *f, cob_s64 k, size_t *width)
{
	size_t i = 0;
	for (cob_s64 c = 0; i < f->size; c++) {
		size_t w = u8_step(f->data + i, f->size - i);
		if (c == k) {
			if (width)
				*width = w;
			return (long)i;
		}
		i += w;
	}
	return -1;
}

cob_dec cob_fn_ulength(const cob_field *f)
{
	cob_s64 c = 0;
	for (size_t i = 0; i < f->size; c++)
		i += u8_step(f->data + i, f->size - i);
	return cob_d_int(c);
}

cob_dec cob_fn_upos(const cob_field *f, cob_dec n)
{
	cob_s64 k = cob_d_to_int(n);
	long at = k >= 1 ? u8_offset(f, k - 1, NULL) : -1;
	return cob_d_int(at < 0 ? 0 : at + 1);
}

cob_dec cob_fn_uwidth(const cob_field *f, cob_dec n)
{
	cob_s64 k = cob_d_to_int(n);
	size_t w = 0;
	long at = k >= 1 ? u8_offset(f, k - 1, &w) : -1;
	return cob_d_int(at < 0 ? 0 : (cob_s64)w);
}

cob_field *cob_fn_usubstr(const cob_field *f, cob_dec start, cob_dec count, int has_count)
{
	cob_s64 s = cob_d_to_int(start), m = has_count ? cob_d_to_int(count) : -1;
	long a = s >= 1 ? u8_offset(f, s - 1, NULL) : -1;
	if (a < 0 || (has_count && m <= 0))
		return cob_tmp_field(0, &cob_attr_alnum);
	size_t e = (size_t)a;
	for (cob_s64 c = 0; e < f->size && (m < 0 || c < m); c++)
		e += u8_step(f->data + e, f->size - e);
	cob_field *r = cob_tmp_field(e - (size_t)a, &cob_attr_alnum);
	memcpy(r->data, f->data + a, r->size);
	return r;
}

cob_dec cob_fn_uvalid(const cob_field *f)
{
	for (size_t i = 0; i < f->size;) {
		int l = u8_len(f->data + i, f->size - i);
		if (!l)
			return cob_d_int((cob_s64)i + 1);
		i += (size_t)l;
	}
	return cob_d_int(0);
}

cob_dec cob_fn_usupplementary(const cob_field *f)
{
	for (size_t i = 0; i < f->size;) {
		int l = u8_len(f->data + i, f->size - i);
		if (l == 4)
			return cob_d_int((cob_s64)i + 1);
		i += l ? (size_t)l : 1;
	}
	return cob_d_int(0);
}
