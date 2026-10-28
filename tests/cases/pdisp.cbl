       IDENTIFICATION DIVISION.
       PROGRAM-ID. PDISP.
      * DISPLAY of items with P scaling to the right of the point.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A         PIC VP9 VALUE .05.
       01  B         PIC SVPP99 VALUE -.00012.
       01  C         PIC VPPP9 COMP VALUE .0007.
       01  D         PIC SVP9 COMP-3 VALUE -.09.
       01  W         PIC 9V9(5).
       PROCEDURE DIVISION.
           DISPLAY "[" A "][" B "][" C "][" D "]".
           COMPUTE A = A * 1.8.
           SUBTRACT .0004 FROM C.
           MOVE B TO W.
           DISPLAY "[" A "][" C "][" W "]".
           STOP RUN.
