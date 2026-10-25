"""Differential check: z3 unrolled model vs Python simulator, step by step,
for a fixed input stream. Finds the first step where the two models diverge
and names the disagreeing FFs, so a gate-model mismatch can be pinpointed.

Usage: python3 diffcheck.py [KEYFILE]  (default: z3_key.txt)
"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from fastsim import FastSim
from zsolve import build_model, PATH

import z3


def main():
    keyfile = sys.argv[1] if len(sys.argv) > 1 else "z3_key.txt"
    key = open(keyfile).read().strip()
    assert len(key) == 121, len(key)
    nl = parse_netlist(PATH)
    m = build_model(nl)
    s, V, i_bits = m["solver"], m["V"], m["i_bits"]
    for b, bit in zip(i_bits, key):
        s.add(b == (bit == "1"))
    r = s.check()
    print("z3 with fixed key:", r)
    assert r == z3.sat
    mod = s.model()

    def zval(net, step):
        # Step-0 FF values are constants in the model (expr() returns BoolVal
        # for them); V(net, 0) variables are unconstrained and meaningless.
        if step == 0 and net in m["ff"]:
            return 1 if m["ff"][net][0] == "dfstp" else 0
        v = V(net, step)
        return 1 if z3.is_true(mod.eval(v)) else 0

    # simulator snapshots: sim_step s == z3 step s
    sim = FastSim(nl)
    ff_qnets = [q for q, (_k, _d, _r) in m["ff"].items()]
    snaps = {}
    for _ in range(3):
        sim.cycle(rst_n=0, enable=0, I=0)
    # z3 step 0 = post-reset state: snapshot FFs right after reset cycles
    snaps[0] = {q: sim.val[sim.net_index[q]] for q in ff_qnets}
    sim.cycle(rst_n=1, enable=0, I=0)
    snaps[1] = {q: sim.val[sim.net_index[q]] for q in ff_qnets}
    for k, b in enumerate(key):
        sim.cycle(rst_n=1, enable=1, I=int(b))
        snaps[k + 2] = {q: sim.val[sim.net_index[q]] for q in ff_qnets}
    # eval-time D (comb from post-load state + eval inputs)
    sim.set_inputs(rst_n=1, enable=0, I=0)
    sim_d = sim.val[sim.net_index["net_87"]]
    z_d = zval("net_87", 122)
    print(f"eval D: simulator={sim_d} z3={z_d}")

    # Only compare FFs that are actually in the z3 model's cone of influence
    # at that step; others are unconstrained in z3 and any mismatch there
    # is an artifact, not a real divergence.
    needed = m["needed"]
    first_bad = None
    for step in range(0, 123):
        bad = [q for q in ff_qnets
               if (q, step) in needed and snaps[step][q] != zval(q, step)]
        if bad:
            first_bad = (step, bad)
            break
    if first_bad is None:
        print("No divergence in FF states over steps 0..122.")
        print("If success still disagrees, the issue is eval timing, not gates.")
        return
    step, bad = first_bad
    print(f"FIRST DIVERGENCE at step {step}: {len(bad)} FFs differ")
    for q in bad[:15]:
        kind, d, _r = m["ff"][q]
        print(f"  {q} ({kind}): sim={snaps[step][q]} z3={zval(q, step)} D={d}")
        # show the D gate driving it at step-1
        cell = m["driver"].get(d)
        print(f"    D driver: {cell[0] if cell else None} {cell[1] if cell else ''}")


if __name__ == "__main__":
    main()
