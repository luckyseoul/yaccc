       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATEINFO.
      * Weekday name and day of the year for a YYYYMMDD date.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DAY-NAME-VALUES.
           05  FILLER        PIC X(9) VALUE "Sunday".
           05  FILLER        PIC X(9) VALUE "Monday".
           05  FILLER        PIC X(9) VALUE "Tuesday".
           05  FILLER        PIC X(9) VALUE "Wednesday".
           05  FILLER        PIC X(9) VALUE "Thursday".
           05  FILLER        PIC X(9) VALUE "Friday".
           05  FILLER        PIC X(9) VALUE "Saturday".
       01  DAY-NAMES REDEFINES DAY-NAME-VALUES.
           05  DAY-NAME      PIC X(9) OCCURS 7 TIMES.
       01  DAYS              PIC 9(7).
       01  WEEKDAY           PIC 9.
       01  JAN-1             PIC 9(8).
       LINKAGE SECTION.
       01  L-DATE            PIC 9(8).
       01  L-RESULT.
           05  L-WEEKDAY     PIC X(9).
           05  L-DAY-OF-YEAR PIC 999.
       PROCEDURE DIVISION USING L-DATE L-RESULT.
      * day 1 of the COBOL calendar (1601-01-01) was a Monday
           COMPUTE DAYS = FUNCTION INTEGER-OF-DATE (L-DATE)
           COMPUTE WEEKDAY = FUNCTION MOD (DAYS, 7) + 1
           MOVE DAY-NAME (WEEKDAY) TO L-WEEKDAY
           COMPUTE JAN-1 = FUNCTION INTEGER (L-DATE / 10000) * 10000
                           + 101
           COMPUTE L-DAY-OF-YEAR = DAYS
                   - FUNCTION INTEGER-OF-DATE (JAN-1) + 1
           GOBACK.
