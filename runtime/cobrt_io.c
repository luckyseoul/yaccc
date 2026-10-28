/* cobrt_io.c - file I/O (sequential, line sequential, relative, indexed) and SORT */
#include "cobrt.h"
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>

struct cob_irec {
	unsigned char *data;
	size_t size;
	cob_u64 seq;
	cob_u64 *kseq;            /* per-key order among duplicates (WRITE/REWRITE order) */
};

static void free_rec(cob_irec *r)
{
	free(r->data);
	free(r->kseq);
	free(r);
}

typedef struct {
	cob_irec **recs;          /* indexed: sorted by primary key; relative: slots */
	size_t n, cap;
	cob_u64 next_seq;
	cob_irec **ord[COB_MAX_KEYS];
	int ord_valid[COB_MAX_KEYS];
	int key_ref;
	unsigned char pos_key[4096];
	size_t pos_keylen;
	cob_u64 pos_seq;
	int pos_mode;             /* 0 start, 1 after pos, 2 at pos (generic), 3 at pos (START) */
	cob_irec *last_read;
	int modified;
	unsigned char last_written[4096];
	int have_last_written;
	cob_s64 rel_pos;          /* relative: last slot read/positioned (0 = before first) */
	int rel_incl;             /* relative: rel_pos set by START, the next READ returns it */
	cob_s64 rel_last_read;
} ixstate;

static cob_file *open_list;

static int set_st(cob_file *f, const char *st)
{
	f->stat[0] = st[0];
	f->stat[1] = st[1];
	cob_exc_io(f, st);
	if (f->status)
		cob_move_bytes((const unsigned char *)st, 2, f->status);
	switch (st[0]) {
	case '0':
		return COB_IO_OK;
	case '1':
		return COB_IO_ATEND;
	case '2':
		return COB_IO_INVALID;
	default:
		return COB_IO_ERROR;
	}
}

static const char *status_msg(const char *s)
{
	int c = (s[0] - '0') * 10 + (s[1] - '0');
	switch (c) {
	case 10: return "end of file";
	case 14: return "relative key out of range";
	case 21: return "key out of sequence";
	case 22: return "duplicate key";
	case 23: return "record not found";
	case 24: return "boundary violation";
	case 30: return "permanent I/O error";
	case 34: return "boundary violation";
	case 35: return "file not found";
	case 37: return "permission denied";
	case 41: return "file already open";
	case 42: return "file not open";
	case 43: return "no previous READ for REWRITE/DELETE";
	case 44: return "record size error";
	case 46: return "READ after end of file";
	case 47: return "READ not allowed in this open mode";
	case 48: return "WRITE not allowed in this open mode";
	case 49: return "REWRITE/DELETE not allowed in this open mode";
	default: return "I/O error";
	}
}

void cob_io_unhandled(cob_file *f, int rc, const char *loc)
{
	if (rc == COB_IO_OK)
		return;
	if (f->status)
		return;
	cob_fatal("%s: %s (status = %c%c) for file %s%s%s%s", loc, status_msg(f->stat), f->stat[0], f->stat[1],
		  f->select_name, f->path[0] ? " ('" : "", f->path, f->path[0] ? "')" : "");
}

static void trim_copy(char *dst, size_t dsz, const unsigned char *src, size_t n)
{
	size_t s = 0;
	while (s < n && (src[s] == ' ' || src[s] == 0))
		s++;
	while (n > s && (src[n - 1] == ' ' || src[n - 1] == 0))
		n--;
	size_t l = n - s;
	if (l >= dsz)
		l = dsz - 1;
	memcpy(dst, src + s, l);
	dst[l] = 0;
}

static void resolve_path(cob_file *f)
{
	char name[1024];
	if (f->assign_field)
		trim_copy(name, sizeof name, f->assign_field->data, f->assign_field->size);
	else if (f->assign_name)
		snprintf(name, sizeof name, "%s", f->assign_name);
	else
		snprintf(name, sizeof name, "%s", f->select_name);
	if (!f->assign_literal && !f->assign_field && !strchr(name, '/') && !strchr(name, '.')) {
		char ev[1100];
		const char *v;
		snprintf(ev, sizeof ev, "DD_%s", name);
		v = getenv(ev);
		if (!v) {
			snprintf(ev, sizeof ev, "dd_%s", name);
			v = getenv(ev);
		}
		if (!v)
			v = getenv(name);
		if (v && *v)
			snprintf(name, sizeof name, "%s", v);
	}
	snprintf(f->path, sizeof f->path, "%s", name);
}

static void link_open(cob_file *f)
{
	f->next_open = open_list;
	open_list = f;
}

static void unlink_open(cob_file *f)
{
	cob_file **pp = &open_list;
	while (*pp) {
		if (*pp == f) {
			*pp = f->next_open;
			break;
		}
		pp = &(*pp)->next_open;
	}
	f->next_open = NULL;
}

/* ================================================================ key helpers */

static int key_cmp_rec(const cob_file *f, int k, const unsigned char *a, const unsigned char *b)
{
	const cob_file_key *key = &f->keys[k];
	return memcmp(a + key->offset, b + key->offset, key->size);
}

static ixstate *ixs(cob_file *f)
{
	if (!f->ix)
		f->ix = cob_malloc(sizeof(ixstate));
	return (ixstate *)f->ix;
}

static void ix_free(cob_file *f)
{
	ixstate *s = f->ix;
	if (!s)
		return;
	for (size_t i = 0; i < s->n; i++)
		if (s->recs[i])
			free_rec(s->recs[i]);
	free(s->recs);
	for (int k = 0; k < COB_MAX_KEYS; k++)
		free(s->ord[k]);
	free(s);
	f->ix = NULL;
}

static cob_irec *new_rec(cob_file *f, const unsigned char *data, size_t size)
{
	cob_irec *r = cob_malloc(sizeof *r);
	r->data = cob_malloc(f->record_max);
	memset(r->data, ' ', f->record_max);
	memcpy(r->data, data, size > f->record_max ? f->record_max : size);
	r->size = size;
	r->seq = ixs(f)->next_seq++;
	int nk = f->nkeys > 0 ? f->nkeys : 1;
	r->kseq = cob_malloc(sizeof(cob_u64) * (size_t)nk);
	for (int k = 0; k < nk; k++)
		r->kseq[k] = r->seq;
	return r;
}

