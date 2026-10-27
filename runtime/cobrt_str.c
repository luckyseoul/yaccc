/* cobrt_str.c - STRING, UNSTRING, INSPECT */
#include "cobrt.h"

/* bytes of an operand: figurative constants are a single repetition */
static const unsigned char *op_bytes(const cob_field *f, size_t *len, unsigned char *buf, size_t bufsz)
{
	int t = f->attr->type;
	if (t == COB_ALL) {
		*len = f->size;
		if (f->size == 0) {
			buf[0] = 0;
			*len = 1;
			return buf;
		}
		return f->data;
	}
	if (cob_is_num_type(t) && t != COB_NUM_DISPLAY) {
		*len = cob_field_text(f, buf, bufsz);
		return buf;
	}
	*len = f->size;
	return f->data;
}

static size_t find_bytes(const unsigned char *h, size_t hn, const unsigned char *n, size_t nn, size_t from)
{
	if (nn == 0 || hn < nn)
		return (size_t)-1;
	for (size_t i = from; i + nn <= hn; i++)
		if (h[i] == n[0] && memcmp(h + i, n, nn) == 0)
			return i;
	return (size_t)-1;
}

/* ================================================================ STRING */

static struct {
	cob_field *dst, *ptr;
	cob_s64 pos;
	int overflow;
	const cob_field *dlm;
} sst;

void cob_string_init(cob_field *dst, cob_field *ptr)
{
	sst.dst = dst;
	sst.ptr = ptr;
	sst.overflow = 0;
	sst.dlm = NULL;
	sst.pos = ptr ? cob_get_int(ptr) : 1;
	if (sst.pos < 1 || sst.pos > (cob_s64)dst->size)
		sst.overflow = 1;
}

void cob_string_delimited(const cob_field *dlm)
{
	sst.dlm = dlm;
}

void cob_string_append(const cob_field *src)
{
	unsigned char b1[256], b2[256];
	size_t sl, dl;
	if (sst.overflow)
		return;
	const unsigned char *s = op_bytes(src, &sl, b1, sizeof b1);
	if (sst.dlm) {
		const unsigned char *d = op_bytes(sst.dlm, &dl, b2, sizeof b2);
		size_t k = find_bytes(s, sl, d, dl, 0);
		if (k != (size_t)-1)
			sl = k;
	}
	size_t room = sst.dst->size - (size_t)(sst.pos - 1);
	size_t n = sl;
	if (n > room) {
		n = room;
		sst.overflow = 1;
	}
	memcpy(sst.dst->data + sst.pos - 1, s, n);
	sst.pos += (cob_s64)n;
}

int cob_string_finish(void)
{
	if (sst.ptr)
		cob_set_int(sst.ptr, sst.pos);
	return sst.overflow;
}

/* ================================================================ UNSTRING */

#define MAX_DLM 32
static struct {
	cob_field *src, *ptr, *tally_field;
	cob_s64 pos;
	int overflow;
	int ndlm;
	struct {
		unsigned char buf[64];
		const unsigned char *p;
		size_t n;
		int all;
	} dlm[MAX_DLM];
	cob_s64 tally;
} ust;

void cob_unstring_init(cob_field *src, cob_field *ptr)
{
	ust.src = src;
	ust.ptr = ptr;
	ust.tally_field = NULL;
	ust.ndlm = 0;
	ust.tally = 0;
	ust.overflow = 0;
	ust.pos = ptr ? cob_get_int(ptr) : 1;
	if (ust.pos < 1 || ust.pos > (cob_s64)src->size)
		ust.overflow = 1;
}

void cob_unstring_delim(const cob_field *d, int all)
{
	if (ust.ndlm >= MAX_DLM)
		return;
	int k = ust.ndlm++;
	ust.dlm[k].p = op_bytes(d, &ust.dlm[k].n, ust.dlm[k].buf, sizeof ust.dlm[k].buf);
	ust.dlm[k].all = all;
}

