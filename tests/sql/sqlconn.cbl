      *> Embedded SQL: CONNECT as DB2 writes it (TO ... AS name) and as
      *> Oracle and OCESQL do (user IDENTIFIED BY password USING db),
      *> SET CONNECTION, DISCONNECT and DISCONNECT ALL, SQLCODE and
      *> SQLSTATE declared on their own, a called program with a cursor
      *> of the same name and an SQLCA of its own, CONNECT RESET.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLCONN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SQLCODE  PIC S9(9) COMP.
       01 SQLSTATE PIC X(5).
       01 USR PIC X(10) VALUE SPACES.
       01 PWD PIC X(10) VALUE SPACES.
       01 DB  PIC X(200).
       01 N   PIC 9(4).
       01 V   PIC X(10).
           EXEC SQL DECLARE C CURSOR FOR SELECT V FROM T1 END-EXEC.
       PROCEDURE DIVISION.
           ACCEPT DB FROM ENVIRONMENT 'SQLTEST_DB'
           EXEC SQL CONNECT :USR IDENTIFIED BY :PWD USING :DB
           END-EXEC
           DISPLAY 'connect ' SQLCODE ' ' SQLSTATE
           EXEC SQL DROP TABLE IF EXISTS T1 END-EXEC
           EXEC SQL DROP TABLE IF EXISTS T2 END-EXEC
           EXEC SQL CREATE TABLE T1 (V VARCHAR(10)) END-EXEC
           EXEC SQL CREATE TABLE T2 (V VARCHAR(10)) END-EXEC
           EXEC SQL INSERT INTO T1 VALUES ('one') END-EXEC
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CONNECT TO :DB AS SECOND END-EXEC
           DISPLAY 'connect as SECOND ' SQLCODE
           EXEC SQL INSERT INTO T2 VALUES ('two') END-EXEC
           EXEC SQL SELECT V INTO :V FROM T1 END-EXEC
           DISPLAY 'SECOND reads T1 [' V ']'
           EXEC SQL COMMIT END-EXEC
           EXEC SQL SET CONNECTION DEFAULT END-EXEC
           DISPLAY 'set connection ' SQLCODE
           EXEC SQL SELECT V INTO :V FROM T2 END-EXEC
           DISPLAY 'DEFAULT reads T2 [' V ']'
           EXEC SQL SET CONNECTION NOSUCH END-EXEC
           DISPLAY 'no such connection ' SQLCODE ' ' SQLSTATE
           EXEC SQL DISCONNECT SECOND END-EXEC
           DISPLAY 'disconnect SECOND ' SQLCODE
           EXEC SQL DISCONNECT SECOND END-EXEC
           DISPLAY 'again ' SQLCODE
           EXEC SQL OPEN C END-EXEC
           EXEC SQL FETCH C INTO :V END-EXEC
           DISPLAY 'main fetched [' V ']'
           CALL 'SQLCONN2'
           EXEC SQL FETCH C INTO :V END-EXEC
           DISPLAY 'main fetched ' SQLCODE
           EXEC SQL CLOSE C END-EXEC
           IF SQLCODE = 0
               EXEC SQL SELECT COUNT(*) INTO :N FROM T1 END-EXEC
               DISPLAY 'inside IF ' N
           END-IF
           EXEC SQL CONNECT RESET END-EXEC
           DISPLAY 'connect reset ' SQLCODE
           EXEC SQL CONNECT TO :DB END-EXEC
           EXEC SQL DISCONNECT ALL END-EXEC
           DISPLAY 'disconnect all ' SQLCODE
           STOP RUN.
       END PROGRAM SQLCONN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLCONN2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 V   PIC X(10).
           EXEC SQL DECLARE C CURSOR FOR SELECT V FROM T2 END-EXEC.
       PROCEDURE DIVISION.
           EXEC SQL OPEN C END-EXEC
           EXEC SQL FETCH C INTO :V END-EXEC
           DISPLAY 'called program fetched [' V '] ' SQLCODE ' '
               SQLSTATE
           EXEC SQL CLOSE C END-EXEC
           GOBACK.
       END PROGRAM SQLCONN2.
