       IDENTIFICATION DIVISION.
       PROGRAM-ID. B6GFX.
      *> Software rasteriser, pure integer arithmetic: 24 triangles are
      *> rotated in 3D, projected, and flat-filled into a 320x224 frame
      *> buffer a scanline at a time, 200 frames. Everything is scaled
      *> integers so the result is identical on every conforming compiler --
      *> a float boundary would make the checksum depend on the compiler's
      *> last-bit behaviour and the timings would not be comparable.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FB.
          05 FB-ROW PIC X(320) OCCURS 224 TIMES.
       01 NPOLY PIC 9(4) COMP VALUE 24.
       01 NV PIC 9(4) COMP VALUE 3.
       01 SCALE-V PIC 9(9) COMP VALUE 1024.
       01 NFRAMES PIC 9(4) COMP VALUE 200.
      *> one frame's rotation, chosen as integers: cos ~ 1023/1024,
      *> sin ~ 32/1024. Rotating by the same amount each frame sweeps the
      *> full circle in 200 frames.
       01 CA PIC S9(9) COMP VALUE 1023.
       01 SA PIC S9(9) COMP VALUE 32.
       01 POLY.
          05 P OCCURS 24 TIMES.
             10 VX PIC S9(9) COMP OCCURS 3 TIMES.
             10 VY PIC S9(9) COMP OCCURS 3 TIMES.
             10 VZ PIC S9(9) COMP OCCURS 3 TIMES.
             10 WX PIC S9(9) COMP OCCURS 3 TIMES.
             10 WY PIC S9(9) COMP OCCURS 3 TIMES.
             10 WZ PIC S9(9) COMP OCCURS 3 TIMES.
       01 IX-TAB.
          05 IX PIC S9(9) COMP OCCURS 3 TIMES.
       01 IY-TAB.
          05 IY PIC S9(9) COMP OCCURS 3 TIMES.
       01 I PIC 99 COMP.
       01 J PIC 99 COMP.
       01 K PIC 99 COMP.
       01 F PIC 9(4) COMP.
       01 T PIC S9(18) COMP.
       01 YMIN PIC S9(6) COMP.
       01 YMAX PIC S9(6) COMP.
       01 YY PIC S9(6) COMP.
       01 XLEFT PIC S9(6) COMP.
       01 XRIGHT PIC S9(6) COMP.
       01 XT PIC S9(6) COMP.
       01 ROW-IDX PIC 9(4) COMP.
       01 LEN PIC 9(4) COMP.
       01 ACC PIC 9(12) COMP VALUE 0.
       01 COUNTED PIC 9(4) COMP.
       01 CROSSED PIC 9 COMP.
       01 ANGLE PIC S9(9) COMP.

       PROCEDURE DIVISION.
           PERFORM INIT-POLYS
           PERFORM VARYING F FROM 1 BY 1 UNTIL F > NFRAMES
               PERFORM ROTATE
               PERFORM CLEAR-FB
               PERFORM VARYING I FROM 1 BY 1 UNTIL I > NPOLY
                   PERFORM PROJECT-POLY
                   PERFORM FILL-TRI
               END-PERFORM
               PERFORM CHECKSUM
           END-PERFORM
           DISPLAY ACC
           STOP RUN.

       INIT-POLYS.
      *> a ring of triangles, coordinates in SCALE-V units
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > NPOLY
               PERFORM VARYING K FROM 1 BY 1 UNTIL K > NV
                   COMPUTE ANGLE = (I - 1) * 683 + (K - 1) * 2184
                   COMPUTE VX(I, K) = 600
                   COMPUTE VY(I, K) = (K - 2) * 500
                   COMPUTE VZ(I, K) = (I - 12) * 120
               END-PERFORM
           END-PERFORM
           MOVE 0 TO F.

       ROTATE.
      *> rotate every vertex one step: x' = (x*CA - z*SA)/SCALE-V
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > NPOLY
               PERFORM VARYING K FROM 1 BY 1 UNTIL K > NV
                   COMPUTE T = VX(I, K) * CA - VZ(I, K) * SA
                   COMPUTE WX(I, K) = T / SCALE-V
                   COMPUTE T = VX(I, K) * SA + VZ(I, K) * CA
                   COMPUTE WZ(I, K) = T / SCALE-V
                   COMPUTE T = VY(I, K) * CA - WZ(I, K) * SA / 4
                   COMPUTE WY(I, K) = T / SCALE-V
                   MOVE WX(I, K) TO VX(I, K)
                   MOVE WY(I, K) TO VY(I, K)
                   MOVE WZ(I, K) TO VZ(I, K)
               END-PERFORM
           END-PERFORM.

       CLEAR-FB.
           PERFORM VARYING ROW-IDX FROM 1 BY 1 UNTIL ROW-IDX > 224
               MOVE SPACES TO FB-ROW(ROW-IDX)
           END-PERFORM.

       PROJECT-POLY.
      *> perspective divide in integers: sx = x * 200 / (z + 4*SCALE-V)
           PERFORM VARYING K FROM 1 BY 1 UNTIL K > NV
               COMPUTE T = VZ(I, K) + 4 * SCALE-V
               IF T < 256 MOVE 256 TO T END-IF
               COMPUTE IX(K) = VX(I, K) * 200 / T + 160
               COMPUTE IY(K) = VY(I, K) * 200 / T + 112
           END-PERFORM.

       FILL-TRI.
           MOVE IY(1) TO YMIN
           MOVE IY(1) TO YMAX
           PERFORM VARYING K FROM 1 BY 1 UNTIL K > NV
               IF IY(K) < YMIN MOVE IY(K) TO YMIN END-IF
               IF IY(K) > YMAX MOVE IY(K) TO YMAX END-IF
           END-PERFORM
           IF YMIN < 1 MOVE 1 TO YMIN END-IF
           IF YMAX > 224 MOVE 224 TO YMAX END-IF
           PERFORM VARYING YY FROM YMIN BY 1 UNTIL YY > YMAX
               MOVE 400 TO XLEFT
               MOVE -100 TO XRIGHT
               PERFORM VARYING J FROM 1 BY 1 UNTIL J > NV
                   COMPUTE K = J + 1
                   IF K > NV MOVE 1 TO K END-IF
                   MOVE 0 TO CROSSED
                   IF IY(J) <= YY
                       IF IY(K) > YY MOVE 1 TO CROSSED END-IF
                   ELSE
                       IF IY(K) <= YY MOVE 1 TO CROSSED END-IF
                   END-IF
                   IF CROSSED = 1
                       IF IY(K) = IY(J)
                           MOVE IX(J) TO XT
                       ELSE
                           COMPUTE T = (YY - IY(J)) * (IX(K) - IX(J))
                           COMPUTE T = T / (IY(K) - IY(J))
                           COMPUTE XT = IX(J) + T
                       END-IF
                       IF XT < XLEFT MOVE XT TO XLEFT END-IF
                       IF XT > XRIGHT MOVE XT TO XRIGHT END-IF
                   END-IF
               END-PERFORM
               IF XLEFT < 1 MOVE 1 TO XLEFT END-IF
               IF XRIGHT > 320 MOVE 320 TO XRIGHT END-IF
               IF XRIGHT >= XLEFT
                   COMPUTE LEN = XRIGHT - XLEFT + 1
                   MOVE ALL "X" TO FB-ROW(YY)(XLEFT:LEN)
               END-IF
           END-PERFORM.

       CHECKSUM.
           PERFORM VARYING ROW-IDX FROM 1 BY 1 UNTIL ROW-IDX > 224
               MOVE 0 TO COUNTED
               INSPECT FB-ROW(ROW-IDX) TALLYING COUNTED FOR ALL "X"
               ADD COUNTED TO ACC
           END-PERFORM.
