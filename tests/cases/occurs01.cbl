      *> an 01 entry may itself have OCCURS: every occurrence needs storage.
      *> Each of these used to be allocated as a single occurrence, so writing
      *> to the last one overran the buffer.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OCCURS01.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  TOP-TABLE PIC X OCCURS 7 TIMES.
       01  TOP-NUM PIC 9(2) OCCURS 7 TIMES.
       01  GROUPED.
           05  G-TEXT PIC X(3) OCCURS 5 TIMES.
       01  I PIC 99.
       PROCEDURE DIVISION.
           MOVE "Z" TO TOP-TABLE(7).
           DISPLAY "TOP LAST=[" TOP-TABLE(7) "] FIRST=[" TOP-TABLE(1) "]".
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 7
               MOVE I TO TOP-NUM(I)
           END-PERFORM
           DISPLAY "TOP-NUM(1)=" TOP-NUM(1) " (7)=" TOP-NUM(7).
           MOVE "AB" TO G-TEXT(5).
           DISPLAY "G-TEXT(5)=[" G-TEXT(5) "] (1)=[" G-TEXT(1) "]".
           STOP RUN.
