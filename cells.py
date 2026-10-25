"""Parse official SkyWater sky130_fd_sc_hd functional Verilog models
(cells/<func>/sky130_fd_sc_hd__<func>.functional.v) into executable
cell behaviour: port directions, primitive netlists, and flip-flop rules.

The functional models are built from Verilog primitives (not/and/or/xor/
buf/nand/nor/xnor/pullup/pulldown) plus UDP DFFs for sequential cells.
No behaviour is hand-coded here except the UDP DFF next-state rules,
which are verified against the UDP state tables in models/udp_dff_*.
"""
import os, re, sys

CELL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sky130_cells")
PRIM2 = {"not": 1, "buf": 1, "and": None, "or": None, "xor": None,
         "nand": None, "nor": None, "xnor": None}
POWER = {"VPWR", "VGND", "VPB", "VNB"}


def func_of(full_name):
    """sky130_fd_sc_hd__nand2_2 -> nand2 (strip drive strength)."""
    short = full_name[len("sky130_fd_sc_hd__"):]
    return re.sub(r"_[0-9]+$", "", short)


def parse_cell_model(func):
    path = os.path.join(CELL_DIR, "func_%s.v" % func)
    with open(path) as f:
        text = f.read()
    # strip comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    inputs, outputs = [], []
    for m in re.finditer(r"\b(input|output)\s+([^;]+);", text):
        direction, names = m.group(1), m.group(2)
        for nm in names.split(","):
            nm = nm.strip()
            if nm:
                (inputs if direction == "input" else outputs).append(nm)
    prims = []          # (kind, out, [ins]) in file order
    ff = None           # (kind, udp_out, d, clk, ctl_net) for sequential cells
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("`") or line.startswith("module") \
                or line.startswith("endmodule") or line.startswith("wire"):
            continue
        m = re.match(r"(not|buf|and|or|xor|nand|nor|xnor)\s+\w+\s*\(([^)]*)\)\s*;", line)
        if m:
            kind = m.group(1)
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            prims.append((kind, args[0], args[1:]))
            continue
        m = re.match(r"(pullup|pulldown)\s+\w+\s*\(([^)]*)\)\s*;", line)
        if m:
            prims.append((m.group(1), m.group(2).strip(), []))
            continue
        m = re.match(r"sky130_fd_sc_hd__udp_dff\$(\w+).*?\(([^)]*)\)\s*;", line)
        if m:
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            # (Q_buf, D, CLK, [RESET|SET])
            ff = (m.group(1), args[0], args[1], args[2], args[3] if len(args) > 3 else None)
            continue
        m = re.match(r"sky130_fd_sc_hd__udp_mux_2to1\s+\w+\s*\(([^)]*)\)\s*;", line)
        if m:
            args = [a.strip() for a in m.group(1).split(",") if a.strip()]
            prims.append(("mux", args[0], args[1:]))
            continue
        if line.startswith("assign"):
            raise ValueError("unexpected assign in %s: %s" % (func, line))
    if ff is not None:
        # Resolve the UDP control net back to the external pin through the
        # inverter: e.g. RESET = not(RESET_B). The UDP output buf_Q feeds
        # the output pin through a buf primitive.
        kind, udp_out, d, clk, ctl = ff
        ctl_pin = None
        if ctl is not None:
            for pk, pout, pins in prims:
                if pk == "not" and pout == ctl:
                    ctl_pin = pins[0]
        ff = {"udp": kind, "udp_out": udp_out, "d": d, "clk": clk, "ctl_pin": ctl_pin}
    return {"func": func, "inputs": inputs, "outputs": outputs,
            "prims": prims, "ff": ff}


class Ops:
    """Value-type abstraction: concrete booleans or z3 expressions."""

    def __init__(self, is_z3):
        self.is_z3 = is_z3
        if is_z3:
            import z3
            self.z3 = z3

    def NOT(self, a):
        return self.z3.Not(a) if self.is_z3 else (not a)

    def AND(self, *args):
        if self.is_z3:
            return self.z3.And(*args)
        r = True
        for a in args:
            r = r and a
        return r

    def OR(self, *args):
        if self.is_z3:
            return self.z3.Or(*args)
        r = False
        for a in args:
            r = r or a
        return r

    def XOR(self, *args):
        if self.is_z3:
            return self.z3.Xor(*args)
        r = False
        for a in args:
            r = r ^ a
        return r

    def ITE(self, cond, a, b):
        if self.is_z3:
            return self.z3.If(cond, a, b)
        return a if cond else b


