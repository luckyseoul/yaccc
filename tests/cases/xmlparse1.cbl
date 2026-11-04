      *> XML PARSE: the events of a document (declaration, comment,
      *> namespaces, attributes, references, CDATA, a processing
      *> instruction, an unresolved reference), XML-CODE for errors,
      *> and XML-CODE -1 set by the processing procedure to stop.
      *> GnuCOBOL 3.1 has no XML PARSE: the expected output is checked
      *> by hand against IBM's documented events and codes.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XMLPARSE1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 DOC PIC X(300) VALUE
           '<?xml version="1.0" encoding="UTF-8"?><!-- order --><p:or'
         & 'der xmlns:p="urn:o" id="7" note="a &amp; b"><item qty="2">'
         & 'bolt &lt;M8&gt;</item><item qty=''1''><![CDATA[<nut>]]></i'
         & 'tem><?app keep?><empty/>&custom;</p:order>'.
       01 DOCS.
          05 D1 PIC X(40) VALUE '<a><b>text</c></a>'.
          05 D2 PIC X(40) VALUE '<a x="1" x="2"/>'.
          05 D3 PIC X(40) VALUE '<a>one</a><b/>'.
          05 D4 PIC X(40) VALUE '<a><b>stop here</b><c/></a>'.
          05 D5 PIC X(40) VALUE '<a>&#x41;&#66;&#xZZ;</a>'.
       01 ONE-DOC PIC X(40).
       01 N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
           XML PARSE FUNCTION TRIM(DOC)
               PROCESSING PROCEDURE SHOW
               ON EXCEPTION DISPLAY "exception " XML-CODE END-DISPLAY
               NOT ON EXCEPTION DISPLAY "done, events " N
           END-XML
           MOVE D1 TO ONE-DOC PERFORM RUN-ONE
           MOVE D2 TO ONE-DOC PERFORM RUN-ONE
           MOVE D3 TO ONE-DOC PERFORM RUN-ONE
           MOVE D4 TO ONE-DOC PERFORM RUN-ONE
           MOVE D5 TO ONE-DOC PERFORM RUN-ONE
           STOP RUN.
       SHOW.
           ADD 1 TO N
           DISPLAY XML-EVENT(1:30) "|" XML-TEXT "|"
               XML-NAMESPACE-PREFIX "|" XML-NAMESPACE "|".
       RUN-ONE.
           MOVE 0 TO N
           XML PARSE FUNCTION TRIM(ONE-DOC)
               PROCESSING PROCEDURE CHECK-ONE
               ON EXCEPTION
                   DISPLAY "  exception " XML-CODE " after " N
                   END-DISPLAY
               NOT ON EXCEPTION
                   DISPLAY "  ok after " N END-DISPLAY
           END-XML.
       CHECK-ONE.
           ADD 1 TO N
           IF XML-EVENT = "EXCEPTION"
               DISPLAY "  EXCEPTION code " XML-CODE " text [" XML-TEXT
                   "]"
           END-IF
           IF XML-EVENT = "START-OF-ELEMENT" AND XML-TEXT = "c"
               MOVE -1 TO XML-CODE
           END-IF
           IF XML-EVENT = "CONTENT-CHARACTERS"
               DISPLAY "  content [" XML-TEXT "] length "
                   FUNCTION LENGTH(XML-TEXT)
           END-IF.
