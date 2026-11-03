      * SPDX-License-Identifier: MIT
      * REPOSITORY. FUNCTION ALL INTRINSIC: intrinsic functions called
      * without the FUNCTION keyword, LENGTH OF still the special register.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPOINT.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           FUNCTION ALL INTRINSIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC X(5) VALUE "hello".
       01 Y PIC X(5).
       01 Z PIC 9V99.
       01 N PIC 99.
       PROCEDURE DIVISION.
           MOVE UPPER-CASE(X) TO Y
           COMPUTE Z = SQRT(16) + PI - PI
           MOVE LENGTH OF X TO N
           DISPLAY Y " " Z " " LENGTH(X) " " N " " TRIM(" a ") "|"
           DISPLAY REVERSE(Y) " " MAX(3 9 4) " " ORD-MAX(3 9 4)
           STOP RUN.
