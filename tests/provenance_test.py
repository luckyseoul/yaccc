#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Provenance checks: this tree stays MIT, and stays free of GPL code.

YACCC is MIT and targets compatibility with GnuCOBOL, which is GPL-3.0. The two
may be *used* together but must never be merged, and that distinction is easy to
lose by accident -- a copied test program, a vendored test suite checked in "just
for CI", a header pasted from a reference implementation. These checks fail the
build if that happens, so the acknowledgement in README.md is backed by
something that runs rather than by good intentions.

usage: provenance_test.py [-v] [--gnucobol PATH]

The default checks catch kept names, vendored files and licence text. They
cannot catch a translation that renamed everything, so `--gnucobol` adds the
measurement that can: token overlap against a GnuCOBOL source checkout. The
Make target `provenance-deep` runs it against `third_party/gnucobol`.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# this file necessarily contains the marker strings it looks for
SELF = 'tests/provenance_test.py'

# --gnucobol PATH: measure token overlap against a real GnuCOBOL source tree.
# A reimplementation necessarily reuses idioms -- a linked-list walk, a clamp,
# two adjacent setters -- so the ceiling sits above the idiom floor this tree
# already shows elsewhere (0.8%) and well below what a port of a file scores
# (the 2026-10-30 Report Writer port scored 2.1%).
OVERLAP_LIMIT = 1.5     # per cent of a file's 12-token runs
OVERLAP_RUN = 12
# A percentage alone misfires on small files: the '#include' prologue every C
# file must carry is ~10 twelve-token runs, which is 1.5% of a 700-token file
# and nothing at all in a 20,000-token one. Measured on this tree, idiom -- a
# table of strings, a printf format, a character scan loop -- tops out at 18
# matched runs (cobrt_conf.c), while the removed Report Writer port matched
# 124. Requiring both the percentage and this many runs separates the two:
# sharing scaffolding is not sharing code.
OVERLAP_MIN_RUNS = 40
# The same measure with every identifier and number replaced by a placeholder,
# so that renaming cannot move it. The removed Report Writer port is the
# reference case: 10.7% here, against 0.75% for the current engine. Renaming
# every identifier in it (no logic changed) moved its 12-token figure from
# 2.06% to 0.24% while leaving this one where it was, which is why both
# measures are kept. Measured on this tree: no file above 1.6%.
SHAPE_LIMIT = 3.0       # per cent of a file's normalised 20-token runs
SHAPE_RUN = 20
# A corpus that is missing or nearly empty would make every file score 0%,
# which is a pass that means nothing. Asking for the check is a commitment to
# its result, so both are failures, not skips. libcob measures ~172,000 runs.
OVERLAP_MIN_CORPUS = 20000

passed = failed = 0
verbose = '-v' in sys.argv


def check(name, ok, detail=''):
    global passed, failed
    if ok:
        passed += 1
        if verbose:
            print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}" + (f": {detail}" if detail else ''))


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=ROOT,
                          capture_output=True, text=True)


def gnucobol_path():
    for i, a in enumerate(sys.argv):
        if a == '--gnucobol' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith('--gnucobol='):
            return a.split('=', 1)[1]
    return None


