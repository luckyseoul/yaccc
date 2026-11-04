      *> Embedded SQL without CONNECT: COB_SQL_DATABASE names the
      *> database. The run unit's normal end commits its work; a
      *> runtime error rolls it back. Run as: sqlend setup, sqlend
      *> normal, sqlend abend (which fails), sqlend check.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLEND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WHAT PIC X(10).
       01 N    PIC 9(4).
       01 V    PIC X(10).
       01 TB.
          05 E PIC X OCCURS 2.
       01 I    PIC 9 VALUE 5.
           EXEC SQL DECLARE C CURSOR FOR SELECT V FROM T ORDER BY V
           END-EXEC.
       PROCEDURE DIVISION.
           ACCEPT WHAT FROM ARGUMENT-VALUE
           EVALUATE WHAT
             WHEN 'setup'
               EXEC SQL DROP TABLE IF EXISTS T END-EXEC
               EXEC SQL CREATE TABLE T (V VARCHAR(10)) END-EXEC
               DISPLAY 'setup ' SQLCODE
             WHEN 'normal'
               EXEC SQL INSERT INTO T VALUES ('normal') END-EXEC
               DISPLAY 'normal ' SQLCODE
             WHEN 'abend'
               EXEC SQL INSERT INTO T VALUES ('abend') END-EXEC
               DISPLAY 'abend ' SQLCODE
               MOVE 'x' TO E(I)
             WHEN OTHER
               EXEC SQL SELECT COUNT(*) INTO :N FROM T END-EXEC
               DISPLAY 'rows ' N
               EXEC SQL OPEN C END-EXEC
               PERFORM WITH TEST AFTER UNTIL SQLCODE NOT = 0
                   EXEC SQL FETCH C INTO :V END-EXEC
                   IF SQLCODE = 0
                       DISPLAY 'row ' V
                   END-IF
               END-PERFORM
           END-EVALUATE
           STOP RUN.
