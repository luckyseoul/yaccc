       IDENTIFICATION DIVISION.
       PROGRAM-ID. notrunc1.
      * -std=ibm (binary-truncate off): the PICTURE's decimal point is not
      * printed on a scaled item, but the item's value still has its scale:
      * comparisons and arithmetic see 1.23, DISPLAY shows 00123.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  D PIC S9(3)V99 VALUE 1.23.
       01  P PIC S9(3)V99 COMP-3 VALUE 1.23.
       01  B PIC S9(3)V99 COMP VALUE 1.23.
       01  R PIC S9(9)V99.
       01  X PIC X(8).
       PROCEDURE DIVISION.
           MOVE D TO R
           DISPLAY "D->R [" R "]"
           MOVE P TO R
           DISPLAY "P->R [" R "]"
           MOVE B TO R
           DISPLAY "B->R [" R "]"
           DISPLAY "D    [" D "]"
           DISPLAY "P    [" P "]"
           DISPLAY "B    [" B "]"
           MOVE D TO X
           DISPLAY "text [" X "]"
           IF D = 1.23
              DISPLAY "cmp  1.23 yes"
           ELSE
              DISPLAY "cmp  1.23 no"
           END-IF
           IF D = 123
              DISPLAY "cmp   123 yes"
           ELSE
              DISPLAY "cmp   123 no"
           END-IF
           COMPUTE R = D + P + B
           DISPLAY "sum  [" R "]"
           MOVE 12 TO D
           DISPLAY "D=12 [" D "]"
           STOP RUN.
