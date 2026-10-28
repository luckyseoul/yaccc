       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEPREV.
      * START FIRST / LAST, READ PREVIOUS on indexed and relative
      * files, WRITE FILE ... FROM, DELETE FILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IX-FILE ASSIGN TO "fileprev.idx"
               ORGANIZATION INDEXED ACCESS DYNAMIC
               RECORD KEY IX-KEY
               ALTERNATE RECORD KEY IX-ALT WITH DUPLICATES
               FILE STATUS IX-ST.
           SELECT REL-FILE ASSIGN TO "fileprev.rel"
               ORGANIZATION RELATIVE ACCESS DYNAMIC
               RELATIVE KEY REL-KEY
               FILE STATUS REL-ST.
       DATA DIVISION.
       FILE SECTION.
       FD  IX-FILE.
       01  IX-REC.
           05  IX-KEY      PIC 99.
           05  IX-ALT      PIC X.
           05  IX-DATA     PIC X(5).
       FD  REL-FILE.
       01  REL-REC         PIC X(4).
       WORKING-STORAGE SECTION.
       01  IX-ST           PIC XX.
       01  REL-ST          PIC XX.
       01  REL-KEY         PIC 99.
       01  K               PIC 99.
       01  NEW-REC.
           05  FILLER      PIC 99 VALUE 50.
           05  FILLER      PIC X VALUE "C".
           05  FILLER      PIC X(5) VALUE "fifty".
       PROCEDURE DIVISION.
           DELETE FILE IX-FILE REL-FILE
           DISPLAY "delete missing: " IX-ST " " REL-ST
           OPEN OUTPUT IX-FILE
           PERFORM VARYING K FROM 10 BY 10 UNTIL K > 40
               MOVE K TO IX-KEY
               IF K < 30 MOVE "A" TO IX-ALT ELSE MOVE "B" TO IX-ALT
               END-IF
               MOVE "data" TO IX-DATA
               WRITE IX-REC
           END-PERFORM
           WRITE FILE IX-FILE FROM NEW-REC
           DISPLAY "write file: " IX-ST
           CLOSE IX-FILE
           OPEN INPUT IX-FILE
           START IX-FILE LAST
           DISPLAY "start last: " IX-ST
           PERFORM 6 TIMES
               READ IX-FILE PREVIOUS
                   AT END DISPLAY "  previous: at end " IX-ST
                   NOT AT END DISPLAY "  previous: " IX-REC
               END-READ
           END-PERFORM
           START IX-FILE FIRST
           READ IX-FILE NEXT
           DISPLAY "first: " IX-REC
           READ IX-FILE NEXT
           READ IX-FILE PREVIOUS
           DISPLAY "next, previous: " IX-REC
           MOVE 35 TO IX-KEY
           START IX-FILE KEY < IX-KEY
           READ IX-FILE PREVIOUS
           DISPLAY "start < 35, previous: " IX-REC
           READ IX-FILE PREVIOUS
           DISPLAY "previous: " IX-REC
           MOVE "B" TO IX-ALT
           START IX-FILE KEY = IX-ALT
           READ IX-FILE NEXT
           DISPLAY "alternate B: " IX-REC
           READ IX-FILE PREVIOUS
           DISPLAY "alternate previous: " IX-REC
           CLOSE IX-FILE
           DELETE FILE IX-FILE
           DISPLAY "delete: " IX-ST
           OPEN OUTPUT REL-FILE
           PERFORM VARYING K FROM 2 BY 3 UNTIL K > 11
               MOVE K TO REL-KEY
               MOVE K TO REL-REC
               WRITE REL-REC
           END-PERFORM
           CLOSE REL-FILE
           OPEN I-O REL-FILE
           START REL-FILE LAST
           DISPLAY "rel last: " REL-ST " key " REL-KEY
           READ REL-FILE PREVIOUS
           DISPLAY "  " REL-REC " key " REL-KEY
           READ REL-FILE PREVIOUS
           DISPLAY "  " REL-REC " key " REL-KEY
           START REL-FILE FIRST
           READ REL-FILE NEXT
           DISPLAY "rel first: " REL-REC " key " REL-KEY
           READ REL-FILE PREVIOUS
               AT END DISPLAY "  before first: " REL-ST
           END-READ
           CLOSE REL-FILE
           DELETE FILE REL-FILE
           DISPLAY "delete: " REL-ST
           STOP RUN.
