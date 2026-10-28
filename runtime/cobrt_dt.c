/* SPDX-License-Identifier: MIT */
/* cobrt_dt.c - COBOL 2014 date and time functions: FORMATTED-DATE,
 * FORMATTED-TIME, FORMATTED-DATETIME, FORMATTED-CURRENT-DATE,
 * INTEGER-OF-FORMATTED-DATE, SECONDS-FROM-FORMATTED-TIME,
 * TEST-FORMATTED-DATETIME and COMBINED-DATETIME; and the locale functions.
 *
 * Integer dates count days from 1600-12-31 (1 is Monday, 1601-01-01), as
 * INTEGER-OF-DATE does. Formats are the standard's:
 *   dates   YYYYMMDD  YYYY-MM-DD  YYYYDDD  YYYY-DDD  YYYYWwwD  YYYY-Www-D
 *   times   hhmmss[.s...][Z|+hhmm]  hh:mm:ss[.s...][Z|+hh:mm]
 *   both    a date, T, a time
 * with the decimal point given by DECIMAL-POINT IS COMMA.
 */
#define _GNU_SOURCE
#include "cobrt.h"
#include <ctype.h>
#include <locale.h>
#ifdef __APPLE__
#include <xlocale.h>
#endif
#include <time.h>

#define MAX_DATE 3067671        /* 9999-12-31 */

/* ---------------------------------------------------------------- calendar */

static int is_leap(int y)
{
	return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
}

static int month_days(int y, int m)
{
	static const int md[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
	return md[m - 1] + (m == 2 && is_leap(y));
}

/* days from 1600-12-31 to Jan 1 of year y, minus one */
static long days_before(int y)
{
	long n = y - 1601;
	return n * 365 + n / 4 - n / 100 + n / 400;
}

static long int_of_ymd(int y, int m, int d)
{
	long n = days_before(y);
	for (int i = 1; i < m; i++)
		n += month_days(y, i);
	return n + d;
}

static void ymd_of_int(long n, int *y, int *m, int *d, int *doy)
{
	int yy = 1601 + (int)((n - 1) / 366);
	while (days_before(yy + 1) < n)
		yy++;
	int dd = (int)(n - days_before(yy));
	*doy = dd;
	int mm = 1;
	while (dd > month_days(yy, mm)) {
		dd -= month_days(yy, mm);
		mm++;
	}
	*y = yy;
	*m = mm;
	*d = dd;
}

/* 1 = Monday ... 7 = Sunday */
static int weekday(long n)
{
	return (int)((n - 1) % 7) + 1;
}

static int weeks_in_year(int y)
{
	/* 53 weeks when the year starts on a Thursday, or on a Wednesday in a leap year */
	int jan1 = weekday(days_before(y) + 1);
	return (jan1 == 4 || (jan1 == 3 && is_leap(y))) ? 53 : 52;
}

static void iso_week(long n, int *wyear, int *week)
{
	int y, m, d, doy;
	ymd_of_int(n, &y, &m, &d, &doy);
	int w = (doy - weekday(n) + 10) / 7;
	if (w < 1) {
		y--;
		w = weeks_in_year(y);
	} else if (w > weeks_in_year(y)) {
		y++;
		w = 1;
	}
	*wyear = y;
	*week = w;
}

static long int_of_week(int wy, int w, int wd)
{
	long jan4 = days_before(wy) + 4;
	long monday1 = jan4 - (weekday(jan4) - 1);
	return monday1 + (long)(w - 1) * 7 + (wd - 1);
}

/* ---------------------------------------------------------------- formats */

enum {
	K_LIT, K_YEAR, K_MONTH, K_DAY, K_DOY, K_WEEK, K_WDAY, K_HOUR, K_MIN, K_SEC,
	K_FRAC, K_DP, K_Z, K_OSIGN, K_OHOUR, K_OMIN
};

typedef struct {
	int kind, len;
	unsigned char ch;
} dt_tok;

typedef struct {
	dt_tok t[48];
	int n;
	int has_date, has_time, week, has_off, has_z;
} dt_fmt;

static int parse_format(const cob_field *f, int dpc, dt_fmt *F)
{
	const unsigned char *s = f->data;
	size_t n = f->size;
	while (n && s[n - 1] == ' ')
		n--;
	memset(F, 0, sizeof *F);
	int in_off = 0, sec_seen = 0, after_dp = 0;
	size_t i = 0;
#define TOK(k, l, c) do { if (F->n >= 48) return 0; F->t[F->n].kind = (k); F->t[F->n].len = (l); \
		F->t[F->n].ch = (unsigned char)(c); F->n++; } while (0)
	while (i < n) {
		const unsigned char *p = s + i;
		size_t left = n - i;
		if (left >= 4 && !memcmp(p, "YYYY", 4)) {
			TOK(K_YEAR, 4, 0);
			F->has_date = 1;
			i += 4;
		} else if (left >= 2 && !memcmp(p, "MM", 2)) {
			TOK(K_MONTH, 2, 0);
			i += 2;
		} else if (left >= 3 && !memcmp(p, "DDD", 3)) {
			TOK(K_DOY, 3, 0);
			i += 3;
		} else if (left >= 2 && !memcmp(p, "DD", 2)) {
			TOK(K_DAY, 2, 0);
			i += 2;
		} else if (left >= 3 && !memcmp(p, "Www", 3)) {
			TOK(K_LIT, 1, 'W');
			TOK(K_WEEK, 2, 0);
			F->week = 1;
			i += 3;
		} else if (*p == 'D') {
			TOK(K_WDAY, 1, 0);
			i++;
		} else if (left >= 2 && !memcmp(p, "hh", 2)) {
			TOK(in_off ? K_OHOUR : K_HOUR, 2, 0);
			if (!in_off)
				F->has_time = 1;
			i += 2;
		} else if (left >= 2 && !memcmp(p, "mm", 2)) {
			TOK(in_off ? K_OMIN : K_MIN, 2, 0);
			i += 2;
		} else if (*p == 's' && after_dp) {
			size_t k = 0;
			while (k < left && p[k] == 's')
				k++;
			if (k > 9)
				return 0;
			TOK(K_FRAC, (int)k, 0);
			after_dp = 0;
			i += k;
		} else if (left >= 2 && !memcmp(p, "ss", 2) && !sec_seen) {
			TOK(K_SEC, 2, 0);
			sec_seen = 1;
			i += 2;
		} else if (*p == (dpc ? ',' : '.') && sec_seen) {
			TOK(K_DP, 1, *p);
			after_dp = 1;
			i++;
		} else if (*p == 'Z') {
			TOK(K_Z, 1, 'Z');
			F->has_z = 1;
			i++;
		} else if (*p == '+') {
			TOK(K_OSIGN, 1, '+');
			F->has_off = 1;
			in_off = 1;
			i++;
		} else if (*p == '-' || *p == ':' || *p == 'T') {
			TOK(K_LIT, 1, *p);
			i++;
		} else
			return 0;
	}
#undef TOK
	return F->n > 0 && !after_dp;
}

