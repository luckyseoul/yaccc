/* SPDX-License-Identifier: MIT */
/* cobrt_sql.c - embedded SQL: EXEC SQL ... END-EXEC
 *
 * The compiler turns each EXEC SQL statement into one call here, with the
 * host variables passed as fields: the statement's text has a ? where each
 * input host variable stood, and SELECT ... INTO and FETCH name the host
 * variables that receive a row. Two databases are reached, each through its
 * client library, loaded the first time a program connects to one (a program
 * that uses neither needs neither installed):
 *
 *   SQLite      a file name, or sqlite:name (":memory:" too)
 *   PostgreSQL  postgresql://... or postgres://..., a conninfo string
 *               ("dbname=x host=y"), pg:name, or name@host[:port]
 *
 * As in DB2, statements run in a unit of work that COMMIT or ROLLBACK ends,
 * and a statement that fails leaves the work done before it in place (on
 * PostgreSQL each statement runs under a savepoint, so one error doesn't
 * abort the transaction). The run unit's normal end commits the work and an
 * abnormal end (a runtime error) rolls it back. COMMIT closes the cursors not
 * declared WITH HOLD; ROLLBACK closes them all.
 *
 * SQLCODE and SQLSTATE follow DB2 for the conditions programs test:
 *     100  02000  no row (SELECT INTO, FETCH, an UPDATE or DELETE that
 *                 changed nothing)
 *    -104  42601  syntax error            -204  42704  no such table
 *    -206  42703  no such column          -304  22003  value out of range
 *    -302  22001  a value too long        -305  22002  null, no indicator
 *    -407  23502  null for NOT NULL       -420  22018  not a number
 *    -501  24501  cursor not open         -502  24502  cursor already open
 *    -508  24504  cursor not on a row     -514  26501  no such statement
 *    -530  23503  foreign key             -545  23513  check constraint
 *    -601  42710  already exists          -803  23505  duplicate key
 *    -811  21000  SELECT INTO found more than one row
 *    -911  40001  deadlock or lock timeout
 *   -1024  08003  no database connection
 * Any other error is -1 with the database's SQLSTATE (HY000 from SQLite).
 * COB_SQL_TRACE=Y writes each statement and its SQLCODE to stderr;
 * COB_SQL_DATABASE (with COB_SQL_USER and COB_SQL_PASSWORD) is the database a
 * program that runs SQL without a CONNECT uses.
 */
#include "cobrt.h"
#include <ctype.h>
#include <dlfcn.h>
#include <stdarg.h>

/* ---------------------------------------------------------------- SQLite */
typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
#define SQ_OK 0
#define SQ_ROW 100
#define SQ_DONE 101
#define SQ_OPEN_READWRITE 0x02
#define SQ_OPEN_CREATE 0x04
#define SQ_OPEN_URI 0x40
#define SQ_TRANSIENT ((void (*)(void *))-1)

static struct {
	int (*open_v2)(const char *, sqlite3 **, int, const char *);
	int (*close_v2)(sqlite3 *);
	int (*prepare_v2)(sqlite3 *, const char *, int, sqlite3_stmt **, const char **);
	int (*bind_null)(sqlite3_stmt *, int);
	int (*bind_int64)(sqlite3_stmt *, int, long long);
	int (*bind_double)(sqlite3_stmt *, int, double);
	int (*bind_text)(sqlite3_stmt *, int, const char *, int, void (*)(void *));
	int (*step)(sqlite3_stmt *);
	int (*column_count)(sqlite3_stmt *);
	int (*column_type)(sqlite3_stmt *, int);
	const unsigned char *(*column_text)(sqlite3_stmt *, int);
	int (*column_bytes)(sqlite3_stmt *, int);
	int (*finalize)(sqlite3_stmt *);
	int (*changes)(sqlite3 *);
	const char *(*errmsg)(sqlite3 *);
	int (*extended_errcode)(sqlite3 *);
	int (*busy_timeout)(sqlite3 *, int);
	int (*get_autocommit)(sqlite3 *);
} sq;

/* ------------------------------------------------------------ PostgreSQL */
typedef struct pg_conn PGconn;
typedef struct pg_result PGresult;
#define PG_CONNECTION_OK 0
#define PG_COMMAND_OK 1
#define PG_TUPLES_OK 2
#define PG_DIAG_SQLSTATE 'C'
#define PG_DIAG_MESSAGE_PRIMARY 'M'

static struct {
	PGconn *(*connectdbParams)(const char *const *, const char *const *, int);
	int (*status)(const PGconn *);
	char *(*errorMessage)(const PGconn *);
	void (*finish)(PGconn *);
	void *(*setNoticeProcessor)(PGconn *, void (*)(void *, const char *), void *);
	PGresult *(*execParams)(PGconn *, const char *, int, const unsigned int *, const char *const *,
				const int *, const int *, int);
	PGresult *(*exec)(PGconn *, const char *);
	int (*resultStatus)(const PGresult *);
	int (*ntuples)(const PGresult *);
	int (*nfields)(const PGresult *);
	char *(*getvalue)(const PGresult *, int, int);
	int (*getisnull)(const PGresult *, int, int);
	int (*getlength)(const PGresult *, int, int);
	char *(*cmdTuples)(PGresult *);
	char *(*resultErrorField)(const PGresult *, int);
	void (*clear)(PGresult *);
} pq;

/* load a client library and its functions; 1 when it is there */
static int load_lib(void **h, const char *env, const char *const *names, const char *const *syms, void **fns,
		    int nfns, char *why, size_t whylen)
{
	if (*h)
		return 1;
	const char *forced = getenv(env);
	void *lib = NULL;
	if (forced && *forced)
		lib = dlopen(forced, RTLD_NOW | RTLD_LOCAL);
	for (int i = 0; !lib && names[i]; i++)
		lib = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
	if (!lib) {
		snprintf(why, whylen, "%s not found (set %s to its path)", forced && *forced ? forced : names[0],
			 env);
		return 0;
	}
	for (int i = 0; i < nfns; i++) {
		fns[i] = dlsym(lib, syms[i]);
		if (!fns[i]) {
			snprintf(why, whylen, "%s lacks %s", names[0], syms[i]);
			dlclose(lib);
			return 0;
		}
	}
	*h = lib;
	return 1;
}

static void *sq_lib, *pq_lib;

