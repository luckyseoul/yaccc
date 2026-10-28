/* SPDX-License-Identifier: MIT */
/* cobrt_xml.c - XML GENERATE (COBOL 2002/2014)
 *
 * The compiler knows the data description and emits one call per item; this
 * file only writes tags and escapes. As with JSON, writing stops at the end of
 * the receiving field but keeps counting, so COUNT IN and XML-CODE can report
 * a document that did not fit.
 */
#include "cobrt.h"

static unsigned char xml_code_data[4];
static const cob_attr attr_xml_code = { COB_NUM_BINARY, 9, 0, COB_F_SIGNED, NULL, 0 };
cob_field cob_xml_code_reg = { 4, xml_code_data, &attr_xml_code };

static void flush_open(xmlw *w);

void cob_xml_code_reset(void)
{
	cob_set_int(&cob_xml_code_reg, 0);
}

int cob_xml_code_value(void)
{
	return (int)cob_get_int(&cob_xml_code_reg);
}

void cob_xml_init(xmlw *w, cob_field *out)
{
	w->dst = out->data;
	w->cap = out->size;
	w->len = 0;
	w->overflow = 0;
	for (int i = 0; i < 258; i++)
		w->pending[i] = 0;
	w->depth = 0;
	w->last_was_empty = 0;
}

static void xput(xmlw *w, int c)
{
	if (w->len < w->cap)
		w->dst[w->len] = (unsigned char)c;
	else
		w->overflow = 1;
	w->len++;
}

static void xputs(xmlw *w, const char *s)
{
	while (*s)
		xput(w, *s++);
}

/* name as written in the source, with the one change XML requires: a name may
 * not start with a digit, so a leading '_' is added ("0SpecialTAGName" becomes
 * "_0SpecialTAGName"). */
static void xname(xmlw *w, const char *name)
{
	if (name && name[0] >= '0' && name[0] <= '9')
		xput(w, '_');
	for (const char *p = name; p && *p; p++) {
		unsigned char c = (unsigned char)*p;
		if (c == ' ')
			xput(w, '_');
		else
			xput(w, c);
	}
}

void cob_xml_declaration(xmlw *w)
{
	xputs(w, "<?xml version=\"1.0\"?>\n");
}

void cob_xml_root_namespace(xmlw *w, const char *prefix, cob_field *uri)
{
	/* xmlns:pre="uri" on the root element, when both are given */
	if (!prefix || !*prefix || !uri || uri->size == 0)
		return;
	int all_space = 1;
	for (size_t i = 0; i < uri->size; i++)
		if (uri->data[i] != ' ')
			all_space = 0;
	if (all_space)
		return;
	xputs(w, " xmlns:");
	xputs(w, prefix);
	xputs(w, "=\"");
	for (size_t i = 0; i < uri->size && uri->data[i] != ' '; i++)
		xput(w, uri->data[i]);
	xputs(w, "\"");
}

static void flush_open(xmlw *w)
{
	if (w->depth > 0 && w->pending[w->depth - 1]) {
		xput(w, '>');
		w->pending[w->depth - 1] = 0;
	}
}

void cob_xml_elem_open(xmlw *w, const char *prefix, const char *name)
{
	flush_open(w);
	if (w->depth < 256)
		w->open_at[w->depth] = w->len;
	w->depth++;
	xput(w, '<');
	if (prefix && *prefix) {
		xputs(w, prefix);
		xput(w, ':');
	}
	xname(w, name);
	if (w->depth < 258)
		w->pending[w->depth - 1] = 1;
	w->last_was_empty = 0;
}

void cob_xml_elem_close(xmlw *w, const char *prefix, const char *name)
{
	w->depth--;
	if (w->depth < 0)
		w->depth = 0;
	if (w->depth < 258 && w->pending[w->depth]) {
		/* nothing inside: <name/> */
		xputs(w, "/>");
		w->pending[w->depth] = 0;
		w->empty_start = w->depth < 256 ? w->open_at[w->depth] : 0;
		w->last_was_empty = 1;
		return;
	}
	w->last_was_empty = 0;
	xputs(w, "</");
	if (prefix && *prefix) {
		xputs(w, prefix);
		xput(w, ':');
	}
	xname(w, name);
	xput(w, '>');
}

/* text content, escaped; leading and trailing spaces of an alphanumeric item
 * are kept as they are (X"20" is meaningful in XML) */
static void emit_text(xmlw *w, const unsigned char *p, size_t n)
{
	for (size_t i = 0; i < n; i++) {
		unsigned char c = p[i];
		switch (c) {
		case '&':  xputs(w, "&amp;");  break;
		case '<':  xputs(w, "&lt;");   break;
		case '>':  xputs(w, "&gt;");   break;
		case '"':  xputs(w, "&quot;"); break;
		case '\'': xputs(w, "&apos;"); break;
		default:
			if (c < 0x20 && c != '\n' && c != '\t')
				xput(w, ' ');
			else
				xput(w, c);
		}
	}
}

void cob_xml_text(xmlw *w, cob_field *f)
{
	flush_open(w);
	/* trailing spaces are not significant in element content, but one is kept
	 * so that a value of all spaces still has content */
	size_t n = f->size;
	while (n > 1 && f->data[n - 1] == ' ')
		n--;
	emit_text(w, f->data, n);
}

/* a JUSTIFIED item is right-aligned, so its leading spaces are padding and
 * are not part of the value */
