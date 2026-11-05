      * -std=ibm: a PERFORM returns wherever control reaches the end
      * of its range, even with a later PERFORM still active, and the
      * intermediate results of arithmetic are cut as OS/VS cut them.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OSVSIBM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MYOCC             PIC 9(4) COMP VALUE 0.
       01 HITS              PIC 9(4) COMP VALUE 0.
       01 NUM-A             PIC 9(3) VALUE 399.
       01 NUM-B             PIC 9(3) VALUE 211.
       01 NUMV1             PIC 9(3)V9.
       01 RSLT              PIC 9(3).
       01 RSLTV1            PIC 9(3).9.
       01 RSLTV2            PIC 9(3).99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM BTEST
           DISPLAY "BACK FROM BTEST " MYOCC
           PERFORM CTEST THRU CTEST-EXIT
           DISPLAY "BACK FROM CTEST " HITS
           COMPUTE RSLTV2, RSLT = ((NUM-A / 100) - (NUM-B / 100)) * 100
           DISPLAY "RSLT " RSLT " RSLTV2 " RSLTV2
           COMPUTE RSLTV1, RSLT = ((NUM-A / 100) - (NUM-B / 100)) * 100
           DISPLAY "RSLT " RSLT " RSLTV1 " RSLTV1
           MOVE NUM-A TO NUMV1
           IF ((NUMV1 / (101 - 1)) - (NUM-B / (10 * 10))) * 100 = 188
              DISPLAY "CONDITION AT FULL PRECISION"
           ELSE
              DISPLAY "CONDITION CUT AS OS/VS"
           END-IF
           STOP RUN.
       BTEST SECTION.
       B01.
           PERFORM B02 VARYING MYOCC FROM 1 BY 1
                   UNTIL MYOCC > 5.
           GO TO B99.
       B02.
           IF MYOCC > 1
              GO TO B99
           END-IF.
       B99.
           EXIT.
       CTEST SECTION.
       C01.
           PERFORM C02.
           DISPLAY "NOT REACHED".
       C02.
           ADD 1 TO HITS.
           GO TO CTEST-EXIT.
       CTEST-EXIT.
           EXIT.
