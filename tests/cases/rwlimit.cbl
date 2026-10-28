      *> LINE LIMIT may follow the PAGE clause directly (GnuCOBOL's own
      *> testsuite writes it in this order), with HEADING and FIRST DETAIL
      *> after it
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RWLIMIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO "rwlimit.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE REPORT IS R1.
       01  RW-REC PIC X(80).
       REPORT SECTION.
       RD  R1
           PAGE LIMIT IS 6 LINES
           LINE LIMIT 60
           HEADING 1
           FIRST DETAIL 3.
       01  PH TYPE IS PAGE HEADING.
           05 LINE 1.
              10 COLUMN 1 PIC X(5) VALUE "TITLE".
       01  DL TYPE IS DETAIL.
           05 LINE 3.
              10 COLUMN 1 PIC X(3) VALUE "ROW".
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE
           INITIATE R1
           GENERATE DL
           TERMINATE R1
           CLOSE PRINT-FILE
           STOP RUN.
