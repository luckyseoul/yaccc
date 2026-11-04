/* SPDX-License-Identifier: MIT */
/* cobrt_json.c - JSON GENERATE (COBOL 2014)
 *
 * The compiler knows the data description, so it emits one call per item;
 * this file only formats. The writer stops at the end of the receiving field
 * but keeps counting, because COUNT IN reports the length the document would
 * have had and JSON-CODE reports that it did not fit.
 */
#include "cobrt.h"
#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>

/* JSON-CODE, the special register reporting the last JSON statement */
static unsigned char json_code_data[4];
static const cob_attr attr_json_code = { COB_NUM_BINARY, 9, 0, COB_F_SIGNED, NULL, 0 };
cob_field cob_json_code_reg = { 4, json_code_data, &attr_json_code };

void cob_json_code_reset(void)
{
	cob_set_int(&cob_json_code_reg, 0);
}

int cob_json_code_value(void)
{
	return (int)cob_get_int(&cob_json_code_reg);
}

void cob_json_code_set(int v)
{
	cob_set_int(&cob_json_code_reg, v);
}

void cob_json_init(jsonw *w, cob_field *out)
{
	w->dst = out->data;
	w->cap = out->size;
	w->len = 0;
	w->overflow = 0;
}

static void jput(jsonw *w, int c)
{
	if (w->len < w->cap)
		w->dst[w->len] = (unsigned char)c;
	else
		w->overflow = 1;
	w->len++;
}

static void jputs(jsonw *w, const char *s)
{
	while (*s)
		jput(w, *s++);
}