void cob_unstring_into(cob_field *dst, cob_field *dlmf, cob_field *cnt)
{
	if (ust.overflow)
		return;
	size_t size = ust.src->size;
	const unsigned char *s = ust.src->data;
	if (ust.pos > (cob_s64)size)
		return;
	size_t start = (size_t)ust.pos - 1;
	size_t end;
	int which = -1;
	size_t dstart = size, dlen = 0;
	if (ust.ndlm == 0) {
		size_t take = dst->size;
		if (dst->attr->type == COB_NUM_DISPLAY && (dst->attr->flags & COB_F_SIGN_SEP))
			take--;
		end = start + take > size ? size : start + take;
	} else {
		for (size_t i = start; i < size && which < 0; i++) {
			for (int k = 0; k < ust.ndlm; k++) {
				size_t dn = ust.dlm[k].n;
				if (dn && i + dn <= size && memcmp(s + i, ust.dlm[k].p, dn) == 0) {
					which = k;
					dstart = i;
					dlen = dn;
					break;
				}
			}
		}
		end = which >= 0 ? dstart : size;
	}
	cob_field tmp = { end - start, (unsigned char *)s + start, &cob_attr_alnum };
	cob_move(&tmp, dst);
	if (dlmf) {
		if (which >= 0) {
			cob_field dt = { dlen, (unsigned char *)s + dstart, &cob_attr_alnum };
			cob_move(&dt, dlmf);
		} else
			cob_move(&cob_fig_space, dlmf);
	}
	if (cnt)
		cob_set_int(cnt, (cob_s64)(end - start));
	size_t np = end + dlen;
	if (which >= 0 && ust.dlm[which].all) {
		size_t dn = ust.dlm[which].n;
		while (np + dn <= size && memcmp(s + np, ust.dlm[which].p, dn) == 0)
			np += dn;
	}
	ust.pos = (cob_s64)np + 1;
	ust.tally++;
}

void cob_unstring_tallying(cob_field *f)
{
	ust.tally_field = f;
}

int cob_unstring_finish(void)
{
	if (ust.ptr && !(ust.overflow && (ust.pos < 1 || ust.pos > (cob_s64)ust.src->size + 1)))
		cob_set_int(ust.ptr, ust.pos);
	if (ust.tally_field)
		cob_d_set(ust.tally_field, cob_d_add(cob_d_get(ust.tally_field), cob_d_int(ust.tally)), 0);
	if (ust.overflow)
		return 1;
	return ust.pos <= (cob_s64)ust.src->size;
}

/* ================================================================ INSPECT */

#define MAX_IOPS 64
typedef struct {
	int replace;
	int mode;
	cob_field *counter;
	unsigned char *pat;
	size_t plen;
	unsigned char *by;
	size_t blen;
	size_t rstart, rend;
	size_t lead_next;
	int first_done;
	cob_s64 count;
} insp_op;

static insp_op iops[MAX_IOPS];
static int niops;
static cob_field *itarget;
static int isign_pos = -1;
static int isign_neg;

/* an embedded (overpunched) sign is removed during INSPECT and restored after */
static void unpunch(cob_field *t)
{
	isign_pos = -1;
	const cob_attr *a = t->attr;
	if (a->type == COB_NUM_DISPLAY && (a->flags & COB_F_SIGNED) && !(a->flags & COB_F_SIGN_SEP) && t->size) {
		size_t pos = (a->flags & COB_F_SIGN_LEAD) ? 0 : t->size - 1;
		unsigned char c = t->data[pos];
		isign_neg = 0;
		if (c >= 0x70 && c <= 0x79) {
			isign_neg = 1;
			t->data[pos] = c - 0x40;
		}
		isign_pos = (int)pos;
	}
}

static void repunch(cob_field *t)
{
	if (isign_pos >= 0 && isign_neg) {
		unsigned char c = t->data[isign_pos];
		if (c >= '0' && c <= '9')
			t->data[isign_pos] = c + 0x40;
	}
	isign_pos = -1;
}

void cob_inspect_start(cob_field *target)
{
	for (int i = 0; i < niops; i++) {
		free(iops[i].pat);
		free(iops[i].by);
	}
	niops = 0;
	itarget = target;
	unpunch(target);
}

static void region(const cob_field *before, const cob_field *after, size_t *rs, size_t *re)
{
	unsigned char b[256];
	size_t n;
	size_t size = itarget->size;
	*rs = 0;
	*re = size;
	if (after) {
		const unsigned char *p = op_bytes(after, &n, b, sizeof b);
		size_t k = find_bytes(itarget->data, size, p, n, 0);
		if (k == (size_t)-1) {
			*rs = *re = size;
			return;
		}
		*rs = k + n;
	}
	if (before) {
		const unsigned char *p = op_bytes(before, &n, b, sizeof b);
		size_t k = find_bytes(itarget->data, size, p, n, *rs);
		if (k != (size_t)-1)
			*re = k;
	}
}

