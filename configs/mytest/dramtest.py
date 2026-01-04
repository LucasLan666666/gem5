import subprocess
import os
import argparse
import math

import m5
from m5.objects import *
from m5.stats import periodicStatDump
from m5.util import addToPath

addToPath("../")

from common import (
    MemConfig,
    ObjectList,
)

# this script is helpful to sweep the efficiency of a specific memory
# controller configuration, by varying the number of banks accessed,
# and the sequential stride size (how many bytes per activate), and
# observe what bus utilisation (bandwidth) is achieved

parser = argparse.ArgumentParser()

dram_generators = {
    "DRAM": lambda x: x.createDram,
    "DRAM_ROTATE": lambda x: x.createDramRot,
}

# Use a single-channel DDR3-1600 x64 (8x8 topology) by default
parser.add_argument(
    "--mem-type",
    default="DDR3_1600_8x8",
    choices=ObjectList.mem_list.get_names(),
    help="type of memory to use",
)

parser.add_argument(
    "--mem-ranks",
    "-r",
    type=int,
    default=1,
    help="Number of ranks to iterate across",
)

parser.add_argument(
    "--rd_perc", type=int, default=50, help="Percentage of read commands"
)

parser.add_argument(
    "--mode",
    default="DRAM_ROTATE",
    choices=list(dram_generators.keys()),
    help="DRAM: Random traffic; \
                          DRAM_ROTATE: Traffic rotating across banks and ranks",
)

parser.add_argument(
    "--addr-map",
    choices=ObjectList.dram_addr_map_list.get_names(),
    default="RoRaBaCoCh",
    help="DRAM address map policy",
)

args = parser.parse_args()

# at the moment we stay with the default open-adaptive page policy,
# and address mapping

# start with the system itself, using a multi-layer 2.0 GHz
# crossbar, delivering 64 bytes / 3 cycles (one header cycle)
# which amounts to 42.7 GByte/s per layer and thus per port
system = System(membus=IOXBar(width=32))
system.clk_domain = SrcClockDomain(
    clock="2.0GHz", voltage_domain=VoltageDomain(voltage="1V")
)

# we are fine with 256 MiB memory for now
mem_range = AddrRange("256MiB")
system.mem_ranges = [mem_range]

# do not worry about reserving space for the backing store
system.mmap_using_noreserve = True

# force a single channel to match the assumptions in the DRAM traffic
# generator
args.mem_channels = 1
args.external_memory_system = 0
args.tlm_memory = 0
args.elastic_trace_en = 0
MemConfig.config_mem(args, system)

# the following assumes that we are using the native DRAM
# controller, check to be sure
if not isinstance(system.mem_ctrls[0], m5.objects.MemCtrl):
    fatal("This script assumes the controller is a MemCtrl subclass")
if not isinstance(system.mem_ctrls[0].dram, m5.objects.DRAMInterface):
    fatal("This script assumes the memory is a DRAMInterface subclass")

# there is no point slowing things down by saving any data
system.mem_ctrls[0].dram.null = True

# Set the address mapping based on input argument
system.mem_ctrls[0].dram.addr_mapping = args.addr_map

# stay in each state for 0.25 ms, long enough to warm things up, and
# short enough to avoid hitting a refresh
period = 25000000

# stay in each state as long as the dump/reset period, use the entire
# range, issue transactions of the right DRAM burst size, and match
# the DRAM maximum bandwidth to ensure that it is saturated

# get the number of banks
nbr_banks = system.mem_ctrls[0].dram.banks_per_rank.value

# determine the burst length in bytes
burst_size = int(
    (
        system.mem_ctrls[0].dram.devices_per_rank.value
        * system.mem_ctrls[0].dram.device_bus_width.value
        * system.mem_ctrls[0].dram.burst_length.value
    )
    / 8
)

# next, get the page size in bytes
page_size = (
    system.mem_ctrls[0].dram.devices_per_rank.value
    * system.mem_ctrls[0].dram.device_rowbuffer_size.value
)

# match the maximum bandwidth of the memory, the parameter is in seconds
# and we need it in ticks (ps)
itt = (
    getattr(
        system.mem_ctrls[0].dram.tBURST_MIN,
        "value",
        system.mem_ctrls[0].dram.tBURST.value,
    )
    * 1000000000000
)

# assume we start at 0
max_addr = mem_range.end

# use min of the page size and 512 bytes as that should be more than
# enough
max_stride = min(512, page_size)

# create a traffic generator, and point it to the file we just created
system.tgen = PyTrafficGen()

# add a communication monitor
system.monitor = CommMonitor()
system.monitor.trace = MemTraceProbe(trace_file="monitor.ptrc")
system.monitor.stackdist = StackDistProbe(verify=True)

# connect the traffic generator to the bus via a communication monitor
system.tgen.port = system.monitor.cpu_side_port
system.monitor.mem_side_port = system.membus.cpu_side_ports

# connect the system port even if it is not used in this example
system.system_port = system.membus.cpu_side_ports

# every period, dump and reset all stats
periodicStatDump(period)

# run Forrest, run!
root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"

m5.instantiate()

# My settings to run a single trace
stride_size = 13  # example stride size
bank = 4           # example bank count
num_seq_pkts = int(math.ceil(float(stride_size) / burst_size))
max_seq_count_per_rank = (bank*2 if (args.rd_perc==50) else bank)
def trace():
    addr_map = ObjectList.dram_addr_map_list.get(args.addr_map)
    generator = dram_generators[args.mode](system.tgen)
    if (args.mode == "DRAM_ROTATE"):
        yield generator(period, 0, max_addr, burst_size, int(itt),
                        int(itt), args.rd_perc, 0, num_seq_pkts,
                        page_size, nbr_banks, bank, addr_map,
                        args.mem_ranks, max_seq_count_per_rank)
    else:
        yield generator(period, 0, max_addr, burst_size, int(itt),
                        int(itt), args.rd_perc, 0, num_seq_pkts,
                        page_size, nbr_banks, bank, addr_map,
                        args.mem_ranks)
    yield system.tgen.createExit(0)


system.tgen.start(trace())

m5.simulate()

# Dump configuration
# Helper to print a key-value pair
def line(k, v):
    print(f"{k:<26}: {v}")
# Helper to format bytes nicely
def _fmt_bytes(x):
    units = [("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)]
    for name, base in units:
        if x >= base: return f"{x/base:.2f} {name}"
    return f"{x} B"
print()
print("========================== memtest_config ==========================")
print("[DRAM setup]")
line("mem_type", repr(args.mem_type))
line("addr_map", repr(args.addr_map))
line("mode", f"{repr(args.mode)}, rd_perc={args.rd_perc}%")
line("mem_ranks", args.mem_ranks)
line("banks_per_rank", nbr_banks)

print("[Geometry & timing]")
line("burst_size_bytes", burst_size)
line("page_size_bytes", page_size)
line("max_stride_bytes", max_stride)
line("period_ticks", period)
line("itt_ticks", int(itt))
line("mem_range", f"{mem_range.start}:{mem_range.end} "
                    f"({_fmt_bytes(mem_range.size())})")

print("[Trace]")
line("stride_size", stride_size)
line("bank", bank)
line("num_seq_pkts", num_seq_pkts)
if args.mode == "DRAM_ROTATE":
    line("max_seq_count_per_rank", max_seq_count_per_rank)
print("====================================================================")