static int load_sqlite(char *why, size_t n)
{
	static const char *const names[] = { "libsqlite3.so.0", "libsqlite3.so", "libsqlite3.dylib",
					     "libsqlite3.0.dylib", NULL };
	static const char *const syms[] = {
		"sqlite3_open_v2", "sqlite3_close_v2", "sqlite3_prepare_v2", "sqlite3_bind_null",
		"sqlite3_bind_int64", "sqlite3_bind_double", "sqlite3_bind_text", "sqlite3_step",
		"sqlite3_column_count", "sqlite3_column_type", "sqlite3_column_text", "sqlite3_column_bytes",
		"sqlite3_finalize", "sqlite3_changes", "sqlite3_errmsg", "sqlite3_extended_errcode",
		"sqlite3_busy_timeout", "sqlite3_get_autocommit"
	};
	return load_lib(&sq_lib, "COB_SQLITE_LIBRARY", names, syms, (void **)&sq, sizeof sq / sizeof(void *),
			why, n);
}

static int load_pq(char *why, size_t n)
{
	static const char *const names[] = { "libpq.so.5", "libpq.so", "libpq.5.dylib", "libpq.dylib", NULL };
	static const char *const syms[] = {
		"PQconnectdbParams", "PQstatus", "PQerrorMessage", "PQfinish", "PQsetNoticeProcessor",
		"PQexecParams", "PQexec", "PQresultStatus", "PQntuples", "PQnfields", "PQgetvalue",
		"PQgetisnull", "PQgetlength", "PQcmdTuples", "PQresultErrorField", "PQclear"
	};
	return load_lib(&pq_lib, "COB_PQ_LIBRARY", names, syms, (void **)&pq, sizeof pq / sizeof(void *), why,
			n);
}

/* ------------------------------------------------------------- the SQLCA */
static int last_code;
static char last_state[6] = "00000";
static int last_warn;
static const cob_sql_ca *cur_ca;  /* where the statement running reports */
static int cur_rows;               /* SQLERRD(3) */
static int cur_warn1;              /* SQLWARN1: a string was cut short */
static int cur_warn3;              /* SQLWARN3: host variables and columns differ in number */
static int trace = -1;

static void sql_begin(const cob_sql_ca *ca, const char *what)
{
	cur_ca = ca;
	cur_rows = 0;
	cur_warn1 = cur_warn3 = 0;
	if (trace < 0) {
		const char *t = getenv("COB_SQL_TRACE");
		trace = t && (*t == 'Y' || *t == 'y' || *t == '1');
	}
	if (trace)
		fprintf(stderr, "SQL: %s\n", what);
}

static void put_text(cob_field *f, const char *s, size_t n)
{
	cob_move(CF(s, n, &cob_attr_alnum), f);
}

/* the statement's outcome, into the program's SQLCA (or its own SQLCODE and
 * SQLSTATE) and for WHENEVER */
static void sql_done(int code, const char *state, const char *msg)
{
	last_code = code;
	snprintf(last_state, sizeof last_state, "%-5.5s", state);
	last_warn = cur_warn1 || cur_warn3 || (code > 0 && code != 100);
	if (trace)
		fprintf(stderr, "SQL: SQLCODE %d SQLSTATE %s%s%s\n", code, last_state, msg && *msg ? " " : "",
			msg ? msg : "");
	const cob_sql_ca *ca = cur_ca;
	if (!ca)
		return;
	size_t ml = msg ? strlen(msg) : 0;
	while (ml > 0 && (msg[ml - 1] == '\n' || msg[ml - 1] == ' '))
		ml--;
	if (ca->caid)
		put_text(ca->caid, "SQLCA", 5);
	if (ca->cabc)
		cob_set_int(ca->cabc, 136);
	if (ca->code)
		cob_set_int(ca->code, code);
	if (ca->errmc) {
		if (ml > ca->errmc->size)
			ml = ca->errmc->size;
		put_text(ca->errmc, msg ? msg : "", ml);
	}
	if (ca->errml)
		cob_set_int(ca->errml, (cob_s64)ml);
	if (ca->errp)
		put_text(ca->errp, "YACCCSQL", 8);
	if (ca->errd)
		for (int i = 0; i < ca->nerrd; i++) {
			cob_field e = { ca->errd->size, ca->errd->data + (size_t)i * ca->errd->size, ca->errd->attr };
			cob_set_int(&e, i == 2 ? cur_rows : 0);
		}
	if (ca->warn) {
		cob_field *w = ca->warn;
		memset(w->data, ' ', w->size);
		if (w->size > 0 && last_warn)
			w->data[0] = 'W';
		if (w->size > 1 && cur_warn1)
			w->data[1] = 'W';
		if (w->size > 3 && cur_warn3)
			w->data[3] = 'W';
	}
	if (ca->state)
		put_text(ca->state, last_state, 5);
}

static void sql_ok(void)
{
	sql_done(0, "00000", "");
}

/* an error: -1 for return values to propagate */
static int sql_fail(int code, const char *state, const char *fmt, ...)
{
	char msg[512];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(msg, sizeof msg, fmt, ap);
	va_end(ap);
	sql_done(code, state, msg);
	return -1;
}

int cob_sql_code(void)
{
	return last_code;
}

int cob_sql_warn(void)
{
	return last_code >= 0 && last_warn;
}

/* ------------------------------------------------- connections, cursors */
enum { DB_SQLITE = 1, DB_PG };

typedef struct sqlconn {
	char name[64];
	int kind;
	sqlite3 *db;
	PGconn *pg;
	int in_work;                 /* PostgreSQL: BEGIN has been sent */
	struct sqlconn *next;
} sqlconn;

typedef struct sqlcursor {
	char name[96];
	sqlconn *conn;
	sqlite3_stmt *st;            /* SQLite: stepped row by row */
	PGresult *res;               /* PostgreSQL: the rows, read at OPEN */
	int row, nrows;
	int keyed;                   /* the last column is the row's key */
	int hold;
	int done;                    /* SQLite: no more rows (a step now would start over) */
	char *key;                   /* the key of the row last fetched */
	struct sqlcursor *next;
} sqlcursor;

typedef struct sqlprep {
	char name[96];
	char *text;
	struct sqlprep *next;
} sqlprep;

static sqlconn *conns, *current;
static sqlcursor *cursors;
static sqlprep *preps;
static int end_registered;

static void cursor_close(sqlcursor *k)
{
	if (k->st)
		sq.finalize(k->st);
	if (k->res)
		pq.clear(k->res);
	k->st = NULL;
	k->res = NULL;
	free(k->key);
	k->key = NULL;
	k->conn = NULL;
}

