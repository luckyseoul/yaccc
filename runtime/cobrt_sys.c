/* SPDX-License-Identifier: MIT */
/* cobrt_sys.c - library routines that programs CALL by name, with the Micro
 * Focus (CBL_...) and ACUCOBOL (C$...) conventions GnuCOBOL provides:
 * bitwise operations on bytes, case conversion, justification, directory
 * and file operations, byte-stream files, process control, and the calling
 * information routines C$NARG, C$PARAMSIZE and C$CALLEDBY.
 *
 * Each routine gets its arguments as data items and returns the value that
 * goes into RETURN-CODE.
 */
#define _GNU_SOURCE
#include "cobrt.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>

/* ---------------------------------------------------------------- helpers */

static cob_s64 num_arg(const cob_field *f)
{
	if (cob_is_num_type(f->attr->type))
		return cob_d_to_int(cob_d_get(f));
	/* an alphanumeric item: its digits ("0") or, for one byte, the byte itself */
	cob_s64 v = 0;
	int digits = 0;
	for (size_t i = 0; i < f->size; i++) {
		if (f->data[i] >= '0' && f->data[i] <= '9') {
			v = v * 10 + (f->data[i] - '0');
			digits++;
		} else if (f->data[i] != ' ')
			return f->size == 1 ? f->data[0] : 0;
	}
	return digits ? v : 0;
}

static void set_num(cob_field *f, cob_s64 v)
{
	cob_d_set(f, cob_d_int(v), 0);
}

static size_t clamp_len(cob_s64 n, size_t max)
{
	if (n <= 0)
		return 0;
	return (size_t)n > max ? max : (size_t)n;
}

static void text_of(const cob_field *f, char *buf, size_t sz)
{
	size_t n = f->size < sz - 1 ? f->size : sz - 1;
	memcpy(buf, f->data, n);
	while (n && (buf[n - 1] == ' ' || buf[n - 1] == 0))
		n--;
	buf[n] = 0;
	/* leading spaces too */
	size_t k = 0;
	while (buf[k] == ' ')
		k++;
	if (k)
		memmove(buf, buf + k, n - k + 1);
}

static const char *env_nonempty(const char *prefix, const char *name)
{
	char ev[600];
	snprintf(ev, sizeof ev, "%s%s", prefix, name);
	const char *v = getenv(ev);
	return v && *v ? v : NULL;
}

static const char *env_map(const char *name)
{
	const char *v = env_nonempty("DD_", name);
	if (!v)
		v = env_nonempty("dd_", name);
	if (!v)
		v = env_nonempty("", name);
	return v;
}

/* File names given to the routines are mapped as GnuCOBOL maps them: a simple
   name through DD_name, dd_name or name; the first directory of a path the
   same way; a leading $VAR/ through the same variables, or dropped when none
   is set. */
void cob_map_filename(const char *in, char *out, size_t sz)
{
	char buf[2048];
	snprintf(buf, sizeof buf, "%s", in);
	while (buf[0] == '$') {
		char *slash = strchr(buf, '/');
		char var[512];
		size_t vl = slash ? (size_t)(slash - buf - 1) : strlen(buf) - 1;
		if (vl >= sizeof var)
			break;
		memcpy(var, buf + 1, vl);
		var[vl] = 0;
		const char *v = env_map(var);
		char rest[2048];
		snprintf(rest, sizeof rest, "%s", slash ? slash + 1 : "");
		if (v) {
			snprintf(out, sz, "%s%s%s", v, slash ? "/" : "", rest);
			return;
		}
		snprintf(buf, sizeof buf, "%s", rest);
	}
	char *slash = strchr(buf, '/');
	if (!slash) {
		const char *v = buf[0] ? env_map(buf) : NULL;
		snprintf(out, sz, "%s", v ? v : buf);
		return;
	}
	if (slash != buf) {
		char first[512];
		size_t fl = (size_t)(slash - buf);
		if (fl < sizeof first) {
			memcpy(first, buf, fl);
			first[fl] = 0;
			const char *v = strcmp(first, ".") && strcmp(first, "..") ? env_map(first) : NULL;
			if (v) {
				snprintf(out, sz, "%s%s", v, slash);
				return;
			}
		}
	}
	snprintf(out, sz, "%s", buf);
}

static void file_arg(const cob_field *f, char *out, size_t sz)
{
	char raw[2048];
	text_of(f, raw, sizeof raw);
	cob_map_filename(raw, out, sz);
}

/* ---------------------------------------------------------------- bitwise */