typedef struct {
	int year, month, day, doy, wyear, week, wday;
	int hour, min, sec;
	char frac[10];
	int osign, ohour, omin;
} dt_val;

static void put_num(unsigned char *o, int v, int len)
{
	for (int k = len - 1; k >= 0; k--) {
		o[k] = (unsigned char)('0' + v % 10);
		v /= 10;
	}
}

static cob_field *format_value(const dt_fmt *F, const dt_val *v)
{
	size_t len = 0;
	for (int i = 0; i < F->n; i++)
		len += (size_t)F->t[i].len;
	cob_field *r = cob_tmp_field(len, &cob_attr_alnum);
	unsigned char *o = r->data;
	for (int i = 0; i < F->n; i++) {
		const dt_tok *t = &F->t[i];
		switch (t->kind) {
		case K_LIT: case K_DP: case K_Z:
			*o = t->ch;
			break;
		case K_YEAR:  put_num(o, F->week ? v->wyear : v->year, 4); break;
		case K_MONTH: put_num(o, v->month, 2); break;
		case K_DAY:   put_num(o, v->day, 2); break;
		case K_DOY:   put_num(o, v->doy, 3); break;
		case K_WEEK:  put_num(o, v->week, 2); break;
		case K_WDAY:  put_num(o, v->wday, 1); break;
		case K_HOUR:  put_num(o, v->hour, 2); break;
		case K_MIN:   put_num(o, v->min, 2); break;
		case K_SEC:   put_num(o, v->sec, 2); break;
		case K_FRAC:  memcpy(o, v->frac, (size_t)t->len); break;
		case K_OSIGN: *o = v->osign < 0 ? '-' : '+'; break;
		case K_OHOUR: put_num(o, v->ohour, 2); break;
		case K_OMIN:  put_num(o, v->omin, 2); break;
		}
		o += t->len;
	}
	return r;
}

