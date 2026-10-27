       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISC1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77 COUNTER       PIC 9(3) VALUE 0.
       77 SCALED-UP     PIC 999PPP VALUE 0.
       77 SCALED-DN     PIC VPPP999 VALUE 0.
       77 RESULT        PIC 9(9)V9(6).
       77 F1            COMP-1 VALUE 0.
       77 F2            COMP-2 VALUE 0.
       77 FLAG-A        PIC X VALUE "Y".
       77 FLAG-B        PIC X VALUE "N".
       01 TBL.
          05 T-ENTRY OCCURS 5 TIMES INDEXED BY TX.
             10 T-KEY   PIC X(3).
             10 T-VAL   PIC 9(3).
       01 SPOS           PIC 99.
       01 ED1           PIC ZZZ9.99-.
       01 ED2           PIC $$$9.99.
       01 NUM           PIC S9(5)V99.
       01 PK            PIC S9(9)V99 COMP-3 VALUE 0.
       01 I             PIC 99.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 123000 TO SCALED-UP.
           DISPLAY "SCALED-UP: " SCALED-UP.
           COMPUTE RESULT = SCALED-UP + 1.
           DISPLAY "SCALED-UP + 1: " RESULT.
           MOVE 0.000123 TO SCALED-DN.
           COMPUTE RESULT = SCALED-DN * 1000000.
           DISPLAY "SCALED-DN * 1E6: " RESULT.
           PERFORM 1000-INIT THRU 1000-EXIT.
           PERFORM 2000-NESTED-IF.
           MOVE 2.5 TO F1.
           COMPUTE F2 = F1 * 4 + 0.25.
           COMPUTE RESULT = F2.
           DISPLAY "FLOAT CALC: " RESULT.
           COMPUTE F2 = 1 / 8.
           MOVE F2 TO RESULT.
           DISPLAY "FLOAT MOVE: " RESULT.
           SET TX TO 1.
           MOVE 1 TO SPOS.
           SEARCH T-ENTRY VARYING SPOS
               AT END DISPLAY "NOT FOUND"
               WHEN T-KEY(TX) = "CCC"
                   DISPLAY "FOUND CCC AT " SPOS " VAL " T-VAL(TX)
           END-SEARCH.
           MOVE -42.5 TO NUM.
           MOVE NUM TO ED1.
           MOVE ED1 TO ED2.
           DISPLAY "EDIT TO EDIT: [" ED1 "] -> [" ED2 "]".
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10
               ADD 1234567.89 TO PK
           END-PERFORM.
           DISPLAY "PACKED SUM: " PK.
           SUBTRACT 99999999.99 FROM PK.
           DISPLAY "PACKED NEG: " PK.
           IF PK < 0 AND PK > -99999999
               DISPLAY "PACKED COMPARE OK".
           STOP RUN.
       1000-INIT.
           PERFORM VARYING TX FROM 1 BY 1 UNTIL TX > 5
               MOVE FUNCTION CHAR(65 + TX) TO T-KEY(TX)(1:1)
               MOVE T-KEY(TX)(1:1) TO T-KEY(TX)(2:1) T-KEY(TX)(3:1)
               SET COUNTER TO TX
               COMPUTE T-VAL(TX) = COUNTER * 111
           END-PERFORM.
           IF COUNTER > 3
               GO TO 1000-EXIT.
           DISPLAY "NOT REACHED".
       1000-EXIT.
           EXIT.
       2000-NESTED-IF.
           IF FLAG-A = "Y"
               IF FLAG-B = "Y"
                   DISPLAY "BOTH Y"
               ELSE
                   DISPLAY "A ONLY"
                   IF COUNTER = 5
                       DISPLAY "COUNTER FIVE"
                   ELSE
                       NEXT SENTENCE
               ELSE
                   DISPLAY "NEITHER".
           DISPLAY "AFTER OLD-STYLE IF".
