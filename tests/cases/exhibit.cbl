      *> Statements that had no implementation: EXHIBIT, ACCEPT OMITTED,
      *> SET ... TO SIZE OF, and the H"..." hexadecimal numeric literal.
      *> Expected text is GnuCOBOL's (testsuite run_extensions.at:188, :451,
      *> :4899, run_accept.at:28).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXHIBIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77  VAR-1         PIC X(8).
       77  VAR-2         PIC 999.
       01  HEX-1         PIC 9(8) VALUE H"012345".
       01  HEX-2         PIC 9(8) VALUE H"FFFFFF".
       01  SZ            PIC 99.
       PROCEDURE DIVISION.
           DISPLAY "HEX: " HEX-1 " " HEX-2.
           SET SZ TO SIZE OF VAR-1.
           DISPLAY "SIZE: " SZ.
      *> CHANGED prints bare values, NAMED (the default) prints names
           EXHIBIT CHANGED VAR-1 "X"
           MOVE 123 TO VAR-1
           EXHIBIT VAR-1 VAR-2 "Y"
           EXHIBIT CHANGED VAR-1
           STOP RUN.