static void set_date(dt_val *v, long n)
{
	ymd_of_int(n, &v->year, &v->month, &v->day, &v->doy);
	iso_week(n, &v->wyear, &v->week);
	v->wday = weekday(n);
}

/* seconds past midnight (with fraction) into the time fields; 0 if out of range */
static int set_time(dt_val *v, cob_dec secs)
{
	if (secs.scale == COB_DEC_ERR || secs.v < 0)
		return 0;
	while (secs.scale < 0) {
		secs.v *= 10;
		secs.scale++;
	}
	cob_s128 p = 1;
	for (int i = 0; i < secs.scale; i++)
		p *= 10;
	cob_s128 whole = secs.v / p, frac = secs.v % p;
	if (whole >= 86400)
		return 0;
	v->hour = (int)(whole / 3600);
	v->min = (int)(whole / 60 % 60);
	v->sec = (int)(whole % 60);
	/* fraction digits, truncated to nine */
	char buf[64];
	int sc = secs.scale;
	for (int i = 0; i < 9; i++) {
		int digit = 0;
		if (i < sc) {
			cob_s128 q = p;
			for (int k = 0; k <= i; k++)
				q /= 10;
			digit = (int)(frac / q % 10);
		}
		buf[i] = (char)('0' + digit);
	}
	memcpy(v->frac, buf, 9);
	v->frac[9] = 0;
	return 1;
}

static cob_field *spaces_result(const dt_fmt *F, size_t fallback)
{
	size_t len = 0;
	for (int i = 0; F && i < F->n; i++)
		len += (size_t)F->t[i].len;
	if (!len)
		len = fallback;
	return cob_tmp_field(len, &cob_attr_alnum);    /* space-filled */
}

static int get_offset(int has_off, cob_dec off, int *minutes)
{
	*minutes = 0;
	if (!has_off)
		return 1;
	if (has_off == 2) {             /* SYSTEM-OFFSET */
		struct tm tm;
		long o;
		cob_now(&tm, NULL, &o);
		*minutes = (int)o;
		return 1;
	}
	if (off.scale == COB_DEC_ERR)
		return 0;
	cob_s64 m = cob_d_to_int(off);
	if (m < -1439 || m > 1439)
		return 0;
	*minutes = (int)m;
	return 1;
}

/* apply the offset: for Z formats the time is shifted to UTC (and the date
   with it); +hhmm formats show the offset */
static void apply_offset(const dt_fmt *F, dt_val *v, long *date, int minutes)
{
	v->osign = minutes < 0 ? -1 : 1;
	int a = minutes < 0 ? -minutes : minutes;
	v->ohour = a / 60;
	v->omin = a % 60;
	if (F->has_z && minutes) {
		long t = (long)v->hour * 3600 + v->min * 60 + v->sec - (long)minutes * 60;
		while (t < 0) {
			t += 86400;
			if (date)
				(*date)--;
		}
		while (t >= 86400) {
			t -= 86400;
			if (date)
				(*date)++;
		}
		v->hour = (int)(t / 3600);
		v->min = (int)(t / 60 % 60);
		v->sec = (int)(t % 60);
	}
}

cob_field *cob_fn_formatted_date(const cob_field *fmt, cob_dec date, int dpc)
{
	dt_fmt F;
	dt_val v;
	memset(&v, 0, sizeof v);
	cob_s64 n = date.scale == COB_DEC_ERR ? 0 : cob_d_to_int(date);
	if (!parse_format(fmt, dpc, &F) || !F.has_date || F.has_time || n < 1 || n > MAX_DATE) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return spaces_result(&F, fmt->size);
	}
	set_date(&v, (long)n);
	return format_value(&F, &v);
}

cob_field *cob_fn_formatted_time(const cob_field *fmt, cob_dec secs, int has_off, cob_dec off, int dpc)
{
	dt_fmt F;
	dt_val v;
	int minutes;
	memset(&v, 0, sizeof v);
	if (!parse_format(fmt, dpc, &F) || F.has_date || !F.has_time || !set_time(&v, secs) ||
	    !get_offset(has_off, off, &minutes)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return spaces_result(&F, fmt->size);
	}
	apply_offset(&F, &v, NULL, minutes);
	return format_value(&F, &v);
}

