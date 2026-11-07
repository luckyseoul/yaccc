       IDENTIFICATION DIVISION.
       PROGRAM-ID. B7MANDEL.
      *> Extended Mandelbrot: 640x480, up to 2000 iterations, 28-bit
      *> fixed point. Integer arithmetic throughout, so every compiler
      *> produces the same iteration count for every pixel.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WIDTH PIC 9(4) COMP VALUE 640.
       01 HEIGHT PIC 9(4) COMP VALUE 480.
       01 MAXIT PIC 9(5) COMP VALUE 2000.
       01 FRAC PIC 9(18) COMP VALUE 268435456.
      *> the usual view: real -2.2 .. 0.8, imaginary -1.2 .. 1.2
       01 RE-MIN PIC S9(18) COMP VALUE -590558003.
       01 RE-MAX PIC S9(18) COMP VALUE 214748365.
       01 IM-MIN PIC S9(18) COMP VALUE -322122547.
       01 IM-MAX PIC S9(18) COMP VALUE 322122547.
       01 PX PIC 9(4) COMP.
       01 PY PIC 9(4) COMP.
       01 IT PIC 9(5) COMP.
       01 CX PIC S9(18) COMP.
       01 CY PIC S9(18) COMP.
       01 ZX PIC S9(18) COMP.
       01 ZY PIC S9(18) COMP.
       01 ZX2 PIC S9(18) COMP.
       01 ZY2 PIC S9(18) COMP.
       01 T PIC S9(18) COMP.
       01 LIM PIC S9(18) COMP.
       01 TOTAL PIC 9(18) COMP VALUE 0.
       01 STEP-X PIC S9(18) COMP.
       01 STEP-Y PIC S9(18) COMP.
       01 ESCAPED PIC 9 COMP.

       PROCEDURE DIVISION.
           COMPUTE LIM = 4 * FRAC
           COMPUTE STEP-X = (RE-MAX - RE-MIN) / (WIDTH - 1)
           COMPUTE STEP-Y = (IM-MAX - IM-MIN) / (HEIGHT - 1)
           PERFORM VARYING PY FROM 0 BY 1 UNTIL PY >= HEIGHT
               COMPUTE CY = IM-MIN + PY * STEP-Y
               PERFORM VARYING PX FROM 0 BY 1 UNTIL PX >= WIDTH
                   COMPUTE CX = RE-MIN + PX * STEP-X
                   MOVE 0 TO ZX ZY ESCAPED
                   MOVE 0 TO IT
                   PERFORM UNTIL ESCAPED = 1 OR IT >= MAXIT
                       COMPUTE ZX2 = ZX * ZX / FRAC
                       COMPUTE ZY2 = ZY * ZY / FRAC
                       COMPUTE T = ZX2 + ZY2
                       IF T > LIM
                           MOVE 1 TO ESCAPED
                       ELSE
                           COMPUTE ZY = 2 * ZX * ZY / FRAC + CY
                           COMPUTE ZX = ZX2 - ZY2 + CX
                           ADD 1 TO IT
                       END-IF
                   END-PERFORM
                   ADD IT TO TOTAL
               END-PERFORM
           END-PERFORM
           DISPLAY TOTAL
           STOP RUN.
