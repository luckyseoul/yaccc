      * SPDX-License-Identifier: MIT
      * DISPLAY of screens: absolute and relative LINE and COLUMN, a
      * group's position, AT on a screen, literals and FROM fields with
      * editing, attributes and colours, BLANK SCREEN, ERASE EOL, and
      * DISPLAY of items AT a position.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRDISP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(10) VALUE "ALICE".
       01 WS-N    PIC S9(3)V9 VALUE -12.5.
       01 WS-AMT  PIC 9(5)V99 VALUE 1234.5.
       01 WS-T    PIC X(5) VALUE "HELLO".
       01 WS-L    PIC 99 VALUE 12.
       SCREEN SECTION.
       01 SCR-A BLANK SCREEN.
          05 LINE 1 COL 1 VALUE "Title" REVERSE-VIDEO.
          05 LINE 2 COL 3 VALUE "Name:" FOREGROUND-COLOR 2.
          05 LINE 2 COL 10 PIC X(10) FROM WS-NAME UNDERLINE.
          05 LINE 3 COL 3 PIC -ZZ9.9 FROM WS-N BACKGROUND-COLOR 4.
          05 LINE 4 COL 3 VALUE "Bright" HIGHLIGHT FOREGROUND-COLOR 6.
          05 VALUE "Next" COL PLUS 2.
          05 VALUE "Same".
          05 LINE 5 VALUE "line5-nocol".
          05 LINE PLUS 1 VALUE "plus1".
          05 COL 30 VALUE "col30".
          05 COL PLUS 3 PIC Z,ZZ9.99 FROM WS-AMT.
          05 LINE MINUS 2 COL 50 VALUE "minus2" BLINK.
          05 LINE WS-L COL 5 VALUE "line from item" LOWLIGHT.
       01 SCR-B.
          05 LINE 2 COL 2 VALUE "B-at".
          05 VALUE "B-next".
       01 SCR-C LINE 15 COL 20 HIGHLIGHT.
          05 VALUE "C1".
          05 LINE PLUS 1 VALUE "C2".
       PROCEDURE DIVISION.
           DISPLAY SCR-A
           DISPLAY SCR-B AT LINE 9 COL 10
           DISPLAY SCR-C
           DISPLAY WS-T AT 1720
           DISPLAY "LIT" AT LINE 18 COLUMN 5 WITH HIGHLIGHT
           DISPLAY WS-N LINE 19 COL 1
           DISPLAY "XXXXXXXXXX" AT 2001
           DISPLAY "erase" AT 2003 WITH ERASE EOL
           STOP RUN.