cob_field *cob_fn_formatted_datetime(const cob_field *fmt, cob_dec date, cob_dec secs, int has_off,
				     cob_dec off, int dpc)
{
	dt_fmt F;
	dt_val v;
	int minutes;
	memset(&v, 0, sizeof v);
	cob_s64 n = date.scale == COB_DEC_ERR ? 0 : cob_d_to_int(date);
	if (!parse_format(fmt, dpc, &F) || !F.has_date || !F.has_time || n < 1 || n > MAX_DATE ||
	    !set_time(&v, secs) || !get_offset(has_off, off, &minutes)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return spaces_result(&F, fmt->size);
	}
	long d = (long)n;
	apply_offset(&F, &v, &d, minutes);
	if (d < 1 || d > MAX_DATE) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return spaces_result(&F, fmt->size);
	}
	set_date(&v, d);
	return format_value(&F, &v);
}

cob_field *cob_fn_formatted_current_date(const cob_field *fmt, int dpc)
{
	dt_fmt F;
	dt_val v;
	memset(&v, 0, sizeof v);
	if (!parse_format(fmt, dpc, &F) || !F.has_date || !F.has_time) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return spaces_result(&F, fmt->size);
	}
	struct tm tm;
	int hs;
	long off;
	cob_now(&tm, &hs, &off);
	long d = int_of_ymd(tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday);
	v.hour = tm.tm_hour;
	v.min = tm.tm_min;
	v.sec = tm.tm_sec;
	memset(v.frac, '0', 9);
	v.frac[0] = (char)('0' + hs / 10);
	v.frac[1] = (char)('0' + hs % 10);
	apply_offset(&F, &v, &d, (int)off);
	set_date(&v, d);
	return format_value(&F, &v);
}

/* Checks s against the format. Returns 0 when valid, else the position of the
   first character that can't be part of a valid value (the length + 1 when
   the value ends too early). */
static int check_value(const dt_fmt *F, const unsigned char *s, size_t n, dt_val *v)
{
	size_t p = 0;
	int zero_off = 0;
	memset(v, 0, sizeof *v);
	memset(v->frac, '0', 9);
	for (int i = 0; i < F->n; i++) {
		const dt_tok *t = &F->t[i];
		long lo = 0, hi = 0;
		switch (t->kind) {
		case K_LIT: case K_DP: case K_Z:
			if (p >= n)
				return (int)n + 1;
			if (s[p] != t->ch)
				return (int)p + 1;
			p++;
			continue;
		case K_OSIGN:
			if (p >= n)
				return (int)n + 1;
			if (s[p] == '0')
				zero_off = 1;           /* "0" for "+" when the offset is zero */
			else if (s[p] != '+' && s[p] != '-')
				return (int)p + 1;
			v->osign = s[p] == '-' ? -1 : 1;
			p++;
			continue;
		case K_FRAC:
			for (int k = 0; k < t->len; k++, p++) {
				if (p >= n)
					return (int)n + 1;
				if (!isdigit(s[p]))
					return (int)p + 1;
				v->frac[k] = (char)s[p];
			}
			continue;
		case K_YEAR:  lo = 1601; hi = 9999; break;
		case K_MONTH: lo = 1; hi = 12; break;
		case K_DAY:   lo = 1; hi = v->month ? month_days(v->year ? v->year : 2000, v->month) : 31; break;
		case K_DOY:   lo = 1; hi = v->year && !is_leap(v->year) ? 365 : 366; break;
		case K_WEEK:  lo = 1; hi = v->year ? weeks_in_year(v->year) : 53; break;
		case K_WDAY:  lo = 1; hi = 7; break;
		case K_HOUR:  lo = 0; hi = 23; break;
		case K_MIN:   lo = 0; hi = 59; break;
		case K_SEC:   lo = 0; hi = 59; break;
		case K_OHOUR: lo = 0; hi = zero_off ? 0 : 23; break;
		case K_OMIN:  lo = 0; hi = zero_off ? 0 : 59; break;
		}
		long val = 0, scale = 1;
		for (int k = 1; k < t->len; k++)
			scale *= 10;
		for (int k = 0; k < t->len; k++, p++) {
			if (p >= n)
				return (int)n + 1;
			if (!isdigit(s[p]))
				return (int)p + 1;
			val = val * 10 + (s[p] - '0');
			long low = val * scale, high = (val + 1) * scale - 1;
			if (high < lo || low > hi)
				return (int)p + 1;
			scale /= 10;
		}
		switch (t->kind) {
		case K_YEAR:  v->year = (int)val; break;
		case K_MONTH: v->month = (int)val; break;
		case K_DAY:   v->day = (int)val; break;
		case K_DOY:   v->doy = (int)val; break;
		case K_WEEK:  v->week = (int)val; break;
		case K_WDAY:  v->wday = (int)val; break;
		case K_HOUR:  v->hour = (int)val; break;
		case K_MIN:   v->min = (int)val; break;
		case K_SEC:   v->sec = (int)val; break;
		case K_OHOUR: v->ohour = (int)val; break;
		case K_OMIN:  v->omin = (int)val; break;
		}
	}
	while (p < n && s[p] == ' ')
		p++;
	if (p < n)
		return (int)p + 1;
	return 0;
}

