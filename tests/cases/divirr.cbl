      * Division by a full-precision intrinsic result: the divisor carries
      * 38 significant digits, more than the scaled dividend leaves room for.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVIRR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X  PIC S9(3)V9(9).
       01 Y  PIC S9(3)V9(9).
       01 W  PIC S9(3)V9(9).
       01 V  PIC S9(9)V9(9).
       01 B  PIC 9V9 VALUE 2.
       01 P  PIC S9(18)V9(9).
       01 Q  PIC S9(9)V9(18).
       01 E  PIC S9(9)V9(9).
       PROCEDURE DIVISION.
           COMPUTE X = 1 / FUNCTION SQRT(2)
           COMPUTE Y = 1 / FUNCTION PI
           COMPUTE W = 1 / FUNCTION SQRT(4)
           COMPUTE V = 10 / FUNCTION SQRT(B)
           DISPLAY X " " Y " " W " " V
           COMPUTE P = 123456789012345678.123456789 / 3
           COMPUTE Q = 1 / 7
           COMPUTE E = FUNCTION E / FUNCTION PI
           DISPLAY P " " Q " " E
           COMPUTE E ROUNDED = 100 / FUNCTION LOG(10)
           DISPLAY E
           COMPUTE E ROUNDED = FUNCTION PI * 1000 / FUNCTION SQRT(3)
           DISPLAY E
           STOP RUN.
