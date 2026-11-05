/* SPDX-License-Identifier: MIT */
/* -fprof: the time each section and paragraph of a run takes, written out
 * as CSV when the run ends.
 *
 * A program compiled with -fprof has a table of its procedures
 * (lib/yaccc/profgen.py), which it registers when it first runs. One entry
 * of all the tables is current: cob_prof_switch charges the time since the
 * last switch to it and makes another current, counting a call when the
 * switch is an entry to the procedure (its label reached) rather than a
 * return to it (from a PERFORM or a CALL). So an entry's time is the time
 * spent in the procedure itself, not in what it performs or calls.
 *
 * The report goes to COB_PROF_FILE ($$ in it becomes the process id), or
 * prof-<main program>.csv: one line per section (its own time and its
 * paragraphs') and per paragraph, in source order, with the calls, the
 * milliseconds and the share of the run's total. */
#include "cobrt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef struct prof_table {
	cob_prof_entry *t;
	int n;
	struct prof_table *next;
} prof_table;

cob_prof_entry *cob_prof_cur;
static unsigned long long prof_last;
static prof_table *tables, **tables_end = &tables;

static unsigned long long prof_now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (unsigned long long)ts.tv_sec * 1000000000ULL + (unsigned long long)ts.tv_nsec;
}

void cob_prof_switch(cob_prof_entry *e, int count)
{
	unsigned long long now = prof_now();
	if (cob_prof_cur)
		cob_prof_cur->ns += now - prof_last;
	prof_last = now;
	cob_prof_cur = e;
	if (count)
		e->calls++;
}

/* the report's file: COB_PROF_FILE with $$ as the process id, or
 * prof-<program>.csv */
static void report_name(char *out, size_t size)
{
	const char *e = getenv("COB_PROF_FILE");
	if (e && *e) {
		size_t o = 0;
		for (const char *p = e; *p && o + 24 < size; p++) {
			if (p[0] == '$' && p[1] == '$') {
				o += (size_t)snprintf(out + o, size - o, "%ld", (long)getpid());
				p++;
			} else
				out[o++] = *p;
		}
		out[o] = 0;
		return;
	}
	snprintf(out, size, "prof-%s.csv", tables && tables->t[0].prog[0] ? tables->t[0].prog : "yaccc");
}

static void prof_report(void)
{
	if (!tables)
		return;
	if (cob_prof_cur) {
		cob_prof_switch(cob_prof_cur, 0);
		cob_prof_cur = NULL;
	}
	char name[1024];
	report_name(name, sizeof name);
	FILE *o = fopen(name, "w");
	if (!o) {
		fprintf(stderr, "libcob: warning: -fprof: cannot write %s\n", name);
		return;
	}
	unsigned long long total = 0;
	for (prof_table *t = tables; t; t = t->next)
		for (int i = 0; i < t->n; i++)
			total += t->t[i].ns;
	fprintf(o, "program,section,paragraph,line,kind,calls,time-ms,percent\n");
	for (prof_table *t = tables; t; t = t->next) {
		for (int i = 0; i < t->n; i++) {
			const cob_prof_entry *e = &t->t[i];
			unsigned long long ns = e->ns;
			if (e->kind == 1) {
				/* a section: its own time and its paragraphs'; an unnamed
				 * one (a program without sections) is the whole program */
				if (!e->section[0])
					continue;
				for (int j = i + 1; j < t->n && t->t[j].kind == 0; j++)
					ns += t->t[j].ns;
			}
			fprintf(o, "%s,%s,%s,%d,%s,%llu,%.3f,%.2f\n", e->prog, e->section,
			        e->kind == 1 ? "" : (e->para[0] ? e->para : "(unnamed)"), e->line,
			        e->kind == 1 ? "section" : "paragraph", e->calls, (double)ns / 1e6,
			        total ? 100.0 * (double)ns / (double)total : 0.0);
		}
	}
	fclose(o);
}

void cob_prof_register(cob_prof_entry *t, int n, int *done)
{
	if (*done)
		return;
	*done = 1;
	prof_table *p = cob_malloc(sizeof *p);
	p->t = t;
	p->n = n;
	p->next = NULL;
	if (!tables)
		atexit(prof_report);
	*tables_end = p;
	tables_end = &p->next;
}
