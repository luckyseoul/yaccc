      * COB_LS_FIXED (the .env sets it): LINE SEQUENTIAL records are
      * written at their full length, trailing spaces kept
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LSFIXED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "fixed.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(10).
       WORKING-STORAGE SECTION.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           MOVE "AB" TO R.
           WRITE R.
           MOVE SPACES TO R.
           WRITE R.
           MOVE "1234567890" TO R.
           WRITE R.
           CLOSE F.
           OPEN INPUT F.
           PERFORM UNTIL EOF-FLAG = "Y"
               READ F AT END MOVE "Y" TO EOF-FLAG
                 NOT AT END DISPLAY "[" R "]"
               END-READ
           END-PERFORM.
           CLOSE F.
           STOP RUN.
