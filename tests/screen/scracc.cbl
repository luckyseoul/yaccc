      * SPDX-License-Identifier: MIT
      * ACCEPT of a screen: TO and USING fields, Tab and Back-tab,
      * Backspace, Delete, Home, End and Insert, SECURE, CRT STATUS
      * and CURSOR, a function key and ON EXCEPTION; ACCEPT of items AT
      * a position with AUTO, UPDATE and REQUIRED.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRACC.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CRT STATUS IS WS-CRT
           CURSOR IS WS-CURSOR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CRT    PIC 9(4) VALUE 0.
       01 WS-CURSOR PIC 9(4) VALUE 0.
       01 WS-A      PIC X(6) VALUE SPACES.
       01 WS-B      PIC 9(4) VALUE 12.
       01 WS-C      PIC X(4) VALUE "ab".
       01 WS-CODE   PIC X(3) VALUE SPACES.
       01 WS-NUM    PIC S9(5) COMP VALUE 42.
       01 WS-REQ    PIC X(4) VALUE SPACES.
       01 WS-LINE   PIC X(78).
       SCREEN SECTION.
       01 SCR.
          05 LINE 2 COL 2 VALUE "A:".
          05 LINE 2 COL 5 PIC X(6) TO WS-A.
          05 LINE 3 COL 2 VALUE "B:".
          05 LINE 3 COL 5 PIC 9(4) USING WS-B.
          05 LINE 4 COL 2 VALUE "C:".
          05 LINE 4 COL 5 PIC X(4) USING WS-C SECURE.
       PROCEDURE DIVISION.
           DISPLAY SCR
      *    xy, Tab, 7, Tab, Back-tab, Tab, Z, Enter
           ACCEPT SCR
           STRING "A=[" WS-A "] B=[" WS-B "] C=[" WS-C "] CRT=" WS-CRT
               " CURSOR=" WS-CURSOR DELIMITED BY SIZE INTO WS-LINE
           DISPLAY WS-LINE AT 0601
      *    Home, abc, Left, Backspace, Insert, Q, End, F3
           MOVE SPACES TO WS-LINE
           ACCEPT SCR
               ON EXCEPTION
                   STRING "F-KEY " WS-CRT " C=[" WS-C "]"
                       DELIMITED BY SIZE INTO WS-LINE
               NOT ON EXCEPTION
                   MOVE "NO EXCEPTION" TO WS-LINE
           END-ACCEPT
           DISPLAY WS-LINE AT 0701
      *    AUTO: three characters end the ACCEPT
           ACCEPT WS-CODE AT 0901 WITH AUTO
           DISPLAY WS-CODE AT 0910
      *    UPDATE on a binary item: the value is there to be edited
           ACCEPT WS-NUM AT 1001 WITH UPDATE
           DISPLAY WS-NUM AT 1010
      *    REQUIRED: Enter on an empty field is refused
           ACCEPT WS-REQ AT 1101 WITH REQUIRED
           DISPLAY WS-REQ AT 1110
           STOP RUN.
