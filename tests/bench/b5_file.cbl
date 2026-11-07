       IDENTIFICATION DIVISION.
       PROGRAM-ID. B5FILE.
      *> sequential file: write then read back 500000 records
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "bench.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R.
          05 K PIC 9(8).
          05 V PIC X(24).
       WORKING-STORAGE SECTION.
       01 I PIC 9(8) COMP.
       01 N PIC 9(9) COMP VALUE 0.
       PROCEDURE DIVISION.
           OPEN OUTPUT F
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 500000
               MOVE I TO K
               MOVE "ABCDEFGHIJKLMNOPQRSTUVWX" TO V
               WRITE R
           END-PERFORM
           CLOSE F
           OPEN INPUT F
           PERFORM UNTIL 1 = 2
               READ F AT END EXIT PERFORM END-READ
               ADD 1 TO N
           END-PERFORM
           CLOSE F
           DISPLAY N.
           STOP RUN.
