      * -std=ibm: ASSIGN names a DD name, the label parts of an IBM
      * assignment-name dropped (UT-S-PAYOUT is PAYOUT), even when a
      * data item has the name; DD_name in the environment maps it.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASSIGNIBM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F-UT ASSIGN TO UT-S-PAYOUT
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-DA ASSIGN TO DA-S-MASTER
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-AS ASSIGN TO AS-VSOUT
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-ITEM ASSIGN TO REPORTDD
               ORGANIZATION LINE SEQUENTIAL.
           SELECT F-MAP ASSIGN TO UT-S-SYSOUT1
               ORGANIZATION LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F-UT.
       01 R-UT PIC X(10).
       FD F-DA.
       01 R-DA PIC X(10).
       FD F-AS.
       01 R-AS PIC X(10).
       FD F-ITEM.
       01 R-ITEM PIC X(10).
       FD F-MAP.
       01 R-MAP PIC X(10).
       WORKING-STORAGE SECTION.
       01 REPORTDD PIC X(12) VALUE "not-used".
       PROCEDURE DIVISION.
           OPEN OUTPUT F-UT
           WRITE R-UT FROM "payout"
           CLOSE F-UT
           OPEN OUTPUT F-DA
           WRITE R-DA FROM "master"
           CLOSE F-DA
           OPEN OUTPUT F-AS
           WRITE R-AS FROM "vsout"
           CLOSE F-AS
           OPEN OUTPUT F-ITEM
           WRITE R-ITEM FROM "report"
           CLOSE F-ITEM
           OPEN OUTPUT F-MAP
           WRITE R-MAP FROM "mapped"
           CLOSE F-MAP
           DISPLAY "DONE"
           STOP RUN.