static sqlcursor *cursor_find(const char *name, int make)
{
	for (sqlcursor *k = cursors; k; k = k->next)
		if (!strcmp(k->name, name))
			return k;
	if (!make)
		return NULL;
	sqlcursor *k = cob_malloc(sizeof *k);
	memset(k, 0, sizeof *k);
	snprintf(k->name, sizeof k->name, "%s", name);
	k->next = cursors;
	cursors = k;
	return k;
}

/* the cursors of a connection a COMMIT or ROLLBACK ends */
static void close_cursors(sqlconn *c, int all)
{
	for (sqlcursor *k = cursors; k; k = k->next)
		if (k->conn == c && (all || !k->hold))
			cursor_close(k);
}

static void pg_simple(sqlconn *c, const char *sql)
{
	PGresult *r = pq.exec(c->pg, sql);
	if (r)
		pq.clear(r);
}

static void conn_end_work(sqlconn *c, int rollback)
{
	close_cursors(c, rollback);
	if (c->kind == DB_SQLITE) {
		if (!sq.get_autocommit(c->db)) {
			sqlite3_stmt *st;
			if (sq.prepare_v2(c->db, rollback ? "ROLLBACK" : "COMMIT", -1, &st, NULL) == SQ_OK) {
				sq.step(st);
				sq.finalize(st);
			}
		}
	} else if (c->in_work) {
		pg_simple(c, rollback ? "ROLLBACK" : "COMMIT");
		c->in_work = 0;
	}
}

static void conn_close(sqlconn *c, int rollback)
{
	conn_end_work(c, rollback);
	close_cursors(c, 1);
	if (c->kind == DB_SQLITE)
		sq.close_v2(c->db);
	else
		pq.finish(c->pg);
	for (sqlconn **pp = &conns; *pp; pp = &(*pp)->next)
		if (*pp == c) {
			*pp = c->next;
			break;
		}
	if (current == c)
		current = NULL;
	free(c);
}

/* the run unit ends: STOP RUN, or the main program's end, commits its work;
 * any other end -- a runtime error, a crash, exit() from C -- rolls it back */
void cob_sql_end(int abnormal)
{
	while (conns)
		conn_close(conns, abnormal);
}

static void end_at_exit(void)
{
	cob_sql_end(1);
}

static void quiet_notices(void *arg, const char *msg)
{
	(void)arg;
	if (trace > 0)
		fprintf(stderr, "SQL: %s", msg);
}

static int is_pg_target(const char *t)
{
	if (!strncmp(t, "postgresql://", 13) || !strncmp(t, "postgres://", 11) || !strncmp(t, "pg:", 3))
		return 1;
	const char *p = t;
	while (*p == ' ')
		p++;
	const char *k = p;
	while (*p == '_' || (*p >= 'a' && *p <= 'z'))
		p++;
	while (*p == ' ')
		p++;
	if (p > k && *p == '=')
		return 1;                           /* dbname=x host=y: a conninfo string */
	const char *at = strchr(t, '@');
	if (at && !strchr(t, '/') && !strchr(t, '\\') && at > t) {
		for (const char *q = t; q < at; q++)
			if (!isalnum((unsigned char)*q) && *q != '_' && *q != '-')
				return 0;
		return 1;                           /* name@host[:port] */
	}
	return 0;
}

/* trailing spaces off a field's text, NUL-terminated (caller frees) */
static char *field_text(const cob_field *f)
{
	if (!f)
		return NULL;
	size_t n = f->size;
	while (n > 0 && (f->data[n - 1] == ' ' || f->data[n - 1] == 0))
		n--;
	size_t s = 0;
	while (s < n && f->data[s] == ' ')
		s++;
	char *r = cob_malloc(n - s + 1);
	memcpy(r, f->data + s, n - s);
	r[n - s] = 0;
	return r;
}

static sqlconn *connect_to(const char *target, const char *user, const char *pass, const char *name)
{
	char why[256];
	sqlconn *c = cob_malloc(sizeof *c);
	memset(c, 0, sizeof *c);
	snprintf(c->name, sizeof c->name, "%s", name && *name ? name : "DEFAULT");
	if (is_pg_target(target)) {
		if (!load_pq(why, sizeof why)) {
			free(c);
			sql_fail(-1, "08001", "PostgreSQL client library: %s", why);
			return NULL;
		}
		const char *keys[6], *vals[6];
		int k = 0;
		char db[256], host[256], port[32];
		const char *at = strchr(target, '@');
		if (!strncmp(target, "pg:", 3)) {
			keys[k] = "dbname";
			vals[k++] = target + 3;
		} else if (at && !strchr(target, '=') && strncmp(target, "postgres", 8)) {
			snprintf(db, sizeof db, "%.*s", (int)(at - target), target);
			snprintf(host, sizeof host, "%s", at + 1);
			char *colon = strchr(host, ':');
			keys[k] = "dbname";
			vals[k++] = db;
			if (colon) {
				*colon = 0;
				snprintf(port, sizeof port, "%s", colon + 1);
				keys[k] = "port";
				vals[k++] = port;
			}
			keys[k] = "host";
			vals[k++] = host;
		} else {
			keys[k] = "dbname";
			vals[k++] = target;
		}
		if (user && *user) {
			keys[k] = "user";
			vals[k++] = user;
		}
		if (pass && *pass) {
			keys[k] = "password";
			vals[k++] = pass;
		}
		keys[k] = NULL;
		vals[k] = NULL;
		c->kind = DB_PG;
		c->pg = pq.connectdbParams(keys, vals, 1);
		if (!c->pg || pq.status(c->pg) != PG_CONNECTION_OK) {
			char msg[512];
			snprintf(msg, sizeof msg, "%s", c->pg ? pq.errorMessage(c->pg) : "out of memory");
			if (c->pg)
				pq.finish(c->pg);
			free(c);
			sql_fail(-30081, "08001", "%s", msg);
			return NULL;
		}
		pq.setNoticeProcessor(c->pg, quiet_notices, NULL);
	} else {
		if (!load_sqlite(why, sizeof why)) {
			free(c);
			sql_fail(-1, "08001", "SQLite library: %s", why);
			return NULL;
		}
		const char *path = !strncmp(target, "sqlite:", 7) ? target + 7 : target;
		c->kind = DB_SQLITE;
		if (sq.open_v2(path, &c->db, SQ_OPEN_READWRITE | SQ_OPEN_CREATE | SQ_OPEN_URI, NULL) != SQ_OK) {
			char msg[512];
			snprintf(msg, sizeof msg, "%s: %s", path, c->db ? sq.errmsg(c->db) : "cannot open");
			if (c->db)
				sq.close_v2(c->db);
			free(c);
			sql_fail(-1, "08001", "%s", msg);
			return NULL;
		}
		sq.busy_timeout(c->db, 10000);
	}
	c->next = conns;
	conns = c;
	if (!end_registered) {
		atexit(end_at_exit);
		end_registered = 1;
	}
	return c;
}