static void ensure_cap(ixstate *s, size_t need)
{
	if (need > s->cap) {
		size_t nc = s->cap ? s->cap * 2 : 64;
		while (nc < need)
			nc *= 2;
		s->recs = realloc(s->recs, nc * sizeof(cob_irec *));
		if (!s->recs)
			cob_fatal("out of memory");
		memset(s->recs + s->cap, 0, (nc - s->cap) * sizeof(cob_irec *));
		s->cap = nc;
	}
}

static void invalidate(ixstate *s)
{
	for (int k = 0; k < COB_MAX_KEYS; k++)
		s->ord_valid[k] = 0;
	s->modified = 1;
}

static const cob_file *sort_file_ctx;
static int sort_key_ctx;

static int ord_cmp(const void *pa, const void *pb)
{
	const cob_irec *a = *(cob_irec *const *)pa, *b = *(cob_irec *const *)pb;
	int c = key_cmp_rec(sort_file_ctx, sort_key_ctx, a->data, b->data);
	if (c)
		return c;
	cob_u64 sa = a->kseq[sort_key_ctx], sb = b->kseq[sort_key_ctx];
	return sa < sb ? -1 : (sa > sb ? 1 : 0);
}

static cob_irec **get_order(cob_file *f, int k)
{
	ixstate *s = ixs(f);
	if (k == 0)
		return s->recs;
	if (!s->ord_valid[k]) {
		free(s->ord[k]);
		s->ord[k] = cob_malloc((s->n + 1) * sizeof(cob_irec *));
		memcpy(s->ord[k], s->recs, s->n * sizeof(cob_irec *));
		sort_file_ctx = f;
		sort_key_ctx = k;
		qsort(s->ord[k], s->n, sizeof(cob_irec *), ord_cmp);
		s->ord_valid[k] = 1;
	}
	return s->ord[k];
}

/* binary search in ordering k: first index with (key prefix, seq) relation */
static size_t lower_bound(cob_file *f, int k, const unsigned char *key, size_t klen, cob_u64 seq, int use_seq, int strict)
{
	ixstate *s = ixs(f);
	cob_irec **ord = get_order(f, k);
	size_t lo = 0, hi = s->n;
	const cob_file_key *fk = &f->keys[k];
	while (lo < hi) {
		size_t mid = (lo + hi) / 2;
		int c = memcmp(ord[mid]->data + fk->offset, key, klen);
		if (c == 0 && use_seq)
			c = ord[mid]->kseq[k] < seq ? -1 : (ord[mid]->kseq[k] > seq ? 1 : 0);
		if (c < 0 || (strict && c == 0))
			lo = mid + 1;
		else
			hi = mid;
	}
	return lo;
}

/* ================================================================ load / persist */

#define CIX_MAGIC "CIX2"

static void load_indexed(cob_file *f, FILE *fp)
{
	ixstate *s = ixs(f);
	unsigned char *buf = cob_malloc(f->record_max);
	char magic[4];
	uint32_t nk = 0;
	if (fread(magic, 1, 4, fp) == 4 && memcmp(magic, CIX_MAGIC, 4) == 0 && fread(&nk, 4, 1, fp) == 1) {
		cob_u64 *ks = cob_malloc(sizeof(cob_u64) * (nk ? nk : 1));
		cob_u64 maxseq = 0;
		for (;;) {
			uint32_t l;
			if (fread(&l, 4, 1, fp) != 1 || fread(buf, 1, f->record_max, fp) != f->record_max ||
			    fread(ks, sizeof(cob_u64), nk, fp) != nk)
				break;
			ensure_cap(s, s->n + 1);
			cob_irec *r = new_rec(f, buf, l > f->record_max ? f->record_max : l);
			for (int k = 0; k < f->nkeys && k < (int)nk; k++) {
				r->kseq[k] = ks[k];
				if (ks[k] > maxseq)
					maxseq = ks[k];
			}
			r->seq = r->kseq[0];
			s->recs[s->n++] = r;
		}
		free(ks);
		free(buf);
		s->next_seq = maxseq + 1;
		sort_file_ctx = f;
		sort_key_ctx = 0;
		qsort(s->recs, s->n, sizeof(cob_irec *), ord_cmp);
		invalidate(s);
		s->modified = 0;
		return;
	}
	rewind(fp);
	for (;;) {
		size_t sz = f->record_max;
		if (f->variable) {
			uint32_t l;
			if (fread(&l, 4, 1, fp) != 1)
				break;
			sz = l > f->record_max ? f->record_max : l;
			if (fread(buf, 1, l, fp) != l)
				break;
		} else if (fread(buf, 1, sz, fp) != sz)
			break;
		ensure_cap(s, s->n + 1);
		s->recs[s->n++] = new_rec(f, buf, sz);
	}
	free(buf);
	/* keep sorted by primary key (file should already be sorted) */
	sort_file_ctx = f;
	sort_key_ctx = 0;
	qsort(s->recs, s->n, sizeof(cob_irec *), ord_cmp);
	invalidate(s);
	s->modified = 0;
}

static void load_relative(cob_file *f, FILE *fp)
{
	ixstate *s = ixs(f);
	unsigned char *buf = cob_malloc(f->record_max + 1);
	size_t slot = 0;
	for (;;) {
		uint32_t l = (uint32_t)f->record_max;
		if (f->variable) {
			int c = fgetc(fp);
			if (c == EOF || fread(&l, 4, 1, fp) != 1)
				break;
			buf[0] = (unsigned char)c;
			if (fread(buf + 1, 1, f->record_max, fp) != f->record_max)
				break;
			if (l > f->record_max)
				l = (uint32_t)f->record_max;
		} else if (fread(buf, 1, f->record_max + 1, fp) != f->record_max + 1)
			break;
		ensure_cap(s, slot + 1);
		if (buf[0])
			s->recs[slot] = new_rec(f, buf + 1, l);
		slot++;
		if (slot > s->n)
			s->n = slot;
	}
	free(buf);
	s->modified = 0;
}

