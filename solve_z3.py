#!/usr/bin/env python3
"""Bounded-model-checking solve for the 121-bit key.

Unrolls the extracted netlist over the VCD-aligned protocol (3 reset
edges, 1 gap edge, 121 shift edges, 16 stream edges) with the 121 I bits
as free symbolic variables, constrains success == 1 at the first stream
edge (cycle 125), and solves with Z3. Then proves uniqueness with a
blocking clause, and re-solves with the layout-undriven net forced to 1
to check the key does not depend on that assumption.

Usage: solve_z3.py <netlist.json> [undriven_value]
Prints the key, the SAT/UNSAT results, and timing.
"""
import sys, os, json, time
sys.path.insert(0, "/home/hatch/workspace/.pydeps")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import z3
from simulate import Circuit, run_cycles
from cells import Ops


def solve(json_path, undriven_value=False):
    data = json.load(open(json_path))
    circ = Circuit(data)
    print("circuit: %d comb, %d FF, undriven: %s"
          % (len(circ.comb), len(circ.ffs), sorted(circ.undriven)))
    ops = Ops(True)
    I_vars = [z3.Bool("I_%d" % k) for k in range(121)]
    cycles = []
    for _ in range(3):
        cycles.append({"rst_n": z3.BoolVal(False), "enable": z3.BoolVal(False),
                       "I": z3.BoolVal(False)})
    cycles.append({"rst_n": z3.BoolVal(True), "enable": z3.BoolVal(False),
                   "I": z3.BoolVal(False)})
    for k in range(121):
        cycles.append({"rst_n": z3.BoolVal(True), "enable": z3.BoolVal(True),
                       "I": I_vars[k]})
    for _ in range(16):
        cycles.append({"rst_n": z3.BoolVal(True), "enable": z3.BoolVal(False),
                       "I": z3.BoolVal(False)})
    t0 = time.time()
    results, _ = run_cycles(circ, ops, cycles, undriven_value=undriven_value)
    print("unrolled %d cycles in %.1fs" % (len(cycles), time.time() - t0))
    solver = z3.Solver()
    solver.add(results[125]["success"] == z3.BoolVal(True))
    t0 = time.time()
    res = solver.check()
    print("solve:", res, "in %.1fs" % (time.time() - t0))
    if res != z3.sat:
        return None
    model = solver.model()
    key = "".join("1" if z3.is_true(model.eval(v)) else "0" for v in I_vars)
    print("key:", key)
    # uniqueness: block this exact key, require a different solution
    block = z3.Or([v != z3.BoolVal(b == "1") for v, b in zip(I_vars, key)])
    solver.add(block)
    t0 = time.time()
    res2 = solver.check()
    print("uniqueness check (expect unsat):", res2, "in %.1fs" % (time.time() - t0))
    return key


if __name__ == "__main__":
    undriven = bool(int(sys.argv[2])) if len(sys.argv) > 2 else False
    key = solve(sys.argv[1], undriven_value=undriven)
    print("RESULT key =", key)
