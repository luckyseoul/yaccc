# Benchmarks

YACCC against GnuCOBOL 3.1.2 and gcobol (GCC 15.2's COBOL front end). One
machine: 2× 22-core Xeon with SMT, 44 physical cores. Same `-O2`, best of five
runs, each pinned to its own core, results verified identical before timing.

Numbers are wall-clock for the whole process, including startup. Every program
prints a checksum that all three compilers agree on, checked before the timings
were taken.

## Runtime

Milliseconds, best of `--reps` runs, each pinned to its own physical core so
nothing shares an SMT sibling. Lower is better; bold is the fastest.

The chart uses dots rather than bars on purpose. The values span 14 ms to
264 s, so the axis has to be logarithmic, and a bar on a log axis is a lie: its
length reads as proportional to the value when it is really `log(value)`, which
would draw 1,229 and 2,242 ms a few percent apart in order to show a 1.8×
difference. A dot has no length to misread.

Each benchmark is a shaded row with its three dots on one line and the values
in a column beside them, so a row can be traced across without the dots of one
benchmark being mistaken for another's.

| Benchmark | What it does | YACCC | GnuCOBOL | gcobol |
|---|---|---:|---:|---:|
| `b1_arith` | 3,000,000 fixed-point COMPUTE/ADD | **1,229** | 2,242 | 3,395 |
| `b2_func` | 300,000 SQRT/SIN/EXP iterations | 13,933 | 77,740 | **1,085** |
| `b3_sort` | in-memory SORT of 200,000 keys | 287 | **286** | 743 |
| `b4_str` | 200,000 STRING operations | **14** | 17 | 64 |
| `b5_file` | write and read back 500,000 records | **120** | 154 | 847 |
| `b6_gfx` | 200 frames of a software rasteriser: 24 rotated triangles, scanline-filled into 320×224 | **185** | 244 | 941 |
| `b7_mandel` | Mandelbrot, 640×480, up to 2,000 iterations, 28-bit fixed point | **91,803** | 122,607 | 264,224 |

![Runtime for seven benchmarks across three compilers, as dots on a log axis](img/bench-time.svg)

Relative to GnuCOBOL: **1.2× to 1.8×** faster on arithmetic, strings, files,
graphics and the Mandelbrot; **5.6×** on transcendental functions; a dead heat
on `qsort`.

![The same data as a ratio to GnuCOBOL](img/bench-ratio.svg)

The one place YACCC loses badly is `b2_func`: gcobol is **12.8× faster** than
YACCC there, and 71.7× faster than GnuCOBOL, which is the far dot in the
chart. That is a design difference, not a defect. gcobol lowers those to
native `double` and the hardware libm; YACCC runs them through its own 640-bit
software fixed-point, which carries more significant digits and exact scaling
but costs an order of magnitude. All three agree to about 1e-11 relative on the
result.

`b3_sort` is a tie because both call the C library's `qsort` on the same data.

The two graphics benchmarks use a second difference worth noting. `b6_gfx` is
written in pure scaled-integer arithmetic and `b7_mandel` in fixed point, so
every compiler produces a byte-identical checksum. That is deliberate: a
rasteriser written in floating point lands on rounding boundaries differently
depending on how a compiler rounds, the checksums diverge, and the timings stop
being comparable. Both checksums were confirmed equal across all three
compilers before any timing was taken.

## Compile time

Seconds, best of five.

| Source | Lines | YACCC | GnuCOBOL | gcobol |
|---|---:|---:|---:|---:|
| `b1_arith` | 18 | 0.24 | 0.12 | 0.11 |
| `b4_str` | 27 | 0.22 | 0.12 | 0.11 |
| `big` (4,207 lines, with a copybook) | 4,207 | 16.0 | 6.9 | — |

YACCC is about **2× slower to compile**, consistently. It is a Python program
front to back with no build step; the other two are native. The gap is the
interpreter, not the code generator, and it is the price of the thing that makes
YACCC easy to work on.

## Binary size

Bytes.

| | YACCC | GnuCOBOL | gcobol |
|---|---:|---:|---:|
| `b1_arith` | 439,880 | 14,664 | 25,728 |
| `b6_gfx` | 454,608 | 23,432 | 83,496 |
| `b7_mandel` | 449,656 | 19,368 | 45,704 |
| `big` (4,207 lines) | 1,050,936 | 294,760 | — |

YACCC links its runtime statically, so a hello-world is **30× larger** than
GnuCOBOL's. The other two link a shared library at run time. A `-static` option
for programs that need to move between machines without the archive is not
implemented; this is the clearest thing on the list worth fixing.

## Caveats

- GnuCOBOL was built `--without-db`, so it has no ISAM handler. None of the
  benchmarks above use indexed files, but its figure is from that build.
- gcobol refused nothing in the final run: after the benchmarks were rewritten
  in ISO syntax (level-78 constants and a level-01 `OCCURS` replaced with
  ordinary items and a group) it compiled all seven. An earlier version of
  `b6_gfx` used level-78 constants and was rejected; that was the benchmark's
  dialect, not a missing feature.
- One machine, one run of the suite. These are indicative, not a laboratory
  result; the relative ordering was stable across the five repetitions taken.

## Reproducing

The programs and the runner are in the repository under `tests/bench/`. They
build with any of the three; `run.sh` times whatever compilers it finds:

```
./tests/bench/run.sh            # uses cobc and gcobol if on PATH
```
