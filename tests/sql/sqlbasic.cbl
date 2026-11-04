      *> Embedded SQL: CONNECT, DDL, INSERT with host variables, an
      *> indicator variable for a null, a host structure, a VARCHAR,
      *> SELECT INTO (one row, no row, too many rows, a null with no
      *> indicator), a cursor, SQLCODE 100 for an UPDATE that changes
      *> nothing, a duplicate key, a missing table, SQLERRD(3).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLBASIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01 DBNAME       PIC X(200).
       01 EMP-REC.
          05 EMP-ID    PIC 9(4).
          05 EMP-NAME  PIC X(20).
          05 SALARY    PIC S9(7)V99 COMP-3.
          05 DEPT      PIC X(4).
       01 IND-DEPT     PIC S9(4) COMP-5.
       01 CNT          PIC S9(9) COMP-5.
       01 TOTAL        PIC S9(9)V99.
       01 MIN-SAL      PIC S9(7)V99 VALUE 1000.
       01 VNAME.
          49 VNAME-LEN  PIC S9(4) COMP-5.
          49 VNAME-TEXT PIC X(8).
       01 SHORT-NAME   PIC X(3).
           EXEC SQL END DECLARE SECTION END-EXEC.
       01 SHOW-SAL     PIC Z,ZZZ,ZZ9.99-.
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT EMP_ID, NAME, SALARY, DEPT FROM EMP
               WHERE SALARY >= :MIN-SAL ORDER BY EMP_ID
           END-EXEC.
       PROCEDURE DIVISION.
           ACCEPT DBNAME FROM ENVIRONMENT 'SQLTEST_DB'
           EXEC SQL CONNECT TO :DBNAME END-EXEC
           DISPLAY 'connect ' SQLCODE
           EXEC SQL DROP TABLE IF EXISTS EMP END-EXEC
           EXEC SQL CREATE TABLE EMP (EMP_ID INTEGER PRIMARY KEY,
                NAME VARCHAR(20) NOT NULL, SALARY NUMERIC(9,2),
                DEPT CHAR(4))
           END-EXEC
           DISPLAY 'create ' SQLCODE
           MOVE 1 TO EMP-ID
           MOVE 'Ada' TO EMP-NAME
           MOVE 1500.50 TO SALARY
           MOVE 'R&D' TO DEPT
           EXEC SQL INSERT INTO EMP VALUES (:EMP-ID, :EMP-NAME,
                :SALARY, :DEPT) END-EXEC
           DISPLAY 'insert ' SQLCODE ' rows ' SQLERRD(3)
           MOVE 2 TO EMP-ID
           MOVE 'Grace' TO EMP-NAME
           MOVE 900 TO SALARY
           MOVE -1 TO IND-DEPT
           EXEC SQL INSERT INTO EMP VALUES (:EMP-ID, :EMP-NAME,
                :SALARY, :DEPT:IND-DEPT) END-EXEC
           DISPLAY 'insert a null ' SQLCODE
           EXEC SQL INSERT INTO EMP VALUES (:EMP-REC) END-EXEC
           DISPLAY 'duplicate key ' SQLCODE ' ' SQLSTATE
           MOVE 3 TO EMP-ID
           MOVE 'Alan' TO EMP-NAME
           MOVE 2500 TO SALARY
           MOVE 'OPS' TO DEPT
           EXEC SQL INSERT INTO EMP VALUES (:EMP-REC) END-EXEC
           DISPLAY 'insert a structure ' SQLCODE
           MOVE 'Barbara' TO VNAME-TEXT
           MOVE 7 TO VNAME-LEN
           EXEC SQL INSERT INTO EMP VALUES (4, :VNAME, 3000, 'R&D')
           END-EXEC
           DISPLAY 'insert a VARCHAR ' SQLCODE
           EXEC SQL SELECT COUNT(*), SUM(SALARY) INTO :CNT, :TOTAL
                FROM EMP END-EXEC
           DISPLAY 'count ' SQLCODE ' ' CNT ' ' TOTAL
           EXEC SQL SELECT NAME, DEPT INTO :EMP-NAME, :DEPT:IND-DEPT
                FROM EMP WHERE EMP_ID = 2 END-EXEC
           DISPLAY 'select ' SQLCODE ' [' EMP-NAME '] ind ' IND-DEPT
           EXEC SQL SELECT NAME INTO :VNAME FROM EMP WHERE EMP_ID = 4
           END-EXEC
           DISPLAY 'into a VARCHAR [' VNAME-TEXT '] ' VNAME-LEN
           EXEC SQL SELECT NAME INTO :SHORT-NAME:IND-DEPT FROM EMP
                WHERE EMP_ID = 4 END-EXEC
           DISPLAY 'cut short ' SQLCODE ' [' SHORT-NAME '] ind '
               IND-DEPT ' warn ' SQLWARN0 SQLWARN1
           EXEC SQL SELECT NAME INTO :EMP-NAME FROM EMP
                WHERE EMP_ID = 99 END-EXEC
           DISPLAY 'no row ' SQLCODE ' ' SQLSTATE
           EXEC SQL SELECT NAME INTO :EMP-NAME FROM EMP END-EXEC
           DISPLAY 'more than one row ' SQLCODE ' ' SQLSTATE
           EXEC SQL SELECT DEPT INTO :DEPT FROM EMP WHERE EMP_ID = 2
           END-EXEC
           DISPLAY 'null, no indicator ' SQLCODE ' ' SQLSTATE
           EXEC SQL SELECT NAME INTO :SALARY FROM EMP WHERE EMP_ID = 1
           END-EXEC
           DISPLAY 'not a number ' SQLCODE
           EXEC SQL SELECT SALARY * 100000 INTO :SALARY FROM EMP
                WHERE EMP_ID = 4 END-EXEC
           DISPLAY 'out of range ' SQLCODE
           EXEC SQL OPEN C1 END-EXEC
           DISPLAY 'open ' SQLCODE
           EXEC SQL OPEN C1 END-EXEC
           DISPLAY 'open again ' SQLCODE
           PERFORM WITH TEST AFTER UNTIL SQLCODE NOT = 0
               EXEC SQL FETCH C1 INTO :EMP-ID, :EMP-NAME, :SALARY,
                    :DEPT:IND-DEPT END-EXEC
               IF SQLCODE = 0
                   MOVE SALARY TO SHOW-SAL
                   DISPLAY '  ' EMP-ID ' ' EMP-NAME ' ' SHOW-SAL ' '
                       DEPT ' ' IND-DEPT
               END-IF
           END-PERFORM
           DISPLAY 'fetch end ' SQLCODE
           EXEC SQL FETCH C1 INTO :EMP-ID END-EXEC
           DISPLAY 'fetch again ' SQLCODE
           EXEC SQL CLOSE C1 END-EXEC
           EXEC SQL CLOSE C1 END-EXEC
           DISPLAY 'close again ' SQLCODE
           EXEC SQL UPDATE EMP SET SALARY = SALARY * 2
                WHERE EMP_ID > 5 END-EXEC
           DISPLAY 'update nothing ' SQLCODE
           EXEC SQL UPDATE EMP SET SALARY = SALARY + 1
                WHERE DEPT = 'R&D' END-EXEC
           DISPLAY 'update ' SQLCODE ' rows ' SQLERRD(3)
           EXEC SQL INSERT INTO EMP VALUES (5, NULL, 1, 'X') END-EXEC
           DISPLAY 'not null column ' SQLCODE
           EXEC SQL SELECT * FROM NO_SUCH_TABLE END-EXEC
           DISPLAY 'no such table ' SQLCODE
           EXEC SQL SELECT NO_SUCH_COLUMN INTO :CNT FROM EMP END-EXEC
           DISPLAY 'no such column ' SQLCODE
           EXEC SQL SELEKT 1 END-EXEC
           DISPLAY 'syntax error ' SQLCODE
           EXEC SQL SELECT COUNT(*) INTO :CNT FROM EMP END-EXEC
           DISPLAY 'still in the unit of work ' SQLCODE ' ' CNT
           EXEC SQL SELECT EMP_ID INTO :EMP-ID FROM EMP
                ORDER BY EMP_ID DESC FETCH FIRST 1 ROW ONLY WITH UR
           END-EXEC
           DISPLAY 'FETCH FIRST ' SQLCODE ' ' EMP-ID
           EXEC SQL SELECT CURRENT DATE INTO :DBNAME
                FROM EMP WHERE EMP_ID = 1 END-EXEC
           DISPLAY 'CURRENT DATE ' SQLCODE ' ' DBNAME(5:1) DBNAME(8:1)
           MOVE 4 TO CNT
           EXEC SQL SELECT NAME INTO :EMP-NAME FROM EMP
                WHERE EMP_ID = :CNT- 1 FOR UPDATE OF SALARY END-EXEC
           DISPLAY 'a minus, FOR UPDATE ' SQLCODE ' ' EMP-NAME
           MOVE '  Ada' TO EMP-NAME
           EXEC SQL UPDATE EMP SET NAME = :EMP-NAME WHERE EMP_ID = 1
           END-EXEC
           EXEC SQL SELECT COUNT(*) INTO :CNT FROM EMP
                WHERE NAME = '  Ada' END-EXEC
           DISPLAY 'leading spaces kept ' SQLCODE ' ' CNT
           EXEC SQL COMMIT END-EXEC
           DISPLAY 'commit ' SQLCODE
           STOP RUN.
