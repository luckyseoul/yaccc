       IDENTIFICATION DIVISION.
       PROGRAM-ID. TABLE1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MONTH-NAMES-DATA.
          05 FILLER PIC X(9) VALUE "JANUARY".
          05 FILLER PIC X(9) VALUE "FEBRUARY".
          05 FILLER PIC X(9) VALUE "MARCH".
          05 FILLER PIC X(9) VALUE "APRIL".
       01 MONTH-NAMES REDEFINES MONTH-NAMES-DATA.
          05 MONTH-NAME PIC X(9) OCCURS 4 TIMES INDEXED BY MX.
       01 GRID.
          05 GRID-ROW OCCURS 3 TIMES INDEXED BY RX.
             10 GRID-CELL PIC 99 OCCURS 4 TIMES INDEXED BY CX.
       01 PRODUCTS.
          05 PROD-ENTRY OCCURS 6 TIMES
                ASCENDING KEY IS PROD-CODE
                INDEXED BY PX.
             10 PROD-CODE  PIC X(4).
             10 PROD-PRICE PIC 9(3)V99.
       01 ODO-COUNT       PIC 99 VALUE 3.
       01 ODO-TABLE.
          05 ODO-ITEM PIC X(3) OCCURS 1 TO 10 TIMES
                DEPENDING ON ODO-COUNT.
       01 I               PIC 99.
       01 J               PIC 99.
       01 TOTAL           PIC 9(5).
       01 SEARCH-CODE     PIC X(4).
       01 IDX-VAL         PIC 99.
       01 SCORES.
          05 SCORE PIC 9(3) OCCURS 5 TIMES.
       PROCEDURE DIVISION.
           PERFORM VARYING MX FROM 1 BY 1 UNTIL MX > 4
               DISPLAY "MONTH " MONTH-NAME(MX)
           END-PERFORM.
           DISPLAY "MONTH(2)=" MONTH-NAME(2) " LAST=" MONTH-NAME(4).
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3
               PERFORM VARYING J FROM 1 BY 1 UNTIL J > 4
                   COMPUTE GRID-CELL(I, J) = I * 10 + J
               END-PERFORM
           END-PERFORM.
           MOVE 0 TO TOTAL.
           PERFORM VARYING RX FROM 1 BY 1 UNTIL RX > 3
               PERFORM VARYING CX FROM 1 BY 1 UNTIL CX > 4
                   ADD GRID-CELL(RX CX) TO TOTAL
               END-PERFORM
           END-PERFORM.
           DISPLAY "GRID TOTAL=" TOTAL.
           DISPLAY "GRID ROW 2: " GRID-ROW(2).
           DISPLAY "CELL(3,4)=" GRID-CELL(3, 4).
           SET RX TO 2. SET CX TO 3.
           DISPLAY "CELL(RX,CX+1)=" GRID-CELL(RX, CX + 1).
           SET CX UP BY 1.
           DISPLAY "CELL AFTER UP BY=" GRID-CELL(RX, CX).
           SET CX DOWN BY 2.
           SET IDX-VAL TO CX.
           DISPLAY "IDX VALUE=" IDX-VAL.
           MOVE "A100" TO PROD-CODE(1). MOVE 1.50 TO PROD-PRICE(1).
           MOVE "B200" TO PROD-CODE(2). MOVE 2.75 TO PROD-PRICE(2).
           MOVE "C300" TO PROD-CODE(3). MOVE 10.00 TO PROD-PRICE(3).
           MOVE "D400" TO PROD-CODE(4). MOVE 99.99 TO PROD-PRICE(4).
           MOVE "E500" TO PROD-CODE(5). MOVE 0.01 TO PROD-PRICE(5).
           MOVE "F600" TO PROD-CODE(6). MOVE 123.45 TO PROD-PRICE(6).
           MOVE "D400" TO SEARCH-CODE.
           SET PX TO 1.
           SEARCH PROD-ENTRY
               AT END DISPLAY "NOT FOUND"
               WHEN PROD-CODE(PX) = SEARCH-CODE
                   DISPLAY "SEARCH FOUND " PROD-CODE(PX) " "
                           PROD-PRICE(PX)
           END-SEARCH.
           MOVE "Z999" TO SEARCH-CODE.
           SET PX TO 1.
           SEARCH PROD-ENTRY
               AT END DISPLAY "SEARCH NOT FOUND Z999"
               WHEN PROD-CODE(PX) = SEARCH-CODE
                   DISPLAY "WRONG"
           END-SEARCH.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 6
               MOVE PROD-CODE(I) TO SEARCH-CODE
               SEARCH ALL PROD-ENTRY
                   AT END DISPLAY "BINARY NOT FOUND"
                   WHEN PROD-CODE(PX) = SEARCH-CODE
                       DISPLAY "BINARY FOUND " PROD-CODE(PX) " AT "
                               PROD-PRICE(PX)
               END-SEARCH
           END-PERFORM.
           MOVE "C301" TO SEARCH-CODE.
           SEARCH ALL PROD-ENTRY
               AT END DISPLAY "BINARY NOT FOUND C301"
               WHEN PROD-CODE(PX) = SEARCH-CODE
                   DISPLAY "WRONG"
           END-SEARCH.
           MOVE "AAA" TO ODO-ITEM(1).
           MOVE "BBB" TO ODO-ITEM(2).
           MOVE "CCC" TO ODO-ITEM(3).
           DISPLAY "ODO TABLE: [" ODO-TABLE "]".
           MOVE 2 TO ODO-COUNT.
           DISPLAY "ODO SHRUNK: [" ODO-TABLE "]".
           MOVE FUNCTION LENGTH(ODO-TABLE) TO I.
           DISPLAY "ODO LENGTH: " I.
           MOVE 85 TO SCORE(1). MOVE 92 TO SCORE(2).
           MOVE 78 TO SCORE(3).
           MOVE 95 TO SCORE(4). MOVE 60 TO SCORE(5).
           MOVE FUNCTION SUM(SCORE(1) SCORE(2) SCORE(3) SCORE(4)
                SCORE(5)) TO TOTAL.
           DISPLAY "SUM=" TOTAL.
           STOP RUN.
