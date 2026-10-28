      * Constants: level 78 with expressions, CONSTANT entries, constants
      * in PICTURE and OCCURS, compilation variables.
       >>DEFINE TABLE-SIZE AS 4
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONST1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       78  NAME-LEN          VALUE 12.
       78  TOTAL-LEN         VALUE NAME-LEN * 2 + 3.
       78  HALF-LEN          VALUE TOTAL-LEN / 2.
       78  GREETING          VALUE "HELLO".
       78  GREET-LEN         VALUE LENGTH OF "HELLO, WORLD".
       01  MAX-ITEMS CONSTANT AS 5.
       01  TITLE-TEXT CONSTANT AS "CONSTANTS".
       01  NEG-VALUE CONSTANT AS 3 - 10.
       01  WS-REC.
           05  WS-NAME       PIC X(NAME-LEN) VALUE GREETING.
           05  WS-TAB        PIC 9(3) OCCURS MAX-ITEMS.
       01  WS-SMALL.
           05  WS-ENTRY      PIC X(2) OCCURS 3 TO MAX-ITEMS
                                      DEPENDING ON WS-COUNT.
       01  WS-COUNT          PIC 9 VALUE 3.
       01  I                 PIC 99.
       01  RESULT            PIC S9(5)V99.
       PROCEDURE DIVISION.
           DISPLAY NAME-LEN " " TOTAL-LEN " " HALF-LEN " " GREETING
           DISPLAY GREET-LEN " " MAX-ITEMS " " TITLE-TEXT " " NEG-VALUE
           DISPLAY FUNCTION LENGTH(WS-NAME) " " LENGTH OF WS-REC
           DISPLAY "[" WS-NAME "]"
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > MAX-ITEMS
               COMPUTE WS-TAB(I) = I * NAME-LEN
           END-PERFORM
           DISPLAY WS-TAB(1) " " WS-TAB(MAX-ITEMS)
           COMPUTE RESULT = TOTAL-LEN * HALF-LEN + NEG-VALUE
           DISPLAY RESULT
           MOVE MAX-ITEMS TO WS-COUNT
           DISPLAY LENGTH OF WS-SMALL
           IF TOTAL-LEN > NAME-LEN
               DISPLAY "TOTAL-LEN > NAME-LEN"
           END-IF
           STOP RUN.
