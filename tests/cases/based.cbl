      *> BASED items: storage allocated at run time by ALLOCATE, freed by
      *> FREE. Access before ALLOCATE is a clean runtime error, and VALUE
      *> clauses apply when the item is allocated INITIALIZED.
      *> Behaviour per GnuCOBOL (testsuite run_misc.at:3348-4200).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BASED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FLD          BASED.
           05  F-X      PIC X.
           05  F-9      PIC 9.
       01  PT           BASED VALUE ".".
       PROCEDURE DIVISION.
           IF ADDRESS OF FLD NOT = NULL
               DISPLAY "ADDRESS BEFORE ALLOCATE"
           END-IF.
           ALLOCATE FLD.
           IF ADDRESS OF FLD = NULL
               DISPLAY "NO ADDRESS AFTER ALLOCATE"
           END-IF.
           MOVE "A5" TO FLD.
           DISPLAY "VALUE: [" FLD "]".
           FREE FLD.
           IF ADDRESS OF FLD = NULL
               DISPLAY "FREED"
           END-IF.
      *> ALLOCATE ... INITIALIZED applies the VALUE clause
           ALLOCATE PT INITIALIZED.
           DISPLAY "INITIALIZED: [" PT "]".
           FREE PT.
           STOP RUN.
