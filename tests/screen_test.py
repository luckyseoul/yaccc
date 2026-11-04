#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Screen tests: SCREEN SECTION, DISPLAY / ACCEPT ... AT, function keys.

Each tests/screen/NAME.cbl is compiled with yaccc and run in a pseudo-terminal
of 24 lines by 80 columns. The keys in NAME.keys are typed one by one (one
per line; \\r Enter, \\t Tab, \\x1b Escape, \\x1bOP F1 and so on, with
Python's string escapes; a line "#sleep N" waits N seconds instead),
NAME.env (optional) adds environment variables, and the screen the program
leaves behind is compared with NAME.screen: the text of each line, then one
'@' line per run of characters with attributes:

    @ 3 10-19 underline fg=2

The screen is read by a small terminal emulator below, which understands the
escape sequences the runtime writes (cursor addressing, erase in line and in
display, SGR), so the tests need nothing outside the standard library.

usage: screen_test.py [-v] [--update] [names...]
"""
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
YACCC = os.path.join(ROOT, 'yaccc')
CASES = os.path.join(HERE, 'screen')
ROWS, COLS = 24, 80


class Term:
    """A screen of ROWS x COLS cells: (character, attributes)."""

    def __init__(self, rows=ROWS, cols=COLS):
        self.rows, self.cols = rows, cols
        self.cells = [[(' ', ()) for _ in range(cols)] for _ in range(rows)]
        self.y = self.x = 0
        self.attr = {}

    def put(self, ch):
        if self.x >= self.cols:
            self.x = self.cols - 1
        self.cells[self.y][self.x] = (ch, tuple(sorted(self.attr.items())))
        self.x += 1

    def scroll(self):
        self.cells.pop(0)
        self.cells.append([(' ', ()) for _ in range(self.cols)])

    def clear(self, y, x0, x1):
        bg = self.attr.get('bg')
        a = (('bg', bg),) if bg is not None else ()
        for x in range(max(x0, 0), min(x1, self.cols)):
            self.cells[y][x] = (' ', a)

    def sgr(self, params):
        if not params:
            params = [0]
        for p in params:
            if p == 0:
                self.attr = {}
            elif p == 1:
                self.attr['bold'] = 1
            elif p == 2:
                self.attr['dim'] = 1
            elif p == 4:
                self.attr['underline'] = 1
            elif p == 5:
                self.attr['blink'] = 1
            elif p == 7:
                self.attr['reverse'] = 1
            elif p == 53:
                self.attr['overline'] = 1
            elif p == 55:
                self.attr.pop('overline', None)
            elif p == 22:
                self.attr.pop('bold', None)
                self.attr.pop('dim', None)
            elif p == 24:
                self.attr.pop('underline', None)
            elif p == 27:
                self.attr.pop('reverse', None)
            elif 30 <= p <= 37:
                self.attr['fg'] = p - 30
            elif 90 <= p <= 97:
                self.attr['fg'] = p - 90 + 8
            elif p == 39:
                self.attr.pop('fg', None)
            elif 40 <= p <= 47:
                self.attr['bg'] = p - 40
            elif 100 <= p <= 107:
                self.attr['bg'] = p - 100 + 8
            elif p == 49:
                self.attr.pop('bg', None)

    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            c = data[i]
            i += 1
            if c == 0x1b:
                if i < n and data[i] == ord('['):
                    j = i + 1
                    while j < n and not (0x40 <= data[j] <= 0x7e):
                        j += 1
                    if j >= n:
                        break
                    body = data[i + 1:j].decode('latin-1')
                    final = chr(data[j])
                    i = j + 1
                    self.csi(body, final)
                elif i < n and data[i] in (ord('('), ord(')')):
                    i += 2
                else:
                    i += 1
            elif c == 13:
                self.x = 0
            elif c == 10:
                if self.y == self.rows - 1:
                    self.scroll()
                else:
                    self.y += 1
            elif c == 8:
                self.x = max(0, self.x - 1)
            elif c == 9:
                self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
            elif c == 7:
                pass
            elif c >= 32:
                self.put(chr(c))

    def csi(self, body, final):
        if body.startswith('?'):
            return
        nums = [int(p) if p.isdigit() else 0 for p in body.split(';')] if body else []
        a = nums[0] if nums else 0
        if final in 'Hf':
            self.y = min(max((nums[0] if nums and nums[0] else 1) - 1, 0), self.rows - 1)
            self.x = min(max((nums[1] if len(nums) > 1 and nums[1] else 1) - 1, 0), self.cols - 1)
        elif final == 'J':
            if a == 2:
                for y in range(self.rows):
                    self.clear(y, 0, self.cols)
            elif a == 0:
                self.clear(self.y, self.x, self.cols)
                for y in range(self.y + 1, self.rows):
                    self.clear(y, 0, self.cols)
        elif final == 'K':
            if a == 0:
                self.clear(self.y, self.x, self.cols)
            elif a == 1:
                self.clear(self.y, 0, self.x + 1)
            else:
                self.clear(self.y, 0, self.cols)
        elif final == 'm':
            self.sgr(nums)
        elif final == 'A':
            self.y = max(0, self.y - (a or 1))
        elif final == 'B':
            self.y = min(self.rows - 1, self.y + (a or 1))
        elif final == 'C':
            self.x = min(self.cols - 1, self.x + (a or 1))
        elif final == 'D':
            self.x = max(0, self.x - (a or 1))
        elif final == 'G':
            self.x = min(max((a or 1) - 1, 0), self.cols - 1)
        elif final == 'd':
            self.y = min(max((a or 1) - 1, 0), self.rows - 1)

    def dump(self):
        """The screen's text, then its attribute runs."""
        lines = [''.join(c for c, _ in row).rstrip() for row in self.cells]
        while lines and not lines[-1]:
            lines.pop()
        out = list(lines)
        for y, row in enumerate(self.cells):
            x = 0
            while x < self.cols:
                a = row[x][1]
                if not a:
                    x += 1
                    continue
                x0 = x
                while x < self.cols and row[x][1] == a:
                    x += 1
                desc = ' '.join(k if v == 1 and k not in ('fg', 'bg') else f"{k}={v}" for k, v in a)
                out.append(f"@ {y + 1} {x0 + 1}-{x} {desc}")
        return '\n'.join(out) + '\n'


def run_pty(argv, keys, env=None, cwd=None, delay=0.1, timeout=10.0):
    """Run argv in a pseudo-terminal, typing keys; the bytes it wrote and its status."""
    pid, fd = pty.fork()
    if pid == 0:
        e = dict(os.environ, TERM='xterm', LINES=str(ROWS), COLUMNS=str(COLS))
        e.update(env or {})
        if cwd:
            os.chdir(cwd)
        os.execvpe(argv[0], argv, e)
    import fcntl
    import termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
    out = bytearray()

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.02)
            if r:
                try:
                    d = os.read(fd, 65536)
                except OSError:
                    return False
                if not d:
                    return False
                out.extend(d)
        return True
    pump(delay * 3)
    for k in keys:
        if isinstance(k, float):
            pump(k)
            continue
        os.write(fd, k.encode('latin-1'))
        pump(delay)
    status = None
    end = time.time() + timeout
    while time.time() < end:
        alive = pump(0.05)
        wp, st = os.waitpid(pid, os.WNOHANG)
        if wp:
            pump(0.05)
            status = os.waitstatus_to_exitcode(st)
            break
        if not alive:
            _, st = os.waitpid(pid, 0)
            status = os.waitstatus_to_exitcode(st)
            break
    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        status = 'timeout'
    os.close(fd)
    return bytes(out), status


