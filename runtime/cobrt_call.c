/* SPDX-License-Identifier: MIT */
/* cobrt_call.c - CALL by name.
 *
 * A name is looked up in this order:
 *   1. the COBOL programs of the run unit: those compiled into the executable
 *      and those of every object or module loaded so far, each of which
 *      registers its programs when it is loaded;
 *   2. a C function linked into the executable or a library it uses;
 *   3. a loadable module NAME.so (as written, then in lower and upper case)
 *      in each directory of COB_LIBRARY_PATH, then in the current directory.
 *      Loading it registers its COBOL programs; failing that, a C function of
 *      that name in it is used.
 * A C function is called with the C calling convention: an address for each
 * argument passed BY REFERENCE or BY CONTENT, the value itself for one passed
 * BY VALUE. Its int (or pointer) result is the call's RETURN-CODE (or the
 * RETURNING item). */
#include "cobrt.h"
#include <ctype.h>
#include <dlfcn.h>
#include <stdint.h>
#include <strings.h>
#include <unistd.h>

#define MAX_PROGS 1024
#define MAX_C_ARGS 64

typedef struct {
	const char *name;
	cob_prog_fn fn;             /* a COBOL program: (argc, argv) */
	cob_cancel_fn cancel;
	void *cfn;                  /* a C function */
	void *cw;                   /* the program's C-convention entry, for pointers */
} callee_entry;

static callee_entry progs[MAX_PROGS];
static int nprogs;

/* per argument of the CALL about to be made, for a C callee: 0 to pass the
 * address, n to pass an n-byte value (big-endian in the buffer), -n for an
 * unsigned one */
const signed char *cob_call_modes;

/* libcob's name for the number of arguments a C caller passes; -1: all */
int cob_call_params = -1;

/* why the last module that was found could not be loaded */
static char load_error[600];
static char load_path[4400];

#if defined(__APPLE__)
#define MODULE_EXT ".dylib"
#else
#define MODULE_EXT ".so"
#endif

void cob_register_program(const char *name, cob_prog_fn fn, cob_cancel_fn cancel)
{
	cob_register_entry(name, fn, cancel, NULL);
}

void cob_register_entry(const char *name, cob_prog_fn fn, cob_cancel_fn cancel, void *cw)
{
	for (int i = 0; i < nprogs; i++) {
		/* the first program or entry point with a name owns it: GnuCOBOL's
		 * loader keeps the earlier definition when two loaded modules define
		 * the same ENTRY name (COB_PRE_LOAD with entry points) */
		if (strcasecmp(progs[i].name, name) == 0) {
			if (!progs[i].fn && progs[i].cfn) {
				/* a C function found first; the COBOL program now loaded wins */
				progs[i].fn = fn;
				progs[i].cancel = cancel;
				progs[i].cfn = NULL;
				progs[i].cw = cw;
			}
			return;
		}
	}
	if (nprogs < MAX_PROGS) {
		progs[nprogs].name = name;
		progs[nprogs].fn = fn;
		progs[nprogs].cancel = cancel;
		progs[nprogs].cfn = NULL;
		progs[nprogs].cw = cw;
		nprogs++;
	}
}

static int find_prog(const char *name)
{
	/* the exact name first: literal PROGRAM-IDs are case-sensitive */
	for (int i = 0; i < nprogs; i++)
		if (strcmp(progs[i].name, name) == 0)
			return i;
	for (int i = 0; i < nprogs; i++)
		if (strcasecmp(progs[i].name, name) == 0)
			return i;
	return -1;
}

static void remember_c(const char *name, void *cfn)
{
	if (nprogs < MAX_PROGS) {
		size_t n = strlen(name);
		char *copy = cob_malloc(n + 1);
		memcpy(copy, name, n + 1);
		progs[nprogs].name = copy;
		progs[nprogs].fn = NULL;
		progs[nprogs].cancel = NULL;
		progs[nprogs].cfn = cfn;
		progs[nprogs].cw = NULL;
		nprogs++;
	}
}

/* The C identifier for a COBOL name, as cobc spells it: '-' becomes "__" and
 * a name that starts with a digit gets a leading '_'. 0 when the name cannot
 * be one. */
int cob_c_name(const char *name, char *out, size_t sz)
{
	size_t o = 0;
	if (!*name)
		return 0;
	if (isdigit((unsigned char)name[0])) {
		if (o + 1 >= sz)
			return 0;
		out[o++] = '_';
	}
	for (const char *p = name; *p; p++) {
		unsigned char c = (unsigned char)*p;
		if (c == '-') {
			if (o + 2 >= sz)
				return 0;
			out[o++] = '_';
			out[o++] = '_';
		} else if (isalnum(c) || c == '_') {
			if (o + 1 >= sz)
				return 0;
			out[o++] = (char)c;
		} else {
			return 0;
		}
	}
	out[o] = 0;
	return 1;
}

