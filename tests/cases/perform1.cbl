       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFORM1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I          PIC 99.
       01 J          PIC 99.
       01 K          PIC S99.
       01 CNT        PIC 999 VALUE 0.
       01 N          PIC 9 VALUE 3.
       01 TRACE-LINE PIC X(60) VALUE SPACES.
       01 PTR        PIC 99 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "START".
           PERFORM PARA-A.
           PERFORM PARA-A THRU PARA-C.
           PERFORM PARA-B 3 TIMES.
           PERFORM PARA-B N TIMES.
           MOVE 0 TO CNT.
           PERFORM PARA-INC UNTIL CNT >= 5.
           DISPLAY "CNT AFTER UNTIL: " CNT.
           MOVE 10 TO CNT.
           PERFORM PARA-INC WITH TEST AFTER UNTIL CNT >= 5.
           DISPLAY "CNT AFTER TEST AFTER: " CNT.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               DISPLAY "I=" I WITH NO ADVANCING
               DISPLAY " "
           END-PERFORM.
           DISPLAY "I AFTER LOOP: " I.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3
                   AFTER J FROM 1 BY 1 UNTIL J > 2
               DISPLAY "I=" I " J=" J
           END-PERFORM.
           DISPLAY "AFTER NESTED: I=" I " J=" J.
           PERFORM PARA-IJ VARYING K FROM 10 BY -3 UNTIL K < 1.
           PERFORM VARYING K FROM -2 BY 1 UNTIL K > 2
               IF K = 0
                   EXIT PERFORM CYCLE
               END-IF
               DISPLAY "K=" K
           END-PERFORM.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 100
               IF I = 4
                   EXIT PERFORM
               END-IF
           END-PERFORM.
           DISPLAY "EXITED AT I=" I.
           PERFORM 2 TIMES
               DISPLAY "INLINE TIMES"
           END-PERFORM.
           PERFORM
               DISPLAY "INLINE ONCE"
           END-PERFORM.
           PERFORM SEC-ONE.
           PERFORM PARA-X IN SEC-TWO.
           PERFORM PARA-GO.
           PERFORM PARA-NESTED.
           PERFORM PARA-EXIT-PARA.
           MOVE 2 TO N.
           GO TO PARA-D1 PARA-D2 PARA-D3 DEPENDING ON N.
           DISPLAY "GO TO DEPENDING FELL THROUGH".
       PARA-D1.
           DISPLAY "D1".
           GO TO PARA-END.
       PARA-D2.
           DISPLAY "D2".
           GO TO PARA-END.
       PARA-D3.
           DISPLAY "D3".
       PARA-END.
           DISPLAY "END".
           STOP RUN.
       PARA-A.
           DISPLAY "IN A".
       PARA-B.
           DISPLAY "IN B".
       PARA-C.
           DISPLAY "IN C".
       PARA-INC.
           ADD 1 TO CNT.
       PARA-IJ.
           DISPLAY "IJ K=" K.
       PARA-GO.
           DISPLAY "GO START".
           GO TO PARA-GO-2.
           DISPLAY "NEVER".
       PARA-GO-2.
           DISPLAY "GO TARGET".
       PARA-NESTED.
           PERFORM PARA-A.
           PERFORM VARYING J FROM 1 BY 1 UNTIL J > 2
               PERFORM PARA-B
           END-PERFORM.
       PARA-EXIT-PARA.
           DISPLAY "BEFORE EXIT PARAGRAPH".
           IF N = 3
               EXIT PARAGRAPH
           END-IF.
           DISPLAY "AFTER EXIT PARAGRAPH".
       SEC-ONE SECTION.
       PARA-X.
           DISPLAY "SEC-ONE PARA-X".
       PARA-Y.
           DISPLAY "SEC-ONE PARA-Y".
           IF N = 3
               NEXT SENTENCE
           END-IF
           DISPLAY "NOT SKIPPED".
           DISPLAY "AFTER NEXT SENTENCE".
       SEC-TWO SECTION.
       PARA-X.
           DISPLAY "SEC-TWO PARA-X".
