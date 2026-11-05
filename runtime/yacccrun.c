/* SPDX-License-Identifier: MIT */
/* yacccrun.c - run a program from a module yaccc -m built (cobcrun's job)
 *
 * yacccrun PROGRAM [ARGUMENT...]: the program is found as CALL finds one --
 * in COB_LIBRARY_PATH, then the current directory, as PROGRAM.so -- and
 * runs as a main program would, with the ARGUMENTs as its command line.
 * The module brings its own compile settings (cob_module_settings). The
 * yacccrun script at the top of the tree builds this and passes it the
 * module, after taking -c FILE (a runtime configuration) and a path. */
#include "cobrt.h"

int main(int argc, char **argv)
{
	if (argc < 2) {
		fputs("usage: yacccrun PROGRAM [ARGUMENT...]\n", stderr);
		return 1;
	}
	cob_init(argc - 1, argv + 1);
	cob_callee ce = cob_lookup_name(argv[1], NULL);
	if (!ce.fn) {
		if (ce.cfn) {
			fprintf(stderr, "yacccrun: '%s' is a C function, not a COBOL program\n", argv[1]);
			return 1;
		}
		cob_call_not_found(NULL, argv[1]);
	}
	int rc = ce.fn(-1, NULL);       /* as a main program: its parameters, the arguments */
	cob_stop_run(rc);
	return rc;
}
