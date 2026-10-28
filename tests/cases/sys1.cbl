       IDENTIFICATION DIVISION.
       PROGRAM-ID. sys1.
      * Library routines, exception functions, CALL scope and
      * recursion checks.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT NOFILE ASSIGN TO "no-such-file.dat"
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD NOFILE.
       01 NOREC PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 X PIC X(4) VALUE "0000".
       01 Z PIC X(4) VALUE X"01010101".
       01 J PIC X(6) VALUE "  OK  ".
       01 U PIC X(6) VALUE "abcdef".
       01 P PIC X(5) VALUE "A" & X"01" & "B" & X"7F" & "C".
       01 NA PIC 9 BINARY.
       01 CB PIC X(8).
       01 FH PIC X(4) COMP-X.
       01 OFS PIC X(8) COMP-X.
       01 CNT PIC X(4) COMP-X.
       01 BUF PIC X(12).
       01 INFO PIC X(16).
       01 C2 PIC X(2) COMP-X VALUE 513.
       01 C5 PIC X(4) COMP-5 VALUE 70000.
       01 D9 PIC 9(9).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "[" FUNCTION EXCEPTION-STATUS "]"
           CALL "CBL_OR" USING X Z BY VALUE LENGTH OF Z
           CALL "CBL_XOR" USING X Z BY VALUE 2
           DISPLAY "[" Z "]"
           CALL "C$JUSTIFY" USING J "L"
           DISPLAY "[" J "]"
           CALL "C$JUSTIFY" USING J "R"
           DISPLAY "[" J "]"
           CALL "C$TOUPPER" USING U BY VALUE 3
           CALL "C$PRINTABLE" USING P
           DISPLAY "[" U "] [" P "]"
           CALL "C$NARG" USING NA
           CALL "C$CALLEDBY" USING CB
           DISPLAY NA " [" CB "] " RETURN-CODE
           MOVE C2 TO D9
           DISPLAY D9 " " C5
           CALL "CBL_CREATE_DIR" USING "sys1dir"
           DISPLAY "mkdir " RETURN-CODE
           CALL "CBL_CREATE_FILE" USING "sys1dir/f.txt" 2 0 0 FH
           MOVE 0 TO OFS
           MOVE 11 TO CNT
           CALL "CBL_WRITE_FILE" USING FH OFS CNT 0 "hello world"
           CALL "CBL_CLOSE_FILE" USING FH
           CALL "CBL_OPEN_FILE" USING "sys1dir/f.txt" 1 0 0 FH
           MOVE 6 TO OFS
           MOVE 12 TO CNT
           MOVE SPACES TO BUF
           CALL "CBL_READ_FILE" USING FH OFS CNT 0 BUF
           DISPLAY "read " RETURN-CODE " [" BUF "]"
           CALL "CBL_CLOSE_FILE" USING FH
           CALL "CBL_CHECK_FILE_EXIST" USING "sys1dir/f.txt" INFO
           DISPLAY "exists " RETURN-CODE " " FUNCTION ORD(INFO(8:1))
           CALL "CBL_RENAME_FILE" USING "sys1dir/f.txt" "sys1dir/g.txt"
           CALL "CBL_DELETE_FILE" USING "sys1dir/g.txt"
           DISPLAY "delete " RETURN-CODE
           CALL "CBL_DELETE_FILE" USING "sys1dir/g.txt"
           DISPLAY "delete again " RETURN-CODE
           CALL "CBL_DELETE_DIR" USING "sys1dir"
           DISPLAY "rmdir " RETURN-CODE
           OPEN INPUT NOFILE
           DISPLAY FS " [" FUNCTION EXCEPTION-STATUS "]"
           DISPLAY "[" FUNCTION EXCEPTION-STATEMENT "]"
           DISPLAY "[" FUNCTION EXCEPTION-LOCATION "]"
           DISPLAY "[" FUNCTION EXCEPTION-FILE "]"
           CALL "no-such-program"
               ON EXCEPTION DISPLAY "not found: "
                            FUNCTION EXCEPTION-STATUS
           END-CALL
           CALL "INNER"
           CALL "INNER2"
               ON EXCEPTION DISPLAY "INNER2 is not visible"
           END-CALL
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 CB PIC X(8).
       PROCEDURE DIVISION.
           CALL "C$CALLEDBY" USING CB
           DISPLAY "INNER called by [" CB "] " RETURN-CODE
                   " " FUNCTION MODULE-CALLER-ID
           CALL "INNER2"
           EXIT PROGRAM.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER2.
       PROCEDURE DIVISION.
           DISPLAY "INNER2"
           CALL "INNER"
               ON EXCEPTION DISPLAY "recursive: "
                            FUNCTION EXCEPTION-STATUS
           END-CALL
           EXIT PROGRAM.
       END PROGRAM INNER2.
       END PROGRAM INNER.
       END PROGRAM sys1.
