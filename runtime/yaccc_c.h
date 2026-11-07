/* SPDX-License-Identifier: MIT */
/* yaccc_c.h - the C entry points a COBOL program and a C main share.
 *
 * A C function a COBOL program CALLs, and a C main program that calls COBOL,
 * need nothing more than this:
 *
 *     int dump (unsigned char *data);        called by COBOL
 *     extern int SUBPROG (void *a, void *b); a COBOL program
 *
 * A COBOL program called from C starts the runtime itself, so cob_init is
 * optional.
 *
 * The five names below are the published C interface of GnuCOBOL, and they are
 * spelled that way on purpose and only for that reason: C code already written
 * against that interface compiles and links here without edits. The
 * implementations are YACCC's (runtime/cobrt_call.c and friends); none of
 * GnuCOBOL's source is used or consulted for them. Field-level functions
 * (cob_get_field_str and the like) are deliberately absent -- their cob_field
 * layout is GnuCOBOL's own and reproducing it would mean reproducing their
 * data structures, which this project does not do.
 */
#ifndef YACCC_C_H
#define YACCC_C_H

#ifdef __cplusplus
extern "C" {
#endif

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
