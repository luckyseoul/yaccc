#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Draw the benchmark figures from a run of tests/bench/run.py.

    ./tests/bench/run.py --reps 5 --jobs 1 > /tmp/run.txt
    ./tests/bench/figures.py /tmp/run.txt

Two figures come out, both written to docs/img:

  bench-time.svg   One row per benchmark. Each row is scaled to its own
                   slowest compiler, so bar length is the ratio within the
                   row and the absolute milliseconds sit in a column beside it.
                   No shared axis can work across 14 ms to 270 s: on a log axis
                   a 3x difference is a few percent of the width, and on a
                   linear axis everything but the slowest benchmark collapses
                   against the left edge.

  bench-ratio.svg  The same measurements against one baseline compiler. A log
                   axis is correct here because a ratio is already
                   multiplicative: 2x and 0.5x sit equally far from the centre.

Parsing the runner's own output, rather than carrying a copy of the numbers,
is what keeps the pictures from drifting away from the measurements.
"""
import math
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'docs', 'img')

BASELINE = 'gnucobol-3.2'

PAPER = "#faf7ef"
INK = "#1b1916"
MUTED = "#6d655a"
FAINT = "#9a9184"
RULE = "#ddd5c3"
MONO = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'Liberation Mono', monospace")
SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, "
        "sans-serif")

# colour by lineage, shade by release, so the families read at a glance
COLOURS = {
    'yaccc': "#1f6f4a",
    'gnucobol-3.1.2': "#7d4a12",
    'gnucobol-3.2': "#b0701f",
    'gnucobol-4.0': "#d9a45c",
    'gcobol-15.2': "#2b4a75",
    'gcobol-16': "#6d92c4",
}
FALLBACK = ["#5b7d3a", "#8a4f7d", "#3f7d7d", "#7d6a3a"]

LABELS = {
    'b1_arith': "fixed-point arithmetic",
    'b2_func': "SQRT/SIN/EXP",
    'b3_sort': "table SORT",
    'b4_str': "STRING/UNSTRING",
    'b5_file': "500k records to file",
    'b6_gfx': "software rasteriser",
    'b7_mandel': "Mandelbrot 640×480",
}


def parse(path):
    """Return (compilers, rows, reps) from the runner's table."""
    text = open(path).read()
    lines = text.splitlines()
    reps = None
    m = re.search(r'reps=(\d+)', text)
    if m:
        reps = int(m.group(1))
    head = None
    rows = []
    for line in lines:
        if line.startswith('benchmark'):
            head = line.split()[1:]
            continue
        if head and re.match(r'^b\d+_\w+\s', line):
            parts = line.split()
            key = parts[0]
            vals = []
            for tok in parts[1:]:
                vals.append(float(tok[:-1]) if tok.endswith('s') else None)
            if len(vals) == len(head):
                rows.append((key, vals))
    if not head or not rows:
        sys.exit(f'no benchmark table in {path}')
    return head, rows, reps


def t(x, y, s, size=10, fill=INK, anchor="start", weight="normal",
      family=MONO, ls=0):
    extra = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}"{extra}>{escape(s)}</text>')


def head(w, h, title, sub):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img">',
            f'<rect width="{w}" height="{h}" fill="{PAPER}"/>',
            t(24, 32, title.upper(), 11.5, MUTED, weight="600", ls=1.9),
            t(24, 52, sub, 10, FAINT, family=SANS)]


def nice(v):
    if v >= 1000:
        return f"{v / 1000:,.1f} s"
    return f"{v:,.0f} ms" if v >= 100 else f"{v:.0f} ms"


# ---------------------------------------------------------------- runtime
def time_fig(ccs, rows, reps):
    n = len(ccs)
    rh = 20 + n * 11
    w = 880
    top = 104
    h = top + len(rows) * rh + 78
    o = head(w, h, "Runtime: every benchmark, every compiler measured",
             "Each row is scaled to its own slowest compiler, so bar length is "
             "the ratio within the row. Absolute times at right.")
    bx, bw = 210, 340
    vx = 712
    bh, pitch = 6, 11

    for i in range(len(rows)):
        if i % 2 == 0:
            o.append(f'<rect x="16" y="{top + i * rh - 12}" width="{w - 32}" '
                     f'height="{rh - 6}" fill="#f2ede1" rx="4"/>')
    o.append(t(vx, top - 24, "ms", 8.8, FAINT, anchor="end"))

    for i, (key, vals) in enumerate(rows):
        yy = top + i * rh
        slowest = max(vals)
        o.append(t(bx - 16, yy + 9, LABELS.get(key, key), 9.8, INK,
                   anchor="end", weight="600"))
        o.append(t(bx - 16, yy + 21, key, 8, FAINT, anchor="end"))
        for j, (val, name) in enumerate(zip(vals, ccs)):
            if val is None:
                continue
            by = yy + 2 + j * pitch
            colour = COLOURS.get(name, FALLBACK[j % len(FALLBACK)])
            o.append(f'<rect x="{bx}" y="{by}" '
                     f'width="{val / slowest * bw:.1f}" height="{bh}" '
                     f'fill="{colour}" rx="2"/>')
            o.append(t(vx, by + 6.2, f"{val * 1000:,.0f}", 8.4, MUTED,
                       anchor="end"))

    legend(o, bx, h - 42, ccs)
    note = (f"Best of {reps} runs, each pinned to its own physical core and "
            "run one at a time." if reps else "Each run pinned to its own core.")
    o.append(t(24, h - 16, note + " Lower is better; a full bar is that row's "
                           "slowest.", 9, FAINT, family=SANS))
    o.append("</svg>")
    open(os.path.join(OUT, "bench-time.svg"), "w").write("\n".join(o) + "\n")


