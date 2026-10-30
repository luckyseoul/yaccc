#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run one GnuCOBOL testsuite test with YACCC and with GnuCOBOL's own cobc,
and show exactly where their output files differ.

usage: compare.py TITLE [TITLE ...] [--suite DIR] [--cobc PATH]

This is the tool to reach for when working on a testsuite failure: it runs the
same program through both compilers in a temporary directory each, then compares
the files those programs wrote (not just stdout, which for Report Writer tests
is empty). The first differing line is usually the whole story.

It needs a GnuCOBOL built from source; see docs/gnucobol-oracle.md. Without
--cobc it looks for cobc on PATH, and it exits with status 2 if there is none.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
YACCC = os.path.join(ROOT, 'yaccc')
DEFAULT_SUITE = os.path.join(ROOT, 'third_party', 'gnucobol', 'tests', 'testsuite.src')


def parse_block(text, title):
    """The AT_SETUP block for `title`: its AT_DATA files and its run command."""
    i = text.find('AT_SETUP([' + title + '])')
    if i < 0:
        return None
    j = text.find('AT_CLEANUP', i)
    block = text[i:j]
    # AT_DATA([name],[content]) or AT_DATA([name], [\ncontent\n])
    files = {m.group(1): m.group(2).strip('\n')
             for m in re.finditer(r'AT_DATA\(\[(.*?)\],\s*\[(.*?)\]\)', block, re.S)}
    m = re.search(r'AT_CHECK\(\[(.*?)\$COBCRUN(?:_DIRECT)? \./prog\], \[(\d+)\]', block)
    if not m:
        return None
    cmd, status = m.group(1), int(m.group(2))
    dd = dict(re.findall(r'DD_(\w+)="?\./([^"\s]+)', cmd))
    out = re.search(r'AT_CHECK\(\[(?:cat|diff reference) ([^\s\]]+)', block)
    if out:
        name = out.group(1)
    else:
        # the tests that check the report file through the DD_ variable
        cap = re.search(r'AT_CAPTURE_FILE\(\./(\S+)\)', block)
        name = cap.group(1) if cap else (list(dd.values())[-1] if dd else None)
    return {'files': files, 'dd': dd, 'status': status, 'output': name}


def run(block, compiler, cobc):
    d = tempfile.mkdtemp(prefix='cmp_')
    env = dict(os.environ)
    for name, text in block['files'].items():
        with open(os.path.join(d, name), 'w', encoding='latin-1') as f:
            f.write(text + '\n')
    for var, name in block['dd'].items():
        env['DD_' + var] = './' + name
    cc = [cobc, '-x', '-o', 'prog', 'prog.cob'] if compiler == 'cobc' else \
         [YACCC, 'prog.cob', '-o', 'prog']
    r = subprocess.run(cc, cwd=d, capture_output=True, env=env)
    if r.returncode:
        shutil.rmtree(d, ignore_errors=True)
        return None, 'compile failed: ' + r.stderr.decode('latin-1', 'replace')[:200]
    r = subprocess.run(['./prog'], cwd=d, capture_output=True, env=env)
    text = None
    if block['output']:
        p = os.path.join(d, block['output'])
        if os.path.exists(p):
            text = open(p, encoding='latin-1').read()
    else:
        # a test that checks stdout itself (no DD_ output file)
        text = r.stdout.decode('latin-1')
    shutil.rmtree(d, ignore_errors=True)
    note = None
    if r.returncode != block['status']:
        note = (f"exit {r.returncode}, expected {block['status']}: "
                + r.stderr.decode('latin-1', 'replace')[:200])
    return text, note


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('titles', nargs='+')
    ap.add_argument('--suite', default=DEFAULT_SUITE)
    ap.add_argument('--cobc', default='cobc')
    ap.add_argument('--file', default='run_reportwriter.at')
    a = ap.parse_args()
    if not shutil.which(a.cobc):
        print(f"no GnuCOBOL cobc at '{a.cobc}': see docs/gnucobol-oracle.md", file=sys.stderr)
        return 2
    src = open(os.path.join(a.suite, a.file), encoding='latin-1').read()
    bad = 0
    for title in a.titles:
        block = parse_block(src, title)
        if block is None:
            # the title may be in another .at file (the default --file is only
            # the Report Writer suite): search the rest of the suite
            for name in sorted(os.listdir(a.suite)):
                if not name.endswith('.at'):
                    continue
                try:
                    other = open(os.path.join(a.suite, name), encoding='latin-1').read()
                except OSError:
                    continue
                found = parse_block(other, title)
                if found is not None:
                    block, src = found, other
                    break
        if block is None:
            print(f"{title}: not found in {a.file}")
            bad += 1
            continue
        want, wn = run(block, 'cobc', a.cobc)
        got, gn = run(block, 'yaccc', a.cobc)
        print(f"=== {title}")
        for tag, note in (('cobc', wn), ('yaccc', gn)):
            if note:
                print(f"  {tag}: {note.replace(chr(10), ' ')}")
        if want is None or got is None:
            bad += 1
            continue
        if want == got:
            print("  identical")
            continue
        bad += 1
        al, bl = want.split('\n'), got.split('\n')
        diffs = [(k + 1, al[k] if k < len(al) else None, bl[k] if k < len(bl) else None)
                 for k in range(max(len(al), len(bl)))
                 if (al[k] if k < len(al) else None) != (bl[k] if k < len(bl) else None)]
        blank = [d for d in diffs if not (d[1] or '').strip() and not (d[2] or '').strip()]
        print(f"  cobc {len(al)} lines, yaccc {len(bl)} lines | differing {len(diffs)}"
              f" ({len(blank)} of them blank-on-both-sides)")
        for k, x, y in diffs[:6]:
            print(f"    L{k}: cobc ={x!r}")
            print(f"         yaccc={y!r}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
