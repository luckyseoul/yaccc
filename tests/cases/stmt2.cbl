      *> statements that had no implementation: PERFORM FOREVER and
      *> INSPECT ... REPLACING TRAILING. The expected values are GnuCOBOL's
      *> (testsuite run_misc.at:1825 and the PERFORM FOREVER tests).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STMT2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  I        PIC 99 VALUE 0.
       01  X        PIC X(4) VALUE "1000".
       01  Y        PIC X(12) VALUE "AAABBCDCCCCC".
       01  Z        PIC X(6) VALUE "ABABAB".
       01  N        PIC 99 VALUE 0.
       PROCEDURE DIVISION.
      *> inline PERFORM FOREVER: only EXIT PERFORM leaves it
           PERFORM FOREVER
               ADD 1 TO I
               IF I = 2
                   EXIT PERFORM CYCLE
               END-IF
               IF I > 4
                   EXIT PERFORM
               END-IF
           END-PERFORM.
           DISPLAY "FOREVER:        " I.
      *> INSPECT REPLACING TRAILING: the maximal run at the end
           INSPECT X REPLACING TRAILING ZEROS BY SPACES.
           DISPLAY "TRAILING ZEROS: [" X "]".
      *> mixed ALL and TRAILING in one statement
           INSPECT Y REPLACING
               ALL      "A" BY "Z"
                        "B" BY "Y"
               TRAILING "C" BY "X".
           DISPLAY "MIXED:          [" Y "]".
      *> TALLYING FOR TRAILING counts the maximal run
           INSPECT Z TALLYING N FOR TRAILING "AB".
           DISPLAY "TRAILING TALLY: " N.
           STOP RUN.
