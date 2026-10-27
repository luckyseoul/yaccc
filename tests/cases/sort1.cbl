       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORT1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "unsorted.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "sorted.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SORT-WORK ASSIGN TO "sortwork".
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC.
          05 IN-DEPT      PIC X(4).
          05 IN-NAME      PIC X(10).
          05 IN-SAL       PIC 9(6).
       FD OUT-FILE.
       01 OUT-REC         PIC X(20).
       SD SORT-WORK.
       01 SORT-REC.
          05 SR-DEPT      PIC X(4).
          05 SR-NAME      PIC X(10).
          05 SR-SAL       PIC 9(6).
       WORKING-STORAGE SECTION.
       01 EOF-SW          PIC X VALUE "N".
          88 EOF          VALUE "Y".
       01 I               PIC 99.
       01 DATA-TBL.
          05 FILLER PIC X(20) VALUE "ENG ZOE       085000".
          05 FILLER PIC X(20) VALUE "SALEBOB       062000".
          05 FILLER PIC X(20) VALUE "ENG ADAM      091000".
          05 FILLER PIC X(20) VALUE "OPS CARL      050000".
          05 FILLER PIC X(20) VALUE "SALEAMY       071000".
          05 FILLER PIC X(20) VALUE "ENG BETH      085000".
          05 FILLER PIC X(20) VALUE "OPS DORA      055000".
       01 DATA-R REDEFINES DATA-TBL.
          05 DR PIC X(20) OCCURS 7 TIMES.
       01 TOT             PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
           OPEN OUTPUT IN-FILE.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 7
               WRITE IN-REC FROM DR(I)
           END-PERFORM.
           CLOSE IN-FILE.
           SORT SORT-WORK
               ON ASCENDING KEY SR-DEPT
               ON DESCENDING KEY SR-SAL
               ON ASCENDING KEY SR-NAME
               USING IN-FILE
               GIVING OUT-FILE.
           OPEN INPUT OUT-FILE.
           PERFORM UNTIL EOF
               READ OUT-FILE AT END SET EOF TO TRUE
                   NOT AT END DISPLAY "SORTED: " OUT-REC
               END-READ
           END-PERFORM.
           CLOSE OUT-FILE.
           SORT SORT-WORK ON ASCENDING KEY SR-NAME
               INPUT PROCEDURE IS LOAD-HIGH-PAID
               OUTPUT PROCEDURE IS PRINT-SORTED.
           DISPLAY "TOTAL HIGH PAID: " TOT.
           STOP RUN.
       LOAD-HIGH-PAID SECTION.
       LHP-1.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 7
               MOVE DR(I) TO SORT-REC
               IF SR-SAL > 60000
                   RELEASE SORT-REC
               END-IF
           END-PERFORM.
       PRINT-SORTED SECTION.
       PS-1.
           MOVE "N" TO EOF-SW.
           PERFORM UNTIL EOF
               RETURN SORT-WORK
                   AT END SET EOF TO TRUE
                   NOT AT END
                       DISPLAY "PROC: " SR-NAME " " SR-SAL
                       ADD SR-SAL TO TOT
               END-RETURN
           END-PERFORM.