static sqlconn *conn_named(const char *name)
{
	for (sqlconn *c = conns; c; c = c->next)
		if (!strcasecmp(c->name, name))
			return c;
	return NULL;
}

/* the connection a statement runs on: CONNECT's, or COB_SQL_DATABASE's */
static sqlconn *need_conn(void)
{
	if (current)
		return current;
	const char *db = getenv("COB_SQL_DATABASE");
	if (db && *db) {
		current = connect_to(db, getenv("COB_SQL_USER"), getenv("COB_SQL_PASSWORD"), NULL);
		return current;
	}
	sql_fail(-1024, "08003", "no database connection (CONNECT, or set COB_SQL_DATABASE)");
	return NULL;
}

void cob_sql_connect(const cob_sql_ca *ca, cob_field *target, cob_field *user, cob_field *pass, cob_field *name)
{
	char *t = field_text(target), *u = field_text(user), *p = field_text(pass), *n = field_text(name);
	sql_begin(ca, "CONNECT");
	if (!t || !*t) {
		sql_fail(-1, "08001", "CONNECT: no database named");
	} else {
		/* a connection of the same name is replaced, its work rolled back */
		sqlconn *old = conn_named(n && *n ? n : "DEFAULT");
		if (old)
			conn_close(old, 1);
		sqlconn *c = connect_to(t, u, p, n);
		if (c) {
			current = c;
			sql_ok();
		}
	}
	free(t);
	free(u);
	free(p);
	free(n);
}

/* DISCONNECT name / CURRENT (name NULL) / ALL; CONNECT RESET is CURRENT */
void cob_sql_disconnect(const cob_sql_ca *ca, cob_field *name, int all)
{
	sql_begin(ca, "DISCONNECT");
	if (all) {
		cob_sql_end(1);
		sql_ok();
		return;
	}
	char *n = field_text(name);
	sqlconn *c = n && *n && strcasecmp(n, "CURRENT") ? conn_named(n) : current;
	free(n);
	if (!c) {
		sql_fail(-1024, "08003", "DISCONNECT: no such connection");
		return;
	}
	conn_close(c, 1);
	sql_ok();
}

void cob_sql_set_connection(const cob_sql_ca *ca, cob_field *name)
{
	sql_begin(ca, "SET CONNECTION");
	char *n = field_text(name);
	sqlconn *c = n ? conn_named(n) : NULL;
	free(n);
	if (!c) {
		sql_fail(-843, "08003", "SET CONNECTION: no such connection");
		return;
	}
	current = c;
	sql_ok();
}

/* COMMIT / ROLLBACK [WORK] [RELEASE] */
void cob_sql_end_work(const cob_sql_ca *ca, int rollback, int release)
{
	sql_begin(ca, rollback ? "ROLLBACK" : "COMMIT");
	sqlconn *c = need_conn();
	if (!c)
		return;
	conn_end_work(c, rollback);
	if (release)
		conn_close(c, 0);
	sql_ok();
}

/* ------------------------------------------------- statement text, values */

/* SQLite has no FOR UPDATE (a writer locks the whole database): a SELECT's
 * FOR UPDATE at its end, outside strings and parentheses, goes */
static void drop_for_update(char *sql)
{
	char q = 0;
	int depth = 0;
	char *cut = NULL;
	for (char *p = sql; *p; p++) {
		if (q) {
			if (*p == q)
				q = 0;
			continue;
		}
		if (*p == '\'' || *p == '"')
			q = *p;
		else if (*p == '(')
			depth++;
		else if (*p == ')')
			depth--;
		else if (depth == 0 && (p == sql || p[-1] == ' ') && !strncasecmp(p, "FOR UPDATE", 10) &&
			 (p[10] == 0 || p[10] == ' '))
			cut = p;
	}
	if (cut)
		*cut = 0;
}

/* the text for the database: ? as $n for PostgreSQL, and the row-key marker
 * as the column that names a row (SQLite's rowid, PostgreSQL's ctid) */
static char *for_db(sqlconn *c, const char *sql)
{
	size_t n = strlen(sql);
	char *out = cob_malloc(n * 4 + 16);
	size_t o = 0;
	int param = 0;
	char q = 0;
	for (size_t i = 0; i < n; i++) {
		char ch = sql[i];
		if (q) {
			out[o++] = ch;
			if (ch == q)
				q = 0;
			continue;
		}
		if (ch == '\'' || ch == '"') {
			q = ch;
			out[o++] = ch;
		} else if (ch == '-' && sql[i + 1] == '-') {
			while (i < n && sql[i] != '\n')
				i++;
			out[o++] = ' ';
		} else if (ch == '?' && c->kind == DB_PG) {
			o += (size_t)sprintf(out + o, "$%d", ++param);
		} else if (ch == '\001') {
			const char *k = c->kind == DB_PG ? "ctid" : "rowid";
			memcpy(out + o, k, strlen(k));
			o += strlen(k);
		} else {
			out[o++] = ch;
		}
	}
	out[o] = 0;
	if (c->kind == DB_SQLITE)
		drop_for_update(out);
	return out;
}

static int first_word_is(const char *sql, const char *w)
{
	while (*sql == ' ' || *sql == '\t' || *sql == '\n' || *sql == '(')
		sql++;
	size_t l = strlen(w);
	return !strncasecmp(sql, w, l) && !isalnum((unsigned char)sql[l]) && sql[l] != '_';
}

/* an INSERT, UPDATE, DELETE or MERGE: SQLCODE 100 when it changes nothing */
static int changes_rows(const char *sql)
{
	return first_word_is(sql, "INSERT") || first_word_is(sql, "UPDATE") || first_word_is(sql, "DELETE") ||
	       first_word_is(sql, "MERGE") || first_word_is(sql, "REPLACE");
}

/* statements that manage the unit of work themselves */
static int is_tx_stmt(const char *sql)
{
	return first_word_is(sql, "BEGIN") || first_word_is(sql, "COMMIT") || first_word_is(sql, "ROLLBACK") ||
	       first_word_is(sql, "END") || first_word_is(sql, "START") || first_word_is(sql, "SAVEPOINT") ||
	       first_word_is(sql, "RELEASE");
}

