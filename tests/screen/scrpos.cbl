      * SPDX-License-Identifier: MIT
      * DISPLAY of several operands, each with its own position, SIZE
      * and attributes; LINE and COLUMN zero (relative to the last
      * DISPLAY); LOW-VALUE, SPACE, ALL X"01" and ALL X"02"; text past
      * the right margin; the positions a group's LINE and COLUMN give
      * the items under it; an item of a screen displayed by itself;
      * ACUCOBOL's COLOR, from a literal and from a data item.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRPOS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N    PIC 9(5) VALUE 12345.
       01 WS-X    PIC X(10) VALUE "abcdefghij".
       01 WS-FOUR PIC 9 VALUE 4.
       01 WS-COLOR PIC 9(5) VALUE 8195.
       SCREEN SECTION.
       01 SCR-G.
          03 LINE 14 COL 10 VALUE "A".
          03 G1 COL 20.
             05 VALUE "B".
             05 COL + 2 VALUE "C".
          03 G2 LINE 15.
             05 VALUE "D".
          03 G3 COL + 3.
             05 COL + 0 VALUE "E".
          03 G4 LINE 16 COL 30.
             05 G5 LINE 17.
                07 VALUE "F".
       01 SCR-H LINE 19 COL 20.
          03 VALUE "H".
          03 COL + 2 VALUE "I".
       01 SCR-P.
          03 LINE 20 COL 40 VALUE "P1".
          03 P2 COL + 3 VALUE "P2" COLOR WS-COLOR.
       PROCEDURE DIVISION.
      *    ALL X"02" erases the screen
           DISPLAY "gone" AT 2401
           DISPLAY ALL X"02" UPON CRT
      *    several operands, each with its own phrases
           DISPLAY "one" AT 0101 "two" AT 0110 HIGHLIGHT "three"
           DISPLAY "A1" LINE 2 COL 1 "B2" REVERSE-VIDEO
                   "C3" LINE 2 COL 20 "D4" OVERLINE
      *    LINE 0: the line after the last; COLUMN 0: the column after
           DISPLAY "x" LINE 0 COL 5
           DISPLAY "y" LINE 3 COL 0
      *    neither: right after the last
           DISPLAY "z" UPON CRT
      *    SIZE cuts and pads; a figurative constant is repeated
           DISPLAY WS-N AT 0501 SIZE 3 "|" WS-X SIZE 12 "|"
           DISPLAY ALL "-=" AT 0601 SIZE 7 QUOTE SIZE 3
                   ZERO SIZE WS-FOUR
      *    past the right margin: on at the start of the next line
           DISPLAY "wrap-me" AT 0777
      *    COLOR 69: red (5) on blue (64)
           DISPLAY "acu" AT 0901 COLOR 69
      *    LOW-VALUE only positions; ALL X"01" erases to the end of line
           DISPLAY "keep this line" AT 1001
           DISPLAY "erase the rest of this" AT 1101
           DISPLAY LOW-VALUE AT 1004 "^"
           DISPLAY ALL X"01" AT 1106 "<"
      *    SPACE erases to the end of the screen
           DISPLAY "stays" AT 2101
           DISPLAY "will go" AT 2201
           DISPLAY "will go too" AT 2301
           DISPLAY SPACE AT 2203 "!"
      *    groups' positions; an item of a screen by itself
           DISPLAY SCR-G
           DISPLAY SCR-H
           DISPLAY P2
           STOP RUN.