static int persist(cob_file *f)
{
	ixstate *s = ixs(f);
	FILE *fp = fopen(f->path, "wb");
	if (!fp)
		return -1;
	if (f->organization == COB_ORG_INDEXED) {
		uint32_t nk = (uint32_t)(f->nkeys > 0 ? f->nkeys : 1);
		fwrite(CIX_MAGIC, 1, 4, fp);
		fwrite(&nk, 4, 1, fp);
		for (size_t i = 0; i < s->n; i++) {
			uint32_t l = (uint32_t)s->recs[i]->size;
			fwrite(&l, 4, 1, fp);
			fwrite(s->recs[i]->data, 1, f->record_max, fp);
			fwrite(s->recs[i]->kseq, sizeof(cob_u64), nk, fp);
		}
	} else {
		unsigned char *empty = cob_malloc(f->record_max + 1);
		/* drop trailing empty slots */
		size_t n = s->n;
		while (n && !s->recs[n - 1])
			n--;
		for (size_t i = 0; i < n; i++) {
			uint32_t l = s->recs[i] ? (uint32_t)s->recs[i]->size : 0;
			fputc(s->recs[i] ? 1 : 0, fp);
			if (f->variable)
				fwrite(&l, 4, 1, fp);
			fwrite(s->recs[i] ? s->recs[i]->data : empty + 1, 1, f->record_max, fp);
		}
		free(empty);
	}
	fclose(fp);
	s->modified = 0;
	return 0;
}

/* ================================================================ OPEN / CLOSE */

static int linage_params(cob_file *f)
{
	int v[4];
	for (int i = 0; i < 4; i++)
		v[i] = f->lin_src[i] ? (int)cob_get_int(f->lin_src[i]) : f->lin_const[i];
	int has_foot = f->lin_src[1] != NULL || f->lin_const[1] != 0;
	if (v[0] < 1)
		return -1;
	if (has_foot) {
		if (v[1] < 1 || v[1] > v[0])
			return -1;
	} else
		v[1] = 0;
	if (v[2] < 0 || v[3] < 0)
		return -1;
	f->lin_lines = v[0];
	f->lin_foot = v[1];
	f->lin_top = v[2];
	f->lin_bot = v[3];
	return 0;
}

static int open_seq(cob_file *f, int mode);

int cob_open(cob_file *f, int mode)
{
	f->use_mode = mode;
	if (f->open_mode)
		return set_st(f, "41");
	if (f->locked)
		return set_st(f, "38");
	f->at_end = 0;
	f->last_read_ok = 0;
	f->linage_lines = 0;
	f->eop = 0;
	resolve_path(f);
	if (f->organization == COB_ORG_SEQUENTIAL || f->organization == COB_ORG_LINE_SEQ) {
		int rc = open_seq(f, mode);
		if (rc == COB_IO_OK && f->linage_ctr && (mode == COB_OPEN_OUTPUT || mode == COB_OPEN_EXTEND)) {
			if (linage_params(f)) {
				cob_close_quiet(f);
				return set_st(f, "57");
			}
			cob_set_int(f->linage_ctr, 1);
			f->lin_need_top = 1;
		}
		return rc;
	}
	/* relative / indexed: in-memory with persistence */
	ix_free(f);
	ixstate *s = ixs(f);
	s->key_ref = 0;
	s->pos_mode = 0;
	s->rel_pos = 0;
	s->rel_incl = 0;
	const char *st = "00";
	if (mode != COB_OPEN_OUTPUT) {
		FILE *fp = fopen(f->path, "rb");
		if (!fp) {
			if (errno == ENOENT) {
				if (!f->optional)
					return set_st(f, "35");
				st = "05";
				/* OPEN I-O / EXTEND creates a missing optional file */
				if (mode != COB_OPEN_INPUT) {
					fp = fopen(f->path, "ab");
					if (!fp)
						return set_st(f, errno == EACCES ? "37" : "30");
					fclose(fp);
					s->modified = 1;
				}
			} else
				return set_st(f, errno == EACCES ? "37" : "30");
		} else {
			if (f->organization == COB_ORG_INDEXED)
				load_indexed(f, fp);
			else
				load_relative(f, fp);
			fclose(fp);
		}
	} else {
		/* the file is written at CLOSE; make sure it can be created now */
		FILE *fp = fopen(f->path, "ab");
		if (!fp)
			return set_st(f, errno == EACCES ? "37" : "30");
		fclose(fp);
		s->modified = 1;
	}
	f->open_mode = mode;
	link_open(f);
	return set_st(f, st);
}

static int open_seq(cob_file *f, int mode)
{
	{
		if (f->assign_kind == 1) {
			if (mode != COB_OPEN_INPUT)
				return set_st(f, "37");
			f->fp = stdin;
		} else if (f->assign_kind == 2 || f->assign_kind == 3) {
			if (mode == COB_OPEN_INPUT || mode == COB_OPEN_IO)
				return set_st(f, "37");
			f->fp = stdout;
		} else {
			const char *fm = mode == COB_OPEN_INPUT ? "rb" : mode == COB_OPEN_OUTPUT ? "wb" :
					 mode == COB_OPEN_IO ? "r+b" : "ab";
			if (mode == COB_OPEN_EXTEND && access(f->path, F_OK) != 0) {
				errno = ENOENT;
				f->fp = NULL;
			} else
				f->fp = fopen(f->path, fm);
			if (!f->fp) {
				int e = errno;
				if (e == ENOENT && f->optional) {
					if (mode == COB_OPEN_INPUT) {
						f->open_mode = mode;
						link_open(f);
						return set_st(f, "05");
					}
					f->fp = fopen(f->path, mode == COB_OPEN_EXTEND ? "ab" : "w+b");
					if (f->fp) {
						f->open_mode = mode;
						link_open(f);
						return set_st(f, "05");
					}
				}
				if (e == EACCES)
					return set_st(f, "37");
				return set_st(f, e == ENOENT && mode != COB_OPEN_OUTPUT ? "35" : "30");
			}
		}
		f->open_mode = mode;
		link_open(f);
		return set_st(f, "00");
	}
}

int cob_close(cob_file *f)
{
	if (!f->open_mode)
		return set_st(f, "42");
	if (f->organization == COB_ORG_SEQUENTIAL || f->organization == COB_ORG_LINE_SEQ) {
		if (f->fp) {
			if (f->linage_lines)
				fputc('\n', f->fp);
			if (f->fp == stdout)
				fflush(stdout);
			else if (f->fp != stdin)
				fclose(f->fp);
		}
		f->fp = NULL;
	} else {
		ixstate *s = ixs(f);
		if (f->open_mode != COB_OPEN_INPUT && s->modified)
			persist(f);
		ix_free(f);
	}
	f->open_mode = 0;
	unlink_open(f);
	return set_st(f, "00");
}

/* DELETE FILE (extension): remove the closed file */
int cob_delete_file(cob_file *f)
{
	if (f->open_mode)
		return set_st(f, "41");
	if (f->assign_kind)
		return set_st(f, "30");
	resolve_path(f);
	if (unlink(f->path) != 0) {
		if (errno == ENOENT) {
			/* nothing to delete: reported in FILE STATUS, not an error */
			set_st(f, f->optional ? "05" : "35");
			return COB_IO_OK;
		}
		return set_st(f, errno == EACCES ? "37" : "30");
	}
	return set_st(f, "00");
}

