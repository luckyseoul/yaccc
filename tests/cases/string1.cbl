       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRING1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FIRST-NAME  PIC X(10) VALUE "JOHN".
       01 LAST-NAME   PIC X(10) VALUE "DOE".
       01 FULL-NAME   PIC X(25).
       01 SHORT-OUT   PIC X(8).
       01 PTR         PIC 99.
       01 CSV-LINE    PIC X(40) VALUE "APPLE,BANANA,,CHERRY  DATE".
       01 F1          PIC X(8).
       01 F2          PIC X(8).
       01 F3          PIC X(8).
       01 F4          PIC X(8).
       01 F5          PIC X(8).
       01 D1          PIC X.
       01 D2          PIC X.
       01 C1          PIC 99.
       01 C2          PIC 99.
       01 C3          PIC 99.
       01 TALLY-CT    PIC 99.
       01 NUM-OUT     PIC 9(4).
       01 TXT         PIC X(30) VALUE "THE QUICK BROWN FOX JUMPS".
       01 CNT         PIC 999.
       01 CNT2        PIC 999.
       01 CNT3        PIC 999.
       01 ZEROS-TXT   PIC X(10) VALUE "0001230045".
       01 DATE-IN     PIC X(10) VALUE "2024-03-15".
       01 YYYY        PIC 9(4).
       01 MM          PIC 99.
       01 DD          PIC 99.
       01 WRDS       PIC X(30) VALUE "  ONE  TWO   THREE ".
       01 W1          PIC X(10).
       01 W2          PIC X(10).
       01 W3          PIC X(10).
       01 AMT         PIC 9(5)V99 VALUE 1234.5.
       01 RM          PIC X(20) VALUE "ABCDEFGHIJKLMNOPQRST".
       01 START-POS   PIC 99 VALUE 3.
       01 LEN         PIC 99 VALUE 4.
       01 NUMED       PIC 9(6) VALUE 123456.
       PROCEDURE DIVISION.
           STRING FIRST-NAME DELIMITED BY SPACE
                  " " DELIMITED BY SIZE
                  LAST-NAME DELIMITED BY SPACE
                  INTO FULL-NAME.
           DISPLAY "[" FULL-NAME "]".
           MOVE 1 TO PTR.
           STRING "ABC" "DEFGHIJ" DELIMITED BY SIZE INTO SHORT-OUT
               WITH POINTER PTR
               ON OVERFLOW DISPLAY "OVERFLOW PTR=" PTR
               NOT ON OVERFLOW DISPLAY "NO OVERFLOW"
           END-STRING.
           DISPLAY "[" SHORT-OUT "]".
           MOVE SPACES TO SHORT-OUT.
           MOVE 3 TO PTR.
           STRING "XY" DELIMITED BY SIZE INTO SHORT-OUT
               WITH POINTER PTR.
           DISPLAY "[" SHORT-OUT "] PTR=" PTR.
           UNSTRING CSV-LINE DELIMITED BY "," OR ALL SPACE
               INTO F1 DELIMITER IN D1 COUNT IN C1
                    F2 DELIMITER IN D2 COUNT IN C2
                    F3 COUNT IN C3
                    F4 F5
               TALLYING IN TALLY-CT
           END-UNSTRING.
           DISPLAY "F1=[" F1 "] D1=[" D1 "] C1=" C1.
           DISPLAY "F2=[" F2 "] D2=[" D2 "] C2=" C2.
           DISPLAY "F3=[" F3 "] C3=" C3.
           DISPLAY "F4=[" F4 "] F5=[" F5 "] TALLY=" TALLY-CT.
           UNSTRING DATE-IN DELIMITED BY "-" INTO YYYY MM DD.
           DISPLAY "Y=" YYYY " M=" MM " D=" DD.
           MOVE 1 TO PTR.
           UNSTRING WRDS DELIMITED BY ALL SPACES
               INTO W1 W2 W3 WITH POINTER PTR.
           DISPLAY "W1=[" W1 "] W2=[" W2 "] W3=[" W3 "] PTR=" PTR.
           MOVE 0 TO CNT CNT2 CNT3.
           INSPECT TXT TALLYING CNT FOR ALL "O".
           DISPLAY "O COUNT: " CNT.
           INSPECT TXT TALLYING CNT2 FOR CHARACTERS BEFORE INITIAL "Q".
           DISPLAY "CHARS BEFORE Q: " CNT2.
           INSPECT TXT TALLYING CNT3 FOR ALL "U" AFTER INITIAL "QUICK".
           DISPLAY "U AFTER QUICK: " CNT3.
           MOVE 0 TO CNT.
           INSPECT ZEROS-TXT TALLYING CNT FOR LEADING "0".
           DISPLAY "LEADING ZEROS: " CNT.
           INSPECT ZEROS-TXT REPLACING LEADING "0" BY " ".
           DISPLAY "[" ZEROS-TXT "]".
           INSPECT TXT REPLACING ALL "O" BY "0".
           DISPLAY "[" TXT "]".
           INSPECT TXT REPLACING FIRST "THE" BY "A  ".
           DISPLAY "[" TXT "]".
           INSPECT TXT CONVERTING "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                               TO "abcdefghijklmnopqrstuvwxyz".
           DISPLAY "[" TXT "]".
           INSPECT TXT REPLACING CHARACTERS BY "*" AFTER INITIAL "fox".
           DISPLAY "[" TXT "]".
           MOVE 0 TO CNT CNT2.
           INSPECT TXT TALLYING CNT FOR ALL "*" CNT2 FOR ALL " ".
           DISPLAY "STARS=" CNT " SPACES=" CNT2.
           MOVE "AABBAABB" TO F1.
           MOVE 0 TO CNT.
           INSPECT F1 TALLYING CNT FOR ALL "AB"
               REPLACING ALL "A" BY "X".
           DISPLAY "AB=" CNT " [" F1 "]".
           DISPLAY "REFMOD: [" RM(3:4) "] [" RM(START-POS:LEN) "]".
           DISPLAY "REFMOD TO END: [" RM(15:) "]".
           MOVE "**" TO RM(5:2).
           DISPLAY "[" RM "]".
           MOVE NUMED(2:3) TO F1.
           DISPLAY "NUMERIC REFMOD: [" F1 "]".
           MOVE SPACES TO FULL-NAME.
           STRING "TOTAL: " AMT DELIMITED BY SIZE INTO FULL-NAME.
           DISPLAY "[" FULL-NAME "]".
           MOVE ALL "-" TO FULL-NAME.
           DISPLAY "[" FULL-NAME "]".
           STOP RUN.
