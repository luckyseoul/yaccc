       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG5.
      * Debug module in a contained program: the containing program's
      * WITH DEBUGGING MODE applies to it. GnuCOBOL 3.1.2 rejects USE
      * FOR DEBUGGING in contained programs (dbg5.noref).
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. X WITH DEBUGGING MODE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N    PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D1 SECTION.
           USE FOR DEBUGGING ON N.
       D1-A.
           DISPLAY "outer debug " DEBUG-NAME (1:10) " ["
             DEBUG-CONTENTS (1:5) "]".
       END DECLARATIVES.
       MAIN-PARA.
           MOVE 3 TO N.
           CALL "INNER".
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  M    PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D2 SECTION.
           USE FOR DEBUGGING ON ALL PROCEDURES.
       D2-A.
           DISPLAY "inner debug " DEBUG-NAME (1:10) " ["
             DEBUG-CONTENTS (1:13) "]".
       END DECLARATIVES.
       IP1.
      D    DISPLAY "inner debugging line".
           ADD 1 TO M.
       IP2.
           EXIT PROGRAM.
       END PROGRAM INNER.
       END PROGRAM DBG5.