def c_tokens(text):
    """C tokens with comments and literals blanked, so only code is compared."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', ' STR ', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", ' CHR ', text)
    return re.findall(r'[A-Za-z_]\w*|\d+(?:\.\d+)?|>>=|<<=|->|\+\+|--|&&|\|\||[^\sA-Za-z0-9_]',
                      text)


C_KEYWORDS = set('''auto break case char const continue default do double else enum
extern float for goto if inline int long register restrict return short signed
sizeof static struct switch typedef union unsigned void volatile while _Bool
NULL'''.split())


def shapes(tokens):
    """Tokens with names and numbers replaced: what is left is the code's
    shape, which renaming every identifier does not change."""
    out = []
    for t in tokens:
        if t[0].isdigit():
            out.append('N')
        elif (t[0].isalpha() or t[0] == '_') and t not in C_KEYWORDS and t not in ('STR', 'CHR'):
            out.append('I')
        else:
            out.append(t)
    return out


def strip_pp(tokens):
    """Drop preprocessor lines: '# include <...>', '# include STR', '# define'.

    Every C file opens with the same includes, so matching them says nothing
    about where the code came from. They are removed from the corpus and from
    the files being measured alike, so the comparison stays symmetric.
    """
    out = []
    i = 0
    while i < len(tokens):
        if tokens[i] == '#':
            i += 1
            if i < len(tokens):
                i += 1                      # the directive word
            if i < len(tokens) and tokens[i] == '<':
                while i < len(tokens) and tokens[i] != '>':
                    i += 1
                i += 1
            elif i < len(tokens) and tokens[i] == 'STR':
                i += 1
            continue
        out.append(tokens[i])
        i += 1
    return out


def shingles(tokens, n):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def check_overlap(src):
    """No tracked source file may be a translated GnuCOBOL C file.

    The marker grep above only catches kept names. Two measures look at the
    code itself, each the fraction of a file's token runs that also occur
    anywhere in GnuCOBOL's libcob and cobc (comments and literals removed):

    - verbatim 12-token runs catch a file carried over with its names, or with
      some of them; renaming moves this one;
    - 20-token runs with every name and number replaced by a placeholder catch
      a translation whatever it renamed: only restructuring moves this one.

    The corpus covers cobc as well as libcob, since a front-end translation is
    no more acceptable than a runtime one.
    """
    lib = os.path.join(src, 'libcob')
    # not a skip: --gnucobol was asked for, and a gate that cannot run must not
    # report success
    if not os.path.isdir(lib):
        check(f'GnuCOBOL sources present for the overlap check ({lib})', False,
              'no such directory; run make gctest or set GNUSRC')
        return
    corpus = set()
    shape_corpus = set()
    dirs = [lib] + [os.path.join(src, d) for d in ('cobc',)]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(('.c', '.h')):
                try:
                    toks = strip_pp(c_tokens(open(os.path.join(d, f), encoding='latin-1').read()))
                except OSError:
                    continue
                corpus |= shingles(toks, OVERLAP_RUN)
                shape_corpus |= shingles(shapes(toks), SHAPE_RUN)
    if verbose:
        print(f"       corpus: {len(corpus)} runs from {' and '.join(dirs)}")
    if len(corpus) < OVERLAP_MIN_CORPUS:
        check(f'GnuCOBOL corpus is large enough to measure against '
              f'({OVERLAP_MIN_CORPUS} runs)', False,
              f"only {len(corpus)} runs in {lib}")
        return
    rows = []
    for f in git('ls-files').stdout.split():
        if not f.endswith(('.c', '.h', '.py')):
            continue
        try:
            text = open(os.path.join(ROOT, f), encoding='latin-1').read()
        except OSError:
            continue
        toks = strip_pp(c_tokens(text))
        runs = shingles(toks, OVERLAP_RUN)
        shaped = shingles(shapes(toks), SHAPE_RUN)
        if runs and shaped:
            rows.append((100.0 * len(runs & corpus) / len(runs),
                         100.0 * len(shaped & shape_corpus) / len(shaped), f,
                         len(runs & corpus)))
    if not rows:
        check('the tree has source files to measure', False, 'none tracked')
        return
    over = [f"{f} {p:.2f}% ({n} runs)"
            for p, _, f, n in sorted(rows, reverse=True)
            if p > OVERLAP_LIMIT and n >= OVERLAP_MIN_RUNS]
    check(f'no source file shares more than {OVERLAP_LIMIT}% of its '
          f'{OVERLAP_RUN}-token runs with GnuCOBOL (at least '
          f'{OVERLAP_MIN_RUNS} of them)', not over, '; '.join(over))
    rows.sort(key=lambda r: r[1], reverse=True)
    over = [f"{f} {q:.2f}%" for _, q, f, _n in rows if q > SHAPE_LIMIT]
    check(f'no source file is a renamed GnuCOBOL C file (> {SHAPE_LIMIT}% of '
          f'its {SHAPE_RUN}-token runs, names ignored)', not over, '; '.join(over))
    if verbose:
        print(f"       {'verbatim':>8}  {'shape':>6}  file")
        for p, q, f, n in rows[:12]:
            print(f"       {p:7.2f}%  {q:5.2f}%  {f}  ({n} runs)")


def main():
    if git('rev-parse', '--is-inside-work-tree').returncode != 0:
        print("not a git checkout: provenance checks skipped")
        return 0

    # 1. the fetched third-party suites are never committed
    tracked = git('ls-files', 'third_party').stdout.split()
    check('no third_party file is tracked (GnuCOBOL and NIST suites are fetched)',
          not tracked,
          f"{len(tracked)} tracked, e.g. {tracked[:3]}")

    # 2. no GnuCOBOL source text: their distinctive function names would appear
    #    in any transliteration of reportio.c or fileio.c
    marks = ['do_page_footing', 'do_page_heading', 'write_to_line',
             'report_line_type', 'line_control_chg', 'saveLineCounter',
             'cob_report_generate', 'cob_report_terminate']
    hits = []
    for f in git('ls-files').stdout.split():
        if not f.endswith(('.c', '.h', '.py')):
            continue
        if f == SELF or f.startswith(('tests/gnucobol/', 'tests/nist/')):
            continue        # the runners name their suite's tests, not its code
        try:
            text = open(os.path.join(ROOT, f), encoding='latin-1').read()
        except OSError:
            continue
        hits += [f"{f}:{m}" for m in marks if m in text]
    check('no GnuCOBOL function body is translated into the tree',
          not hits, ', '.join(hits[:4]))

    # 3. no GPL notice or licence text pasted in from another project
    gpl = []
    for f in git('ls-files').stdout.split():
        base = os.path.basename(f)
        if base in ('COPYING', 'LICENSE') and base != 'LICENSE':
            gpl.append(f)
        if f == SELF or not f.endswith(('.c', '.h', '.py', '.sh')):
            continue
        try:
            text = open(os.path.join(ROOT, f), encoding='latin-1').read(4000)
        except OSError:
            continue
        if 'Free Software Foundation' in text or 'GNU General Public License' in text:
            gpl.append(f)
    check('no GPL notice in a tracked source file', not gpl, ', '.join(gpl[:4]))

    # 4. the project licence itself is still MIT
    try:
        lic = open(os.path.join(ROOT, 'LICENSE'), encoding='latin-1').read()
    except OSError:
        lic = ''
    check('LICENSE is MIT', 'MIT License' in lic or 'Permission is hereby granted' in lic)

    # 5. every tracked source file carries the project's SPDX line, so a file
    #    copied in from elsewhere is visible by its missing tag
    missing = []
    for f in git('ls-files').stdout.split():
        if not f.endswith(('.c', '.h', '.py', '.sh')) or f.startswith('tests/'):
            continue
        try:
            head = open(os.path.join(ROOT, f), encoding='latin-1').read(300)
        except OSError:
            continue
        if 'SPDX-License-Identifier: MIT' not in head:
            missing.append(f)
    check('every source file carries SPDX-License-Identifier: MIT',
          not missing, ', '.join(missing[:4]))

    # 6. the acknowledgement exists, and names GnuCOBOL
    try:
        readme = open(os.path.join(ROOT, 'README.md'), encoding='latin-1').read()
    except OSError:
        readme = ''
    # the heading may be either name; what matters is that GnuCOBOL is
    # credited somewhere the reader will find it
    credited = (('## Credits' in readme or '## Acknowledgements' in readme)
                and 'GnuCOBOL' in readme)
    check('README credits GnuCOBOL', credited)

    # 7. optional and much stronger: with a GnuCOBOL source tree to compare
    #    against, measure how much of each runtime file reappears in libcob
    gnu = gnucobol_path()
    if gnu:
        check_overlap(gnu)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
