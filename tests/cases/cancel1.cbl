       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCEL1.
      * CANCEL by literal and by identifier resets the called program.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PNAME     PIC X(8) VALUE "COUNTER".
       PROCEDURE DIVISION.
           PERFORM 3 TIMES
               CALL "COUNTER"
           END-PERFORM
           CANCEL PNAME
           PERFORM 2 TIMES
               CALL PNAME
           END-PERFORM
           CANCEL "COUNTER"
           CALL "COUNTER"
           STOP RUN.
       END PROGRAM CANCEL1.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 C         PIC 99 VALUE 0.
       PROCEDURE DIVISION.
           ADD 1 TO C
           DISPLAY "count " C
           GOBACK.
       END PROGRAM COUNTER.
