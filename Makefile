# SPDX-License-Identifier: MIT
# YACCC - convenience targets. The compiler itself needs no build step:
# ./yaccc builds the runtime library (runtime/libcobrt.a) on first use.

PYTHON ?= python3
# NIST CCVS85 suite as split into modules by opensource COBOL (see README)
SUITE  ?= third_party/opensourcecobol4j/tests/cobol85
# GnuCOBOL 3.1.2 testsuite sources (autotest .at files)
GCSUITE ?= third_party/gnucobol/tests/testsuite.src
GCTAG   ?= gnucobol-3.1.2
GNUSRC  ?= third_party/gnucobol
OUT    ?= build/examples

# make install: the compiler and its runtime under $(PREFIX)/lib/yaccc, and the
# command as $(PREFIX)/bin/yaccc. PREFIX=$$HOME/.local installs for one user.
PREFIX ?= /usr/local
DESTDIR ?=
INSTDIR = $(DESTDIR)$(PREFIX)/lib/yaccc
BINDIR  = $(DESTDIR)$(PREFIX)/bin

.PHONY: all runtime test cli-test screen-test files-test sql-test provenance provenance-deep test-ref nist nist-all gctest gctest-update three-way examples install uninstall clean

all: runtime

runtime:
	./yaccc --build-runtime

# regression tests against the recorded GnuCOBOL baselines
test: runtime
	$(PYTHON) tests/difftest.py

# the compiler's own command line: options honoured, mistakes reported
cli-test: runtime
	$(PYTHON) tests/cli_test.py

# SCREEN SECTION and DISPLAY / ACCEPT ... AT, run in a pseudo-terminal
screen-test: runtime
	$(PYTHON) tests/screen_test.py

# files shared between programs and processes: sharing, record locks, journal
files-test: runtime
	$(PYTHON) tests/files_test.py

# embedded SQL, against SQLite and against PostgreSQL (a server it starts,
# or the one YACCC_TEST_PG names)
sql-test: runtime
	$(PYTHON) tests/sql_test.py

# this tree stays MIT: no GPL code, no vendored third-party suite
provenance:
	$(PYTHON) tests/provenance_test.py

# the same, plus token overlap against GnuCOBOL's own C: catches a translation
# that renamed every identifier. Needs the libcob sources (fetched by $(GCSUITE))
provenance-deep:
	$(PYTHON) tests/provenance_test.py --gnucobol $(GNUSRC)

# the same programs through YACCC and two independent compilers, to tell a
# matched standard from a matched GnuCOBOL quirk (needs cobc and gcobol on PATH;
# see docs/three-way.md). A survey, not a gate: it never fails the build.
three-way: runtime
	$(PYTHON) tests/three_way.py

# the same tests compared live against GnuCOBOL (needs cobc on PATH)
test-ref: runtime
	$(PYTHON) tests/difftest.py --ref

$(SUITE):
	git clone --depth 1 --filter=blob:none --sparse \
	    https://github.com/opensourcecobol/opensourcecobol4j.git third_party/opensourcecobol4j
	git -C third_party/opensourcecobol4j sparse-checkout set tests/cobol85

# NIST CCVS85: the reference summary.txt program set, plus Report Writer and Debug
nist: runtime $(SUITE)
	$(PYTHON) tests/nist/run_nist.py $(SUITE)

# NIST CCVS85 including the programs the reference summary skips
nist-all: runtime $(SUITE)
	$(PYTHON) tests/nist/run_nist.py --all $(SUITE)

$(GCSUITE):
	git clone --depth 1 --filter=blob:none --sparse --branch $(GCTAG) \
	    https://github.com/OCamlPro/gnucobol.git third_party/gnucobol
	git -C third_party/gnucobol sparse-checkout set tests/testsuite.src libcob cobc

# GnuCOBOL's own runtime tests; fails if a test recorded as passing no longer passes
gctest: runtime $(GCSUITE)
	$(PYTHON) tests/gnucobol/run_gc.py --expect tests/gnucobol/results.txt $(GCSUITE)

# rerun them and record the results as the new expectation
gctest-update: runtime $(GCSUITE)
	$(PYTHON) tests/gnucobol/run_gc.py -v $(GCSUITE) > tests/gnucobol/results.txt.new
	mv tests/gnucobol/results.txt.new tests/gnucobol/results.txt

# build and run the example programs in $(OUT)
examples: runtime
	mkdir -p $(OUT)
	cp examples/*.dat examples/*.txt $(OUT)/
	./yaccc examples/payroll.cbl    -o $(OUT)/payroll
	./yaccc examples/bank.cbl       -o $(OUT)/bank
	./yaccc examples/wordfreq.cbl   -o $(OUT)/wordfreq
	./yaccc examples/mandelbrot.cbl -o $(OUT)/mandelbrot
	./yaccc examples/dayname.cbl examples/datefmt.cbl -o $(OUT)/dayname
	cd $(OUT) && ./payroll && cat payroll.rpt
	cd $(OUT) && ./bank
	cd $(OUT) && ./wordfreq
	cd $(OUT) && ./mandelbrot
	cd $(OUT) && ./dayname

install: runtime
	mkdir -p $(INSTDIR)/lib/yaccc $(INSTDIR)/runtime $(BINDIR)
	install -m 644 lib/yaccc/*.py $(INSTDIR)/lib/yaccc/
	install -m 644 runtime/*.c runtime/*.h $(INSTDIR)/runtime/
	# the library last, so that it is newer than the sources it was built from
	install -m 644 runtime/libcobrt.a $(INSTDIR)/runtime/
	install -m 755 yaccc $(INSTDIR)/yaccc
	ln -sf $(PREFIX)/lib/yaccc/yaccc $(BINDIR)/yaccc
	@echo "installed: $(BINDIR)/yaccc"

uninstall:
	rm -f $(BINDIR)/yaccc
	rm -rf $(INSTDIR)

clean:
	rm -rf build runtime/*.o runtime/libcobrt.a runtime/yacccrun
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
