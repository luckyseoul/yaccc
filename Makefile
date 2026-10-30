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

.PHONY: all runtime test cli-test provenance provenance-deep test-ref nist nist-all gctest gctest-update examples clean

all: runtime

runtime:
	./yaccc --build-runtime

# regression tests against the recorded GnuCOBOL baselines
test: runtime
	$(PYTHON) tests/difftest.py

# the compiler's own command line: options honoured, mistakes reported
cli-test: runtime
	$(PYTHON) tests/cli_test.py

# this tree stays MIT: no GPL code, no vendored third-party suite
provenance:
	$(PYTHON) tests/provenance_test.py

# the same, plus token overlap against GnuCOBOL's own C: catches a translation
# that renamed every identifier. Needs the libcob sources (fetched by $(GCSUITE))
provenance-deep:
	$(PYTHON) tests/provenance_test.py --gnucobol $(GNUSRC)

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
	git -C third_party/gnucobol sparse-checkout set tests/testsuite.src libcob

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

clean:
	rm -rf build runtime/*.o runtime/libcobrt.a
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
