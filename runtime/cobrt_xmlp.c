/* SPDX-License-Identifier: MIT */
/* cobrt_xmlp.c - XML PARSE (IBM Enterprise COBOL)
 *
 * The statement hands the processing procedure one event at a time, with
 * XML-EVENT, XML-TEXT, XML-NAMESPACE and XML-NAMESPACE-PREFIX set for it.
 * The document is read whole when the statement starts, into a list of
 * events, and the generated code loops over them: the processing procedure is
 * PERFORMed for each, and the statement ends after END-OF-DOCUMENT, after an
 * EXCEPTION event, or when the procedure sets XML-CODE to -1.
 *
 * The events are those of Enterprise COBOL's XMLPARSE(XMLSS) parser: character
 * and entity references are resolved inside CONTENT-CHARACTERS and
 * ATTRIBUTE-CHARACTERS, a reference to an entity that isn't predefined is an
 * UNRESOLVED-REFERENCE event, and a namespace declaration is a
 * NAMESPACE-DECLARATION event rather than an attribute; element and attribute
 * names come as the local name, with the prefix and the namespace it is bound
 * to in XML-NAMESPACE-PREFIX and XML-NAMESPACE. A document that isn't
 * well-formed ends with an EXCEPTION event, XML-TEXT holding the document up
 * to the fault, and XML-CODE one of the values Enterprise COBOL documents for
 * its XMLPARSE(COMPAT) parser for the same fault (XMLSS reports z/OS system
 * service reason codes, which mean nothing elsewhere).
 *
 * Parsers are kept on a stack, so the processing procedure can itself run an
 * XML PARSE; nothing the generated loop needs lives in C locals, which a
 * PERFORM of the procedure would leave.
 */
#include "cobrt.h"

enum {
	EV_START_DOC, EV_VERSION, EV_ENCODING, EV_STANDALONE, EV_DOCTYPE, EV_COMMENT,
	EV_PI_TARGET, EV_PI_DATA, EV_START_ELEM, EV_NS_DECL, EV_ATTR_NAME, EV_ATTR_CHARS,
	EV_CONTENT, EV_START_CDATA, EV_END_CDATA, EV_END_ELEM, EV_UNRESOLVED, EV_END_DOC,
	EV_EXCEPTION
};
static const char *const ev_names[] = {
	"START-OF-DOCUMENT", "VERSION-INFORMATION", "ENCODING-DECLARATION",
	"STANDALONE-DECLARATION", "DOCUMENT-TYPE-DECLARATION", "COMMENT",
	"PROCESSING-INSTRUCTION-TARGET", "PROCESSING-INSTRUCTION-DATA", "START-OF-ELEMENT",
	"NAMESPACE-DECLARATION", "ATTRIBUTE-NAME", "ATTRIBUTE-CHARACTERS", "CONTENT-CHARACTERS",
	"START-OF-CDATA-SECTION", "END-OF-CDATA-SECTION", "END-OF-ELEMENT", "UNRESOLVED-REFERENCE",
	"END-OF-DOCUMENT", "EXCEPTION"
};

/* the special registers */
static unsigned char xml_event_data[30];
cob_field cob_xml_event_reg = { 30, xml_event_data, &cob_attr_alnum };
cob_field cob_xml_text_reg = { 0, xml_event_data, &cob_attr_alnum };
cob_field cob_xml_ns_reg = { 0, xml_event_data, &cob_attr_alnum };
cob_field cob_xml_nsprefix_reg = { 0, xml_event_data, &cob_attr_alnum };

typedef struct { size_t off, len; } span;         /* in the parser's arena */

typedef struct {
	int ev;
	span text, prefix, ns;
} xevent;

