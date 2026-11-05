      * -fodoslide: every table with OCCURS DEPENDING ON takes its
      * current size and what follows it moves up: IBM's layout. A
      * record of counts and variable segments is written to a file.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOSL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO "odosl.txt"
               ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC.
           05 OUT-ID        PIC X(4).
           05 OUT-N1        PIC 9.
           05 OUT-ITEM      PIC X(3) OCCURS 0 TO 4
                            DEPENDING ON OUT-N1.
           05 OUT-N2        PIC 9.
           05 OUT-NOTE      PIC X(2) OCCURS 0 TO 3
                            DEPENDING ON OUT-N2.
           05 OUT-END       PIC X.
       WORKING-STORAGE SECTION.
       01 I                 PIC 9 VALUE 2.
       01 J                 PIC 9 VALUE 2.
       01 K                 PIC 9 VALUE 2.
       01 N                 PIC 99.
       01 M                 PIC 9 VALUE 3.
       01 NN                PIC 9 VALUE 2.
       01 R                 VALUE "ABCDEFGH".
          05 A              PIC X OCCURS 1 TO 3 DEPENDING ON I.
          05 B              PIC X(2).
       01 VGROUP.
          05 VX             OCCURS 1 TO 5 DEPENDING ON I.
             10 VXX         PIC X.
          05 VY             OCCURS 1 TO 5 DEPENDING ON J.
             10 VYY         PIC XX.
          05 ZZ             OCCURS 1 TO 5 DEPENDING ON K.
             10 VZZ         PIC XXX.
          05 VFIX           PIC X(3).
       01 A-TABLE           VALUE "ABCDEFGHIJ".
          03 ROWS           OCCURS 0 TO 2 TIMES DEPENDING ON NN.
             05 CHARS       PIC X OCCURS 0 TO 5 TIMES
                            DEPENDING ON M.
       01 VALS              PIC X(3).
       PROCEDURE DIVISION.
           DISPLAY R ":" B
           MOVE LENGTH OF R TO N
           DISPLAY "LENGTH OF R " N
           MOVE 1 TO I J K
           MOVE "1" TO VXX (1)
           MOVE "22" TO VYY (1)
           MOVE "333" TO VZZ (1)
           MOVE "444" TO VFIX
           MOVE LENGTH OF VGROUP TO N
           DISPLAY N "[" VGROUP "]"
           INITIALIZE VGROUP
           MOVE 3 TO I
           MOVE 2 TO J
           MOVE "3" TO VXX (3)
           MOVE "22" TO VYY (2)
           MOVE "111" TO VZZ (1)
           MOVE "000" TO VFIX
           MOVE LENGTH OF VGROUP TO N
           DISPLAY N "[" VGROUP "]"
           MOVE CHARS (1, 2) TO VALS (1:1)
           MOVE CHARS (2, 1) TO VALS (2:1)
           MOVE CHARS (2, 3) TO VALS (3:1)
           DISPLAY VALS ":" A-TABLE
           OPEN OUTPUT OUT-FILE
           MOVE "REC1" TO OUT-ID
           MOVE 2 TO OUT-N1
           MOVE "AAA" TO OUT-ITEM (1)
           MOVE "BBB" TO OUT-ITEM (2)
           MOVE 1 TO OUT-N2
           MOVE "xx" TO OUT-NOTE (1)
           MOVE "!" TO OUT-END
           WRITE OUT-REC
           MOVE "REC2" TO OUT-ID
           MOVE 0 TO OUT-N1
           MOVE 3 TO OUT-N2
           MOVE "aa" TO OUT-NOTE (1)
           MOVE "bb" TO OUT-NOTE (2)
           MOVE "cc" TO OUT-NOTE (3)
           MOVE "?" TO OUT-END
           WRITE OUT-REC
           CLOSE OUT-FILE
           STOP RUN.
