       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTER1.
      * ALTER of a GO TO paragraph, including GO TO without an operand.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N         PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SW THRU SW-EXIT 3 TIMES.
           ALTER BLANK-GO TO PROCEED TO DONE.
           GO TO BLANK-GO.
       SW.
           ADD 1 TO N.
       SW-GO.
           GO TO FIRST-TIME.
       FIRST-TIME.
           DISPLAY "first " N.
           ALTER SW-GO TO PROCEED TO LATER.
           GO TO SW-EXIT.
       LATER.
           DISPLAY "later " N.
       SW-EXIT.
           EXIT.
       BLANK-GO.
           GO TO.
       DONE.
           DISPLAY "done".
           STOP RUN.
