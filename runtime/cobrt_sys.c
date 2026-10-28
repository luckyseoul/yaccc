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
