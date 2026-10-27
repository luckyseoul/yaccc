       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECL2.
      * USE GLOBAL declarative invoked for I/O in a contained program.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OPTIONAL MISSING-FILE ASSIGN TO "no-such-file.dat"
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD  MISSING-FILE GLOBAL.
       01  MREC     PIC X(10).
       WORKING-STORAGE SECTION.
       01  FS       PIC XX GLOBAL.
       PROCEDURE DIVISION.
       DECLARATIVES.
       ERR SECTION.
           USE GLOBAL AFTER ERROR PROCEDURE ON INPUT.
       ERR-1.
           DISPLAY "declarative: status " FS.
       END DECLARATIVES.
       MAIN SECTION.
       M-1.
           CALL "READER"
           DISPLAY "back in main"
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READER.
       PROCEDURE DIVISION.
           OPEN INPUT MISSING-FILE
           DISPLAY "open status " FS
           READ MISSING-FILE
           DISPLAY "read status " FS
           READ MISSING-FILE
           DISPLAY "second read status " FS
           CLOSE MISSING-FILE
           EXIT PROGRAM.
       END PROGRAM READER.
       END PROGRAM DECL2.
