       IDENTIFICATION DIVISION.
       PROGRAM-ID. POWFLOAT.
      *> COMPUTE with ** and a floating-point receiver takes the double fast
      *> path in the generated C, which is a different expression from the
      *> decimal one compute1.cbl covers. That path once emitted a bare pow()
      *> with no declaration, so the compiler produced C that did not build.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 D        COMP-2 VALUE 0.
       01 E        COMP-2 VALUE 0.
       01 S        COMP-1 VALUE 0.
       01 BASE     COMP-2 VALUE 2.
       01 NEG      COMP-2 VALUE -3.
       01 ZR     COMP-2 VALUE 0.
       01 EXPON    COMP-2 VALUE 0.5.
       PROCEDURE DIVISION.
           COMPUTE D = BASE ** 3.
           DISPLAY "2 ** 3     = " D.
           COMPUTE D = BASE ** NEG.
           DISPLAY "2 ** -3    = " D.
           COMPUTE D = BASE ** EXPON.
           DISPLAY "2 ** 0.5   = " D.
           COMPUTE D = ZR ** 0.
           DISPLAY "0 ** 0     = " D.
           COMPUTE D = ZR ** NEG.
           DISPLAY "0 ** -3    = " D.
           COMPUTE E = FUNCTION E ** -2.
           DISPLAY "e ** -2    = " E.
           COMPUTE S = BASE ** 10.
           DISPLAY "COMP-1 2**10 = " S.
           STOP RUN.
