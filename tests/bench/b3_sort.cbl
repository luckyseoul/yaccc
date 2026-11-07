       IDENTIFICATION DIVISION.
       PROGRAM-ID. B3SORT.
      *> internal SORT of a table, 200000 keys
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 T.
          05 ENT OCCURS 200000 TIMES.
             10 E PIC 9(9).
       01 I PIC 9(9) COMP.
       01 S PIC 9(18) COMP.
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 200000
               COMPUTE E(I) = FUNCTION MOD(I * 7919, 200003)
           END-PERFORM
           SORT ENT DESCENDING KEY E
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 200000
               ADD E(I) TO S
           END-PERFORM
           DISPLAY S.
           STOP RUN.
