/* SPDX-License-Identifier: MIT */
/* libcob.h - for C code written to work with GnuCOBOL programs: the part of
 * that interface YACCC's runtime provides. A C function a COBOL program
 * CALLs, and a C main program that calls COBOL, need nothing more:
 *
 *     COB_EXT_EXPORT int dump (unsigned char *data);    called by COBOL
 *     extern int SUBPROG (void *a, void *b);             a COBOL program
 *
 * A COBOL program called from C starts the runtime itself, so cob_init is
 * optional. Field-level functions (cob_get_field_str and the like) are not
 * provided: their cob_field layout is GnuCOBOL's own. */
#ifndef YACCC_LIBCOB_H
#define YACCC_LIBCOB_H

#ifdef __cplusplus
extern "C" {
#endif

#define COB_EXT_EXPORT
#define COB_EXT_IMPORT extern

/* start the runtime with the program's arguments (for ACCEPT FROM ARGUMENT-VALUE) */
void cob_init(int argc, char **argv);
/* end the run unit: close the files, flush the output, exit with status */
void cob_stop_run(int status);
/* close the files and flush the output without exiting */
int cob_tidy(void);
/* call a COBOL program (or C function) by name, as CALL does */
int cob_call(const char *name, int argc, void **argv);
/* set before calling a COBOL program to the number of arguments passed */
extern int cob_call_params;

#ifdef __cplusplus
}
#endif
#endif
