"""Method (b) on the puzzle: structural trace backwards from `success`.

Steps:
1. Walk the combinational cone back from `success`, stopping at flip-flop
   outputs and primary inputs.
2. Encode the cone as CNF (Tseitin, one clause per forbidden input/output
   combination per gate) and solve for success==1 with a small DPLL solver
   (unit propagation + branching). For an equality-comparator checker this
   propagates deterministically to the required register values.
3. Classify flip-flops: shift-chain FFs (D driven by a mux selecting
   between the previous FF's Q and the serial input I, or directly by the
   previous Q / I) form the key register; the rest are state/control FFs.
4. Emit the required key-register state and both candidate serial orders
   (chain order and reversed); verify_puzzle.py decides empirically which
   order the hardware uses.

Usage: python3 trace_puzzle.py [netlist.v]
If no path is given, auto-discovers a puzzle netlist under solution/
(excluding sky130_cells/ and the warmup).
"""
import sys, os, glob, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist, CELL_MODELS

SOL = "/home/hatch/workspace/asic-puzzle-2026/solution"
POWER = ("VPWR", "VGND", "VPB", "VNB")


def discover():
    cands = []
    for p in glob.glob(SOL + "/**/*.v", recursive=True):
        if "sky130_cells" in p or "warmup" in p:
            continue
        if os.path.basename(p) in ("cells.py",):
            continue
        cands.append(p)
    # prefer names mentioning puzzle/netlist/extract
    cands.sort(key=lambda p: (0 if any(k in os.path.basename(p).lower()
                                        for k in ("puzzle", "netlist", "extract")) else 1, p))
    return cands


def build_cone(nl, target="success"):
    driver = {}
    ff_info = {}   # Q net -> (base, conns)
    for base, conns in nl["instances"]:
        if base.startswith(("dfrtp", "dfstp", "dfxtp")):
            ff_info[conns["Q"]] = (base, conns)
            continue
        for p, n in conns.items():
            if p in ("X", "Y"):
                driver[n] = (base, conns)
    cone = {}      # net -> (base, conns)
    leaves = set()
    stack = [target]
    seen = set()
    while stack:
        net = stack.pop()
        if net in seen:
            continue
        seen.add(net)
        if net in ff_info or net in nl["inputs"]:
            leaves.add(net)
            continue
        cell = driver.get(net)
        if cell is None:
            leaves.add(net)  # constant / undriven net
            continue
        base, conns = cell
        cone[net] = (base, conns)
        for p, n in conns.items():
            if p in ("X", "Y") or p in POWER:
                continue
            stack.append(n)
    return cone, leaves, driver, ff_info


# --------------------------------------------------------------------- DPLL
# Definitional CNF encoding (propagates both ways, unlike forbidden-combo
# enumeration): each gate output is tied to its inputs with clauses that
# unit-propagate in both directions, so asserting success==1 walks straight
# down an AND/XNOR comparator tree to the leaves.
#
# A literal is (var, inverted?). Ports ending in _N are inverted inputs.

def _lit(var_of, conns, port):
    v = var_of[conns[port]]
    return (v, port.endswith("_N"))


def _as_lit(lit):
    v, inv = lit
    return -v if inv else v


def _emit_and(clauses, aux, lits):
    """aux <-> AND(lits). lits: list of (var, inverted)."""
    for v, inv in lits:
        clauses.append([-aux, -v if inv else v])
    clauses.append([aux] + [v if inv else -v for v, inv in lits])