static int bitwise(int n, cob_field **a, int op)
{
	if (n < 3)
		return 0;
	size_t len = clamp_len(num_arg(a[2]), a[0]->size < a[1]->size ? a[0]->size : a[1]->size);
	const unsigned char *s = a[0]->data;
	unsigned char *d = a[1]->data;
	for (size_t i = 0; i < len; i++) {
		switch (op) {
		case 0: d[i] &= s[i]; break;                            /* AND */
		case 1: d[i] |= s[i]; break;                            /* OR */
		case 2: d[i] = (unsigned char)~(s[i] | d[i]); break;    /* NOR */
		case 3: d[i] ^= s[i]; break;                            /* XOR */
		case 4: d[i] = (unsigned char)(~s[i] | d[i]); break;    /* IMP */
		case 5: d[i] = (unsigned char)(s[i] & ~d[i]); break;    /* NIMP */
		case 6: d[i] = (unsigned char)~(s[i] ^ d[i]); break;    /* EQ */
		}
	}
	return 0;
}

int cob_sys_cbl_and(int n, cob_field **a)  { return bitwise(n, a, 0); }
int cob_sys_cbl_or(int n, cob_field **a)   { return bitwise(n, a, 1); }
int cob_sys_cbl_nor(int n, cob_field **a)  { return bitwise(n, a, 2); }
int cob_sys_cbl_xor(int n, cob_field **a)  { return bitwise(n, a, 3); }
int cob_sys_cbl_imp(int n, cob_field **a)  { return bitwise(n, a, 4); }
int cob_sys_cbl_nimp(int n, cob_field **a) { return bitwise(n, a, 5); }
int cob_sys_cbl_eq(int n, cob_field **a)   { return bitwise(n, a, 6); }

int cob_sys_cbl_not(int n, cob_field **a)
{
	if (n < 2)
		return 0;
	size_t len = clamp_len(num_arg(a[1]), a[0]->size);
	for (size_t i = 0; i < len; i++)
		a[0]->data[i] = (unsigned char)~a[0]->data[i];
	return 0;
}

/* ---------------------------------------------------------------- text */

static int convert_case(int n, cob_field **a, int upper)
{
	if (n < 1)
		return 0;
	size_t len = n > 1 ? clamp_len(num_arg(a[1]), a[0]->size) : a[0]->size;
	for (size_t i = 0; i < len; i++)
		a[0]->data[i] = (unsigned char)(upper ? toupper(a[0]->data[i]) : tolower(a[0]->data[i]));
	return 0;
}

int cob_sys_cbl_toupper(int n, cob_field **a) { return convert_case(n, a, 1); }
int cob_sys_cbl_tolower(int n, cob_field **a) { return convert_case(n, a, 0); }
int cob_sys_c_toupper(int n, cob_field **a)   { return convert_case(n, a, 1); }
int cob_sys_c_tolower(int n, cob_field **a)   { return convert_case(n, a, 0); }

/* C$JUSTIFY item ["L" | "C" | "R"]: the text moved to the left, center or
   right (the default) of the item */
int cob_sys_c_justify(int n, cob_field **a)
{
	if (n < 1)
		return 0;
	cob_field *f = a[0];
	unsigned char how = n > 1 && a[1]->size ? (unsigned char)toupper(a[1]->data[0]) : 'R';
	size_t s = 0, e = f->size;
	while (s < e && f->data[s] == ' ')
		s++;
	while (e > s && f->data[e - 1] == ' ')
		e--;
	size_t len = e - s;
	if (len == 0 || len == f->size)
		return 0;
	unsigned char *tmp = cob_malloc(len);
	memcpy(tmp, f->data + s, len);
	size_t at = how == 'L' ? 0 : how == 'C' ? (f->size - len) / 2 : f->size - len;
	memset(f->data, ' ', f->size);
	memcpy(f->data + at, tmp, len);
	free(tmp);
	return 0;
}

/* C$PRINTABLE item [char]: non-printable bytes replaced by char (default ".") */
int cob_sys_c_printable(int n, cob_field **a)
{
	if (n < 1)
		return 0;
	unsigned char rep = n > 1 && a[1]->size ? a[1]->data[0] : '.';
	for (size_t i = 0; i < a[0]->size; i++)
		if (!isprint(a[0]->data[i]))
			a[0]->data[i] = rep;
	return 0;
}

/* CBL_OC_DUMP / CBL_GC_DUMP item: hex and character dump to standard error */
int cob_sys_cbl_oc_dump(int n, cob_field **a)
{
	if (n < 1)
		return 0;
	const cob_field *f = a[0];
	fflush(stdout);
	for (size_t off = 0; off < f->size; off += 16) {
		fprintf(stderr, "<%04zx>", off);
		for (size_t i = off; i < off + 16; i++) {
			if (i < f->size)
				fprintf(stderr, " %02x", f->data[i]);
			else
				fputs("   ", stderr);
		}
		fputs("  ", stderr);
		for (size_t i = off; i < off + 16 && i < f->size; i++)
			fputc(isprint(f->data[i]) ? f->data[i] : '.', stderr);
		fputc('\n', stderr);
	}
	return 0;
}

/* ---------------------------------------------------------------- calling information */

int cob_sys_c_narg(int n, cob_field **a)
{
	if (n >= 1)
		set_num(a[0], cob_frame_nargs());
	return 0;
}

