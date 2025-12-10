GEM5_BIN    ?= build/ALL/gem5.opt
SCRIPT      ?= configs/mytest/simple.py
OUTDIR      ?= m5out
DEBUG_FLAGS ?= DRAMsim3
DEBUG_FILE  ?= debug.txt
# STDOUT_FILE ?= simout.txt
# STDERR_FILE ?= simerr.txt
ARGS        ?=


DEBUG_OPTS :=
ifdef DEBUG_FLAGS
    DEBUG_OPTS += --debug-flags=$(DEBUG_FLAGS)
endif
ifdef DEBUG_FILE
    DEBUG_OPTS += --debug-file=$(DEBUG_FILE)
endif

STD_OPTS :=
ifdef STDOUT_FILE
    STD_OPTS += --stdout-file=$(STDOUT_FILE) -r
endif
ifdef STDERR_FILE
    STD_OPTS += --stderr-file=$(STDERR_FILE) -e
endif

.PHONY: run clean
run: clean
	$(GEM5_BIN) \
		--outdir=$(OUTDIR) \
		$(DEBUG_OPTS) \
		$(STD_OPTS) \
		$(SCRIPT) \
		$(ARGS)

clean:
	rm -rf $(OUTDIR)