def gate_cnf(out_var, base, conns, var_of, aux_alloc):
    """Return clauses tying out_var to the gate function of base.
    aux_alloc: callable returning a fresh variable id."""
    in_ports = [p for p in conns if p not in ("X", "Y") and p not in POWER]
    clauses = []

    def lit(port):
        return _lit(var_of, conns, port)

    def tie_equiv(a, b):
        clauses.append([-a, b])
        clauses.append([a, -b])

    def tie_not(a, b):  # a <-> ~b
        clauses.append([-a, -b])
        clauses.append([a, b])

    if base in ("buf", "clkbuf"):
        tie_equiv(out_var, _as_lit(lit(in_ports[0])))
        return clauses
    if base == "inv":
        tie_not(out_var, _as_lit(lit(in_ports[0])))
        return clauses
    if base == "mux2":
        s = _as_lit(lit("S"))
        a0 = _as_lit(lit("A0"))
        a1 = _as_lit(lit("A1"))
        # out <-> (S ? A1 : A0)
        clauses.append([-s, -a1, out_var])
        clauses.append([-s, a1, -out_var])
        clauses.append([s, -a0, out_var])
        clauses.append([s, a0, -out_var])
        return clauses
    if base in ("xor2", "xnor2"):
        a = _as_lit(lit("A"))
        b = _as_lit(lit("B"))
        # xor: out <-> a^b ; xnor: out <-> ~(a^b)
        neg = base == "xnor2"
        clauses.append([-a, -b, -out_var if not neg else out_var])
        clauses.append([a, b, -out_var if not neg else out_var])
        clauses.append([a, -b, out_var if not neg else -out_var])
        clauses.append([-a, b, out_var if not neg else -out_var])
        return clauses
    # AND/OR/NAND/NOR families (incl. inverted-input 'b' variants)
    m = __import__("re").match(r"(and|or|nand|nor)(\d+)(b*)$", base)
    if m:
        op, _n, _bs = m.group(1), int(m.group(2)), m.group(3)
        lits = [lit(p) for p in in_ports]
        g = aux_alloc()
        if op in ("and", "nand"):
            _emit_and(clauses, g, lits)
        else:
            # g <-> OR(lits): (¬lit ∨ g) per lit; (¬g ∨ lit_1 ∨ ...)
            for v, inv in lits:
                clauses.append([g, v if inv else -v])
            clauses.append([-g] + [-v if inv else v for v, inv in lits])
        if op in ("nand", "nor"):
            tie_not(out_var, g)
        else:
            tie_equiv(out_var, g)
        return clauses
    # AOI/OAI families: structure from port groups, not name digits
    # (covers oddballs like o2bb2a); trailing 'i' = inverted output.
    if base[0] in ("a", "o"):
        kind, inv_out = base[0], base.endswith("i")
        groups = {}
        for p in in_ports:
            groups.setdefault(p[0], []).append(lit(p))
        if kind == "a":
            # out = OR over groups of AND(group)
            terms = []
            for gname in sorted(groups):
                glits = groups[gname]
                if len(glits) == 1:
                    terms.append(_as_lit(glits[0]))
                else:
                    t = aux_alloc()
                    _emit_and(clauses, t, glits)
                    terms.append(t)
            g = aux_alloc()
            for t in terms:
                clauses.append([-t, g])
            clauses.append([-g] + terms)
        else:
            # out = AND over groups of OR(group)
            terms = []
            for gname in sorted(groups):
                glits = groups[gname]
                if len(glits) == 1:
                    terms.append(_as_lit(glits[0]))
                else:
                    t = aux_alloc()
                    for v, inv in glits:
                        clauses.append([t, v if inv else -v])
                    clauses.append([-t] + [-v if inv else v for v, inv in glits])
                    terms.append(t)
            g = aux_alloc()
            _emit_and(clauses, g, [(t, False) for t in terms])
        if inv_out:
            tie_not(out_var, g)
        else:
            tie_equiv(out_var, g)
        return clauses
    return None


