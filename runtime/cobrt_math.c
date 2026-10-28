/* cobrt_math.c - high-precision evaluation of the transcendental functions
 *
 * SQRT, EXP, EXP10, LOG, LOG10, SIN, COS, TAN, ASIN, ACOS, ATAN, ANNUITY,
 * PRESENT-VALUE, VARIANCE, STANDARD-DEVIATION and non-integer powers are
 * computed in binary fixed point: a sign and a 640-bit magnitude with a
 * 128-bit integer part and a 512-bit (about 154 decimal digits) fraction,
 * enough to keep the smallest cob_dec values (1E-38) precise to far more
 * than 38 digits.
 * Results are truncated to the 38 significant digits a cob_dec holds, so a
 * MOVE to a field with fewer decimals gets the same digits as the exact value.
 */
#include "cobrt.h"
#include <math.h>
#include <stdint.h>

#define NL 10                   /* 64-bit limbs */
#define FL 8                    /* fraction limbs */
#define FBITS (64 * FL)

typedef unsigned __int128 u128;

typedef struct {
	int neg;
	uint64_t l[NL];         /* little-endian magnitude, scaled by 2^FBITS */
} hp;

static int ovf;                 /* set when a result leaves the representable range */

static const uint64_t P10_64[20] = {
	1ULL, 10ULL, 100ULL, 1000ULL, 10000ULL, 100000ULL, 1000000ULL, 10000000ULL,
	100000000ULL, 1000000000ULL, 10000000000ULL, 100000000000ULL, 1000000000000ULL,
	10000000000000ULL, 100000000000000ULL, 1000000000000000ULL, 10000000000000000ULL,
	100000000000000000ULL, 1000000000000000000ULL, 10000000000000000000ULL
};

/* ---------------------------------------------------------------- basics */

static hp hp_zero(void)
{
	hp r;
	memset(&r, 0, sizeof r);
	return r;
}

static hp hp_int(int64_t v)
{
	hp r = hp_zero();
	r.neg = v < 0;
	r.l[FL] = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
	return r;
}

static int hp_is_zero(const hp *a)
{
	for (int i = 0; i < NL; i++)
		if (a->l[i])
			return 0;
	return 1;
}

static int mag_cmp(const hp *a, const hp *b)
{
	for (int i = NL - 1; i >= 0; i--)
		if (a->l[i] != b->l[i])
			return a->l[i] < b->l[i] ? -1 : 1;
	return 0;
}

static void mag_add(hp *r, const hp *a, const hp *b)
{
	u128 c = 0;
	for (int i = 0; i < NL; i++) {
		c += (u128)a->l[i] + b->l[i];
		r->l[i] = (uint64_t)c;
		c >>= 64;
	}
	if (c)
		ovf = 1;
}

/* r = a - b for |a| >= |b| */
static void mag_sub(hp *r, const hp *a, const hp *b)
{
	uint64_t borrow = 0;
	for (int i = 0; i < NL; i++) {
		u128 d = (u128)a->l[i] - b->l[i] - borrow;
		r->l[i] = (uint64_t)d;
		borrow = (uint64_t)(d >> 127);
	}
}

static hp hp_add(hp a, hp b)
{
	hp r;
	if (a.neg == b.neg) {
		mag_add(&r, &a, &b);
		r.neg = a.neg;
	} else if (mag_cmp(&a, &b) >= 0) {
		mag_sub(&r, &a, &b);
		r.neg = a.neg;
	} else {
		mag_sub(&r, &b, &a);
		r.neg = b.neg;
	}
	if (hp_is_zero(&r))
		r.neg = 0;
	return r;
}

static hp hp_neg(hp a)
{
	a.neg = !a.neg && !hp_is_zero(&a);
	return a;
}

static hp hp_sub(hp a, hp b)
{
	return hp_add(a, hp_neg(b));
}

static int hp_cmp(hp a, hp b)
{
	if (a.neg != b.neg)
		return a.neg ? -1 : 1;
	int c = mag_cmp(&a, &b);
	return a.neg ? -c : c;
}

