      *> a report item with SOURCE and no COLUMN clause is placed after the
      *> previous item; it must not be dropped from the report
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RWSRC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO "rwsrc.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE REPORT IS R1.
       01  RW-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01  FOO PIC X(5).
       REPORT SECTION.
       RD  R1.
       01  DL TYPE DE.
           02 LINE + 1.
              03 SOURCE FOO, PIC X(5).
              03 PIC X(3) VALUE " | ".
              03 COLUMN 10 PIC X(4) VALUE "END".
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE
           INITIATE R1
           MOVE "HELLO" TO FOO
           GENERATE DL
           TERMINATE R1
           CLOSE PRINT-FILE
           STOP RUN.
