       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILE1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "employees.txt"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS EMP-STATUS.
           SELECT RPT-FILE ASSIGN TO "report.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT FIX-FILE ASSIGN TO "fixed.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS FIX-STATUS.
           SELECT MISSING-FILE ASSIGN TO "no-such-file.txt"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS MISS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD EMP-FILE.
       01 EMP-REC.
          05 EMP-ID       PIC 9(4).
          05 EMP-NAME     PIC X(12).
          05 EMP-DEPT     PIC X(4).
          05 EMP-SALARY   PIC 9(6)V99.
       FD RPT-FILE.
       01 RPT-LINE        PIC X(60).
       FD FIX-FILE.
       01 FIX-REC.
          05 FIX-KEY      PIC 9(3).
          05 FIX-AMT      PIC S9(5)V99 COMP-3.
          05 FIX-NAME     PIC X(6).
       FD MISSING-FILE.
       01 MISS-REC        PIC X(10).
       WORKING-STORAGE SECTION.
       01 EMP-STATUS      PIC XX.
       01 FIX-STATUS      PIC XX.
       01 MISS-STATUS     PIC XX.
       01 EOF-SW          PIC X VALUE "N".
          88 EOF          VALUE "Y".
       01 TOTAL-SAL       PIC 9(8)V99 VALUE 0.
       01 REC-COUNT       PIC 999 VALUE 0.
       01 DETAIL-LINE.
          05 DL-ID        PIC Z(3)9.
          05 FILLER       PIC X(2) VALUE SPACES.
          05 DL-NAME      PIC X(12).
          05 DL-DEPT      PIC X(6).
          05 DL-SAL       PIC $$$,$$9.99.
       01 TOTAL-LINE.
          05 FILLER       PIC X(18) VALUE "TOTAL SALARIES:".
          05 TL-TOT       PIC $$,$$$,$$9.99.
       01 I               PIC 99.
       PROCEDURE DIVISION.
       MAIN.
           OPEN OUTPUT EMP-FILE.
           DISPLAY "OPEN OUTPUT STATUS: " EMP-STATUS.
           MOVE 1001 TO EMP-ID. MOVE "ALICE" TO EMP-NAME.
           MOVE "ENG" TO EMP-DEPT. MOVE 85000.00 TO EMP-SALARY.
           WRITE EMP-REC.
           MOVE 1002 TO EMP-ID. MOVE "BOB" TO EMP-NAME.
           MOVE "SALE" TO EMP-DEPT. MOVE 62500.50 TO EMP-SALARY.
           WRITE EMP-REC.
           MOVE 1003 TO EMP-ID. MOVE "CAROL" TO EMP-NAME.
           MOVE "ENG" TO EMP-DEPT. MOVE 91250.75 TO EMP-SALARY.
           WRITE EMP-REC.
           CLOSE EMP-FILE.
           OPEN INPUT EMP-FILE.
           OPEN OUTPUT RPT-FILE.
           PERFORM UNTIL EOF
               READ EMP-FILE
                   AT END SET EOF TO TRUE
                   NOT AT END PERFORM PROCESS-EMP
               END-READ
           END-PERFORM.
           DISPLAY "READ AT END STATUS: " EMP-STATUS.
           MOVE TOTAL-SAL TO TL-TOT.
           WRITE RPT-LINE FROM TOTAL-LINE AFTER ADVANCING 2 LINES.
           CLOSE EMP-FILE RPT-FILE.
           DISPLAY "RECORDS: " REC-COUNT " TOTAL: " TOTAL-SAL.
           OPEN OUTPUT FIX-FILE.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3
               COMPUTE FIX-KEY = I * 100
               COMPUTE FIX-AMT = I * -12.5
               MOVE "ITEM" TO FIX-NAME
               MOVE I TO FIX-NAME(5:1)
               WRITE FIX-REC
           END-PERFORM.
           CLOSE FIX-FILE.
           OPEN I-O FIX-FILE.
           READ FIX-FILE.
           READ FIX-FILE.
           ADD 1000 TO FIX-AMT.
           REWRITE FIX-REC.
           DISPLAY "REWRITE STATUS: " FIX-STATUS.
           CLOSE FIX-FILE.
           OPEN INPUT FIX-FILE.
           MOVE "N" TO EOF-SW.
           PERFORM UNTIL EOF
               READ FIX-FILE
                   AT END SET EOF TO TRUE
                   NOT AT END
                       DISPLAY "FIX: " FIX-KEY " " FIX-AMT " " FIX-NAME
               END-READ
           END-PERFORM.
           CLOSE FIX-FILE.
           OPEN EXTEND EMP-FILE.
           MOVE 1004 TO EMP-ID. MOVE "DAVE" TO EMP-NAME.
           MOVE "OPS" TO EMP-DEPT. MOVE 50000 TO EMP-SALARY.
           WRITE EMP-REC.
           CLOSE EMP-FILE.
           OPEN INPUT EMP-FILE.
           MOVE 0 TO REC-COUNT.
           MOVE "N" TO EOF-SW.
           PERFORM UNTIL EOF
               READ EMP-FILE AT END SET EOF TO TRUE
                   NOT AT END ADD 1 TO REC-COUNT
               END-READ
           END-PERFORM.
           CLOSE EMP-FILE.
           DISPLAY "AFTER EXTEND: " REC-COUNT " RECORDS".
           OPEN INPUT MISSING-FILE.
           DISPLAY "MISSING FILE STATUS: " MISS-STATUS.
           STOP RUN.
       PROCESS-EMP.
           ADD 1 TO REC-COUNT.
           ADD EMP-SALARY TO TOTAL-SAL.
           MOVE EMP-ID TO DL-ID.
           MOVE EMP-NAME TO DL-NAME.
           MOVE EMP-DEPT TO DL-DEPT.
           MOVE EMP-SALARY TO DL-SAL.
           WRITE RPT-LINE FROM DETAIL-LINE.
