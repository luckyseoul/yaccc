      *> IF item OMITTED tests whether a CALL left an argument out; the
      *> callee declares it OPTIONAL. Behaviour per GnuCOBOL (testsuite
      *> run_misc.at:3488).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OMITTED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  P1 PIC X VALUE "A".
       PROCEDURE DIVISION.
           CALL "OMITCALLEE" USING P1 END-CALL.
           CALL "OMITCALLEE" USING P1 "SECOND" END-CALL.
           DISPLAY "DONE".
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OMITCALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  P1 PIC X.
       01  P2 PIC X(6).
       PROCEDURE DIVISION USING P1 OPTIONAL P2.
           DISPLAY "NARGS=" NUMBER-OF-CALL-PARAMETERS.
           IF P2 OMITTED
               DISPLAY "P2 OMITTED"
           END-IF.
           IF P2 NOT OMITTED
               DISPLAY "P2=[" P2 "]"
           END-IF.
           EXIT PROGRAM.
       END PROGRAM OMITCALLEE.
       END PROGRAM OMITTED.