/* C$PARAMSIZE number: RETURN-CODE gets the size of that parameter of the running program */
int cob_sys_c_paramsize(int n, cob_field **a)
{
	if (n < 1)
		return 0;
	return cob_frame_param_size((int)num_arg(a[0]));
}

/* C$CALLEDBY name: the calling program's name; RETURN-CODE 1, or 0 and spaces for the main program */
int cob_sys_c_calledby(int n, cob_field **a)
{
	const char *caller = cob_frame_caller();
	if (n >= 1) {
		memset(a[0]->data, ' ', a[0]->size);
		if (caller) {
			size_t l = strlen(caller);
			memcpy(a[0]->data, caller, l < a[0]->size ? l : a[0]->size);
		}
	}
	return caller ? 1 : 0;
}

/* ---------------------------------------------------------------- process */

int cob_sys_c_getpid(int n, cob_field **a)
{
	(void)n;
	(void)a;
	return (int)getpid();
}

int cob_sys_c_sleep(int n, cob_field **a)
{
	fflush(stdout);
	if (n >= 1) {
		cob_s64 s = num_arg(a[0]);
		if (s > 0)
			sleep((unsigned int)s);
	}
	return 0;
}

int cob_sys_cbl_gc_nanosleep(int n, cob_field **a)
{
	fflush(stdout);
	if (n >= 1) {
		cob_s64 ns = num_arg(a[0]);
		if (ns > 0) {
			struct timespec ts = { (time_t)(ns / 1000000000), (long)(ns % 1000000000) };
			nanosleep(&ts, NULL);
		}
	}
	return 0;
}

int cob_sys_cbl_gc_fork(int n, cob_field **a)
{
	(void)n;
	(void)a;
	fflush(stdout);
	fflush(stderr);
	return (int)fork();
}

int cob_sys_cbl_gc_waitpid(int n, cob_field **a)
{
	if (n < 1)
		return -1;
	fflush(stdout);
	int st;
	if (waitpid((pid_t)num_arg(a[0]), &st, 0) < 0)
		return -1;
	if (WIFEXITED(st))
		return WEXITSTATUS(st);
	if (WIFSIGNALED(st))
		return -WTERMSIG(st);
	return 0;
}

/* ---------------------------------------------------------------- directories */

static int status_128(int ok)
{
	return ok ? 0 : 128;
}

int cob_sys_cbl_create_dir(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 128;
	file_arg(a[0], p, sizeof p);
	return status_128(mkdir(p, 0777) == 0);
}

int cob_sys_cbl_delete_dir(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 128;
	file_arg(a[0], p, sizeof p);
	return status_128(rmdir(p) == 0);
}

int cob_sys_cbl_change_dir(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 128;
	file_arg(a[0], p, sizeof p);
	return status_128(chdir(p) == 0);
}

/* C$MAKEDIR name: 0, or 1 when the directory can't be made */
int cob_sys_c_makedir(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 1;
	file_arg(a[0], p, sizeof p);
	return mkdir(p, 0777) == 0 ? 0 : 1;
}

/* C$CHDIR name status */
int cob_sys_c_chdir(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 1;
	file_arg(a[0], p, sizeof p);
	int rc = chdir(p) == 0 ? 0 : 1;
	if (n > 1)
		set_num(a[1], rc);
	return rc;
}

/* CBL_GET_CURRENT_DIR flags length buffer */
int cob_sys_cbl_get_current_dir(int n, cob_field **a)
{
	char p[4096];
	if (n < 3 || !getcwd(p, sizeof p))
		return 128;
	cob_field *f = a[2];
	size_t len = strlen(p);
	if (len > f->size)
		return 128;
	memset(f->data, ' ', f->size);
	memcpy(f->data, p, len);
	return 0;
}

/* ---------------------------------------------------------------- files */

int cob_sys_cbl_delete_file(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 128;
	file_arg(a[0], p, sizeof p);
	return status_128(unlink(p) == 0);
}

/* C$DELETE name [type]: 0, or 1 when the file can't be deleted */
int cob_sys_c_delete(int n, cob_field **a)
{
	char p[2048];
	if (n < 1)
		return 1;
	file_arg(a[0], p, sizeof p);
	return unlink(p) == 0 ? 0 : 1;
}

int cob_sys_cbl_rename_file(int n, cob_field **a)
{
	char p[2048], q[2048];
	if (n < 2)
		return 128;
	file_arg(a[0], p, sizeof p);
	file_arg(a[1], q, sizeof q);
	return status_128(rename(p, q) == 0);
}

static int copy_file(const char *from, const char *to)
{
	FILE *in = fopen(from, "rb");
	if (!in)
		return 0;
	FILE *out = fopen(to, "wb");
	if (!out) {
		fclose(in);
		return 0;
	}
	char buf[65536];
	size_t k;
	int ok = 1;
	while ((k = fread(buf, 1, sizeof buf, in)) > 0)
		if (fwrite(buf, 1, k, out) != k) {
			ok = 0;
			break;
		}
	fclose(in);
	if (fclose(out) != 0)
		ok = 0;
	return ok;
}

