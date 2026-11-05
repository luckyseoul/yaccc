      * COB_LS_NULLS (the .env sets it): a character below space in a
      * LINE SEQUENTIAL record is written after a NUL and read back,
      * a newline in the record among them
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LSNULLS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "nulls.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(12).
       WORKING-STORAGE SECTION.
       01 I PIC 99.
       01 N PIC 999.
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           MOVE X"410A0D011F7F80FF1B0C0942" TO R.
           WRITE R.
           MOVE "PLAIN" TO R.
           WRITE R.
           CLOSE F.
           OPEN INPUT F.
           READ F.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 12
               COMPUTE N = FUNCTION ORD (R (I:1)) - 1
               DISPLAY N " " WITH NO ADVANCING
           END-PERFORM.
           DISPLAY " ".
           READ F.
           DISPLAY "[" R "]".
           CLOSE F.
           STOP RUN.
