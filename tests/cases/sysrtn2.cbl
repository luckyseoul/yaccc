      *> Library routines: CBL_ALLOC_MEM and CBL_FREE_MEM, X"F4" and
      *> X"F5" (bits to a byte and back), CBL_GET_SCR_SIZE (from LINES
      *> and COLUMNS, which sysrtn2.env sets, when the output is no
      *> terminal), CBL_EXIT_PROC: install, query, set a priority, and
      *> the procedures run at STOP RUN, highest priority first.
      *> GnuCOBOL 3.1 has no CBL_ALLOC_MEM and its CBL_EXIT_PROC takes
      *> its parameters otherwise: the expected output is checked by hand.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYSRTN2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MEM-PTR    USAGE POINTER.
       01 MEM-SIZE   PIC X(4) COMP-5 VALUE 64.
       01 FLAGS      PIC X(4) COMP-5 VALUE 0.
       01 STATUS-CODE PIC S9(9) COMP-5.
       01 EXIT-PARAMS.
          05 EXIT-PTR  USAGE PROCEDURE-POINTER.
          05 EXIT-PRIO PIC X COMP-X.
       01 EXIT-PARAMS2.
          05 EXIT-PTR2 USAGE PROCEDURE-POINTER.
          05 EXIT-PRIO2 PIC X COMP-X.
       01 BYTE1      PIC X COMP-X.
       01 BITS.
          05 ONEBIT  PIC X COMP-X OCCURS 8.
       01 I          PIC 9.
       01 ROWS-N     PIC X COMP-X.
       01 COLS-N     PIC X COMP-X.
       LINKAGE SECTION.
       01 MEMBLK     PIC X(64).
       PROCEDURE DIVISION.
           CALL "CBL_ALLOC_MEM" USING MEM-PTR BY VALUE MEM-SIZE FLAGS
               RETURNING STATUS-CODE
           DISPLAY "alloc " STATUS-CODE
           SET ADDRESS OF MEMBLK TO MEM-PTR
           IF MEMBLK = LOW-VALUES
               DISPLAY "the memory is zeros"
           END-IF
           MOVE "hello" TO MEMBLK
           DISPLAY "memory [" MEMBLK(1:5) "]"
           CALL "CBL_FREE_MEM" USING BY VALUE MEM-PTR
               RETURNING STATUS-CODE
           DISPLAY "free " STATUS-CODE
           MOVE 5 TO BYTE1
           CALL X"F5" USING BYTE1 BITS
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 8
               DISPLAY ONEBIT(I) " " NO ADVANCING
           END-PERFORM
           DISPLAY "unpacked"
           MOVE 1 TO ONEBIT(1)
           CALL X"F4" USING BYTE1 BITS
           DISPLAY "packed " BYTE1
           CALL "CBL_GET_SCR_SIZE" USING ROWS-N COLS-N
           DISPLAY "screen " ROWS-N " x " COLS-N
           SET EXIT-PTR TO ENTRY "SYSRTN2X"
           CALL "CBL_EXIT_PROC" USING X"00" EXIT-PARAMS
               RETURNING STATUS-CODE
           DISPLAY "exit procedure installed " STATUS-CODE
           SET EXIT-PTR2 TO ENTRY "SYSRTN2Y"
           MOVE 200 TO EXIT-PRIO2
           CALL "CBL_EXIT_PROC" USING X"03" EXIT-PARAMS2
           CALL "CBL_EXIT_PROC" USING X"02" EXIT-PARAMS
           DISPLAY "its priority " EXIT-PRIO
           CALL "CBL_EXIT_PROC" USING X"01" EXIT-PARAMS
               RETURNING STATUS-CODE
           DISPLAY "removed " STATUS-CODE
           CALL "CBL_EXIT_PROC" USING X"01" EXIT-PARAMS
               RETURNING STATUS-CODE
           DISPLAY "removed again " STATUS-CODE
           CALL "CBL_EXIT_PROC" USING X"00" EXIT-PARAMS
           DISPLAY "STOP RUN"
           STOP RUN.
       END PROGRAM SYSRTN2.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYSRTN2X.
       PROCEDURE DIVISION.
           DISPLAY "exit procedure, priority 64".
           GOBACK.
       END PROGRAM SYSRTN2X.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYSRTN2Y.
       PROCEDURE DIVISION.
           DISPLAY "exit procedure, priority 200".
           GOBACK.
       END PROGRAM SYSRTN2Y.
