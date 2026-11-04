      * SET pointer UP BY / DOWN BY moves the address by that many bytes:
      * walking a table with a pointer, and the arithmetic on NULL
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PTRSTEP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TBL.
          05 ENT PIC X(4) OCCURS 4.
       01 PG.
          05 P USAGE POINTER.
       01 PN REDEFINES PG PIC 9(18) COMP-5.
       01 N PIC 9(4) VALUE 32.
       01 I PIC 9.
       LINKAGE SECTION.
       01 L PIC X(4).
       PROCEDURE DIVISION.
           MOVE "AAAABBBBCCCCDDDD" TO TBL.
           SET P TO ADDRESS OF TBL.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 4
               SET ADDRESS OF L TO P
               DISPLAY I " " L
               SET P UP BY LENGTH OF ENT
           END-PERFORM.
           SET P DOWN BY 8.
           SET ADDRESS OF L TO P.
           DISPLAY "BACK " L.
           SET P TO NULL.
           DISPLAY PN.
           SET P UP BY 16.
           DISPLAY PN.
           SET P UP BY N.
           DISPLAY PN.
           SET P DOWN BY 8.
           DISPLAY PN.
           STOP RUN.