static void jput_utf8(jsonw *w, unsigned int cp)
{
	char b[8];
	if (cp < 0x80) {
		jput(w, (int)cp);
	} else if (cp < 0x800) {
		b[0] = (char)(0xC0 | (cp >> 6));
		b[1] = (char)(0x80 | (cp & 0x3F));
		b[2] = 0;
		jputs(w, b);
	} else {
		b[0] = (char)(0xE0 | (cp >> 12));
		b[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
		b[2] = (char)(0x80 | (cp & 0x3F));
		b[3] = 0;
		jputs(w, b);
	}
}

/* one character of a JSON string, escaped as the standard requires */
static void jput_escaped(jsonw *w, unsigned char c)
{
	switch (c) {
	case '"':  jputs(w, "\\\""); break;
	case '\\': jputs(w, "\\\\"); break;
	case '\b': jputs(w, "\\b");  break;
	case '\f': jputs(w, "\\f");  break;
	case '\n': jputs(w, "\\n");  break;
	case '\r': jputs(w, "\\r");  break;
	case '\t': jputs(w, "\\t");  break;
	default:
		if (c < 0x20) {
			char b[8];
			snprintf(b, sizeof b, "\\u%04X", c);
			jputs(w, b);
		} else if (c < 0x80) {
			jput(w, c);
		} else {
			jput_utf8(w, c);        /* latin-1 byte as a code point */
		}
	}
}

void cob_json_obj_open(jsonw *w)
{
	jput(w, '{');
}

void cob_json_obj_close(jsonw *w)
{
	jput(w, '}');
}

void cob_json_arr_open(jsonw *w)
{
	jput(w, '[');
}

void cob_json_arr_close(jsonw *w)
{
	jput(w, ']');
}

void cob_json_comma(jsonw *w)
{
	jput(w, ',');
}

void cob_json_key(jsonw *w, const char *name)
{
	jput(w, '"');
	for (const unsigned char *p = (const unsigned char *)name; *p; p++)
		jput_escaped(w, *p);
	jputs(w, "\":");
}

/* an alphanumeric item as a JSON string: trailing spaces are not significant,
 * except for a JUSTIFIED item, where the value is right-aligned and the
 * leading spaces are the ones that carry no meaning */
void cob_json_str(jsonw *w, cob_field *f, int justified)
{
	const unsigned char *p = f->data;
	size_t n = f->size;
	size_t lo = 0, hi = n;
	if (justified) {
		while (lo + 1 < hi && p[lo] == ' ')
			lo++;
	} else {
		while (hi > lo + 1 && p[hi - 1] == ' ')
			hi--;
	}
	jput(w, '"');
	for (size_t i = lo; i < hi; i++)
		jput_escaped(w, p[i]);
	jput(w, '"');
}

/* a numeric item as a JSON number: no quotes, no leading zeros, the PICTURE's
 * scale decides how many digits follow the point */
void cob_json_num(jsonw *w, cob_field *f, int dpc)
{
	if (f->attr->type == COB_NUM_DEC_FLOAT) {
		char t[160];
		int n = cob_dec_float_str(f, t, sizeof t);
		for (int i = 0; i < n; i++)
			jput(w, t[i]);
		return;
	}
	cob_dec d = cob_d_get(f);
	const cob_attr *a = f->attr;
	int scale = a->scale;
	if (d.scale == COB_DEC_ERR) {
		jput(w, '0');
		return;
	}
	/* bring the value to the item's declared scale, restoring the zeros that
	 * normalising the value removed (PIC 99V999 holding .12 is 0.120) */
	if (d.scale < scale) {
		int k = scale - d.scale;
		for (int i = 0; i < k; i++) {
			if (d.v > (cob_s128)1 << 120)
				break;                  /* would overflow: leave as is */
			d.v *= 10;
		}
	} else if (d.scale > scale) {
		for (int i = 0; i < d.scale - scale; i++)
			d.v /= 10;
	}
	cob_s128 v = d.v;
	if (v < 0) {
		jput(w, '-');
		v = -v;
	}
	char digits[48];
	int n = 0;
	if (v == 0) {
		digits[n++] = '0';
	} else {
		while (v > 0 && n < 40) {
			digits[n++] = (char)('0' + (int)(v % 10));
			v /= 10;
		}
	}
	/* digits[] is least-significant first */
	if (scale <= 0) {
		for (int i = n - 1; i >= 0; i--)
			jput(w, digits[i]);
		for (int i = 0; i < -scale; i++)      /* P scaling: trailing zeros */
			jput(w, '0');
		return;
	}
	if (n <= scale) {
		/* 0.00ddd: leading zero and enough zeros after the point */
		jput(w, '0');
		jput(w, dpc);
		for (int i = 0; i < scale - n; i++)
			jput(w, '0');
		for (int i = n - 1; i >= 0; i--)
			jput(w, digits[i]);
		return;
	}
	for (int i = n - 1; i >= 0; i--) {
		if (i == scale - 1)
			jput(w, dpc);
		jput(w, digits[i]);
	}
}

/* finish: pad the rest of the field with spaces, report the length and set
 * JSON-CODE to 1 when the document did not fit */
void cob_json_finish(jsonw *w, cob_field *count_in)
{
	for (size_t i = w->len < w->cap ? w->len : w->cap; i < w->cap; i++)
		w->dst[i] = ' ';
	if (w->overflow)
		cob_set_int(&cob_json_code_reg, 1);
	if (count_in)
		cob_set_int(count_in, (cob_s64)w->len);
}

/* ================================================================ JSON PARSE
 *
 * JSON PARSE (IBM Enterprise COBOL 6.2): the JSON text is read once, and each
 * name/value pair given to the data item its name matches among the children
 * of the item the enclosing object matched -- a NAME phrase literal exactly,
 * a data name in any case. The text is an object whose member named after
 * the receiver holds its value, or, with NAME OF receiver IS OMITTED, the
 * receiver's value itself. Objects go to groups, arrays to tables (as many
 * elements as the table has, or as its DEPENDING ON object says), strings and
 * numbers to elementary items as MOVE would put them, and true and false to
 * an item of the CONVERTING phrase. The compiler describes the receiver in a
 * table of nodes, each subtree contiguous.
 *
 * JSON-STATUS gathers the conditions that don't stop the statement, and
 * JSON-CODE is the one that did, as Enterprise COBOL numbers them:
 *   JSON-STATUS   1 a data item no JSON name matched
 *                 2 a JSON name no data item matched
 *                 8 an array with fewer elements than its table
 *                16 an array with more elements than its table
 *                32 a null left a data item as it was
 *                64 a null in an array left an element as it was
 *               128 a number too big for the item (SIZE ERROR)
 *               256 a value cut short to fit the item
 *   JSON-CODE   100 the JSON text is not valid
 *               101 the JSON text is empty or only white space
 *               104 a value of the wrong kind (an object for an elementary
 *                   item, an array for one that is no table, ...)
 *               105 true or false for an item not in the CONVERTING phrase
 *               106 no JSON name matched any data item
 * WITH DETAIL writes a message for each to standard error.
 */

static unsigned char json_status_data[4];
cob_field cob_json_status_reg = { 4, json_status_data, &attr_json_code };

typedef struct {
	const unsigned char *s;
	size_t n, i;
	const cob_jp_node *nodes;
	unsigned char *base;      /* the receiver */
	int code, status, matched, detail;
	int depth;                /* objects and arrays open: kept to a bound */
	unsigned char *buf;       /* a string, decoded */
	size_t blen, bcap;
} jpar;

static void jp_note(jpar *p, int bit, const char *fmt, ...)
{
	p->status |= bit;
	if (p->detail) {
		va_list ap;
		va_start(ap, fmt);
		fputs("JSON PARSE: ", stderr);
		vfprintf(stderr, fmt, ap);
		fputc('\n', stderr);
		va_end(ap);
	}
}

static int jp_fail(jpar *p, int code, const char *what)
{
	if (!p->code) {
		p->code = code;
		if (p->detail)
			fprintf(stderr, "JSON PARSE: %s at offset %lu\n", what, (unsigned long)p->i);
	}
	return -1;
}

static void jp_ws(jpar *p)
{
	while (p->i < p->n && (p->s[p->i] == ' ' || p->s[p->i] == '\t' || p->s[p->i] == '\n' ||
			       p->s[p->i] == '\r'))
		p->i++;
}

static int jp_peek(jpar *p)
{
	jp_ws(p);
	return p->i < p->n ? p->s[p->i] : -1;
}

static void jp_add(jpar *p, const unsigned char *b, size_t n)
{
	if (p->blen + n + 1 > p->bcap) {
		p->bcap = (p->blen + n + 1) * 2;
		p->buf = realloc(p->buf, p->bcap);
		if (!p->buf)
			cob_fatal("out of memory");
	}
	memcpy(p->buf + p->blen, b, n);
	p->blen += n;
	p->buf[p->blen] = 0;
}

static int jp_hex4(jpar *p, unsigned *v)
{
	*v = 0;
	for (int k = 0; k < 4; k++) {
		if (p->i >= p->n)
			return -1;
		int c = p->s[p->i++];
		int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
			c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
		if (d < 0)
			return -1;
		*v = *v * 16 + (unsigned)d;
	}
	return 0;
}

/* a string at '"': decoded into p->buf */
static int jp_string(jpar *p)
{
	p->blen = 0;
	jp_add(p, (const unsigned char *)"", 0);
	p->i++;
	for (;;) {
		if (p->i >= p->n)
			return jp_fail(p, 100, "JSON text invalid (a string not closed)");
		unsigned char c = p->s[p->i];
		if (c == '"') {
			p->i++;
			return 0;
		}
		if (c < 0x20)
			return jp_fail(p, 100, "JSON text invalid (a control character in a string)");
		if (c != '\\') {
			size_t s = p->i;
			while (p->i < p->n && p->s[p->i] != '"' && p->s[p->i] != '\\' && p->s[p->i] >= 0x20)
				p->i++;
			jp_add(p, p->s + s, p->i - s);
			continue;
		}
		p->i++;
		if (p->i >= p->n)
			return jp_fail(p, 100, "JSON text invalid (a string not closed)");
		unsigned char e = p->s[p->i++], out;
		switch (e) {
		case '"': out = '"'; break;
		case '\\': out = '\\'; break;
		case '/': out = '/'; break;
		case 'b': out = '\b'; break;
		case 'f': out = '\f'; break;
		case 'n': out = '\n'; break;
		case 'r': out = '\r'; break;
		case 't': out = '\t'; break;
		case 'u': {
			unsigned cp;
			if (jp_hex4(p, &cp))
				return jp_fail(p, 100, "JSON text invalid (a bad \\u escape)");
			if (cp >= 0xD800 && cp <= 0xDBFF && p->i + 1 < p->n && p->s[p->i] == '\\' &&
			    p->s[p->i + 1] == 'u') {
				unsigned lo;
				p->i += 2;
				if (jp_hex4(p, &lo) || lo < 0xDC00 || lo > 0xDFFF)
					return jp_fail(p, 100, "JSON text invalid (a bad surrogate pair)");
				cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
			}
			unsigned char u[4];
			size_t k;
			if (cp < 0x80) {
				u[0] = (unsigned char)cp;
				k = 1;
			} else if (cp < 0x800) {
				u[0] = (unsigned char)(0xC0 | (cp >> 6));
				u[1] = (unsigned char)(0x80 | (cp & 0x3F));
				k = 2;
			} else if (cp < 0x10000) {
				u[0] = (unsigned char)(0xE0 | (cp >> 12));
				u[1] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
				u[2] = (unsigned char)(0x80 | (cp & 0x3F));
				k = 3;
			} else {
				u[0] = (unsigned char)(0xF0 | (cp >> 18));
				u[1] = (unsigned char)(0x80 | ((cp >> 12) & 0x3F));
				u[2] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
				u[3] = (unsigned char)(0x80 | (cp & 0x3F));
				k = 4;
			}
			jp_add(p, u, k);
			continue;
		}
		default:
			return jp_fail(p, 100, "JSON text invalid (a bad escape)");
		}
		jp_add(p, &out, 1);
	}
}

/* a number: its text (start, length) after JSON's grammar */
static int jp_number(jpar *p, size_t *start, size_t *len)
{
	size_t s = p->i;
	if (p->i < p->n && p->s[p->i] == '-')
		p->i++;
	if (p->i >= p->n || !isdigit(p->s[p->i]))
		return jp_fail(p, 100, "JSON text invalid (a bad number)");
	if (p->s[p->i] == '0')
		p->i++;
	else
		while (p->i < p->n && isdigit(p->s[p->i]))
			p->i++;
	if (p->i < p->n && p->s[p->i] == '.') {
		p->i++;
		if (p->i >= p->n || !isdigit(p->s[p->i]))
			return jp_fail(p, 100, "JSON text invalid (a bad number)");
		while (p->i < p->n && isdigit(p->s[p->i]))
			p->i++;
	}
	if (p->i < p->n && (p->s[p->i] == 'e' || p->s[p->i] == 'E')) {
		p->i++;
		if (p->i < p->n && (p->s[p->i] == '+' || p->s[p->i] == '-'))
			p->i++;
		if (p->i >= p->n || !isdigit(p->s[p->i]))
			return jp_fail(p, 100, "JSON text invalid (a bad number)");
		while (p->i < p->n && isdigit(p->s[p->i]))
			p->i++;
	}
	*start = s;
	*len = p->i - s;
	return 0;
}

static int jp_word(jpar *p, const char *w)
{
	size_t l = strlen(w);
	if (p->i + l > p->n || memcmp(p->s + p->i, w, l) != 0)
		return jp_fail(p, 100, "JSON text invalid");
	p->i += l;
	return 0;
}

#define JP_MAX_DEPTH 2000

static int jp_skip(jpar *p);

/* an object or array at '{' or '[', read and dropped */
static int jp_skip_open(jpar *p, int c)
{
	switch (c) {
	case '{':
		p->i++;
		if (jp_peek(p) == '}') {
			p->i++;
			return 0;
		}
		for (;;) {
			if (jp_peek(p) != '"')
				return jp_fail(p, 100, "JSON text invalid (a name expected)");
			if (jp_string(p))
				return -1;
			if (jp_peek(p) != ':')
				return jp_fail(p, 100, "JSON text invalid (':' expected)");
			p->i++;
			if (jp_skip(p))
				return -1;
			c = jp_peek(p);
			p->i++;
			if (c == '}')
				return 0;
			if (c != ',')
				return jp_fail(p, 100, "JSON text invalid (',' or '}' expected)");
		}
	case '[':
		p->i++;
		if (jp_peek(p) == ']') {
			p->i++;
			return 0;
		}
		for (;;) {
			if (jp_skip(p))
				return -1;
			c = jp_peek(p);
			p->i++;
			if (c == ']')
				return 0;
			if (c != ',')
				return jp_fail(p, 100, "JSON text invalid (',' or ']' expected)");
		}
	}
	return 0;
}


/* any value, read and dropped */
static int jp_skip(jpar *p)
{
	int c = jp_peek(p);
	size_t s, l;
	if ((c == '{' || c == '[') && p->depth >= JP_MAX_DEPTH)
		return jp_fail(p, 100, "JSON text invalid (nested too deeply)");
	if (c == '{' || c == '[') {
		p->depth++;
		int rc = jp_skip_open(p, c);
		p->depth--;
		return rc;
	}
	switch (c) {
	case '"':
		return jp_string(p);
	case 't':
		return jp_word(p, "true");
	case 'f':
		return jp_word(p, "false");
	case 'n':
		return jp_word(p, "null");
	default:
		return jp_number(p, &s, &l);
	}
}

static int jp_name_eq(const cob_jp_node *nd, const unsigned char *s, size_t n)
{
	if (!nd->name || strlen(nd->name) != n)
		return 0;
	if (nd->exact)
		return memcmp(nd->name, s, n) == 0;
	for (size_t k = 0; k < n; k++)
		if (toupper((unsigned char)nd->name[k]) != toupper(s[k]))
			return 0;
	return 1;
}

static cob_field jp_target(jpar *p, const cob_jp_node *nd, size_t extra)
{
	cob_field f = { nd->size, p->base + nd->offset + extra, nd->attr };
	return f;
}

static int jp_is_numeric(const cob_jp_node *nd)
{
	switch (nd->attr->type) {
	case COB_NUM_DISPLAY: case COB_NUM_PACKED: case COB_NUM_BINARY: case COB_NUM_COMP5:
	case COB_NUM_FLOAT: case COB_NUM_DOUBLE: case COB_NUM_DEC_FLOAT: case COB_NUM_EDITED:
	case COB_INDEX:
		return 1;
	}
	return 0;
}

/* a string that holds a number: [sign] digits [. digits] [e [sign] digits],
 * spaces around it allowed */
static int jp_numeric_text(const unsigned char *s, size_t n)
{
	size_t i = 0, d = 0;
	while (i < n && s[i] == ' ')
		i++;
	while (n > i && s[n - 1] == ' ')
		n--;
	if (i < n && (s[i] == '+' || s[i] == '-'))
		i++;
	while (i < n && isdigit(s[i]))
		i++, d++;
	if (i < n && s[i] == '.')
		for (i++; i < n && isdigit(s[i]); i++)
			d++;
	if (!d)
		return 0;
	if (i < n && (s[i] == 'e' || s[i] == 'E')) {
		i++;
		if (i < n && (s[i] == '+' || s[i] == '-'))
			i++;
		if (i >= n || !isdigit(s[i]))
			return 0;
		while (i < n && isdigit(s[i]))
			i++;
	}
	return i == n;
}

/* a number (its text, already checked) given to a numeric item as MOVE
 * would; digits lost at the left are a SIZE ERROR, JSON-STATUS 128, and the
 * item keeps what fits */
static void jp_assign_number(jpar *p, const cob_jp_node *nd, size_t extra, const unsigned char *s,
			     size_t n, const char *jname, size_t at)
{
	char num[128];
	size_t k = 0, i = 0;
	int expo = 0, eneg = 0;
	while (i < n && s[i] == ' ')
		i++;
	/* the coefficient as it is (cob_d_exp_str keeps 38 digits of it) */
	for (; i < n && s[i] != 'e' && s[i] != 'E' && s[i] != ' '; i++)
		if (k < sizeof num - 16)
			num[k++] = (char)s[i];
	if (i < n && (s[i] == 'e' || s[i] == 'E')) {
		i++;
		if (i < n && (s[i] == '+' || s[i] == '-'))
			eneg = s[i++] == '-';
		/* any exponent past 99999 is as good as 99999: nothing holds it */
		for (; i < n && isdigit(s[i]); i++)
			if (expo < 99999)
				expo = expo * 10 + (s[i] - '0');
		if (expo > 99999)
			expo = 99999;
	}
	k += (size_t)snprintf(num + k, sizeof num - k, "E%c%d", eneg ? '-' : '+', expo);
	cob_dec d = cob_d_exp_str(num);
	cob_field dst = jp_target(p, nd, extra);
	int lost = 0;
	switch (nd->attr->type) {
	case COB_NUM_FLOAT: case COB_NUM_DOUBLE: case COB_NUM_DEC_FLOAT:
		cob_d_set(&dst, d, 0);
		break;
	case COB_NUM_EDITED:
		if (cob_d_set(&dst, d, COB_SIZE_CHECK)) {
			lost = 1;
			cob_d_set(&dst, d, 0);
		}
		break;
	default:
		lost = cob_d_set(&dst, d, COB_SIZE_REPORT);
	}
	if (lost)
		jp_note(p, 128, "SIZE ERROR during assignment to numeric item from JSON name %s at offset %lu", jname,
			(unsigned long)at);
}

/* a string or a number's text, moved to an item; alphanumeric is cut
 * short when it doesn't fit */
static void jp_move_text(jpar *p, const cob_jp_node *nd, size_t extra, const unsigned char *s, size_t n,
			 const char *jname, size_t at)
{
	cob_field dst = jp_target(p, nd, extra);
	cob_field src = { n, (unsigned char *)s, &cob_attr_alnum };
	if (!jp_is_numeric(nd) && n > dst.size) {
		/* the end MOVE drops: the right, or the left of a JUSTIFIED item */
		const unsigned char *cut = (nd->attr->flags & COB_F_JUSTIFIED) ? s : s + dst.size;
		for (size_t k = 0; k < n - dst.size; k++)
			if (cut[k] != ' ') {
				jp_note(p, 256, "truncation during assignment from JSON name %s at offset %lu", jname,
					(unsigned long)at);
				break;
			}
	}
	cob_move(&src, &dst);
}

static int jp_value(jpar *p, int ni, size_t extra, int element, const char *jname, size_t at);

/* an object's members, given to a group's children */
static int jp_object(jpar *p, int ni, size_t extra)
{
	const cob_jp_node *nd = &p->nodes[ni];
	p->i++;                         /* '{' */
	/* which children got a value: for JSON-STATUS 1 */
	unsigned char seen_stack[64];
	int nchild = 0;
	for (int c = ni + 1; c < ni + nd->span; c += p->nodes[c].span)
		nchild++;
	unsigned char *seen = nchild <= 64 ? seen_stack : cob_malloc((size_t)nchild);
	memset(seen, 0, (size_t)nchild);
	int rc = 0;
	if (jp_peek(p) == '}')
		p->i++;
	else
		for (;;) {
			if (jp_peek(p) != '"') {
				rc = jp_fail(p, 100, "JSON text invalid (a name expected)");
				break;
			}
			size_t nat = p->i;
			if (jp_string(p)) {
				rc = -1;
				break;
			}
			char *jn = (char *)cob_malloc(p->blen + 1);
			memcpy(jn, p->buf, p->blen + 1);
			size_t jl = p->blen;
			if (jp_peek(p) != ':') {
				free(jn);
				rc = jp_fail(p, 100, "JSON text invalid (':' expected)");
				break;
			}
			p->i++;
			int found = -1, k = 0;
			for (int c = ni + 1; c < ni + nd->span; c += p->nodes[c].span, k++)
				if (jp_name_eq(&p->nodes[c], (const unsigned char *)jn, jl)) {
					found = c;
					break;
				}
			if (found >= 0) {
				p->matched = 1;
				seen[k] = 1;
				rc = jp_value(p, found, extra, 0, jn, nat);
			} else {
				jp_note(p, 2, "no data item matched JSON name %s at offset %lu", jn, (unsigned long)nat);
				rc = jp_skip(p);
			}
			free(jn);
			if (rc)
				break;
			int c = jp_peek(p);
			p->i++;
			if (c == '}')
				break;
			if (c != ',') {
				rc = jp_fail(p, 100, "JSON text invalid (',' or '}' expected)");
				break;
			}
		}
	if (!rc) {
		int k = 0;
		for (int c = ni + 1; c < ni + nd->span; c += p->nodes[c].span, k++)
			if (!seen[k])
				jp_note(p, 1, "no JSON name matched %s", p->nodes[c].name);
	}
	if (seen != seen_stack)
		free(seen);
	return rc;
}

/* the value at the current position, given to node ni (element: one
 * occurrence of a table, extra: where that occurrence is) */
static int jp_value(jpar *p, int ni, size_t extra, int element, const char *jname, size_t at)
{
	const cob_jp_node *nd = &p->nodes[ni];
	int c = jp_peek(p);
	if (c < 0)
		return jp_fail(p, 100, "JSON text invalid (a value expected)");
	if (c == 'n') {
		if (jp_word(p, "null"))
			return -1;
		if (element)
			jp_note(p, 64, "JSON array %s included null at offset %lu, corresponding element unmodified",
				jname, (unsigned long)at);
		else
			jp_note(p, 32, "data item matching JSON name %s was unmodified because of value null at offset %lu",
				jname, (unsigned long)at);
		return 0;
	}
	if (nd->occurs && !element) {
		if (c != '[') {
			p->code = 104;
			if (p->detail)
				fprintf(stderr, "JSON PARSE: JSON name/value pair with name %s at offset %lu was "
					"incompatible with matching data item\n", jname, (unsigned long)at);
			return -1;
		}
		size_t count = (size_t)nd->occurs;
		if (nd->odo) {
			cob_s64 v = cob_get_int((cob_field *)nd->odo);
			count = v < 0 ? 0 : (size_t)v < count ? (size_t)v : count;
		}
		p->i++;
		size_t k = 0;
		if (jp_peek(p) == ']')
			p->i++;
		else
			for (;;) {
				int rc;
				if (k < count)
					rc = jp_value(p, ni, extra + k * nd->size, 1, jname, at);
				else {
					if (k == count)
						jp_note(p, 16, "JSON array %s at offset %lu had more elements than matching table",
							jname, (unsigned long)at);
					rc = jp_skip(p);
				}
				if (rc)
					return -1;
				k++;
				int d = jp_peek(p);
				p->i++;
				if (d == ']')
					break;
				if (d != ',')
					return jp_fail(p, 100, "JSON text invalid (',' or ']' expected)");
			}
		if (k < count)
			jp_note(p, 8, "JSON array %s at offset %lu had fewer elements than matching table", jname,
				(unsigned long)at);
		return 0;
	}
	if ((c == 't' || c == 'f') && nd->kind != COB_JP_BOOL) {
		if (jp_word(p, c == 't' ? "true" : "false"))
			return -1;
		p->code = 105;
		if (p->detail)
			fprintf(stderr, "JSON PARSE: matching JSON name %s had value true or false at offset %lu\n",
				jname, (unsigned long)at);
		return -1;
	}
	int wrong = (nd->kind == COB_JP_GROUP) != (c == '{') || c == '[';
	if (wrong) {
		p->code = 104;
		if (p->detail)
			fprintf(stderr, "JSON PARSE: JSON name/value pair with name %s at offset %lu was "
				"incompatible with matching data item\n", jname, (unsigned long)at);
		return -1;
	}
	if (c == '{')
		return jp_object(p, ni, extra);
	if (c == 't' || c == 'f') {
		if (jp_word(p, c == 't' ? "true" : "false"))
			return -1;
		cob_field dst = jp_target(p, nd, extra);
		cob_move((cob_field *)(c == 't' ? nd->tv : nd->fv), &dst);
		return 0;
	}
	if (c == '"') {
		if (jp_string(p))
			return -1;
		if (jp_is_numeric(nd) && jp_numeric_text(p->buf, p->blen))
			jp_assign_number(p, nd, extra, p->buf, p->blen, jname, at);
		else
			jp_move_text(p, nd, extra, p->buf, p->blen, jname, at);
		return 0;
	}
	size_t s, l;
	if (jp_number(p, &s, &l))
		return -1;
	if (jp_is_numeric(nd))
		jp_assign_number(p, nd, extra, p->s + s, l, jname, at);
	else
		jp_move_text(p, nd, extra, p->s + s, l, jname, at);
	return 0;
}

int cob_json_parse(cob_field *text, cob_field *into, const cob_jp_node *nodes, int detail)
{
	jpar p;
	memset(&p, 0, sizeof p);
	p.s = text->data;
	p.n = text->size;
	p.nodes = nodes;
	p.base = into->data;
	p.detail = detail;
	cob_set_int(&cob_json_status_reg, 0);
	if (jp_peek(&p) < 0) {
		p.code = 101;
		if (detail)
			fprintf(stderr, "JSON PARSE: JSON text zero-length or entirely whitespace\n");
	} else if (jp_peek(&p) != '{') {
		jp_fail(&p, 100, "JSON text invalid (an object expected)");
	} else if (!nodes[0].name) {
		/* NAME OF receiver IS OMITTED: the object is the receiver's */
		jp_value(&p, 0, 0, 0, "", 0);
	} else {
		/* {"receiver": value} */
		p.i++;
		if (jp_peek(&p) == '}')
			p.i++;
		else
			for (;;) {
				if (jp_peek(&p) != '"') {
					jp_fail(&p, 100, "JSON text invalid (a name expected)");
					break;
				}
				size_t nat = p.i;
				if (jp_string(&p))
					break;
				char *jn = (char *)cob_malloc(p.blen + 1);
				memcpy(jn, p.buf, p.blen + 1);
				size_t jl = p.blen;
				int rc;
				if (jp_peek(&p) != ':') {
					free(jn);
					jp_fail(&p, 100, "JSON text invalid (':' expected)");
					break;
				}
				p.i++;
				if (jp_name_eq(&nodes[0], (const unsigned char *)jn, jl)) {
					p.matched = 1;
					rc = jp_value(&p, 0, 0, 0, jn, nat);
				} else {
					jp_note(&p, 2, "no data item matched JSON name %s at offset %lu", jn, (unsigned long)nat);
					rc = jp_skip(&p);
				}
				free(jn);
				if (rc)
					break;
				int c = jp_peek(&p);
				p.i++;
				if (c == '}')
					break;
				if (c != ',') {
					jp_fail(&p, 100, "JSON text invalid (',' or '}' expected)");
					break;
				}
			}
		if (!p.code && !p.matched)
			jp_note(&p, 1, "no JSON name matched %s", nodes[0].name);
	}
	if (!p.code && jp_peek(&p) >= 0)
		jp_fail(&p, 100, "JSON text invalid (text after the object)");
	if (!p.code && !p.matched) {
		p.code = 106;
		if (detail)
			fprintf(stderr, "JSON PARSE: no JSON name matched any data item. Target was unmodified\n");
	}
	free(p.buf);
	cob_set_int(&cob_json_status_reg, p.status);
	cob_set_int(&cob_json_code_reg, p.code);
	return p.code;
}