def legend(o, x, y, names):
    for name in names:
        colour = COLOURS.get(name, FAINT)
        o.append(f'<circle cx="{x + 5:.1f}" cy="{y - 3.5:.1f}" r="4.5" '
                 f'fill="{colour}"/>')
        o.append(t(x + 16, y, name, 9.4, MUTED))
        x += 34 + len(name) * 5.5


# ---------------------------------------------------------------- ratio
def ratio_fig(ccs, rows, reps):
    if BASELINE not in ccs:
        sys.exit(f'no {BASELINE} column to use as the baseline')
    b = ccs.index(BASELINE)
    n = len(ccs) - 1
    rh = 20 + n * 12
    w = 880
    top = 108
    h = top + len(rows) * rh + 78
    o = head(w, h, f"Same data as a ratio to {BASELINE}",
             "Right of the line is faster than the baseline, left is slower. "
             "Log axis, so 2x and 0.5x sit equally far out.")
    ax0, ax1 = 296, 660
    vx = 748
    lo, hi = math.log10(0.1), math.log10(100)

    def px(r):
        return ax0 + (math.log10(max(min(r, 100), 0.1)) - lo) / (hi - lo) * (ax1 - ax0)

    cx = px(1.0)
    for i in range(len(rows)):
        if i % 2 == 0:
            o.append(f'<rect x="16" y="{top + i * rh - 12}" width="{w - 32}" '
                     f'height="{rh - 6}" fill="#f2ede1" rx="4"/>')
    for r, label in ((0.1, "10x slower"), (0.3, "3x"), (1, "equal"),
                     (3, "3x faster"), (10, "10x"), (30, "30x")):
        x = px(r)
        strong = r == 1
        o.append(f'<line x1="{x:.1f}" y1="{top - 17}" x2="{x:.1f}" '
                 f'y2="{top + len(rows) * rh - 10}" '
                 f'stroke="{INK if strong else RULE}" '
                 f'stroke-width="{1.3 if strong else 1}"/>')
        o.append(t(x, top - 23, label, 8.8, INK if strong else FAINT,
                   anchor="middle"))
    o.append(t(vx, top - 23, "ratio", 8.8, FAINT, anchor="end"))

    for i, (key, vals) in enumerate(rows):
        yy = top + i * rh
        base = vals[b]
        o.append(t(ax0 - 14, yy + 9, LABELS.get(key, key), 9.8, INK,
                   anchor="end", weight="600"))
        o.append(t(ax0 - 14, yy + 21, key, 8, FAINT, anchor="end"))
        j = 0
        for k, (val, name) in enumerate(zip(vals, ccs)):
            if k == b or val is None:
                continue
            r = base / val                       # > 1 means faster than base
            x = px(r)
            cy = yy + 1 + j * 12
            colour = COLOURS.get(name, FALLBACK[j % len(FALLBACK)])
            o.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" '
                     f'y2="{cy:.1f}" stroke="{colour}" stroke-width="1.1" '
                     f'opacity="0.4"/>')
            o.append(f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="4.0" '
                     f'fill="{colour}"/>')
            o.append(t(vx, cy + 3.4, f"{r:.1f}x" if r >= 0.1 else "<0.1x",
                       8.5, MUTED, anchor="end"))
            j += 1

    names = [c for i, c in enumerate(ccs) if i != b]
    legend(o, ax0 - 14, h - 42, names)
    note = (f"Baseline is {BASELINE}. Best of {reps} runs, one at a time."
            if reps else f"Baseline is {BASELINE}.")
    o.append(t(24, h - 16, note, 9, FAINT, family=SANS))
    o.append("</svg>")
    open(os.path.join(OUT, "bench-ratio.svg"), "w").write("\n".join(o) + "\n")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[0])
    ccs, rows, reps = parse(sys.argv[1])
    os.makedirs(OUT, exist_ok=True)
    time_fig(ccs, rows, reps)
    ratio_fig(ccs, rows, reps)
    for f in ("bench-time.svg", "bench-ratio.svg"):
        p = os.path.join(OUT, f)
        print(f"  {f}  {os.path.getsize(p):,} bytes")


if __name__ == '__main__':
    main()
