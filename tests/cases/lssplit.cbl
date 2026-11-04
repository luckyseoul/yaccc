      *> LINE SEQUENTIAL READ of a line longer than the record: the
      *> record gets what fits and status 04 says the rest was dropped
      *> (spaces at the end don't count); CR LF ends a line as LF does.
      *> GnuCOBOL 3.1.2 drops the rest with status 00: compared only
      *> against the recorded baseline. lssplit runs it with
      *> COB_LS_SPLIT=Y, where the rest is read as the next records.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LSSPLIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN "in.txt" ORGANIZATION LINE SEQUENTIAL
               FILE STATUS FS.
           SELECT G ASSIGN "out.txt" ORGANIZATION LINE SEQUENTIAL
               FILE STATUS GS.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 R PIC X(10).
       FD G.
       01 W PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 GS PIC XX.
       PROCEDURE DIVISION.
           OPEN INPUT F OUTPUT G
           PERFORM UNTIL FS(1:1) NOT = '0'
               READ F
                   AT END DISPLAY 'at end ' FS
                   NOT AT END
                       DISPLAY FS ' [' R ']'
                       WRITE W FROM R
               END-READ
           END-PERFORM
           CLOSE F G
           STOP RUN.
