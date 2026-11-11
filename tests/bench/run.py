#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Time the benchmark programs against whichever compilers are installed.

    ./tests/bench/run.py                # every compiler it finds
    ./tests/bench/run.py --reps 9       # more repetitions
    ./tests/bench/run.py --only b1_arith b4_str

YACCC is the one in this repository. GnuCOBOL and gcobol are used when `cobc`
and `gcobol` are on `PATH` (or named by $COBC and $GCOBOL). Each program is
built at -O2, run once to check that the compilers agree on its output, and
then timed; a program whose outputs disagree is reported and not timed.

`BENCH_COMPILERS` adds more, as a comma-separated list of `label=/path/to/cc`.
Each label is used as a column heading, and the command line is chosen from the
file name: a name containing `gcobol` is driven like gcobol, one containing
`cobc` like GnuCOBOL, `yaccc` like this repository's compiler. So a wrapper
script is enough to put a second GnuCOBOL release in the same table:

    BENCH_COMPILERS='gnucobol-3.2=/opt/gc32/cobc,cobc=/usr/bin/cobc' \
        ./tests/bench/run.py

Builds run in parallel. Timings run in parallel too, each pinned to its own
physical core, so two runs never share a core. That is not the same as
independence: they still share memory bandwidth, cache and memory controller,
and measurement showed the effect is large. Timing all forty-two
(benchmark, compiler) pairs at once raised arithmetic from 0.99s to 1.25s
(+26%) and the Mandelbrot from 83.2s to 92.8s (+12%), and it compressed the
gaps between close rows, so differences that are real serially can vanish.
Pinning keeps a run off its twin's core; it does not give it a private
machine.

So the default is one measurement per physical core, which is fast and fine for
a rough look, and `--jobs 1` is for numbers worth publishing. The results are
single-core measurements either way; only the contention differs.

This is a development tool. It writes nothing outside a temporary directory
except the file `b5_file` creates, which it removes.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
YACCC = os.path.join(ROOT, 'yaccc')

BENCH = ['b1_arith', 'b2_func', 'b3_sort', 'b4_str', 'b5_file',
         'b6_gfx', 'b7_mandel']


def physical_cores():
    """One CPU number per physical core, so a run is never sharing an SMT
    sibling with another run. Falls back to every CPU if the topology is not
    readable."""
    cores = []
    for d in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/topology/thread_siblings_list'):
        cpu = int(d.split('/')[-3].replace('cpu', ''))
        try:
            sibs = open(d).read().strip()
        except OSError:
            continue
        lo = min(int(x) for x in sibs.replace('-', ',').split(','))
        if cpu == lo:
            cores.append(cpu)
    return sorted(cores) or list(range(os.cpu_count() or 4))


def compilers():
    found = {'yaccc': YACCC if os.path.exists(YACCC) else None}
    found['cobc'] = os.environ.get('COBC') or shutil.which('cobc')
    found['gcobol'] = os.environ.get('GCOBOL') or shutil.which('gcobol')
    found = {k: v for k, v in found.items() if v}
    for spec in os.environ.get('BENCH_COMPILERS', '').split(','):
        label, _, path = spec.partition('=')
        label, path = label.strip(), path.strip()
        if not label or not path:
            continue
        if not os.path.exists(path):
            print(f'ignoring {label}: no such file {path}', file=sys.stderr)
            continue
        found[label] = path
    return found


def build(cc, name, workdir):
    """Compile one benchmark; return (exe, error)."""
    src = os.path.join(HERE, name + '.cbl')
    exe = os.path.join(workdir, f'{name}.{os.path.basename(cc)}')
    base = os.path.basename(cc)
    if base == 'yaccc':
        cmd = [cc, src, '-O2', '-o', exe]
    elif 'gcobol' in base:
        cmd = [cc, src, '-O2', '-o', exe]
    else:
        cmd = [cc, '-x', '-O2', '-o', exe, src]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True)
    if r.returncode:
        err = (r.stderr or r.stdout).decode('latin-1', 'replace').strip()
        return None, (err.splitlines() or ['failed'])[0][:90]
    return exe, ''


def run_pinned(exe, cwd, cpu):
    """Run one executable on one core.

    Each run gets its own empty directory, because a benchmark that writes a
    file would otherwise have several concurrent runs overwriting the same
    one and measuring each other's I/O.
    """
    d = tempfile.mkdtemp(prefix='run_', dir=cwd)
    cmd = ['taskset', '-c', str(cpu), exe] if shutil.which('taskset') else [exe]
    try:
        r = subprocess.run(cmd, cwd=d, capture_output=True, timeout=900)
        return r.returncode, r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


def same_output(a, b):
    """Do two runs agree?

    Exactly, or -- when both print a number -- to within 1e-9 relative. The
    transcendental benchmark accumulates in floating point, and the three
    compilers legitimately land a few units in the last place apart; treating
    that as disagreement would throw the benchmark away.
    """
    if a == b:
        return True
    try:
        x = float(a.decode().strip())
        y = float(b.decode().strip())
    except (ValueError, AttributeError):
        return False
    if y == 0:
        return abs(x) < 1e-12
    return abs(x - y) / abs(y) < 1e-9


