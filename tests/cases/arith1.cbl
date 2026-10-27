       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A        PIC 9(4)     VALUE 100.
       01 B        PIC 9(4)     VALUE 25.
       01 C        PIC S9(4)V99 VALUE 0.
       01 D        PIC S9(4)V99 VALUE 0.
       01 E        PIC 9(2)     VALUE 0.
       01 Q        PIC 9(3)     VALUE 0.
       01 R        PIC 9(3)     VALUE 0.
       01 QD       PIC 9(3)V9   VALUE 0.
       01 RMD       PIC 9(3)V99  VALUE 0.
       01 P3       PIC S9(5)V99 COMP-3 VALUE 1234.56.
       01 BN       PIC S9(8)    COMP   VALUE 7.
       01 SM       PIC 9V99     VALUE 0.
       01 NEG      PIC S9(3)    VALUE -15.
       PROCEDURE DIVISION.
           ADD A TO B.
           DISPLAY "ADD A TO B: " B.
           ADD 1 2 3 TO A B.
           DISPLAY "ADD 1 2 3 TO A B: " A " " B.
           ADD A B GIVING C.
           DISPLAY "ADD A B GIVING C: " C.
           ADD A TO B GIVING D.
           DISPLAY "ADD A TO B GIVING D: " D.
           SUBTRACT 6 FROM A.
           DISPLAY "SUBTRACT 6 FROM A: " A.
           SUBTRACT A B FROM 1000 GIVING C.
           DISPLAY "SUBTRACT A B FROM 1000 GIVING C: " C.
           SUBTRACT 1 FROM NEG.
           DISPLAY "SUBTRACT 1 FROM NEG: " NEG.
           MULTIPLY 3 BY A.
           DISPLAY "MULTIPLY 3 BY A: " A.
           MULTIPLY A BY 1.5 GIVING C.
           DISPLAY "MULTIPLY A BY 1.5 GIVING C: " C.
           DIVIDE 4 INTO A.
           DISPLAY "DIVIDE 4 INTO A: " A.
           DIVIDE A BY 7 GIVING Q REMAINDER R.
           DISPLAY "DIVIDE A BY 7: " Q " R " R.
           DIVIDE 7 INTO A GIVING QD ROUNDED REMAINDER RMD.
           DISPLAY "DIVIDE 7 INTO A GIVING QD ROUNDED: " QD " R " RMD.
           DIVIDE 10 BY 3 GIVING C ROUNDED.
           DISPLAY "10 / 3 ROUNDED: " C.
           DIVIDE 20 BY 3 GIVING C.
           DISPLAY "20 / 3 TRUNC: " C.
           DIVIDE 20 BY 3 GIVING C ROUNDED.
           DISPLAY "20 / 3 ROUNDED: " C.
           MOVE 99 TO E.
           ADD 1 TO E ON SIZE ERROR DISPLAY "SIZE ERROR ON E=" E
               NOT ON SIZE ERROR DISPLAY "NO SIZE ERROR".
           ADD 1 TO E.
           DISPLAY "E AFTER OVERFLOW (TRUNCATED): " E.
           MOVE 5 TO E.
           ADD 1 TO E ON SIZE ERROR DISPLAY "SIZE ERROR"
               NOT ON SIZE ERROR DISPLAY "NO SIZE ERROR, E=" E
           END-ADD.
           DIVIDE 0 INTO A ON SIZE ERROR DISPLAY "DIV BY ZERO CAUGHT".
           DISPLAY "A UNCHANGED: " A.
           ADD 0.005 TO SM ROUNDED.
           DISPLAY "SM ROUNDED: " SM.
           ADD 1.234 TO P3.
           DISPLAY "P3: " P3.
           SUBTRACT 2000 FROM P3.
           DISPLAY "P3 NEG: " P3.
           MULTIPLY -3 BY BN.
           DISPLAY "BN: " BN.
           COMPUTE C = -7.5.
           DISPLAY "C=-7.5: " C.
           COMPUTE E ROUNDED = 2.5.
           DISPLAY "E ROUNDED 2.5: " E.
           COMPUTE E ROUNDED = 3.49.
           DISPLAY "E ROUNDED 3.49: " E.
           COMPUTE NEG ROUNDED = -2.5.
           DISPLAY "NEG ROUNDED -2.5: " NEG.
           COMPUTE NEG = -2.9.
           DISPLAY "NEG TRUNC -2.9: " NEG.
           STOP RUN.