static void *c_symbol(void *handle, const char *name)
{
	char c[320];
	if (!cob_c_name(name, c, sizeof c))
		return NULL;
	return dlsym(handle, c);
}

/* the directories a module is looked for in, ':'-separated */
static void search_dirs(char *out, size_t sz)
{
	const char *lp = getenv("COB_LIBRARY_PATH");
	if (lp && *lp)
		snprintf(out, sz, "%s:.", lp);
	else
		snprintf(out, sz, ".");
}

static void *load_module(const char *name)
{
	char dirs[4000];
	char variants[3][256];
	int nv = 0;
	size_t n = strlen(name);
	if (n == 0 || n > 200 || strchr(name, '/'))
		return NULL;
	snprintf(variants[nv++], sizeof variants[0], "%s", name);
	for (int k = 0; k < 2; k++) {
		char v[256];
		for (size_t i = 0; i <= n; i++)
			v[i] = (char)(k ? toupper((unsigned char)name[i]) : tolower((unsigned char)name[i]));
		int dup = 0;
		for (int j = 0; j < nv; j++)
			dup |= strcmp(variants[j], v) == 0;
		if (!dup)
			memcpy(variants[nv++], v, n + 1);
	}
	search_dirs(dirs, sizeof dirs);
	for (char *d = dirs; d && *d;) {
		char *next = strchr(d, ':');
		if (next)
			*next++ = 0;
		const char *dir = *d ? d : ".";
		for (int j = 0; j < nv; j++) {
			char path[4400];
			if ((size_t)snprintf(path, sizeof path, "%s/%s%s", dir, variants[j], MODULE_EXT) >= sizeof path)
				continue;
			if (access(path, F_OK) != 0)
				continue;
			void *h = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
			if (h)
				return h;
			const char *why = dlerror();
			snprintf(load_path, sizeof load_path, "%s", path);
			snprintf(load_error, sizeof load_error, "%s", why ? why : "unknown error");
		}
		d = next;
	}
	return NULL;
}

static void preload(void)
{
	/* COB_PRE_LOAD: modules to load at start-up, ':'-separated; a module
	 * may hold several programs or entry points that are called by name */
	const char *pl = getenv("COB_PRE_LOAD");
	if (!pl || !*pl)
		return;
	char list[4096];
	snprintf(list, sizeof list, "%s", pl);
	for (char *m = strtok(list, ":"); m; m = strtok(NULL, ":"))
		if (*m && !load_module(m))
			cob_warning("COB_PRE_LOAD: module '%s' not found", m);
}

cob_callee cob_lookup_name(const char *name, void *weak)
{
	cob_callee ce = { NULL, NULL };
	int k = find_prog(name);
	if (k >= 0) {
		ce.fn = progs[k].fn;
		ce.cfn = progs[k].cfn;
		return ce;
	}
	void *p = weak ? weak : c_symbol(RTLD_DEFAULT, name);
	if (p) {
		remember_c(name, p);
		ce.cfn = p;
		return ce;
	}
	void *h = load_module(name);
	if (h) {
		k = find_prog(name);
		if (k >= 0) {
			ce.fn = progs[k].fn;
			ce.cfn = progs[k].cfn;
			return ce;
		}
		p = c_symbol(h, name);
		if (p) {
			remember_c(name, p);
			ce.cfn = p;
			return ce;
		}
		snprintf(load_error, sizeof load_error,
		         "it was loaded, but has no program or C function named '%s'", name);
	}
	return ce;
}

static void field_name(const cob_field *f, char *nm, size_t sz)
{
	size_t n = f->size < sz - 1 ? f->size : sz - 1;
	memcpy(nm, f->data, n);
	while (n && (nm[n - 1] == ' ' || nm[n - 1] == 0))
		n--;
	size_t s = 0;
	while (s < n && nm[s] == ' ')
		s++;
	nm[n] = 0;
	if (s)
		memmove(nm, nm + s, n - s + 1);
}

cob_callee cob_lookup(const cob_field *name)
{
	char nm[256];
	field_name(name, nm, sizeof nm);
	return cob_lookup_name(nm, NULL);
}

/* SET program-pointer TO ENTRY: the address C code (and CALL of the
 * pointer) calls -- a program's C-convention entry, or a C function */
void *cob_entry_address(const char *name, void *weak)
{
	int k = find_prog(name);
	if (k < 0) {
		cob_lookup_name(name, weak);
		k = find_prog(name);
	}
	if (k < 0)
		return NULL;
	return progs[k].cw ? progs[k].cw : progs[k].cfn;
}