int cob_close_opt(cob_file *f, int opt)
{
	if (opt == 1) {
		/* CLOSE REEL/UNIT: a disk file has no reels; it stays open */
		if (!f->open_mode)
			return set_st(f, "42");
		if (f->fp)
			fflush(f->fp);
		return set_st(f, "07");
	}
	int rc = cob_close(f);
	if (rc != COB_IO_OK)
		return rc;
	if (opt == 3)
		f->locked = 1;
	if (opt == 2)
		return set_st(f, "07");
	return rc;
}

void cob_close_quiet(cob_file *f)
{
	cob_field *st = f->status;
	f->status = NULL;
	cob_close(f);
	f->status = st;
}

void cob_close_all_files(void)
{
	while (open_list)
		cob_close(open_list);
}

/* ================================================================ sequential */

static int read_seq(cob_file *f)
{
	f->last_read_ok = 0;
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	if (f->at_end)
		return set_st(f, "46");
	if (!f->fp) {
		f->at_end = 1;
		return set_st(f, "10");
	}
	unsigned char *rec = f->record;
	size_t max = f->record_max;
	if (f->organization == COB_ORG_LINE_SEQ) {
		int c = getc(f->fp);
		size_t n = 0;
		if (c == EOF) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		while (c != EOF && c != '\n') {
			if (n < max)
				rec[n++] = (unsigned char)c;
			c = getc(f->fp);
		}
		if (n > 0 && rec[n - 1] == '\r')
			n--;
		memset(rec + n, ' ', max - n);
		f->cur_size = n;
		if (f->size_field)
			cob_set_int(f->size_field, (cob_s64)n);
		f->last_read_ok = 1;
		return set_st(f, "00");
	}
	f->last_pos = ftell(f->fp);
	size_t sz = max;
	if (f->variable) {
		uint32_t l;
		if (fread(&l, 4, 1, f->fp) != 1) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		sz = l;
		size_t rd = l > max ? max : l;
		if (fread(rec, 1, rd, f->fp) != rd) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		if (l > max)
			fseek(f->fp, (long)(l - max), SEEK_CUR);
		if (rd < max)
			memset(rec + rd, ' ', max - rd);
		f->cur_size = rd;
		if (f->size_field)
			cob_set_int(f->size_field, (cob_s64)rd);
		f->last_read_ok = 1;
		return set_st(f, "00");
	}
	size_t got = fread(rec, 1, sz, f->fp);
	if (got == 0) {
		f->at_end = 1;
		return set_st(f, "10");
	}
	f->last_read_ok = 1;
	f->cur_size = got;
	if (got < sz) {
		memset(rec + got, ' ', sz - got);
		return set_st(f, "04");
	}
	return set_st(f, "00");
}

static void put_nl(cob_file *f, int n)
{
	for (int i = 0; i < n; i++)
		fputc('\n', f->fp);
}

/* print the record on the current line (terminating a line left open) */
static void lin_print(cob_file *f, const unsigned char *rec, size_t n)
{
	if (f->linage_lines)
		fputc('\n', f->fp);
	fwrite(rec, 1, n, f->fp);
	f->linage_lines = 1;
}

static void lin_advance(cob_file *f, int k)
{
	if (k > 0) {
		put_nl(f, k);
		f->linage_lines = 0;
	}
}

/* move from body line lc to body line 1 of the next logical page */
static int lin_next_page(cob_file *f, int lc)
{
	int k = f->lin_lines - lc + f->lin_bot;
	if (k > 0)
		lin_advance(f, k);
	if (linage_params(f))
		return -1;
	lin_advance(f, f->lin_top + 1);
	cob_set_int(f->linage_ctr, 1);
	return 0;
}

static int write_linage(cob_file *f, const unsigned char *rec, size_t n, int when, int lines)
{
	int lc = (int)cob_get_int(f->linage_ctr);
	if (lc < 1)
		return set_st(f, "57");
	if (f->lin_need_top) {
		f->lin_need_top = 0;
		lin_advance(f, f->lin_top);
	}
	if (when == COB_ADV_NONE) {
		when = COB_ADV_AFTER;
		lines = 1;
	}
	if (lines == COB_ADV_PAGE) {
		if (when == COB_ADV_BEFORE)
			lin_print(f, rec, n);
		if (lin_next_page(f, lc))
			return set_st(f, "57");
		if (when == COB_ADV_AFTER)
			lin_print(f, rec, n);
		return set_st(f, "00");
	}
	if (lines < 0)
		lines = 0;
	int nlc = lc + lines;
	if (when == COB_ADV_BEFORE)
		lin_print(f, rec, n);
	if (nlc > f->lin_lines) {
		/* page overflow */
		if (lin_next_page(f, lc))
			return set_st(f, "57");
		f->eop = 1;
		if (when == COB_ADV_AFTER)
			lin_print(f, rec, n);
		return set_st(f, "00");
	}
	if (when == COB_ADV_AFTER) {
		if (lines == 0) {
			if (f->linage_lines)
				fputc('\r', f->fp);
			fwrite(rec, 1, n, f->fp);
			f->linage_lines = 1;
		} else {
			lin_advance(f, lines);
			lin_print(f, rec, n);
		}
	} else
		lin_advance(f, lines);
	cob_set_int(f->linage_ctr, nlc);
	if (f->lin_foot && nlc >= f->lin_foot)
		f->eop = 1;
	return set_st(f, "00");
}