static int is_numeric_attr(const cob_attr *a)
{
	switch (a->type) {
	case COB_NUM_DISPLAY: case COB_NUM_PACKED: case COB_NUM_BINARY: case COB_NUM_COMP5:
	case COB_NUM_FLOAT: case COB_NUM_DOUBLE: case COB_NUM_DEC_FLOAT: case COB_INDEX:
		return 1;
	}
	return 0;
}

typedef struct {
	int isnull;
	int kind;                /* 0 text, 1 integer, 2 floating point */
	long long i;
	double d;
	char *text;
	size_t len;
} param;

static void hv_param(const cob_sql_hv *hv, param *pa)
{
	memset(pa, 0, sizeof *pa);
	if (hv->ind && cob_get_int(hv->ind) < 0) {
		pa->isnull = 1;
		return;
	}
	cob_field *f = hv->f;
	if (hv->len) {
		/* a VARCHAR: the length item says how much of the text */
		cob_s64 n = cob_get_int(hv->len);
		if (n < 0)
			n = 0;
		if ((size_t)n > f->size)
			n = (cob_s64)f->size;
		pa->text = cob_malloc((size_t)n + 1);
		memcpy(pa->text, f->data, (size_t)n);
		pa->text[n] = 0;
		pa->len = (size_t)n;
		return;
	}
	char buf[128];
	switch (f->attr->type) {
	case COB_NUM_FLOAT:
	case COB_NUM_DOUBLE: {
		double x;
		if (f->attr->type == COB_NUM_FLOAT) {
			float fl;
			memcpy(&fl, f->data, 4);
			x = fl;
		} else {
			memcpy(&x, f->data, 8);
		}
		pa->kind = 2;
		pa->d = x;
		snprintf(buf, sizeof buf, "%.17g", x);
		break;
	}
	case COB_NUM_DEC_FLOAT:
		cob_dec_float_str(f, buf, sizeof buf);
		break;
	case COB_NUM_DISPLAY:
	case COB_NUM_PACKED:
	case COB_NUM_BINARY:
	case COB_NUM_COMP5:
	case COB_INDEX: {
		cob_dec d = cob_d_get(f);
		cob_d_to_str(d, buf, sizeof buf);
		if (f->attr->scale <= 0 && f->attr->digits <= 18) {
			pa->kind = 1;
			pa->i = (long long)cob_d_to_int(d);
		} else {
			pa->kind = 2;
			pa->d = cob_d_to_double(d);
		}
		break;
	}
	default: {
		/* text: its trailing spaces off, its leading ones kept */
		size_t n = f->size;
		while (n > 0 && f->data[n - 1] == ' ')
			n--;
		pa->text = cob_malloc(n + 1);
		memcpy(pa->text, f->data, n);
		pa->text[n] = 0;
		pa->len = n;
		return;
	}
	}
	pa->len = strlen(buf);
	pa->text = cob_malloc(pa->len + 1);
	memcpy(pa->text, buf, pa->len + 1);
}

static void params_free(param *pa, int n)
{
	for (int i = 0; i < n; i++)
		free(pa[i].text);
	free(pa);
}

static param *params_make(int nin, const cob_sql_hv *in, const char *key)
{
	param *pa = cob_malloc(sizeof *pa * (size_t)(nin + 1));
	for (int i = 0; i < nin; i++)
		hv_param(&in[i], &pa[i]);
	if (key) {
		memset(&pa[nin], 0, sizeof pa[nin]);
		pa[nin].len = strlen(key);
		pa[nin].text = cob_malloc(pa[nin].len + 1);
		memcpy(pa[nin].text, key, pa[nin].len + 1);
	}
	return pa;
}

/* a number's text (a column value), as a decimal: 0 when it is one */
static int text_number(const char *s, size_t n, cob_dec *out)
{
	char num[128];
	size_t i = 0, k = 0, digits = 0;
	int expo = 0, eneg = 0;
	while (i < n && s[i] == ' ')
		i++;
	while (n > i && s[n - 1] == ' ')
		n--;
	if (i < n && (s[i] == '+' || s[i] == '-'))
		num[k++] = s[i++];
	for (; i < n && (isdigit((unsigned char)s[i]) || s[i] == '.'); i++) {
		if (s[i] != '.')
			digits++;
		if (k < sizeof num - 16)
			num[k++] = s[i];
	}
	if (!digits)
		return -1;
	if (i < n && (s[i] == 'e' || s[i] == 'E')) {
		i++;
		if (i < n && (s[i] == '+' || s[i] == '-'))
			eneg = s[i++] == '-';
		if (i >= n || !isdigit((unsigned char)s[i]))
			return -1;
		for (; i < n && isdigit((unsigned char)s[i]); i++)
			if (expo < 99999)
				expo = expo * 10 + (s[i] - '0');
	}
	if (i != n)
		return -1;
	snprintf(num + k, sizeof num - k, "E%c%d", eneg ? '-' : '+', expo > 99999 ? 99999 : expo);
	*out = cob_d_exp_str(num);
	return 0;
}

/* a column's value to a host variable; -1 after an error */
static int hv_assign(const cob_sql_hv *hv, const char *v, size_t n, int isnull, int col)
{
	if (isnull) {
		if (!hv->ind)
			return sql_fail(-305, "22002", "column %d is null and its host variable has no indicator",
					col + 1);
		cob_set_int(hv->ind, -1);
		return 0;
	}
	if (hv->ind)
		cob_set_int(hv->ind, 0);
	cob_field *f = hv->f;
	if (hv->len) {
		size_t m = n < f->size ? n : f->size;
		memcpy(f->data, v, m);
		memset(f->data + m, ' ', f->size - m);
		cob_set_int(hv->len, (cob_s64)m);
		if (m < n) {
			cur_warn1 = 1;
			if (hv->ind)
				cob_set_int(hv->ind, (cob_s64)n);
		}
		return 0;
	}
	if (is_numeric_attr(f->attr)) {
		cob_dec d;
		if (n == 1 && (v[0] == 't' || v[0] == 'f')) {
			d = cob_d_int(v[0] == 't');    /* a PostgreSQL boolean */
		} else if (text_number(v, n, &d)) {
			return sql_fail(-420, "22018", "column %d, '%.*s', is not a number", col + 1,
					(int)(n > 40 ? 40 : n), v);
		}
		int t = f->attr->type;
		if (t == COB_NUM_FLOAT || t == COB_NUM_DOUBLE || t == COB_NUM_DEC_FLOAT)
			cob_d_set(f, d, 0);
		else if (cob_d_set(f, d, COB_SIZE_CHECK))
			return sql_fail(-304, "22003", "column %d, %.*s, is out of range for its host variable",
					col + 1, (int)(n > 40 ? 40 : n), v);
		return 0;
	}
	if (n > f->size) {
		for (size_t k = f->size; k < n; k++)
			if (v[k] != ' ') {
				cur_warn1 = 1;
				if (hv->ind)
					cob_set_int(hv->ind, (cob_s64)n);
				break;
			}
	}
	cob_move(CF(v, n, &cob_attr_alnum), f);
	return 0;
}

