      * SPDX-License-Identifier: MIT
      * Keys that end an ACCEPT, with COB_SCREEN_EXCEPTIONS and
      * COB_SCREEN_ESC set: Page Up, Page Down, Up in the first field,
      * Escape and F10; ACCEPT FROM ESCAPE KEY; FULL and PROMPT; a group
      * displayed on its own; a colour from a data item; BLANK LINE and
      * ERASE EOS.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRKEYS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY    PIC 9(4).
       01 WS-F      PIC X(3) VALUE SPACES.
       01 WS-G      PIC X(4) VALUE SPACES.
       01 WS-COLOUR PIC 9 VALUE 3.
       01 WS-I      PIC 9.
       01 WS-LINE   PIC X(40).
       SCREEN SECTION.
       01 SCR.
          05 HEAD LINE 1 COL 1.
             10 VALUE "Keys" FOREGROUND-COLOR WS-COLOUR.
             10 VALUE " test" COL PLUS 1.
          05 BODY.
             10 LINE 3 COL 1 VALUE "Full:".
             10 LINE 3 COL 7 PIC X(3) TO WS-F FULL.
             10 LINE 4 COL 1 VALUE "Prompt:".
             10 LINE 4 COL 9 PIC X(4) TO WS-G PROMPT CHARACTER IS ".".
       PROCEDURE DIVISION.
           DISPLAY "will be blanked" AT 2001
           DISPLAY "erased from here" AT 2201
           DISPLAY "and below" AT 2301
           DISPLAY HEAD
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 6
               ACCEPT BODY
               ACCEPT WS-KEY FROM ESCAPE KEY
               STRING "key " WS-KEY " F=[" WS-F "] G=[" WS-G "]"
                   DELIMITED BY SIZE INTO WS-LINE
               DISPLAY WS-LINE AT LINE WS-I COL 30
           END-PERFORM
           DISPLAY "line blanked" AT 2001 WITH BLANK LINE
           DISPLAY " " AT 2210 WITH ERASE EOS
           STOP RUN.
