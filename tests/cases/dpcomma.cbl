       IDENTIFICATION DIVISION.
       PROGRAM-ID. DPCOMMA.
      * DECIMAL-POINT IS COMMA: literals after operators and separators.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X           PIC 99V99.
       PROCEDURE DIVISION.
           COMPUTE X = 1*,5
           DISPLAY X
           COMPUTE X = 2 + ,25
           DISPLAY X
           MOVE FUNCTION MAX (3,,,,1,5) TO X
           DISPLAY X
           DISPLAY 12,5 " " -0,75 " " +1,5E1
           STOP RUN.
