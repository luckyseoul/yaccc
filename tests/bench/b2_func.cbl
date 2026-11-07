       IDENTIFICATION DIVISION.
       PROGRAM-ID. B2FUNC.
      *> intrinsic functions, transcending the integer fast paths
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X COMP-2 VALUE 2.
       01 Y COMP-2.
       01 I PIC 9(9) COMP.
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 300000
               COMPUTE Y = FUNCTION SQRT(X) + FUNCTION SIN(X)
                         + FUNCTION EXP(X / 1000)
               ADD 0.000001 TO X
           END-PERFORM
           DISPLAY Y.
           STOP RUN.
