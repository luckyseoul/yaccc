      *****************************************************************
      * MANDELBROT - renders the Mandelbrot set as ASCII art using
      * fixed-point decimal arithmetic (no floating point).
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MANDELBROT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WIDTH          PIC 9(3)        VALUE 78.
       01  HEIGHT         PIC 9(3)        VALUE 32.
       01  MAX-ITER       PIC 9(3)        VALUE 200.
       01  PX-ROW            PIC 9(3).
       01  PX-COL            PIC 9(3).
       01  ITER           PIC 9(3).
       01  CX             PIC S9(2)V9(12).
       01  CY             PIC S9(2)V9(12).
       01  ZX             PIC S9(4)V9(12).
       01  ZY             PIC S9(4)V9(12).
       01  ZX2            PIC S9(4)V9(12).
       01  ZY2            PIC S9(4)V9(12).
       01  TMP            PIC S9(4)V9(12).
       01  X-MIN          PIC S9V9(4)     VALUE -2.2.
       01  X-MAX          PIC S9V9(4)     VALUE  0.8.
       01  Y-MIN          PIC S9V9(4)     VALUE -1.2.
       01  Y-MAX          PIC S9V9(4)     VALUE  1.2.
       01  PALETTE        PIC X(10)       VALUE " .:-=+*#%@".
       01  SHADE          PIC 99.
       01  OUT-LINE       PIC X(78).
       01  TOTAL-ITER     PIC 9(9)        VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING PX-ROW FROM 0 BY 1 UNTIL PX-ROW >= HEIGHT
               COMPUTE CY = Y-MIN + (Y-MAX - Y-MIN) * PX-ROW / HEIGHT
               MOVE SPACES TO OUT-LINE
               PERFORM VARYING PX-COL FROM 0 BY 1 UNTIL PX-COL >= WIDTH
                   COMPUTE CX = X-MIN + (X-MAX - X-MIN) * PX-COL / WIDTH
                   PERFORM ITERATE-POINT
                   IF ITER >= MAX-ITER
                       MOVE "@" TO OUT-LINE(PX-COL + 1:1)
                   ELSE
                       COMPUTE SHADE = FUNCTION MOD(ITER, 9) + 1
                       MOVE PALETTE(SHADE:1) TO OUT-LINE(PX-COL + 1:1)
                   END-IF
               END-PERFORM
               DISPLAY OUT-LINE
           END-PERFORM
           DISPLAY "Total iterations: " TOTAL-ITER
           STOP RUN.

       ITERATE-POINT.
           MOVE 0 TO ZX ZY ZX2 ZY2 ITER
           PERFORM UNTIL ITER >= MAX-ITER OR ZX2 + ZY2 > 4
               COMPUTE ZY = 2 * ZX * ZY + CY
               COMPUTE ZX = ZX2 - ZY2 + CX
               COMPUTE ZX2 = ZX * ZX
               COMPUTE ZY2 = ZY * ZY
               ADD 1 TO ITER
           END-PERFORM
           ADD ITER TO TOTAL-ITER.
