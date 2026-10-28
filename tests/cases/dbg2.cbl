       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG2.
      * Debug module, standard behavior checked by hand (dbg2.noref):
      * DEBUG-LINE, ALL PROCEDURES with sections, SORT and USE
      * procedures, GO TO DEPENDING, STRING/READ INTO, DEBUG-ITEM space
      * filling. GnuCOBOL 3.1.2 leaves stale DEBUG-ITEM fields, has no
      * DEBUG-LINE for START PROGRAM and skips STRING/READ INTO.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. X86-64
           WITH DEBUGGING MODE.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DFILE ASSIGN TO "dbg2.dat"
               ORGANIZATION LINE SEQUENTIAL.
           SELECT NOFILE ASSIGN TO "dbg2-missing.dat"
               FILE STATUS IS NOFILE-STATUS.
           SELECT SFILE ASSIGN TO "dbg2.srt".
       DATA DIVISION.
       FILE SECTION.
       FD  DFILE.
       01  DREC            PIC X(10).
       FD  NOFILE.
       01  NOREC           PIC X(10).
       SD  SFILE.
       01  SREC.
           05  SKEY        PIC 9.
       WORKING-STORAGE SECTION.
       01  KEY-VAL         PIC 9 VALUE 2.
       01  WATCHED         PIC X(5) VALUE SPACES.
       01  INTO-AREA       PIC X(10) VALUE SPACES.
       01  TBL.
           05  ELEM        PIC 9 OCCURS 3 TIMES.
       01  NOFILE-STATUS   PIC XX.
       01  N               PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D-ALL SECTION.
           USE FOR DEBUGGING ON ALL PROCEDURES.
       D-ALL-1.
           DISPLAY "P " DEBUG-LINE " " DEBUG-NAME (1:14) " ["
               DEBUG-CONTENTS (1:13) "]".
       D-DATA SECTION.
           USE FOR DEBUGGING ON ALL REFERENCES OF KEY-VAL
               ALL REFERENCES OF WATCHED INTO-AREA ELEM.
       D-DATA-1.
           DISPLAY "D " DEBUG-LINE " " DEBUG-NAME (1:14) " ["
               DEBUG-CONTENTS (1:10) "] [" DEBUG-ITEM (39:5) "]".
       NOFILE-ERROR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON NOFILE.
       NOFILE-ERROR-1.
           DISPLAY "  error status " NOFILE-STATUS.
       END DECLARATIVES.
       FIRST-SECTION SECTION.
       BEGIN-PARA.
           DISPLAY "  begin".
           MOVE 1 TO ELEM (2).
           PERFORM SECOND-SECTION.
           PERFORM SHORT-PARA 2 TIMES.
           GO TO TARGET-1 TARGET-2 DEPENDING ON KEY-VAL.
       TARGET-1.
           DISPLAY "  wrong target".
       TARGET-2.
           STRING "ABC" DELIMITED SIZE INTO WATCHED.
           OPEN INPUT NOFILE.
           OPEN OUTPUT DFILE.
           MOVE "rec" TO DREC.
           WRITE DREC.
           CLOSE DFILE.
           OPEN INPUT DFILE.
           READ DFILE INTO INTO-AREA AT END CONTINUE END-READ.
           READ DFILE INTO INTO-AREA AT END CONTINUE END-READ.
           CLOSE DFILE.
           SORT SFILE ON ASCENDING KEY SKEY
               INPUT PROCEDURE IS SORT-IN
               OUTPUT PROCEDURE IS SORT-OUT.
           STOP RUN.
       SHORT-PARA.
           ADD 1 TO N.
       SECOND-SECTION SECTION.
       SECOND-PARA.
           DISPLAY "  second".
       SORT-IN SECTION.
       SORT-IN-1.
           MOVE 3 TO SKEY.
           RELEASE SREC.
       SORT-OUT SECTION.
       SORT-OUT-1.
           RETURN SFILE AT END CONTINUE END-RETURN.
