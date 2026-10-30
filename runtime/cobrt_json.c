/* SPDX-License-Identifier: MIT */
/* cobrt_json.c - JSON GENERATE (COBOL 2014)
 *
 * The compiler knows the data description, so it emits one call per item;
 * this file only formats. The writer stops at the end of the receiving field
 * but keeps counting, because COUNT IN reports the length the document would
 * have had and JSON-CODE reports that it did not fit.
 */
#include "cobrt.h"
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