int cob_sys_cbl_copy_file(int n, cob_field **a)
{
	char p[2048], q[2048];
	if (n < 2)
		return 128;
	file_arg(a[0], p, sizeof p);
	file_arg(a[1], q, sizeof q);
	return status_128(copy_file(p, q));
}

/* C$COPY from to [type]: 0, or 1 when the copy fails */
int cob_sys_c_copy(int n, cob_field **a)
{
	char p[2048], q[2048];
	if (n < 2)
		return 1;
	file_arg(a[0], p, sizeof p);
	file_arg(a[1], q, sizeof q);
	return copy_file(p, q) ? 0 : 1;
}

static void put_be(unsigned char *d, unsigned long long v, int n)
{
	for (int i = n - 1; i >= 0; i--) {
		d[i] = (unsigned char)(v & 0xFF);
		v >>= 8;
	}
}

/* CBL_CHECK_FILE_EXIST name info: info gets the size (8 bytes), date (day,
   month, 2-byte year) and time (hour, minute, second, hundredths); 35 if the
   file doesn't exist */
int cob_sys_cbl_check_file_exist(int n, cob_field **a)
{
	char p[2048];
	struct stat st;
	if (n < 2)
		return 128;
	file_arg(a[0], p, sizeof p);
	if (stat(p, &st) != 0)
		return 35;
	if (a[1]->size >= 16) {
		struct tm tm;
		localtime_r(&st.st_mtime, &tm);
		unsigned char *d = a[1]->data;
		put_be(d, (unsigned long long)st.st_size, 8);
		d[8] = (unsigned char)tm.tm_mday;
		d[9] = (unsigned char)(tm.tm_mon + 1);
		put_be(d + 10, (unsigned long long)(tm.tm_year + 1900), 2);
		d[12] = (unsigned char)tm.tm_hour;
		d[13] = (unsigned char)tm.tm_min;
		d[14] = (unsigned char)tm.tm_sec;
		d[15] = 0;
	}
	return 0;
}

/* C$FILEINFO name info: size (8 bytes), date YYYYMMDD and time HHMMSShh (4-byte binaries) */
int cob_sys_c_fileinfo(int n, cob_field **a)
{
	char p[2048];
	struct stat st;
	if (n < 2)
		return 128;
	file_arg(a[0], p, sizeof p);
	if (stat(p, &st) != 0)
		return 35;
	if (a[1]->size >= 16) {
		struct tm tm;
		localtime_r(&st.st_mtime, &tm);
		unsigned char *d = a[1]->data;
		put_be(d, (unsigned long long)st.st_size, 8);
		put_be(d + 8, (unsigned long long)((tm.tm_year + 1900) * 10000 + (tm.tm_mon + 1) * 100 + tm.tm_mday), 4);
		put_be(d + 12, (unsigned long long)(tm.tm_hour * 1000000 + tm.tm_min * 10000 + tm.tm_sec * 100), 4);
	}
	return 0;
}

/* ---------------------------------------------------------------- byte-stream files */

static int handle_fd(const cob_field *f)
{
	int fd = -1;
	if (f->size >= sizeof fd)
		memcpy(&fd, f->data, sizeof fd);
	return fd;
}

/* CBL_OPEN_FILE / CBL_CREATE_FILE name access deny device handle */
static int open_stream(int n, cob_field **a, int create)
{
	char p[2048];
	if (n < 5)
		return -1;
	int access = (int)num_arg(a[1]), deny = (int)num_arg(a[2]), device = (int)num_arg(a[3]);
	int bad = 0;
	if (deny < 0 || deny > 3) {
		cob_warning("call to %s with wrong file_lock: %d", create ? "CBL_CREATE_FILE" : "CBL_OPEN_FILE", deny);
		bad = 1;
	}
	if (device != 0) {
		cob_warning("call to %s with wrong file_dev: %d", create ? "CBL_CREATE_FILE" : "CBL_OPEN_FILE", device);
		bad = 1;
	}
	int flags;
	switch (access & 0x3F) {
	case 1: flags = O_RDONLY; break;
	case 2: flags = O_WRONLY; break;
	case 3: flags = O_RDWR; break;
	default:
		cob_warning("call to CBL_OPEN_FILE with wrong access mode: %d", access);
		return -1;
	}
	if (bad)
		return -1;
	file_arg(a[0], p, sizeof p);
	if (create)
		flags |= O_CREAT | O_TRUNC;
	int fd = open(p, flags, 0666);
	if (fd < 0)
		return errno == ENOENT ? 35 : errno == EACCES || errno == EISDIR ? 37 : 30;
	if (a[4]->size >= sizeof fd)
		memcpy(a[4]->data, &fd, sizeof fd);
	return 0;
}

int cob_sys_cbl_open_file(int n, cob_field **a)   { return open_stream(n, a, 0); }
int cob_sys_cbl_create_file(int n, cob_field **a) { return open_stream(n, a, 1); }

/* CBL_READ_FILE handle offset count flags buffer: 10 at end of file; flags 128
   asks for the file size, returned in offset */
