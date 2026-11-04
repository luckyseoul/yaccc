      *> Embedded SQL: cursors with UPDATE and DELETE WHERE CURRENT OF,
      *> WITH HOLD across COMMIT, ROLLBACK, WHENEVER (PERFORM, GO TO,
      *> CONTINUE), dynamic SQL (EXECUTE IMMEDIATE, PREPARE with
      *> parameter markers, EXECUTE ... USING, a cursor over a prepared
      *> statement, OPEN ... USING), SET :hv =, VALUES ... INTO, and a
      *> DCLGEN-style host structure brought in by EXEC SQL INCLUDE.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLCURSOR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE EMPDCL END-EXEC.
       01 IND-TAB.
          05 IND PIC S9(4) COMP-5 OCCURS 3.
       01 DBNAME PIC X(200).
       01 TXT PIC X(200).
       01 N   PIC S9(4) COMP-5.
       01 V   PIC X(10).
       01 LIM PIC S9(9) COMP-5.
           EXEC SQL DECLARE CU CURSOR FOR
                SELECT EMP_ID, NAME, SALARY FROM EMP ORDER BY EMP_ID
                FOR UPDATE OF SALARY
           END-EXEC.
           EXEC SQL DECLARE CH CURSOR WITH HOLD FOR
                SELECT EMP_ID FROM EMP ORDER BY EMP_ID
           END-EXEC.
           EXEC SQL DECLARE CN CURSOR FOR
                SELECT EMP_ID FROM EMP ORDER BY EMP_ID
           END-EXEC.
           EXEC SQL DECLARE CD CURSOR FOR DYN END-EXEC.
       PROCEDURE DIVISION.
           ACCEPT DBNAME FROM ENVIRONMENT 'SQLTEST_DB'
           EXEC SQL WHENEVER SQLERROR PERFORM SQL-ERR END-EXEC
           EXEC SQL CONNECT TO :DBNAME END-EXEC
           EXEC SQL EXECUTE IMMEDIATE 'DROP TABLE IF EXISTS EMP'
           END-EXEC
           MOVE 'CREATE TABLE EMP (EMP_ID INTEGER PRIMARY KEY,'
             & ' NAME VARCHAR(20), SALARY NUMERIC(9,2))' TO TXT
           EXEC SQL EXECUTE IMMEDIATE :TXT END-EXEC
           PERFORM VARYING N FROM 1 BY 1 UNTIL N > 4
               COMPUTE EMP-ID = N * 10
               STRING 'emp-' N DELIMITED BY SIZE INTO EMP-NAME-TEXT
               MOVE 8 TO EMP-NAME-LEN
               COMPUTE SALARY = N * 1000.25
               EXEC SQL INSERT INTO EMP (EMP_ID, NAME, SALARY)
                    VALUES (:DCL-EMP) END-EXEC
           END-PERFORM
           EXEC SQL COMMIT END-EXEC
           EXEC SQL WHENEVER NOT FOUND GO TO DONE-UPD END-EXEC
           EXEC SQL OPEN CU END-EXEC
           PERFORM FOREVER
               EXEC SQL FETCH CU INTO :EMP-ID, :EMP-NAME, :SALARY
               END-EXEC
               DISPLAY 'fetched ' EMP-ID ' ['
                   EMP-NAME-TEXT(1:EMP-NAME-LEN) ']'
               IF EMP-ID = 20
                   EXEC SQL UPDATE EMP SET SALARY = 0
                        WHERE CURRENT OF CU END-EXEC
                   DISPLAY '  updated where current ' SQLCODE ' '
                       SQLERRD(3)
               END-IF
               IF EMP-ID = 30
                   EXEC SQL DELETE FROM EMP WHERE CURRENT OF CU
                   END-EXEC
                   DISPLAY '  deleted where current ' SQLCODE
               END-IF
           END-PERFORM.
       DONE-UPD.
           EXEC SQL WHENEVER NOT FOUND CONTINUE END-EXEC
           DISPLAY 'the loop ended at ' SQLCODE
           EXEC SQL CLOSE CU END-EXEC
           EXEC SQL UPDATE EMP SET SALARY = 1 WHERE CURRENT OF CU
           END-EXEC
           EXEC SQL SELECT SALARY INTO :SALARY FROM EMP
                WHERE EMP_ID = 20 END-EXEC
           DISPLAY 'salary of 20: ' SALARY
           EXEC SQL SELECT COUNT(*) INTO :N FROM EMP END-EXEC
           DISPLAY 'rows: ' N
           EXEC SQL ROLLBACK END-EXEC
           EXEC SQL SELECT COUNT(*) INTO :N FROM EMP END-EXEC
           DISPLAY 'rows after ROLLBACK: ' N
           EXEC SQL OPEN CH END-EXEC
           EXEC SQL OPEN CN END-EXEC
           EXEC SQL FETCH CH INTO :LIM END-EXEC
           EXEC SQL FETCH CN INTO :LIM END-EXEC
           EXEC SQL COMMIT END-EXEC
           EXEC SQL FETCH CH INTO :LIM END-EXEC
           DISPLAY 'WITH HOLD after COMMIT: ' SQLCODE ' ' LIM
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC
           EXEC SQL FETCH CN INTO :LIM END-EXEC
           DISPLAY 'without HOLD after COMMIT: ' SQLCODE
           EXEC SQL CLOSE CH END-EXEC
           EXEC SQL WHENEVER SQLERROR PERFORM SQL-ERR END-EXEC
           MOVE 'SELECT EMP_ID, NAME FROM EMP WHERE EMP_ID > ?'
             & ' ORDER BY 1' TO TXT
           EXEC SQL PREPARE DYN FROM :TXT END-EXEC
           MOVE 15 TO LIM
           EXEC SQL OPEN CD USING :LIM END-EXEC
           PERFORM 5 TIMES
               EXEC SQL FETCH CD INTO :EMP-ID, :EMP-NAME END-EXEC
               IF SQLCODE = 0
                   DISPLAY 'dynamic cursor ' EMP-ID ' '
                       EMP-NAME-TEXT(1:EMP-NAME-LEN)
               ELSE
                   DISPLAY 'dynamic cursor ' SQLCODE
               END-IF
           END-PERFORM
           EXEC SQL CLOSE CD END-EXEC
           MOVE 'UPDATE EMP SET NAME = ? WHERE EMP_ID = ?' TO TXT
           EXEC SQL PREPARE UPD FROM :TXT END-EXEC
           MOVE 'renamed' TO EMP-NAME-TEXT
           MOVE 7 TO EMP-NAME-LEN
           MOVE 40 TO EMP-ID
           EXEC SQL EXECUTE UPD USING :EMP-NAME, :EMP-ID END-EXEC
           DISPLAY 'EXECUTE ' SQLCODE ' ' SQLERRD(3)
           EXEC SQL EXECUTE NOT-PREPARED END-EXEC
           EXEC SQL SELECT NAME, SALARY INTO :EMP-NAME, :SALARY
                FROM EMP WHERE EMP_ID = 40 END-EXEC
           DISPLAY 'name of 40 [' EMP-NAME-TEXT '] ' EMP-NAME-LEN
           EXEC SQL SET :V = 'abc' || 'def' END-EXEC
           DISPLAY 'SET ' SQLCODE ' ' V
           EXEC SQL VALUES 6 * 7 INTO :N END-EXEC
           DISPLAY 'VALUES ' N
           MOVE -5 TO IND(3)
           EXEC SQL SELECT EMP_ID, NAME, NULL INTO :DCL-EMP:IND
                FROM EMP WHERE EMP_ID = 10 END-EXEC
           DISPLAY 'a structure ' EMP-ID ' '
               EMP-NAME-TEXT(1:EMP-NAME-LEN) ' indicators ' IND(1)
               ' ' IND(2) ' ' IND(3)
           EXEC SQL INSERT INTO NO_SUCH_TABLE VALUES (1) END-EXEC
           DISPLAY 'after the error ' SQLCODE
           EXEC SQL COMMIT END-EXEC
           EXEC SQL DISCONNECT END-EXEC
           EXEC SQL SELECT 1 INTO :N END-EXEC
           DISPLAY 'after DISCONNECT ' SQLCODE ' ' SQLSTATE
           STOP RUN.
       SQL-ERR.
           DISPLAY 'WHENEVER SQLERROR: ' SQLCODE.