/* ------------------------------------------------------ errors to SQLCODE */
static void sq_error(sqlconn *c)
{
	int ext = sq.extended_errcode(c->db);
	const char *msg = sq.errmsg(c->db);
	int code = -1;
	const char *state = "HY000";
	switch (ext & 0xff) {
	case 19:                                    /* SQLITE_CONSTRAINT */
		switch (ext >> 8) {
		case 6: case 8: code = -803; state = "23505"; break;   /* PRIMARYKEY, UNIQUE */
		case 5: code = -407; state = "23502"; break;            /* NOTNULL */
		case 3: code = -530; state = "23503"; break;            /* FOREIGNKEY */
		case 1: code = -545; state = "23513"; break;            /* CHECK */
		default: state = "23000";
		}
		break;
	case 5: case 6:                             /* SQLITE_BUSY, SQLITE_LOCKED */
		code = -911;
		state = "40001";
		break;
	case 18:                                    /* SQLITE_TOOBIG */
		code = -302;
		state = "22001";
		break;
	case 1:                                     /* SQLITE_ERROR */
		if (strstr(msg, "no such table")) {
			code = -204;
			state = "42704";
		} else if (strstr(msg, "no such column")) {
			code = -206;
			state = "42703";
		} else if (strstr(msg, "syntax error") || strstr(msg, "incomplete input")) {
			code = -104;
			state = "42601";
		} else if (strstr(msg, "already exists")) {
			code = -601;
			state = "42710";
		}
		break;
	}
	sql_fail(code, state, "%s", msg);
}

static void pg_error(PGresult *r, sqlconn *c)
{
	const char *state = r ? pq.resultErrorField(r, PG_DIAG_SQLSTATE) : NULL;
	const char *msg = r ? pq.resultErrorField(r, PG_DIAG_MESSAGE_PRIMARY) : NULL;
	if (!msg)
		msg = pq.errorMessage(c->pg);
	if (!state)
		state = "HY000";
	static const struct { const char *state; int code; } map[] = {
		{ "23505", -803 }, { "23502", -407 }, { "23503", -530 }, { "23514", -545 },
		{ "42P01", -204 }, { "42703", -206 }, { "42601", -104 }, { "42P07", -601 },
		{ "42710", -601 }, { "40001", -911 }, { "40P01", -911 }, { "55P03", -911 },
		{ "22001", -302 }, { "22003", -304 }, { "22P02", -420 }, { "22018", -420 },
		{ "57014", -952 }, { "21000", -811 }
	};
	int code = -1;
	for (size_t i = 0; i < sizeof map / sizeof map[0]; i++)
		if (!strcmp(map[i].state, state))
			code = map[i].code;
	if (!strncmp(state, "08", 2))
		code = -30081;
	sql_fail(code, state, "%s", msg);
}

/* ------------------------------------------------------- running a statement */

/* SQLite: bind the parameters (the row key, if any, as the last one) */
static int sq_bind(sqlite3_stmt *st, param *pa, int np)
{
	for (int i = 0; i < np; i++) {
		int rc;
		if (pa[i].isnull)
			rc = sq.bind_null(st, i + 1);
		else if (pa[i].kind == 1)
			rc = sq.bind_int64(st, i + 1, pa[i].i);
		else if (pa[i].kind == 2)
			rc = sq.bind_double(st, i + 1, pa[i].d);
		else
			rc = sq.bind_text(st, i + 1, pa[i].text, (int)pa[i].len, SQ_TRANSIENT);
		if (rc != SQ_OK)
			return -1;
	}
	return 0;
}

/* a row's columns into the host variables; the key column, if any, kept */
static int sq_row(sqlite3_stmt *st, int nout, const cob_sql_hv *out, int keyed, char **key)
{
	int ncol = sq.column_count(st) - (keyed ? 1 : 0);
	if (ncol != nout)
		cur_warn3 = 1;
	for (int i = 0; i < nout && i < ncol; i++) {
		int isnull = sq.column_type(st, i) == 5;
		const char *v = (const char *)sq.column_text(st, i);
		size_t n = (size_t)sq.column_bytes(st, i);
		if (hv_assign(&out[i], v ? v : "", v ? n : 0, isnull, i))
			return -1;
	}
	if (keyed && key) {
		free(*key);
		const char *v = (const char *)sq.column_text(st, ncol);
		size_t n = v ? strlen(v) : 0;
		*key = cob_malloc(n + 1);
		memcpy(*key, v ? v : "", n + 1);
	}
	return 0;
}

static int pg_row(PGresult *r, int row, int nout, const cob_sql_hv *out, int keyed, char **key)
{
	int ncol = pq.nfields(r) - (keyed ? 1 : 0);
	if (ncol != nout)
		cur_warn3 = 1;
	for (int i = 0; i < nout && i < ncol; i++) {
		const char *v = pq.getvalue(r, row, i);
		if (hv_assign(&out[i], v, (size_t)pq.getlength(r, row, i), pq.getisnull(r, row, i), i))
			return -1;
	}
	if (keyed && key) {
		free(*key);
		const char *v = pq.getvalue(r, row, ncol);
		size_t n = strlen(v);
		*key = cob_malloc(n + 1);
		memcpy(*key, v, n + 1);
	}
	return 0;
}

/* PostgreSQL: the unit of work, and a savepoint around one statement so an
 * error undoes that statement alone, as in DB2 (PostgreSQL would otherwise
 * refuse every statement after it until ROLLBACK). COB_SQL_SAVEPOINT=N
 * leaves the savepoints out: a statement costs one round trip instead of
 * three, and an error spoils the unit of work. */
static int use_savepoints(void)
{
	static int on = -1;
	if (on < 0) {
		const char *e = getenv("COB_SQL_SAVEPOINT");
		on = !(e && (*e == 'N' || *e == 'n' || *e == '0'));
	}
	return on;
}

