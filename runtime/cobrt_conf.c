/* SPDX-License-Identifier: MIT */
/* cobrt_conf.c - runtime configuration files, as GnuCOBOL's runtime.cfg
 *
 * COB_RUNTIME_CONFIG names a file of settings read when the run unit starts
 * (or, without it, COB_CONFIG_DIR/runtime.cfg when COB_CONFIG_DIR is set and
 * the file is there). Each line is one of
 *
 *     TAG VALUE          a setting: TAG is the environment variable's name,
 *                        with or without COB_, in either case (ls_fixed,
 *                        COB_LS_FIXED)
 *     setenv NAME VALUE  an environment variable (NAME=VALUE too)
 *     unsetenv NAME
 *     reset TAG          a setting made earlier in the files undone
 *     include "FILE"     another file's settings (includeif: if it exists)
 *
 * with '#' starting a comment, VALUE optionally in quotes, and ${NAME},
 * ${NAME:-default} and ${NAME:default} in a VALUE replaced by the variable's
 * value. A setting is an environment variable the runtime reads, and one
 * already in the environment wins over the file, as with GnuCOBOL. The tags
 * are GnuCOBOL's (so a file shared with it works; those YACCC has no use for
 * are accepted) and YACCC's own; an unknown tag or a file that isn't there
 * is a configuration error that ends the run unit before it starts, a bad
 * value for a tag a message after which the setting is ignored -- the
 * behaviour and messages measured against cobc 3.1.2.
 */
#include "cobrt.h"
#include <ctype.h>
#include <strings.h>

typedef struct {
	const char *tag;
	const char *env;        /* the environment variable it sets */
	char kind;              /* 'b' boolean, 'v' varseq format, 's' anything */
} cfg_tag;

static const cfg_tag tags[] = {
	/* GnuCOBOL 3.1.2's (cobcrun --runtime-conf) */
	{ "load_case", "COB_LOAD_CASE", 's' },
	{ "physical_cancel", "COB_PHYSICAL_CANCEL", 'b' },
	{ "pre_load", "COB_PRE_LOAD", 's' },
	{ "stacktrace", "COB_STACKTRACE", 'b' },
	{ "library_path", "COB_LIBRARY_PATH", 's' },
	{ "file_path", "COB_FILE_PATH", 's' },
	{ "varseq_format", "COB_VARSEQ_FORMAT", 'v' },
	{ "ls_fixed", "COB_LS_FIXED", 'b' },
	{ "ls_nulls", "COB_LS_NULLS", 'b' },
	{ "sort_chunk", "COB_SORT_CHUNK", 's' },
	{ "sort_memory", "COB_SORT_MEMORY", 's' },
	{ "sync", "COB_SYNC", 'b' },
	{ "db_home", "DB_HOME", 's' },
	{ "bell", "COB_BELL", 's' },
	{ "redirect_display", "COB_REDIRECT_DISPLAY", 'b' },
	{ "screen_esc", "COB_SCREEN_ESC", 'b' },
	{ "screen_exceptions", "COB_SCREEN_EXCEPTIONS", 'b' },
	{ "timeout_scale", "COB_TIMEOUT_SCALE", 's' },
	{ "insert_mode", "COB_INSERT_MODE", 'b' },
	{ "mouse_flags", "COB_MOUSE_FLAGS", 's' },
	{ "mouse_interval", "COB_MOUSE_INTERVAL", 's' },
	{ "display_print_pipe", "COB_DISPLAY_PRINT_PIPE", 's' },
	{ "display_print_file", "COB_DISPLAY_PRINT_FILE", 's' },
	{ "display_punch_file", "COB_DISPLAY_PUNCH_FILE", 's' },
	{ "legacy", "COB_LEGACY", 'b' },
	{ "exit_wait", "COB_EXIT_WAIT", 'b' },
	{ "exit_msg", "COB_EXIT_MSG", 's' },
	{ "disable_warnings", "COB_DISABLE_WARNINGS", 'b' },
	{ "env_mangle", "COB_ENV_MANGLE", 'b' },
	{ "col_just_lrc", "COB_COL_JUST_LRC", 'b' },
	{ "set_debug", "COB_SET_DEBUG", 'b' },
	{ "set_trace", "COB_SET_TRACE", 'b' },
	{ "trace_file", "COB_TRACE_FILE", 's' },
	{ "trace_format", "COB_TRACE_FORMAT", 's' },
	{ "dump_file", "COB_DUMP_FILE", 's' },
	{ "dump_width", "COB_DUMP_WIDTH", 's' },
	{ "current_date", "COB_CURRENT_DATE", 's' },
	/* YACCC's own */
	{ "ls_split", "COB_LS_SPLIT", 'b' },
	{ "sql_database", "COB_SQL_DATABASE", 's' },
	{ "sql_user", "COB_SQL_USER", 's' },
	{ "sql_password", "COB_SQL_PASSWORD", 's' },
	{ "sql_trace", "COB_SQL_TRACE", 'b' },
	{ "sql_savepoint", "COB_SQL_SAVEPOINT", 'b' },
	{ "sqlite_library", "COB_SQLITE_LIBRARY", 's' },
	{ "pq_library", "COB_PQ_LIBRARY", 's' },
	{ NULL, NULL, 0 }
};

