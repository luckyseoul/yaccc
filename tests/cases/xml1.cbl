      *> XML GENERATE: elements, attributes, content, suppression and name
      *> mangling. Expected text is GnuCOBOL's (testsuite run_ml.at:19-472).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XML1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  out          PIC X(200).
       01  rec.
           03  a        PIC X(3) VALUE 'A'.
           03  b        PIC X(3) VALUE ALL 'B'.
           03  c.
               05  d    PIC X(3) VALUE SPACES.
       01  0SpecialTAGName PIC X(3) VALUE "abc".
       PROCEDURE DIVISION.
           XML GENERATE out FROM rec
               WITH XML-DECLARATION
               NAME OF a IS 'alpha', d IS 'ABCDEF'
               TYPE OF a IS ATTRIBUTE
               SUPPRESS WHEN SPACES
           DISPLAY "1:[" out "]".
           XML GENERATE out FROM d
           DISPLAY "2:[" out "]".
           XML GENERATE out FROM c, WITH ATTRIBUTES
           DISPLAY "3:[" out "]".
           MOVE ALL 'A' TO a
           MOVE ALL 'C' TO c
           XML GENERATE out FROM rec, TYPE OF a IS CONTENT,
               b IS CONTENT, d IS CONTENT
           DISPLAY "4:[" out "]".
           MOVE ALL "&" TO d
           XML GENERATE out FROM d
           DISPLAY "5:[" out "]".
      *> a name may not start with a digit; the source case is kept
           XML GENERATE out FROM 0specialtagname
           DISPLAY "6:[" out "]".
           STOP RUN.
