      *****************************************************************
      * WORDFREQ - counts word frequencies in a text file and prints
      * the most frequent words (UNSTRING, INSPECT, SEARCH, table SORT)
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WORDFREQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TEXT-FILE ASSIGN TO "speech.txt"
                  ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  TEXT-FILE.
       01  TEXT-LINE              PIC X(200).
       WORKING-STORAGE SECTION.
       01  WS-EOF                 PIC X VALUE "N".
           88  EOF                VALUE "Y".
       01  WS-PTR                 PIC 999.
       01  WS-WORD                PIC X(30).
       01  WS-LEN                 PIC 99.
       01  WS-TOTAL-WORDS         PIC 9(5) VALUE 0.
       01  WS-LINES               PIC 9(5) VALUE 0.
       01  WORD-COUNT             PIC 999 VALUE 0.
       01  WORD-TABLE.
           05  WORD-ENTRY OCCURS 1 TO 500 TIMES
                   DEPENDING ON WORD-COUNT
                   INDEXED BY WX.
               10  WT-WORD        PIC X(30).
               10  WT-COUNT       PIC 9(4).
       01  RANK                   PIC Z9.
       01  HIST-BAR                    PIC X(20).
       01  I                      PIC 999.
       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT TEXT-FILE
           PERFORM UNTIL EOF
               READ TEXT-FILE
                   AT END SET EOF TO TRUE
                   NOT AT END PERFORM PROCESS-LINE
               END-READ
           END-PERFORM
           CLOSE TEXT-FILE
           SORT WORD-ENTRY ON DESCENDING KEY WT-COUNT
                           ON ASCENDING KEY WT-WORD
           DISPLAY "Lines: " WS-LINES "  Words: " WS-TOTAL-WORDS
                   "  Distinct: " WORD-COUNT
           DISPLAY "Top words:"
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10 OR I > WORD-COUNT
               MOVE I TO RANK
               MOVE ALL "#" TO HIST-BAR
               MOVE SPACES TO HIST-BAR(WT-COUNT(I) + 1:)
               DISPLAY "  " RANK ". " WT-WORD(I)(1:12) " "
                       WT-COUNT(I) " " HIST-BAR
           END-PERFORM
           STOP RUN.

       PROCESS-LINE.
           ADD 1 TO WS-LINES
           INSPECT TEXT-LINE CONVERTING
               "ABCDEFGHIJKLMNOPQRSTUVWXYZ,.;:!?"
            TO "abcdefghijklmnopqrstuvwxyz      "
           MOVE 1 TO WS-PTR
           PERFORM UNTIL WS-PTR > 200
               MOVE SPACES TO WS-WORD
               UNSTRING TEXT-LINE DELIMITED BY ALL SPACE
                   INTO WS-WORD COUNT IN WS-LEN
                   WITH POINTER WS-PTR
               END-UNSTRING
               IF WS-LEN > 0
                   PERFORM COUNT-WORD
               END-IF
           END-PERFORM.

       COUNT-WORD.
           ADD 1 TO WS-TOTAL-WORDS
           SET WX TO 1
           SEARCH WORD-ENTRY
               AT END
                   ADD 1 TO WORD-COUNT
                   MOVE WS-WORD TO WT-WORD(WORD-COUNT)
                   MOVE 1 TO WT-COUNT(WORD-COUNT)
               WHEN WT-WORD(WX) = WS-WORD
                   ADD 1 TO WT-COUNT(WX)
           END-SEARCH.
