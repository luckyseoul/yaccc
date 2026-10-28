       IDENTIFICATION DIVISION.
       PROGRAM-ID. fn2.
      * Function results as data items, high-precision math, NUMVAL
      * family, COBOL 2014 date functions.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC S9(4)V9(4) VALUE -1.2345.
       01 B PIC 9(3) VALUE 7.
       01 X PIC X(10) VALUE "hello".
       01 Z PIC S9V9(35).
       01 Z2 PIC S99V9(34).
       01 R PIC X(12).
       01 S PIC X(30).
       01 N PIC S9(9)V9(9).
       01 F1 PIC $**,**9.99BCR.
       01 F2 PIC S9(4) BINARY.
       PROCEDURE DIVISION.
           DISPLAY FUNCTION ABS(A) " " FUNCTION ABS(B) " "
                   FUNCTION ABS(-1.5)
           DISPLAY FUNCTION ORD(X) " " FUNCTION INTEGER(-1.5) " "
                   FUNCTION MOD(-11 3) " " FUNCTION SIGN(A)
           DISPLAY FUNCTION MAX(A B) " " FUNCTION MIN(1.5 2) " "
                   FUNCTION MEDIAN(1 2 4) " " FUNCTION MEAN(1 2)
           DISPLAY FUNCTION SUM(0.1 0.2) " " FUNCTION RANGE(A B) " "
                   FUNCTION FACTORIAL(20) " " FUNCTION SQRT(4)
           DISPLAY FUNCTION PRESENT-VALUE(3 2 1) " "
                   FUNCTION LENGTH(X) " " FUNCTION STORED-CHAR-LENGTH(X)
           MOVE FUNCTION ORD("A") TO R
           DISPLAY "[" R "]"
           MOVE FUNCTION MEAN(1 2) TO R
           DISPLAY "[" R "]"
           MOVE FUNCTION SQRT(1.5) TO Z
           DISPLAY Z
           MOVE FUNCTION ACOS(-0.2345) TO Z
           DISPLAY Z
           MOVE FUNCTION LOG(1.5) TO Z
           DISPLAY Z
           MOVE FUNCTION SIN(1.5) TO Z
           DISPLAY Z
           MOVE FUNCTION EXP(3) TO Z2
           DISPLAY Z2
           MOVE FUNCTION ANNUITY(3, 5) TO Z
           DISPLAY Z
           COMPUTE N = 2 ** 0.5
           DISPLAY N
           COMPUTE N = FUNCTION LOG10(1000) + FUNCTION EXP10(-3)
           DISPLAY N
           MOVE FUNCTION NUMVAL(" -12.5 ") TO N
           DISPLAY N
           MOVE FUNCTION NUMVAL-C("$1,234.50") TO N
           DISPLAY N
           MOVE FUNCTION NUMVAL-F("-1.5E-3") TO N
           DISPLAY N
           DISPLAY FUNCTION TEST-NUMVAL("12x") " "
                   FUNCTION TEST-NUMVAL-C("$1,234.5,6") " "
                   FUNCTION TEST-NUMVAL-F("1.5E3")
           DISPLAY FUNCTION FORMATTED-DATE("YYYY-MM-DD", 150844) " "
                   FUNCTION FORMATTED-DATE("YYYYWwwD", 150115) " "
                   FUNCTION FORMATTED-TIME("hh:mm:ss.ss", 45296.78)
           DISPLAY FUNCTION FORMATTED-DATETIME
                   ("YYYYDDDThhmmss+hhmm", 1, 45296, -754)
           DISPLAY FUNCTION TEST-FORMATTED-DATETIME
                   ("YYYYMMDD", "18000229") " "
                   FUNCTION INTEGER-OF-FORMATTED-DATE
                   ("YYYY-Www-D", "2014-W01-1") " "
                   FUNCTION SECONDS-FROM-FORMATTED-TIME
                   ("hhmmss", "010203")
           MOVE FUNCTION SUBSTITUTE-CASE("ABC111abc" "abc" "zz") TO S
           DISPLAY S
           MOVE FUNCTION HIGHEST-ALGEBRAIC(F1) TO N
           DISPLAY N
           MOVE FUNCTION LOWEST-ALGEBRAIC(F2) TO N
           DISPLAY N
           MOVE FUNCTION COMBINED-DATETIME(987, 345.6) TO N
           DISPLAY N
           STOP RUN.
