      * ASSIGN: a literal, a word that names no data item (the file
      * keeps the word as written), a data item that holds the name,
      * and ASSIGN EXTERNAL / DYNAMIC, which say which of these it is.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASSIGN1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F-LIT ASSIGN TO "literal.txt"
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-WORD ASSIGN TO payroll
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-ITEM ASSIGN TO WS-NAME
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-EXT ASSIGN TO EXTERNAL WS-NAME
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-DYN ASSIGN TO DYNAMIC WS-NAME
               ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F-LIT.
       01 R-LIT PIC X(10).
       FD F-WORD.
       01 R-WORD PIC X(10).
       FD F-ITEM.
       01 R-ITEM PIC X(10).
       FD F-EXT.
       01 R-EXT PIC X(10).
       FD F-DYN.
       01 R-DYN PIC X(10).
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(12) VALUE "item.txt".
       PROCEDURE DIVISION.
           OPEN OUTPUT F-LIT
           WRITE R-LIT FROM "literal"
           CLOSE F-LIT
           OPEN OUTPUT F-WORD
           WRITE R-WORD FROM "word"
           CLOSE F-WORD
           OPEN OUTPUT F-ITEM
           WRITE R-ITEM FROM "item"
           CLOSE F-ITEM
           OPEN OUTPUT F-EXT
           WRITE R-EXT FROM "external"
           CLOSE F-EXT
           MOVE "dynamic.txt" TO WS-NAME
           OPEN OUTPUT F-DYN
           WRITE R-DYN FROM "dynamic"
           CLOSE F-DYN
           DISPLAY "DONE"
           STOP RUN.
