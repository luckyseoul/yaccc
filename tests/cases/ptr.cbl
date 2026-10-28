      *> POINTER items and SET ADDRESS OF: rebinding a LINKAGE item's storage,
      *> passing pointers through other pointers, and NULL. Behaviour per
      *> GnuCOBOL (testsuite run_extensions.at:237).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PTR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X-1 PIC X(3) VALUE "X-1".
       01  X-2 PIC X(3) VALUE "X-2".
       01  G.
           02  PTR-1 USAGE POINTER VALUE NULL.
           02  PTR-2 USAGE POINTER VALUE NULL.
       LINKAGE SECTION.
       01  Y PIC X(3).
       PROCEDURE DIVISION.
           SET ADDRESS OF Y TO ADDRESS OF X-1.
           DISPLAY "1:[" Y "]".
           SET PTR-1 TO ADDRESS OF X-2.
           SET PTR-2 TO PTR-1.
           SET ADDRESS OF Y TO PTR-2.
           DISPLAY "2:[" Y "]".
           INITIALIZE PTR-1.
           IF PTR-1 = NULL
               DISPLAY "3: PTR-1 IS NULL"
           END-IF.
           SET ADDRESS OF Y TO NULL.
           IF PTR-1 = ADDRESS OF Y
               DISPLAY "4: BOTH NULL"
           END-IF.
           STOP RUN.
