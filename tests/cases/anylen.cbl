      *> PIC X ANY LENGTH in LINKAGE: the calling program's argument decides
      *> the size, for LENGTH OF, MOVE and comparison alike.
      *> Expected values are GnuCOBOL's (testsuite run_misc.at:3972-4144).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANYLEN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  six    PIC X(6) VALUE "OKOKOK".
       01  two    PIC X(2) VALUE "OK".
       PROCEDURE DIVISION.
           CALL "ANYCALLEE" USING six.
           CALL "ANYCALLEE" USING two.
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANYCALLEE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  reported PIC 99.
       LINKAGE SECTION.
       01  arg    PIC X ANY LENGTH.
       PROCEDURE DIVISION USING arg.
           MOVE LENGTH OF arg TO reported.
           DISPLAY "LENGTH=" reported.
      *> a 20-character comparison must not stop at the first character
           IF arg = "OKOKOK"
               DISPLAY "MATCHES OKOKOK"
           ELSE
               DISPLAY "DIFFERS"
           END-IF.
           EXIT PROGRAM.
       END PROGRAM ANYCALLEE.
       END PROGRAM ANYLEN.
