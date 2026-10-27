       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 D2U        PIC 9(3)V99.
       01 D2S        PIC S9(3)V99.
       01 D0S        PIC S9(4).
       01 D0U        PIC 9(4).
       01 P4E        PIC S9(4) COMP-3.
       01 P5O        PIC S9(5)V99 COMP-3.
       01 P3U        PIC 9(3) COMP-3.
       01 B4         PIC S9(4) COMP.
       01 B9U        PIC 9(9) COMP.
       01 B18        PIC S9(18) COMP.
       01 C5         PIC S9(4) COMP-5.
       01 D18        PIC S9(16)V99.
       01 I          PIC 99.
       01 VALS.
          05 V       PIC S9(5)V999 OCCURS 8.
       PROCEDURE DIVISION.
           MOVE 1.005 TO V(1). MOVE -1.005 TO V(2).
           MOVE 999.999 TO V(3).
           MOVE -999.999 TO V(4). MOVE 12345.678 TO V(5).
           MOVE -0.004 TO V(6). MOVE 0.005 TO V(7). MOVE -2.5 TO V(8).
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 8
               MOVE V(I) TO D2U D2S D0S D0U P4E P5O P3U B4 B9U C5
               DISPLAY "MOVE " V(I) ": " D2U " " D2S " " D0S " " D0U
                       " " P4E " " P5O " " P3U " " B4 " " B9U " " C5
               COMPUTE D2U ROUNDED = V(I)
               COMPUTE D2S ROUNDED = V(I)
               COMPUTE D0S ROUNDED = V(I)
               COMPUTE P4E ROUNDED = V(I)
               COMPUTE P5O ROUNDED = V(I) * 3
               COMPUTE B4 ROUNDED = V(I) * 10
               DISPLAY "  ROUNDED: " D2U " " D2S " " D0S " " P4E
                       " " P5O " " B4
               ADD V(I) TO D0S P5O B4
               SUBTRACT V(I) FROM D2S P3U B9U
               MULTIPLY V(I) BY D2U P4E C5
               DISPLAY "  ARITH: " D0S " " P5O " " B4 " " D2S " " P3U
                       " " B9U " " D2U " " P4E " " C5
               ADD V(I) 1 2.5 TO D2S ROUNDED
               SUBTRACT V(I) 1 FROM 50 GIVING D2U ROUNDED
               MULTIPLY V(I) BY -3 GIVING P5O ROUNDED
               DISPLAY "  GIVING: " D2S " " D2U " " P5O
           END-PERFORM.
           MOVE 999999999999999999 TO B18.
           ADD 1 TO B18.
           DISPLAY "B18 WRAP: " B18.
           MOVE 123456789012345.67 TO D18.
           COMPUTE D18 = D18 * 3 + D18 / 2.
           DISPLAY "D18: " D18.
           MOVE 99999999.99 TO V(1).
           MOVE V(1) TO D18.
           COMPUTE D18 = D18 * D18.
           DISPLAY "D18 BIG: " D18.
           COMPUTE D0S = 12345 * 2.
           DISPLAY "D0S TRUNC: " D0S.
           COMPUTE D0U = -5 - 7.
           DISPLAY "D0U ABS: " D0U.
           MOVE 9999 TO C5.
           ADD 30000 TO C5.
           DISPLAY "C5 WRAP: " C5.
           MOVE 1.005 TO V(1).
           IF V(1) > V(2) AND V(3) = 999.999 AND V(6) < 0
              AND V(7) >= 0.005
               DISPLAY "COMPARES OK"
           END-IF.
           IF D2S = -12.3 DISPLAY "EQ" ELSE DISPLAY "NE" END-IF.
           STOP RUN.
