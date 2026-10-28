       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG3.
      * Debug module with the object-time switch off: debugging lines
      * run, debugging procedures do not.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. X86-64 WITH DEBUGGING MODE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N               PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       D-ALL SECTION.
           USE FOR DEBUGGING ON ALL PROCEDURES.
       D-ALL-1.
           DISPLAY "debugging procedure " DEBUG-NAME.
       D-N SECTION.
           USE FOR DEBUGGING ON ALL REFERENCES OF N.
       D-N-1.
           DISPLAY "debugging procedure for N".
       END DECLARATIVES.
       MAIN-PARA.
           ADD 1 TO N.
      D    DISPLAY "debugging line, N = " N.
           PERFORM OTHER-PARA.
           STOP RUN.
       OTHER-PARA.
           DISPLAY "other".