/* rounded product */
static hp hp_mul(hp a, hp b)
{
	uint64_t p[2 * NL];
	memset(p, 0, sizeof p);
	for (int i = 0; i < NL; i++) {
		if (!a.l[i])
			continue;
		u128 c = 0;
		for (int j = 0; j < NL; j++) {
			c += (u128)a.l[i] * b.l[j] + p[i + j];
			p[i + j] = (uint64_t)c;
			c >>= 64;
		}
		p[i + NL] = (uint64_t)c;
	}
	hp r;
	r.neg = a.neg != b.neg;
	for (int i = 0; i < NL; i++)
		r.l[i] = p[i + FL];
	for (int i = NL + FL; i < 2 * NL; i++)
		if (p[i])
			ovf = 1;
	if (p[FL - 1] >> 63) {
		for (int i = 0; i < NL && ++r.l[i] == 0; i++)
			;
	}
	if (hp_is_zero(&r))
		r.neg = 0;
	return r;
}

static hp hp_mul_small(hp a, uint64_t k)
{
	u128 c = 0;
	for (int i = 0; i < NL; i++) {
		c += (u128)a.l[i] * k;
		a.l[i] = (uint64_t)c;
		c >>= 64;
	}
	if (c)
		ovf = 1;
	if (hp_is_zero(&a))
		a.neg = 0;
	return a;
}

static hp hp_div_small(hp a, uint64_t k)
{
	u128 rem = 0;
	for (int i = NL - 1; i >= 0; i--) {
		rem = (rem << 64) | a.l[i];
		a.l[i] = (uint64_t)(rem / k);
		rem %= k;
	}
	if (hp_is_zero(&a))
		a.neg = 0;
	return a;
}

/* multiply by 2^n (n < 0 divides, truncating) */
static hp hp_shift(hp a, int n)
{
	hp r = hp_zero();
	r.neg = a.neg;
	if (n >= 0) {
		int w = n / 64, b = n % 64;
		for (int i = NL - 1; i >= 0; i--) {
			if (!a.l[i])
				continue;
			int j = i + w;
			uint64_t lo = a.l[i] << b;
			uint64_t hi = b ? a.l[i] >> (64 - b) : 0;
			if (j >= NL || (hi && j + 1 >= NL)) {
				ovf = 1;
				continue;
			}
			r.l[j] |= lo;
			if (hi)
				r.l[j + 1] |= hi;
		}
	} else {
		n = -n;
		int w = n / 64, b = n % 64;
		for (int i = 0; i < NL; i++) {
			int j = i + w;
			if (j >= NL)
				break;
			uint64_t v = a.l[j] >> b;
			if (b && j + 1 < NL)
				v |= a.l[j + 1] << (64 - b);
			r.l[i] = v;
		}
	}
	if (hp_is_zero(&r))
		r.neg = 0;
	return r;
}

/* position of the highest set bit relative to the binary point (2^e <= |a| < 2^(e+1)) */
static int hp_exponent(const hp *a)
{
	for (int i = NL - 1; i >= 0; i--)
		if (a->l[i])
			return 64 * i + 63 - __builtin_clzll(a->l[i]) - FBITS;
	return -FBITS - 1;
}

static double hp_to_double(hp a)
{
	double x = 0;
	for (int i = NL - 1; i >= 0; i--)
		if (a.l[i])
			x += ldexp((double)a.l[i], 64 * (i - FL));
	return a.neg ? -x : x;
}

static hp hp_from_double(double x)
{
	hp r = hp_zero();
	if (x == 0 || !isfinite(x)) {
		if (!isfinite(x))
			ovf = 1;
		return r;
	}
	int e;
	double f = frexp(fabs(x), &e);          /* |x| = f * 2^e, f in [0.5, 1) */
	r.l[0] = (uint64_t)ldexp(f, 64);
	r = hp_shift(r, e - 64 + FBITS);
	r.neg = x < 0 && !hp_is_zero(&r);
	return r;
}

