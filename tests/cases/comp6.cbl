      *> COMP-6: packed decimal with no sign nibble, so every nibble is a
      *> digit and PIC 99 COMP-6 occupies one byte rather than two.
      *> Expected values are GnuCOBOL's (testsuite data_packed.at:606-760).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMP6.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X-99         PIC 99  USAGE COMP-6.
       01  X-999        PIC 999 USAGE COMP-6.
       01  B-99         USAGE BINARY-LONG UNSIGNED.
       01  BAD-2        PIC 99  USAGE COMP-6.
       PROCEDURE DIVISION.
           DISPLAY "SIZE: " LENGTH OF X-99 " " LENGTH OF X-999.
           MOVE 0 TO X-99
           DISPLAY "ZERO: " X-99.
           MOVE 99 TO X-99
           DISPLAY "MAX:  " X-99.
           MOVE 0 TO X-999
           DISPLAY "ZERO: " X-999.
           MOVE 123 TO X-999
           DISPLAY "VALUE:" X-999.
      *> reading back through arithmetic, not just DISPLAY
           MOVE 99 TO B-99
           ADD X-99 X-999 GIVING B-99
           DISPLAY "SUM:  " B-99.
      *> every nibble must be a digit for IS NUMERIC
           MOVE X"0012" TO BAD-2
           IF BAD-2 IS NUMERIC
               DISPLAY "AA IS NUMERIC"
           ELSE
               DISPLAY "AA IS NOT NUMERIC"
           END-IF.
           MOVE X"9999" TO BAD-2
           IF BAD-2 IS NUMERIC
               DISPLAY "99 IS NUMERIC"
           ELSE
               DISPLAY "99 IS NOT NUMERIC"
           END-IF.
           STOP RUN.