int cob_sys_cbl_read_file(int n, cob_field **a)
{
	if (n < 5)
		return -1;
	int fd = handle_fd(a[0]);
	if (fd < 0)
		return -1;
	if (num_arg(a[3]) & 0x80) {
		struct stat st;
		if (fstat(fd, &st) != 0)
			return -1;
		set_num(a[1], (cob_s64)st.st_size);
	}
	off_t off = (off_t)num_arg(a[1]);
	size_t cnt = clamp_len(num_arg(a[2]), a[4]->size);
	if (cnt == 0)
		return 0;
	ssize_t k = pread(fd, a[4]->data, cnt, off);
	if (k < 0)
		return -1;
	return k == 0 ? 10 : 0;
}

int cob_sys_cbl_write_file(int n, cob_field **a)
{
	if (n < 5)
		return -1;
	int fd = handle_fd(a[0]);
	if (fd < 0)
		return -1;
	off_t off = (off_t)num_arg(a[1]);
	size_t cnt = clamp_len(num_arg(a[2]), a[4]->size);
	if (cnt && pwrite(fd, a[4]->data, cnt, off) != (ssize_t)cnt)
		return 30;
	return 0;
}

int cob_sys_cbl_close_file(int n, cob_field **a)
{
	if (n < 1)
		return -1;
	int fd = handle_fd(a[0]);
	return fd >= 0 && close(fd) == 0 ? 0 : -1;
}

int cob_sys_cbl_flush_file(int n, cob_field **a)
{
	if (n < 1)
		return -1;
	return handle_fd(a[0]) >= 0 ? 0 : -1;
}

/* ================================================================ CBL_GC_GETOPT
 *
 * GNU getopt_long over COBOL data:
 *   SO         PIC X(n)   optstring: "ab:c::"  (":" required, "::" optional arg)
 *   LO         group      array of 38-byte records, no padding:
 *                           name[25], has_value[1], valpoint[8], val[4]
 *   LONGIND    PIC 99     index from 0 of the long option that matched
 *   LONG-ONLY  numeric    a single-dash word is tried as a long option first
 *   RETURN-CHAR PIC X(4)  the option's letter, or '?' when it failed
 *   OPT-VAL    PIC X(10)  the option's argument, blank padded
 *
 * Returns 3 for an option, 2 when its argument did not fit OPT-VAL, 0 for a
 * long option that stores its VAL through VALPOINT, 63 ('?') when the option
 * was not understood, and -1 when none are left. Every value here was measured
 * on GnuCOBOL 3.1.2; the messages are glibc's, which is what it prints.
 */
#define GO_ENTRY 38

static int go_argi = 1;         /* argv index we are looking at */
static int go_ch = 1;           /* offset in the current short-option token */
static int go_done;             /* saw "--" */
static int go_started;

void cob_getopt_reset(void)
{
	go_argi = 1;
	go_ch = 1;
	go_done = 0;
	go_started = 0;
}

static const char *go_prog(void)
{
	const char *p = cob_arg_value(0);
	return p ? p : "";
}

static void go_put(cob_field *f, const char *src, size_t n, int *truncated)
{
	memset(f->data, ' ', f->size);
	size_t k = n < f->size ? n : f->size;
	if (k && src)
		memcpy(f->data, src, k);
	if (n > f->size)
		*truncated = 1;
}

static void go_put_int(cob_field *f, int v)
{
	cob_set_int(f, v);
}

/* name of long option i, without the blank padding; returns its length */
static size_t go_name(const unsigned char *lo, int i, char *out)
{
	const unsigned char *p = lo + (size_t)i * GO_ENTRY;
	size_t n = 25;
	while (n > 0 && p[n - 1] == ' ')
		n--;
	memcpy(out, p, n);
	out[n] = 0;
	return n;
}