def dpll(clauses, nvars, max_decisions=200000):
    """Simple DPLL: unit propagation + branching. Returns assignment dict
    var->bool or None if UNSAT / budget exhausted (with 'budget' flag)."""
    assign = {}

    def propagate(clauses, assign):
        changed = True
        while changed:
            changed = False
            for cl in clauses:
                un, sat = [], False
                for lit in cl:
                    v = assign.get(abs(lit))
                    if v is None:
                        un.append(lit)
                    elif (v and lit > 0) or (not v and lit < 0):
                        sat = True
                        break
                if sat:
                    continue
                if not un:
                    return False
                if len(un) == 1:
                    lit = un[0]
                    assign[abs(lit)] = lit > 0
                    changed = True
        return True

    decisions = [0]

    def solve():
        if not propagate(clauses, assign):
            return None
        if len(assign) == nvars:
            return dict(assign)
        # pick first unassigned variable
        v = next(i for i in range(1, nvars + 1) if i not in assign)
        decisions[0] += 1
        if decisions[0] > max_decisions:
            return "budget"
        for val in (True, False):
            saved = dict(assign)
            assign[v] = val
            r = solve()
            if r is not None:
                return r
            assign.clear()
            assign.update(saved)
        return None

    r = solve()
    return r


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        cands = discover()
        if not cands:
            print("NO PUZZLE NETLIST FOUND under", SOL)
            print("Status: waiting on netlist extraction; warmup proof stands alone.")
            return
        path = cands[0]
        print("auto-discovered netlist:", path)
    nl = parse_netlist(path)
    print("module inputs:", nl["inputs"])
    print("module outputs:", nl["outputs"])
    print("logic instances:", len(nl["instances"]))
    target_net = nl.get("outputs_map", {}).get("success", "success")
    print("success resolves to net:", target_net)

    cone, leaves, driver, ff_info = build_cone(nl, target=target_net)
    if not cone and target_net in ff_info:
        # success is a registered output: the real condition is the D-input
        # cone of the success flip-flop (sampled on the evaluation edge).
        fbase, fconns = ff_info[target_net]
        print(f"success is the Q output of a {fbase} FF:")
        print(f"  CLK={fconns.get('CLK')} D={fconns.get('D')} "
              f"RESET_B={fconns.get('RESET_B')} SET_B={fconns.get('SET_B')}")
        target_net = fconns["D"]
        print("tracing the D-input cone instead:", target_net)
        cone, leaves, driver, ff_info = build_cone(nl, target=target_net)
    from collections import Counter
    print(f"success cone: {len(cone)} gates; leaves: {len(leaves)}")
    print("cone cell mix:", dict(Counter(b for b, _c in cone.values())))
    ff_leaves = sorted(n for n in leaves if n in ff_info)
    other_leaves = sorted(n for n in leaves if n not in ff_info)
    print(f"cone leaves that are FF outputs: {len(ff_leaves)}")
    print("other cone leaves (primary inputs / constants):", other_leaves)

    # ---- CNF + solve ----
    var_of = {}
    def var(net):
        if net not in var_of:
            var_of[net] = len(var_of) + 1
        return var_of[net]
    for net in cone:
        var(net)
    for net in leaves:
        var(net)
    next_aux = [len(var_of) + 1]
    def aux_alloc():
        v = next_aux[0]
        next_aux[0] += 1
        return v
    clauses = []
    failed = []
    for net, (base, conns) in cone.items():
        c = gate_cnf(var(net), base, conns, var_of, aux_alloc)
        if c is None:
            failed.append((net, base))
        else:
            clauses.extend(c)
    nvars = next_aux[0] - 1
    if failed:
        print("UNMODELLED cone gates (cannot solve):", failed[:20])
        return
    clauses.append([var(target_net)])
    print(f"CNF: {nvars} vars ({len(var_of)} nets + aux), {len(clauses)} clauses")
    sol = dpll(clauses, nvars)
    if sol is None:
        print("DPLL: UNSAT — no assignment in the traced cone asserts success?!")
        print("(Possible cause: cone walk missed a driver, or success needs sequential state.)")
        return
    if sol == "budget":
        print("DPLL: decision budget exhausted — checker is not a simple comparator cone.")
        return
    inv = {v: k for k, v in var_of.items()}
    req = {inv[v]: val for v, val in sol.items()
           if inv.get(v) is not None and inv[v] in leaves}
    print("\nRequired leaf values for success==1:")
    for net in sorted(req):
        print(f"  {net} = {int(req[net])}")

    # ---- shift-chain classification ----
    # driver for D nets (comb only) to find mux(prev_Q, I) structure
    # (I may be aliased to an internal net, e.g. net_271 = I)
    i_nets = set(nl.get("input_aliases", {}).get("I", [])) | {"I"}
    q_to_ff = {q: conns for q, (_b, conns) in ff_info.items()}
    chain_next = {}   # prev Q net -> FF Q net whose D-path selects prev Q or I
    def d_sources(dnet, depth=0, seen=None):
        """Nets feeding dnet through muxes (followed recursively); for other
        gates only direct FF-Q / I inputs are reported, to avoid walking
        whole datapaths."""
        if seen is None:
            seen = set()
        if dnet in seen or depth > 6:
            return set()
        seen.add(dnet)
        cell = driver.get(dnet)
        if cell is None:
            return {dnet}
        base, conns = cell
        if base == "mux2":
            srcs = set()
            for p in ("A0", "A1"):
                srcs |= d_sources(conns[p], depth + 1, seen)
            return srcs
        srcs = set()
        for p, n in conns.items():
            if p in ("X", "Y") or p in POWER:
                continue
            if n in q_to_ff or n in i_nets:
                srcs.add(n)
        return srcs
    for q, conns in q_to_ff.items():
        d = conns.get("D")
        if d is None:
            continue
        srcs = d_sources(d)
        for s in srcs:
            if s in q_to_ff or s in i_nets:
                chain_next.setdefault(s, []).append(q)
    # walk chains starting at I (any of its alias nets)
    chains = []
    seen_q = set()
    starts = []
    for s in i_nets:
        starts.extend(chain_next.get(s, []))
    for start in starts:
        chain = [start]
        seen_q.add(start)
        cur = start
        while cur in chain_next:
            nxts = [n for n in chain_next[cur] if n not in seen_q]
            if len(nxts) != 1:
                break
            cur = nxts[0]
            chain.append(cur)
            seen_q.add(cur)
        chains.append(chain)
    print(f"\nshift chains found from I: {len(chains)}")
    for ch in chains:
        print(f"  chain length {len(ch)}: {ch[:4]} ... {ch[-2:] if len(ch) > 4 else ''}")
    key_ff = [q for ch in chains for q in ch]
    key_state = {q: int(req[q]) for q in key_ff if q in req}
    other_state = {q: int(req[q]) for q in ff_leaves if q not in key_ff and q in req}
    print(f"\nkey-register FFs in cone: {len(key_ff)}, with required values: {len(key_state)}")
    print("other (state/control) FF requirements:", other_state)
    out = {"netlist": path, "cone_gates": len(cone),
           "key_chains": chains, "required_state": {k: int(v) for k, v in req.items()}}
    with open(os.path.join(os.path.dirname(__file__), "trace_result.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote trace_result.json")
    if chains:
        for ci, ch in enumerate(chains):
            vals = [str(key_state.get(q, "?")) for q in ch]
            print(f"\nchain {ci} required register state (chain order): {''.join(vals)}")
            print(f"chain {ci} reversed: {''.join(vals[::-1])}")
            print("=> candidate serial keys (time order) are the above two strings;"
                  " verify_puzzle.py will test both.")

if __name__ == "__main__":
    main()