#define MAX_DEPTH 16
#define MAX_SET 64

static const char *include_stack[MAX_DEPTH];
static int include_lines[MAX_DEPTH];
static int depth;
static const char *set_by_file[MAX_SET];     /* the variables the files set */
static int n_set;
static int unknown_tag;

static void error_head(void)
{
	static int said;
	if (!said) {
		fputs("configuration error:\n", stderr);
		said = 1;
	}
}

/* where an include came from, innermost first, after an error: from the
 * file being read (a file that can't be included) or from the one that
 * included it (a line of the file) */
static void include_trail(int from)
{
	for (int i = from; i >= 0; i--)
		fprintf(stderr, "%s:%d: configuration file was included here\n",
		        include_stack[i], include_lines[i]);
}

static const cfg_tag *find_tag(const char *name)
{
	const char *t = name;
	if (!strncasecmp(t, "COB_", 4))
		t += 4;
	for (const cfg_tag *c = tags; c->tag; c++)
		if (!strcasecmp(c->tag, t) || !strcasecmp(c->env, name))
			return c;
	return NULL;
}

/* ${NAME}, ${NAME:-default} and ${NAME:default} replaced */
static void expand(const char *in, char *out, size_t sz)
{
	size_t o = 0;
	while (*in && o + 1 < sz) {
		if (in[0] == '$' && in[1] == '{') {
			const char *end = strchr(in + 2, '}');
			if (end) {
				char name[256];
				const char *def = NULL;
				size_t dl = 0;
				size_t nl = (size_t)(end - (in + 2));
				const char *colon = memchr(in + 2, ':', nl);
				if (colon) {
					def = colon + 1;
					if (*def == '-')
						def++;
					dl = (size_t)(end - def);
					nl = (size_t)(colon - (in + 2));
				}
				if (nl >= sizeof name)
					nl = sizeof name - 1;
				memcpy(name, in + 2, nl);
				name[nl] = 0;
				const char *v = getenv(name);
				if (v && *v) {
					while (*v && o + 1 < sz)
						out[o++] = *v++;
				} else if (def) {
					for (size_t i = 0; i < dl && o + 1 < sz; i++)
						out[o++] = def[i];
				}
				in = end + 1;
				continue;
			}
		}
		out[o++] = *in++;
	}
	out[o] = 0;
}

static int bool_value(const char *v)
{
	static const char *const ok[] = { "true", "false", "yes", "no", "on", "off", "1", "0",
	                                  "y", "n", "t", "f", NULL };
	for (int i = 0; ok[i]; i++)
		if (!strcasecmp(v, ok[i]))
			return 1;
	return 0;
}

static int set_by_files(const char *name)
{
	for (int i = 0; i < n_set; i++)
		if (set_by_file[i] && !strcmp(set_by_file[i], name))
			return 1;
	return 0;
}

static void set_var(const char *name, const char *value)
{
	if (getenv(name) && !set_by_files(name))
		return;                 /* the environment wins over the files */
	setenv(name, value, 1);
	if (!set_by_files(name) && n_set < MAX_SET)
		set_by_file[n_set++] = strdup(name);
}

static int read_file(const char *path, int optional);

