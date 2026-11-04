      *> JSON PARSE (IBM Enterprise COBOL 6.2): names matched to data
      *> names in any case and to NAME literals exactly, objects to
      *> groups, arrays to tables (DEPENDING ON counts), strings and
      *> numbers by MOVE, true/false through CONVERTING, null, SUPPRESS,
      *> NAME OF receiver IS OMITTED, JSON-STATUS and JSON-CODE.
      *> GnuCOBOL 3.1 has no JSON PARSE: the expected output is checked
      *> by hand against IBM's documented codes.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSONPARSE1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 T1 PIC X(300) VALUE
           '{"customer": {"cust-id": 42, "Cust-Name": "Ada Lovelace", '
         & '"balance": -123.45, "active": true, "addr": {"city": "Lon'
         & 'don", "zip": "NW1"}, "phones": [{"kind": "home", "num": "'
         & '5551234"}, {"kind": "work", "num": "5559876"}], "tags": ["'
         & 'a", "bb", "ccc", "dddd"], "extra": [1, {"x": null}]}}'.
       01 T2 PIC X(60) VALUE
           '{"customer": {"active": false, "cust-id": null}}'.
       01 T3 PIC X(300) VALUE
           '{"order-rec": {"OrderNumber": 7, "qty": "15", "price": 1.25'
         & '5e2, "rate": 2.5E-3, "edited": 1234.5, "flag": false, "yesn'
         & 'o": true, "note-txt": "abcdefgh", "secret": "zzzz", "old-no'
         & '": 5, "n": 3, "items": [{"sku": "Aé", "lines-q": [1, 2'
         & ']}, null, {"sku": "C", "lines-q": [5, 6, 7]}, {"sku": "D"}]'
         & '}}'.
       01 T4 PIC X(60) VALUE
           '{"orderNumber": 99999, "qty": 1e3, "price": -1.5}'.
       01 T5 PIC X(60) VALUE
           '{"OrderNumber": 5, "qty": 1e999999999999}'.
       01 TXT PIC X(80).
       01 CUSTOMER.
          05 CUST-ID     PIC 9(5).
          05 CUST-NAME   PIC X(12).
          05 BALANCE     PIC S9(5)V99 COMP-3.
          05 ACTIVE      PIC X.
             88 IS-ACTIVE   VALUE 'Y' WHEN SET TO FALSE 'N'.
          05 ADDR.
             10 CITY     PIC X(10).
             10 ZIP      PIC X(5).
          05 PHONES OCCURS 3 TIMES.
             10 KIND     PIC X(4).
             10 NUM      PIC X(8).
          05 TAGS        PIC X(3) OCCURS 4 TIMES.
       01 SHOW-BAL PIC -(5)9.99.
       01 ORDER-REC.
          05 ORDER-NO   PIC 9(4).
          05 FILLER     PIC X(2).
          05 QTY        PIC 9(3).
          05 PRICE      PIC 9(3)V99.
          05 RATE       COMP-2.
          05 EDITED     PIC Z,ZZ9.99.
          05 FLAG       PIC X.
          05 YESNO      PIC X(3).
             88 YES-V   VALUE 'YES'.
             88 NO-V    VALUE 'NO '.
          05 NOTE-TXT   PIC X(6) JUSTIFIED RIGHT.
          05 SECRET     PIC X(4).
          05 OLD-NO     REDEFINES SECRET PIC 9(4).
          05 N          PIC 9.
          05 ITEMS OCCURS 0 TO 5 DEPENDING ON N.
             10 SKU     PIC X(3).
             10 LINES-Q OCCURS 2 TIMES PIC 99.
       PROCEDURE DIVISION.
           MOVE ALL '*' TO CUSTOMER
           JSON PARSE T1 INTO CUSTOMER
               CONVERTING ACTIVE FROM JSON BOOLEAN USING IS-ACTIVE
               ON EXCEPTION
                   DISPLAY '1 exception ' JSON-CODE END-DISPLAY
               NOT ON EXCEPTION
                   DISPLAY '1 ok ' JSON-CODE END-DISPLAY
           END-JSON
      *>   256 truncated + 8 fewer elements + 2 a name with no item
           DISPLAY '1 status ' JSON-STATUS
           DISPLAY '  id [' CUST-ID '] name [' CUST-NAME ']'
           MOVE BALANCE TO SHOW-BAL
           DISPLAY '  balance [' SHOW-BAL '] active [' ACTIVE ']'
           DISPLAY '  city [' CITY '] zip [' ZIP ']'
           DISPLAY '  phone 1 [' KIND(1) '][' NUM(1) ']'
           DISPLAY '  phone 2 [' KIND(2) '][' NUM(2) ']'
           DISPLAY '  phone 3 [' KIND(3) '][' NUM(3) ']'
           DISPLAY '  tags [' TAGS(1) '][' TAGS(2) '][' TAGS(3) ']['
               TAGS(4) ']'
      *>   null leaves cust-id; 32 null + 1 items with no name
           JSON PARSE T2 INTO CUSTOMER
               CONVERTING ACTIVE FROM JSON BOOLEAN USING IS-ACTIVE
           END-JSON
           DISPLAY '2 code ' JSON-CODE ' status ' JSON-STATUS
           DISPLAY '  active [' ACTIVE '] id [' CUST-ID ']'
      *>   true with no CONVERTING: 105
           MOVE '{"customer": {"active": true}}' TO TXT
           JSON PARSE TXT INTO CUSTOMER
               ON EXCEPTION DISPLAY '3 exception ' JSON-CODE
           END-JSON
      *>   only white space: 101
           MOVE SPACES TO TXT
           JSON PARSE TXT INTO CUSTOMER
               ON EXCEPTION DISPLAY '4 exception ' JSON-CODE
           END-JSON
      *>   not JSON: 100
           MOVE '{"customer": {"cust-id": 1,}}' TO TXT
           JSON PARSE TXT INTO CUSTOMER
               ON EXCEPTION DISPLAY '5 exception ' JSON-CODE
           END-JSON
      *>   nothing matched: 106
           MOVE '{"client": {"cust-id": 1}}' TO TXT
           JSON PARSE TXT INTO CUSTOMER
               ON EXCEPTION
                   DISPLAY '6 exception ' JSON-CODE ' status '
                       JSON-STATUS
                   END-DISPLAY
           END-JSON
      *>   a string for a group: 104
           MOVE '{"customer": {"addr": "x"}}' TO TXT
           JSON PARSE TXT INTO CUSTOMER
               ON EXCEPTION DISPLAY '7 exception ' JSON-CODE
           END-JSON
           DISPLAY '  id [' CUST-ID ']'
      *>   a JSON text given as a literal
           JSON PARSE '{"customer": {"addr": {"zip": "E1"}}}'
               INTO CUSTOMER
           END-JSON
           DISPLAY '8 code ' JSON-CODE ' zip [' ZIP ']'
           MOVE SPACES TO ORDER-REC
           MOVE ZERO TO ORDER-NO QTY PRICE N
           JSON PARSE T3 INTO ORDER-REC
               NAME OF ORDER-NO IS 'OrderNumber'
               SUPPRESS SECRET
               CONVERTING FLAG FROM JSON BOOLEAN USING 'T' AND 'F'
                   ALSO YESNO FROM JSON BOOLEAN YES-V AND NO-V
               NOT ON EXCEPTION
                   DISPLAY '9 ok' END-DISPLAY
           END-JSON
      *>   256 + 64 null element + 16 more elements + 2 names with no item
           DISPLAY '9 code ' JSON-CODE ' status ' JSON-STATUS
           DISPLAY '  no [' ORDER-NO '] qty [' QTY '] price [' PRICE
               ']'
           DISPLAY '  rate [' RATE '] edited [' EDITED ']'
           DISPLAY '  flag [' FLAG '] yesno [' YESNO '] note ['
               NOTE-TXT ']'
           DISPLAY '  secret [' SECRET '] n [' N ']'
           DISPLAY '  item 1 [' SKU(1) '][' LINES-Q(1, 1) ']['
               LINES-Q(1, 2) ']'
           DISPLAY '  item 2 [' SKU(2) '][' LINES-Q(2, 1) ']['
               LINES-Q(2, 2) ']'
           DISPLAY '  item 3 [' SKU(3) '][' LINES-Q(3, 1) ']['
               LINES-Q(3, 2) ']'
      *>   SIZE ERROR keeps the digits that fit: 128 (+1)
           JSON PARSE T4 INTO ORDER-REC
               NAME OF ORDER-NO IS 'orderNumber' ORDER-REC IS OMITTED
           END-JSON
           DISPLAY '10 code ' JSON-CODE ' status ' JSON-STATUS
           DISPLAY '  no [' ORDER-NO '] qty [' QTY '] price [' PRICE
               ']'
           JSON PARSE T5 INTO ORDER-REC
               NAME OF ORDER-NO IS 'OrderNumber' ORDER-REC IS OMITTED
           END-JSON
           DISPLAY '11 code ' JSON-CODE ' status ' JSON-STATUS
           DISPLAY '  no [' ORDER-NO '] qty [' QTY ']'
           STOP RUN.
