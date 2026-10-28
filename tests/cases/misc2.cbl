       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISC2 AS "misc2-main".
      * EBCDIC alphabet with table SORT ... SEQUENCE, OCCURS KEY naming
      * the element, SORT without a key name, PROGRAM-ID AS, RETURN-CODE
      * across CALLs, EXIT PROGRAM RETURNING, boolean literals.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           ALPHABET EBC IS EBCDIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  G           VALUE "d4B2e1a3C5".
           05  TBL     PIC X OCCURS 10.
       01  G2          VALUE "3142".
           05  T2      PIC X OCCURS 4 ASCENDING KEY T2.
       PROCEDURE DIVISION.
           SORT TBL ASCENDING SEQUENCE EBC
           DISPLAY G
           SORT TBL DESCENDING
           DISPLAY G
           SORT TBL ASCENDING KEY TBL
           DISPLAY G
           SORT T2
           DISPLAY G2
           DISPLAY B"101" " " BX"FF"
           CALL "sub-a"
           DISPLAY "after sub-a: " RETURN-CODE
           CALL "SUB-B"
           DISPLAY "after sub-b: " RETURN-CODE
           MOVE 0 TO RETURN-CODE
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBA AS "sub-a".
       PROCEDURE DIVISION.
           EXIT PROGRAM RETURNING 7.
       END PROGRAM SUBA.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB-B.
       PROCEDURE DIVISION.
           DISPLAY "in sub-b: " RETURN-CODE
           GOBACK.
       END PROGRAM SUB-B.
       END PROGRAM MISC2.