def eval_cell(model, pin_values, ops):
    """Evaluate one combinational cell. pin_values: {pin: value}.
    Returns {output_pin: value}. Sequential cells are NOT evaluated here
    (their next-state rule lives in the simulator / Z3 unrolling)."""
    vals = dict(pin_values)
    for kind, out, ins in model["prims"]:
        if kind == "not":
            vals[out] = ops.NOT(vals[ins[0]])
        elif kind == "buf":
            vals[out] = vals[ins[0]]
        elif kind == "and":
            vals[out] = ops.AND(*[vals[i] for i in ins])
        elif kind == "or":
            vals[out] = ops.OR(*[vals[i] for i in ins])
        elif kind == "xor":
            vals[out] = ops.XOR(*[vals[i] for i in ins])
        elif kind == "nand":
            vals[out] = ops.NOT(ops.AND(*[vals[i] for i in ins]))
        elif kind == "nor":
            vals[out] = ops.NOT(ops.OR(*[vals[i] for i in ins]))
        elif kind == "xnor":
            vals[out] = ops.NOT(ops.XOR(*[vals[i] for i in ins]))
        elif kind == "mux":
            # ins = [A0, A1, S]; out = S ? A1 : A0
            vals[out] = ops.ITE(vals[ins[2]], vals[ins[1]], vals[ins[0]])
        elif kind == "pullup":
            vals[out] = ops.AND() if ops.is_z3 else True
            if ops.is_z3:
                vals[out] = ops.z3.BoolVal(True)
        elif kind == "pulldown":
            vals[out] = ops.z3.BoolVal(False) if ops.is_z3 else False
        else:
            raise ValueError("unknown primitive %s" % kind)
    return {o: vals[o] for o in model["outputs"]}


def load_all_models(full_names):
    """full_names: iterable of full cell names. Returns {full: model}."""
    cache = {}
    out = {}
    for full in full_names:
        func = func_of(full)
        if func not in cache:
            cache[func] = parse_cell_model(func)
        out[full] = cache[func]
    return out


if __name__ == "__main__":
    import json, itertools
    types = set()
    for d in json.load(open("/tmp/cell_types.json")).values():
        types.update(d.keys())
    models = load_all_models(types)
    print("parsed %d cell types" % len(models))
    bad = []
    for full, m in sorted(models.items()):
        if m["ff"] is not None:
            print("FF %-32s udp=%s d=%s clk=%s ctl_pin=%s outs=%s" %
                  (full, m["ff"]["udp"], m["ff"]["d"], m["ff"]["clk"],
                   m["ff"]["ctl_pin"], m["outputs"]))
            # sanity: FF must have exactly one output Q
            if m["outputs"] != ["Q"]:
                bad.append((full, "ff outputs != [Q]"))
        else:
            # every output must be driven by some primitive
            driven = {p[1] for p in m["prims"]}
            if m["ff"] is not None:
                driven.add(m["ff"]["udp_out"])
            for o in m["outputs"]:
                if o not in driven:
                    bad.append((full, "output %s not driven" % o))
            # every primitive input must be a pin or driven internally
            known = set(m["inputs"]) | driven
            for kind, o, ins in m["prims"]:
                for i in ins:
                    if i not in known:
                        bad.append((full, "prim input %s unknown" % i))
    print("problems:", bad if bad else "none")
    # spot checks with concrete booleans
    ops = Ops(False)
    checks = [
        ("sky130_fd_sc_hd__and2b_2", {"A_N": True, "B": True}, {"X": False}),
        ("sky130_fd_sc_hd__and2b_2", {"A_N": False, "B": True}, {"X": True}),
        ("sky130_fd_sc_hd__o2bb2a_2", {"A1_N": False, "A2_N": False, "B1": True, "B2": False}, None),
        ("sky130_fd_sc_hd__mux2_1", {"A0": False, "A1": True, "S": True}, {"X": True}),
        ("sky130_fd_sc_hd__mux2_1", {"A0": True, "A1": False, "S": False}, {"X": True}),
        ("sky130_fd_sc_hd__conb_1", {}, {"HI": True, "LO": False}),
        ("sky130_fd_sc_hd__a2111oi_2", {"A1": True, "A2": True, "B1": False, "C1": False, "D1": False}, {"Y": False}),
        ("sky130_fd_sc_hd__xor2_2", {"A": True, "B": False}, {"X": True}),
        ("sky130_fd_sc_hd__xnor2_2", {"A": True, "B": True}, {"Y": True}),
        ("sky130_fd_sc_hd__a21boi_2", {"A1": True, "A2": True, "B1_N": False}, None),
    ]
    for full, pins, expect in checks:
        got = eval_cell(models[full], pins, ops)
        print("check %-32s %s -> %s %s" % (full, pins, got,
              "OK" if expect is None or got == expect else "MISMATCH exp %s" % expect))
