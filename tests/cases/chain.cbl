      *> PROCEDURE DIVISION CHAINING: the items are WORKING-STORAGE items
      *> that receive the command-line arguments, keeping their VALUE when
      *> there are fewer arguments than items. Behaviour per GnuCOBOL
      *> (testsuite run_extensions.at:2242).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X            PIC X.
       01  ABCD         PIC X(4).
       01  NUM          PIC 9 VALUE 7.
       PROCEDURE DIVISION CHAINING X ABCD NUM.
           DISPLAY "X=[" X "] ABCD=[" ABCD "] NUM=" NUM.
           STOP RUN.
