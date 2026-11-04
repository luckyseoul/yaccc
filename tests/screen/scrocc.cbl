      * SPDX-License-Identifier: MIT
      * OCCURS in SCREEN SECTION: a group repeated on the lines below,
      * its FROM and USING items given the occurrence number as their
      * subscript; two levels of OCCURS; ACCEPT through the occurrences.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCROCC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ORDER-TAB.
          03 ORDER-LINE OCCURS 3.
             05 OL-ITEM PIC X(6).
             05 OL-QTY  PIC 9(3).
       01 GRID-TAB.
          03 GRID-ROW OCCURS 2.
             05 GRID-CELL PIC X OCCURS 3.
       01 WS-I    PIC 9.
       01 WS-L    PIC 99.
       SCREEN SECTION.
       01 ORDER-SCR.
          03 LINE 1 COL 1 VALUE "Item   Qty".
          03 OL OCCURS 3 LINE + 1.
             05 COL 1 PIC X(6) USING OL-ITEM.
             05 COL + 2 PIC ZZ9 USING OL-QTY.
       01 GRID-SCR LINE 6.
          03 GRID-R OCCURS 2 LINE + 1.
             05 GRID-C OCCURS 3 COL + 1 PIC X FROM GRID-CELL.
       PROCEDURE DIVISION.
           MOVE "BOLT  005NUT   010WASHER100" TO ORDER-TAB
           MOVE "abcdef" TO GRID-TAB
           DISPLAY ORDER-SCR
           DISPLAY GRID-SCR
      *    Tab to the first quantity, type over it, Tab to the second
      *    item, clear it and type another
           ACCEPT ORDER-SCR
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               COMPUTE WS-L = 10 + WS-I
               DISPLAY OL-ITEM(WS-I) LINE WS-L COL 1 "/" OL-QTY(WS-I)
           END-PERFORM
           STOP RUN.
