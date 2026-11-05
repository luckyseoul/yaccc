      * Variable-length SEQUENTIAL records: each after a header that
      * holds its length, in GnuCOBOL's format (two bytes big-endian and
      * two zero bytes), so either compiler reads what the other wrote
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARSEQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "var.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F RECORD VARYING FROM 1 TO 20 DEPENDING ON L.
       01 R PIC X(20).
       WORKING-STORAGE SECTION.
       01 L PIC 99.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN OUTPUT F.
           MOVE "ABC" TO R. MOVE 3 TO L. WRITE R.
           MOVE "DEFGHIJ" TO R. MOVE 7 TO L. WRITE R.
           MOVE "KLMNOPQRSTUVWXYZ0123" TO R. MOVE 20 TO L. WRITE R.
           CLOSE F.
           OPEN EXTEND F.
           MOVE "END" TO R. MOVE 3 TO L. WRITE R.
           CLOSE F.
           OPEN INPUT F.
           PERFORM UNTIL EOF-FLAG = "Y"
               READ F AT END MOVE "Y" TO EOF-FLAG
                 NOT AT END DISPLAY L " [" R (1:L) "]"
               END-READ
           END-PERFORM.
           CLOSE F.
           STOP RUN.
