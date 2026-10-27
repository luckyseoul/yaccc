/* cobrt_fn.c - intrinsic functions */
#include "cobrt.h"
#include <ctype.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>

static long double to_ld(cob_dec d)
{
	long double x = (long double)d.v;
	if (d.scale > 0)
		x /= powl(10.0L, d.scale);
	else if (d.scale < 0)
		x *= powl(10.0L, -d.scale);
	return x;
}

static cob_dec from_ld(long double x)
{
	char buf[80];
	if (isnan(x) || isinf(x))
		return cob_d_err();
	snprintf(buf, sizeof buf, "%.17Le", x);
	char *e = strchr(buf, 'e');
	int expo = atoi(e + 1);
	*e = 0;
	cob_dec r = cob_d_str(buf);
	r.scale -= expo;
	if (r.scale < 0) {
		while (r.scale < 0) {
			r.v *= 10;
			r.scale++;
		}
	}
	while (r.scale > 0 && r.v % 10 == 0) {
		r.v /= 10;
		r.scale--;
	}
	if (r.scale > 38) {
		cob_dec t = r;
		while (t.scale > 38) {
			t.v /= 10;
			t.scale--;
		}
		r = t;
	}
	return r;
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
	if (b.v == 0)
		return cob_d_err();
	cob_dec q = cob_fn_integer(cob_d_div(a, b));
	return cob_d_sub(a, cob_d_mul(b, q));
}

cob_dec cob_fn_rem(cob_dec a, cob_dec b)
{
	if (b.v == 0)
		return cob_d_err();
	cob_dec q = cob_d_trunc(cob_d_div(a, b), 0);
	return cob_d_sub(a, cob_d_mul(b, q));
}

cob_dec cob_fn_sign(cob_dec a)
{
	return cob_d_int(cob_d_sign(a));
}

cob_dec cob_fn_sqrt(cob_dec a)
{
	if (a.scale == COB_DEC_ERR || a.v < 0)
		return cob_d_err();
	if (a.v == 0)
		return cob_d_int(0);
	/* Newton iteration in decimal starting from long double estimate */
	cob_dec x = from_ld(sqrtl(to_ld(a)));
	cob_dec two = cob_d_int(2);
	for (int i = 0; i < 3; i++) {
		cob_dec nx = cob_d_div(cob_d_add(x, cob_d_div(a, x)), two);
		if (nx.scale == COB_DEC_ERR)
			break;
		if (nx.scale > 34)
			nx = cob_d_trunc(nx, 34);
		x = nx;
	}
	return x;
}

cob_dec cob_fn_math(int which, cob_dec a)
{
	long double x = to_ld(a), r;
	switch (which) {
	case 0: r = expl(x); break;
	case 1: r = powl(10.0L, x); break;
	case 2: if (x <= 0) return cob_d_err(); r = logl(x); break;
	case 3: if (x <= 0) return cob_d_err(); r = log10l(x); break;
	case 4: r = sinl(x); break;
	case 5: r = cosl(x); break;
	case 6: r = tanl(x); break;
	case 7: if (x < -1 || x > 1) return cob_d_err(); r = asinl(x); break;
	case 8: if (x < -1 || x > 1) return cob_d_err(); r = acosl(x); break;
	case 9: r = atanl(x); break;
	default: return cob_d_err();
	}
	return from_ld(r);
}

cob_dec cob_fn_pi(void)
{
	return cob_d_str("3.1415926535897932384626433832795028842");
}

cob_dec cob_fn_e(void)
{
	return cob_d_str("2.7182818284590452353602874713526624978");
}

cob_dec cob_fn_factorial(cob_dec a)
{
	if (a.scale == COB_DEC_ERR)
		return a;
	cob_s64 n = cob_d_to_int(a);
	if (n < 0 || n > 33)
		return cob_d_err();
	cob_s128 r = 1;
	for (cob_s64 i = 2; i <= n; i++)
		r *= i;
	cob_dec d;
	d.v = r;
	d.scale = 0;
	return d;
}

static int rnd_seeded;

cob_dec cob_fn_random(int has_seed, cob_dec seed)
{
	if (has_seed) {
		srand48((long)cob_d_to_int(seed));
		rnd_seeded = 1;
	} else if (!rnd_seeded) {
		srand48(0);
		rnd_seeded = 1;
	}
	double x = drand48();
	cob_dec r = from_ld((long double)x);
	return cob_d_trunc(r, 15);
}

cob_dec cob_fn_length(const cob_field *f)
{
	return cob_d_int((cob_s64)f->size);
}

cob_dec cob_fn_ord(const cob_field *f)
{
	return cob_d_int(f->size ? f->data[0] + 1 : 1);
}

static cob_dec numval_impl(const unsigned char *s, size_t n, int currency, unsigned char cur)
{
	size_t i = 0;
	int neg = 0, after = 0, scale = 0;
	cob_s128 v = 0;
	int nd = 0;
	while (i < n && s[i] == ' ')
		i++;
	if (i < n && (s[i] == '+' || s[i] == '-')) {
		neg = s[i] == '-';
		i++;
		while (i < n && s[i] == ' ')
			i++;
	}
	if (currency && i < n && s[i] == cur) {
		i++;
		while (i < n && s[i] == ' ')
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
			}
		} else if (c == '.') {
			after = 1;
		} else if (c == ',' && currency) {
			continue;
		} else
			break;
	}
	while (i < n && s[i] == ' ')
		i++;
	if (i < n) {
		if (s[i] == '-')
			neg = 1;
		else if (i + 1 < n && ((toupper(s[i]) == 'C' && toupper(s[i + 1]) == 'R') ||
				       (toupper(s[i]) == 'D' && toupper(s[i + 1]) == 'B')))
			neg = 1;
	}
	cob_dec r;
	r.v = neg ? -v : v;
	r.scale = scale;
	return r;
}

