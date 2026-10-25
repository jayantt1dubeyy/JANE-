"""Gate-level simulator for sky130 structural Verilog netlists.

Parses a synthesized netlist (module header, wire decls, cell instances with
named ports), models each sky130 cell functionally from its standard name,
and simulates with levelized combinational evaluation + edge-triggered
flip-flops (dfrtp: posedge CLK, async active-low RESET_B).

Power-only cells (tap/decap/diode/fill) are ignored. conb (constant) cells
are honoured if present. No external simulator required.
"""

import re

# ---------------------------------------------------------------- cell models
# Each entry: (output_port, function over port dict)
# Port names follow the sky130 convention; suffix _N = inverted input,
# trailing 'i' in the cell function code = inverted output.

def _comb(fn):
    return fn


CELL_MODELS = {
    # buffers / constants
    "buf": ("X", lambda p: p["A"]),
    "clkbuf": ("X", lambda p: p["A"]),
    "inv": ("Y", lambda p: 1 - p["A"]),
    "conb": (None, None),  # handled specially: HI=1, LO=0
    # basic gates
    "and2": ("X", lambda p: p["A"] & p["B"]),
    "and3": ("X", lambda p: p["A"] & p["B"] & p["C"]),
    "and4": ("X", lambda p: p["A"] & p["B"] & p["C"] & p["D"]),
    "or2": ("X", lambda p: p["A"] | p["B"]),
    "or3": ("X", lambda p: p["A"] | p["B"] | p["C"]),
    "or4": ("X", lambda p: p["A"] | p["B"] | p["C"] | p["D"]),
    "nand2": ("Y", lambda p: 1 - (p["A"] & p["B"])),
    "nand3": ("Y", lambda p: 1 - (p["A"] & p["B"] & p["C"])),
    "nand4": ("Y", lambda p: 1 - (p["A"] & p["B"] & p["C"] & p["D"])),
    "nor2": ("Y", lambda p: 1 - (p["A"] | p["B"])),
    "nor3": ("Y", lambda p: 1 - (p["A"] | p["B"] | p["C"])),
    "nor4": ("Y", lambda p: 1 - (p["A"] | p["B"] | p["C"] | p["D"])),
    "xor2": ("X", lambda p: p["A"] ^ p["B"]),
    "xnor2": ("Y", lambda p: 1 - (p["A"] ^ p["B"])),
    "xor3": ("X", lambda p: p["A"] ^ p["B"] ^ p["C"]),
    "xnor3": ("Y", lambda p: 1 - (p["A"] ^ p["B"] ^ p["C"])),
    "mux2": ("X", lambda p: p["A1"] if p["S"] else p["A0"]),
    "mux4": ("X", lambda p: (p["A3"] if p["S1"] else p["A2"]) if p["S0"] else (p["A1"] if p["S1"] else p["A0"])),
    # AOI / OAI: a<k><m>o = (AND of k inputs) OR (AND of m inputs); 'i' = inverted out
    "a21o": ("X", lambda p: (p["A1"] & p["A2"]) | p["B1"]),
    "a21oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | p["B1"])),
    "a21bo": ("X", lambda p: (p["A1"] & p["A2"]) | (1 - p["B1_N"])),
    "a21boi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | (1 - p["B1_N"]))),
    "a211o": ("X", lambda p: (p["A1"] & p["A2"]) | p["B1"] | p["C1"]),
    "a211oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | p["B1"] | p["C1"])),
    "a221o": ("X", lambda p: (p["A1"] & p["A2"]) | (p["B1"] & p["B2"]) | p["C1"]),
    "a221oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | (p["B1"] & p["B2"]) | p["C1"])),
    "a31o": ("X", lambda p: (p["A1"] & p["A2"] & p["A3"]) | p["B1"]),
    "a31oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"] & p["A3"]) | p["B1"])),
    "a32o": ("X", lambda p: (p["A1"] & p["A2"] & p["A3"]) | (p["B1"] & p["B2"])),
    "a32oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"] & p["A3"]) | (p["B1"] & p["B2"]))),
    "a41o": ("X", lambda p: (p["A1"] & p["A2"] & p["A3"] & p["A4"]) | p["B1"]),
    "o21a": ("X", lambda p: (p["A1"] | p["A2"]) & p["B1"]),
    "o21ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"]) & p["B1"])),
    "o21ba": ("X", lambda p: (p["A1"] | p["A2"]) & (1 - p["B1_N"])),
    "o21bai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"]) & (1 - p["B1_N"]))),
    "o22a": ("X", lambda p: (p["A1"] | p["A2"]) & (p["B1"] | p["B2"])),
    "o22ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"]) & (p["B1"] | p["B2"]))),
    "o31a": ("X", lambda p: (p["A1"] | p["A2"] | p["A3"]) & p["B1"]),
    "o31ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"] | p["A3"]) & p["B1"])),
    # inverted-input ANDs: and4bb = ~A_N & ~B_N & C & D etc.
    "and2b": ("X", lambda p: (1 - p["A_N"]) & p["B"]),
    "and3b": ("X", lambda p: (1 - p["A_N"]) & p["B"] & p["C"]),
    "and3bb": ("X", lambda p: (1 - p["A_N"]) & (1 - p["B_N"]) & p["C"]),
    "and4b": ("X", lambda p: (1 - p["A_N"]) & p["B"] & p["C"] & p["D"]),
    "and4bb": ("X", lambda p: (1 - p["A_N"]) & (1 - p["B_N"]) & p["C"] & p["D"]),
    "and4bbb": ("X", lambda p: (1 - p["A_N"]) & (1 - p["B_N"]) & (1 - p["C_N"]) & p["D"]),
    "or2b": ("X", lambda p: (1 - p["A_N"]) | p["B"]),
    "or3b": ("X", lambda p: p["A"] | p["B"] | (1 - p["C_N"])),
    "or4b": ("X", lambda p: p["A"] | p["B"] | p["C"] | (1 - p["D_N"])),
    "or4bb": ("X", lambda p: p["A"] | p["B"] | (1 - p["C_N"]) | (1 - p["D_N"])),
    "nand2b": ("Y", lambda p: 1 - ((1 - p["A_N"]) & p["B"])),
    "nand3b": ("Y", lambda p: 1 - ((1 - p["A_N"]) & p["B"] & p["C"])),
    "nor2b": ("Y", lambda p: 1 - ((1 - p["A_N"]) | p["B"])),
    "nor3b": ("Y", lambda p: 1 - (p["A"] | p["B"] | (1 - p["C_N"]))),
    "nor4b": ("Y", lambda p: 1 - (p["A"] | p["B"] | p["C"] | (1 - p["D_N"]))),
    "o21bo": ("X", lambda p: (p["A1"] | p["A2"]) | (1 - p["B1_N"])),
    # extended AOI/OAI families (equations verified against PDK func comments)
    "a211o": ("X", lambda p: (p["A1"] & p["A2"]) | p["B1"] | p["C1"]),
    "a211oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | p["B1"] | p["C1"])),
    "a2111oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | p["B1"] | p["C1"] | p["D1"])),
    "a221o": ("X", lambda p: (p["A1"] & p["A2"]) | (p["B1"] & p["B2"]) | p["C1"]),
    "a221oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | (p["B1"] & p["B2"]) | p["C1"])),
    "a22o": ("X", lambda p: (p["A1"] & p["A2"]) | (p["B1"] & p["B2"])),
    "a22oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"]) | (p["B1"] & p["B2"]))),
    "a311o": ("X", lambda p: (p["A1"] & p["A2"] & p["A3"]) | p["B1"] | p["C1"]),
    "a31oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"] & p["A3"]) | p["B1"])),
    "a41oi": ("Y", lambda p: 1 - ((p["A1"] & p["A2"] & p["A3"] & p["A4"]) | p["B1"])),
    "o211a": ("X", lambda p: (p["A1"] | p["A2"]) & p["B1"] & p["C1"]),
    "o211ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"]) & p["B1"] & p["C1"])),
    "o221a": ("X", lambda p: (p["A1"] | p["A2"]) & (p["B1"] | p["B2"]) & p["C1"]),
    "o22a": ("X", lambda p: (p["A1"] | p["A2"]) & (p["B1"] | p["B2"])),
    "o22ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"]) & (p["B1"] | p["B2"]))),
    # NOTE (verified against PDK primitives): o2bb2a is NAND(A1_N,A2_N) AND
    # OR(B1,B2) -- the _N pins feed the NAND directly, NOT inverted first.
    # An earlier version had (A1_N|A2_N) here, which is wrong.
    "o2bb2a": ("X", lambda p: (1 - (p["A1_N"] & p["A2_N"])) & (p["B1"] | p["B2"])),
    "o311a": ("X", lambda p: (p["A1"] | p["A2"] | p["A3"]) & p["B1"] & p["C1"]),
    "o31a": ("X", lambda p: (p["A1"] | p["A2"] | p["A3"]) & p["B1"]),
    "o31ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"] | p["A3"]) & p["B1"])),
    "o32a": ("X", lambda p: (p["A1"] | p["A2"] | p["A3"]) & (p["B1"] | p["B2"])),
    "o32ai": ("Y", lambda p: 1 - ((p["A1"] | p["A2"] | p["A3"]) & (p["B1"] | p["B2"]))),
    "o21ba": ("X", lambda p: (p["A1"] | p["A2"]) & (1 - p["B1_N"])),
}