int cob_sys_cbl_gc_getopt(int n, cob_field **a)
{
	if (n < 6)
		return 63;
	cob_field *so = a[0], *lo = a[1], *ind = a[2], *ov = a[5], *rch = a[4];
	int long_only = (int)cob_get_int(a[3]);
	int nargs = cob_arg_count();
	if (lo->size == 0 || lo->size % GO_ENTRY != 0)
		cob_fatal("Call to CBL_GC_GETOPT with wrong longoption size");
	int nent = (int)(lo->size / GO_ENTRY);
	if (!go_started) {
		go_argi = 1;
		go_ch = 1;
		go_done = 0;
		go_started = 1;
	}
	char optstr[512];
	size_t osl = so->size < sizeof optstr - 1 ? so->size : sizeof optstr - 1;
	memcpy(optstr, so->data, osl);
	optstr[osl] = 0;
	/* the optstring ends at the first space or NUL */
	for (size_t i = 0; i < osl; i++)
		if (optstr[i] == ' ' || optstr[i] == 0) {
			optstr[i] = 0;
			break;
		}
	if (!optstr[0] && so->size > 0 && so->data[0] == ' ')
		optstr[0] = 0;

	const char *tok = NULL;
	for (;;) {
		if (go_done || go_argi >= nargs)
			return -1;
		tok = cob_arg_value(go_argi);
		if (!tok)
			return -1;
		if (tok[0] != '-' || tok[1] == 0) {
			go_argi++;              /* a plain operand: not an option */
			continue;
		}
		if (tok[1] == '-' && tok[2] == 0) {
			go_done = 1;
			go_argi++;
			return -1;
		}
		if (tok[1] == '-')
			break;                  /* long option */
		/* ---- short option(s) in this token ---- */
		while (tok[go_ch]) {
			char c = tok[go_ch];
			const char *o = strchr(optstr, c);
			if (!o || c == ':') {
				fprintf(stderr, "%s: invalid option -- '%c'\n", go_prog(), c);
				go_ch++;
				if (!tok[go_ch]) {
					go_argi++;
					go_ch = 1;
				}
				go_put(rch, "?", 1, &(int){0});
				return '?';
			}
			int need = o[1] == ':' ? (o[2] == ':' ? 2 : 1) : 0;
			const char *arg = NULL;
			size_t alen = 0;
			int took_next = 0;
			if (need == 1) {
				if (tok[go_ch + 1]) {
					arg = tok + go_ch + 1;
					alen = strlen(arg);
				} else if (go_argi + 1 < nargs) {
					arg = cob_arg_value(go_argi + 1);
					alen = arg ? strlen(arg) : 0;
					took_next = 1;
				} else {
					fprintf(stderr, "%s: option requires an argument -- '%c'\n",
					        go_prog(), c);
					go_argi++;
					go_ch = 1;
					go_put(rch, "?", 1, &(int){0});
					return '?';
				}
			} else if (need == 2) {
				if (tok[go_ch + 1]) {
					arg = tok + go_ch + 1;
					alen = strlen(arg);
				}
			}
			if (took_next || need == 1 || need == 2) {
				go_argi += 1 + took_next;   /* the rest of the token was the argument */
				go_ch = 1;
			} else if (tok[go_ch + 1]) {
				go_ch++;                    /* the next letter of a cluster: -jkl */
			} else {
				go_argi++;
				go_ch = 1;
			}
			go_put(rch, &c, 1, &(int){0});
			int truncated = 0;
			if (arg)
				go_put(ov, arg, alen, &truncated);
			return truncated ? 2 : 3;
		}
		go_argi++;
		go_ch = 1;
	}

	/* ---- long option ---- */
	{
		const char *name = tok + 2;
		const char *eq = strchr(name, '=');
		size_t nlen = eq ? (size_t)(eq - name) : strlen(name);
		int exact = -1, best = -1, nbest = 0;
		char nm[26];
		for (int i = 0; i < nent; i++) {
			size_t l = go_name(lo->data, i, nm);
			if (l == 0)
				continue;               /* an empty slot ends nothing: skip it */
			if (l == nlen && memcmp(nm, name, nlen) == 0) {
				exact = i;
				break;
			}
			if (nlen < l && memcmp(nm, name, nlen) == 0) {
				best = i;
				nbest++;
			}
		}
		int match = exact >= 0 ? exact : (nbest == 1 ? best : -1);
		if (match < 0) {
			if (nbest > 1) {
				fprintf(stderr, "%s: option '--%.*s' is ambiguous; possibilities:",
				        go_prog(), (int)nlen, name);
				for (int i = 0; i < nent; i++) {
					size_t l = go_name(lo->data, i, nm);
					if (l > nlen && memcmp(nm, name, nlen) == 0)
						fprintf(stderr, " '--%s'", nm);
				}
				fputc('\n', stderr);
			} else {
				fprintf(stderr, "%s: unrecognized option '--%.*s'\n",
				        go_prog(), (int)nlen, name);
			}
			go_argi++;
			go_ch = 1;
			go_put(rch, "?", 1, &(int){0});
			return '?';
		}
		const unsigned char *ent = lo->data + (size_t)match * GO_ENTRY;
		int has_value = ent[25] - '0';
		void *valpoint = NULL;
		memcpy(&valpoint, ent + 26, sizeof valpoint);
		const unsigned char *val = ent + 34;
		go_put_int(ind, match);
		if (valpoint) {
			memcpy(valpoint, val, 4);
			go_argi++;
			go_ch = 1;
			return 0;
		}
		go_put(rch, (const char *)val, 4, &(int){0});
		const char *arg = NULL;
		size_t alen = 0;
		if (eq) {
			arg = eq + 1;
			alen = strlen(arg);
		} else if (has_value == 1) {
			if (go_argi + 1 < nargs) {
				arg = cob_arg_value(go_argi + 1);
				alen = arg ? strlen(arg) : 0;
				go_argi++;
			} else {
				fprintf(stderr, "%s: option '--%.*s' requires an argument\n",
				        go_prog(), (int)nlen, name);
				go_argi++;
				go_ch = 1;
				go_put(rch, "?", 1, &(int){0});
				return '?';
			}
		}
		go_argi++;
		go_ch = 1;
		int truncated = 0;
		go_put(ov, arg, arg ? alen : 0, &truncated);
		return truncated ? 2 : 3;
	}
}

