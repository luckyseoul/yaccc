       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPT1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 NAME         PIC X(20).
       01 AGE          PIC 9(3).
       01 AMOUNT       PIC 9(5)V99.
       01 NUM-IN       PIC X(10).
       01 N            PIC S9(5).
       01 TOTAL        PIC S9(7) VALUE 0.
       01 EOF-FLAG     PIC X VALUE "N".
       PROCEDURE DIVISION.
           DISPLAY "Enter name: " WITH NO ADVANCING.
           ACCEPT NAME.
           DISPLAY "Enter age: " WITH NO ADVANCING.
           ACCEPT AGE.
           ACCEPT AMOUNT.
           DISPLAY "Hello, " FUNCTION TRIM(NAME) "! Age " AGE
                   " Amount " AMOUNT.
           PERFORM 3 TIMES
               ACCEPT NUM-IN
               MOVE FUNCTION NUMVAL(NUM-IN) TO N
               ADD N TO TOTAL
           END-PERFORM.
           DISPLAY "TOTAL: " TOTAL.
           STOP RUN.
