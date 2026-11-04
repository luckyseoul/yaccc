      * SPDX-License-Identifier: MIT
      * ACCEPT: INITIAL picks the field an ACCEPT starts in; CRT STATUS
      * and CURSOR declared with IS SPECIAL-NAMES; BLANK LINE is for
      * DISPLAY only; TIMEOUT; SIZE edits the first characters of a
      * field; Alt-Delete clears to the end of the field; Shift-F1.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRTIME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STAT PIC 9(4) IS SPECIAL-NAMES CRT STATUS.
       01 WS-CUR  PIC 9(4) IS SPECIAL-NAMES CURSOR.
       01 WS-A    PIC X(5).
       01 WS-B    PIC X(5).
       01 WS-C    PIC X(10) VALUE "abcdefghij".
       SCREEN SECTION.
       01 SCR.
          03 LINE 2 COL 1 VALUE "A:".
          03 COL + 2 PIC X(5) TO WS-A.
          03 LINE 3 COL 1 VALUE "B:".
          03 COL + 2 PIC X(5) TO WS-B INITIAL.
          03 LINE 4 COL 1 VALUE "kept" BLANK LINE.
       PROCEDURE DIVISION.
      *    the DISPLAY of SCR blanks line 4; its ACCEPT doesn't
           DISPLAY "blanked" AT 0401
           DISPLAY SCR
           DISPLAY "stays" AT 0410
           ACCEPT SCR
           DISPLAY "A=[" AT 0701 WS-A "] B=[" WS-B "] " WS-STAT " "
                   WS-CUR
      *    nothing typed for a second: CRT STATUS 8001
           ACCEPT WS-A AT 0901 TIMEOUT 1
               ON EXCEPTION
                   DISPLAY "timeout " AT 0910 WS-STAT
           END-ACCEPT
      *    SIZE 4: the first four; Alt-Delete clears the rest of them
           ACCEPT WS-C AT 1101 WITH UPDATE SIZE 4
           DISPLAY "C=[" AT 1201 WS-C "]"
      *    Shift-F1 is F13
           ACCEPT WS-A AT 1401
           DISPLAY "key " AT 1501 WS-STAT
           STOP RUN.
