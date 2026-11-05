      * Tables with OCCURS DEPENDING ON that are not at the end of
      * their record ("complex ODO"): which take their current size,
      * where the items after them are, what INITIALIZE touches.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOCX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I               PIC 9 VALUE 2.
       01 N               PIC 99.
      * each table ends its group: the groups after it follow its end
       01 G-1             VALUE "123456789".
          02 G-2.
             03 X         PIC X OCCURS 1 TO 3 DEPENDING ON I.
          02 G-3.
             03 G-4.
                04 X      PIC X OCCURS 1 TO 3 DEPENDING ON I.
             03 G-5.
                04 X      PIC X OCCURS 1 TO 3 DEPENDING ON I.
      * a table with an item after it in its group keeps its maximum
       01 R               VALUE "ABCDEFGH".
          05 A            PIC X OCCURS 1 TO 3 DEPENDING ON I.
          05 B            PIC X(2).
      * ... but a group that ends with one does not
       01 S               VALUE "ABCDEFGH".
          05 G.
             10 C         PIC X OCCURS 1 TO 3 DEPENDING ON I.
          05 D            PIC X(2).
      * three tables in a row: only the last one varies
       01 VTOP.
          03 VGROUP.
             05 VX        OCCURS 1 TO 5 DEPENDING ON I.
                10 VXX    PIC X.
             05 VY        OCCURS 1 TO 5 DEPENDING ON I.
                10 VYY    PIC XX.
             05 ZZ        OCCURS 1 TO 5 DEPENDING ON I.
                10 VZZ    PIC XXX.
      * the same with a fixed item at the end: none of them varies
       01 WTOP.
          03 WGROUP.
             05 WX        PIC X OCCURS 1 TO 5 DEPENDING ON I.
             05 WY        PIC X OCCURS 1 TO 5 DEPENDING ON I.
             05 WFIX      PIC X(3).
      * a DEPENDING ON item in each element of a table (cobc 3.1.2
      * counts every element with the first one's: only ROW (1) here)
       01 TBL.
          05 ROW          OCCURS 3.
             10 RN        PIC 9.
             10 RC        PIC X OCCURS 1 TO 5 DEPENDING ON RN.
      * INITIALIZE gives a table the occurrences it has now
       01 C5              PIC 9 VALUE 5.
       01 IR.
          05 IA           PIC X(2) VALUE "AB"
                          OCCURS 1 TO 5 DEPENDING ON C5.
      * ... unless the group holds its own counter
       01 OWN.
          05 OC           PIC 9 VALUE 3.
          05 OA           PIC X(2) VALUE "AB"
                          OCCURS 0 TO 5 DEPENDING ON OC.
       PROCEDURE DIVISION.
           DISPLAY G-1 ":" G-4 ":" G-5 ":" G-2 ":" G-3
           MOVE LENGTH OF G-1 TO N
           DISPLAY "LENGTH OF G-1 " N
           DISPLAY R ":" B
           MOVE LENGTH OF R TO N
           DISPLAY "LENGTH OF R " N
           DISPLAY S ":" D ":" G
           MOVE LENGTH OF S TO N
           DISPLAY "LENGTH OF S " N
           MOVE 1 TO I
           MOVE "1" TO VXX (1)
           MOVE "22" TO VYY (1)
           MOVE "333" TO VZZ (1)
           MOVE LENGTH OF VGROUP TO N
           DISPLAY N "[" VGROUP "]"
           MOVE ALL "-" TO WGROUP
           MOVE "W" TO WX (1)
           MOVE "V" TO WY (1)
           MOVE "FIX" TO WFIX
           MOVE LENGTH OF WGROUP TO N
           DISPLAY N "[" WGROUP "]"
           MOVE ALL "A" TO TBL
           MOVE 2 TO RN (1)
           MOVE 4 TO RN (2)
           MOVE "Q" TO RC (2, 4)
           MOVE LENGTH OF ROW (1) TO N
           DISPLAY "[" ROW (1) "] " N
           MOVE ALL "*" TO IR
           MOVE 2 TO C5
           INITIALIZE IR
           MOVE 5 TO C5
           DISPLAY "[" IR "]"
           MOVE ALL "*" TO IR
           MOVE 2 TO C5
           INITIALIZE IR ALL TO VALUE
           MOVE 5 TO C5
           DISPLAY "[" IR "]"
           MOVE 5 TO OC
           MOVE ALL "*" TO OWN
           MOVE 3 TO OC
           INITIALIZE OWN
           MOVE 5 TO OC
           DISPLAY "[" OWN "]"
           MOVE 1 TO OC
           MOVE "1ABCDEFGHIJKL" TO OWN
           DISPLAY "[" OWN "]"
           STOP RUN.
