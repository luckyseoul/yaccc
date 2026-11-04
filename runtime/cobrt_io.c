/* SPDX-License-Identifier: MIT */
/* cobrt_io.c - file I/O (sequential, line sequential, relative, indexed) and SORT */
#include "cobrt.h"
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/mman.h>
#include <fcntl.h>

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
	size_t ord_n[COB_MAX_KEYS];   /* records indexed under each key */
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
	/* the file on disk (see "the journal" below) */
	int fd;                   /* open while the file is; -1 for a missing OPTIONAL file */
	int journal;              /* the file is a journal: each change is appended to it */
	int writable;
	int sync;                 /* someone else may change it: catch up before each statement */
	int reload;               /* this process rewrote it under this connector: read it again */
	off_t log_end;            /* how much of the journal is applied */
	size_t live_bytes;        /* what the live records take in a fresh journal */
	/* record locks this connector holds: hashes of their keys or numbers */
	cob_u64 *held;
	size_t nheld, heldcap;
	unsigned char *map;       /* the journal's header, shared with the other connectors */
	int locker;               /* this connector is counted among those that lock records */
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
	case 51: return "record locked by another file connector";
	case 61: return "file in use (sharing conflict)";
	default: return "I/O error";
	}
}

void cob_io_unhandled(cob_file *f, int rc, const char *loc)
{
	if (rc == COB_IO_OK)
		return;
	if (f->status)
		return;
	if (f->path[0] && f->given[0] && strcmp(f->given, f->path) != 0)
		/* the name the program gave and the file it became */
		cob_fatal("%s: %s (status = %c%c) for file %s ('%s' => %s)", loc, status_msg(f->stat),
			  f->stat[0], f->stat[1], f->select_name, f->given, f->path);
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
	if (f->assign_field && f->assign_field->data)
		trim_copy(name, sizeof name, f->assign_field->data, f->assign_field->size);
	else if (f->assign_field)
		name[0] = 0;            /* BASED assign item never allocated */
	else if (f->assign_name)
		snprintf(name, sizeof name, "%s", f->assign_name);
	else
		snprintf(name, sizeof name, "%s", f->select_name);
	snprintf(f->given, sizeof f->given, "%s", name);
	if (f->no_mapping) {
		snprintf(f->path, sizeof f->path, "%s", name);
		return;
	}
	/* $VAR/rest: the directory from the environment */
	if (name[0] == '$') {
		char mapped[1024];
		cob_map_filename(name, mapped, sizeof mapped);
		snprintf(name, sizeof name, "%s", mapped);
	}
	/* DD_<name> overrides the name, whatever form ASSIGN took (GnuCOBOL does
	   the same for a literal and for a data item), unless the name is a path */
	if (!strchr(name, '/') && !strchr(name, '.')) {
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
	/* COB_FILE_PATH: the directory for a name that names none */
	const char *dir = getenv("COB_FILE_PATH");
	if (dir && *dir && name[0] && !strchr(name, '/')) {
		size_t dl = strlen(dir);
		snprintf(f->path, sizeof f->path, "%s%s%s", dir, dir[dl - 1] == '/' ? "" : "/", name);
		return;
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

/* copy a key's segments out of a record, in order; returns the byte count */
static size_t gather_key(const cob_file *f, int k, const unsigned char *rec, unsigned char *out)
{
	const cob_file_key *key = &f->keys[k];
	if (key->nseg <= 1) {
		memcpy(out, rec + key->offset, key->size);
		return key->size;
	}
	size_t o = 0;
	for (int i = 0; i < key->nseg && i < COB_KEY_MAX_SEGS; i++) {
		memcpy(out + o, rec + key->seg[i].offset, key->seg[i].size);
		o += key->seg[i].size;
	}
	return o;
}

static int key_cmp_rec(const cob_file *f, int k, const unsigned char *a, const unsigned char *b)
{
	const cob_file_key *key = &f->keys[k];
	if (key->nseg <= 1)
		return memcmp(a + key->offset, b + key->offset, key->size);
	unsigned char ka[COB_KEY_MAX_SEGS * 512], kb[COB_KEY_MAX_SEGS * 512];
	size_t n = gather_key(f, k, a, ka);
	gather_key(f, k, b, kb);
	return memcmp(ka, kb, n);
}

static ixstate *ixs(cob_file *f)
{
	if (!f->ix) {
		ixstate *s = cob_malloc(sizeof(ixstate));
		s->fd = -1;
		f->ix = s;
	}
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
	free(s->held);
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

/* SUPPRESS WHEN: is this record left out of key k's index? The clause names a
 * value; with ALL every segment must be that value, otherwise any one of them
 * must. A single character stands for a field filled with it, which is how
 * GnuCOBOL reads "SUPPRESS WHEN ALL '*'" (its cobc emits char_suppress). */
static int key_suppressed(const cob_file *f, int k, const unsigned char *rec)
{
	const cob_file_key *key = &f->keys[k];
	if (!key->supp || !key->supplen)
		return 0;
	unsigned char kbuf[COB_KEY_MAX_SEGS * 512];
	gather_key(f, k, rec, kbuf);
	int seen = 0;
	size_t off = 0;
	for (int i = 0; i < key->nseg && i < COB_KEY_MAX_SEGS; i++) {
		const unsigned char *seg = kbuf + off;
		size_t n = key->seg[i].size;
		off += n;
		int hit;
		if (key->supplen == 1) {
			hit = n > 0;
			for (size_t b = 0; b < n; b++)
				if (seg[b] != key->supp[0]) {
					hit = 0;
					break;
				}
		} else {
			hit = n == key->supplen && memcmp(seg, key->supp, n) == 0;
		}
		if (key->supp_all) {
			if (!hit)
				return 0;
			seen++;
		} else if (hit) {
			return 1;
		}
	}
	return key->supp_all && seen == key->nseg;
}

static cob_irec **get_order(cob_file *f, int k)
{
	ixstate *s = ixs(f);
	if (k == 0)
		return s->recs;
	if (!s->ord_valid[k]) {
		free(s->ord[k]);
		s->ord[k] = cob_malloc((s->n + 1) * sizeof(cob_irec *));
		size_t m = 0;
		for (size_t i = 0; i < s->n; i++) {
			if (!s->recs[i])
				continue;
			if (f->keys[k].supp && key_suppressed(f, k, s->recs[i]->data))
				continue;
			s->ord[k][m++] = s->recs[i];
		}
		sort_file_ctx = f;
		sort_key_ctx = k;
		qsort(s->ord[k], m, sizeof(cob_irec *), ord_cmp);
		s->ord_n[k] = m;
		s->ord_valid[k] = 1;
	}
	return s->ord[k];
}

/* how many records key k indexes: fewer than s->n for a sparse key */
static size_t ord_count(cob_file *f, int k)
{
	ixstate *s = ixs(f);
	if (k == 0)
		return s->n;
	get_order(f, k);
	return s->ord_n[k];
}

/* binary search in ordering k: first index with (key prefix, seq) relation */
static size_t lower_bound(cob_file *f, int k, const unsigned char *key, size_t klen, cob_u64 seq, int use_seq, int strict)
{
	cob_irec **ord = get_order(f, k);
	size_t lo = 0, hi = ord_count(f, k);
	const cob_file_key *fk = &f->keys[k];
	while (lo < hi) {
		size_t mid = (lo + hi) / 2;
		int c;
		if (fk->nseg <= 1) {
			c = memcmp(ord[mid]->data + fk->offset, key, klen);
		} else {
			/* a split key is not contiguous in the record: gather it */
			unsigned char mid_key[COB_KEY_MAX_SEGS * 512];
			gather_key(f, k, ord[mid]->data, mid_key);
			c = memcmp(mid_key, key, klen);
		}
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

/* ================================================================ sharing and locks
 *
 * Who may have a file open is settled with byte-range locks far past its end,
 * taken on an open file description of their own (Linux OFD locks: they
 * belong to the description, not to the process, so closing one descriptor
 * drops nothing taken through another):
 *   LK_READERS  every connector holds it shared; one that has the file to
 *               itself (SHARING NO, LOCK MODE EXCLUSIVE, OPEN ... WITH LOCK,
 *               OPEN OUTPUT, and a sequential file opened I-O or EXTEND
 *               without SHARING or LOCK MODE) holds it exclusively
 *   LK_WRITERS  a connector that may change the file holds it shared, and
 *               SHARING READ ONLY exclusively: no one else may write
 * A process holds one set of these per file however many of its connectors
 * have the file open, so a program and the programs it calls can each open
 * it. Record locks are each connector's own, at LK_RECORDS plus a hash of
 * the record's key (or its relative record number), and LK_JOURNAL is held
 * while a connector appends to a journal or reads what others appended. */
#ifdef F_OFD_SETLK
#define LK_SET  F_OFD_SETLK
#define LK_SETW F_OFD_SETLKW
#define LK_GET  F_OFD_GETLK
#else
#define LK_SET  F_SETLK
#define LK_SETW F_SETLKW
#define LK_GET  F_GETLK
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#define LK_READERS ((off_t)1 << 62)
#define LK_WRITERS (LK_READERS + 1)
#define LK_JOURNAL (LK_READERS + 2)
#define LK_RECORDS ((off_t)1 << 61)
#define LK_RECSPAN ((cob_u64)1 << 60)

static int lk(int fd, int cmd, int type, off_t at)
{
	struct flock l;
	memset(&l, 0, sizeof l);
	l.l_type = (short)type;
	l.l_whence = SEEK_SET;
	l.l_start = at;
	l.l_len = 1;
	int rc;
	while ((rc = fcntl(fd, cmd, &l)) != 0 && errno == EINTR)
		;
	return rc;
}

/* whether another descriptor holds a lock on the byte */
static int lk_busy(int fd, off_t at)
{
	struct flock l;
	memset(&l, 0, sizeof l);
	l.l_type = F_WRLCK;
	l.l_whence = SEEK_SET;
	l.l_start = at;
	l.l_len = 1;
	if (fcntl(fd, LK_GET, &l) != 0)
		return 0;
	return l.l_type != F_UNLCK;
}

typedef struct holder {
	dev_t dev;
	ino_t ino;
	int fd;                   /* a description of its own, for the locks */
	int refs;                 /* connectors of this process with the file open */
	int readers, writers;     /* what it holds: F_UNLCK, F_RDLCK or F_WRLCK */
	struct holder *next;
} holder;
static holder *holders;

static int lock_rank(int t)
{
	return t == F_WRLCK ? 2 : t == F_RDLCK ? 1 : 0;
}

/* raise a holder's lock on byte `at` to `want`; -1 when another process
 * holds a lock in the way */
static int raise_lock(holder *h, int *have, int want, off_t at)
{
	if (lock_rank(want) <= lock_rank(*have))
		return 0;
	if (lk(h->fd, LK_SET, want, at) != 0) {
		if (errno == EBADF)
			return 0;       /* a read-only file can't be locked for writing */
		return -1;
	}
	*have = want;
	return 0;
}

/* the file-level locks an OPEN needs: 0, or -1 (status 61) when another
 * process has the file in a way this OPEN can't share */
static int take_file_locks(cob_file *f, int fd, int mode)
{
	struct stat st;
	if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode))
		return 0;               /* a terminal, a pipe, a device: nothing to share */
	int seq = f->organization == COB_ORG_SEQUENTIAL || f->organization == COB_ORG_LINE_SEQ;
	int alone = mode == COB_OPEN_OUTPUT || f->sharing == COB_SHARE_NO || f->lock_mode == 3 ||
		    f->open_lock ||
		    (seq && f->sharing == COB_SHARE_NONE && f->lock_mode == 0 && mode != COB_OPEN_INPUT);
	int want_r = alone ? F_WRLCK : F_RDLCK;
	int want_w = f->sharing == COB_SHARE_READ_ONLY ? F_WRLCK :
		     mode != COB_OPEN_INPUT ? F_RDLCK : F_UNLCK;
	holder *h;
	for (h = holders; h; h = h->next)
		if (h->dev == st.st_dev && h->ino == st.st_ino)
			break;
	int fresh = h == NULL;
	if (fresh) {
		/* a new description of the same file: through /proc, so a rename
		   since this OPEN can't give another file */
		char proc[64];
		snprintf(proc, sizeof proc, "/proc/self/fd/%d", fd);
		int hfd = open(proc, O_RDWR | O_CLOEXEC);
		if (hfd < 0)
			hfd = open(proc, O_RDONLY | O_CLOEXEC);
		if (hfd < 0)
			hfd = open(f->path, O_RDWR | O_CLOEXEC);
		if (hfd < 0)
			hfd = open(f->path, O_RDONLY | O_CLOEXEC);
		if (hfd < 0)
			return 0;
		h = cob_malloc(sizeof *h);
		h->dev = st.st_dev;
		h->ino = st.st_ino;
		h->fd = hfd;
		h->readers = h->writers = F_UNLCK;
	}
	int r0 = h->readers, w0 = h->writers;
	if (raise_lock(h, &h->readers, want_r, LK_READERS) != 0 ||
	    raise_lock(h, &h->writers, want_w, LK_WRITERS) != 0) {
		if (fresh) {
			close(h->fd);
			free(h);
		} else {
			/* back to what the process held before */
			if (h->readers != r0)
				lk(h->fd, LK_SET, r0, LK_READERS);
			if (h->writers != w0)
				lk(h->fd, LK_SET, w0, LK_WRITERS);
			h->readers = r0;
			h->writers = w0;
		}
		return -1;
	}
	if (fresh) {
		h->next = holders;
		holders = h;
	}
	h->refs++;
	f->holder = h;
	return 0;
}

static void drop_file_locks(cob_file *f)
{
	holder *h = f->holder;
	if (!h)
		return;
	f->holder = NULL;
	if (--h->refs > 0)
		return;
	close(h->fd);           /* the locks go with the description */
	for (holder **pp = &holders; *pp; pp = &(*pp)->next)
		if (*pp == h) {
			*pp = h->next;
			break;
		}
	free(h);
}

/* the other connectors of this process that have the same file open */
static int same_file_open(cob_file *f)
{
	int n = 0;
	for (cob_file *o = open_list; o; o = o->next_open)
		if (o != f && o->holder && o->holder == f->holder)
			n++;
	return n;
}

/* ================================================================ the journal
 *
 * A relative or indexed file is a journal: a header, then an entry for every
 * WRITE, REWRITE and DELETE, appended as the statement runs, so what a
 * program has done is on disk however it ends. OPEN reads the journal into
 * memory, where the records are kept in key order. A connector that may not
 * be alone with the file reads what others have appended before each
 * statement, and appends under LK_JOURNAL. The last connector to CLOSE a
 * journal made mostly of superseded entries writes the live records to a
 * fresh one and renames it over the file.
 *
 *   header  "CIXJ", u32 version (1), u32 organization, u32 key count,
 *           u64 record size, u64 where the journal ends (0: not known),
 *           u32 how many connectors may be holding record locks, zeros to 64
 *           bytes; the last two are read and written through a shared
 *           mapping, so a statement that finds nothing new needs no system
 *           call to know it
 *   entry   u32 size of the entry, u8 'W' (WRITE), 'R' (REWRITE) or 'D'
 *           (DELETE), u8 key count n, u16 0, u64 relative record number (0
 *           when indexed), u32 record length, n u64 sequence numbers (the
 *           order of duplicates under each key), the record, the size again
 *
 * COB_SYNC=Y makes every change wait until it is on the disk (fdatasync).
 * Files in the format of earlier versions are read, and rewritten as a
 * journal the first time they are opened for update by a lone connector. */
#define J_MAGIC "CIXJ"
#define J_HDR 64
#define J_FIXED 24

static size_t j_entry_size(int nk, size_t len)
{
	return J_FIXED + (size_t)nk * 8 + len + 4;
}

static int j_nkeys(const cob_file *f)
{
	return f->organization == COB_ORG_INDEXED ? (f->nkeys > 0 ? f->nkeys : 1) : 0;
}

static int sync_wanted(void)
{
	static int v = -1;
	if (v < 0) {
		const char *e = getenv("COB_SYNC");
		v = e && (strchr("YyTt1", e[0]) != NULL || strcasecmp(e, "on") == 0);
	}
	return v;
}

static void put32(unsigned char *p, uint32_t v)
{
	memcpy(p, &v, 4);
}

static void put64(unsigned char *p, cob_u64 v)
{
	memcpy(p, &v, 8);
}

static uint32_t get32(const unsigned char *p)
{
	uint32_t v;
	memcpy(&v, p, 4);
	return v;
}

static cob_u64 get64(const unsigned char *p)
{
	cob_u64 v;
	memcpy(&v, p, 8);
	return v;
}

static void j_header(const cob_file *f, unsigned char *h)
{
	memset(h, 0, J_HDR);
	memcpy(h, J_MAGIC, 4);
	put32(h + 4, 1);
	put32(h + 8, (uint32_t)f->organization);
	put32(h + 12, (uint32_t)j_nkeys(f));
	put64(h + 16, (cob_u64)f->record_max);
}

static size_t j_encode(unsigned char *b, int op, cob_u64 slot, const unsigned char *data, size_t len,
		       const cob_u64 *kseq, int nk)
{
	size_t sz = j_entry_size(nk, len);
	put32(b, (uint32_t)sz);
	b[4] = (unsigned char)op;
	b[5] = (unsigned char)nk;
	b[6] = b[7] = 0;
	put64(b + 8, slot);
	put32(b + 16, (uint32_t)len);
	put32(b + 20, 0);
	unsigned char *p = b + J_FIXED;
	for (int k = 0; k < nk; k++, p += 8)
		put64(p, kseq[k]);
	memcpy(p, data, len);
	put32(p + len, (uint32_t)sz);
	return sz;
}

/* ---------------------------------------------------------------- applying entries */

static size_t rec_entry_size(cob_file *f, const cob_irec *r)
{
	return j_entry_size(j_nkeys(f), r->size);
}

static cob_irec *irec_make(cob_file *f, const unsigned char *data, size_t len, const cob_u64 *kseq, int nk)
{
	if (len > f->record_max)
		len = f->record_max;
	cob_irec *r = cob_malloc(sizeof *r);
	r->data = cob_malloc(f->record_max);
	memset(r->data, ' ', f->record_max);
	memcpy(r->data, data, len);
	r->size = len;
	int n = f->nkeys > 0 ? f->nkeys : 1;
	r->kseq = cob_malloc(sizeof(cob_u64) * (size_t)n);
	for (int k = 0; k < n; k++)
		r->kseq[k] = k < nk ? kseq[k] : (nk ? kseq[0] : 0);
	r->seq = r->kseq[0];
	return r;
}

static void irec_set(cob_file *f, cob_irec *r, const unsigned char *data, size_t len, const cob_u64 *kseq, int nk)
{
	if (len > f->record_max)
		len = f->record_max;
	memset(r->data, ' ', f->record_max);
	memcpy(r->data, data, len);
	r->size = len;
	int n = f->nkeys > 0 ? f->nkeys : 1;
	for (int k = 0; k < n && k < nk; k++)
		r->kseq[k] = kseq[k];
	r->seq = r->kseq[0];
}

static long find_exact(cob_file *f, int k, const unsigned char *key);

/* an entry, applied to the records in memory (the same for this connector's
 * own statements and for what others appended) */
static void apply_entry(cob_file *f, int op, cob_u64 slot, const unsigned char *data, size_t len,
			const cob_u64 *kseq, int nk)
{
	ixstate *s = ixs(f);
	for (int k = 0; k < nk; k++)
		if (kseq[k] >= s->next_seq)
			s->next_seq = kseq[k] + 1;
	if (f->organization == COB_ORG_RELATIVE) {
		if (slot < 1 || slot > ((cob_u64)1 << 40))
			return;
		size_t i = (size_t)slot - 1;
		ensure_cap(s, i + 1);
		cob_irec *r = s->recs[i];
		if (op == 'D') {
			if (r) {
				s->live_bytes -= rec_entry_size(f, r);
				free_rec(r);
				s->recs[i] = NULL;
			}
		} else if (r) {
			s->live_bytes -= rec_entry_size(f, r);
			irec_set(f, r, data, len, kseq, nk);
			s->live_bytes += rec_entry_size(f, r);
		} else {
			s->recs[i] = r = irec_make(f, data, len, kseq, nk);
			s->live_bytes += rec_entry_size(f, r);
			if (i + 1 > s->n)
				s->n = i + 1;
		}
		s->modified = 1;
		return;
	}
	/* indexed: the record with the entry's primary key (from the record as
	   it would be in the record area: a short one padded with spaces) */
	unsigned char stackpad[8192];
	unsigned char *pad = (const unsigned char *)data == NULL ? NULL : stackpad;
	if (len >= f->record_max)
		pad = (unsigned char *)data;
	else {
		if (f->record_max > sizeof stackpad)
			pad = cob_malloc(f->record_max);
		memset(pad, ' ', f->record_max);
		memcpy(pad, data, len);
	}
	unsigned char key[COB_KEY_MAX_SEGS * 512];
	size_t klen = gather_key(f, 0, pad, key);
	long i = find_exact(f, 0, key);
	if (op == 'D') {
		if (i >= 0) {
			cob_irec *r = s->recs[i];
			if (s->last_read == r)
				s->last_read = NULL;
			s->live_bytes -= rec_entry_size(f, r);
			free_rec(r);
			memmove(s->recs + i, s->recs + i + 1, (s->n - (size_t)i - 1) * sizeof(cob_irec *));
			s->n--;
		}
	} else if (i >= 0) {
		cob_irec *r = s->recs[i];
		s->live_bytes -= rec_entry_size(f, r);
		irec_set(f, r, data, len, kseq, nk);
		s->live_bytes += rec_entry_size(f, r);
	} else {
		size_t at = lower_bound(f, 0, key, klen, 0, 0, 0);
		ensure_cap(s, s->n + 1);
		memmove(s->recs + at + 1, s->recs + at, (s->n - at) * sizeof(cob_irec *));
		s->recs[at] = irec_make(f, data, len, kseq, nk);
		s->live_bytes += rec_entry_size(f, s->recs[at]);
		s->n++;
	}
	if (pad != stackpad && pad != data)
		free(pad);
	invalidate(s);
}

/* ---------------------------------------------------------------- reading the journal */

typedef void (*entry_fn)(cob_file *, int, cob_u64, const unsigned char *, size_t, const cob_u64 *, int);

/* the entries in [from, to), each given to fn; returns where the complete
 * ones end */
static off_t j_replay(cob_file *f, off_t from, off_t to, entry_fn fn)
{
	ixstate *s = ixs(f);
	size_t cap = 1 << 16;
	unsigned char *buf = cob_malloc(cap);
	size_t pos = 0, have = 0;       /* unread bytes: buf[pos .. have) */
	off_t at = from;                /* file offset of buf[pos] */
	cob_u64 *kseq = cob_malloc(sizeof(cob_u64) * 256);
	for (;;) {
		size_t avail = have - pos;
		uint32_t sz = avail >= 4 ? get32(buf + pos) : 0;
		if (avail < 4 || avail < sz) {
			/* refill: what is left to the front, then read */
			if (at + (off_t)avail >= to)
				break;
			memmove(buf, buf + pos, avail);
			pos = 0;
			have = avail;
			if (sz > cap) {
				cap = sz;
				buf = realloc(buf, cap);
				if (!buf)
					cob_fatal("out of memory");
			}
			off_t want = to - (at + (off_t)have);
			if (want > (off_t)(cap - have))
				want = (off_t)(cap - have);
			ssize_t n = pread(s->fd, buf + have, (size_t)want, at + (off_t)have);
			if (n <= 0)
				break;
			have += (size_t)n;
			continue;
		}
		if (sz < J_FIXED + 4 || at + (off_t)sz > to)
			break;          /* the last entry, still being written (or cut short) */
		const unsigned char *e = buf + pos;
		if (get32(e + sz - 4) != sz)
			break;
		int op = e[4], nk = e[5];
		cob_u64 slot = get64(e + 8);
		size_t len = get32(e + 16);
		if (j_entry_size(nk, len) != sz)
			break;
		for (int k = 0; k < nk; k++)
			kseq[k] = get64(e + J_FIXED + (size_t)k * 8);
		fn(f, op, slot, e + J_FIXED + (size_t)nk * 8, len, kseq, nk);
		at += sz;
		pos += sz;
	}
	free(kseq);
	free(buf);
	return at;
}

/* OPEN of an indexed file: its records found by key in a hash table while
 * the journal is read, and sorted once at the end (one at a time into the
 * sorted array would be quadratic for a journal in random key order) */
static struct {
	cob_irec **tab;           /* open addressing */
	size_t cap, used;
} bulk;

static cob_u64 key_hash(const unsigned char *k, size_t n)
{
	cob_u64 h = 1469598103934665603ULL;
	for (size_t i = 0; i < n; i++) {
		h ^= k[i];
		h *= 1099511628211ULL;
	}
	return h;
}

static void bulk_grow(cob_file *f)
{
	size_t ncap = bulk.cap ? bulk.cap * 2 : 1024;
	cob_irec **nt = cob_malloc(ncap * sizeof(cob_irec *));
	unsigned char key[COB_KEY_MAX_SEGS * 512];
	for (size_t i = 0; i < bulk.cap; i++) {
		cob_irec *r = bulk.tab[i];
		if (!r)
			continue;
		size_t n = gather_key(f, 0, r->data, key);
		size_t j = (size_t)key_hash(key, n) & (ncap - 1);
		while (nt[j])
			j = (j + 1) & (ncap - 1);
		nt[j] = r;
	}
	free(bulk.tab);
	bulk.tab = nt;
	bulk.cap = ncap;
}

static void bulk_entry(cob_file *f, int op, cob_u64 slot, const unsigned char *data, size_t len,
		       const cob_u64 *kseq, int nk)
{
	ixstate *s = ixs(f);
	(void)slot;
	for (int k = 0; k < nk; k++)
		if (kseq[k] >= s->next_seq)
			s->next_seq = kseq[k] + 1;
	if ((bulk.used + 1) * 2 > bulk.cap)
		bulk_grow(f);
	unsigned char key[COB_KEY_MAX_SEGS * 512], other[COB_KEY_MAX_SEGS * 512];
	size_t n;
	if (len >= f->record_max)
		n = gather_key(f, 0, data, key);
	else {
		unsigned char *pad = cob_malloc(f->record_max);
		memset(pad, ' ', f->record_max);
		memcpy(pad, data, len);
		n = gather_key(f, 0, pad, key);
		free(pad);
	}
	size_t j = (size_t)key_hash(key, n) & (bulk.cap - 1);
	for (; bulk.tab[j]; j = (j + 1) & (bulk.cap - 1)) {
		gather_key(f, 0, bulk.tab[j]->data, other);
		if (memcmp(key, other, n) == 0)
			break;
	}
	cob_irec *r = bulk.tab[j];
	if (op == 'D') {
		if (r) {
			/* removed from the table: the run after it is placed again */
			free_rec(r);
			bulk.tab[j] = NULL;
			bulk.used--;
			for (size_t i = (j + 1) & (bulk.cap - 1); bulk.tab[i]; i = (i + 1) & (bulk.cap - 1)) {
				cob_irec *m = bulk.tab[i];
				bulk.tab[i] = NULL;
				size_t mn = gather_key(f, 0, m->data, other);
				size_t q = (size_t)key_hash(other, mn) & (bulk.cap - 1);
				while (bulk.tab[q])
					q = (q + 1) & (bulk.cap - 1);
				bulk.tab[q] = m;
			}
		}
	} else if (r) {
		irec_set(f, r, data, len, kseq, nk);
	} else {
		bulk.tab[j] = irec_make(f, data, len, kseq, nk);
		bulk.used++;
	}
}

/* the whole journal, as OPEN reads it */
static void j_load(cob_file *f, off_t size)
{
	ixstate *s = ixs(f);
	s->live_bytes = 0;
	if (f->organization != COB_ORG_INDEXED) {
		s->log_end = j_replay(f, J_HDR, size, apply_entry);
		s->modified = 0;
		return;
	}
	memset(&bulk, 0, sizeof bulk);
	bulk_grow(f);
	s->log_end = j_replay(f, J_HDR, size, bulk_entry);
	ensure_cap(s, s->n + bulk.used + 1);
	for (size_t i = 0; i < bulk.cap; i++)
		if (bulk.tab[i]) {
			s->recs[s->n++] = bulk.tab[i];
			s->live_bytes += rec_entry_size(f, bulk.tab[i]);
		}
	free(bulk.tab);
	memset(&bulk, 0, sizeof bulk);
	sort_file_ctx = f;
	sort_key_ctx = 0;
	qsort(s->recs, s->n, sizeof(cob_irec *), ord_cmp);
	invalidate(s);
	s->modified = 0;
}

/* what the other connectors appended since this one last looked */
static void j_catch_up(cob_file *f)
{
	ixstate *s = ixs(f);
	if (!s->journal || !s->sync || s->fd < 0)
		return;
	if (!s->reload && s->map &&
	    __atomic_load_n((cob_u64 *)(void *)(s->map + 24), __ATOMIC_ACQUIRE) == (cob_u64)s->log_end)
		return;
	struct stat st;
	if (!s->reload && (fstat(s->fd, &st) != 0 || st.st_size == s->log_end))
		return;
	lk(s->fd, LK_SETW, F_RDLCK, LK_JOURNAL);
	if (fstat(s->fd, &st) == 0) {
		if (s->reload || st.st_size < s->log_end) {
			/* the file was rewritten (OPEN OUTPUT by another connector of
			   this process): read it all again */
			for (size_t i = 0; i < s->n; i++)
				if (s->recs[i])
					free_rec(s->recs[i]);
			s->n = 0;
			s->last_read = NULL;
			invalidate(s);
			s->reload = 0;
			j_load(f, st.st_size);
		} else if (st.st_size > s->log_end) {
			s->log_end = j_replay(f, s->log_end, st.st_size, apply_entry);
		}
	}
	lk(s->fd, LK_SET, F_UNLCK, LK_JOURNAL);
}

/* ---------------------------------------------------------------- writing it */

/* before a change: the journal to this connector alone, and up to date */
static void j_begin(cob_file *f)
{
	ixstate *s = ixs(f);
	if (!s->journal || !s->sync || s->fd < 0)
		return;
	lk(s->fd, LK_SETW, F_WRLCK, LK_JOURNAL);
	struct stat st;
	if (s->reload || (fstat(s->fd, &st) == 0 && st.st_size != s->log_end)) {
		lk(s->fd, LK_SET, F_UNLCK, LK_JOURNAL);
		j_catch_up(f);
		lk(s->fd, LK_SETW, F_WRLCK, LK_JOURNAL);
		/* nobody can append between the two locks but this process, which
		   isn't doing so: the catch-up stands */
		if (fstat(s->fd, &st) == 0 && st.st_size > s->log_end)
			s->log_end = j_replay(f, s->log_end, st.st_size, apply_entry);
	}
}

static void j_end(cob_file *f)
{
	ixstate *s = ixs(f);
	if (!s->journal || !s->sync || s->fd < 0)
		return;
	lk(s->fd, LK_SET, F_UNLCK, LK_JOURNAL);
}

/* a change: appended to the journal, then applied in memory; -1 when the
 * file can't be written */
static int j_change(cob_file *f, int op, cob_u64 slot, const unsigned char *data, size_t len, const cob_u64 *kseq)
{
	ixstate *s = ixs(f);
	int nk = j_nkeys(f);
	if (s->journal && s->fd >= 0) {
		size_t sz = j_entry_size(nk, len);
		unsigned char stack[4096];
		unsigned char *b = sz <= sizeof stack ? stack : cob_malloc(sz);
		j_encode(b, op, slot, data, len, kseq, nk);
		ssize_t w = pwrite(s->fd, b, sz, s->log_end);
		if (b != stack)
			free(b);
		if (w != (ssize_t)sz) {
			if (w > 0 && ftruncate(s->fd, s->log_end) != 0) {
				/* the torn entry stays; readers stop before it */
			}
			return -1;
		}
		if (sync_wanted())
			fdatasync(s->fd);
		s->log_end += (off_t)sz;
		if (s->map && s->writable)
			__atomic_store_n((cob_u64 *)(void *)(s->map + 24), (cob_u64)s->log_end, __ATOMIC_RELEASE);
	}
	apply_entry(f, op, slot, data, len, kseq, nk);
	return 0;
}

/* a fresh journal of the live records, in key or record-number order: to
 * the open descriptor (fd >= 0), else to a new file renamed over `path` */
static int j_write_all(cob_file *f, int fd, const char *path)
{
	ixstate *s = ixs(f);
	char tmp[1100];
	int own = fd < 0;
	if (own) {
		snprintf(tmp, sizeof tmp, "%s.yaccc-%ld", path, (long)getpid());
		fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0666);
		if (fd < 0)
			return -1;
		struct stat st;
		if (stat(path, &st) == 0)
			fchmod(fd, st.st_mode & 07777);
	} else if (ftruncate(fd, 0) != 0)
		return -1;
	int nk = j_nkeys(f);
	size_t cap = 1 << 16, used = 0;
	unsigned char *buf = cob_malloc(cap);
	j_header(f, buf);
	used = J_HDR;
	off_t at = 0;
	int bad = 0;
	size_t live = 0;
	for (size_t i = 0; i < s->n && !bad; i++) {
		cob_irec *r = s->recs[i];
		if (!r)
			continue;
		size_t sz = j_entry_size(nk, r->size);
		if (used + sz > cap) {
			if (pwrite(fd, buf, used, at) != (ssize_t)used)
				bad = 1;
			at += (off_t)used;
			used = 0;
			if (sz > cap) {
				cap = sz;
				buf = realloc(buf, cap);
				if (!buf)
					cob_fatal("out of memory");
			}
		}
		j_encode(buf + used, 'W', f->organization == COB_ORG_RELATIVE ? (cob_u64)i + 1 : 0,
			 r->data, r->size, r->kseq, nk);
		used += sz;
		live += sz;
	}
	if (!bad && used && pwrite(fd, buf, used, at) != (ssize_t)used)
		bad = 1;
	at += (off_t)used;
	free(buf);
	if (!bad && sync_wanted())
		fdatasync(fd);
	if (own) {
		if (close(fd) != 0)
			bad = 1;
		if (bad || rename(tmp, path) != 0) {
			unlink(tmp);
			return -1;
		}
	} else if (!bad) {
		s->log_end = at;
	}
	if (!bad)
		s->live_bytes = live;
	return bad ? -1 : 0;
}

/* does this connector have the file to itself (no other process, no other
 * connector of this one)? */
static int alone_with(cob_file *f)
{
	holder *h = f->holder;
	if (!h)
		return 1;
	if (same_file_open(f))
		return 0;
	if (h->readers == F_WRLCK)
		return 1;
	/* ask for it: no other process holds the file */
	if (lk(h->fd, LK_SET, F_WRLCK, LK_READERS) == 0) {
		h->readers = F_WRLCK;
		return 1;
	}
	return 0;
}

/* ---------------------------------------------------------------- record locks */

static cob_u64 rec_lock_id(cob_file *f, const unsigned char *rec, cob_s64 slot)
{
	if (f->organization == COB_ORG_RELATIVE)
		return (cob_u64)slot % LK_RECSPAN;
	unsigned char key[COB_KEY_MAX_SEGS * 512];
	size_t n = gather_key(f, 0, rec, key);
	cob_u64 h = 1469598103934665603ULL;     /* FNV-1a */
	for (size_t i = 0; i < n; i++) {
		h ^= key[i];
		h *= 1099511628211ULL;
	}
	return h % LK_RECSPAN;
}

static int rec_held(ixstate *s, cob_u64 id)
{
	for (size_t i = 0; i < s->nheld; i++)
		if (s->held[i] == id)
			return 1;
	return 0;
}

/* lock a record for this connector: 0, or -1 when another holds it */
static int rec_lock(cob_file *f, cob_u64 id)
{
	ixstate *s = ixs(f);
	if (rec_held(s, id))
		return 0;
	if (!s->locker && s->map) {
		/* from now on the others check for this connector's locks */
		__atomic_fetch_add((uint32_t *)(void *)(s->map + 32), 1, __ATOMIC_ACQ_REL);
		s->locker = 1;
	}
	if (lk(s->fd, LK_SET, F_WRLCK, LK_RECORDS + (off_t)id) != 0)
		return errno == EBADF ? 0 : -1;
	if (s->nheld == s->heldcap) {
		s->heldcap = s->heldcap ? s->heldcap * 2 : 8;
		s->held = realloc(s->held, s->heldcap * sizeof(cob_u64));
		if (!s->held)
			cob_fatal("out of memory");
	}
	s->held[s->nheld++] = id;
	return 0;
}

static int rec_locked_elsewhere(cob_file *f, cob_u64 id)
{
	ixstate *s = ixs(f);
	if (s->map) {
		uint32_t n = __atomic_load_n((uint32_t *)(void *)(s->map + 32), __ATOMIC_ACQUIRE);
		if (n <= (uint32_t)s->locker)
			return 0;       /* no other connector locks records */
	}
	return !rec_held(s, id) && lk_busy(s->fd, LK_RECORDS + (off_t)id);
}

static void rec_unlock_all(cob_file *f)
{
	ixstate *s = f->ix;
	if (!s)
		return;
	for (size_t i = 0; i < s->nheld; i++)
		lk(s->fd, LK_SET, F_UNLCK, LK_RECORDS + (off_t)s->held[i]);
	s->nheld = 0;
}

/* record locks are kept only where someone else may share the file, by a
 * connector open for I-O */
static int rec_locking(cob_file *f)
{
	ixstate *s = f->ix;
	return s && s->fd >= 0 && s->sync && s->journal && f->open_mode == COB_OPEN_IO;
}

static void rec_unlock_one(cob_file *f, cob_u64 id)
{
	ixstate *s = ixs(f);
	for (size_t i = 0; i < s->nheld; i++)
		if (s->held[i] == id) {
			lk(s->fd, LK_SET, F_UNLCK, LK_RECORDS + (off_t)id);
			s->held[i] = s->held[--s->nheld];
			return;
		}
}

/* the lock a READ takes on the record it found: 0 nothing more to do (no
 * lock wanted, or held since before the last catch-up), 1 locked just now
 * (*id: which), -1 locked by another connector (status 51) */
static int read_lock_step(cob_file *f, const unsigned char *rec, cob_s64 slot, cob_u64 *id)
{
	if (!rec_locking(f))
		return 0;
	int opt = f->read_lock;
	if (opt == COB_LOCK_NONE)
		return 0;
	*id = rec_lock_id(f, rec, slot);
	int want = opt == COB_LOCK_WITH || opt == COB_LOCK_KEPT ||
		   (opt == COB_LOCK_DEFAULT && f->lock_mode == 2);
	if (!want)
		return rec_locked_elsewhere(f, *id) ? -1 : 0;
	if (rec_held(ixs(f), *id))
		return 0;
	return rec_lock(f, *id) == 0 ? 1 : -1;
}

/* before a READ: in single-record mode the lock of the record read before
 * goes */
static void read_release(cob_file *f)
{
	if (!rec_locking(f))
		return;
	if (f->lock_multiple || f->read_lock == COB_LOCK_KEPT)
		return;
	rec_unlock_all(f);
}

/* REWRITE and DELETE: not of a record another connector holds */
static int update_blocked(cob_file *f, const unsigned char *rec, cob_s64 slot)
{
	if (!rec_locking(f))
		return 0;
	return rec_locked_elsewhere(f, rec_lock_id(f, rec, slot));
}

int cob_unlock(cob_file *f)
{
	if (!f->open_mode)
		return set_st(f, "42");
	rec_unlock_all(f);
	return set_st(f, "00");
}

/* COMMIT and ROLLBACK: every record lock goes (changes are already on disk) */
void cob_unlock_all(void)
{
	for (cob_file *f = open_list; f; f = f->next_open)
		rec_unlock_all(f);
}

/* has the path been renamed over (a fresh journal) since fd was opened? */
static int path_moved(int fd, const char *path)
{
	struct stat a, b;
	if (fstat(fd, &a) != 0 || stat(path, &b) != 0)
		return 0;
	return a.st_dev != b.st_dev || a.st_ino != b.st_ino;
}

/* the other connectors of this process with the file open: they now share
 * it, so they catch up before each statement; reload: OPEN OUTPUT rewrote it */
static void share_with_others(cob_file *f, int reload)
{
	for (cob_file *o = open_list; o; o = o->next_open) {
		if (o == f || !o->holder || o->holder != f->holder || !o->ix)
			continue;
		ixstate *t = o->ix;
		t->sync = 1;
		if (reload)
			t->reload = 1;
	}
}

static int open_ix(cob_file *f, int mode);

int cob_open(cob_file *f, int mode)
{
	f->use_mode = mode;
	if (f->open_mode)
		return set_st(f, "41");
	if (f->locked)
		return set_st(f, "38");
	f->at_end = 0;
	f->last_read_ok = 0;
	f->no_current = 0;
	f->linage_lines = 0;
	f->eop = 0;
	resolve_path(f);
	if (!f->path[0])
		return set_st(f, "31");         /* no file name: the file does not exist */
	f->lockfd = 0;
	f->holder = NULL;
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
	return open_ix(f, mode);
}

/* relative / indexed: the journal opened and read */
static int open_ix(cob_file *f, int mode)
{
	int converted = 0;
again:
	ix_free(f);
	ixstate *s = ixs(f);
	s->key_ref = 0;
	s->pos_mode = 0;
	s->rel_pos = 0;
	s->rel_incl = 0;
	s->writable = mode != COB_OPEN_INPUT;
	const char *st = "00";
	int fd = -1;
	for (int tries = 0;; tries++) {
		int flags = O_CLOEXEC | (mode == COB_OPEN_INPUT ? O_RDONLY : O_RDWR);
		fd = open(f->path, flags);
		if (fd < 0 && errno == ENOENT) {
			if (mode == COB_OPEN_OUTPUT || (f->optional && mode != COB_OPEN_INPUT)) {
				/* OUTPUT, and I-O / EXTEND of a missing OPTIONAL file, create it */
				fd = open(f->path, flags | O_CREAT, 0666);
				if (fd >= 0 && mode != COB_OPEN_OUTPUT)
					st = "05";
			} else if (f->optional) {
				/* INPUT of a missing OPTIONAL file: there are no records */
				f->open_mode = mode;
				link_open(f);
				return set_st(f, "05");
			} else
				return set_st(f, "35");
		}
		if (fd < 0)
			return set_st(f, errno == EACCES ? "37" : "30");
		if (take_file_locks(f, fd, mode) != 0) {
			close(fd);
			return set_st(f, "61");
		}
		/* a CLOSE elsewhere may have renamed a fresh journal over the file
		   between our open and our lock: then it's that file we want */
		if (!path_moved(fd, f->path) || tries >= 8)
			break;
		drop_file_locks(f);
		close(fd);
	}
	s->fd = fd;
	holder *h = f->holder;
	/* catch up before each statement unless no one else can change the file */
	s->sync = !(h && h->readers == F_WRLCK) || same_file_open(f) > 0;
	if (s->sync)
		share_with_others(f, 0);
	unsigned char hdr[J_HDR];
	ssize_t got = mode == COB_OPEN_OUTPUT ? 0 : pread(fd, hdr, J_HDR, 0);
	if (mode == COB_OPEN_OUTPUT || got == 0) {
		/* a new journal: OUTPUT has the file to itself; an empty file gets
		   its header from whoever writes first */
		if (s->writable) {
			if (s->sync)
				lk(fd, LK_SETW, F_WRLCK, LK_JOURNAL);
			struct stat sb;
			if (mode == COB_OPEN_OUTPUT || (fstat(fd, &sb) == 0 && sb.st_size == 0)) {
				unsigned char h0[J_HDR];
				j_header(f, h0);
				if (ftruncate(fd, 0) != 0 || pwrite(fd, h0, J_HDR, 0) != J_HDR) {
					if (s->sync)
						lk(fd, LK_SET, F_UNLCK, LK_JOURNAL);
					drop_file_locks(f);
					close(fd);
					s->fd = -1;
					return set_st(f, "30");
				}
				s->log_end = J_HDR;
			}
			if (s->sync)
				lk(fd, LK_SET, F_UNLCK, LK_JOURNAL);
			if (mode == COB_OPEN_OUTPUT)
				share_with_others(f, 1);
		}
		s->journal = 1;
		if (mode != COB_OPEN_OUTPUT) {
			/* someone may have written the header and more meanwhile */
			struct stat sb;
			if (fstat(fd, &sb) == 0 && sb.st_size >= J_HDR &&
			    pread(fd, hdr, J_HDR, 0) == J_HDR && memcmp(hdr, J_MAGIC, 4) == 0)
				j_load(f, sb.st_size);
		}
	} else if (got == J_HDR && memcmp(hdr, J_MAGIC, 4) == 0) {
		if ((int)get32(hdr + 8) != f->organization) {
			drop_file_locks(f);
			close(fd);
			s->fd = -1;
			return set_st(f, "39");
		}
		s->journal = 1;
		if (s->sync)
			lk(fd, LK_SETW, F_RDLCK, LK_JOURNAL);
		struct stat sb;
		if (fstat(fd, &sb) == 0)
			j_load(f, sb.st_size);
		if (s->sync)
			lk(fd, LK_SET, F_UNLCK, LK_JOURNAL);
	} else {
		/* a file in the format of an earlier version: read as it was */
		int dfd = dup(fd);
		FILE *fp = dfd >= 0 ? fdopen(dfd, "rb") : NULL;
		if (fp) {
			if (f->organization == COB_ORG_INDEXED)
				load_indexed(f, fp);
			else
				load_relative(f, fp);
			fclose(fp);
		}
		/* opened for update by a lone connector: rewritten as a journal
		   (renamed over the file, which is then opened again); otherwise
		   written back at CLOSE, as before */
		if (s->writable && !converted && alone_with(f) && j_write_all(f, -1, f->path) == 0) {
			converted = 1;
			drop_file_locks(f);
			close(fd);
			s->fd = -1;
			goto again;
		}
	}
	if (s->journal && s->sync && s->fd >= 0) {
		void *m = mmap(NULL, J_HDR, PROT_READ | (s->writable ? PROT_WRITE : 0), MAP_SHARED, s->fd, 0);
		if (m != MAP_FAILED) {
			s->map = m;
			if (s->writable)
				__atomic_store_n((cob_u64 *)(void *)(s->map + 24), (cob_u64)s->log_end,
						 __ATOMIC_RELEASE);
		}
	}
	f->open_mode = mode;
	link_open(f);
	return set_st(f, st);
}

static int open_seq(cob_file *f, int mode)
{
	if (f->assign_kind == 1) {
		if (mode != COB_OPEN_INPUT)
			return set_st(f, "37");
		f->fp = stdin;
		f->open_mode = mode;
		link_open(f);
		return set_st(f, "00");
	}
	if (f->assign_kind == 2 || f->assign_kind == 3) {
		if (mode == COB_OPEN_INPUT || mode == COB_OPEN_IO)
			return set_st(f, "37");
		f->fp = stdout;
		f->open_mode = mode;
		link_open(f);
		return set_st(f, "00");
	}
	int flags = O_CLOEXEC | (mode == COB_OPEN_INPUT ? O_RDONLY : mode == COB_OPEN_OUTPUT ? O_WRONLY :
				 mode == COB_OPEN_IO ? O_RDWR : O_WRONLY | O_APPEND);
	const char *fm = mode == COB_OPEN_INPUT ? "rb" : mode == COB_OPEN_OUTPUT ? "wb" :
			 mode == COB_OPEN_IO ? "r+b" : "ab";
	const char *st = "00";
	int fd = open(f->path, flags | (mode == COB_OPEN_OUTPUT ? O_CREAT : 0), 0666);
	if (fd < 0) {
		int e = errno;
		if (e == ENOENT && f->optional) {
			if (mode == COB_OPEN_INPUT) {
				f->fp = NULL;   /* a missing OPTIONAL file: at end at once */
				f->open_mode = mode;
				link_open(f);
				return set_st(f, "05");
			}
			fd = open(f->path, flags | O_CREAT, 0666);
			if (fd >= 0)
				st = "05";
			else
				e = errno;
		}
		if (fd < 0) {
			if (e == EACCES)
				return set_st(f, "37");
			return set_st(f, e == ENOENT && mode != COB_OPEN_OUTPUT ? "35" : "30");
		}
	}
	/* the sharing is settled before OUTPUT empties the file */
	if (take_file_locks(f, fd, mode) != 0) {
		close(fd);
		return set_st(f, "61");
	}
	if (mode == COB_OPEN_OUTPUT) {
		struct stat sb;
		if (fstat(fd, &sb) == 0 && S_ISREG(sb.st_mode) && ftruncate(fd, 0) != 0) {
			drop_file_locks(f);
			close(fd);
			return set_st(f, "30");
		}
	}
	f->fp = fdopen(fd, fm);
	if (!f->fp) {
		drop_file_locks(f);
		close(fd);
		return set_st(f, "30");
	}
	f->open_mode = mode;
	link_open(f);
	return set_st(f, st);
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
		if (s->journal) {
			/* the last connector out writes a journal made mostly of
			   superseded entries afresh */
			struct stat sb;
			if (s->writable && s->fd >= 0 && fstat(s->fd, &sb) == 0 &&
			    (size_t)sb.st_size > 2 * s->live_bytes + J_HDR + 65536 && alone_with(f)) {
				j_catch_up(f);
				j_write_all(f, -1, f->path);
			}
		} else if (f->open_mode != COB_OPEN_INPUT && s->modified) {
			persist(f);     /* an earlier format, shared: written back as before */
		}
		if (s->map) {
			if (s->locker)
				__atomic_fetch_sub((uint32_t *)(void *)(s->map + 32), 1, __ATOMIC_ACQ_REL);
			munmap(s->map, J_HDR);
			s->map = NULL;
		}
		if (s->fd >= 0)
			close(s->fd);   /* the record locks go with it */
		ix_free(f);
	}
	f->open_mode = 0;
	drop_file_locks(f);
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
	/* the top margin is lin_top blank lines; the page break already closed
	 * the last line, so the +1 that used to be here is now one too many */
	lin_advance(f, f->lin_top);
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
			/* AFTER ADVANCING: the record goes on the current line and
			 * the advance follows it. Doing it the other way round put
			 * every record one line lower and left a blank at the top. */
			lin_print(f, rec, n);
			lin_advance(f, lines);
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

/* the record number a READ of a relative file reads: 0 and a status when
 * there is none */
static cob_s64 locate_rel(cob_file *f, int next, const char **st)
{
	ixstate *s = ixs(f);
	cob_s64 slot;
	*st = NULL;
	if (next == 2) {
		/* READ PREVIOUS */
		if (f->at_end) {
			*st = "46";
			return 0;
		}
		slot = s->rel_incl ? s->rel_pos : s->rel_pos - 1;
		if (slot > (cob_s64)s->n)
			slot = (cob_s64)s->n;
		while (slot >= 1 && !s->recs[slot - 1])
			slot--;
		if (slot < 1) {
			f->at_end = 1;
			*st = "10";
			return 0;
		}
		return slot;
	}
	if (next || f->access == COB_ACC_SEQUENTIAL) {
		if (f->at_end) {
			*st = "46";
			return 0;
		}
		slot = s->rel_incl ? s->rel_pos : s->rel_pos + 1;
		if (slot < 1)
			slot = 1;
		while (slot <= (cob_s64)s->n && !s->recs[slot - 1])
			slot++;
		if (slot > (cob_s64)s->n) {
			f->at_end = 1;
			*st = "10";
			return 0;
		}
		if (slot > rel_key_cap(f)) {
			f->at_end = 1;
			*st = "14";
			return 0;
		}
		return slot;
	}
	slot = rel_key(f);
	if (slot < 1 || slot > (cob_s64)s->n || !s->recs[slot - 1]) {
		*st = "23";
		return 0;
	}
	return slot;
}

static int read_rel(cob_file *f, int next)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	read_release(f);
	cob_s64 slot = 0;
	cob_u64 got = 0;
	int have_got = 0;
	for (int pass = 0;; pass++) {
		j_catch_up(f);
		const char *st;
		slot = locate_rel(f, next, &st);
		if (!slot) {
			if (have_got)
				rec_unlock_one(f, got);
			return set_st(f, st);
		}
		cob_u64 id = 0;
		int lr = read_lock_step(f, NULL, slot, &id);
		if (lr < 0) {
			if (have_got)
				rec_unlock_one(f, got);
			/* the position stays, to try again */
			if (f->relative_key && (next || f->access == COB_ACC_SEQUENTIAL))
				cob_set_int(f->relative_key, slot);
			return set_st(f, "51");
		}
		if (have_got && got != (cob_u64)slot % LK_RECSPAN)
			rec_unlock_one(f, got);
		if (lr == 0 || pass >= 8)
			break;
		got = id;
		have_got = 1;
	}
	if (f->relative_key && (next || f->access == COB_ACC_SEQUENTIAL))
		cob_set_int(f->relative_key, slot);
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
	j_begin(f);
	cob_s64 slot;
	const char *st = "00";
	if (f->access == COB_ACC_SEQUENTIAL) {
		slot = (cob_s64)s->n + 1;
		if (slot > rel_key_cap(f))
			st = "24";
		else if (f->relative_key)
			cob_set_int(f->relative_key, slot);
	} else {
		slot = rel_key(f);
		if (slot < 1)
			st = "24";
	}
	if (st[0] == '0' && slot <= (cob_s64)s->n && s->recs[slot - 1])
		st = "22";
	if (st[0] == '0') {
		cob_u64 seq = s->next_seq++;
		if (j_change(f, 'W', (cob_u64)slot, f->record, size, &seq) != 0)
			st = "30";
	}
	j_end(f);
	return set_st(f, st);
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
	j_begin(f);
	const char *st = "00";
	if (slot < 1 || slot > (cob_s64)s->n || !s->recs[slot - 1])
		st = "23";
	else if (update_blocked(f, NULL, slot))
		st = "51";
	else {
		cob_u64 seq = s->recs[slot - 1]->kseq[0];
		if (j_change(f, del ? 'D' : 'R', (cob_u64)slot, f->record, del ? 0 : size, &seq) != 0)
			st = "30";
	}
	j_end(f);
	f->last_read_ok = 0;
	return set_st(f, st);
}

static int start_rel(cob_file *f, int op)
{
	ixstate *s = ixs(f);
	j_catch_up(f);
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
	size_t klen = f->keys[k].size;
	size_t i = lower_bound(f, k, key, klen, 0, 0, 0);
	cob_irec **ord = get_order(f, k);
	if (i < ord_count(f, k)) {
		unsigned char got[COB_KEY_MAX_SEGS * 512];
		gather_key(f, k, ord[i]->data, got);
		if (memcmp(got, key, f->keys[k].total ? f->keys[k].total : klen) == 0)
			return (long)i;
	}
	return -1;
}

static void set_pos(ixstate *s, cob_file *f, cob_irec *r, int k, int mode)
{
	s->key_ref = k;
	s->pos_keylen = gather_key(f, k, r->data, s->pos_key);
	s->pos_seq = r->kseq[k];
	s->pos_mode = mode;
}

/* the record a READ reads: NULL and a status when there is none */
static cob_irec *locate_idx(cob_file *f, int next, int key_index, int *kk, const char **st)
{
	ixstate *s = ixs(f);
	*st = NULL;
	if (next == 2) {
		/* READ PREVIOUS: the record before the position (at it after a START) */
		if (f->at_end) {
			*st = "46";
			return NULL;
		}
		int k = *kk = s->key_ref;
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
			*st = "10";
			return NULL;
		}
		return ord[j - 1];
	}
	if (next || f->access == COB_ACC_SEQUENTIAL) {
		if (f->at_end) {
			*st = "46";
			return NULL;
		}
		int k = *kk = s->key_ref;
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
		if (i >= ord_count(f, k)) {
			f->at_end = 1;
			*st = "10";
			return NULL;
		}
		return ord[i];
	}
	int k = *kk = key_index < 0 ? 0 : key_index;
	unsigned char kbuf[COB_KEY_MAX_SEGS * 512];
	gather_key(f, k, f->record, kbuf);
	long i = find_exact(f, k, kbuf);
	if (i < 0) {
		*st = "23";
		return NULL;
	}
	return get_order(f, k)[i];
}

static int read_idx(cob_file *f, int next, int key_index)
{
	ixstate *s = ixs(f);
	if (f->open_mode != COB_OPEN_INPUT && f->open_mode != COB_OPEN_IO)
		return set_st(f, "47");
	if (f->no_current && next != 0)
		return set_st(f, "46");      /* a sequential READ after a failed START */
	read_release(f);
	cob_irec *r = NULL;
	int k = 0;
	cob_u64 got = 0;
	int have_got = 0;
	/* a record lock taken now: catch up once more and find the record
	   again, so what is read is what the lock protects */
	for (int pass = 0;; pass++) {
		j_catch_up(f);
		const char *st;
		r = locate_idx(f, next, key_index, &k, &st);
		if (!r) {
			if (have_got)
				rec_unlock_one(f, got);
			return set_st(f, st);
		}
		cob_u64 id = 0;
		int lr = read_lock_step(f, r->data, 0, &id);
		if (lr < 0) {
			if (have_got)
				rec_unlock_one(f, got);
			return set_st(f, "51");
		}
		if (have_got && (lr == 1 || got != rec_lock_id(f, r->data, 0)) && got != id)
			rec_unlock_one(f, got);
		if (lr == 0 || pass >= 8)
			break;
		got = id;
		have_got = 1;
	}
	set_pos(s, f, r, k, 1);
	if (!(next == 2 || next || f->access == COB_ACC_SEQUENTIAL))
		f->at_end = 0;
	memcpy(f->record, r->data, f->record_max);
	f->cur_size = r->size;
	if (f->size_field)
		cob_set_int(f->size_field, (cob_s64)r->size);
	s->last_read = r;
	f->last_read_ok = 1;
	f->no_current = 0;
	return set_st(f, "00");
}

static int alt_conflict(cob_file *f, const unsigned char *rec, cob_irec *self)
{
	for (int k = 1; k < f->nkeys; k++) {
		if (f->keys[k].dups)
			continue;
		unsigned char kbuf[COB_KEY_MAX_SEGS * 512];
		gather_key(f, k, rec, kbuf);
		long i = find_exact(f, k, kbuf);
		if (i >= 0) {
			cob_irec **ord = get_order(f, k);
			/* any match other than self? */
			size_t j = (size_t)i;
			unsigned char krec[COB_KEY_MAX_SEGS * 512], kbuf2[COB_KEY_MAX_SEGS * 512];
			gather_key(f, k, rec, krec);
			size_t klen_k = f->keys[k].total ? f->keys[k].total : f->keys[k].size;
			while (j < ord_count(f, k) && (gather_key(f, k, ord[j]->data, kbuf2),
			                    memcmp(kbuf2, krec, klen_k) == 0)) {
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
	unsigned char keybuf[COB_KEY_MAX_SEGS * 512];
	size_t klen = gather_key(f, 0, f->record, keybuf);
	const unsigned char *key = keybuf;
	if (f->access == COB_ACC_SEQUENTIAL && (f->open_mode == COB_OPEN_OUTPUT || f->open_mode == COB_OPEN_EXTEND)) {
		if (s->have_last_written && memcmp(key, s->last_written, klen) <= 0)
			return set_st(f, "21");
	}
	size_t size;
	if (new_rec_size(f, recsize, &size))
		return set_st(f, "44");
	j_begin(f);
	const char *st = "00";
	size_t i = lower_bound(f, 0, key, klen, 0, 0, 0);
	if (i < s->n) {
		unsigned char seen[COB_KEY_MAX_SEGS * 512];
		gather_key(f, 0, s->recs[i]->data, seen);
		if (memcmp(seen, key, klen) == 0)
			st = "22";
	}
	if (st[0] == '0' && alt_conflict(f, f->record, NULL))
		st = "22";
	if (st[0] == '0') {
		cob_u64 kseq[COB_MAX_KEYS];
		cob_u64 seq = s->next_seq++;
		for (int k = 0; k < j_nkeys(f); k++)
			kseq[k] = seq;
		if (j_change(f, 'W', 0, f->record, size, kseq) != 0)
			st = "30";
		else {
			memcpy(s->last_written, key, klen);
			s->have_last_written = 1;
		}
	}
	j_end(f);
	return set_st(f, st);
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
	size_t size = 0;
	if (!del && new_rec_size(f, recsize, &size))
		return set_st(f, "44");
	unsigned char keycopy[COB_KEY_MAX_SEGS * 512];
	memcpy(keycopy, key, klen);     /* last_read may go while catching up */
	key = keycopy;
	j_begin(f);
	const char *st = "00";
	i = find_exact(f, 0, key);
	cob_irec *r = i >= 0 ? s->recs[i] : NULL;
	if (!r)
		st = "23";
	else if (update_blocked(f, r->data, 0))
		st = "51";
	else if (del) {
		if (j_change(f, 'D', 0, r->data, r->size, r->kseq) != 0)
			st = "30";
	} else if (alt_conflict(f, f->record, r)) {
		st = "22";
	} else {
		/* an alternate key that changes goes after its duplicates */
		cob_u64 kseq[COB_MAX_KEYS];
		int nk = j_nkeys(f);
		for (int k = 0; k < nk; k++)
			kseq[k] = r->kseq[k];
		for (int k = 1; k < f->nkeys; k++) {
			unsigned char ka[COB_KEY_MAX_SEGS * 512], kb[COB_KEY_MAX_SEGS * 512];
			size_t klen2 = gather_key(f, k, r->data, ka);
			gather_key(f, k, f->record, kb);
			if (memcmp(ka, kb, klen2) != 0)
				kseq[k] = s->next_seq++;
		}
		if (j_change(f, 'R', 0, f->record, size, kseq) != 0)
			st = "30";
	}
	j_end(f);
	f->last_read_ok = 0;
	return set_st(f, st);
}

static int start_idx(cob_file *f, int op, int k, size_t keylen)
{
	ixstate *s = ixs(f);
	j_catch_up(f);
	if (k < 0)
		k = 0;
	size_t kfull = f->keys[k].total ? f->keys[k].total : f->keys[k].size;
	if (keylen == 0 || keylen > kfull)
		keylen = kfull;
	unsigned char keybuf[COB_KEY_MAX_SEGS * 512];
	gather_key(f, k, f->record, keybuf);
	const unsigned char *key = keybuf;
	cob_irec **ord = get_order(f, k);
	size_t i;
	size_t cnt = ord_count(f, k);      /* sparse keys index fewer records */
	switch (op) {
	case 5: /* FIRST */
	case 6: /* LAST */
		if (cnt == 0)
			return set_st(f, "23");
		i = op == 5 ? 0 : cnt - 1;
		break;
	case 0: /* EQ */
		i = lower_bound(f, k, key, keylen, 0, 0, 0);
		unsigned char got[COB_KEY_MAX_SEGS * 512];
		gather_key(f, k, i < cnt ? ord[i]->data : key, got);
		if (i >= cnt || memcmp(got, key, keylen) != 0)
			return set_st(f, "23");
		break;
	case 1: /* GT */
		i = lower_bound(f, k, key, keylen, 0, 0, 1);
		if (i >= cnt)
			return set_st(f, "23");
		break;
	case 2: /* GE */
		i = lower_bound(f, k, key, keylen, 0, 0, 0);
		if (i >= cnt)
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
	s->pos_keylen = gather_key(f, k, ord[i]->data, s->pos_key);
	s->pos_seq = ord[i]->kseq[k];
	s->pos_mode = 3;
	f->at_end = 0;
	return set_st(f, "00");
}

/* ================================================================ dispatch */

int cob_read_lock(cob_file *f, int next, int key_index, int lock)
{
	f->read_lock = lock;
	int rc = cob_read(f, next, key_index);
	f->read_lock = COB_LOCK_DEFAULT;
	return rc;
}

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
	int rc;
	switch (f->organization) {
	case COB_ORG_RELATIVE:
		rc = start_rel(f, op);
		break;
	case COB_ORG_INDEXED:
		rc = start_idx(f, op, key_index, keylen);
		break;
	default:
		return set_st(f, "30");
	}
	/* a START that found nothing leaves no current record: the READ that
	   follows reports 46, not end of file */
	f->no_current = rc != COB_IO_OK;
	return rc;
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
