# cobolc - convenience targets. The compiler itself needs no build step:
# ./cobolc builds the runtime library (runtime/libcobrt.a) on first use.

PYTHON ?= python3
# NIST CCVS85 suite as split into modules by opensource COBOL (see README)
SUITE  ?= third_party/opensourcecobol4j/tests/cobol85
OUT    ?= build/examples

.PHONY: all runtime test test-ref nist nist-all examples clean

all: runtime

runtime:
	./cobolc --build-runtime

# regression tests against the recorded GnuCOBOL baselines
test: runtime
	$(PYTHON) tests/difftest.py

# the same tests compared live against GnuCOBOL (needs cobc on PATH)
test-ref: runtime
	$(PYTHON) tests/difftest.py --ref

$(SUITE):
	git clone --depth 1 --filter=blob:none --sparse \
	    https://github.com/opensourcecobol/opensourcecobol4j.git third_party/opensourcecobol4j
	git -C third_party/opensourcecobol4j sparse-checkout set tests/cobol85

# NIST CCVS85: same program set as the suite's reference summary.txt
nist: runtime $(SUITE)
	$(PYTHON) tests/nist/run_nist.py $(SUITE)

# NIST CCVS85 including the programs the reference summary skips
nist-all: runtime $(SUITE)
	$(PYTHON) tests/nist/run_nist.py --all $(SUITE)

# build and run the example programs in $(OUT)
examples: runtime
	mkdir -p $(OUT)
	cp examples/*.dat examples/*.txt $(OUT)/
	./cobolc examples/payroll.cbl    -o $(OUT)/payroll
	./cobolc examples/bank.cbl       -o $(OUT)/bank
	./cobolc examples/wordfreq.cbl   -o $(OUT)/wordfreq
	./cobolc examples/mandelbrot.cbl -o $(OUT)/mandelbrot
	./cobolc examples/dayname.cbl examples/datefmt.cbl -o $(OUT)/dayname
	cd $(OUT) && ./payroll && cat payroll.rpt
	cd $(OUT) && ./bank
	cd $(OUT) && ./wordfreq
	cd $(OUT) && ./mandelbrot
	cd $(OUT) && ./dayname

clean:
	rm -rf build runtime/*.o runtime/libcobrt.a
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