static hp hp_from_dec(cob_dec d)
{
	hp r = hp_zero();
	u128 u = d.v < 0 ? (u128)0 - (u128)d.v : (u128)d.v;
	r.l[FL] = (uint64_t)u;
	r.l[FL + 1] = (uint64_t)(u >> 64);
	int s = d.scale;
	while (s > 0) {
		int k = s > 19 ? 19 : s;
		r = hp_div_small(r, P10_64[k]);
		s -= k;
	}
	while (s < 0) {
		int k = -s > 19 ? 19 : -s;
		r = hp_mul_small(r, P10_64[k]);
		s += k;
	}
	r.neg = d.v < 0 && !hp_is_zero(&r);
	return r;
}

/* 38 significant digits (at most 38 decimals), truncated. A value within a
   relative 2^-280 below a decimal boundary is taken as the boundary: that is
   far above the error of the computation and far below the distance of any
   inexact result from a 38-digit boundary, so exact results (LOG10 of 1000,
   SQRT of 4, PRESENT-VALUE of 3 2 1) stay exact and everything else is
   truncated as the exact value would be. */
static cob_dec hp_to_dec(hp a)
{
	if (ovf)
		return cob_d_err();
	hp m = a;
	m.neg = 0;
	hp eps = hp_shift(m, -280);
	eps.l[0] |= 1ULL << 12;         /* and at least 2^-500 */
	mag_add(&m, &m, &eps);
	u128 ip = ((u128)m.l[FL + 1] << 64) | m.l[FL];
	int nd = 0;
	for (u128 t = ip; t; t /= 10)
		nd++;
	if (nd > 38)
		return cob_d_err();
	int k = 38 - nd;
	hp y = m;
	for (int kk = k; kk > 0;) {
		int s = kk > 19 ? 19 : kk;
		y = hp_mul_small(y, P10_64[s]);
		kk -= s;
	}
	u128 q = ((u128)y.l[FL + 1] << 64) | y.l[FL];
	cob_dec r;
	r.v = a.neg ? -(cob_s128)q : (cob_s128)q;
	r.scale = k;
	while (r.scale > 0 && r.v % 10 == 0) {
		r.v /= 10;
		r.scale--;
	}
	if (r.v == 0)
		r.scale = 0;
	return r;
}

/* ---------------------------------------------------------------- division, roots */

static hp hp_recip(hp b)
{
	if (hp_is_zero(&b)) {
		ovf = 1;
		return b;
	}
	hp y = hp_from_double(1.0 / hp_to_double(b));
	hp two = hp_int(2);
	for (int i = 0; i < 5; i++)             /* 53 -> 106 -> ... -> 848 bits */
		y = hp_mul(y, hp_sub(two, hp_mul(b, y)));
	return y;
}

static hp hp_div(hp a, hp b)
{
	return hp_mul(a, hp_recip(b));
}

static hp hp_sqrt(hp x)
{
	if (hp_is_zero(&x) || x.neg) {
		if (x.neg)
			ovf = 1;
		return hp_zero();
	}
	/* x = 4^k m with m in [1, 4); inverse square root of m by Newton's
	   method, then one correction on the root */
	int e = hp_exponent(&x);
	int k = e >= 0 ? e / 2 : -((1 - e) / 2);
	hp m = hp_shift(x, -2 * k);
	hp y = hp_from_double(1.0 / sqrt(hp_to_double(m)));
	hp three = hp_int(3);
	for (int i = 0; i < 5; i++)
		y = hp_shift(hp_mul(y, hp_sub(three, hp_mul(m, hp_mul(y, y)))), -1);
	hp s = hp_mul(m, y);
	s = hp_shift(hp_add(s, hp_div(m, s)), -1);
	return hp_shift(s, k);
}

/* ---------------------------------------------------------------- constants */

static int consts_ready;
static hp c_pi, c_half_pi, c_two_over_pi, c_ln2, c_ln10, c_inv_ln10, c_e;

/* atan(1/n) */
static hp atan_inv(uint64_t n)
{
	hp t = hp_div_small(hp_int(1), n);
	hp s = t;
	for (uint64_t k = 1;; k++) {
		t = hp_div_small(t, n * n);
		if (hp_is_zero(&t))
			break;
		hp term = hp_div_small(t, 2 * k + 1);
		s = (k & 1) ? hp_sub(s, term) : hp_add(s, term);
	}
	return s;
}

