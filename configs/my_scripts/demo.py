import math
import argparse

import m5
from m5.objects import *
from m5.util import addToPath

addToPath("../")

from common import (
    MemConfig,
    ObjectList,
)

############################ System & Memory Setup ############################
mem_range = AddrRange("256MiB")

system = System(
    membus=IOXBar(width=32),
    clk_domain=SrcClockDomain(clock="2.0GHz", voltage_domain=VoltageDomain()),
    mem_ranges = [mem_range],
    mmap_using_noreserve = True
)

opts = argparse.Namespace(
    mem_type="DDR3_1600_8x8",
    mem_ranks=1,
    addr_mapping="RoRaBaCoCh",
    mem_channels=1,
    external_memory_system=0,
    tlm_memory=0,
    elastic_trace_en=0,
)

MemConfig.config_mem(opts, system)


system.mem_ctrls[0].dram.null = True
system.mem_ctrls[0].dram.addr_mapping = opts.addr_mapping



########################### Traffic Generator Setup ###########################
system.tgen = PyTrafficGen()



################################ Monitor Setup ################################
system.monitor = CommMonitor()
system.monitor.trace = MemTraceProbe(trace_file="monitor.ptrc.gz")
# system.monitor.stackdist = StackDistProbe(verify=True)



########################## Connecting the Components ##########################
system.monitor.cpu_side_port = system.tgen.port
system.monitor.mem_side_port = system.membus.cpu_side_ports



################### Calculating Parameters for the Tracegen ###################
duration = 10000000000
read_percent = 50

nbr_of_banks = system.mem_ctrls[0].dram.banks_per_rank.value

burst_size = (system.mem_ctrls[0].dram.devices_per_rank.value
              * system.mem_ctrls[0].dram.device_bus_width.value
              * system.mem_ctrls[0].dram.burst_length.value) / 8
blocksize = int(burst_size)

page_size = system.mem_ctrls[0].dram.devices_per_rank.value \
            * system.mem_ctrls[0].dram.device_rowbuffer_size.value

# inter-transaction time
# match the maximum bandwidth of the memory, the parameter is in seconds
# and we need it in ticks (ps)
itt = getattr(system.mem_ctrls[0].dram.tBURST_MIN, "value",
              system.mem_ctrls[0].dram.tBURST.value) * 1000000000000


bank = 4

stride_size = 4096

num_seq_pkts = int(math.ceil(float(stride_size) / burst_size))

max_seq_count_per_rank = (bank*2 if (read_percent==50) else bank)

addr_map = ObjectList.dram_addr_map_list.get(opts.addr_mapping)

# duration          duration of this state before transitioning
# start_addr        Start address
# end_addr          End address
# blocksize         Size used for transactions injected
# min_period        Lower limit of random inter-transaction time
# max_period        Upper limit of random inter-transaction time
# read_percent      Percent of transactions that are reads
# data_limit        Upper limit on how much data to read/write
# num_seq_pkts      Number of packets per stride, each of _blocksize
# page_size         Page size (bytes) used in the DRAM
# nbr_of_banks_DRAM Total number of banks in DRAM
# nbr_of_banks_util Number of banks to utilized,
#                   for N banks, we will use banks: 0->(N-1)
# nbr_of_ranks      Number of ranks utilized,
# addr_mapping      Address mapping to be used, assumes single channel system
def trace():
    yield system.tgen.createDramRot(
        duration,
        mem_range.start, mem_range.end,
        blocksize,
        int(itt), int(itt),
        read_percent,
        0,
        num_seq_pkts,
        page_size,
        nbr_of_banks,
        bank,
        addr_map,
        opts.mem_ranks,
        max_seq_count_per_rank
    )
    yield system.tgen.createExit(0)



############################### Running the Simulation ##########################
root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"
m5.instantiate()
system.tgen.start(trace())
m5.simulate()