typedef struct xparser {
	const unsigned char *d;   /* the document, a copy */
	size_t n, i;
	unsigned char *arena;
	size_t alen, acap;
	xevent *ev;
	size_t nev, evcap, cur;
	int code;                 /* the fault, when the events end in EXCEPTION */
	int final;                /* XML-CODE when the statement ends */
	int stopped;
	/* elements open, and namespace bindings in scope */
	struct { size_t name_off, name_len; span prefix, ns; size_t nbind; } *open;
	size_t nopen, opencap;
	struct { span prefix, uri; } *bind;
	size_t nbind, bindcap;
	unsigned char *buf;       /* text being gathered */
	size_t blen, bcap;
	int in_text;              /* buf holds element content (not an attribute value) */
	struct xparser *outer;    /* the XML PARSE this one runs inside, if any */
} xparser;

static xparser *active;

static void *grow(void *p, size_t *cap, size_t need, size_t elem)
{
	if (need <= *cap)
		return p;
	size_t nc = *cap ? *cap * 2 : 64;
	while (nc < need)
		nc *= 2;
	p = realloc(p, nc * elem);
	if (!p)
		cob_fatal("out of memory");
	*cap = nc;
	return p;
}

static span keep(xparser *p, const unsigned char *s, size_t len)
{
	p->arena = grow(p->arena, &p->acap, p->alen + len + 1, 1);
	span sp = { p->alen, len };
	if (len)
		memcpy(p->arena + p->alen, s, len);
	p->alen += len;
	p->arena[p->alen] = 0;
	return sp;
}

static const span none = { 0, 0 };

static void event(xparser *p, int ev, span text, span prefix, span ns)
{
	p->ev = grow(p->ev, &p->evcap, p->nev + 1, sizeof(xevent));
	xevent *e = &p->ev[p->nev++];
	e->ev = ev;
	e->text = text;
	e->prefix = prefix;
	e->ns = ns;
}

static void event_text(xparser *p, int ev, const unsigned char *s, size_t len)
{
	event(p, ev, keep(p, s, len), none, none);
}

static void flush_content(xparser *p);

/* a fault: the events end with EXCEPTION, XML-TEXT the document up to it;
 * the content read before it comes first */
static int fail(xparser *p, int code)
{
	if (!p->code) {
		if (p->in_text)
			flush_content(p);
		p->code = code;
		size_t upto = p->i < p->n ? p->i + 1 : p->n;
		event_text(p, EV_EXCEPTION, p->d, upto);
	}
	return -1;
}

/* ---------------------------------------------------------------- characters */

static int at_end(xparser *p)
{
	return p->i >= p->n;
}

static int peek(xparser *p, size_t k)
{
	return p->i + k < p->n ? p->d[p->i + k] : -1;
}

static int looking_at(xparser *p, const char *s)
{
	size_t l = strlen(s);
	return p->i + l <= p->n && memcmp(p->d + p->i, s, l) == 0;
}