IGNORE_PREFIXES = ("tap", "decap", "diode", "fill")

# ------------------------------------------------------------------- parsing

def _unescape(tok):
    return tok[1:] if tok.startswith("\\") else tok


def parse_netlist(path):
    """Return dict with inputs, outputs, instances.

    instances: list of (cell_base, {port: net}) for logic cells only.
    cell_base strips the sky130_fd_sc_hd__ prefix and _<drive> suffix.
    """
    txt = open(path).read()
    txt = re.sub(r"//.*", "", txt)
    # escaped identifiers: backslash + non-whitespace chars, terminated by space
    txt = re.sub(r"\\(\S+)\s", lambda m: "ESC" + m.group(1) + " ", txt)

    m = re.search(r"module\s+\w+\s*\((.*?)\);", txt, re.S)
    header = m.group(1) if m else ""
    ports = [p.strip() for p in header.split(",") if p.strip()]
    inputs, outputs = [], []
    for decl, lst in re.findall(r"\b(input|output)\b\s+([^;]+);", txt):
        for chunk in lst.split(","):
            chunk = chunk.strip()
            chunk = re.sub(r"^(wire|reg)\s+", "", chunk)
            chunk = re.sub(r"\[[^\]]*\]", "", chunk).strip()
            if chunk.startswith("ESC"):
                chunk = chunk[3:]
            if chunk:
                (inputs if decl == "input" else outputs).append(chunk)
    # header-only ports (no separate decl) fall back to the header list
    if not inputs and not outputs:
        for name in ports:
            name = re.sub(r"\[[^\]]*\]", "", name).strip()
            if name.startswith("ESC"):
                name = name[3:]
            outputs.append(name)

    # continuous assigns: alias map lhs -> rhs (may be a primary input,
    # another net, or a bus bit like O[3])
    raw_alias = {}
    for lhs, rhs in re.findall(r"\bassign\s+(\S+)\s*=\s*(\S+)\s*;", txt):
        if lhs.startswith("ESC"):
            lhs = lhs[3:]
        if rhs.startswith("ESC"):
            rhs = rhs[3:]
        raw_alias[lhs] = rhs

    def resolve(net, _seen=None):
        _seen = _seen or set()
        while net in raw_alias and net not in _seen:
            _seen.add(net)
            net = raw_alias[net]
        return net

    # nets driven directly by a primary input (e.g. net_271 = I)
    input_aliases = {}
    for lhs, rhs in raw_alias.items():
        if rhs in inputs:
            input_aliases.setdefault(rhs, []).append(lhs)
    # output ports -> driving net (bus bits kept as O[i])
    outputs_map = {}
    for o in outputs:
        if o in raw_alias:
            outputs_map[o] = resolve(o)
    for lhs in raw_alias:
        mm = re.match(r"(\w+)\[(\d+)\]$", lhs)
        if mm and mm.group(1) in outputs:
            outputs_map[lhs] = resolve(lhs)

    instances = []
    pat = re.compile(r"(sky130_fd_sc_hd__\w+)\s+(\S+?)\s*\((.*?)\);\s*$", re.M | re.S)
    for mm in pat.finditer(txt):
        full, _inst, body = mm.group(1), mm.group(2), mm.group(3)
        base = full[len("sky130_fd_sc_hd__"):]
        base = re.sub(r"_\d+$", "", base)
        if any(base.startswith(p) for p in IGNORE_PREFIXES):
            continue
        conns = {}
        for pm in re.finditer(r"\.(\w+)\(\s*([^)]*?)\s*\)", body):
            net = pm.group(2).strip()
            if net.startswith("ESC"):
                net = net[3:]
            conns[pm.group(1)] = resolve(net)
        instances.append((base, conns))
    return {"inputs": inputs, "outputs": outputs, "instances": instances,
            "outputs_map": outputs_map, "input_aliases": input_aliases,
            "aliases": raw_alias}


