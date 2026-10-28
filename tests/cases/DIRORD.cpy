      *> a copybook whose conditional depends on a variable the includer
      *> defines *after* the COPY: textual inclusion means it is not yet on
      >>IF SET-LATE = 1
       01  FROM-COPY PIC X(3) VALUE "BAD".
      >>ELSE
       01  FROM-COPY PIC X(3) VALUE "OK".
      >>END-IF
      *> and a define that the includer relies on after the COPY
      >>DEFINE FROM-COPY-DEF AS 1