void cob_xml_text_just(xmlw *w, cob_field *f)
{
	/* right-aligned: leading spaces are padding, but a trailing space is part
	 * of the value and is kept */
	flush_open(w);
	size_t lo = 0;
	while (lo + 1 < f->size && f->data[lo] == ' ')
		lo++;
	emit_text(w, f->data + lo, f->size - lo);
}

void cob_xml_num(xmlw *w, cob_field *f, int dpc)
{
	cob_dec d = cob_d_get(f);
	flush_open(w);
	if (d.scale == COB_DEC_ERR) {
		xput(w, '0');
		return;
	}
	int scale = f->attr->scale;
	if (d.scale < scale)
		for (int i = 0; i < scale - d.scale; i++)
			d.v *= 10;
	else if (d.scale > scale)
		for (int i = 0; i < d.scale - scale; i++)
			d.v /= 10;
	cob_s128 v = d.v;
	if (v < 0) {
		xput(w, '-');
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
	if (scale <= 0) {
		for (int i = n - 1; i >= 0; i--)
			xput(w, digits[i]);
		for (int i = 0; i < -scale; i++)
			xput(w, '0');
		return;
	}
	if (n <= scale) {
		xput(w, '0');
		xput(w, dpc);
		for (int i = 0; i < scale - n; i++)
			xput(w, '0');
		for (int i = n - 1; i >= 0; i--)
			xput(w, digits[i]);
		return;
	}
	for (int i = n - 1; i >= 0; i--) {
		if (i == scale - 1)
			xput(w, dpc);
		xput(w, digits[i]);
	}
}

void cob_xml_attr(xmlw *w, const char *prefix, const char *name, cob_field *f)
{
	xput(w, ' ');
	if (prefix && *prefix) {
		xputs(w, prefix);
		xput(w, ':');
	}
	xname(w, name);
	xputs(w, "=\"");
	/* an attribute value is trimmed at both ends, as GnuCOBOL writes it */
	/* trim both ends, keeping at least one character so an all-space value
	 * is still " " rather than "" */
	size_t hi = f->size;
	while (hi > 1 && f->data[hi - 1] == ' ')
		hi--;
	size_t lo = 0;
	while (lo + 1 < hi && f->data[lo] == ' ')
		lo++;
	for (size_t i = lo; i < hi; i++) {
		unsigned char c = f->data[i];
		switch (c) {
		case '&':  xputs(w, "&amp;");  break;
		case '<':  xputs(w, "&lt;");   break;
		case '>':  xputs(w, "&gt;");   break;
		case '"':  xputs(w, "&quot;"); break;
		case '\'': xputs(w, "&apos;"); break;
		default:
			if (c < 0x20)
				xput(w, ' ');
			else
				xput(w, c);
		}
	}
	xput(w, '"');
}

/* <name></name> with no content is written as <name/>, as GnuCOBOL writes it */
static void collapse_empty(xmlw *w)
{
	size_t i = 0;
	while (i + 3 < w->len) {
		if (w->dst[i] == '<' && w->dst[i + 1] == '/') {
			i++;
			continue;
		}
		if (w->dst[i] == '<') {
			size_t j = i + 1;
			while (j < w->len && w->dst[j] != '>' && w->dst[j] != '<')
				j++;
			if (j + 1 < w->len && w->dst[j] == '>' && w->dst[j + 1] == '<') {
				size_t k = j + 2;
				size_t n = j - i - 1;
				if (k + n + 1 < w->len && w->dst[k] == '/' &&
						memcmp(w->dst + k + 1, w->dst + i + 1, n) == 0 &&
						w->dst[k + 1 + n] == '>') {
					/* <name></name> -> <name/>: keep the "</" slot for
					 * "/>" and drop the rest of the closing tag */
					size_t tail = w->len - (k + 1 + n + 1);
					w->dst[j] = '/';
					w->dst[j + 1] = '>';
					memmove(w->dst + j + 2, w->dst + k + 1 + n + 1, tail);
					w->len = j + 2 + tail;
					i = j + 2;
					continue;
				}
			}
			i = j;
			continue;
		}
		i++;
	}
}

void cob_xml_finish(xmlw *w, cob_field *count_in)
{
	collapse_empty(w);
	for (size_t i = w->len < w->cap ? w->len : w->cap; i < w->cap; i++)
		w->dst[i] = ' ';
	if (w->overflow)
		cob_set_int(&cob_xml_code_reg, 1);
	if (count_in)
		cob_set_int(count_in, (cob_s64)w->len);
}

/* SUPPRESS WHEN <figurative>: is every byte of the item that byte? */
int cob_xml_all(const cob_field *f, int c)
{
	if (f->size == 0)
		return 1;
	for (size_t i = 0; i < f->size; i++)
		if (f->data[i] != (unsigned char)c)
			return 0;
	return 1;
}

/* SUPPRESS EVERY NONNUMERIC WHEN <figurative>: same test, but only for items
 * that are not numeric */
int cob_xml_nonnumeric(const cob_field *f)
{
	return !cob_is_num_type(f->attr->type);
}

size_t cob_xml_mark(xmlw *w)
{
	/* a parent's open tag may still be waiting for its '>': write it now, so
	 * that the mark and the position the child records agree */
	flush_open(w);
	w->last_was_empty = 0;
	return w->len;
}

/* an element that came out as <x/> with nothing in it is taken out again when
 * everything inside it was suppressed */
void cob_xml_rollback_if_empty(xmlw *w, size_t mark)
{
	/* the element came out as <x/>, and nothing but its own tag was written:
	 * take it out again, which is how a group whose every item was suppressed
	 * disappears */
	if (w->last_was_empty && w->empty_start == mark)
		w->len = mark;
	w->last_was_empty = 0;
}
