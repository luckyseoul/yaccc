       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENTRYGOTO.
      *> ENTRY FOR GO TO marks a point inside the procedure that a
      *> GO TO ENTRY can jump to, and GO TO ENTRY ... DEPENDING ON picks one
      *> by number. A vendor extension; the case is limited to the behaviour
      *> both references agree on, which is jumping forward and falling
      *> through, not jumping into the middle of a PERFORM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WHICH   PIC 9 VALUE 1.
       01 COUNTED PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           GO TO ENTRY 'B' 'C' DEPENDING ON WHICH.
           DISPLAY "FELL THROUGH".
           GOBACK.
       ENTRY FOR GO TO 'B'.
           DISPLAY "AT B".
           ADD 1 TO COUNTED.
           IF COUNTED < 2
               GO TO ENTRY 'C'.
       ENTRY FOR GO TO 'C'.
           DISPLAY "AT C".
           ADD 1 TO WHICH.
           IF WHICH < 4
               GO TO MAIN.
           DISPLAY "DONE".
           GOBACK.
