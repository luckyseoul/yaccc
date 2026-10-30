#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Provenance checks: this tree stays MIT, and stays free of GPL code.

YACCC is MIT and targets compatibility with GnuCOBOL, which is GPL-3.0. The two
may be *used* together but must never be merged, and that distinction is easy to
lose by accident -- a copied test program, a vendored test suite checked in "just
for CI", a header pasted from a reference implementation. These checks fail the
build if that happens, so the acknowledgement in README.md is backed by
something that runs rather than by good intentions.

usage: provenance_test.py [-v]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

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
        if f.startswith(('tests/gnucobol/', 'tests/nist/')):
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
        if not f.endswith(('.c', '.h', '.py', '.sh')):
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

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
