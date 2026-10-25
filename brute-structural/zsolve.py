"""Unrolled SAT solve for the puzzle key (independent cross-check of the
structural trace): model the extracted netlist over the exact protocol
(reset -> 1 idle cycle -> 121 load cycles -> evaluate), and solve for the
121 serial input bits that make the success FF's D input high on the
evaluation cycle.

Only the cone of influence of the success D net is modelled (traced back
through time), which prunes the output generator and unrelated logic.

Timing model (steps):
  step 0: post-reset state. dfrtp Q=0 (RESET_B=rst_n was low), dfstp Q=1
          (SET_B=rst_n was low -> set active), dfxtp Q=0 (matches the
          simulator's power-up assumption).
  step 0 inputs: idle cycle (enable=0, I=0, rst_n=1).
  steps 1..121: load cycles (enable=1, I=I[step-1] symbolic, rst_n=1).
  step 122: evaluation cycle (enable=0, I=0, rst_n=1); assert D_success==1.
FF update: Q[step+1] = D[step] (rst_n=1 throughout the modelled window, so
reset/set are inactive; all resettable FFs use net_5 = rst_n).

build_model() is reusable: diffcheck.py imports it to compare the z3
model against the Python simulator step by step.
"""
import sys, re
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist

PATH = "/home/hatch/workspace/asic-puzzle-2026/solution/puzzle_extracted.v"
NSTEPS = 122  # steps 0..122; eval at 122
NLOAD = 121
POWER = ("VPWR", "VGND", "VPB", "VNB")
TARGET_D = "net_87"   # D input of the success FF (Q = net_66)


def build_model(nl):
    import z3
    driver = {}
    ff = {}  # Q -> (kind, D, RST/SET net or None)
    for base, conns in nl["instances"]:
        if base.startswith("dfrtp"):
            ff[conns["Q"]] = ("dfrtp", conns["D"], conns.get("RESET_B"))
        elif base.startswith("dfstp"):
            ff[conns["Q"]] = ("dfstp", conns["D"], conns.get("SET_B"))
        elif base.startswith("dfxtp"):
            ff[conns["Q"]] = ("dfxtp", conns["D"], None)
        elif base.startswith("conb"):
            for p, n in conns.items():
                if p in ("HI", "LO"):
                    driver[n] = ("conb", {p: n})
        else:
            for p, n in conns.items():
                if p in ("X", "Y"):
                    driver[n] = (base, conns)
    input_alias = {}
    for inp, nets in nl.get("input_aliases", {}).items():
        for n in nets:
            input_alias[n] = inp

    def step_inputs(step):
        if step == 0 or step == NSTEPS:
            return (False, True, False)
        return (True, True, None)  # load steps: I symbolic

    needed = set()
    stack = [(TARGET_D, NSTEPS)]
    while stack:
        net, step = stack.pop()
        if (net, step) in needed:
            continue
        needed.add((net, step))
        if net in ff:
            if step > 0:
                stack.append((ff[net][1], step - 1))
            continue
        cell = driver.get(net)
        if cell is None:
            continue
        base, conns = cell
        if base == "conb":
            continue
        for p, n in conns.items():
            if p in ("X", "Y") or p in POWER:
                continue
            stack.append((n, step))

    s = z3.Solver()
    var = {}

    def V(net, step):
        key = (net, step)
        if key not in var:
            var[key] = z3.Bool(f"{net}@{step}")
        return var[key]

    i_bits = [z3.Bool(f"I_{i}") for i in range(NLOAD)]

    def primary(net, step):
        inp = input_alias.get(net, net)
        en, rst, ival = step_inputs(step)
        if inp == "enable":
            return z3.BoolVal(en)
        if inp == "rst_n":
            return z3.BoolVal(rst)
        if inp == "clk":
            return z3.BoolVal(False)
        if inp == "I":
            if ival is None:
                return i_bits[step - 1]
            return z3.BoolVal(ival)
        return None

    def lit_expr(port, conns, step):
        net = conns[port]
        inv = port.endswith("_N")
        e = expr(net, step)
        return z3.Not(e) if inv else e

    def expr(net, step):
        if (net, step) in var:
            return var[(net, step)]
        if net in ff:
            kind, _d, _r = ff[net]
            if step == 0:
                return z3.BoolVal(kind == "dfstp")
            return V(net, step)
        cell = driver.get(net)
        if cell is None:
            p = primary(net, step)
            if p is not None:
                return p
            return z3.BoolVal(False)
        base, conns = cell
        if base == "conb":
            return z3.BoolVal("HI" in conns)
        return V(net, step)

    for q, (kind, _d, _r) in ff.items():
        if (q, 0) in needed:
            s.add(V(q, 0) == (kind == "dfstp"))
    for (net, step) in sorted(needed):
        if net in ff:
            if step == 0:
                continue
            _kind, d, _r = ff[net]
            s.add(V(net, step) == expr(d, step - 1))
            continue
        cell = driver.get(net)
        if cell is None:
            p = primary(net, step)
            if p is not None:
                s.add(V(net, step) == p)
            else:
                s.add(V(net, step) == z3.BoolVal(False))
            continue
        base, conns = cell
        if base == "conb":
            s.add(V(net, step) == z3.BoolVal("HI" in conns))
            continue
        e = gate_expr(base, conns, step, lit_expr)
        if e is None:
            raise ValueError(f"unmodelled gate in COI: {base}")
        s.add(V(net, step) == e)
    return {"solver": s, "V": V, "i_bits": i_bits, "ff": ff,
            "driver": driver, "input_alias": input_alias, "needed": needed,
            "expr": expr, "z3": z3}


