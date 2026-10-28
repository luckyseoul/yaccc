      *> FUNCTION CONTENT-LENGTH and CONTENT-OF read the bytes a POINTER
      *> addresses, up to the NUL that Z"..." literals end with. Behaviour per
      *> GnuCOBOL (testsuite run_functions.at:350 and :384).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONTENT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  P        USAGE POINTER.
       01  X        PIC X(4) VALUE Z"ABC".
       01  LEN      PIC 9(4).
       01  B        PIC X(10) BASED.
       PROCEDURE DIVISION.
      *> a null pointer has no content
           MOVE FUNCTION CONTENT-LENGTH(P) TO LEN
           DISPLAY "NULL LENGTH=" LEN.
      *> and asking for its content raises EC-DATA-PTR-NULL
           DISPLAY "NULL CONTENT=[" FUNCTION CONTENT-OF(P) "] "
                   FUNCTION TRIM(FUNCTION EXCEPTION-STATUS).
           SET P TO ADDRESS OF X
           MOVE FUNCTION CONTENT-LENGTH(P) TO LEN
           DISPLAY "LENGTH=" LEN.
           DISPLAY "ALL=[" FUNCTION CONTENT-OF(P) "]".
           DISPLAY "FIRST2=[" FUNCTION CONTENT-OF(P, 2) "]".
      *> a successful call leaves no exception behind
           DISPLAY "STATUS=[" FUNCTION TRIM(FUNCTION EXCEPTION-STATUS) "]".
      *> storage allocated by ALLOCATE is zeroed by INITIALIZED
           ALLOCATE B INITIALIZED
           SET P TO ADDRESS OF B
           DISPLAY "BASED=[" FUNCTION CONTENT-OF(P, 1) "]".
           FREE B.
           STOP RUN.
