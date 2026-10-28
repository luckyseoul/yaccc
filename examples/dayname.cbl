       IDENTIFICATION DIVISION.
       PROGRAM-ID. DAYNAME.
      * Two-file example: this main program CALLs DATEINFO, which is
      * compiled from datefmt.cbl into the same executable:
      *     ./yaccc examples/dayname.cbl examples/datefmt.cbl --run
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DATES.
           05  FILLER        PIC 9(8) VALUE 19690720.
           05  FILLER        PIC 9(8) VALUE 19860128.
           05  FILLER        PIC 9(8) VALUE 20000101.
           05  FILLER        PIC 9(8) VALUE 20261027.
       01  DATE-TABLE REDEFINES DATES.
           05  A-DATE        PIC 9(8) OCCURS 4 TIMES INDEXED BY DX.
       01  RESULT.
           05  R-WEEKDAY     PIC X(9).
           05  R-DAY-OF-YEAR PIC 999.
       PROCEDURE DIVISION.
           PERFORM VARYING DX FROM 1 BY 1 UNTIL DX > 4
               CALL "DATEINFO" USING A-DATE (DX) RESULT
               DISPLAY A-DATE (DX) " was a " R-WEEKDAY
                       " (day " R-DAY-OF-YEAR " of the year)"
           END-PERFORM
           STOP RUN.
