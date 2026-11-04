#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Embedded SQL tests: the programs in tests/sql run against SQLite (a
database file in a temporary directory) and against PostgreSQL when a server
can be had, and each program's output must match its .expected file -- the
same file for both databases.

PostgreSQL: YACCC_TEST_PG names a server (a libpq connection string, the
tests create and drop their own tables in it); otherwise, when PostgreSQL's
initdb is installed and this isn't run as root, a throwaway server is started
in the temporary directory and stopped at the end. YACCC_TEST_PG=none skips
PostgreSQL."""
import ctypes
import ctypes.util
import glob
import os
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')
CASES = os.path.join(HERE, 'sql')

# sqlend runs four times, the database carrying over from one to the next
RUNS = {'sqlend': ['setup', 'normal', 'abend', 'check']}


def have_lib(names):
    for n in names:
        try:
            ctypes.CDLL(n)
            return True
        except OSError:
            pass
    return False


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_postgres(work):
    """A throwaway PostgreSQL server: (connection string, stop function), or
    (None, reason)."""
    given = os.environ.get('YACCC_TEST_PG')
    if given:
        if given.lower() == 'none':
            return None, 'YACCC_TEST_PG=none'
        return given, None
    initdb = shutil.which('initdb') or next(iter(sorted(glob.glob('/usr/lib/postgresql/*/bin/initdb'))[-1:]),
                                            None)
    if not initdb:
        return None, 'no PostgreSQL server (initdb not found; YACCC_TEST_PG names one)'
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        return None, 'PostgreSQL will not start as root (YACCC_TEST_PG names a server)'
    if not have_lib(['libpq.so.5', 'libpq.so', 'libpq.5.dylib', 'libpq.dylib']):
        return None, 'libpq not found'
    bindir = os.path.dirname(initdb)
    data = os.path.join(work, 'pgdata')
    user = 'yaccc'
    r = subprocess.run([initdb, '-D', data, '-A', 'trust', '-U', user, '--no-sync'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, 'initdb failed: ' + r.stderr.strip()[-200:]
    port = free_port()
    r = subprocess.run([os.path.join(bindir, 'pg_ctl'), '-D', data, '-w', '-l',
                        os.path.join(work, 'pg.log'), '-o',
                        f"-k {work} -p {port} -c listen_addresses='' -c fsync=off", 'start'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, 'the server did not start: ' + r.stderr.strip()[-200:]

    def stop():
        subprocess.run([os.path.join(bindir, 'pg_ctl'), '-D', data, '-m', 'immediate', 'stop'],
                       capture_output=True)
    start_postgres.stop = stop
    return f"host={work} port={port} dbname=postgres user={user}", None


def run_case(name, exe, target, work):
    """The program's output, with the exit status of each run."""
    env = dict(os.environ)
    env.pop('COB_SQL_TRACE', None)
    env['SQLTEST_DB'] = target
    env['COB_SQL_DATABASE'] = target
    out = b''
    for args in ([[a] for a in RUNS[name]] if name in RUNS else [[]]):
        r = subprocess.run([exe] + args, cwd=work, env=env, capture_output=True, timeout=120)
        out += r.stdout
        if name in RUNS:
            out += f"exit {r.returncode}\n".encode()
        elif r.returncode != 0:
            out += f"exit {r.returncode}\n".encode() + r.stderr[-500:]
    return out


def main():
    work = tempfile.mkdtemp(prefix='sqltest_')
    passed = failed = 0
    try:
        cases = sorted(os.path.splitext(f)[0] for f in os.listdir(CASES) if f.endswith('.cbl'))
        exes = {}
        for name in cases:
            exe = os.path.join(work, name)
            r = subprocess.run([YACCC, os.path.join(CASES, name + '.cbl'), '-o', exe],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL {name}: compile error\n{r.stderr}")
                failed += 1
                continue
            exes[name] = exe
        backends = []
        if have_lib(['libsqlite3.so.0', 'libsqlite3.so', 'libsqlite3.dylib']):
            backends.append(('SQLite', lambda name: os.path.join(work, name + '.db')))
        else:
            print("SKIP SQLite: libsqlite3 not found")
        pg, why = start_postgres(work)
        if pg:
            backends.append(('PostgreSQL', lambda name: pg))
        else:
            print(f"SKIP PostgreSQL: {why}")
        for db, target in backends:
            for name, exe in exes.items():
                want = open(os.path.join(CASES, name + '.expected'), 'rb').read()
                got = run_case(name, exe, target(name), work)
                if got == want:
                    passed += 1
                    continue
                failed += 1
                print(f"FAIL {name} on {db}")
                import difflib
                for line in difflib.unified_diff(want.decode('latin-1').splitlines(),
                                                 got.decode('latin-1').splitlines(),
                                                 'expected', db, lineterm='', n=1):
                    print('   ' + line)
    finally:
        stop = getattr(start_postgres, 'stop', None)
        if stop:
            stop()
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
