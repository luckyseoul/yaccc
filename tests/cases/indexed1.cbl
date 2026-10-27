       IDENTIFICATION DIVISION.
       PROGRAM-ID. INDEXED1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO "accounts.idx"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS ACCT-ID
               ALTERNATE RECORD KEY IS ACCT-OWNER WITH DUPLICATES
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD ACCT-FILE.
       01 ACCT-REC.
          05 ACCT-ID       PIC 9(5).
          05 ACCT-OWNER    PIC X(10).
          05 ACCT-BAL      PIC S9(7)V99.
       WORKING-STORAGE SECTION.
       01 FS              PIC XX.
       01 EOF-SW          PIC X VALUE "N".
          88 EOF          VALUE "Y".
       01 I               PIC 99.
       01 IDS-DATA.
          05 FILLER PIC X(20) VALUE "30000SMITH     00100".
          05 FILLER PIC X(20) VALUE "10000JONES     00250".
          05 FILLER PIC X(20) VALUE "50000SMITH     00075".
          05 FILLER PIC X(20) VALUE "20000BROWN     01000".
          05 FILLER PIC X(20) VALUE "40000ADAMS     00500".
       01 IDS REDEFINES IDS-DATA.
          05 ID-ENTRY OCCURS 5 TIMES.
             10 IE-ID    PIC 9(5).
             10 IE-OWNER PIC X(10).
             10 IE-BAL   PIC 9(5).
       PROCEDURE DIVISION.
           OPEN OUTPUT ACCT-FILE.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               MOVE IE-ID(I) TO ACCT-ID
               MOVE IE-OWNER(I) TO ACCT-OWNER
               MOVE IE-BAL(I) TO ACCT-BAL
               WRITE ACCT-REC
                   INVALID KEY DISPLAY "DUP ON WRITE " ACCT-ID
               END-WRITE
           END-PERFORM.
           MOVE 10000 TO ACCT-ID.
           WRITE ACCT-REC INVALID KEY DISPLAY "DUPLICATE KEY " FS.
           CLOSE ACCT-FILE.
           OPEN I-O ACCT-FILE.
           DISPLAY "SEQUENTIAL READ BY PRIMARY KEY:".
           PERFORM UNTIL EOF
               READ ACCT-FILE NEXT RECORD
                   AT END SET EOF TO TRUE
                   NOT AT END DISPLAY "  " ACCT-ID " " ACCT-OWNER " "
                                     ACCT-BAL
               END-READ
           END-PERFORM.
           MOVE 30000 TO ACCT-ID.
           READ ACCT-FILE KEY IS ACCT-ID
               INVALID KEY DISPLAY "NOT FOUND"
               NOT INVALID KEY DISPLAY "RANDOM READ: " ACCT-OWNER
           END-READ.
           MOVE 99999 TO ACCT-ID.
           READ ACCT-FILE
               INVALID KEY DISPLAY "99999 NOT FOUND, FS=" FS
           END-READ.
           MOVE 20000 TO ACCT-ID.
           READ ACCT-FILE.
           ADD 50 TO ACCT-BAL.
           REWRITE ACCT-REC INVALID KEY DISPLAY "REWRITE FAILED".
           DISPLAY "REWRITE FS=" FS.
           MOVE 40000 TO ACCT-ID.
           DELETE ACCT-FILE RECORD INVALID KEY DISPLAY "DELETE FAILED".
           DISPLAY "DELETE FS=" FS.
           MOVE 25000 TO ACCT-ID.
           START ACCT-FILE KEY IS GREATER THAN ACCT-ID
               INVALID KEY DISPLAY "START FAILED".
           MOVE "N" TO EOF-SW.
           DISPLAY "FROM KEY > 25000:".
           PERFORM UNTIL EOF
               READ ACCT-FILE NEXT
                   AT END SET EOF TO TRUE
                   NOT AT END DISPLAY "  " ACCT-ID " " ACCT-OWNER
               END-READ
           END-PERFORM.
           MOVE "SMITH" TO ACCT-OWNER.
           START ACCT-FILE KEY IS EQUAL TO ACCT-OWNER
               INVALID KEY DISPLAY "START ALT FAILED".
           MOVE "N" TO EOF-SW.
           DISPLAY "BY OWNER FROM SMITH:".
           PERFORM UNTIL EOF
               READ ACCT-FILE NEXT
                   AT END SET EOF TO TRUE
                   NOT AT END DISPLAY "  " ACCT-OWNER " " ACCT-ID
               END-READ
           END-PERFORM.
           MOVE "BROWN" TO ACCT-OWNER.
           READ ACCT-FILE KEY IS ACCT-OWNER
               INVALID KEY DISPLAY "ALT NOT FOUND".
           DISPLAY "READ BY ALT KEY BROWN: " ACCT-ID " " ACCT-BAL.
           CLOSE ACCT-FILE.
           OPEN INPUT ACCT-FILE.
           MOVE "N" TO EOF-SW.
           DISPLAY "AFTER REOPEN:".
           PERFORM UNTIL EOF
               READ ACCT-FILE NEXT
                   AT END SET EOF TO TRUE
                   NOT AT END DISPLAY "  " ACCT-ID " " ACCT-BAL
               END-READ
           END-PERFORM.
           CLOSE ACCT-FILE.
           STOP RUN.
