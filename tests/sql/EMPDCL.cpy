      *> a host structure as DB2's DCLGEN writes one: a VARCHAR is a
      *> group of a length and its text, both level 49
       01 DCL-EMP.
          10 EMP-ID     PIC S9(9) COMP.
          10 EMP-NAME.
             49 EMP-NAME-LEN  PIC S9(4) COMP.
             49 EMP-NAME-TEXT PIC X(20).
          10 SALARY     PIC S9(7)V99 COMP-3.
