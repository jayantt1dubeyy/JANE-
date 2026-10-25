#!/usr/bin/env python3
"""Driver: extract a GDS netlist, derive pad directions from the cell
models, and emit the Verilog netlist + JSON description."""
import sys, os, json
sys.path.insert(0, "/home/hatch/workspace/.pydeps")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import extract, emit_verilog
from cells import load_all_models

gds_path, module_name, out_prefix = sys.argv[1:4]
dump = sys.argv[4] if len(sys.argv) > 4 else None
data = extract(gds_path, module_name, dump_nodes_path=dump)

models = load_all_models([inst["cell"] for inst in data["instances"]])
# A pad net is an output if any connected instance pin is a cell output.
out_pins = {}   # net -> True if driven by a cell output
in_pins = {}    # net -> True if feeding a cell input
for inst in data["instances"]:
    m = models[inst["cell"]]
    outs = set(m["outputs"])
    for pin, net in inst["pins"].items():
        if pin in outs:
            out_pins[net] = True
        else:
            in_pins[net] = True
port_dirs = {}
for pad, net in data["pads"].items():
    base = pad.split("[")[0]
    if net in out_pins:
        port_dirs[base] = "output"
    elif net in in_pins:
        port_dirs[base] = "input"
    else:
        port_dirs[base] = "input"  # unconnected pad; flagged in warnings
        print("WARN: pad %s (net %d) connects to no cell pin" % (pad, net))
print("port directions:", port_dirs)

with open(out_prefix + ".json", "w") as f:
    json.dump(data, f)
emit_verilog(data, out_prefix + ".v", port_dirs)
# instances missing pins vs model (e.g. power pins are expected to be absent)
missing = []
for inst in data["instances"]:
    m = models[inst["cell"]]
    expected = set(m["inputs"]) | set(m["outputs"])
    got = set(inst["pins"])
    miss = expected - got
    extra = got - expected
    if miss - {"VPWR", "VGND", "VPB", "VNB"}:
        missing.append((inst["cell"], sorted(miss)))
    if extra:
        missing.append((inst["cell"], "extra pins: %s" % sorted(extra)))
print("pin/model mismatches (excluding power pins):", missing[:10],
      "count:", len(missing))
