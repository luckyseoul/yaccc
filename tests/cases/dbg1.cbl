       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG1.
      * Debug module: USE FOR DEBUGGING on procedures, data items, a
      * table element and a file; debugging lines. Runs with the
      * object-time switch on (COB_SET_DEBUG=Y in dbg1.env).
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. X86-64 WITH DEBUGGING MODE.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DFILE ASSIGN TO "dbg1.dat"
               ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  DFILE.
       01  DREC            PIC X(20).
       WORKING-STORAGE SECTION.
       01  CNT             PIC 99 VALUE 0.
       01  TOTAL           PIC 9(4) VALUE 0.
       01  OTHER-COUNT     PIC 9(4) VALUE 0.
       01  TBL.
           05  ELEM        PIC X(3) OCCURS 5 TIMES INDEXED BY IX.
       01  MATRIX.
           05  ROW         OCCURS 3 TIMES.
               10  CELL    PIC 9 OCCURS 4 TIMES.
       01  GRP.
           05  G-A         PIC X(4) VALUE "AAAA".
           05  G-B         PIC X(4) VALUE "BBBB".
       01  WS-EOF          PIC X VALUE "N".
       01  R               PIC 9.
       01  C               PIC 9.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D-PROC SECTION.
           USE FOR DEBUGGING ON START-UP LOOP-PARA SWITCHABLE FINISH.
       D-PROC-1.
           DISPLAY "PROC " DEBUG-NAME (1:12) " [" DEBUG-CONTENTS (1:20)
               "]".
       D-DATA SECTION.
           USE FOR DEBUGGING ON ALL REFERENCES OF TOTAL CNT
               G-A OF GRP.
       D-DATA-1.
           DISPLAY "DATA " DEBUG-NAME (1:12) " [" DEBUG-CONTENTS (1:6)
               "]".
       D-TABLE SECTION.
           USE FOR DEBUGGING ON ELEM CELL.
       D-TABLE-1.
           DISPLAY "ELEM " DEBUG-NAME (1:12) " [" DEBUG-CONTENTS (1:3)
               "] [" DEBUG-ITEM (39:11) "]".
       D-FILE SECTION.
           USE FOR DEBUGGING ON DFILE.
       D-FILE-1.
           DISPLAY "FILE " DEBUG-NAME (1:12) " [" DEBUG-CONTENTS (1:20)
               "]".
       END DECLARATIVES.
       MAIN SECTION.
       START-UP.
           DISPLAY "start".
      D    DISPLAY "debugging line".
           PERFORM LOOP-PARA 2 TIMES.
           ALTER SWITCHABLE TO PROCEED TO AFTER-SWITCH.
           GO TO SWITCHABLE.
       LOOP-PARA.
           ADD 1 TO OTHER-COUNT.
       SWITCHABLE.
           GO TO LOOP-PARA.
       AFTER-SWITCH.
           MOVE 5 TO TOTAL.
           MOVE TOTAL TO CNT.
           ADD CNT TO TOTAL.
           IF TOTAL > 9
               DISPLAY "total " TOTAL.
           MOVE CNT TO TOTAL.
           PERFORM VARYING CNT FROM 1 BY 1 UNTIL CNT > 2
               SET IX TO CNT
               MOVE "XY" TO ELEM (IX)
           END-PERFORM.
           MOVE ELEM (2) TO G-B.
           MOVE 2 TO R.
           MOVE 3 TO C.
           MOVE 7 TO CELL (R, C).
           ADD CELL (R, C) TO OTHER-COUNT.
           MOVE "1234" TO G-A OF GRP.
           MOVE G-B TO G-A.
           MOVE SPACES TO GRP.
           OPEN OUTPUT DFILE.
           MOVE "first record" TO DREC.
           WRITE DREC.
           MOVE "second record" TO DREC.
           WRITE DREC.
           CLOSE DFILE.
           OPEN INPUT DFILE.
           PERFORM UNTIL WS-EOF = "Y"
               READ DFILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END DISPLAY "read " DREC
               END-READ
           END-PERFORM.
           CLOSE DFILE.
       FINISH.
           DISPLAY "end".
           STOP RUN.