def timeit(exe, cwd, cpu, reps):
    """Best of `reps`, but fewer for a slow benchmark.

    A 67-second run repeated five times costs five minutes and tells you no
    more than three do: the minimum of a handful of clean runs is already
    stable when each run is long. Repetitions exist to filter scheduler noise,
    and long runs have less of it.
    """
    best = None
    done = 0
    keep = reps
    while done < keep:
        t = time.perf_counter()
        run_pinned(exe, cwd, cpu)
        d = time.perf_counter() - t
        best = d if best is None else min(best, d)
        done += 1
        if done == 1:
            # long runs carry their own averaging: a 90-second run repeated
            # three times costs four minutes and moves the answer by less
            # than the noise it is meant to remove
            if d > 20.0:
                keep = 1
            elif d > 2.0:
                keep = min(reps, 3)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reps', type=int, default=5)
    ap.add_argument('--only', nargs='*', default=None)
    ap.add_argument('--jobs', type=int, default=0,
                    help='max concurrent measurements (default: one per '
                         'physical core). Lower it when comparing many '
                         'compilers: pinning stops two runs sharing an SMT '
                         'sibling, but not sharing memory bandwidth, so '
                         'timing everything at once inflates every number '
                         'by about a quarter.')
    a = ap.parse_args()

    ccs = compilers()
    if 'yaccc' not in ccs:
        print('this repo has no ./yaccc; run it from a checkout')
        return 2
    if len(ccs) < 2:
        print('only %s found; install cobc or gcobol to compare' % ', '.join(ccs))
        return 2

    names = a.only or BENCH
    work = tempfile.mkdtemp(prefix='bench_')
    cores = physical_cores()
    if a.jobs:
        cores = cores[:max(1, a.jobs)]
    jobs = [(n, cc) for n in names for cc in ccs]

    print(f"reps={a.reps}  compilers: {', '.join(ccs)}  "
          f"pinned to {len(cores)} physical cores\n")

    # 1. build everything at once
    built, refused = {}, {}
    keys = [(n, c) for n in names for c in ccs]
    with ThreadPoolExecutor(max_workers=max(1, min(len(keys), len(cores)))) as pool:
        futs = {k: pool.submit(build, ccs[k[1]], k[0], work) for k in keys}
        for key, fut in futs.items():
            exe, err = fut.result()
            if exe is None:
                refused[key] = err
            else:
                built[key] = exe

    # 2. one unchecked run per (benchmark, compiler) to confirm they agree
    outs = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(built), len(cores)))) as pool:
        futs = {k: pool.submit(run_pinned, exe, work, cores[i % len(cores)])
                for i, (k, exe) in enumerate(sorted(built.items()))}
        for key, fut in futs.items():
            rc, out = fut.result()
            outs[key] = out

    # 3. time every (benchmark, compiler) that can be compared at all, each on
    # its own core: a benchmark whose compilers disagree is skipped entirely
    comparable = set()
    for name in names:
        present = [outs.get((name, c)) for c in ccs]
        present = [v for v in present if v is not None]
        if present and all(same_output(present[0], v) for v in present[1:]):
            comparable.update((name, c) for c in ccs)
    cw = max([9] + [len(n) for n in ccs])
    print(f"{'benchmark':10s} " + ' '.join(f'{n:>{cw}s}' for n in ccs))
    timings = {}
    tasks = []
    for i, (key, exe) in enumerate(sorted(built.items())):
        if key in comparable:
            tasks.append((key, exe, cores[i % len(cores)]))
    with ThreadPoolExecutor(max_workers=max(1, min(len(tasks), len(cores)))) as pool:
        futs = {key: pool.submit(timeit, exe, work, cpu, a.reps)
                for key, exe, cpu in tasks}
        for key, fut in futs.items():
            timings[key] = fut.result()

    try:
        for name in names:
            present = [outs.get((name, c)) for c in ccs]
            present = [v for v in present if v is not None]
            if not present:
                why = sorted({refused[(name, c)].split(':')[0]
                              for c in ccs if (name, c) in refused})
                print(f"{name:10s} no compiler produced it"
                      + (f" ({'; '.join(why)[:70]})" if why else ''))
                continue
            if not all(same_output(present[0], v) for v in present[1:]):
                print(f"{name:10s} outputs disagree between compilers; not timed")
                continue
            row = []
            for c in ccs:
                t = timings.get((name, c))
                row.append(f'{t:>{cw - 1}.3f}s' if t is not None
                           else f'{"refused":>{cw}s}')
            print(f"{name:10s} " + ' '.join(row))
            for c in ccs:
                if (name, c) in refused:
                    print(f"           {c} refused it: {refused[(name, c)]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        for junk in ('bench.dat',):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
