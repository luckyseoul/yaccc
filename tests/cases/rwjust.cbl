      * Report Writer: COLUMN LEFT / RIGHT / CENTER, COLUMN PLUS, LINE
      * LIMIT, report groups described by entries under an 01 entry.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RWJUST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO "rwjust.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE REPORT IS STUDENT-REPORT.
       WORKING-STORAGE SECTION.
       01  STUDENT-DATA.
           05  FILLER PIC X(34) VALUE
               "00099Dorken, Keith       CS 000008".
           05  FILLER PIC X(34) VALUE
               "00007Allinson, Sandy     MA 000118".
           05  FILLER PIC X(34) VALUE
               "00125Allinson, Nina      MA 012308".
           05  FILLER PIC X(34) VALUE
               "00127Allinson, Kristina  MBA000008".
           05  FILLER PIC X(34) VALUE
               "12345Norman, Ron         CS 112306".
       01  FILLER REDEFINES STUDENT-DATA.
           05  STUDENT OCCURS 5.
               10  STUDENT-ID       PIC 9(5).
               10  STUDENT-NAME     PIC X(20).
               10  MAJOR            PIC XXX.
               10  NUM-COURSES      PIC 9(6).
       01  S                        PIC 9.
       01  FOOT-TEXT                PIC X(10) VALUE "  page".
       REPORT SECTION.
       RD  STUDENT-REPORT
           PAGE LIMIT 20
           HEADING 1
           FIRST DETAIL 5
           LAST DETAIL 15
           FOOTING 18
           LINE LIMIT 72.
       01  HEADING-LINE.
           02  TYPE PAGE HEADING LINE PLUS 1.
               05  COLUMN 1   PIC X(50) VALUE
                   "         1         2         3         4         5".
               05  COLUMN 51  PIC X(20) VALUE "         6         7".
           02  TYPE PAGE HEADING LINE PLUS 1.
               05  COLUMN 1   PIC X(50) VALUE
                   "12345678901234567890123456789012345678901234567890".
               05  COLUMN 51  PIC X(20) VALUE "12345678901234567890".
           02  TYPE PAGE HEADING LINE PLUS 1.
               05  COLUMN 1   PIC X(2)  VALUE "Ln".
               05  COLUMN 5   PIC X(6)  VALUE "--ID--".
               05  COLUMN 16  PIC X(20) VALUE "--------Name--------".
               05  COLUMN 39  PIC X(5)  VALUE "Major".
               05  COLUMN 45  PIC XXX   VALUE "*-*".
               05  COLUMN 54  PIC X(5)  VALUE "+Odd+".
               05  COLUMN 61  PIC X(6)  VALUE "+Even+".
       01  REPORT-LINE TYPE DETAIL LINE PLUS 1.
           05  COLUMN 1             PIC Z9
                   SOURCE LINE-COUNTER OF STUDENT-REPORT.
           05  COLUMN LEFT 5        PIC Z(5)9 SOURCE STUDENT-ID(S).
           05  COLUMN CENTER 25     PIC X(20) SOURCE STUDENT-NAME(S).
           05  COLUMN RIGHT 43      PIC X(5)  SOURCE MAJOR(S).
           05  COLUMN 45            PIC XXX   VALUE ":-:".
           05  COLUMN CENTER 56     PIC Z(4)9 SOURCE NUM-COURSES(S).
           05  COLUMN CENTER 63     PIC Z(5)9 SOURCE NUM-COURSES(S).
           05  COLUMN 68            PIC X     VALUE ":".
       01  END-LINE TYPE DETAIL LINE PLUS 2.
           05  COLUMN RIGHT 30      PIC X(10) SOURCE FOOT-TEXT.
           05  COLUMN PLUS 2        PIC X(4)  VALUE "<--".
           05  COLUMN RIGHT 72      PIC X(10) VALUE "end".
       PROCEDURE DIVISION.
           OPEN OUTPUT PRINT-FILE
           INITIATE STUDENT-REPORT
           PERFORM VARYING S FROM 1 BY 1 UNTIL S > 5
               GENERATE REPORT-LINE
           END-PERFORM
           GENERATE END-LINE
           TERMINATE STUDENT-REPORT
           CLOSE PRINT-FILE
           DISPLAY "done"
           STOP RUN.