static int write_seq(cob_file *f, size_t recsize, int adv_when, int adv_lines)
{
	f->last_read_ok = 0;
	f->eop = 0;
	if (f->open_mode != COB_OPEN_OUTPUT && f->open_mode != COB_OPEN_EXTEND)
		return set_st(f, "48");
	if (!f->fp)
		return set_st(f, "48");
	unsigned char *rec = f->record;
	if (f->organization == COB_ORG_LINE_SEQ && f->size_field) {
		/* RECORD VARYING ... DEPENDING ON: the line has that many characters */
		cob_s64 l = cob_get_int(f->size_field);
		recsize = l < 0 ? 0 : (l > (cob_s64)f->record_max ? f->record_max : (size_t)l);
	}
	if (f->organization == COB_ORG_LINE_SEQ && f->linage_ctr) {
		size_t n = recsize;
		while (n && rec[n - 1] == ' ')
			n--;
		int rc = write_linage(f, rec, n, adv_when, adv_lines);
		if (f->fp == stdout)
			fflush(stdout);
		return rc;
	}
	if (f->organization == COB_ORG_LINE_SEQ) {
		size_t n = recsize;
		while (n && rec[n - 1] == ' ')
			n--;
		if (adv_when == COB_ADV_AFTER) {
			if (adv_lines == COB_ADV_PAGE)
				fputc('\f', f->fp);
			else if (adv_lines == 0)
				fputc('\r', f->fp);
			else
				put_nl(f, adv_lines);
			fwrite(rec, 1, n, f->fp);
			f->linage_lines = 1;
		} else {
			/* a line left open by AFTER ADVANCING is terminated first by a
			 * WRITE without ADVANCING, which behaves as AFTER ADVANCING 1
			 * (ISO default); BEFORE ADVANCING prints on that line, as the
			 * printer would (and as GnuCOBOL and Micro Focus do) */
			if (f->linage_lines && adv_when != COB_ADV_BEFORE)
				fputc('\n', f->fp);
			fwrite(rec, 1, n, f->fp);
			if (adv_when == COB_ADV_BEFORE && adv_lines == COB_ADV_PAGE)
				fputc('\f', f->fp);
			else if (adv_when == COB_ADV_BEFORE && adv_lines == 0)
				fputc('\r', f->fp);
			else if (adv_when == COB_ADV_BEFORE)
				put_nl(f, adv_lines);
			else
				fputc('\n', f->fp);
			f->linage_lines = 0;
		}
		if (f->fp == stdout)
			fflush(stdout);
		return set_st(f, "00");
	}
	if (f->variable) {
		cob_s64 l = (cob_s64)recsize;
		if (f->size_field)
			l = cob_get_int(f->size_field);
		if (l < (cob_s64)f->record_min || l > (cob_s64)f->record_max || l < 1)
			return set_st(f, "44");
		uint32_t l32 = (uint32_t)l;
		fwrite(&l32, 4, 1, f->fp);
		fwrite(rec, 1, l32, f->fp);
	} else {
		fwrite(rec, 1, f->record_max, f->fp);
	}
	return set_st(f, "00");
}

static int rewrite_seq(cob_file *f, size_t recsize)
{
	if (f->open_mode != COB_OPEN_IO)
		return set_st(f, "49");
	if (!f->last_read_ok)
		return set_st(f, "43");
	f->last_read_ok = 0;
	if (f->organization == COB_ORG_LINE_SEQ)
		return set_st(f, "30");
	size_t nsize = f->record_max;
	if (f->variable) {
		nsize = recsize;
		if (f->size_field)
			nsize = (size_t)cob_get_int(f->size_field);
	} else if (recsize && recsize != f->record_max)
		nsize = recsize;
	if (nsize != f->cur_size)
		return set_st(f, "44");
	long cur = ftell(f->fp);
	fseek(f->fp, f->last_pos + (f->variable ? 4 : 0), SEEK_SET);
	fwrite(f->record, 1, nsize, f->fp);
	fflush(f->fp);
	fseek(f->fp, cur, SEEK_SET);
	return set_st(f, "00");
}

/* size of a record about to be written / rewritten (relative, indexed) */
static int new_rec_size(cob_file *f, size_t recsize, size_t *out)
{
	cob_s64 l;
	if (f->size_field)
		l = cob_get_int(f->size_field);
	else
		l = recsize ? (cob_s64)recsize : (cob_s64)f->record_max;
	if (f->variable) {
		if (l < (cob_s64)f->record_min || l > (cob_s64)f->record_max || l < 1)
			return -1;
	} else
		l = (cob_s64)f->record_max;
	*out = (size_t)l;
	return 0;
}

/* largest value the RELATIVE KEY item can hold */
static cob_s64 rel_key_cap(cob_file *f)
{
	if (!f->relative_key)
		return INT64_MAX;
	int d = f->relative_key->attr->digits;
	int t = f->relative_key->attr->type;
	if (t == COB_NUM_COMP5 || t == COB_INDEX || d <= 0 || d >= 18)
		return INT64_MAX;
	cob_s64 m = 1;
	for (int i = 0; i < d; i++)
		m *= 10;
	return m - 1;
}

/* ================================================================ relative */

static cob_s64 rel_key(cob_file *f)
{
	return f->relative_key ? cob_get_int(f->relative_key) : 0;
}

static int read_rel(cob_file *f, int next)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	cob_s64 slot;
	if (next == 2) {
		/* READ PREVIOUS */
		if (f->at_end)
			return set_st(f, "46");
		slot = s->rel_incl ? s->rel_pos : s->rel_pos - 1;
		if (slot > (cob_s64)s->n)
			slot = (cob_s64)s->n;
		while (slot >= 1 && !s->recs[slot - 1])
			slot--;
		if (slot < 1) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		if (f->relative_key)
			cob_set_int(f->relative_key, slot);
	} else if (next || f->access == COB_ACC_SEQUENTIAL) {
		if (f->at_end)
			return set_st(f, "46");
		slot = s->rel_incl ? s->rel_pos : s->rel_pos + 1;
		if (slot < 1)
			slot = 1;
		while (slot <= (cob_s64)s->n && !s->recs[slot - 1])
			slot++;
		if (slot > (cob_s64)s->n) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		if (slot > rel_key_cap(f)) {
			f->at_end = 1;
			return set_st(f, "14");
		}
		if (f->relative_key)
			cob_set_int(f->relative_key, slot);
	} else {
		slot = rel_key(f);
		if (slot < 1 || slot > (cob_s64)s->n || !s->recs[slot - 1])
			return set_st(f, "23");
	}
	memcpy(f->record, s->recs[slot - 1]->data, f->record_max);
	f->cur_size = s->recs[slot - 1]->size;
	if (f->size_field)
		cob_set_int(f->size_field, (cob_s64)f->cur_size);
	s->rel_pos = slot;
	s->rel_incl = 0;
	s->rel_last_read = slot;
	f->last_read_ok = 1;
	return set_st(f, "00");
}