/* CBL_ERROR_PROC (index, procedure-address): register a runtime error handler.
 * The first argument selects a slot, but GnuCOBOL's procedures form one chain
 * in which the latest registration runs first whatever the index, which is what
 * its own test depends on. */
/* ---------------------------------------------------------------- memory */

/* CBL_ALLOC_MEM pointer BY VALUE size BY VALUE flags: memory set to zeros,
 * its address in pointer; 0, or 1 when there is none to be had */
int cob_sys_cbl_alloc_mem(int n, cob_field **a)
{
	if (n < 2)
		return -1;
	cob_s64 size = num_arg(a[1]);
	void *p = size > 0 ? calloc(1, (size_t)size) : NULL;
	cob_pointer_set(a[0], p);
	return p ? 0 : 1;
}

/* CBL_FREE_MEM BY VALUE pointer (memory from CBL_ALLOC_MEM or ALLOCATE) */
int cob_sys_cbl_free_mem(int n, cob_field **a)
{
	if (n < 1)
		return -1;
	free(cob_pointer_get(a[0]));
	return 0;
}

/* ---------------------------------------------------------------- bits in a byte */

/* X"F4" byte array: the low bits of eight bytes, the first the highest, as
 * one byte; X"F5" byte array: the other way */
int cob_sys_x_f4(int n, cob_field **a)
{
	if (n < 2 || !a[0]->size)
		return -1;
	unsigned char b = 0;
	for (size_t i = 0; i < 8; i++)
		b = (unsigned char)(b << 1 | (i < a[1]->size ? (a[1]->data[i] & 1) : 0));
	a[0]->data[0] = b;
	return 0;
}

int cob_sys_x_f5(int n, cob_field **a)
{
	if (n < 2 || !a[0]->size)
		return -1;
	unsigned char b = a[0]->data[0];
	for (size_t i = 0; i < 8 && i < a[1]->size; i++)
		a[1]->data[i] = (unsigned char)((b >> (7 - i)) & 1);
	return 0;
}

/* ---------------------------------------------------------------- exit procedures
 *
 * CBL_EXIT_PROC flag params: params is a PROCEDURE-POINTER, then a byte for
 * the priority. Flag 0 installs the procedure (priority 64), 1 removes it, 2
 * puts its priority in the byte, 3 sets the priority from the byte (and
 * installs it). The run unit's end -- STOP RUN, the main program's end, or a
 * runtime error -- calls them, highest priority first and, of the same
 * priority, the last installed first.
 */
#define COB_MAX_EXIT_PROCS 32
static struct { void *fn; int prio; int order; } exit_procs[COB_MAX_EXIT_PROCS];
static int n_exit_procs, exit_order, exits_running;

int cob_sys_cbl_exit_proc(int n, cob_field **a)
{
	if (n < 2 || a[1]->size < sizeof(void *))
		return -1;
	int flag = (int)num_arg(a[0]);
	void *fn = cob_pointer_get(a[1]);
	unsigned char *prio = a[1]->size > sizeof(void *) ? a[1]->data + sizeof(void *) : NULL;
	int i = 0;
	while (i < n_exit_procs && exit_procs[i].fn != fn)
		i++;
	switch (flag) {
	case 1:
		if (i == n_exit_procs)
			return 1;
		exit_procs[i] = exit_procs[--n_exit_procs];
		return 0;
	case 2:
		if (i == n_exit_procs)
			return 1;
		if (prio)
			*prio = (unsigned char)exit_procs[i].prio;
		return 0;
	case 0:
	case 3:
		if (!fn)
			return 1;
		if (i == n_exit_procs) {
			if (n_exit_procs == COB_MAX_EXIT_PROCS)
				return 1;
			exit_procs[n_exit_procs].fn = fn;
			exit_procs[n_exit_procs].prio = 64;
			exit_procs[n_exit_procs].order = ++exit_order;
			n_exit_procs++;
		}
		if (flag == 3 && prio)
			exit_procs[i].prio = *prio;
		return 0;
	}
	return 1;
}

void cob_run_exit_procs(void)
{
	if (exits_running)
		return;
	exits_running = 1;
	while (n_exit_procs > 0) {
		int best = 0;
		for (int i = 1; i < n_exit_procs; i++)
			if (exit_procs[i].prio > exit_procs[best].prio ||
			    (exit_procs[i].prio == exit_procs[best].prio && exit_procs[i].order > exit_procs[best].order))
				best = i;
		void *fn = exit_procs[best].fn;
		exit_procs[best] = exit_procs[--n_exit_procs];
		((int (*)(void))fn)();
	}
}

int cob_sys_cbl_error_proc(int n, cob_field **a)
{
	if (n < 2)
		return -1;
	void *fn = cob_pointer_get(a[1]);
	cob_error_proc_set(fn);
	return 0;
}

