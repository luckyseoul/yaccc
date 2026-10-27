       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDIT1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 V          PIC S9(7)V99.
       01 E01        PIC ZZZ9.
       01 E02        PIC ZZZZ.
       01 E03        PIC ZZ,ZZ9.99.
       01 E04        PIC $$,$$9.99.
       01 E05        PIC ***,**9.99.
       01 E06        PIC -ZZ9.
       01 E07        PIC ZZ9-.
       01 E08        PIC +ZZ9.
       01 E09        PIC ---9.
       01 E10        PIC +++9.
       01 E11        PIC 9(3)CR.
       01 E12        PIC 9(3)DB.
       01 E13        PIC 99/99/99.
       01 E14        PIC 9B9B9.
       01 E15        PIC $ZZ9.99.
       01 E16        PIC ZZZ.ZZ.
       01 E17        PIC $$$.99.
       01 E18        PIC $$$.$$.
       01 E19        PIC ***.**.
       01 E20        PIC Z,ZZZ,ZZ9.99-.
       01 E21        PIC $$,$$$,$$9.99CR.
       01 E22        PIC 9(5).
       01 E23        PIC 999000.
       01 E24        PIC ZZ9.99 BLANK WHEN ZERO.
       01 E25        PIC -(5)9.99.
       01 E26        PIC +(5)9.99.
       01 E27        PIC $(6)9.99.
       01 E28        PIC Z(6)9.99.
       01 E29        PIC *(6)9.99.
       01 E30        PIC $***,**9.99.
       01 E31        PIC 9.99.
       01 E32        PIC ZZZZ9.
       01 E33        PIC XXBXX.
       01 E34        PIC X(3)/X(3).
       01 E35        PIC 0XX0.
       01 VALS.
          05 VAL     PIC S9(7)V99 OCCURS 9 TIMES.
       01 I          PIC 99.
       PROCEDURE DIVISION.
           MOVE 0         TO VAL(1).
           MOVE 5         TO VAL(2).
           MOVE -5        TO VAL(3).
           MOVE 12.34     TO VAL(4).
           MOVE -12.34    TO VAL(5).
           MOVE 1234.5    TO VAL(6).
           MOVE -1234567.89 TO VAL(7).
           MOVE 0.05      TO VAL(8).
           MOVE 999999.99 TO VAL(9).
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 9
               MOVE VAL(I) TO V
               DISPLAY "VALUE " V
               MOVE V TO E01 MOVE V TO E02 MOVE V TO E03 MOVE V TO E04
               MOVE V TO E05 MOVE V TO E06 MOVE V TO E07 MOVE V TO E08
               MOVE V TO E09 MOVE V TO E10 MOVE V TO E11 MOVE V TO E12
               MOVE V TO E13 MOVE V TO E14 MOVE V TO E15 MOVE V TO E16
               MOVE V TO E17 MOVE V TO E18 MOVE V TO E19 MOVE V TO E20
               MOVE V TO E21 MOVE V TO E22 MOVE V TO E23 MOVE V TO E24
               MOVE V TO E25 MOVE V TO E26 MOVE V TO E27 MOVE V TO E28
               MOVE V TO E29 MOVE V TO E30 MOVE V TO E31 MOVE V TO E32
               DISPLAY " [" E01 "][" E02 "][" E03 "][" E04 "][" E05 "]"
               DISPLAY " [" E06 "][" E07 "][" E08 "][" E09 "][" E10 "]"
               DISPLAY " [" E11 "][" E12 "][" E13 "][" E14 "][" E15 "]"
               DISPLAY " [" E16 "][" E17 "][" E18 "][" E19 "][" E20 "]"
               DISPLAY " [" E21 "][" E22 "][" E23 "][" E24 "][" E25 "]"
               DISPLAY " [" E26 "][" E27 "][" E28 "][" E29 "][" E30 "]"
               DISPLAY " [" E31 "][" E32 "]"
           END-PERFORM.
           MOVE "ABCD" TO E33. DISPLAY "[" E33 "]".
           MOVE "ABCDEF" TO E34. DISPLAY "[" E34 "]".
           MOVE "AB" TO E35. DISPLAY "[" E35 "]".
           MOVE E03 TO V. DISPLAY "DE-EDIT " V.
           MOVE -42.5 TO E20. MOVE E20 TO V. DISPLAY "DE-EDIT NEG " V.
           STOP RUN.
