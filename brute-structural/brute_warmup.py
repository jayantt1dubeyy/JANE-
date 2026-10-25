"""Method (a) on the warmup: brute-force search over A,B.

Protocol (from 00_source.v): rst_n low resets both 8-bit shift registers;
with en high, each clock shifts one serial bit into each register, MSB first
(first bit shifted in ends up at bit 7 after 8 shifts). S is combinational:
S == 1 iff a_reg + b_reg == 496 (to be recovered, not assumed).
"""
import sys, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from fastsim import FastSim as Sim

WARMUP = "/home/hatch/workspace/asic-puzzle-2026/warmup/01_netlist.v"

def load_value(sim, aval, bval):
    """Reset, then shift 8 bits of A and B in, MSB first, with en=1."""
    sim.reset(cycles=2)
    for i in range(7, -1, -1):
        sim.cycle(rst_n=1, en=1, A=(aval >> i) & 1, B=(bval >> i) & 1)
    sim.set_inputs(rst_n=1, en=0, A=0, B=0)

def main():
    nl = parse_netlist(WARMUP)
    print("inputs:", nl["inputs"], "outputs:", nl["outputs"])
    print("logic instances:", len(nl["instances"]))
    sim = Sim(nl)
    # sanity: empty registers -> S should be 0 (0+0 != 496)
    sim.reset(cycles=2)
    print("after reset: S =", sim.read("S"))
    t0 = time.time()
    hits = []
    for aval in range(256):
        for bval in range(256):
            load_value(sim, aval, bval)
            if sim.read("S") == 1:
                hits.append((aval, bval))
    dt = time.time() - t0
    print(f"brute force over 65536 (A,B) pairs took {dt:.1f}s")
    print("success pairs found:", len(hits))
    print("pairs:", hits)
    ok = all(a + b == 496 for a, b in hits)
    complete = set(hits) == {(a, 496 - a) for a in range(241, 256)}
    print("every hit satisfies A+B==496:", ok)
    print("hit set == exactly all pairs with A+B==496:", complete)
    # spot-check a failing pair
    load_value(sim, 100, 100)
    print("spot check A=100,B=100 (sum 200): S =", sim.read("S"))
    load_value(sim, 250, 246)
    print("spot check A=250,B=246 (sum 496): S =", sim.read("S"))

if __name__ == "__main__":
    main()