def gate_expr(base, conns, step, lit_expr):
    import z3
    in_ports = [p for p in conns if p not in ("X", "Y") and p not in POWER]
    L = lambda p: lit_expr(p, conns, step)
    if base in ("buf", "clkbuf"):
        return L(in_ports[0])
    if base == "inv":
        return z3.Not(L(in_ports[0]))
    if base == "mux2":
        return z3.If(L("S"), L("A1"), L("A0"))
    if base in ("xor2", "xnor2"):
        e = z3.Xor(L("A"), L("B"))
        return z3.Not(e) if base == "xnor2" else e
    m = re.match(r"(and|or|nand|nor)(\d+)(b*)$", base)
    if m:
        op = m.group(1)
        lits = [L(p) for p in in_ports]
        e = z3.And(lits) if op in ("and", "nand") else z3.Or(lits)
        return z3.Not(e) if op in ("nand", "nor") else e
    if base[0] in ("a", "o"):
        # AOI/OAI families (incl. o2bb2a): structure from port groups.
        kind = base[0]
        inv_out = base.endswith("i")
        groups = {}
        for p in in_ports:
            groups.setdefault(p[0], []).append(L(p))
        if kind == "a":
            terms = [z3.And(g) if len(g) > 1 else g[0] for g in groups.values()]
            e = z3.Or(terms)
        else:
            terms = [z3.Or(g) if len(g) > 1 else g[0] for g in groups.values()]
            e = z3.And(terms)
        return z3.Not(e) if inv_out else e
    return None


def main():
    import z3
    nl = parse_netlist(PATH)
    m = build_model(nl)
    print(f"COI size: {len(m['needed'])} (net, step) pairs")
    m["solver"].add(m["expr"](TARGET_D, NSTEPS) == True)
    print("solving...")
    r = m["solver"].check()
    print("z3 result:", r)
    if r != z3.sat:
        print("UNSAT under the step-122 evaluation model.")
        return
    mod = m["solver"].model()
    key = "".join("1" if z3.is_true(mod.eval(b)) else "0" for b in m["i_bits"])
    print("candidate key (time order):", key)
    with open("z3_key.txt", "w") as f:
        f.write(key + "\n")
    print("wrote z3_key.txt")


if __name__ == "__main__":
    main()