cob_dec cob_fn_test_formatted_datetime(const cob_field *fmt, const cob_field *val, int dpc)
{
	dt_fmt F;
	dt_val v;
	if (!parse_format(fmt, dpc, &F)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_d_int(0);
	}
	return cob_d_int(check_value(&F, val->data, val->size, &v));
}

cob_dec cob_fn_integer_of_formatted_date(const cob_field *fmt, const cob_field *val, int dpc)
{
	dt_fmt F;
	dt_val v;
	if (!parse_format(fmt, dpc, &F) || !F.has_date || check_value(&F, val->data, val->size, &v)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_d_int(0);
	}
	long n;
	if (F.week)
		n = int_of_week(v.year, v.week, v.wday);
	else if (v.doy)
		n = days_before(v.year) + v.doy;
	else
		n = int_of_ymd(v.year, v.month, v.day);
	return cob_d_int(n);
}

cob_dec cob_fn_seconds_from_formatted_time(const cob_field *fmt, const cob_field *val, int dpc)
{
	dt_fmt F;
	dt_val v;
	if (!parse_format(fmt, dpc, &F) || !F.has_time || check_value(&F, val->data, val->size, &v)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_d_int(0);
	}
	int fd = 0;
	for (int i = 0; i < F.n; i++)
		if (F.t[i].kind == K_FRAC)
			fd = F.t[i].len;
	cob_dec r;
	r.v = (cob_s128)v.hour * 3600 + v.min * 60 + v.sec;
	r.scale = fd;
	for (int k = 0; k < fd; k++)
		r.v = r.v * 10 + (v.frac[k] - '0');
	return r;
}

/* COMBINED-DATETIME: integer date + seconds / 100000 */
cob_dec cob_fn_combined_datetime(cob_dec date, cob_dec secs)
{
	cob_s64 n = date.scale == COB_DEC_ERR ? 0 : cob_d_to_int(date);
	if (n < 1 || n > MAX_DATE || secs.scale == COB_DEC_ERR || secs.v < 0 ||
	    cob_d_cmp(secs, cob_d_int(86400)) > 0) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_d_int(0);
	}
	cob_dec s = secs;
	s.scale += 5;
	return cob_d_add(cob_d_int(n), s);
}

/* ---------------------------------------------------------------- locale */

static locale_t user_locale(void)
{
	static locale_t loc;
	static int tried;
	if (!tried) {
		tried = 1;
		loc = newlocale(LC_ALL_MASK, "", (locale_t)0);
		if (!loc)
			loc = newlocale(LC_ALL_MASK, "C", (locale_t)0);
	}
	return loc;
}

static cob_field *text_result(const char *s)
{
	size_t n = strlen(s);
	cob_field *r = cob_tmp_field(n ? n : 1, &cob_attr_alnum);
	memcpy(r->data, s, n);
	return r;
}

static char *field_cstr(const cob_field *f)
{
	unsigned char b[1024];
	size_t n = cob_field_text(f, b, sizeof b - 1);
	char *s = cob_malloc(n + 1);
	memcpy(s, b, n);
	while (n && s[n - 1] == ' ')
		n--;
	s[n] = 0;
	return s;
}