static int write_rel(cob_file *f, size_t recsize)
{
	ixstate *s = ixs(f);
	f->last_read_ok = 0;
	if (f->open_mode == COB_OPEN_INPUT)
		return set_st(f, "48");
	size_t size;
	if (new_rec_size(f, recsize, &size))
		return set_st(f, "44");
	cob_s64 slot;
	if (f->access == COB_ACC_SEQUENTIAL) {
		slot = (cob_s64)s->n + 1;
		if (slot > rel_key_cap(f))
			return set_st(f, "24");
		if (f->relative_key)
			cob_set_int(f->relative_key, slot);
	} else {
		slot = rel_key(f);
		if (slot < 1)
			return set_st(f, "24");
	}
	ensure_cap(s, (size_t)slot);
	if (slot <= (cob_s64)s->n && s->recs[slot - 1])
		return set_st(f, "22");
	s->recs[slot - 1] = new_rec(f, f->record, size);
	if ((size_t)slot > s->n)
		s->n = (size_t)slot;
	s->modified = 1;
	return set_st(f, "00");
}

static int rewrite_rel(cob_file *f, size_t recsize, int del)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_IO)
		return set_st(f, "49");
	size_t size = 0;
	if (!del && new_rec_size(f, recsize, &size)) {
		f->last_read_ok = 0;
		return set_st(f, "44");
	}
	cob_s64 slot;
	if (f->access == COB_ACC_SEQUENTIAL) {
		if (!f->last_read_ok)
			return set_st(f, "43");
		slot = s->rel_last_read;
	} else
		slot = rel_key(f);
	if (slot < 1 || slot > (cob_s64)s->n || !s->recs[slot - 1])
		return set_st(f, "23");
	if (del) {
		free_rec(s->recs[slot - 1]);
		s->recs[slot - 1] = NULL;
	} else {
		memcpy(s->recs[slot - 1]->data, f->record, f->record_max);
		s->recs[slot - 1]->size = size;
	}
	f->last_read_ok = 0;
	s->modified = 1;
	return set_st(f, "00");
}

static int start_rel(cob_file *f, int op)
{
	ixstate *s = ixs(f);
	cob_s64 k = rel_key(f);
	cob_s64 found = 0;
	if (op == 5 || op == 6) {
		/* START FIRST / LAST */
		for (cob_s64 i = 1; i <= (cob_s64)s->n; i++) {
			cob_s64 j = op == 5 ? i : (cob_s64)s->n + 1 - i;
			if (s->recs[j - 1]) {
				found = j;
				break;
			}
		}
	} else if (op == 0 || op == 2 || op == 1) {
		/* EQ GE GT */
		for (cob_s64 i = 1; i <= (cob_s64)s->n; i++) {
			if (!s->recs[i - 1])
				continue;
			if ((op == 0 && i == k) || (op == 1 && i > k) || (op == 2 && i >= k)) {
				found = i;
				break;
			}
		}
	} else {
		for (cob_s64 i = (cob_s64)s->n; i >= 1; i--) {
			if (!s->recs[i - 1])
				continue;
			if ((op == 3 && i < k) || (op == 4 && i <= k)) {
				found = i;
				break;
			}
		}
	}
	if (!found)
		return set_st(f, "23");
	s->rel_pos = found;
	s->rel_incl = 1;
	if (f->relative_key && (op == 5 || op == 6))
		cob_set_int(f->relative_key, found);
	f->at_end = 0;
	return set_st(f, "00");
}

/* ================================================================ indexed */

static long find_exact(cob_file *f, int k, const unsigned char *key)
{
	ixstate *s = ixs(f);
	size_t klen = f->keys[k].size;
	size_t i = lower_bound(f, k, key, klen, 0, 0, 0);
	cob_irec **ord = get_order(f, k);
	if (i < s->n && memcmp(ord[i]->data + f->keys[k].offset, key, klen) == 0)
		return (long)i;
	return -1;
}

static void set_pos(ixstate *s, cob_file *f, cob_irec *r, int k, int mode)
{
	s->key_ref = k;
	s->pos_keylen = f->keys[k].size;
	memcpy(s->pos_key, r->data + f->keys[k].offset, s->pos_keylen);
	s->pos_seq = r->kseq[k];
	s->pos_mode = mode;
}

static int read_idx(cob_file *f, int next, int key_index)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	cob_irec *r;
	if (next == 2) {
		/* READ PREVIOUS: the record before the position (at it after a START) */
		if (f->at_end)
			return set_st(f, "46");
		int k = s->key_ref;
		cob_irec **ord = get_order(f, k);
		size_t j;
		if (s->pos_mode == 0)
			j = 0;
		else if (s->pos_mode == 1)
			j = lower_bound(f, k, s->pos_key, s->pos_keylen, s->pos_seq, k != 0, 0);
		else if (s->pos_mode == 3)
			j = lower_bound(f, k, s->pos_key, s->pos_keylen, s->pos_seq, k != 0, 1);
		else
			j = lower_bound(f, k, s->pos_key, s->pos_keylen, 0, 0, 1);
		if (j == 0) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		r = ord[j - 1];
		set_pos(s, f, r, k, 1);
	} else if (next || f->access == COB_ACC_SEQUENTIAL) {
		if (f->at_end)
			return set_st(f, "46");
		int k = s->key_ref;
		cob_irec **ord = get_order(f, k);
		size_t i;
		if (s->pos_mode == 0)
			i = 0;
		else if (s->pos_mode == 1)
			i = lower_bound(f, k, s->pos_key, s->pos_keylen, s->pos_seq, k != 0, 1);
		else if (s->pos_mode == 3)
			i = lower_bound(f, k, s->pos_key, s->pos_keylen, s->pos_seq, k != 0, 0);
		else
			i = lower_bound(f, k, s->pos_key, s->pos_keylen, 0, 0, 0);
		if (i >= s->n) {
			f->at_end = 1;
			return set_st(f, "10");
		}
		r = ord[i];
		set_pos(s, f, r, k, 1);
	} else {
		int k = key_index < 0 ? 0 : key_index;
		long i = find_exact(f, k, f->record + f->keys[k].offset);
		if (i < 0)
			return set_st(f, "23");
		r = get_order(f, k)[i];
		set_pos(s, f, r, k, 1);
		f->at_end = 0;
	}
	memcpy(f->record, r->data, f->record_max);
	f->cur_size = r->size;
	if (f->size_field)
		cob_set_int(f->size_field, (cob_s64)r->size);
	s->last_read = r;
	f->last_read_ok = 1;
	return set_st(f, "00");
}

