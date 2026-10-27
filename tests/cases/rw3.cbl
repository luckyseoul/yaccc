       IDENTIFICATION DIVISION.
       PROGRAM-ID. RW3.
      * Report Writer: summary reporting (GENERATE report-name), a
      * report without a PAGE clause, signed sums, a report footing
      * summing footing counters, CODE, and two reports at once with
      * qualified LINE-COUNTER / PAGE-COUNTER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SUM-FILE ASSIGN TO "rw3sum.txt".
           SELECT LIST-FILE ASSIGN TO "rw3list.txt".
       DATA DIVISION.
       FILE SECTION.
       FD  SUM-FILE REPORT IS SUMMARY-RPT.
       FD  LIST-FILE REPORT IS LIST-RPT.
       WORKING-STORAGE SECTION.
       01  SALE.
           05 REGION    PIC X(4).
           05 ITEM      PIC X(10).
           05 AMT       PIC S9(4)V99 SIGN LEADING SEPARATE.
       01  ONE          PIC 9 VALUE 1.
       01  ROWS.
           05 FILLER PIC X(21) VALUE "EASTW1        +001000".
           05 FILLER PIC X(21) VALUE "EASTW2        -000250".
           05 FILLER PIC X(21) VALUE "WESTW3        +000525".
           05 FILLER PIC X(21) VALUE "WESTW4        +010000".
           05 FILLER PIC X(21) VALUE "WESTW5        -000075".
       01  RT REDEFINES ROWS.
           05 ROW PIC X(21) OCCURS 5.
       01  I            PIC 9.
       REPORT SECTION.
       RD  SUMMARY-RPT
           CONTROLS ARE REGION.
       01  TYPE CH REGION LINE PLUS 1.
           05 COLUMN 1 PIC X(7) VALUE "REGION ".
           05 COLUMN 8 PIC X(4) SOURCE REGION.
       01  TYPE CF REGION LINE PLUS 1.
           05 COLUMN 3 PIC X(6) VALUE "COUNT ".
           05 RC COLUMN 9 PIC ZZ9 SUM ONE.
           05 COLUMN 13 PIC X(7) VALUE "AMOUNT ".
           05 RA COLUMN 20 PIC Z,ZZ9.99- SUM AMT.
       01  TYPE RF LINE PLUS 2.
           05 COLUMN 1 PIC X(6) VALUE "TOTAL ".
           05 COLUMN 9 PIC ZZ9 SUM RC.
           05 COLUMN 20 PIC Z,ZZ9.99- SUM RA.
       RD  LIST-RPT
           CODE "L1"
           PAGE LIMIT 8 FIRST DETAIL 2.
       01  TYPE PH LINE 1.
           05 COLUMN 1 PIC X(5) VALUE "LIST ".
           05 COLUMN 6 PIC 9 SOURCE PAGE-COUNTER.
       01  LIST-LINE TYPE DE LINE PLUS 1.
           05 COLUMN 1 PIC X(10) SOURCE ITEM.
           05 COLUMN 12 PIC -ZZ9.99 SOURCE AMT.
           05 COLUMN 20 PIC 9 SOURCE LINE-COUNTER.
       PROCEDURE DIVISION.
           OPEN OUTPUT SUM-FILE LIST-FILE
           INITIATE SUMMARY-RPT LIST-RPT
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               MOVE ROW (I) TO SALE
               GENERATE SUMMARY-RPT
               GENERATE LIST-LINE
           END-PERFORM
           TERMINATE SUMMARY-RPT LIST-RPT
           CLOSE SUM-FILE LIST-FILE
           DISPLAY "LIST LINE-COUNTER " LINE-COUNTER OF LIST-RPT
                   " PAGE-COUNTER " PAGE-COUNTER IN LIST-RPT
           DISPLAY "SUMMARY RC " RC " RA " RA
           STOP RUN.
