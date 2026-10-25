"""Refine the structural trace: the success FF's D depends on its own Q
(net_66) — a latch path. Force success-current == 0 so the solver returns
the genuine first-pass checker condition (not the latched branch), then
print the required evaluation-time FF state.
"""
import sys, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from trace_puzzle import build_cone, gate_cnf, dpll

PATH = "/home/hatch/workspace/asic-puzzle-2026/solution/puzzle_extracted.v"


def main():
    nl = parse_netlist(PATH)
    cone, leaves, driver, ff_info = build_cone(nl, target="net_87")  # D of success FF
    print(f"D cone: {len(cone)} gates, {len(leaves)} FF leaves")
    var_of = {}

    def var(n):
        if n not in var_of:
            var_of[n] = len(var_of) + 1
        return var_of[n]
    for n in cone:
        var(n)
    for n in leaves:
        var(n)
    nxt = [len(var_of) + 1]

    def aux():
        v = nxt[0]
        nxt[0] += 1
        return v

    clauses = []
    for net, (base, conns) in cone.items():
        c = gate_cnf(var(net), base, conns, var_of, aux)
        assert c is not None, base
        clauses.extend(c)
    clauses.append([var("net_87")])    # D == 1
    clauses.append([-var("net_66")])   # success currently 0 (first pass)
    sol = dpll(clauses, nxt[0] - 1)
    assert isinstance(sol, dict), sol
    inv = {v: k for k, v in var_of.items()}
    req = {inv[v]: int(val) for v, val in sol.items() if inv.get(v) in leaves}
    print(f"required evaluation-time state: {len(req)} FFs")
    for net in sorted(req):
        print(f"  {net} = {req[net]}")
    with open("firstpass_state.json", "w") as f:
        json.dump(req, f, indent=1, sort_keys=True)
    print("wrote firstpass_state.json")
    # which FFs are NOT in the checker cone (load path / output generator)?
    all_q = set(ff_info)
    print(f"FFs outside checker cone: {len(all_q - set(leaves))}")
    print("  ", sorted(all_q - set(leaves)))


if __name__ == "__main__":
    main()
