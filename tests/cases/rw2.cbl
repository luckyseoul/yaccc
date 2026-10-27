       IDENTIFICATION DIVISION.
       PROGRAM-ID. RW2.
      * Report Writer paging: report heading alone on page 1, page
      * breaks inside a control group (GROUP INDICATE repeats), page
      * footing, NEXT GROUP NEXT PAGE and a report footing on its own
      * page that totals the control footings.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT ASSIGN TO "rw2.txt".
       DATA DIVISION.
       FILE SECTION.
       FD  RPT REPORT IS INV.
       WORKING-STORAGE SECTION.
       01  WAREHOUSE    PIC X(3).
       01  PART         PIC X(8).
       01  QTY          PIC 999.
       01  I            PIC 99.
       REPORT SECTION.
       RD  INV
           CONTROLS ARE WAREHOUSE
           PAGE LIMIT 20 HEADING 2 FIRST DETAIL 5 LAST DETAIL 15
           FOOTING 17.
       01  TYPE RH NEXT GROUP NEXT PAGE.
           05 LINE 3.
              10 COLUMN 10 PIC X(16) VALUE "INVENTORY REPORT".
           05 LINE 5.
              10 COLUMN 10 PIC X(10) VALUE "TITLE PAGE".
       01  TYPE PH.
           05 LINE 2.
              10 COLUMN 1 PIC X(9) VALUE "INVENTORY".
              10 COLUMN 30 PIC X(5) VALUE "PAGE ".
              10 COLUMN 35 PIC Z9 SOURCE PAGE-COUNTER.
           05 LINE PLUS 1.
              10 COLUMN 1 PIC X(36) VALUE ALL "-".
       01  TYPE CH WAREHOUSE LINE PLUS 1.
           05 COLUMN 1 PIC X(10) VALUE "WAREHOUSE ".
           05 COLUMN 11 PIC X(3) SOURCE WAREHOUSE.
       01  ITEM-LINE TYPE DE LINE PLUS 1.
           05 COLUMN 3 PIC X(3) SOURCE WAREHOUSE GROUP INDICATE.
           05 COLUMN 8 PIC X(8) SOURCE PART.
           05 COLUMN 18 PIC ZZ9 SOURCE QTY.
           05 COLUMN 23 PIC 99 SOURCE LINE-COUNTER.
       01  TYPE CF WAREHOUSE LINE PLUS 1 NEXT GROUP NEXT PAGE.
           05 COLUMN 3 PIC X(9) VALUE "SUBTOTAL ".
           05 WH-QTY COLUMN 17 PIC ZZZ9 SUM QTY.
       01  TYPE PF LINE 19.
           05 COLUMN 1 PIC X(12) VALUE "END OF PAGE ".
           05 COLUMN 13 PIC Z9 SOURCE PAGE-COUNTER.
       01  TYPE RF LINE 10 ON NEXT PAGE.
           05 COLUMN 1 PIC X(13) VALUE "TOTAL PARTS: ".
           05 COLUMN 14 PIC ZZZ9 SUM WH-QTY.
       PROCEDURE DIVISION.
           OPEN OUTPUT RPT
           INITIATE INV
           MOVE "A" TO WAREHOUSE
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 12
               MOVE I TO QTY
               STRING "PART-" I DELIMITED BY SIZE INTO PART
               GENERATE ITEM-LINE
           END-PERFORM
           MOVE "B" TO WAREHOUSE
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3
               COMPUTE QTY = I * 10
               STRING "PART-" I DELIMITED BY SIZE INTO PART
               GENERATE ITEM-LINE
           END-PERFORM
           TERMINATE INV
           CLOSE RPT
           DISPLAY "PAGES: " PAGE-COUNTER " LAST LINE: " LINE-COUNTER
           STOP RUN.
