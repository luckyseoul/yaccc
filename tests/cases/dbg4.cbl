       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG4.
      * No WITH DEBUGGING MODE: debugging lines are comments and the
      * debugging sections are not compiled.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. X86-64.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N               PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D-ALL SECTION.
           USE FOR DEBUGGING ON ALL PROCEDURES.
       D-ALL-1.
           DISPLAY "debugging procedure " DEBUG-NAME.
       END DECLARATIVES.
       MAIN-PARA.
           ADD 1 TO N.
      D    DISPLAY "debugging line".
           DISPLAY "N = " N.
           STOP RUN.
