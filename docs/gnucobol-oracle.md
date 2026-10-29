# Building a GnuCOBOL oracle

`make test-ref` compiles each differential test with a real `cobc` and compares
the two programs' output, instead of comparing against the recorded `.expected`
files. It needs `cobc` on `PATH`; this note records how to get one without
root and without a package manager.

GnuCOBOL 3.1.2 is the version the recorded baselines came from, so use that
tag. The git tag does not carry generated parser sources (`ppparse.c`,
`pplex.c`) and there is no bison/flex on this machine; the release tarball
does, so take the tarball:

```sh
curl -sSLo gc.tar.xz \
  https://downloads.sourceforge.net/project/gnucobol/gnucobol/3.1/gnucobol-3.1.2.tar.xz
tar xf gc.tar.xz && cd gnucobol-3.1.2
./configure --prefix=/tmp/gcinst --without-ncurses --without-db \
    CFLAGS="-O2 -std=gnu89 -Wno-incompatible-pointer-types -Wno-error"
make -j"$(nproc)" && make install
```

Three flags matter:

- `--without-db` — `db.h` (Berkeley DB) is not installed, and configure stops
  without this.
- `-std=gnu89` and `-Wno-incompatible-pointer-types` — 3.1.2 predates the
  C23/GCC-14 rule that makes its `funcint` dispatch table an error rather than
  a warning.
- `--without-ncurses` — not required, but skips a dependency the scanner does
  not need.

Then:

```sh
export PATH=/tmp/gcinst/bin:$PATH LD_LIBRARY_PATH=/tmp/gcinst/lib
cd <yaccc checkout> && make test-ref
```

Built this way, GnuCOBOL 3.1.2 agrees with yaccc on 57 of the 62 differential
tests. The other five are skipped because `cobc` rejects the *test program*
(for example a `[` inside a `DISPLAY` literal), not because the outputs differ.

## What the oracle is good for

- `make test-ref`: validating the recorded baselines are genuine GnuCOBOL
  output rather than something yaccc produced.
- Settling questions about behaviour that the expected-output files cannot,
  since they only show the final text.

It did **not** settle the Report Writer page geometry. Making a page span
`PAGE LIMIT - 1` lines makes the first two pages of `Report Line Order` match
`cobc` exactly, but turns the rest of that cluster from 8 passes to 1 and
breaks five differential baselines, so page length evidently depends on more
than `PAGE LIMIT`. See `report-writer-page-model.md`.