static void pg_open_work(sqlconn *c, const char *sql)
{
	if (!c->in_work && !is_tx_stmt(sql)) {
		pg_simple(c, "BEGIN");
		c->in_work = 1;
	}
	if (c->in_work && use_savepoints())
		pg_simple(c, "SAVEPOINT cob_sql_stmt");
}

static void pg_close_stmt(sqlconn *c, int failed)
{
	if (c->in_work && use_savepoints())
		pg_simple(c, failed ? "ROLLBACK TO SAVEPOINT cob_sql_stmt" : "RELEASE SAVEPOINT cob_sql_stmt");
}

static PGresult *pg_run(sqlconn *c, const char *dbsql, param *pa, int np)
{
	const char **vals = cob_malloc(sizeof *vals * (size_t)(np + 1));
	int *lens = cob_malloc(sizeof *lens * (size_t)(np + 1));
	for (int i = 0; i < np; i++) {
		vals[i] = pa[i].isnull ? NULL : pa[i].text;
		lens[i] = (int)pa[i].len;
	}
	PGresult *r = np ? pq.execParams(c->pg, dbsql, np, NULL, vals, lens, NULL, 0) : pq.exec(c->pg, dbsql);
	free(vals);
	free(lens);
	return r;
}

/* one statement: nout > 0 for SELECT INTO (a single row), key for a
 * positioned UPDATE or DELETE */
static void run(sqlconn *c, const char *sql, int nin, const cob_sql_hv *in, const char *key, int nout,
		const cob_sql_hv *out)
{
	int np = nin + (key ? 1 : 0);
	param *pa = params_make(nin, in, key);
	if (key && c->kind == DB_SQLITE) {
		pa[nin].kind = 1;
		pa[nin].i = strtoll(key, NULL, 10);
	}
	char *dbsql = for_db(c, sql);
	if (c->kind == DB_SQLITE) {
		if (sq.get_autocommit(c->db) && !is_tx_stmt(sql)) {
			sqlite3_stmt *b;
			if (sq.prepare_v2(c->db, "BEGIN", -1, &b, NULL) == SQ_OK) {
				sq.step(b);
				sq.finalize(b);
			}
		}
		const char *rest = dbsql;
		int done = 0;
		while (!done) {
			sqlite3_stmt *st = NULL;
			const char *tail = NULL;
			if (sq.prepare_v2(c->db, rest, -1, &st, &tail) != SQ_OK) {
				sq_error(c);
				break;
			}
			if (!st) {                    /* nothing but white space or comments */
				sql_ok();
				break;
			}
			if (sq_bind(st, pa, np)) {
				sq_error(c);
				sq.finalize(st);
				break;
			}
			int rc = sq.step(st);
			if (rc == SQ_ROW) {
				if (nout) {
					if (sq_row(st, nout, out, 0, NULL) == 0) {
						cur_rows = 1;
						rc = sq.step(st);
						if (rc == SQ_ROW)
							sql_fail(-811, "21000",
								 "SELECT INTO found more than one row");
						else
							sql_ok();
					}
				} else {
					while (rc == SQ_ROW)
						rc = sq.step(st);
					if (rc == SQ_DONE)
						sql_ok();
					else
						sq_error(c);
				}
			} else if (rc == SQ_DONE) {
				if (nout) {
					sql_done(100, "02000", "no row");
				} else if (changes_rows(rest)) {
					cur_rows = sq.changes(c->db);
					if (cur_rows == 0)
						sql_done(100, "02000", "no row");
					else
						sql_ok();
				} else {
					sql_ok();
				}
			} else {
				sq_error(c);
				sq.finalize(st);
				break;
			}
			sq.finalize(st);
			/* a text of several statements (EXECUTE IMMEDIATE of a script)
			 * runs them all, while each succeeds and none takes values */
			rest = tail;
			while (rest && (*rest == ' ' || *rest == '\n' || *rest == '\t' || *rest == ';'))
				rest++;
			done = !rest || !*rest || np || nout || last_code < 0;
		}
	} else {
		pg_open_work(c, sql);
		PGresult *r = pg_run(c, dbsql, pa, np);
		int st = r ? pq.resultStatus(r) : -1;
		int failed = 0;
		if (st == PG_TUPLES_OK) {
			int rows = pq.ntuples(r);
			if (nout) {
				if (rows == 0)
					sql_done(100, "02000", "no row");
				else if (pg_row(r, 0, nout, out, 0, NULL) == 0) {
					cur_rows = 1;
					if (rows > 1)
						sql_fail(-811, "21000", "SELECT INTO found more than one row");
					else
						sql_ok();
				}
			} else {
				cur_rows = rows;
				sql_ok();
			}
		} else if (st == PG_COMMAND_OK) {
			const char *t = pq.cmdTuples(r);
			cur_rows = t && *t ? atoi(t) : 0;
			if ((nout || changes_rows(sql)) && cur_rows == 0)
				sql_done(100, "02000", "no row");
			else
				sql_ok();
		} else if (st == 0) {               /* an empty query */
			sql_ok();
		} else {
			pg_error(r, c);
			failed = 1;
		}
		if (r)
			pq.clear(r);
		pg_close_stmt(c, failed);
		if (is_tx_stmt(sql))
			c->in_work = first_word_is(sql, "BEGIN") || first_word_is(sql, "START");
	}
	free(dbsql);
	params_free(pa, np);
}

void cob_sql_exec(const cob_sql_ca *ca, const char *sql, int nin, const cob_sql_hv *in, int nout, const cob_sql_hv *out)
{
	sql_begin(ca, sql);
	sqlconn *c = need_conn();
	if (c)
		run(c, sql, nin, in, NULL, nout, out);
}

/* UPDATE / DELETE ... WHERE CURRENT OF cursor: the statement's last
 * parameter is the key of the cursor's row */
void cob_sql_current(const cob_sql_ca *ca, const char *sql, const char *cursor, int nin, const cob_sql_hv *in)
{
	sql_begin(ca, sql);
	sqlcursor *k = cursor_find(cursor, 0);
	if (!k || !k->conn) {
		sql_fail(-501, "24501", "cursor %s is not open", strchr(cursor, ':') ? strchr(cursor, ':') + 1 : cursor);
		return;
	}
	if (!k->key) {
		sql_fail(-508, "24504", "cursor %s is not on a row", strchr(cursor, ':') ? strchr(cursor, ':') + 1 : cursor);
		return;
	}
	char *key = cob_malloc(strlen(k->key) + 1);
	strcpy(key, k->key);
	run(k->conn, sql, nin, in, key, 0, NULL);
	free(key);
}

