       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATA1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 CUSTOMER.
          05 CUST-ID       PIC 9(5)     VALUE 12345.
          05 CUST-NAME     PIC X(10)    VALUE "ACME CORP".
          05 CUST-BAL      PIC S9(5)V99 VALUE -150.25.
          05 FILLER        PIC X(3)     VALUE "***".
          05 CUST-ADDR.
             10 STREET     PIC X(10)    VALUE "MAIN ST".
             10 ZIP        PIC 9(5)     VALUE 90210.
          05 CUST-TAGS     PIC X(2) OCCURS 3 TIMES VALUE "TG".
       01 CUSTOMER-COPY.
          05 CUST-NAME     PIC X(12).
          05 CUST-ID       PIC 9(7).
          05 CUST-ADDR.
             10 ZIP        PIC X(5).
             10 CITY       PIC X(8) VALUE "NOWHERE".
          05 CUST-BAL      PIC -(6)9.99.
       01 DATE-NUM        PIC 9(8) VALUE 20240315.
       01 DATE-PARTS REDEFINES DATE-NUM.
          05 DP-YEAR      PIC 9(4).
          05 DP-MONTH     PIC 99.
          05 DP-DAY       PIC 99.
       01 PACKED-NUM      PIC S9(7) COMP-3 VALUE -1234567.
       01 PACKED-X REDEFINES PACKED-NUM PIC X(4).
       01 BIN-NUM         PIC S9(4) COMP VALUE -2.
       01 BIN-X REDEFINES BIN-NUM PIC X(2).
       01 SIGNED-DISP     PIC S9(3) VALUE -123.
       01 SIGNED-X REDEFINES SIGNED-DISP PIC X(3).
       01 SEP-LEAD        PIC S9(3) SIGN LEADING SEPARATE VALUE -45.
       01 SEP-TRAIL       PIC S9(3) SIGN TRAILING SEPARATE VALUE 45.
       01 LEAD-EMB        PIC S9(3) SIGN LEADING VALUE -45.
       01 LEAD-EMB-X REDEFINES LEAD-EMB PIC X(3).
       01 GRP-A.
          05 GA-1         PIC X(3) VALUE "ABC".
          05 GA-2         PIC 9(3) VALUE 42.
       01 GRP-B           PIC X(10).
       01 NUM-GROUP.
          05 NG-1         PIC 9(3) VALUE 1.
          05 NG-2         PIC 9(3) VALUE 2.
       01 INIT-REC.
          05 IR-NUM       PIC 9(4) VALUE 1111.
          05 IR-ALPHA     PIC X(4) VALUE "ZZZZ".
          05 IR-EDIT      PIC ZZ9.9 VALUE 9.9.
          05 IR-PACK      PIC S9(3) COMP-3 VALUE 77.
          05 FILLER       PIC X(2) VALUE "FF".
          05 IR-TBL OCCURS 2 TIMES.
             10 IR-T1     PIC 99 VALUE 55.
             10 IR-T2     PIC X  VALUE "Q".
       01 HEXOUT          PIC X(8).
       01 I               PIC 9.
       01 HEXDIGITS       PIC X(16) VALUE "0123456789ABCDEF".
       01 BYTE-VAL        PIC 9(3).
       01 HI              PIC 99.
       01 LO              PIC 99.
       PROCEDURE DIVISION.
           DISPLAY "CUSTOMER: [" CUSTOMER "]".
           MOVE CORRESPONDING CUSTOMER TO CUSTOMER-COPY.
           DISPLAY "COPY: [" CUSTOMER-COPY "]".
           DISPLAY "YEAR=" DP-YEAR " MONTH=" DP-MONTH " DAY=" DP-DAY.
           MOVE 12 TO DP-MONTH.
           DISPLAY "DATE-NUM=" DATE-NUM.
           DISPLAY "PACKED=" PACKED-NUM.
           PERFORM SHOW-PACKED.
           DISPLAY "BIN=" BIN-NUM.
           MOVE BIN-X TO HEXOUT.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 2
               COMPUTE BYTE-VAL = FUNCTION ORD(BIN-X(I:1)) - 1
               DISPLAY "BIN BYTE " I ": " BYTE-VAL
           END-PERFORM.
           DISPLAY "SIGNED-DISP=" SIGNED-DISP " RAW=[" SIGNED-X "]".
           DISPLAY "SEP-LEAD=" SEP-LEAD " RAW=[" SEP-LEAD "]".
           DISPLAY "SEP-TRAIL=" SEP-TRAIL.
           DISPLAY "LEAD-EMB=" LEAD-EMB " RAW=[" LEAD-EMB-X "]".
           MOVE GRP-A TO GRP-B.
           DISPLAY "GROUP MOVE: [" GRP-B "]".
           MOVE "XY" TO GRP-A.
           DISPLAY "SHORT TO GROUP: [" GRP-A "]".
           MOVE NUM-GROUP TO GRP-B.
           DISPLAY "NUM GROUP: [" GRP-B "]".
           INITIALIZE INIT-REC.
           DISPLAY "INITIALIZED: [" IR-NUM "][" IR-ALPHA "][" IR-EDIT
                   "][" IR-PACK "][" IR-T1(1) IR-T2(1) IR-T1(2)
                   IR-T2(2) "]".
           INITIALIZE INIT-REC REPLACING NUMERIC DATA BY 7
                                         ALPHANUMERIC DATA BY "AB".
           DISPLAY "REPLACED: [" IR-NUM "][" IR-ALPHA "][" IR-EDIT
                   "][" IR-PACK "][" IR-T1(1) IR-T2(1) "]".
           MOVE SPACES TO CUSTOMER.
           DISPLAY "SPACES: [" CUSTOMER "]".
           MOVE ZEROS TO NUM-GROUP.
           DISPLAY "ZEROS: [" NUM-GROUP "]".
           MOVE HIGH-VALUES TO GRP-B.
           IF GRP-B = HIGH-VALUES DISPLAY "HIGH-VALUES OK" END-IF.
           MOVE LOW-VALUES TO GRP-B.
           IF GRP-B = LOW-VALUES DISPLAY "LOW-VALUES OK" END-IF.
           MOVE QUOTES TO GRP-B.
           DISPLAY "QUOTES: [" GRP-B "]".
           MOVE ALL "XYZ" TO GRP-B.
           DISPLAY "ALL XYZ: [" GRP-B "]".
           STOP RUN.
       SHOW-PACKED.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 4
               COMPUTE BYTE-VAL = FUNCTION ORD(PACKED-X(I:1)) - 1
               DIVIDE BYTE-VAL BY 16 GIVING HI REMAINDER LO
               DISPLAY "PACKED BYTE " I ": " HEXDIGITS(HI + 1:1)
                       HEXDIGITS(LO + 1:1)
           END-PERFORM.