/* atanh(1/n) */
static hp atanh_inv(uint64_t n)
{
	hp t = hp_div_small(hp_int(1), n);
	hp s = t;
	for (uint64_t k = 1;; k++) {
		t = hp_div_small(t, n * n);
		if (hp_is_zero(&t))
			break;
		s = hp_add(s, hp_div_small(t, 2 * k + 1));
	}
	return s;
}

static hp hp_exp(hp x);

static void init_consts(void)
{
	if (consts_ready)
		return;
	int saved = ovf;
	/* Machin: pi = 16 atan(1/5) - 4 atan(1/239) */
	c_pi = hp_sub(hp_mul_small(atan_inv(5), 16), hp_mul_small(atan_inv(239), 4));
	c_half_pi = hp_shift(c_pi, -1);
	c_two_over_pi = hp_recip(c_half_pi);
	c_ln2 = hp_shift(atanh_inv(3), 1);                                   /* 2 atanh(1/3) */
	c_ln10 = hp_add(hp_mul_small(c_ln2, 3), hp_shift(atanh_inv(9), 1));  /* ln 8 + ln 1.25 */
	c_inv_ln10 = hp_recip(c_ln10);
	consts_ready = 1;
	c_e = hp_exp(hp_int(1));
	ovf = saved;
}

/* ---------------------------------------------------------------- functions */

static hp hp_exp(hp x)
{
	init_consts();
	double xd = hp_to_double(x);
	if (xd > 89.0) {                /* beyond 2^128 */
		ovf = 1;
		return hp_zero();
	}
	if (xd < -360.0)                /* below 2^-512 */
		return hp_zero();
	/* x = k ln2 + r, then r / 2^10 for the series and 10 squarings */
	long k = lround(xd / M_LN2);
	hp kl = hp_mul_small(c_ln2, (uint64_t)labs(k));
	hp r = k < 0 ? hp_add(x, kl) : hp_sub(x, kl);
	r = hp_shift(r, -10);
	hp s = hp_int(1), t = hp_int(1);
	for (uint64_t n = 1;; n++) {
		t = hp_div_small(hp_mul(t, r), n);
		if (hp_is_zero(&t))
			break;
		s = hp_add(s, t);
	}
	for (int i = 0; i < 10; i++)
		s = hp_mul(s, s);
	return hp_shift(s, (int)k);
}

static hp hp_ln(hp x)
{
	init_consts();
	if (x.neg || hp_is_zero(&x)) {
		ovf = 1;
		return hp_zero();
	}
	/* x = 2^e m with m in [0.75, 1.5); ln m = 2 atanh((m - 1) / (m + 1)) */
	int e = hp_exponent(&x);
	hp m = hp_shift(x, -e);
	hp one = hp_int(1);
	if (hp_cmp(m, hp_add(one, hp_shift(one, -1))) >= 0) {
		m = hp_shift(m, -1);
		e++;
	}
	hp z = hp_div(hp_sub(m, one), hp_add(m, one));
	hp z2 = hp_mul(z, z), t = z, s = z;
	for (uint64_t k = 1;; k++) {
		t = hp_mul(t, z2);
		if (hp_is_zero(&t))
			break;
		s = hp_add(s, hp_div_small(t, 2 * k + 1));
	}
	s = hp_shift(s, 1);
	hp el = hp_mul_small(c_ln2, (uint64_t)(e < 0 ? -e : e));
	return e < 0 ? hp_sub(s, el) : hp_add(s, el);
}