static const char *short_name(const char *qualified)
{
	const char *p = strchr(qualified, ':');
	return p ? p + 1 : qualified;
}

static sqlprep *prep_find(const char *name)
{
	for (sqlprep *p = preps; p; p = p->next)
		if (!strcmp(p->name, name))
			return p;
	return NULL;
}

/* OPEN: the cursor's SELECT (or the statement PREPAREd for it) runs with the
 * host variables' values now */
void cob_sql_open(const cob_sql_ca *ca, const char *cursor, const char *sql, const char *prepared, int keyed, int hold,
		  int nin, const cob_sql_hv *in)
{
	sql_begin(ca, sql ? sql : prepared);
	sqlcursor *k = cursor_find(cursor, 1);
	if (k->conn) {
		sql_fail(-502, "24502", "cursor %s is already open", short_name(cursor));
		return;
	}
	if (!sql) {
		sqlprep *p = prep_find(prepared);
		if (!p) {
			sql_fail(-514, "26501", "statement %s is not prepared", short_name(prepared));
			return;
		}
		sql = p->text;
		keyed = 0;
	}
	sqlconn *c = need_conn();
	if (!c)
		return;
	param *pa = params_make(nin, in, NULL);
	char *dbsql = for_db(c, sql);
	k->keyed = keyed;
	k->hold = hold;
	k->done = 0;
	if (c->kind == DB_SQLITE) {
		if (sq.get_autocommit(c->db)) {
			sqlite3_stmt *b;
			if (sq.prepare_v2(c->db, "BEGIN", -1, &b, NULL) == SQ_OK) {
				sq.step(b);
				sq.finalize(b);
			}
		}
		sqlite3_stmt *st = NULL;
		if (sq.prepare_v2(c->db, dbsql, -1, &st, NULL) != SQ_OK || !st) {
			sq_error(c);
		} else if (sq_bind(st, pa, nin)) {
			sq_error(c);
			sq.finalize(st);
		} else {
			k->st = st;
			k->conn = c;
			sql_ok();
		}
	} else {
		pg_open_work(c, sql);
		PGresult *r = pg_run(c, dbsql, pa, nin);
		if (r && pq.resultStatus(r) == PG_TUPLES_OK) {
			k->res = r;
			k->row = 0;
			k->nrows = pq.ntuples(r);
			k->conn = c;
			pg_close_stmt(c, 0);
			sql_ok();
		} else {
			pg_error(r, c);
			if (r)
				pq.clear(r);
			pg_close_stmt(c, 1);
		}
	}
	free(dbsql);
	params_free(pa, nin);
}

void cob_sql_fetch(const cob_sql_ca *ca, const char *cursor, int nout, const cob_sql_hv *out)
{
	char what[128];
	snprintf(what, sizeof what, "FETCH %s", short_name(cursor));
	sql_begin(ca, what);
	sqlcursor *k = cursor_find(cursor, 0);
	if (!k || !k->conn) {
		sql_fail(-501, "24501", "cursor %s is not open", short_name(cursor));
		return;
	}
	free(k->key);
	k->key = NULL;
	if (k->st) {
		int rc = k->done ? SQ_DONE : sq.step(k->st);
		if (rc != SQ_ROW)
			k->done = 1;
		if (rc == SQ_ROW) {
			if (sq_row(k->st, nout, out, k->keyed, &k->key) == 0) {
				cur_rows = 1;
				sql_ok();
			}
		} else if (rc == SQ_DONE) {
			sql_done(100, "02000", "no more rows");
		} else {
			sq_error(k->conn);
		}
	} else {
		if (k->row >= k->nrows) {
			sql_done(100, "02000", "no more rows");
		} else if (pg_row(k->res, k->row++, nout, out, k->keyed, &k->key) == 0) {
			cur_rows = 1;
			sql_ok();
		}
	}
}

void cob_sql_close(const cob_sql_ca *ca, const char *cursor)
{
	char what[128];
	snprintf(what, sizeof what, "CLOSE %s", short_name(cursor));
	sql_begin(ca, what);
	sqlcursor *k = cursor_find(cursor, 0);
	if (!k || !k->conn) {
		sql_fail(-501, "24501", "cursor %s is not open", short_name(cursor));
		return;
	}
	cursor_close(k);
	sql_ok();
}

/* the text of a dynamic statement: a VARCHAR's, or an item's without its
 * trailing spaces */
static char *hv_text(const cob_sql_hv *hv)
{
	param pa;
	hv_param(hv, &pa);
	if (pa.isnull || !pa.text) {
		free(pa.text);
		char *e = cob_malloc(1);
		*e = 0;
		return e;
	}
	return pa.text;
}

void cob_sql_prepare(const cob_sql_ca *ca, const char *name, const cob_sql_hv *text)
{
	char *t = hv_text(text);
	sql_begin(ca, t);
	sqlprep *p = prep_find(name);
	if (!p) {
		p = cob_malloc(sizeof *p);
		memset(p, 0, sizeof *p);
		snprintf(p->name, sizeof p->name, "%s", name);
		p->next = preps;
		preps = p;
	}
	free(p->text);
	p->text = t;
	/* SQLite checks the statement now, as DB2's PREPARE does */
	sqlconn *c = need_conn();
	if (!c)
		return;
	if (c->kind == DB_SQLITE) {
		char *dbsql = for_db(c, t);
		sqlite3_stmt *st = NULL;
		if (sq.prepare_v2(c->db, dbsql, -1, &st, NULL) != SQ_OK)
			sq_error(c);
		else
			sql_ok();
		if (st)
			sq.finalize(st);
		free(dbsql);
	} else {
		sql_ok();
	}
}

void cob_sql_execute(const cob_sql_ca *ca, const char *name, int nin, const cob_sql_hv *in, int nout, const cob_sql_hv *out)
{
	sqlprep *p = prep_find(name);
	sql_begin(ca, p ? p->text : name);
	if (!p) {
		sql_fail(-514, "26501", "statement %s is not prepared", short_name(name));
		return;
	}
	sqlconn *c = need_conn();
	if (c)
		run(c, p->text, nin, in, NULL, nout, out);
}

void cob_sql_immediate(const cob_sql_ca *ca, const cob_sql_hv *text)
{
	char *t = hv_text(text);
	sql_begin(ca, t);
	sqlconn *c = need_conn();
	if (c)
		run(c, t, 0, NULL, NULL, 0, NULL);
	free(t);
}