/* the COBOL program of a name */
cob_prog_fn cob_resolve_name(const char *name)
{
	return cob_lookup_name(name, NULL).fn;
}

cob_prog_fn cob_resolve(const cob_field *name)
{
	return cob_lookup(name).fn;
}

void cob_cancel_name(const char *name)
{
	int k = find_prog(name);
	if (k >= 0 && progs[k].cancel)
		progs[k].cancel();
}

void cob_cancel(const cob_field *name)
{
	char nm[256];
	field_name(name, nm, sizeof nm);
	cob_cancel_name(nm);
}

void cob_call_not_found(const char *where, const char *name)
{
	char dirs[4096];
	search_dirs(dirs, sizeof dirs);
	if (load_error[0] && load_path[0])
		cob_fatal_note("%s could not be loaded: %s", load_path, load_error);
	else
		cob_fatal_note("no COBOL program, C function or module %s%s of that name "
		               "(modules are looked for in %s)", name, MODULE_EXT, dirs);
	if (where)
		cob_fatal("%s: module '%s' not found", where, name);
	cob_fatal("module '%s' not found", name);
}

void cob_call_not_found_field(const char *where, const cob_field *name)
{
	char nm[256];
	field_name(name, nm, sizeof nm);
	cob_call_not_found(where, nm);
}

/* Call a C function with the arguments of a COBOL CALL. Every argument goes
 * in an integer register or stack slot, so passing more of them than the
 * function takes is harmless on the System V and AAPCS64 conventions. */
cob_s64 cob_call_c(void *fn, int n, unsigned char **av)
{
	intptr_t a[MAX_C_ARGS] = { 0 };
	if (n > MAX_C_ARGS)
		cob_fatal("CALL of a C function with %d arguments: at most %d are supported", n, MAX_C_ARGS);
	for (int i = 0; i < n; i++) {
		int mode = cob_call_modes ? cob_call_modes[i] : 0;
		if (mode == 0 || !av[i]) {
			a[i] = (intptr_t)av[i];
			continue;
		}
		int w = mode < 0 ? -mode : mode;
		uint64_t v = 0;
		for (int j = 0; j < w; j++)
			v = (v << 8) | av[i][j];
		if (mode > 0 && w < 8 && (av[i][0] & 0x80))
			v |= ~(uint64_t)0 << (8 * w);
		a[i] = (intptr_t)v;
	}
	cob_call_modes = NULL;
	typedef intptr_t (*cfn64)(intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t,
	                          intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t, intptr_t);
	cfn64 f = (cfn64)fn;
	return (cob_s64)f(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
	                  a[8], a[9], a[10], a[11], a[12], a[13], a[14], a[15],
	                  a[16], a[17], a[18], a[19], a[20], a[21], a[22], a[23],
	                  a[24], a[25], a[26], a[27], a[28], a[29], a[30], a[31],
	                  a[32], a[33], a[34], a[35], a[36], a[37], a[38], a[39],
	                  a[40], a[41], a[42], a[43], a[44], a[45], a[46], a[47],
	                  a[48], a[49], a[50], a[51], a[52], a[53], a[54], a[55],
	                  a[56], a[57], a[58], a[59], a[60], a[61], a[62], a[63]);
}

/* A COBOL program called from C: the runtime starts on first use when the
 * main program is not COBOL, and closes the files it left open at exit. */
static void close_at_exit(void)
{
	fflush(stdout);
	cob_close_all_files();
	fflush(stdout);
}

void cob_ensure_init(void)
{
	if (cob_initialized)
		return;
	cob_init(0, NULL);
	atexit(close_at_exit);
}

/* the number of arguments a C caller passed to an exported entry point */
int cob_c_argc(int declared)
{
	int n = cob_call_params;
	cob_call_params = -1;
	return n >= 0 && n < declared ? n : declared;
}

void cob_call_init(void)
{
	preload();
}

/* C API: call a program by name, as CALL "name" USING BY REFERENCE does */
int cob_call(const char *name, int argc, void **argv)
{
	cob_ensure_init();
	cob_callee ce = cob_lookup_name(name, NULL);
	if (!ce.fn && !ce.cfn)
		cob_call_not_found(NULL, name);
	cob_call_sizes = NULL;
	cob_call_arg_omitted = NULL;
	cob_call_modes = NULL;
	if (ce.fn)
		return ce.fn(argc, (unsigned char **)argv);
	return (int)cob_call_c(ce.cfn, argc, (unsigned char **)argv);
}

/* C API: close the files and flush the output, without ending the process */
int cob_tidy(void)
{
	close_at_exit();
	return 0;
}