static void hp_sincos(hp x, hp *sn, hp *cs)
{
	init_consts();
	int neg = x.neg;
	x.neg = 0;
	/* x = q pi/2 + r, 0 <= r < pi/2 */
	hp q = hp_mul(x, c_two_over_pi);
	u128 qi = ((u128)q.l[FL + 1] << 64) | q.l[FL];
	hp r = hp_sub(x, hp_add(hp_mul_small(c_half_pi, (uint64_t)qi),
				hp_shift(hp_mul_small(c_half_pi, (uint64_t)(qi >> 64)), 64)));
	if (r.neg) {
		r = hp_add(r, c_half_pi);
		qi--;
	} else if (hp_cmp(r, c_half_pi) >= 0) {
		r = hp_sub(r, c_half_pi);
		qi++;
	}
	hp r2 = hp_mul(r, r);
	hp s = r, t = r;
	for (uint64_t k = 1;; k++) {
		t = hp_div_small(hp_mul(t, r2), (2 * k) * (2 * k + 1));
		if (hp_is_zero(&t))
			break;
		s = (k & 1) ? hp_sub(s, t) : hp_add(s, t);
	}
	hp c = hp_int(1);
	t = c;
	for (uint64_t k = 1;; k++) {
		t = hp_div_small(hp_mul(t, r2), (2 * k - 1) * (2 * k));
		if (hp_is_zero(&t))
			break;
		c = (k & 1) ? hp_sub(c, t) : hp_add(c, t);
	}
	switch ((int)(qi & 3)) {
	case 0: *sn = s; *cs = c; break;
	case 1: *sn = c; *cs = hp_neg(s); break;
	case 2: *sn = hp_neg(s); *cs = hp_neg(c); break;
	default: *sn = hp_neg(c); *cs = s; break;
	}
	if (neg)
		*sn = hp_neg(*sn);
}

static hp hp_atan(hp x)
{
	init_consts();
	int neg = x.neg;
	x.neg = 0;
	hp one = hp_int(1);
	int inv = hp_cmp(x, one) > 0;
	if (inv)
		x = hp_recip(x);
	/* atan x = 2 atan(x / (1 + sqrt(1 + x^2))), twice: |x| <= tan(pi/16) */
	for (int i = 0; i < 2; i++)
		x = hp_div(x, hp_add(one, hp_sqrt(hp_add(one, hp_mul(x, x)))));
	hp x2 = hp_mul(x, x), t = x, s = x;
	for (uint64_t k = 1;; k++) {
		t = hp_mul(t, x2);
		if (hp_is_zero(&t))
			break;
		hp term = hp_div_small(t, 2 * k + 1);
		s = (k & 1) ? hp_sub(s, term) : hp_add(s, term);
	}
	s = hp_shift(s, 2);
	if (inv)
		s = hp_sub(c_half_pi, s);
	return neg ? hp_neg(s) : s;
}

static hp hp_asin(hp x)
{
	init_consts();
	hp one = hp_int(1);
	int c = mag_cmp(&x, &one);
	if (c > 0) {
		ovf = 1;
		return hp_zero();
	}
	if (c == 0)
		return x.neg ? hp_neg(c_half_pi) : c_half_pi;
	hp ax = x;
	ax.neg = 0;
	hp d = hp_sqrt(hp_mul(hp_sub(one, ax), hp_add(one, ax)));
	return hp_atan(hp_div(x, d));
}

/* ---------------------------------------------------------------- entry points */

/* an argument outside the function's domain: EC-ARGUMENT-FUNCTION, result zero */
static cob_dec arg_error(void)
{
	cob_set_exception("EC-ARGUMENT-FUNCTION");
	return cob_d_int(0);
}

/* which: 0 EXP, 1 EXP10, 2 LOG, 3 LOG10, 4 SIN, 5 COS, 6 TAN, 7 ASIN, 8 ACOS, 9 ATAN */
cob_dec cob_fn_math(int which, cob_dec a)
{
	if (a.scale == COB_DEC_ERR)
		return a;
	init_consts();
	ovf = 0;
	hp x = hp_from_dec(a), r, s, c;
	switch (which) {
	case 0:
		r = hp_exp(x);
		break;
	case 1: {
		cob_dec n = a;
		while (n.scale > 0 && n.v % 10 == 0) {
			n.v /= 10;
			n.scale--;
		}
		if (n.scale == 0 && n.v >= -38 && n.v <= 37) {         /* exact powers of ten */
			cob_dec p = cob_d_int(1);
			if (n.v < 0)
				p.scale = (int)-n.v;
			else
				for (int i = 0; i < (int)n.v; i++)
					p.v *= 10;
			return p;
		}
		r = hp_exp(hp_mul(x, c_ln10));
		break;
	}
	case 2:
	case 3:
		if (x.neg || hp_is_zero(&x))
			return arg_error();
		r = hp_ln(x);
		if (which == 3)
			r = hp_mul(r, c_inv_ln10);
		break;
	case 4:
		hp_sincos(x, &r, &c);
		break;
	case 5:
		hp_sincos(x, &s, &r);
		break;
	case 6:
		hp_sincos(x, &s, &c);
		r = hp_div(s, c);
		break;
	case 7:
	case 8: {
		hp one = hp_int(1);
		if (mag_cmp(&x, &one) > 0)
			return arg_error();
		r = hp_asin(x);
		if (which == 8)
			r = hp_sub(c_half_pi, r);
		break;
	}
	case 9:
		r = hp_atan(x);
		break;
	default:
		return cob_d_err();
	}
	return hp_to_dec(r);
}

