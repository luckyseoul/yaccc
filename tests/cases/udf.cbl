      *> User-defined functions: FUNCTION-ID programs called as functions,
      *> through REPOSITORY, with and without arguments. Behaviour per
      *> GnuCOBOL (testsuite run_functions.at:4126 and :4177).
       IDENTIFICATION DIVISION.
       FUNCTION-ID. ADDONE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  PAR-IN   PIC 99.
       01  PAR-OUT  PIC 99.
       PROCEDURE DIVISION USING PAR-IN RETURNING PAR-OUT.
           ADD 1 TO PAR-IN GIVING PAR-OUT END-ADD.
           GOBACK.
       END FUNCTION ADDONE.

       IDENTIFICATION DIVISION.
       FUNCTION-ID. ONE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  PAR      PIC 9.
       PROCEDURE DIVISION RETURNING PAR.
           MOVE 1 TO PAR.
           GOBACK.
       END FUNCTION ONE.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. UDF.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           FUNCTION ADDONE
           FUNCTION ONE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N        PIC 99.
       PROCEDURE DIVISION.
           DISPLAY "ADDONE(1)=" ADDONE(1).
           DISPLAY "ONE=" ONE.
      *> and inside COMPUTE, where the value is used arithmetically
           COMPUTE N = ADDONE(41) + 1
           DISPLAY "COMPUTE=" N.
           STOP RUN.
       END PROGRAM UDF.
