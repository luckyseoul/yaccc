       IDENTIFICATION DIVISION.
       PROGRAM-ID. B1ARITH.
      *> fixed-point arithmetic in a tight loop
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC S9(9)V99 COMP-3 VALUE 1.
       01 B PIC S9(9)V99 COMP-3 VALUE 3.
       01 C PIC S9(9)V99 COMP-3.
       01 I PIC 9(9) COMP.
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3000000
               COMPUTE C = (A * B) / 7 + I
               ADD 1 TO A
           END-PERFORM
           DISPLAY C.
           STOP RUN.