cob_dec cob_fn_sqrt(cob_dec a)
{
	if (a.scale == COB_DEC_ERR)
		return a;
	if (a.v < 0)
		return arg_error();
	ovf = 0;
	return hp_to_dec(hp_sqrt(hp_from_dec(a)));
}

cob_dec cob_fn_pi(void)
{
	init_consts();
	ovf = 0;
	return hp_to_dec(c_pi);
}

cob_dec cob_fn_e(void)
{
	init_consts();
	ovf = 0;
	return hp_to_dec(c_e);
}

/* a ** b for a non-integer exponent */
cob_dec cob_hp_pow(cob_dec a, cob_dec b)
{
	if (a.scale == COB_DEC_ERR || b.scale == COB_DEC_ERR || a.v < 0)
		return cob_d_err();
	if (a.v == 0)
		return b.v > 0 ? cob_d_int(0) : cob_d_err();
	init_consts();
	ovf = 0;
	return hp_to_dec(hp_exp(hp_mul(hp_from_dec(b), hp_ln(hp_from_dec(a)))));
}

/* ANNUITY: rate / (1 - (1 + rate) ** -periods) */
cob_dec cob_fn_annuity(cob_dec rate, cob_dec periods)
{
	if (rate.scale == COB_DEC_ERR || periods.scale == COB_DEC_ERR)
		return cob_d_err();
	init_consts();
	ovf = 0;
	hp r = hp_from_dec(rate), n = hp_from_dec(periods), one = hp_int(1);
	if (hp_is_zero(&n) || n.neg)
		return arg_error();
	if (hp_is_zero(&r))
		return hp_to_dec(hp_recip(n));
	hp base = hp_add(one, r);
	if (base.neg || hp_is_zero(&base))
		return arg_error();
	hp p = hp_exp(hp_neg(hp_mul(n, hp_ln(base))));
	return hp_to_dec(hp_div(r, hp_sub(one, p)));
}

/* PRESENT-VALUE: sum of v[i] / (1 + rate) ** i */
cob_dec cob_fn_present_value(int n, const cob_dec *v)
{
	for (int i = 0; i < n; i++)
		if (v[i].scale == COB_DEC_ERR)
			return cob_d_err();
	ovf = 0;
	hp base = hp_add(hp_int(1), hp_from_dec(v[0]));
	hp den = base, acc = hp_zero();
	for (int i = 1; i < n; i++) {
		acc = hp_add(acc, hp_div(hp_from_dec(v[i]), den));
		den = hp_mul(den, base);
	}
	return hp_to_dec(acc);
}

/* VARIANCE (sd = 0) and STANDARD-DEVIATION (sd = 1) */
cob_dec cob_fn_variance(int n, const cob_dec *v, int sd)
{
	if (n <= 0)
		return cob_d_err();
	for (int i = 0; i < n; i++)
		if (v[i].scale == COB_DEC_ERR)
			return cob_d_err();
	ovf = 0;
	hp s = hp_zero();
	for (int i = 0; i < n; i++)
		s = hp_add(s, hp_from_dec(v[i]));
	hp mean = hp_div_small(s, (uint64_t)n);
	hp acc = hp_zero();
	for (int i = 0; i < n; i++) {
		hp d = hp_sub(hp_from_dec(v[i]), mean);
		acc = hp_add(acc, hp_mul(d, d));
	}
	hp var = hp_div_small(acc, (uint64_t)n);
	return hp_to_dec(sd ? hp_sqrt(var) : var);
}
