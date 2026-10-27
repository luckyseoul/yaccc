       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTE1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X        PIC S9(6)V9(4) VALUE 0.
       01 Y        PIC S9(6)V9(4) VALUE 0.
       01 I        PIC S9(4)      VALUE 0.
       01 J        PIC S9(4)      VALUE 3.
       01 K        PIC S9(4)      VALUE 4.
       01 BIG      PIC 9(18)      VALUE 0.
       01 BIGS     PIC S9(15)V9(3) VALUE 0.
       01 PCT      PIC 9V9(6)     VALUE 0.
       01 PK       PIC S9(7)V99 COMP-3.
       01 BN       PIC S9(9) COMP.
       01 FL       COMP-2.
       PROCEDURE DIVISION.
           COMPUTE X = 1 + 2 * 3.
           DISPLAY "1 + 2 * 3 = " X.
           COMPUTE X = (1 + 2) * 3.
           DISPLAY "(1 + 2) * 3 = " X.
           COMPUTE X = 2 ** 10.
           DISPLAY "2 ** 10 = " X.
           COMPUTE X = 2 ** -2.
           DISPLAY "2 ** -2 = " X.
           COMPUTE X = 10 / 4.
           DISPLAY "10 / 4 = " X.
           COMPUTE X = 1 / 3.
           DISPLAY "1 / 3 = " X.
           COMPUTE X ROUNDED = 2 / 3.
           DISPLAY "2 / 3 ROUNDED = " X.
           COMPUTE X = - J + K.
           DISPLAY "- J + K = " X.
           COMPUTE X = J - K * 2.
           DISPLAY "J - K * 2 = " X.
           COMPUTE X = J * K / 5.
           DISPLAY "J * K / 5 = " X.
           COMPUTE X = (J + K) / (J - K).
           DISPLAY "(J + K) / (J - K) = " X.
           COMPUTE X = 1.5 ** 2.
           DISPLAY "1.5 ** 2 = " X.
           COMPUTE X = 16 ** 0.5.
           DISPLAY "16 ** 0.5 = " X.
           COMPUTE BIG = 999999999 * 999999999.
           DISPLAY "999999999 SQUARED = " BIG.
           COMPUTE BIGS = 123456789012.345 * 2.
           DISPLAY "BIGS = " BIGS.
           COMPUTE PCT = 1 / 7.
           DISPLAY "1/7 = " PCT.
           COMPUTE PK = 12345.678 * 3.
           DISPLAY "PK = " PK.
           COMPUTE PK ROUNDED = 12345.678 * 3.
           DISPLAY "PK ROUNDED = " PK.
           COMPUTE BN = 2 ** 20 - 1.
           DISPLAY "BN = " BN.
           COMPUTE I = J ** 2 + K ** 2.
           DISPLAY "J**2 + K**2 = " I.
           COMPUTE Y = 100.
           COMPUTE X = Y * 1.05 * 1.05 * 1.05.
           DISPLAY "COMPOUND = " X.
           COMPUTE X = 7 / 2 * 2.
           DISPLAY "7 / 2 * 2 = " X.
           COMPUTE I = 7 / 2 * 2.
           DISPLAY "INT 7 / 2 * 2 = " I.
           COMPUTE X = (((1 + 2) * (3 + 4)) - 5) / 2.
           DISPLAY "NESTED = " X.
           COMPUTE X = 0.1 + 0.2.
           DISPLAY "0.1 + 0.2 = " X.
           COMPUTE FL = 1 / 3.
           COMPUTE X = FL * 3.
           DISPLAY "FLOAT ROUNDTRIP = " X.
           COMPUTE X EQUAL 5 + 5.
           DISPLAY "EQUAL = " X.
           COMPUTE X Y = 42.42.
           DISPLAY "MULTI TARGET = " X " " Y.
           STOP RUN.
