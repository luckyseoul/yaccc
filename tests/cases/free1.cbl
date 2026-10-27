*> Free-format source
IDENTIFICATION DIVISION.
PROGRAM-ID. FREE1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 counter      PIC 9(3) VALUE 0.
01 total        PIC 9(6) VALUE 0.
01 line-text    PIC X(100) VALUE "Free format allows long lines that go well past column seventy-two easily".
PROCEDURE DIVISION.
    PERFORM VARYING counter FROM 1 BY 1 UNTIL counter > 100
        ADD counter TO total   *> accumulate
    END-PERFORM
    DISPLAY "Sum of 1..100 = " total
    DISPLAY function trim(line-text)
    display "lower-case keywords work too"
    STOP RUN.
