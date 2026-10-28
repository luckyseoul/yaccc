      *> the size error condition exists even without ON SIZE ERROR, and the
      *> exception facility reports it. Values are GnuCOBOL's (testsuite
      *> run_misc.at:6210, :12248 and :12291).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXCEPT2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X  PIC 9.
       01  A  PIC 9 VALUE 5.
       01  B  PIC 9 VALUE 0.
       01  C  PIC 9.
       PROCEDURE DIVISION.
      *> overflow: 10 does not fit PIC 9. The value still stores truncated,
      *> and the exception is the one that was raised.
           COMPUTE X = 10
           DISPLAY "OVERFLOW-STATUS:   " FUNCTION TRIM(FUNCTION EXCEPTION-STATUS)
           DISPLAY "OVERFLOW-LOCATION: " FUNCTION TRIM(FUNCTION EXCEPTION-LOCATION)
           DISPLAY "OVERFLOW-VALUE:    " X.
      *> SET LAST EXCEPTION TO OFF clears it
           SET LAST EXCEPTION TO OFF
           DISPLAY "CLEARED-STATUS:   [" FUNCTION TRIM(FUNCTION EXCEPTION-STATUS) "]".
      *> division by zero is its own condition
           COMPUTE C = A / B
           DISPLAY "DIVZERO-STATUS:    " FUNCTION TRIM(FUNCTION EXCEPTION-STATUS).
      *> and ON SIZE ERROR still suppresses the store, as it must
           MOVE 5 TO X
           COMPUTE X = 10 ON SIZE ERROR CONTINUE END-COMPUTE
           DISPLAY "AFTER-ON-SIZE-ERROR: " X.
           STOP RUN.
