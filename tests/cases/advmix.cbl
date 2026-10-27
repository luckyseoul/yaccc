       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADVMIX.
      * A default WRITE after WRITE ... AFTER ADVANCING starts a new
      * line (ISO default AFTER ADVANCING 1) instead of joining lines.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO "mix.txt" ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F1. 01 R1 PIC X(10).
       WORKING-STORAGE SECTION.
       01 EOF PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN OUTPUT F1.
           MOVE "HEADER" TO R1. WRITE R1.
           MOVE "TITLE" TO R1. WRITE R1 AFTER ADVANCING 2 LINES.
           MOVE "DETAIL1" TO R1. WRITE R1.
           MOVE "DETAIL2" TO R1. WRITE R1.
           MOVE "FOOT" TO R1. WRITE R1 AFTER ADVANCING 1 LINE.
           MOVE "END" TO R1. WRITE R1 BEFORE ADVANCING 1 LINE.
           CLOSE F1.
           OPEN INPUT F1.
           PERFORM UNTIL EOF = "Y"
               READ F1 AT END MOVE "Y" TO EOF
                   NOT AT END DISPLAY "[" R1 "]"
               END-READ
           END-PERFORM.
           CLOSE F1.
           STOP RUN.
