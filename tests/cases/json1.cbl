      *> JSON GENERATE: object from a group, string and number values, the
      *> NAME OF and SUPPRESS clauses, arrays from OCCURS, COUNT IN and
      *> JSON-CODE. Expected text is GnuCOBOL's (testsuite run_ml.at:516-760).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSON1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  out              PIC X(200).
       01  rec.
           03  a            PIC X(3) VALUE 'A'.
           03  b            PIC X(3) VALUE ALL 'B'.
           03  c.
               05  d        PIC X(3) VALUE SPACES.
       01  nums.
           03  n-int        PIC 9(5) VALUE 5.
           03  n-dec        PIC 99V999 PACKED-DECIMAL VALUE 0.12.
           03  n-neg        PIC S999 COMP-X VALUE -1.
       01  arr.
           03  e            PIC X OCCURS 3 VALUE "f".
       01  short-out        PIC X(5).
       01  jlen             PIC 99.
       PROCEDURE DIVISION.
           JSON GENERATE out FROM rec
               NAME OF a IS 'alpha', d IS 'ABCDEF'
               SUPPRESS c
           DISPLAY "1:[" FUNCTION TRIM (out) "]".
           JSON GENERATE out FROM rec
               NAME OF a IS 'alpha', rec IS OMITTED
               SUPPRESS c
           DISPLAY "2:[" FUNCTION TRIM (out) "]".
           JSON GENERATE out FROM d
           DISPLAY "3:[" FUNCTION TRIM (out) "]".
           JSON GENERATE out FROM nums
           DISPLAY "4:[" FUNCTION TRIM (out) "]".
           JSON GENERATE out FROM arr
           DISPLAY "5:[" FUNCTION TRIM (out) "]".
      *> a document that does not fit: COUNT IN is the full length,
      *> JSON-CODE says it was truncated
           JSON GENERATE short-out FROM nums COUNT IN jlen
           DISPLAY "6:[" short-out "] len=" jlen " code=" JSON-CODE.
           JSON GENERATE out FROM nums
           DISPLAY "7:code=" JSON-CODE.
           STOP RUN.
