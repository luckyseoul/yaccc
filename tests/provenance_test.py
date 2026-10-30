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


def shingles(tokens, n):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def check_overlap(src):
    """No runtime file may be a renamed copy of a GnuCOBOL C file.

    The marker grep above only catches kept names. This measures the code
    itself: the fraction of a file's 12-token runs that also occur anywhere in
    libcob. Renaming identifiers does not move it; restructuring does.
    """
    lib = os.path.join(src, 'libcob')
    # not a skip: --gnucobol was asked for, and a gate that cannot run must not
    # report success
    if not os.path.isdir(lib):
        check(f'GnuCOBOL sources present for the overlap check ({lib})', False,
              'no such directory; run make gctest or set GNUSRC')
        return
    corpus = set()
    for f in sorted(os.listdir(lib)):
        if f.endswith(('.c', '.h')):
            try:
                corpus |= shingles(c_tokens(
                    open(os.path.join(lib, f), encoding='latin-1').read()),
                    OVERLAP_RUN)
            except OSError:
                continue
    if verbose:
        print(f"       corpus: {len(corpus)} runs from {lib}")
    if len(corpus) < OVERLAP_MIN_CORPUS:
        check(f'GnuCOBOL corpus is large enough to measure against '
              f'({OVERLAP_MIN_CORPUS} runs)', False,
              f"only {len(corpus)} runs in {lib}")
        return
    rows = []
    for f in git('ls-files', 'runtime').stdout.split():
        if not f.endswith(('.c', '.h')):
            continue
        try:
            text = open(os.path.join(ROOT, f), encoding='latin-1').read()
        except OSError:
            continue
        runs = shingles(c_tokens(text), OVERLAP_RUN)
        if runs:
            rows.append((100.0 * len(runs & corpus) / len(runs), f))
    rows.sort(reverse=True)
    if not rows:
        check('runtime/ has files to measure', False, 'no tracked runtime C file')
        return
    over = [f"{f} {p:.2f}%" for p, f in rows if p > OVERLAP_LIMIT]
    check(f'no runtime file is a renamed GnuCOBOL C file (> {OVERLAP_LIMIT}% '
          f'shared {OVERLAP_RUN}-token runs)', not over, '; '.join(over))
    for p, f in rows if verbose else ():
        print(f"       {p:5.2f}%  {f}")


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
    check('README has an Acknowledgements section naming GnuCOBOL',
          '## Acknowledgements' in readme and 'GnuCOBOL' in readme)

    # 7. optional and much stronger: with a GnuCOBOL source tree to compare
    #    against, measure how much of each runtime file reappears in libcob
    gnu = gnucobol_path()
    if gnu:
        check_overlap(gnu)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