/* ================================================================ -ftrace
 *
 * One line per traced point, in the layout GnuCOBOL 3 uses:
 *
 *   Source: 'prog.cob'
 *   Program-Id:  prog
 *   Program-Id:  prog                 Entry: prog                            Line:      4
 *   Program-Id:  prog             Paragraph: MAIN-PARA                       Line:      6
 *   Program-Id:  prog                        MOVE                            Line:      7
 *
 * The Source and Program-Id lines come whenever the program changes. The
 * output goes to standard error, or to the file COB_TRACE_FILE names (a
 * leading '+' appends). COB_TRACE_FORMAT changes the layout of a line: %P is
 * the program (17 wide), %S the kind and name of what is traced (an
 * 11-character label such as "Paragraph: ", then the name, 31 wide), %L the
 * line (6 wide) and %F the source file; trailing spaces are dropped. */
int cob_trace_on;
static FILE *trace_fp;
static const char *trace_src;
static const char *trace_prog;
static int trace_line;

static FILE *trace_out(void)
{
	if (!trace_fp) {
		const char *f = getenv("COB_TRACE_FILE");
		if (f && *f)
			trace_fp = f[0] == '+' ? fopen(f + 1, "a") : fopen(f, "w");
		if (!trace_fp)
			trace_fp = stderr;
	}
	return trace_fp;
}

void cob_trace_point(const char *src, const char *prog, const char *label, const char *name, int line)
{
	FILE *fp = trace_out();
	if (!trace_prog || strcmp(trace_prog, prog) != 0 || strcmp(trace_src, src) != 0) {
		fprintf(fp, "Source: '%s'\n", src);
		fprintf(fp, "Program-Id:  %s\n", prog);
		trace_src = src;
		trace_prog = prog;
	}
	if (line < 0)
		line = trace_line;
	trace_line = line;
	const char *fmt = getenv("COB_TRACE_FORMAT");
	if (!fmt || !*fmt)
		fmt = "Program-Id:  %P%S Line: %L";
	char out[1024];
	size_t o = 0;
	for (const char *p = fmt; *p && o < sizeof out - 200; p++) {
		if (*p != '%' || !p[1]) {
			out[o++] = *p;
			continue;
		}
		p++;
		char lab[24] = "";
		if (label)
			snprintf(lab, sizeof lab, "%s: ", label);
		switch (*p) {
		case 'P':
			o += (size_t)snprintf(out + o, sizeof out - o, "%-17s", prog);
			break;
		case 'S':
			o += (size_t)snprintf(out + o, sizeof out - o, "%11s%-31s", lab, name);
			break;
		case 'L':
			o += (size_t)snprintf(out + o, sizeof out - o, "%6d", line);
			break;
		case 'F':
			o += (size_t)snprintf(out + o, sizeof out - o, "%s", src);
			break;
		case '%':
			out[o++] = '%';
			break;
		default:
			out[o++] = '%';
			out[o++] = *p;
			break;
		}
		if (o > sizeof out - 1)
			o = sizeof out - 1;
	}
	while (o && out[o - 1] == ' ')
		o--;
	out[o] = 0;
	fprintf(fp, "%s\n", out);
	if (fp != stderr)
		fflush(fp);
}

/* ================================================================ CBL_GC_HOSTED
 *
 * CALL "CBL_GC_HOSTED" USING item "name": the C runtime's own variables, for
 * a program that hands them to C functions -- stdin, stdout and stderr (FILE
 * pointers), argc and argv, errno (its address), tzname (its address),
 * timezone and daylight. Returns 1 for a name it does not know. */
int cob_sys_cbl_gc_hosted(int n, cob_field **a)
{
	if (n < 2 || !a[0] || !a[0]->data || a[0] == &cob_fig_null)
		return 0;
	char name[32];
	text_of(a[1], name, sizeof name);
	void *p = NULL;
	cob_s64 v = 0;
	int is_ptr = 1;
	if (strcmp(name, "stdin") == 0)
		p = stdin;
	else if (strcmp(name, "stdout") == 0)
		p = stdout;
	else if (strcmp(name, "stderr") == 0)
		p = stderr;
	else if (strcmp(name, "argv") == 0)
		p = cob_arg_vector();
	else if (strcmp(name, "errno") == 0)
		p = &errno;
	else if (strcmp(name, "tzname") == 0)
		p = tzname;
	else {
		is_ptr = 0;
		if (strcmp(name, "argc") == 0)
			v = cob_arg_count();
		else if (strcmp(name, "cell") == 0)
			v = (cob_s64)sizeof(void *);
		else if (strcmp(name, "timezone") == 0)
			v = (cob_s64)timezone;
		else if (strcmp(name, "daylight") == 0)
			v = daylight;
		else
			return 1;
	}
	if (is_ptr)
		memcpy(a[0]->data, &p, a[0]->size < sizeof p ? a[0]->size : sizeof p);
	else
		cob_set_int(a[0], v);
	return 0;
}