/* LOCALE-COMPARE: "<", "=" or ">" in the collating order of the user's locale */
cob_field *cob_fn_locale_compare(const cob_field *a, const cob_field *b)
{
	char *x = field_cstr(a), *y = field_cstr(b);
	locale_t loc = user_locale();
	int c = loc ? strcoll_l(x, y, loc) : strcmp(x, y);
	free(x);
	free(y);
	return text_result(c < 0 ? "<" : c > 0 ? ">" : "=");
}

static cob_field *locale_strftime(const char *fmt, const struct tm *tm)
{
	char buf[256];
	locale_t loc = user_locale();
	size_t n = loc ? strftime_l(buf, sizeof buf, fmt, tm, loc) : strftime(buf, sizeof buf, fmt, tm);
	buf[n] = 0;
	return text_result(buf);
}

static long digits_of(const cob_field *f, int *ok)
{
	if (cob_is_num_type(f->attr->type)) {
		*ok = 1;
		return (long)cob_d_to_int(cob_d_get(f));
	}
	long v = 0;
	int nd = 0;
	*ok = 1;
	for (size_t i = 0; i < f->size; i++) {
		if (f->data[i] == ' ')
			continue;
		if (!isdigit(f->data[i])) {
			*ok = 0;
			return 0;
		}
		v = v * 10 + (f->data[i] - '0');
		nd++;
	}
	if (!nd)
		*ok = 0;
	return v;
}

/* LOCALE-DATE: a YYYYMMDD date in the locale's date format */
cob_field *cob_fn_locale_date(const cob_field *f)
{
	int ok;
	long d = digits_of(f, &ok);
	int y = (int)(d / 10000), m = (int)(d / 100 % 100), dd = (int)(d % 100);
	if (!ok || y < 1601 || y > 9999 || m < 1 || m > 12 || dd < 1 || dd > month_days(y, m)) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_tmp_field(1, &cob_attr_alnum);
	}
	struct tm tm;
	memset(&tm, 0, sizeof tm);
	tm.tm_year = y - 1900;
	tm.tm_mon = m - 1;
	tm.tm_mday = dd;
	tm.tm_wday = weekday(int_of_ymd(y, m, dd)) % 7;
	tm.tm_yday = (int)(int_of_ymd(y, m, dd) - days_before(y)) - 1;
	return locale_strftime("%x", &tm);
}

static cob_field *locale_time_of(long secs)
{
	struct tm tm;
	memset(&tm, 0, sizeof tm);
	tm.tm_hour = (int)(secs / 3600);
	tm.tm_min = (int)(secs / 60 % 60);
	tm.tm_sec = (int)(secs % 60);
	tm.tm_mday = 1;
	tm.tm_year = 100;
	return locale_strftime("%X", &tm);
}

/* LOCALE-TIME: an hhmmss time in the locale's time format */
cob_field *cob_fn_locale_time(const cob_field *f)
{
	int ok;
	long t = digits_of(f, &ok);
	int h = (int)(t / 10000), m = (int)(t / 100 % 100), s = (int)(t % 100);
	if (!ok || h > 23 || m > 59 || s > 59) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_tmp_field(1, &cob_attr_alnum);
	}
	return locale_time_of((long)h * 3600 + m * 60 + s);
}

cob_field *cob_fn_locale_time_from_seconds(cob_dec secs)
{
	cob_s64 s = secs.scale == COB_DEC_ERR ? -1 : cob_d_to_int(secs);
	if (s < 0 || s >= 86400) {
		cob_set_exception("EC-ARGUMENT-FUNCTION");
		return cob_tmp_field(1, &cob_attr_alnum);
	}
	return locale_time_of((long)s);
}

/* which: 0 CURRENCY-SYMBOL, 1 MONETARY-DECIMAL-POINT, 2 MONETARY-THOUSANDS-SEPARATOR,
   3 NUMERIC-DECIMAL-POINT, 4 NUMERIC-THOUSANDS-SEPARATOR */
cob_field *cob_fn_locale_info(int which)
{
	locale_t loc = user_locale();
	locale_t old = loc ? uselocale(loc) : (locale_t)0;
	struct lconv *lc = localeconv();
	const char *s = "";
	switch (which) {
	case 0: s = lc->currency_symbol; break;
	case 1: s = lc->mon_decimal_point; break;
	case 2: s = lc->mon_thousands_sep; break;
	case 3: s = lc->decimal_point; break;
	case 4: s = lc->thousands_sep; break;
	}
	cob_field *r = text_result(s ? s : "");
	if (loc)
		uselocale(old);
	return r;
}
