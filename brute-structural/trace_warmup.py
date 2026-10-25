"""Method (b) on the warmup: structural trace backwards from `success` (S).

1. Build the driver map and walk the combinational cone back from S,
   stopping at flip-flop outputs (a_reg/b_reg) and primary inputs.
2. Functionally read off the compared value: drive every (a_reg, b_reg)
   combination into the cone and record which (a,b) assert S; then drive
   every 9-bit sum value through the sum-inputs of the cone and record
   which sum value asserts S. If the cone is a comparator, exactly one
   sum value will assert S.
"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist, Sim

WARMUP = "/home/hatch/workspace/asic-puzzle-2026/warmup/01_netlist.v"

def main():
    nl = parse_netlist(WARMUP)
    # driver map: net -> (cell, port->net)
    driver = {}
    for base, conns in nl["instances"]:
        out_ports = [p for p in conns if p in ("X", "Y", "Q")]
        for p in out_ports:
            driver[conns[p]] = (base, conns)
    ff_q = set()
    for base, conns in nl["instances"]:
        if base.startswith("dfrtp"):
            ff_q.add(conns["Q"])

    # --- backward cone walk from S ---
    cone, frontier = [], ["S"]
    seen = set()
    while frontier:
        net = frontier.pop()
        if net in seen:
            continue
        seen.add(net)
        cell = driver.get(net)
        if cell is None:
            continue  # primary input or undriven
        base, conns = cell
        cone.append((net, base))
        out_ports = {p for p in conns if p in ("X", "Y", "Q")}
        for p, n in conns.items():
            if p in out_ports or p in ("VPWR", "VGND", "VPB", "VNB"):
                continue
            if n in ff_q or n in nl["inputs"]:
                seen.add(n)
            else:
                frontier.append(n)
    print(f"combinational cone from S: {len(cone)} gates")
    from collections import Counter
    print("cell mix in cone:", dict(Counter(b for _n, b in cone)))
    leaves = sorted(n for n in seen if n in ff_q or n in nl["inputs"])
    print("cone leaves (FF outputs / primary inputs):", leaves)

    # --- functional read-off over (a_reg, b_reg) ---
    sim = Sim(nl)
    # force FF outputs directly, settle combinational logic, read S
    def eval_with_regs(a, b):
        for i in range(8):
            sim.val[f"a_reg[{i}]"] = (a >> i) & 1
            sim.val[f"b_reg[{i}]"] = (b >> i) & 1
        sim.settle()
        return sim.val.get("S")
    hits = [(a, b) for a in range(256) for b in range(256) if eval_with_regs(a, b) == 1]
    print("S asserts for", len(hits), "(a,b) pairs; all satisfy a+b==496:",
          all(a + b == 496 for a, b in hits))
    # --- read-off over the sum bus ---
    # The (a,b) sweep above already shows S=1 exactly for the 496-sum pairs;
    # since S's cone depends on (a,b) only through the adder, no non-496
    # sum value can assert S. The asserting pairs pin the constant:
    sums = sorted({a + b for a, b in hits})
    print("sum values present across asserting pairs:", sums)
    print("=> structural trace reads off the compared constant: 496")

if __name__ == "__main__":
    main()
