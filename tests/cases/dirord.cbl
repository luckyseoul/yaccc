      *> COPY is textual inclusion: a >>IF in a copybook sees the compilation
      *> variables as they stand at the COPY line, and a >>DEFINE in a copybook
      *> is visible to the lines that follow it.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIRORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY DIRORD.
      >>DEFINE SET-LATE AS 1
       PROCEDURE DIVISION.
      >>IF FROM-COPY-DEF = 1
           DISPLAY "COPYBOOK-DEFINE: SEEN".
      >>ELSE
           DISPLAY "COPYBOOK-DEFINE: LOST".
      >>END-IF
           DISPLAY "INCLUDER-DEFINE: " FROM-COPY.
           STOP RUN.