# ---------------------------------------------------------------- simulator

class Sim:
    def __init__(self, netlist):
        self.nl = netlist
        self.val = {}
        self.ffs = []   # (clk_net, d_net, q_net, rst_net)
        self.comb = []  # (cell_base, conns, out_port, fn)
        self.const_nets = {}
        for base, conns in netlist["instances"]:
            if base.startswith("dfrtp") or base.startswith("dfstp") or base.startswith("dfxtp"):
                # DFF with async reset (RESET_B) or set; Q output
                self.ffs.append((conns.get("CLK"), conns.get("D"), conns.get("Q"),
                                 conns.get("RESET_B"), conns.get("SET_B")))
            elif base.startswith("conb"):
                for port, net in conns.items():
                    if port == "HI":
                        self.const_nets[net] = 1
                    elif port == "LO":
                        self.const_nets[net] = 0
            else:
                model = CELL_MODELS.get(base)
                if model is None:
                    raise ValueError(f"no cell model for {base}")
                out_port, fn = model
                self.comb.append((base, conns, out_port, fn))
        # levelize combinational gates: order so drivers come before consumers
        self._levelize()
        for net, v in self.const_nets.items():
            self.val[net] = v

    def _levelize(self):
        driver = {}
        for base, conns, out_port, fn in self.comb:
            driver[conns[out_port]] = True
        ordered, remaining = [], list(self.comb)
        known = set(self.nl["inputs"])
        known |= {q for *_r, q, _s in [(f[0], f[1], f[2], f[3], f[4]) for f in self.ffs]}
        known |= set(self.const_nets)
        while remaining:
            progress = False
            nxt = []
            for item in remaining:
                _b, conns, out_port, _f = item
                ins = [n for p, n in conns.items()
                       if p != out_port and p not in ("VPWR", "VGND", "VPB", "VNB")]
                if all(n in known or n not in driver for n in ins):
                    ordered.append(item)
                    known.add(conns[out_port])
                    progress = True
                else:
                    nxt.append(item)
            if not progress:
                # combinational loop (should not happen in synth netlists);
                # fall back to remaining order and iterate to fixpoint
                ordered.extend(nxt)
                break
            remaining = nxt
        self.comb = ordered

    def settle(self, iters=50):
        for _ in range(iters):
            changed = False
            for _b, conns, out_port, fn in self.comb:
                args = {}
                ok = True
                for p, n in conns.items():
                    if p == out_port or p in ("VPWR", "VGND", "VPB", "VNB"):
                        continue
                    if n not in self.val:
                        ok = False
                        break
                    args[p] = self.val[n]
                if not ok:
                    continue
                v = fn(args) & 1
                if self.val.get(conns[out_port]) != v:
                    self.val[conns[out_port]] = v
                    changed = True
            if not changed:
                break

    def set_inputs(self, **kw):
        for k, v in kw.items():
            self.val[k] = v & 1
            for alias in self.nl.get("input_aliases", {}).get(k, []):
                self.val[alias] = v & 1
        # async reset/set
        for clk_n, d_n, q_n, rst_n, set_n in self.ffs:
            if rst_n is not None and self.val.get(rst_n, 1) == 0:
                self.val[q_n] = 0
            elif set_n is not None and self.val.get(set_n, 1) == 0:
                self.val[q_n] = 1
        self.settle()

    def clock_edge(self):
        """One rising edge: sample D of every FF, update Q, settle."""
        updates = {}
        for clk_n, d_n, q_n, rst_n, set_n in self.ffs:
            if rst_n is not None and self.val.get(rst_n, 1) == 0:
                updates[q_n] = 0
            elif set_n is not None and self.val.get(set_n, 1) == 0:
                updates[q_n] = 1
            else:
                updates[q_n] = self.val.get(d_n, 0)
        self.val.update(updates)
        self.settle()

    def cycle(self, **inputs):
        """Set inputs (with clk=0), settle, then raise clk for one edge."""
        inputs = dict(inputs)
        inputs["clk"] = 0
        self.set_inputs(**inputs)
        self.set_inputs(clk=1)
        self.clock_edge()
        self.set_inputs(clk=0)

    def reset(self, cycles=2):
        kw = {p: 0 for p in self.nl["inputs"] if p != "rst_n"}
        for _ in range(cycles):
            self.cycle(rst_n=0, **kw)
        self.set_inputs(rst_n=1)