static unsigned char *dup_bytes(const cob_field *f, size_t *len, size_t want)
{
	unsigned char b[256];
	size_t n;
	const unsigned char *p = op_bytes(f, &n, b, sizeof b);
	if (f->attr->type == COB_ALL && want > 0) {
		unsigned char *r = cob_malloc(want);
		for (size_t i = 0; i < want; i++)
			r[i] = p[i % n];
		*len = want;
		return r;
	}
	unsigned char *r = cob_malloc(n + 1);
	memcpy(r, p, n);
	*len = n;
	return r;
}

static insp_op *new_op(void)
{
	if (niops >= MAX_IOPS)
		cob_fatal("INSPECT: too many operands");
	insp_op *op = &iops[niops++];
	memset(op, 0, sizeof *op);
	return op;
}

void cob_inspect_tally(cob_field *counter, int mode, const cob_field *pat, const cob_field *before, const cob_field *after)
{
	insp_op *op = new_op();
	op->replace = 0;
	op->mode = mode;
	op->counter = counter;
	if (pat)
		op->pat = dup_bytes(pat, &op->plen, 0);
	region(before, after, &op->rstart, &op->rend);
	op->lead_next = op->rstart;
}

void cob_inspect_replace(int mode, const cob_field *pat, const cob_field *by, const cob_field *before, const cob_field *after)
{
	insp_op *op = new_op();
	op->replace = 1;
	op->mode = mode;
	if (pat)
		op->pat = dup_bytes(pat, &op->plen, 0);
	op->by = dup_bytes(by, &op->blen, pat ? op->plen : 1);
	region(before, after, &op->rstart, &op->rend);
	op->lead_next = op->rstart;
}

static void run_ops(int replace)
{
	unsigned char *d = itarget->data;
	size_t n = itarget->size;
	size_t pos = 0;
	while (pos < n) {
		int matched = 0;
		for (int k = 0; k < niops; k++) {
			insp_op *op = &iops[k];
			if (op->replace != replace)
				continue;
			if (pos < op->rstart || pos >= op->rend)
				continue;
			if (op->mode == COB_INSP_CHARACTERS) {
				if (replace)
					d[pos] = op->by[0];
				else
					op->count++;
				pos++;
				matched = 1;
				break;
			}
			size_t pl = op->plen;
			if (pl == 0 || pos + pl > op->rend)
				continue;
			if (memcmp(d + pos, op->pat, pl) != 0)
				continue;
			if (op->mode == COB_INSP_LEADING && pos != op->lead_next)
				continue;
			if (op->mode == COB_INSP_FIRST && op->first_done)
				continue;
			if (replace) {
				size_t bl = op->blen < pl ? op->blen : pl;
				memcpy(d + pos, op->by, bl);
			} else
				op->count++;
			pos += pl;
			if (op->mode == COB_INSP_LEADING)
				op->lead_next = pos;
			op->first_done = 1;
			matched = 1;
			break;
		}
		if (!matched)
			pos++;
	}
}

void cob_inspect_end(void)
{
	run_ops(0);
	for (int k = 0; k < niops; k++) {
		insp_op *op = &iops[k];
		if (!op->replace && op->counter)
			cob_d_set(op->counter, cob_d_add(cob_d_get(op->counter), cob_d_int(op->count)), 0);
	}
	run_ops(1);
	repunch(itarget);
	for (int i = 0; i < niops; i++) {
		free(iops[i].pat);
		free(iops[i].by);
		iops[i].pat = iops[i].by = NULL;
	}
	niops = 0;
}

void cob_inspect_converting(cob_field *target, const cob_field *from, const cob_field *to, const cob_field *before, const cob_field *after)
{
	size_t rs, re, fl, tl;
	itarget = target;
	unpunch(target);
	region(before, after, &rs, &re);
	unsigned char *f = dup_bytes(from, &fl, 0);
	unsigned char *t = dup_bytes(to, &tl, fl);
	unsigned char map[256];
	int set[256];
	for (int i = 0; i < 256; i++) {
		map[i] = (unsigned char)i;
		set[i] = 0;
	}
	for (size_t i = 0; i < fl; i++) {
		if (!set[f[i]]) {
			map[f[i]] = i < tl ? t[i] : ' ';
			set[f[i]] = 1;
		}
	}
	for (size_t i = rs; i < re; i++)
		target->data[i] = map[target->data[i]];
	repunch(target);
	free(f);
	free(t);
}