static int alt_conflict(cob_file *f, const unsigned char *rec, cob_irec *self)
{
	ixstate *s = ixs(f);
	for (int k = 1; k < f->nkeys; k++) {
		if (f->keys[k].dups)
			continue;
		long i = find_exact(f, k, rec + f->keys[k].offset);
		if (i >= 0) {
			cob_irec **ord = get_order(f, k);
			/* any match other than self? */
			size_t j = (size_t)i;
			while (j < s->n && memcmp(ord[j]->data + f->keys[k].offset, rec + f->keys[k].offset, f->keys[k].size) == 0) {
				if (ord[j] != self)
					return 1;
				j++;
			}
		}
	}
	return 0;
}

static int write_idx(cob_file *f, size_t recsize)
{
	ixstate *s = ixs(f);
	if (f->open_mode == COB_OPEN_INPUT)
		return set_st(f, "48");
	const unsigned char *key = f->record + f->keys[0].offset;
	size_t klen = f->keys[0].size;
	if (f->access == COB_ACC_SEQUENTIAL && (f->open_mode == COB_OPEN_OUTPUT || f->open_mode == COB_OPEN_EXTEND)) {
		if (s->have_last_written && memcmp(key, s->last_written, klen) <= 0)
			return set_st(f, "21");
	}
	size_t i = lower_bound(f, 0, key, klen, 0, 0, 0);
	if (i < s->n && memcmp(s->recs[i]->data + f->keys[0].offset, key, klen) == 0)
		return set_st(f, "22");
	if (alt_conflict(f, f->record, NULL))
		return set_st(f, "22");
	size_t size;
	if (new_rec_size(f, recsize, &size))
		return set_st(f, "44");
	ensure_cap(s, s->n + 1);
	memmove(s->recs + i + 1, s->recs + i, (s->n - i) * sizeof(cob_irec *));
	s->recs[i] = new_rec(f, f->record, size);
	s->n++;
	memcpy(s->last_written, key, klen);
	s->have_last_written = 1;
	invalidate(s);
	return set_st(f, "00");
}

static int rewrite_idx(cob_file *f, size_t recsize, int del)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_IO)
		return set_st(f, "49");
	const unsigned char *key = f->record + f->keys[0].offset;
	size_t klen = f->keys[0].size;
	long i;
	if (f->access == COB_ACC_SEQUENTIAL) {
		if (!f->last_read_ok || !s->last_read)
			return set_st(f, "43");
		if (!del && memcmp(s->last_read->data + f->keys[0].offset, key, klen) != 0)
			return set_st(f, "21");
		key = s->last_read->data + f->keys[0].offset;
	}
	i = find_exact(f, 0, key);
	if (i < 0)
		return set_st(f, "23");
	cob_irec *r = s->recs[i];
	if (del) {
		if (s->last_read == r)
			s->last_read = NULL;
		free_rec(r);
		memmove(s->recs + i, s->recs + i + 1, (s->n - (size_t)i - 1) * sizeof(cob_irec *));
		s->n--;
	} else {
		size_t size;
		if (new_rec_size(f, recsize, &size))
			return set_st(f, "44");
		if (alt_conflict(f, f->record, r))
			return set_st(f, "22");
		for (int k = 1; k < f->nkeys; k++)
			if (memcmp(r->data + f->keys[k].offset, f->record + f->keys[k].offset, f->keys[k].size) != 0)
				r->kseq[k] = s->next_seq++;
		memcpy(r->data, f->record, f->record_max);
		r->size = size;
	}
	f->last_read_ok = 0;
	invalidate(s);
	return set_st(f, "00");
}

static int start_idx(cob_file *f, int op, int k, size_t keylen)
{
	ixstate *s = ixs(f);
	if (k < 0)
		k = 0;
	if (keylen == 0 || keylen > f->keys[k].size)
		keylen = f->keys[k].size;
	const unsigned char *key = f->record + f->keys[k].offset;
	cob_irec **ord = get_order(f, k);
	size_t i;
	switch (op) {
	case 5: /* FIRST */
	case 6: /* LAST */
		if (s->n == 0)
			return set_st(f, "23");
		i = op == 5 ? 0 : s->n - 1;
		break;
	case 0: /* EQ */
		i = lower_bound(f, k, key, keylen, 0, 0, 0);
		if (i >= s->n || memcmp(ord[i]->data + f->keys[k].offset, key, keylen) != 0)
			return set_st(f, "23");
		break;
	case 1: /* GT */
		i = lower_bound(f, k, key, keylen, 0, 0, 1);
		if (i >= s->n)
			return set_st(f, "23");
		break;
	case 2: /* GE */
		i = lower_bound(f, k, key, keylen, 0, 0, 0);
		if (i >= s->n)
			return set_st(f, "23");
		break;
	case 3: /* LT */
		i = lower_bound(f, k, key, keylen, 0, 0, 0);
		if (i == 0)
			return set_st(f, "23");
		i--;
		break;
	default: /* LE */
		i = lower_bound(f, k, key, keylen, 0, 0, 1);
		if (i == 0)
			return set_st(f, "23");
		i--;
		break;
	}
	/* the position indicator points at record i: READ NEXT and READ
	   PREVIOUS both return it */
	s->key_ref = k;
	s->pos_keylen = f->keys[k].size;
	memcpy(s->pos_key, ord[i]->data + f->keys[k].offset, s->pos_keylen);
	s->pos_seq = ord[i]->kseq[k];
	s->pos_mode = 3;
	f->at_end = 0;
	return set_st(f, "00");
}

/* ================================================================ dispatch */

int cob_read(cob_file *f, int next, int key_index)
{
	f->last_read_ok = 0;
	if (!f->open_mode)
		return set_st(f, "47");
	switch (f->organization) {
	case COB_ORG_RELATIVE:
		return read_rel(f, next);
	case COB_ORG_INDEXED:
		return read_idx(f, next, key_index);
	default:
		return read_seq(f);
	}
}

int cob_write(cob_file *f, size_t recsize, int adv_when, int adv_lines)
{
	f->last_read_ok = 0;
	if (!f->open_mode)
		return set_st(f, "48");
	switch (f->organization) {
	case COB_ORG_RELATIVE:
		return write_rel(f, recsize);
	case COB_ORG_INDEXED:
		return write_idx(f, recsize);
	default:
		return write_seq(f, recsize, adv_when, adv_lines);
	}
}

int cob_rewrite(cob_file *f, size_t recsize)
{
	int rc;
	if (!f->open_mode)
		rc = set_st(f, "49");
	else switch (f->organization) {
	case COB_ORG_RELATIVE:
		rc = rewrite_rel(f, recsize, 0);
		break;
	case COB_ORG_INDEXED:
		rc = rewrite_idx(f, recsize, 0);
		break;
	default:
		rc = rewrite_seq(f, recsize);
		break;
	}
	f->last_read_ok = 0;
	return rc;
}