def read_keys(path):
    if not os.path.exists(path):
        return []
    keys = []
    with open(path, encoding='latin-1') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('#sleep '):
                keys.append(float(line.split()[1]))
            elif line:
                keys.append(line.encode('latin-1').decode('unicode_escape'))
    return keys


def read_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding='latin-1'):
            if '=' in line:
                k, v = line.strip().split('=', 1)
                env[k] = v
    return env


def main():
    args = sys.argv[1:]
    verbose = '-v' in args
    update = '--update' in args
    names = [a for a in args if not a.startswith('-')]
    if not names:
        names = sorted(f[:-4] for f in os.listdir(CASES) if f.endswith('.cbl'))
    work = tempfile.mkdtemp(prefix='yaccscr_')
    passed = failed = 0
    for name in names:
        src = os.path.join(CASES, name + '.cbl')
        exe = os.path.join(work, name)
        r = subprocess.run([YACCC, src, '-o', exe], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL {name}: compile error\n{r.stderr}")
            failed += 1
            continue
        raw, status = run_pty([exe], read_keys(os.path.join(CASES, name + '.keys')),
                              read_env(os.path.join(CASES, name + '.env')), cwd=work)
        term = Term()
        term.feed(raw)
        got = term.dump() + f"exit {status}\n"
        want_path = os.path.join(CASES, name + '.screen')
        if update and not os.path.exists(want_path):
            with open(want_path, 'w', encoding='latin-1') as f:
                f.write(got)
        want = open(want_path, encoding='latin-1').read() if os.path.exists(want_path) else None
        if got == want:
            passed += 1
            if verbose:
                print(f"ok   {name}")
        else:
            failed += 1
            print(f"FAIL {name}")
            import difflib
            for line in difflib.unified_diff((want or '').splitlines(), got.splitlines(),
                                             'expected', 'got', lineterm='', n=1):
                print('     ' + line)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
