      *****************************************************************
      * BANK - account ledger on an INDEXED file.
      *   1. Loads the account master (primary key ACCT-NO, alternate
      *      key ACCT-NAME WITH DUPLICATES).
      *   2. Posts deposits (D), withdrawals (W) and transfers (T)
      *      from TRANSACTIONS.DAT, rejecting invalid ones.
      *   3. Lists accounts by number and by owner name.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNTS ASSIGN TO "accounts.idx"
                  ORGANIZATION IS INDEXED
                  ACCESS MODE IS DYNAMIC
                  RECORD KEY IS ACCT-NO
                  ALTERNATE RECORD KEY IS ACCT-NAME WITH DUPLICATES
                  FILE STATUS IS ACCT-STATUS.
           SELECT TRANS-FILE ASSIGN TO "transactions.dat"
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS IS TRANS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNTS.
       01  ACCT-REC.
           05  ACCT-NO            PIC 9(5).
           05  ACCT-NAME          PIC X(16).
           05  ACCT-TYPE          PIC X.
               88  CHECKING       VALUE "C".
               88  SAVINGS        VALUE "S".
           05  ACCT-BALANCE       PIC S9(9)V99 COMP-3.
           05  ACCT-TXN-COUNT     PIC 9(4) COMP.
       FD  TRANS-FILE.
       01  TRANS-REC.
           05  TR-CODE            PIC X.
               88  TR-DEPOSIT     VALUE "D".
               88  TR-WITHDRAW    VALUE "W".
               88  TR-TRANSFER    VALUE "T".
               88  TR-VALID       VALUE "D" "W" "T".
           05  TR-ACCT            PIC 9(5).
           05  TR-AMOUNT          PIC 9(9)V99.
           05  TR-TO-ACCT         PIC 9(5).
           05  FILLER             PIC X(5).
           05  TR-MEMO            PIC X(20).
       WORKING-STORAGE SECTION.
       01  ACCT-STATUS            PIC XX.
           88  ACCT-OK            VALUE "00".
           88  ACCT-NOT-FOUND     VALUE "23".
       01  TRANS-STATUS           PIC XX.
       01  WS-EOF                 PIC X VALUE "N".
           88  EOF                VALUE "Y".
       01  WS-COUNTS.
           05  WS-POSTED          PIC 9(3) VALUE 0.
           05  WS-REJECTED        PIC 9(3) VALUE 0.
       01  WS-REASON              PIC X(24).
       01  WS-SAVE-REC            PIC X(30).
       01  WS-TOTAL               PIC S9(11)V99 VALUE 0.
       01  WS-AMT-ED              PIC ZZZ,ZZZ,ZZ9.99-.
       01  WS-BAL-ED              PIC $$$,$$$,$$9.99-.
       01  INITIAL-DATA.
           05  FILLER PIC X(31) VALUE "10001Hopper, Grace   C000120000".
           05  FILLER PIC X(31) VALUE "10002Turing, Alan    C000015000".
           05  FILLER PIC X(31) VALUE "10003Hopper, Grace   S000500000".
           05  FILLER PIC X(31) VALUE "10004Lovelace, Ada   C000008000".
           05  FILLER PIC X(31) VALUE "10005Turing, Alan    S000250000".
       01  INIT-TABLE REDEFINES INITIAL-DATA.
           05  INIT-ENTRY OCCURS 5 TIMES INDEXED BY IX.
               10  IN-NO          PIC 9(5).
               10  IN-NAME        PIC X(16).
               10  IN-TYPE        PIC X.
               10  IN-BAL         PIC 9(7)V99.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM LOAD-ACCOUNTS
           PERFORM POST-TRANSACTIONS
           PERFORM LIST-BY-NUMBER
           PERFORM LIST-BY-NAME
           STOP RUN.

       LOAD-ACCOUNTS.
           OPEN OUTPUT ACCOUNTS
           PERFORM VARYING IX FROM 1 BY 1 UNTIL IX > 5
               MOVE IN-NO(IX)   TO ACCT-NO
               MOVE IN-NAME(IX) TO ACCT-NAME
               MOVE IN-TYPE(IX) TO ACCT-TYPE
               MOVE IN-BAL(IX)  TO ACCT-BALANCE
               MOVE 0           TO ACCT-TXN-COUNT
               WRITE ACCT-REC
                   INVALID KEY DISPLAY "DUPLICATE ACCOUNT " ACCT-NO
               END-WRITE
           END-PERFORM
           CLOSE ACCOUNTS.

       POST-TRANSACTIONS.
           DISPLAY "TRANSACTION LOG"
           DISPLAY "---------------"
           OPEN I-O ACCOUNTS
           OPEN INPUT TRANS-FILE
           PERFORM UNTIL EOF
               READ TRANS-FILE
                   AT END SET EOF TO TRUE
                   NOT AT END PERFORM APPLY-TRANSACTION
               END-READ
           END-PERFORM
           CLOSE TRANS-FILE ACCOUNTS
           DISPLAY "POSTED: " WS-POSTED "  REJECTED: " WS-REJECTED
           DISPLAY SPACE.

       APPLY-TRANSACTION.
           MOVE SPACES TO WS-REASON
           MOVE TR-AMOUNT TO WS-AMT-ED
           IF NOT TR-VALID
               MOVE "INVALID TRANSACTION CODE" TO WS-REASON
           ELSE
               MOVE TR-ACCT TO ACCT-NO
               READ ACCOUNTS
                   INVALID KEY MOVE "ACCOUNT NOT FOUND" TO WS-REASON
               END-READ
           END-IF
           IF WS-REASON = SPACES
               EVALUATE TRUE
                   WHEN TR-DEPOSIT
                       ADD TR-AMOUNT TO ACCT-BALANCE
                       PERFORM UPDATE-ACCOUNT
                   WHEN TR-WITHDRAW
                       IF TR-AMOUNT > ACCT-BALANCE
                           MOVE "INSUFFICIENT FUNDS" TO WS-REASON
                       ELSE
                           SUBTRACT TR-AMOUNT FROM ACCT-BALANCE
                           PERFORM UPDATE-ACCOUNT
                       END-IF
                   WHEN TR-TRANSFER
                       PERFORM TRANSFER-FUNDS
               END-EVALUATE
           END-IF
           IF WS-REASON = SPACES
               ADD 1 TO WS-POSTED
               DISPLAY "  OK   " TR-CODE " " TR-ACCT " " WS-AMT-ED
                       "  " TR-MEMO
           ELSE
               ADD 1 TO WS-REJECTED
               DISPLAY "  REJ  " TR-CODE " " TR-ACCT " " WS-AMT-ED
                       "  " WS-REASON
           END-IF.

       TRANSFER-FUNDS.
           IF TR-AMOUNT > ACCT-BALANCE
               MOVE "INSUFFICIENT FUNDS" TO WS-REASON
           ELSE
               MOVE ACCT-REC TO WS-SAVE-REC
               MOVE TR-TO-ACCT TO ACCT-NO
               READ ACCOUNTS
                   INVALID KEY MOVE "TARGET NOT FOUND" TO WS-REASON
               END-READ
               IF WS-REASON = SPACES
                   ADD TR-AMOUNT TO ACCT-BALANCE
                   PERFORM UPDATE-ACCOUNT
                   MOVE WS-SAVE-REC TO ACCT-REC
                   SUBTRACT TR-AMOUNT FROM ACCT-BALANCE
                   PERFORM UPDATE-ACCOUNT
               END-IF
           END-IF.

       UPDATE-ACCOUNT.
           ADD 1 TO ACCT-TXN-COUNT
           REWRITE ACCT-REC
               INVALID KEY MOVE "REWRITE FAILED" TO WS-REASON
           END-REWRITE.

       LIST-BY-NUMBER.
           DISPLAY "ACCOUNTS BY NUMBER"
           DISPLAY "------------------"
           MOVE 0 TO WS-TOTAL
           MOVE "N" TO WS-EOF
           OPEN INPUT ACCOUNTS
           PERFORM UNTIL EOF
               READ ACCOUNTS NEXT
                   AT END SET EOF TO TRUE
                   NOT AT END
                       ADD ACCT-BALANCE TO WS-TOTAL
                       MOVE ACCT-BALANCE TO WS-BAL-ED
                       DISPLAY "  " ACCT-NO "  " ACCT-NAME " "
                               ACCT-TYPE " " WS-BAL-ED "  ("
                               ACCT-TXN-COUNT " TXN)"
               END-READ
           END-PERFORM
           CLOSE ACCOUNTS
           MOVE WS-TOTAL TO WS-BAL-ED
           DISPLAY "  TOTAL ON DEPOSIT:         " WS-BAL-ED
           DISPLAY SPACE.

       LIST-BY-NAME.
           DISPLAY "ACCOUNTS BY OWNER (ALTERNATE KEY)"
           DISPLAY "---------------------------------"
           MOVE "N" TO WS-EOF
           OPEN INPUT ACCOUNTS
           MOVE LOW-VALUES TO ACCT-NAME
           START ACCOUNTS KEY IS GREATER THAN OR EQUAL TO ACCT-NAME
               INVALID KEY SET EOF TO TRUE
           END-START
           PERFORM UNTIL EOF
               READ ACCOUNTS NEXT
                   AT END SET EOF TO TRUE
                   NOT AT END
                       MOVE ACCT-BALANCE TO WS-BAL-ED
                       EVALUATE TRUE
                           WHEN CHECKING
                               DISPLAY "  " ACCT-NAME " CHECKING "
                                       ACCT-NO " " WS-BAL-ED
                           WHEN SAVINGS
                               DISPLAY "  " ACCT-NAME " SAVINGS  "
                                       ACCT-NO " " WS-BAL-ED
                       END-EVALUATE
               END-READ
           END-PERFORM
           CLOSE ACCOUNTS.
