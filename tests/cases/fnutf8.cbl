      *> COBOL 2023 / Enterprise COBOL 6.4 functions: HEX-TO-CHAR,
      *> BIT-OF, BIT-TO-CHAR, UUID4, and the UTF-8 functions ULENGTH,
      *> UPOS, UWIDTH, USUBSTR, UVALID, USUPPLEMENTARY. GnuCOBOL 3.1 has
      *> none of them: the expected output is checked by hand.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FNUTF8.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *> "naive" with i-diaeresis, a euro sign and an emoji, in UTF-8
       01 U    PIC X(20) VALUE X"6E61C3AF766520E282AC20F09F988021".
       01 BAD  PIC X(6) VALUE X"41C328424344".
       01 ID1  PIC X(36).
       01 ID2  PIC X(36).
       01 H    PIC X(8) VALUE "414243".
       PROCEDURE DIVISION.
           DISPLAY "ULENGTH " FUNCTION ULENGTH(U)
           DISPLAY "ULENGTH TRIM " FUNCTION ULENGTH(FUNCTION TRIM(U))
           DISPLAY "UPOS 3 " FUNCTION UPOS(U 3) " 4 " FUNCTION UPOS(U 4)
           DISPLAY "UPOS 0 " FUNCTION UPOS(U 0) " 99 "
               FUNCTION UPOS(U 99)
           DISPLAY "UWIDTH " FUNCTION UWIDTH(U 3) " "
               FUNCTION UWIDTH(U 7) " " FUNCTION UWIDTH(U 9) " "
               FUNCTION UWIDTH(U 99)
           DISPLAY "USUBSTR [" FUNCTION HEX-OF(FUNCTION USUBSTR(U 7 3))
               "]"
           DISPLAY "USUBSTR to the end [" FUNCTION USUBSTR(U 10) "]"
           DISPLAY "UVALID " FUNCTION UVALID(U) " "
               FUNCTION UVALID(BAD)
           DISPLAY "USUPPLEMENTARY " FUNCTION USUPPLEMENTARY(U) " "
               FUNCTION USUPPLEMENTARY(BAD)
           MOVE FUNCTION UUID4 TO ID1
           MOVE FUNCTION UUID4 TO ID2
           DISPLAY "UUID4 " FUNCTION LENGTH(FUNCTION UUID4) " "
               ID1(9:1) ID1(14:1) ID1(15:1) ID1(19:1) ID1(24:1)
           IF ID1 NOT = ID2
               DISPLAY "two UUID4 differ"
           END-IF
           IF FUNCTION LOWER-CASE(ID1) = ID1
               DISPLAY "UUID4 is lower case"
           END-IF
           DISPLAY "HEX-TO-CHAR [" FUNCTION HEX-TO-CHAR(H) "]"
           DISPLAY "BIT-OF " FUNCTION BIT-OF("AB")
           DISPLAY "BIT-TO-CHAR [" FUNCTION BIT-TO-CHAR("0100000101000010")
               "]"
           DISPLAY "round trip [" FUNCTION HEX-TO-CHAR(
               FUNCTION HEX-OF("xyz")) "]"
           STOP RUN.