/* one line: 0, or -1 for an error that stops the run unit */
static int line(const char *file, int ln, char *text)
{
	/* the comment off, and the line's ends */
	int q = 0;
	for (char *p = text; *p; p++) {
		if (*p == '"' || *p == '\'')
			q = q == *p ? 0 : (q ? q : *p);
		else if (*p == '#' && !q) {
			*p = 0;
			break;
		}
	}
	char *s = text;
	while (isspace((unsigned char)*s))
		s++;
	char *e = s + strlen(s);
	while (e > s && isspace((unsigned char)e[-1]))
		*--e = 0;
	if (!*s)
		return 0;
	char *word = s;
	while (*s && !isspace((unsigned char)*s) && *s != '=')
		s++;
	char kw[128];
	size_t kl = (size_t)(s - word) < sizeof kw - 1 ? (size_t)(s - word) : sizeof kw - 1;
	memcpy(kw, word, kl);
	kw[kl] = 0;
	while (isspace((unsigned char)*s))
		s++;
	if (*s == '=') {            /* TAG=VALUE too */
		s++;
		while (isspace((unsigned char)*s))
			s++;
	}
	char *rest = s;
	/* the value: unquoted */
	char val[4096], raw[4096];
	size_t rl = strlen(rest);
	if (rl >= 2 && (rest[0] == '"' || rest[0] == '\'') && rest[rl - 1] == rest[0]) {
		rest[rl - 1] = 0;
		rest++;
	}
	snprintf(raw, sizeof raw, "%s", rest);
	expand(raw, val, sizeof val);
	if (!strcasecmp(kw, "include") || !strcasecmp(kw, "includeif")) {
		if (!*val) {
			error_head();
			fprintf(stderr, "%s:%d: 'include' without a value!\n", file, ln);
			return -1;
		}
		char path[8192];
		size_t vl = strlen(val);
		memcpy(path, val, vl + 1);
		if (val[0] != '/' && strchr(file, '/')) {
			/* beside the file that includes it, when it is there */
			size_t dl = (size_t)(strrchr(file, '/') - file);
			if (dl + 1 + vl + 1 <= sizeof path) {
				char beside[8192];
				memcpy(beside, file, dl);
				beside[dl] = '/';
				memcpy(beside + dl + 1, val, vl + 1);
				FILE *t = fopen(beside, "r");
				if (t) {
					fclose(t);
					memcpy(path, beside, dl + 1 + vl + 1);
				}
			}
		}
		include_lines[depth - 1] = ln;
		return read_file(path, !strcasecmp(kw, "includeif"));
	}
	if (!strcasecmp(kw, "setenv")) {
		char *eq = strchr(val, '=');
		char *name = val, *v;
		if (eq && (eq < val + strcspn(val, " \t"))) {
			*eq = 0;
			v = eq + 1;
		} else {
			v = val + strcspn(val, " \t");
			if (*v) {
				*v++ = 0;
				while (isspace((unsigned char)*v))
					v++;
			}
		}
		size_t vl = strlen(v);
		if (vl >= 2 && (v[0] == '"' || v[0] == '\'') && v[vl - 1] == v[0]) {
			v[vl - 1] = 0;
			v++;
		}
		if (!*name || !*v) {
			fprintf(stderr, "%s:%d: WARNING - 'setenv %s' without a value - ignored!\n", file, ln, name);
			return 0;
		}
		set_var(name, v);
		return 0;
	}
	if (!strcasecmp(kw, "unsetenv")) {
		unsetenv(val);
		return 0;
	}
	if (!strcasecmp(kw, "reset")) {
		const cfg_tag *c = find_tag(val);
		const char *name = c ? c->env : val;
		for (int i = 0; i < n_set; i++)
			if (set_by_file[i] && !strcmp(set_by_file[i], name)) {
				unsetenv(name);
				set_by_file[i] = NULL;
			}
		return 0;
	}
	const cfg_tag *c = find_tag(kw);
	if (!c) {
		error_head();
		fprintf(stderr, "%s:%d: unknown configuration tag '%s'\n", file, ln, kw);
		include_trail(depth - 2);
		unknown_tag = 1;        /* the rest is read too, then the run unit ends */
		return 0;
	}
	if (!*val) {
		fprintf(stderr, "%s:%d: WARNING - '%s' without a value - ignored!\n", file, ln, kw);
		return 0;
	}
	if (c->kind == 'b' && !bool_value(val)) {
		error_head();
		fprintf(stderr, "%s:%d: invalid value '%s' for configuration tag '%s';\n"
		        "\tshould be one of the following values: true, false\n", file, ln, val, kw);
		return 0;
	}
	if (c->kind == 'v' && !(val[0] >= '0' && val[0] <= '3' && !val[1])) {
		error_head();
		fprintf(stderr, "%s:%d: invalid value '%s' for configuration tag '%s';\n"
		        "\tshould be one of the following values: 0, 1, 2, 3\n", file, ln, val, kw);
		return 0;
	}
	set_var(c->env, val);
	return 0;
}

static int read_file(const char *path, int optional)
{
	for (int i = 0; i < depth; i++)
		if (!strcmp(include_stack[i], path)) {
			error_head();
			fprintf(stderr, "%s: recursive inclusion\n", path);
			include_trail(depth - 1);
			return -1;
		}
	FILE *f = fopen(path, "r");
	if (!f) {
		if (optional)
			return 0;
		error_head();
		fprintf(stderr, "%s: %s\n", path, strerror(errno));
		include_trail(depth - 1);
		return -1;
	}
	if (depth == MAX_DEPTH) {
		fclose(f);
		error_head();
		fprintf(stderr, "%s: recursive inclusion\n", path);
		return -1;
	}
	include_stack[depth] = strdup(path);
	include_lines[depth] = 0;
	depth++;
	char buf[4096];
	int ln = 0, rc = 0;
	while (rc == 0 && fgets(buf, sizeof buf, f)) {
		ln++;
		rc = line(path, ln, buf);
	}
	fclose(f);
	depth--;
	return rc;
}

/* at the run unit's start, before anything reads a setting */
void cob_runtime_config(void)
{
	const char *p = getenv("COB_RUNTIME_CONFIG");
	int rc = 0;
	if (p && *p) {
		rc = read_file(p, 0);
	} else {
		const char *dir = getenv("COB_CONFIG_DIR");
		if (dir && *dir) {
			char path[4096];
			snprintf(path, sizeof path, "%s/runtime.cfg", dir);
			rc = read_file(path, 1);
		}
	}
	if (rc != 0 || unknown_tag) {
		fflush(stderr);
		exit(1);
	}
}