cob_dec cob_fn_numval(const cob_field *f)
{
	unsigned char b[256];
	size_t n = cob_field_text(f, b, sizeof b);
	if (cob_is_num_type(f->attr->type))
		return cob_d_get(f);
	return numval_impl(b, n, 0, '$');
}

cob_dec cob_fn_numval_c(const cob_field *f, const cob_field *cur)
{
	unsigned char b[256];
	size_t n = cob_field_text(f, b, sizeof b);
	unsigned char c = '$';
	if (cur && cur->size)
		c = cur->data[0];
	return numval_impl(b, n, 1, c);
}

cob_dec cob_fn_test_numval(const cob_field *f)
{
	const unsigned char *s = f->data;
	size_t n = f->size, i = 0;
	int digits = 0, point = 0, sign = 0;
	while (i < n && s[i] == ' ')
		i++;
	if (i < n && (s[i] == '+' || s[i] == '-')) {
		sign = 1;
		i++;
		while (i < n && s[i] == ' ')
			i++;
	}
	for (; i < n; i++) {
		if (isdigit(s[i]))
			digits++;
		else if (s[i] == '.' && !point)
			point = 1;
		else
			break;
	}
	while (i < n && s[i] == ' ')
		i++;
	if (i < n && !sign) {
		if (s[i] == '+' || s[i] == '-')
			i++;
		else if (i + 1 < n && ((toupper(s[i]) == 'C' && toupper(s[i + 1]) == 'R') ||
				       (toupper(s[i]) == 'D' && toupper(s[i + 1]) == 'B')))
			i += 2;
		while (i < n && s[i] == ' ')
			i++;
	}
	if (i < n)
		return cob_d_int((cob_s64)i + 1);
	if (!digits)
		return cob_d_int((cob_s64)n + 1);
	return cob_d_int(0);
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
	case 6: {
		cob_dec mean = cob_d_div(s, cob_d_int(n));
		cob_dec acc = cob_d_int(0);
		for (int i = 0; i < n; i++) {
			cob_dec d = cob_d_sub(v[i], mean);
			acc = cob_d_add(acc, cob_d_mul(d, d));
		}
		cob_dec var = cob_d_div(acc, cob_d_int(n));
		return which == 5 ? var : cob_fn_sqrt(var);
	}
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

cob_dec cob_fn_annuity(cob_dec rate, cob_dec periods)
{
	if (rate.v == 0)
		return cob_d_div(cob_d_int(1), periods);
	long double r = to_ld(rate), n = to_ld(periods);
	return from_ld(r / (1.0L - powl(1.0L + r, -n)));
}

cob_dec cob_fn_present_value(int n, const cob_dec *v)
{
	cob_dec base = cob_d_add(cob_d_int(1), v[0]);
	cob_dec acc = cob_d_int(0), den = base;
	for (int i = 1; i < n; i++) {
		acc = cob_d_add(acc, cob_d_div(v[i], den));
		den = cob_d_mul(den, base);
	}
	return acc;
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
		return cob_d_int(0);
	int ml = mdays[m - 1] + (m == 2 && leap(y));
	if (dd > ml)
		return cob_d_int(0);
	cob_s64 n = days_before_year(y);
	for (int i = 1; i < m; i++)
		n += mdays[i - 1] + (i == 2 && leap(y));
	return cob_d_int(n + dd);
}

cob_dec cob_fn_date_of_integer(cob_dec a)
{
	cob_s64 n = cob_d_to_int(a);
	if (n < 1 || n > 3067671)
		return cob_d_int(0);
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
		return cob_d_int(0);
	return cob_d_int(days_before_year(y) + dd);
}

cob_dec cob_fn_day_of_integer(cob_dec a)
{
	cob_s64 n = cob_d_to_int(a);
	if (n < 1 || n > 3067671)
		return cob_d_int(0);
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
	time_t t = time(NULL);
	struct tm tm;
	localtime_r(&t, &tm);
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
	time_t t = time(NULL);
	struct tm tm;
	localtime_r(&t, &tm);
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
	struct timeval tv;
	struct tm tm;
	char buf[96];
	gettimeofday(&tv, NULL);
	localtime_r(&tv.tv_sec, &tm);
	long off = tm.tm_gmtoff / 60;
	char sg = off < 0 ? '-' : '+';
	if (off < 0)
		off = -off;
	snprintf(buf, sizeof buf, "%04d%02d%02d%02d%02d%02d%02d%c%02ld%02ld",
		 tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec,
		 (int)(tv.tv_usec / 10000), sg, off / 60, off % 60);
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

cob_field *cob_fn_substitute(int n, cob_field **f)
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
			if (a->size && i + a->size <= src->size && memcmp(src->data + i, a->data, a->size) == 0) {
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
