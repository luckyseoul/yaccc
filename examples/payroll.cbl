      *****************************************************************
      * PAYROLL - weekly payroll register with department subtotals.
      * Reads EMPLOYEES.DAT, sorts by department and name, computes
      * gross pay (time-and-a-half over 40 hours), federal tax by
      * bracket, state tax and FICA, and writes PAYROLL.RPT.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE   ASSIGN TO "employees.dat"
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS IS WS-EMP-STATUS.
           SELECT SORT-FILE  ASSIGN TO "sortwk".
           SELECT RPT-FILE   ASSIGN TO "payroll.rpt"
                  ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-FILE.
       01  EMP-IN-REC                 PIC X(40).
       SD  SORT-FILE.
       01  SORT-REC.
           05  SR-ID                  PIC 9(5).
           05  SR-NAME                PIC X(20).
           05  SR-DEPT                PIC X(4).
           05  SR-HOURS               PIC 9(3)V9.
           05  SR-RATE                PIC 9(3)V99.
           05  SR-STATUS              PIC X.
               88  SR-MARRIED         VALUE "M".
               88  SR-SINGLE          VALUE "S".
       FD  RPT-FILE.
       01  RPT-REC                    PIC X(100).
       WORKING-STORAGE SECTION.
       01  WS-EMP-STATUS              PIC XX.
       01  WS-FLAGS.
           05  WS-EOF                 PIC X VALUE "N".
               88  END-OF-SORT        VALUE "Y".
           05  WS-FIRST               PIC X VALUE "Y".
               88  FIRST-RECORD       VALUE "Y".
       01  WS-PREV-DEPT               PIC X(4) VALUE SPACES.
       01  WS-CALC.
           05  WS-REG-HOURS           PIC 9(3)V9.
           05  WS-OT-HOURS            PIC 9(3)V9.
           05  WS-GROSS               PIC 9(6)V99.
           05  WS-TAXABLE             PIC S9(6)V99.
           05  WS-FED                 PIC 9(6)V99.
           05  WS-STATE               PIC 9(6)V99.
           05  WS-FICA                PIC 9(6)V99.
           05  WS-NET                 PIC S9(6)V99.
           05  WS-ALLOWANCE           PIC 9(4)V99.
       01  WS-TOTALS.
           05  WS-DEPT-COUNT          PIC 9(3)       VALUE 0.
           05  WS-DEPT-GROSS          PIC 9(7)V99    VALUE 0.
           05  WS-DEPT-NET            PIC S9(7)V99   VALUE 0.
           05  WS-GRAND-COUNT         PIC 9(3)       VALUE 0.
           05  WS-GRAND-GROSS         PIC 9(8)V99    VALUE 0.
           05  WS-GRAND-TAX           PIC 9(8)V99    VALUE 0.
           05  WS-GRAND-NET           PIC S9(8)V99   VALUE 0.
       01  WS-LINE-COUNT              PIC 99 VALUE 99.
       01  WS-PAGE                    PIC 99 VALUE 0.
       01  HDR-1.
           05  FILLER  PIC X(30) VALUE "ACME COMPUTING CORPORATION".
           05  FILLER  PIC X(40) VALUE "WEEKLY PAYROLL REGISTER".
           05  FILLER  PIC X(5)  VALUE "PAGE ".
           05  H1-PAGE PIC Z9.
       01  HDR-2.
           05  FILLER  PIC X(7)  VALUE "EMP-ID".
           05  FILLER  PIC X(21) VALUE "NAME".
           05  FILLER  PIC X(6)  VALUE "HOURS".
           05  FILLER  PIC X(10) VALUE "    GROSS".
           05  FILLER  PIC X(10) VALUE "  FED TAX".
           05  FILLER  PIC X(10) VALUE "  ST TAX".
           05  FILLER  PIC X(10) VALUE "     FICA".
           05  FILLER  PIC X(12) VALUE "        NET".
       01  DEPT-HDR.
           05  FILLER  PIC X(12) VALUE "DEPARTMENT: ".
           05  DH-DEPT PIC X(4).
       01  DETAIL-LINE.
           05  DL-ID       PIC 9(5).
           05  FILLER      PIC XX VALUE SPACES.
           05  DL-NAME     PIC X(20).
           05  DL-HOURS    PIC ZZ9.9.
           05  DL-OT       PIC X VALUE SPACE.
           05  DL-GROSS    PIC ZZ,ZZ9.99.
           05  DL-FED      PIC ZZ,ZZ9.99.
           05  DL-STATE    PIC ZZ,ZZ9.99.
           05  DL-FICA     PIC ZZ,ZZ9.99.
           05  DL-NET      PIC $$$,$$9.99-.
       01  DEPT-TOTAL-LINE.
           05  FILLER      PIC X(7) VALUE SPACES.
           05  FILLER      PIC X(8) VALUE "TOTAL ".
           05  DT-DEPT     PIC X(4).
           05  FILLER      PIC X(3) VALUE " (".
           05  DT-COUNT    PIC Z9.
           05  FILLER      PIC X(8) VALUE ")".
           05  DT-GROSS    PIC $$$$,$$9.99.
           05  FILLER      PIC X(25) VALUE SPACES.
           05  DT-NET      PIC $$$$,$$9.99-.
       01  GRAND-LINE-1.
           05  FILLER      PIC X(24) VALUE "EMPLOYEES PAID:".
           05  GL-COUNT    PIC ZZ9.
       01  GRAND-LINE-2.
           05  FILLER      PIC X(24) VALUE "TOTAL GROSS PAY:".
           05  GL-GROSS    PIC $$$,$$$,$$9.99.
       01  GRAND-LINE-3.
           05  FILLER      PIC X(24) VALUE "TOTAL TAXES WITHHELD:".
           05  GL-TAX      PIC $$$,$$$,$$9.99.
       01  GRAND-LINE-4.
           05  FILLER      PIC X(24) VALUE "TOTAL NET PAY:".
           05  GL-NET      PIC $$$,$$$,$$9.99-.
       PROCEDURE DIVISION.
       0000-MAIN.
           SORT SORT-FILE
               ON ASCENDING KEY SR-DEPT
               ON ASCENDING KEY SR-NAME
               USING EMP-FILE
               OUTPUT PROCEDURE IS 2000-PRODUCE-REPORT
           DISPLAY "PAYROLL COMPLETE: " WS-GRAND-COUNT
                   " EMPLOYEES, NET " GL-NET
           STOP RUN.

       2000-PRODUCE-REPORT SECTION.
       2000-START.
           OPEN OUTPUT RPT-FILE
           PERFORM 2100-RETURN-RECORD
           PERFORM UNTIL END-OF-SORT
               IF SR-DEPT NOT = WS-PREV-DEPT
                   IF NOT FIRST-RECORD
                       PERFORM 3000-DEPT-BREAK
                   END-IF
                   MOVE "N" TO WS-FIRST
                   MOVE SR-DEPT TO WS-PREV-DEPT
                   PERFORM 3100-DEPT-HEADER
               END-IF
               PERFORM 2200-COMPUTE-PAY
               PERFORM 2300-PRINT-DETAIL
               PERFORM 2100-RETURN-RECORD
           END-PERFORM
           IF NOT FIRST-RECORD
               PERFORM 3000-DEPT-BREAK
           END-IF
           PERFORM 4000-GRAND-TOTALS
           CLOSE RPT-FILE.
       2000-EXIT.
           EXIT.

       2100-SUBROUTINES SECTION.
       2100-RETURN-RECORD.
           RETURN SORT-FILE
               AT END SET END-OF-SORT TO TRUE
           END-RETURN.

       2200-COMPUTE-PAY.
           IF SR-HOURS > 40
               MOVE 40 TO WS-REG-HOURS
               COMPUTE WS-OT-HOURS = SR-HOURS - 40
               MOVE "*" TO DL-OT
           ELSE
               MOVE SR-HOURS TO WS-REG-HOURS
               MOVE 0 TO WS-OT-HOURS
               MOVE SPACE TO DL-OT
           END-IF
           COMPUTE WS-GROSS ROUNDED =
                   WS-REG-HOURS * SR-RATE
                 + WS-OT-HOURS * SR-RATE * 1.5
           IF SR-MARRIED
               MOVE 532.00 TO WS-ALLOWANCE
           ELSE
               MOVE 266.00 TO WS-ALLOWANCE
           END-IF
           COMPUTE WS-TAXABLE = WS-GROSS - WS-ALLOWANCE
           EVALUATE TRUE
               WHEN WS-TAXABLE <= 0
                   MOVE 0 TO WS-FED
               WHEN WS-TAXABLE <= 1000
                   COMPUTE WS-FED ROUNDED = WS-TAXABLE * 0.12
               WHEN WS-TAXABLE <= 3000
                   COMPUTE WS-FED ROUNDED =
                           120 + (WS-TAXABLE - 1000) * 0.22
               WHEN OTHER
                   COMPUTE WS-FED ROUNDED =
                           560 + (WS-TAXABLE - 3000) * 0.24
           END-EVALUATE
           COMPUTE WS-STATE ROUNDED = WS-GROSS * 0.0425
           COMPUTE WS-FICA  ROUNDED = WS-GROSS * 0.0765
           COMPUTE WS-NET = WS-GROSS - WS-FED - WS-STATE - WS-FICA
           ADD 1 TO WS-DEPT-COUNT WS-GRAND-COUNT
           ADD WS-GROSS TO WS-DEPT-GROSS WS-GRAND-GROSS
           ADD WS-NET TO WS-DEPT-NET WS-GRAND-NET
           ADD WS-FED WS-STATE WS-FICA TO WS-GRAND-TAX.

       2300-PRINT-DETAIL.
           IF WS-LINE-COUNT > 20
               PERFORM 3200-PAGE-HEADER
           END-IF
           MOVE SR-ID    TO DL-ID
           MOVE SR-NAME  TO DL-NAME
           MOVE SR-HOURS TO DL-HOURS
           MOVE WS-GROSS TO DL-GROSS
           MOVE WS-FED   TO DL-FED
           MOVE WS-STATE TO DL-STATE
           MOVE WS-FICA  TO DL-FICA
           MOVE WS-NET   TO DL-NET
           WRITE RPT-REC FROM DETAIL-LINE
           ADD 1 TO WS-LINE-COUNT.

       3000-DEPT-BREAK.
           MOVE WS-PREV-DEPT  TO DT-DEPT
           MOVE WS-DEPT-COUNT TO DT-COUNT
           MOVE WS-DEPT-GROSS TO DT-GROSS
           MOVE WS-DEPT-NET   TO DT-NET
           WRITE RPT-REC FROM DEPT-TOTAL-LINE
           MOVE SPACES TO RPT-REC
           WRITE RPT-REC
           ADD 2 TO WS-LINE-COUNT
           INITIALIZE WS-DEPT-COUNT WS-DEPT-GROSS WS-DEPT-NET.

       3100-DEPT-HEADER.
           IF WS-LINE-COUNT > 18
               PERFORM 3200-PAGE-HEADER
           END-IF
           MOVE WS-PREV-DEPT TO DH-DEPT
           WRITE RPT-REC FROM DEPT-HDR
           ADD 1 TO WS-LINE-COUNT.

       3200-PAGE-HEADER.
           ADD 1 TO WS-PAGE
           MOVE WS-PAGE TO H1-PAGE
           IF WS-PAGE = 1
               WRITE RPT-REC FROM HDR-1
           ELSE
               WRITE RPT-REC FROM HDR-1 AFTER ADVANCING PAGE
           END-IF
           WRITE RPT-REC FROM HDR-2 AFTER ADVANCING 2 LINES
           MOVE ALL "-" TO RPT-REC
           WRITE RPT-REC
           MOVE 4 TO WS-LINE-COUNT.

       4000-GRAND-TOTALS.
           MOVE WS-GRAND-COUNT TO GL-COUNT
           MOVE WS-GRAND-GROSS TO GL-GROSS
           MOVE WS-GRAND-TAX   TO GL-TAX
           MOVE WS-GRAND-NET   TO GL-NET
           MOVE ALL "=" TO RPT-REC
           WRITE RPT-REC
           WRITE RPT-REC FROM GRAND-LINE-1
           WRITE RPT-REC FROM GRAND-LINE-2
           WRITE RPT-REC FROM GRAND-LINE-3
           WRITE RPT-REC FROM GRAND-LINE-4.