int cob_delete(cob_file *f)
{
	int rc;
	if (!f->open_mode)
		rc = set_st(f, "49");
	else switch (f->organization) {
	case COB_ORG_RELATIVE:
		rc = rewrite_rel(f, 0, 1);
		break;
	case COB_ORG_INDEXED:
		rc = rewrite_idx(f, 0, 1);
		break;
	default:
		rc = set_st(f, "30");
		break;
	}
	f->last_read_ok = 0;
	return rc;
}

/* op: 0 EQ 1 GT 2 GE 3 LT 4 LE */
int cob_start(cob_file *f, int op, int key_index, size_t keylen)
{
	f->last_read_ok = 0;
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	switch (f->organization) {
	case COB_ORG_RELATIVE:
		return start_rel(f, op);
	case COB_ORG_INDEXED:
		return start_idx(f, op, key_index, keylen);
	default:
		return set_st(f, "30");
	}
}

/* ================================================================ SORT */

static const cob_sort_key *g_keys;
static int g_nkeys;

typedef struct {
	unsigned char *rec;
	size_t seq;
} srec;

static int key_compare(const unsigned char *a, const unsigned char *b, int nkeys, const cob_sort_key *keys)
{
	for (int k = 0; k < nkeys; k++) {
		cob_field fa = { keys[k].size, (unsigned char *)a + keys[k].offset, keys[k].attr };
		cob_field fb = { keys[k].size, (unsigned char *)b + keys[k].offset, keys[k].attr };
		int c = cob_cmp(&fa, &fb);
		if (c)
			return keys[k].desc ? -c : c;
	}
	return 0;
}

static int srec_cmp(const void *pa, const void *pb)
{
	const srec *a = pa, *b = pb;
	int c = key_compare(a->rec, b->rec, g_nkeys, g_keys);
	if (c)
		return c;
	return a->seq < b->seq ? -1 : (a->seq > b->seq ? 1 : 0);
}

void cob_sort_init(cob_file *sd, int nkeys, const cob_sort_key *keys, int dups)
{
	(void)dups;
	sd->sbuf = NULL;
	sd->scount = sd->scap = sd->sret = 0;
	sd->sort_nkeys = nkeys;
	sd->sort_keys = keys;
	sd->is_sort = 1;
	cob_set_int(&cob_sort_return_reg, 0);
}

static void sort_add(cob_file *sd, const unsigned char *rec, size_t n)
{
	if (sd->scount == sd->scap) {
		sd->scap = sd->scap ? sd->scap * 2 : 256;
		sd->sbuf = realloc(sd->sbuf, sd->scap * sizeof(unsigned char *));
		if (!sd->sbuf)
			cob_fatal("out of memory in SORT");
	}
	unsigned char *r = cob_malloc(sd->record_max);
	memset(r, ' ', sd->record_max);
	memcpy(r, rec, n > sd->record_max ? sd->record_max : n);
	sd->sbuf[sd->scount++] = r;
}

void cob_sort_using(cob_file *sd, cob_file *in)
{
	int rc = cob_open(in, COB_OPEN_INPUT);
	if (rc != COB_IO_OK && in->stat[0] == '3' && in->stat[1] == '5')
		return;     /* a missing USING file contributes no records */
	if (rc != COB_IO_OK) {
		cob_io_unhandled(in, rc, "SORT USING");
		return;
	}
	for (;;) {
		rc = cob_read(in, 1, -1);
		if (rc != COB_IO_OK)
			break;
		size_t n = in->organization == COB_ORG_LINE_SEQ ? in->record_max : in->record_max;
		sort_add(sd, in->record, n);
	}
	cob_close(in);
}

void cob_sort_release(cob_file *sd)
{
	sort_add(sd, sd->record, sd->record_max);
}

void cob_sort_sort(cob_file *sd)
{
	srec *a = cob_malloc((sd->scount + 1) * sizeof(srec));
	for (size_t i = 0; i < sd->scount; i++) {
		a[i].rec = sd->sbuf[i];
		a[i].seq = i;
	}
	g_keys = (const cob_sort_key *)sd->sort_keys;
	g_nkeys = sd->sort_nkeys;
	const unsigned short *save = cob_get_collating();
	if (sd->sort_coll)
		cob_set_collating(sd->sort_coll);
	qsort(a, sd->scount, sizeof(srec), srec_cmp);
	cob_set_collating(save);
	for (size_t i = 0; i < sd->scount; i++)
		sd->sbuf[i] = a[i].rec;
	free(a);
	sd->sret = 0;
}

void cob_sort_giving(cob_file *sd, cob_file *out)
{
	int rc = cob_open(out, COB_OPEN_OUTPUT);
	if (rc != COB_IO_OK) {
		cob_io_unhandled(out, rc, "SORT GIVING");
		return;
	}
	for (size_t i = 0; i < sd->scount; i++) {
		size_t n = sd->record_max < out->record_max ? sd->record_max : out->record_max;
		memset(out->record, ' ', out->record_max);
		memcpy(out->record, sd->sbuf[i], n);
		cob_write(out, out->record_max, COB_ADV_NONE, 0);
	}
	cob_close(out);
}

int cob_sort_return(cob_file *sd)
{
	if (sd->sret >= sd->scount)
		return COB_IO_ATEND;
	memcpy(sd->record, sd->sbuf[sd->sret++], sd->record_max);
	return COB_IO_OK;
}

void cob_sort_end(cob_file *sd)
{
	for (size_t i = 0; i < sd->scount; i++)
		free(sd->sbuf[i]);
	free(sd->sbuf);
	sd->sbuf = NULL;
	sd->scount = sd->scap = sd->sret = 0;
}

void cob_table_sort(unsigned char *base, size_t n, size_t elem, int nkeys, const cob_sort_key *keys)
{
	if (n < 2)
		return;
	srec *a = cob_malloc(n * sizeof(srec));
	unsigned char *copy = cob_malloc(n * elem);
	memcpy(copy, base, n * elem);
	for (size_t i = 0; i < n; i++) {
		a[i].rec = copy + i * elem;
		a[i].seq = i;
	}
	g_keys = keys;
	g_nkeys = nkeys;
	qsort(a, n, sizeof(srec), srec_cmp);
	for (size_t i = 0; i < n; i++)
		memcpy(base + i * elem, a[i].rec, elem);
	free(a);
	free(copy);
}
