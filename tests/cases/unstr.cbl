      *> UNSTRING with a literal or figurative sending item: the standard
      *> names an identifier, but GnuCOBOL, Micro Focus and IBM all accept a
      *> literal, and programs use it
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSTR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  B PIC X(10).
       01  C PIC X(10).
       01  D PIC X(10).
       01  PTR PIC 99 VALUE 1.
       01  CNT PIC 99.
       PROCEDURE DIVISION.
           UNSTRING "data" INTO B.
           DISPLAY "LITERAL:   [" B "]".
           UNSTRING "a,b,c" DELIMITED BY "," INTO B C D.
           DISPLAY "DELIMITED: [" B "][" C "][" D "]".
           MOVE SPACES TO B C.
           UNSTRING SPACES INTO B.
           DISPLAY "FIGURATIVE:[" B "]".
           UNSTRING "x|y" DELIMITED BY "|" INTO B COUNT IN CNT
               WITH POINTER PTR.
           DISPLAY "COUNT:     " CNT.
           UNSTRING "lone" INTO B
               ON OVERFLOW DISPLAY "OVERFLOW (should not happen)"
               NOT ON OVERFLOW DISPLAY "NO OVERFLOW".
           STOP RUN.
