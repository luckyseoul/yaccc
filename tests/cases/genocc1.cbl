      *> JSON and XML GENERATE of tables: a group table as an array of
      *> objects (repeated elements in XML), an elementary table, a table
      *> with DEPENDING ON (its current count), a subscripted source,
      *> and WITH ATTRIBUTES: numbers written as values and a group whose
      *> items are all attributes kept as an element. JSON PARSE reads
      *> the generated text back. GnuCOBOL 3.1 does not generate tables
      *> ("OCCURS items in JSON/XML GENERATE is not implemented").
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GENOCC1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 OUT-TXT PIC X(400).
       01 CNT PIC 9(4).
       01 TBL.
          05 ENTRY-X OCCURS 3.
             10 REC.
                15 ID-NO      PIC 9(3).
                15 AMT        PIC S9(3)V99 COMP-3.
                15 PHN OCCURS 2 TIMES.
                   20 KIND    PIC X(4).
                   20 NUM     PIC 9(3).
                15 TAGS       PIC X(2) OCCURS 3.
       01 REC2.
          05 ID-NO      PIC 9(3).
          05 AMT        PIC S9(3)V99.
          05 PHN OCCURS 2 TIMES.
             10 KIND    PIC X(4).
             10 NUM     PIC 9(3).
          05 TAGS       PIC X(2) OCCURS 3.
       01 VREC.
          05 VN PIC 9 VALUE 0.
          05 VTAG PIC X(2) OCCURS 0 TO 3 DEPENDING ON VN.
       PROCEDURE DIVISION.
           INITIALIZE TBL
           MOVE 7 TO ID-NO OF REC(2)
           MOVE -1.5 TO AMT OF REC(2)
           MOVE 'home' TO KIND OF REC(2, 1)
           MOVE 123 TO NUM OF REC(2, 1)
           MOVE 'work' TO KIND OF REC(2, 2)
           MOVE 456 TO NUM OF REC(2, 2)
           MOVE 'ab' TO TAGS OF REC(2, 1)
           MOVE 'cd' TO TAGS OF REC(2, 2)
           MOVE 'ef' TO TAGS OF REC(2, 3)
           JSON GENERATE OUT-TXT FROM REC(2) COUNT IN CNT
           DISPLAY OUT-TXT(1:CNT)
           MOVE ALL '.' TO REC2
           JSON PARSE OUT-TXT(1:CNT) INTO REC2
               NAME OF REC2 IS 'REC'
           END-JSON
           DISPLAY 'code ' JSON-CODE ' status ' JSON-STATUS
           DISPLAY REC2
           XML GENERATE OUT-TXT FROM REC(2) COUNT IN CNT
           DISPLAY OUT-TXT(1:CNT)
           XML GENERATE OUT-TXT FROM REC(2) COUNT IN CNT
               WITH ATTRIBUTES
           DISPLAY OUT-TXT(1:CNT)
           MOVE 3 TO VN
           MOVE 'x1' TO VTAG(1)
           MOVE 'x2' TO VTAG(2)
           MOVE 'x3' TO VTAG(3)
           MOVE 2 TO VN
           JSON GENERATE OUT-TXT FROM VREC COUNT IN CNT
           DISPLAY OUT-TXT(1:CNT)
           XML GENERATE OUT-TXT FROM VREC COUNT IN CNT
           DISPLAY OUT-TXT(1:CNT)
           MOVE 3 TO VN
           MOVE SPACES TO VREC
           MOVE 1 TO VN
           JSON PARSE '{"vrec": {"vn": 3, "vtag": ["p", "q", "r", "s"]}}'
               INTO VREC
           END-JSON
           DISPLAY 'code ' JSON-CODE ' status ' JSON-STATUS ' vn ' VN
           DISPLAY VTAG(1) VTAG(2) VTAG(3)
           STOP RUN.