static int is_space(int c)
{
	return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

static void skip_space(xparser *p)
{
	while (!at_end(p) && is_space(p->d[p->i]))
		p->i++;
}

/* a character that may stand in a document: not a C0 control but the white space */
static int is_char(int c)
{
	return c >= 0x20 || c == '\t' || c == '\n' || c == '\r';
}

static int name_start(int c)
{
	return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == ':' || c >= 0x80;
}

static int name_char(int c)
{
	return name_start(c) || (c >= '0' && c <= '9') || c == '-' || c == '.';
}

/* a name at the current position; 0 when none starts here */
static size_t scan_name(xparser *p)
{
	size_t s = p->i;
	if (at_end(p) || !name_start(p->d[p->i]))
		return 0;
	while (!at_end(p) && name_char(p->d[p->i]))
		p->i++;
	return p->i - s;
}

static void buf_add(xparser *p, const unsigned char *s, size_t len)
{
	p->buf = grow(p->buf, &p->bcap, p->blen + len + 1, 1);
	memcpy(p->buf + p->blen, s, len);
	p->blen += len;
}

static void buf_utf8(xparser *p, unsigned long cp)
{
	unsigned char b[4];
	size_t n;
	if (cp < 0x80) {
		b[0] = (unsigned char)cp;
		n = 1;
	} else if (cp < 0x800) {
		b[0] = (unsigned char)(0xC0 | (cp >> 6));
		b[1] = (unsigned char)(0x80 | (cp & 0x3F));
		n = 2;
	} else if (cp < 0x10000) {
		b[0] = (unsigned char)(0xE0 | (cp >> 12));
		b[1] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
		b[2] = (unsigned char)(0x80 | (cp & 0x3F));
		n = 3;
	} else {
		b[0] = (unsigned char)(0xF0 | (cp >> 18));
		b[1] = (unsigned char)(0x80 | ((cp >> 12) & 0x3F));
		b[2] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
		b[3] = (unsigned char)(0x80 | (cp & 0x3F));
		n = 4;
	}
	buf_add(p, b, n);
}

static void flush_content(xparser *p)
{
	if (p->blen) {
		event_text(p, EV_CONTENT, p->buf, p->blen);
		p->blen = 0;
	}
}

/* a reference after '&': its character added to the buffer (1), an entity
 * that isn't predefined (2, its name at *name), or a fault (-1). eof: the
 * code for a document that ends inside it */
static int reference(xparser *p, size_t *name, size_t *nlen, int eof)
{
	p->i++;                 /* '&' */
	if (at_end(p))
		return fail(p, eof);
	if (p->d[p->i] == '#') {
		p->i++;
		int hex = peek(p, 0) == 'x';
		if (hex)
			p->i++;
		unsigned long cp = 0;
		size_t digits = 0;
		for (;;) {
			if (at_end(p))
				return fail(p, eof);
			int c = p->d[p->i];
			if (c == ';')
				break;
			int v = c >= '0' && c <= '9' ? c - '0' : hex && c >= 'a' && c <= 'f' ? c - 'a' + 10 :
				hex && c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
			if (v < 0)
				return fail(p, hex ? 13 : 14);
			cp = cp * (hex ? 16 : 10) + (unsigned long)v;
			if (cp > 0x10FFFF)
				return fail(p, 16);
			digits++;
			p->i++;
		}
		if (!digits)
			return fail(p, hex ? 13 : 14);
		if ((cp < 0x20 && cp != 9 && cp != 10 && cp != 13) || (cp >= 0xD800 && cp <= 0xDFFF) ||
		    cp == 0xFFFE || cp == 0xFFFF)
			return fail(p, 16);
		p->i++;         /* ';' */
		buf_utf8(p, cp);
		return 1;
	}
	size_t s = p->i, l = scan_name(p);
	if (!l)
		return fail(p, 141);
	if (at_end(p))
		return fail(p, eof);
	if (p->d[p->i] != ';')
		return fail(p, 17);
	p->i++;
	static const struct { const char *name; char c; } pre[] = {
		{ "lt", '<' }, { "gt", '>' }, { "amp", '&' }, { "apos", '\'' }, { "quot", '"' }
	};
	for (size_t k = 0; k < sizeof pre / sizeof pre[0]; k++)
		if (strlen(pre[k].name) == l && memcmp(p->d + s, pre[k].name, l) == 0) {
			buf_add(p, (const unsigned char *)&pre[k].c, 1);
			return 1;
		}
	*name = s;
	*nlen = l;
	return 2;
}

/* ---------------------------------------------------------------- namespaces */

static span lookup_ns(xparser *p, const unsigned char *pre, size_t plen)
{
	static const char xmlns_uri[] = "http://www.w3.org/XML/1998/namespace";
	for (size_t k = p->nbind; k-- > 0;) {
		span bp = p->bind[k].prefix;
		if (bp.len == plen && memcmp(p->arena + bp.off, pre, plen) == 0)
			return p->bind[k].uri;
	}
	if (plen == 3 && memcmp(pre, "xml", 3) == 0)
		return keep(p, (const unsigned char *)xmlns_uri, sizeof xmlns_uri - 1);
	return none;
}

/* a qualified name: its local part, and its prefix and namespace */
static void qualify(xparser *p, size_t off, size_t len, int is_attr, span *local, span *prefix, span *ns)
{
	const unsigned char *s = p->d + off;
	const unsigned char *colon = memchr(s, ':', len);
	if (colon && colon > s && colon < s + len - 1) {
		size_t pl = (size_t)(colon - s);
		*prefix = keep(p, s, pl);
		*local = keep(p, colon + 1, len - pl - 1);
		*ns = lookup_ns(p, s, pl);
	} else {
		*prefix = none;
		*local = keep(p, s, len);
		/* an attribute without a prefix is in no namespace; an element
		   is in the default one */
		*ns = is_attr ? none : lookup_ns(p, (const unsigned char *)"", 0);
	}
}

/* ---------------------------------------------------------------- markup */

/* <!-- ... --> */
static int comment(xparser *p, int eof)
{
	p->i += 4;
	size_t s = p->i;
	for (;;) {
		if (at_end(p))
			return fail(p, eof);
		int c = p->d[p->i];
		if (c == '-' && peek(p, 1) == '-') {
			if (peek(p, 2) != '>')
				return fail(p, 10);
			event_text(p, EV_COMMENT, p->d + s, p->i - s);
			p->i += 3;
			return 0;
		}
		if (!is_char(c))
			return fail(p, 9);
		p->i++;
	}
}

/* <?target data?> */
static int pi(xparser *p, int eof)
{
	p->i += 2;
	size_t s = p->i, l = scan_name(p);
	if (!l)
		return fail(p, at_end(p) ? eof : 138);
	if (l == 3 && (p->d[s] | 0x20) == 'x' && (p->d[s + 1] | 0x20) == 'm' && (p->d[s + 2] | 0x20) == 'l')
		return fail(p, 12);
	if (!at_end(p) && !is_space(p->d[p->i]) && !looking_at(p, "?>"))
		return fail(p, 139);
	event_text(p, EV_PI_TARGET, p->d + s, l);
	skip_space(p);
	size_t ds = p->i;
	for (;;) {
		if (at_end(p))
			return fail(p, 140);
		if (looking_at(p, "?>"))
			break;
		if (!is_char(p->d[p->i]))
			return fail(p, 11);
		p->i++;
	}
	event_text(p, EV_PI_DATA, p->d + ds, p->i - ds);
	p->i += 2;
	return 0;
}

/* <!DOCTYPE ...>, with an internal subset in [ ] and quoted strings */
static int doctype(xparser *p)
{
	size_t s = p->i;
	int depth = 0;
	p->i += 9;
	for (;;) {
		if (at_end(p))
			return fail(p, 122);
		int c = p->d[p->i];
		if (c == '"' || c == '\'') {
			const unsigned char *q = memchr(p->d + p->i + 1, c, p->n - p->i - 1);
			if (!q)
				return fail(p, 122);
			p->i = (size_t)(q - p->d) + 1;
			continue;
		}
		if (c == '[')
			depth++;
		else if (c == ']')
			depth--;
		else if (c == '>' && depth <= 0) {
			p->i++;
			break;
		}
		p->i++;
	}
	event_text(p, EV_DOCTYPE, p->d + s, p->i - s);
	return 0;
}

/* an attribute value after its quote, references resolved and white space
 * made spaces; into p->buf */
static int attr_value(xparser *p, int q)
{
	p->blen = 0;
	for (;;) {
		if (at_end(p))
			return fail(p, 110);
		int c = p->d[p->i];
		if (c == q) {
			p->i++;
			return 0;
		}
		if (c == '<')
			return fail(p, 4);
		if (c == '&') {
			size_t nm, nl;
			int r = reference(p, &nm, &nl, 111);
			if (r < 0)
				return -1;
			if (r == 2) {
				/* an entity this parser doesn't know: kept as written */
				buf_add(p, (const unsigned char *)"&", 1);
				buf_add(p, p->d + nm, nl);
				buf_add(p, (const unsigned char *)";", 1);
			}
			continue;
		}
		if (!is_char(c))
			return fail(p, 18);
		unsigned char sp = ' ';
		if (is_space(c) && c != ' ') {
			if (c == '\r' && peek(p, 1) == '\n')
				p->i++;
			buf_add(p, &sp, 1);
		} else
			buf_add(p, p->d + p->i, 1);
		p->i++;
	}
}

/* <name attrs> or <name attrs/>: 1 when the element is empty (/>), so its
 * end follows at once */
static int start_tag(xparser *p, int root)
{
	p->i++;                 /* '<' */
	size_t ns = p->i, nl = scan_name(p);
	if (!nl)
		return fail(p, at_end(p) ? (root ? 113 : 114) : (root ? 124 : 135));
	if (at_end(p))
		return fail(p, root ? 113 : 114);
	if (!is_space(p->d[p->i]) && p->d[p->i] != '>' && p->d[p->i] != '/')
		return fail(p, 126);
	/* the attributes first: namespace declarations bind for the element's
	   own name too */
	struct att { size_t n_off, n_len; span value; } *atts = NULL;
	size_t natt = 0, attcap = 0;
	size_t nbind0 = p->nbind;
	int empty = 0, rc = 0;
	for (;;) {
		skip_space(p);
		if (at_end(p)) {
			rc = fail(p, 109);
			break;
		}
		int c = p->d[p->i];
		if (c == '>') {
			p->i++;
			break;
		}
		if (c == '/') {
			if (peek(p, 1) != '>') {
				rc = fail(p, at_end(p) ? 112 : 132);
				break;
			}
			p->i += 2;
			empty = 1;
			break;
		}
		size_t as = p->i, al = scan_name(p);
		if (!al) {
			rc = fail(p, natt ? 130 : 125);
			break;
		}
		if (at_end(p)) {
			rc = fail(p, 109);
			break;
		}
		if (!is_space(p->d[p->i]) && p->d[p->i] != '=') {
			rc = fail(p, 131);
			break;
		}
		skip_space(p);
		if (at_end(p) || p->d[p->i] != '=') {
			rc = fail(p, at_end(p) ? 109 : 127);
			break;
		}
		p->i++;
		skip_space(p);
		if (at_end(p)) {
			rc = fail(p, 110);
			break;
		}
		int q = p->d[p->i];
		if (q != '"' && q != '\'') {
			rc = fail(p, 128);
			break;
		}
		p->i++;
		if (attr_value(p, q) < 0) {
			rc = -1;
			break;
		}
		for (size_t k = 0; k < natt; k++)
			if (atts[k].n_len == al && memcmp(p->d + atts[k].n_off, p->d + as, al) == 0) {
				p->i = as;
				rc = fail(p, 3);
				break;
			}
		if (rc < 0)
			break;
		atts = grow(atts, &attcap, natt + 1, sizeof *atts);
		atts[natt].n_off = as;
		atts[natt].n_len = al;
		atts[natt].value = keep(p, p->buf, p->blen);
		natt++;
		/* xmlns="uri", xmlns:prefix="uri": a binding for this element */
		if ((al == 5 && memcmp(p->d + as, "xmlns", 5) == 0) ||
		    (al > 6 && memcmp(p->d + as, "xmlns:", 6) == 0)) {
			p->bind = grow(p->bind, &p->bindcap, p->nbind + 1, sizeof *p->bind);
			p->bind[p->nbind].prefix = al == 5 ? none : keep(p, p->d + as + 6, al - 6);
			p->bind[p->nbind].uri = atts[natt - 1].value;
			p->nbind++;
		}
	}
	if (rc < 0) {
		free(atts);
		return -1;
	}
	span local, prefix, uri;
	qualify(p, ns, nl, 0, &local, &prefix, &uri);
	event(p, EV_START_ELEM, local, prefix, uri);
	for (size_t k = 0; k < natt; k++) {
		size_t as = atts[k].n_off, al = atts[k].n_len;
		if ((al == 5 && memcmp(p->d + as, "xmlns", 5) == 0) ||
		    (al > 6 && memcmp(p->d + as, "xmlns:", 6) == 0)) {
			span bp = al == 5 ? none : keep(p, p->d + as + 6, al - 6);
			event(p, EV_NS_DECL, none, bp, atts[k].value);
			continue;
		}
		span al_local, al_prefix, al_ns;
		qualify(p, as, al, 1, &al_local, &al_prefix, &al_ns);
		event(p, EV_ATTR_NAME, al_local, al_prefix, al_ns);
		event(p, EV_ATTR_CHARS, atts[k].value, none, none);
	}
	free(atts);
	if (empty) {
		event(p, EV_END_ELEM, local, prefix, uri);
		p->nbind = nbind0;
		return 1;
	}
	p->open = grow(p->open, &p->opencap, p->nopen + 1, sizeof *p->open);
	p->open[p->nopen].name_off = ns;
	p->open[p->nopen].name_len = nl;
	p->open[p->nopen].prefix = prefix;
	p->open[p->nopen].ns = uri;
	p->open[p->nopen].nbind = nbind0;
	p->nopen++;
	return 0;
}

/* </name> */
static int end_tag(xparser *p)
{
	p->i += 2;
	size_t s = p->i, l = scan_name(p);
	if (!l)
		return fail(p, at_end(p) ? 114 : 133);
	skip_space(p);
	if (at_end(p) || p->d[p->i] != '>')
		return fail(p, at_end(p) ? 114 : 134);
	p->i++;
	size_t top = p->nopen - 1;
	if (l != p->open[top].name_len || memcmp(p->d + s, p->d + p->open[top].name_off, l) != 0) {
		p->i = s;
		return fail(p, 5);
	}
	span local, prefix, uri;
	const unsigned char *nm = p->d + s;
	const unsigned char *colon = memchr(nm, ':', l);
	local = colon ? keep(p, colon + 1, l - (size_t)(colon - nm) - 1) : keep(p, nm, l);
	prefix = p->open[top].prefix;
	uri = p->open[top].ns;
	event(p, EV_END_ELEM, local, prefix, uri);
	p->nbind = p->open[top].nbind;
	p->nopen--;
	return 0;
}

/* the content of the elements, from just after the root's start tag */
static int content(xparser *p)
{
	while (p->nopen) {
		p->in_text = 1;
		if (at_end(p))
			return fail(p, 115);
		int c = p->d[p->i];
		if (c == '<') {
			flush_content(p);
			p->in_text = 0;
			if (looking_at(p, "</")) {
				if (end_tag(p) < 0)
					return -1;
			} else if (looking_at(p, "<!--")) {
				if (comment(p, 118) < 0)
					return -1;
			} else if (looking_at(p, "<![CDATA[")) {
				p->i += 9;
				size_t s = p->i;
				for (;;) {
					if (at_end(p))
						return fail(p, 119);
					if (looking_at(p, "]]>"))
						break;
					p->i++;
				}
				event(p, EV_START_CDATA, none, none, none);
				event_text(p, EV_CONTENT, p->d + s, p->i - s);
				event(p, EV_END_CDATA, none, none, none);
				p->i += 3;
			} else if (looking_at(p, "<?")) {
				if (pi(p, 116) < 0)
					return -1;
			} else if (looking_at(p, "<!")) {
				return fail(p, 136);
			} else {
				if (start_tag(p, 0) < 0)
					return -1;
				p->blen = 0;    /* the attribute values went through it */
			}
			continue;
		}
		if (c == '&') {
			size_t nm, nl;
			int r = reference(p, &nm, &nl, 120);
			if (r < 0)
				return -1;
			if (r == 2) {
				flush_content(p);
				event_text(p, EV_UNRESOLVED, p->d + nm, nl);
			}
			continue;
		}
		if (c == ']' && looking_at(p, "]]>"))
			return fail(p, 8);
		if (!is_char(c))
			return fail(p, 6);
		if (c == '\r') {
			/* line ends are a line feed */
			buf_add(p, (const unsigned char *)"\n", 1);
			p->i += peek(p, 1) == '\n' ? 2 : 1;
			continue;
		}
		buf_add(p, p->d + p->i, 1);
		p->i++;
	}
	return 0;
}

/* comments, processing instructions and white space before or after the
 * root element (where: 0 before, 1 after) */
static int misc(xparser *p, int where, int *doctypes)
{
	for (;;) {
		skip_space(p);
		if (at_end(p))
			return where ? 0 : fail(p, 102);
		int c = p->d[p->i];
		if (looking_at(p, "<!--")) {
			if (comment(p, where ? 121 : 102) < 0)
				return -1;
		} else if (looking_at(p, "<?")) {
			if (pi(p, where ? 121 : 102) < 0)
				return -1;
		} else if (looking_at(p, "<!DOCTYPE")) {
			if (where)
				return fail(p, 159);
			if (++*doctypes > 1)
				return fail(p, 123);
			if (doctype(p) < 0)
				return -1;
		} else if (c == '<' && peek(p, 1) >= 0 && name_start(peek(p, 1))) {
			if (where)
				return fail(p, 160);
			return 1;       /* the root element */
		} else if (c == '<') {
			return fail(p, where ? 160 : 2);
		} else {
			return fail(p, 1);
		}
	}
}

/* the XML declaration: <?xml version="..." encoding="..." standalone="..."?> */
static int pseudo_attr(xparser *p, const char *name, int c_eq, int c_delim, int c_bad, int eof)
{
	size_t l = strlen(name);
	if (!looking_at(p, name))
		return 0;
	p->i += l;
	skip_space(p);
	if (at_end(p))
		return fail(p, eof);
	if (p->d[p->i] != '=')
		return fail(p, c_eq);
	p->i++;
	skip_space(p);
	if (at_end(p))
		return fail(p, eof);
	int q = p->d[p->i];
	if (q != '"' && q != '\'')
		return fail(p, c_delim);
	p->i++;
	size_t s = p->i;
	while (!at_end(p) && p->d[p->i] != q) {
		int c = p->d[p->i];
		if (!(name_char(c) || c == ' ') || c == ':')
			return fail(p, c_bad);
		p->i++;
	}
	if (at_end(p))
		return fail(p, eof);
	p->blen = 0;
	buf_add(p, p->d + s, p->i - s);
	p->i++;
	return 1;
}

static int declaration(xparser *p)
{
	p->i += 5;              /* <?xml */
	skip_space(p);
	int r = pseudo_attr(p, "version", 143, 144, 145, 104);
	if (r < 0)
		return -1;
	if (r == 0)
		return fail(p, at_end(p) ? 103 : 142);
	event_text(p, EV_VERSION, p->buf, p->blen);
	if (!at_end(p) && !is_space(p->d[p->i]) && !looking_at(p, "?>"))
		return fail(p, 146);
	skip_space(p);
	r = pseudo_attr(p, "encoding", 148, 149, 150, 106);
	if (r < 0)
		return -1;
	if (r) {
		if (!((p->buf[0] | 0x20) >= 'a' && (p->buf[0] | 0x20) <= 'z'))
			return fail(p, 15);
		event_text(p, EV_ENCODING, p->buf, p->blen);
		if (!at_end(p) && !is_space(p->d[p->i]) && !looking_at(p, "?>"))
			return fail(p, 151);
		skip_space(p);
	}
	r = pseudo_attr(p, "standalone", 153, 154, 156, 108);
	if (r < 0)
		return -1;
	if (r) {
		if (!((p->blen == 3 && memcmp(p->buf, "yes", 3) == 0) || (p->blen == 2 && memcmp(p->buf, "no", 2) == 0)))
			return fail(p, 155);
		event_text(p, EV_STANDALONE, p->buf, p->blen);
		if (!at_end(p) && !is_space(p->d[p->i]) && !looking_at(p, "?>"))
			return fail(p, 157);
		skip_space(p);
	}
	if (at_end(p))
		return fail(p, 101);
	if (!looking_at(p, "?>"))
		return fail(p, 158);
	p->i += 2;
	return 0;
}

static void scan(xparser *p)
{
	if (p->n >= 3 && p->d[0] == 0xEF && p->d[1] == 0xBB && p->d[2] == 0xBF)
		p->i = 3;       /* a UTF-8 byte order mark */
	event(p, EV_START_DOC, none, none, none);
	if (looking_at(p, "<?xml") && (peek(p, 5) < 0 || is_space(peek(p, 5)))) {
		if (declaration(p) < 0)
			return;
	}
	int doctypes = 0;
	int r = misc(p, 0, &doctypes);
	if (r < 0)
		return;
	r = start_tag(p, 1);
	if (r < 0)
		return;
	p->blen = 0;
	if (r == 0 && content(p) < 0)
		return;
	p->in_text = 0;
	if (misc(p, 1, &doctypes) < 0)
		return;
	event(p, EV_END_DOC, none, none, none);
}

/* ---------------------------------------------------------------- the statement */

static void set_reg(xparser *p, cob_field *reg, span s)
{
	reg->data = p->arena + s.off;
	reg->size = s.len;
}

/* XML PARSE: the document read, its events ready */
void cob_xml_parse_start(cob_field *doc)
{
	xparser *p = cob_malloc(sizeof *p);
	unsigned char *copy = cob_malloc(doc->size + 1);
	memcpy(copy, doc->data, doc->size);
	p->d = copy;
	p->n = doc->size;
	p->arena = cob_malloc(64);
	p->acap = 64;
	scan(p);
	p->outer = active;
	active = p;
}

/* the next event into the registers: 0 when there is none */
int cob_xml_parse_next(void)
{
	xparser *p = active;
	if (!p || p->stopped || p->cur >= p->nev)
		return 0;
	xevent *e = &p->ev[p->cur++];
	const char *nm = ev_names[e->ev];
	size_t l = strlen(nm);
	memset(xml_event_data, ' ', sizeof xml_event_data);
	memcpy(xml_event_data, nm, l);
	set_reg(p, &cob_xml_text_reg, e->text);
	set_reg(p, &cob_xml_ns_reg, e->ns);
	set_reg(p, &cob_xml_nsprefix_reg, e->prefix);
	cob_set_int(&cob_xml_code_reg, e->ev == EV_EXCEPTION ? p->code : 0);
	return 1;
}

/* after the processing procedure: 1 when parsing ends here (the procedure
 * set XML-CODE to -1, or the event was EXCEPTION) */
int cob_xml_parse_after(void)
{
	xparser *p = active;
	if (!p)
		return 1;
	if (p->ev[p->cur - 1].ev == EV_EXCEPTION) {
		p->final = p->code;
		p->stopped = 1;
		return 1;
	}
	if (cob_get_int(&cob_xml_code_reg) == -1) {
		p->final = -1;
		p->stopped = 1;
		return 1;
	}
	return 0;
}

/* the statement's end: XML-CODE, nonzero for ON EXCEPTION */
int cob_xml_parse_finish(void)
{
	xparser *p = active;
	if (!p)
		return 0;
	int code = p->final;
	active = p->outer;
	free((void *)p->d);
	free(p->arena);
	free(p->ev);
	free(p->open);
	free(p->bind);
	free(p->buf);
	free(p);
	cob_set_int(&cob_xml_code_reg, code);
	/* the registers keep nothing of a parser that is gone */
	cob_xml_text_reg.size = cob_xml_ns_reg.size = cob_xml_nsprefix_reg.size = 0;
	cob_xml_text_reg.data = cob_xml_ns_reg.data = cob_xml_nsprefix_reg.data = xml_event_data;
	return code;
}
