      * -std=ibm: an alphanumeric MOVE whose receiving bytes begin
      * inside the sending ones copies a byte at a time, left to right,
      * as IBM's MVC instruction does: the old way to clear a record.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MVCIBM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC             PIC X(20) VALUE "ABCDEFGHIJKLMNOPQRST".
       01 TBL.
          05 T-ENTRY      PIC X(4) OCCURS 5 VALUE "....".
       01 X10             PIC X(10).
       01 G.
          05 G-HEAD       PIC X(3) VALUE "<->".
          05 G-BODY       PIC X(9) VALUE "123456789".
       01 G-ALL REDEFINES G PIC X(12).
       PROCEDURE DIVISION.
           MOVE SPACE TO REC (1:1)
           MOVE REC (1:19) TO REC (2:19)
           DISPLAY "[" REC "]"
           MOVE "*" TO REC (1:1)
           MOVE REC TO REC (2:19)
           DISPLAY "[" REC "]"
           MOVE "AB12" TO T-ENTRY (1)
           MOVE TBL (1:16) TO TBL (5:16)
           DISPLAY "[" TBL "]"
           MOVE "0123456789" TO X10
           MOVE X10 (3:8) TO X10 (1:8)
           DISPLAY "[" X10 "]"
           MOVE G-ALL TO G-BODY
           DISPLAY "[" G-ALL "]"
           STOP RUN.
