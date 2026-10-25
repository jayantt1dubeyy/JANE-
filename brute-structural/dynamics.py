"""Dynamic structural analysis of the puzzle netlist.

Simulate the example protocol, record every FF's Q after each cycle, and
report:
1. O-byte stream + success for the two example runs (must be TRY AGAIN, 0)
   -- validates netlist + simulator against VCD ground truth.
2. At evaluation time, the 57 checker FFs (firstpass_state.json) vs the
   required pattern: Hamming distance for each example run.
3. Shift-link detection over the load window: FFs whose Q[t+1] equals
   another FF's Q[t] for (nearly) every load cycle, or equals I[t].
4. Which FFs move at all during the load window (load-path vs static).
"""
import sys, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from fastsim import FastSim
from verify_puzzle import RUN1, RUN2

PATH = "/home/hatch/workspace/asic-puzzle-2026/solution/puzzle_extracted.v"


def simulate(stream, sim, ff_qnets):
    """Run full protocol; return list of per-cycle snapshots (dict Q->val)
    and the O bytes after enable falls."""
    snaps = []
    def snap():
        return {q: sim.val[sim.net_index[q]] for q in ff_qnets}
    for _ in range(3):
        sim.cycle(rst_n=0, enable=0, I=0)
        snaps.append(snap())
    sim.cycle(rst_n=1, enable=0, I=0)
    snaps.append(snap())
    load_snaps = []
    for b in stream:
        sim.cycle(rst_n=1, enable=1, I=int(b))
        load_snaps.append(snap())
    eval_state = dict(load_snaps[-1])
    o_bytes = []
    success = False
    for _ in range(12):
        sim.cycle(rst_n=1, enable=0, I=0)
        if sim.read_output("success") == 1:
            success = True
        byte = 0
        for i in range(8):
            byte |= sim.read_output(f"O[{i}]") << i
        o_bytes.append(byte)
    return load_snaps, eval_state, success, o_bytes


def main():
    nl = parse_netlist(PATH)
    ff_qnets = []
    for base, conns in nl["instances"]:
        if base.startswith(("dfrtp", "dfstp", "dfxtp")):
            ff_qnets.append(conns["Q"])
    print(f"total FFs: {len(ff_qnets)}")
    req = json.load(open("firstpass_state.json"))
    print(f"checker FFs in required pattern: {len(req)}")

    sim = FastSim(nl)
    for name, stream in (("run1", RUN1), ("run2", RUN2)):
        load_snaps, eval_state, success, o_bytes = simulate(stream, sim, ff_qnets)
        txt = bytes(b for b in o_bytes if b).decode("ascii", "replace")
        print(f"\n{name}: success={success} O={txt!r}")
        diff = [q for q in req if eval_state.get(q) != req[q]]
        print(f"  checker FFs differing from required pattern: {len(diff)}/{len(req)}")
        print(f"  differing: {sorted(diff)[:20]}")
        # shift-link detection over load window
        n = len(load_snaps)
        qvals = {q: [s[q] for s in load_snaps] for q in ff_qnets}
        ivals = [int(b) for b in stream]
        links = []
        for q in ff_qnets:
            # Q[t+1] == I[t] ?
            if all(qvals[q][t + 1] == ivals[t] for t in range(n - 1)):
                links.append((q, "I"))
                continue
            for r in ff_qnets:
                if r == q:
                    continue
                if all(qvals[q][t + 1] == qvals[r][t] for t in range(n - 1)):
                    links.append((q, r))
                    break
        print(f"  shift links found (Q[t+1] == other Q[t] or I[t] every cycle): {len(links)}")
        for q, src in links:
            print(f"    {q} <- {src}")
        moved = [q for q in ff_qnets if len(set(qvals[q])) > 1]
        print(f"  FFs that move during load window: {len(moved)}")


if __name__ == "__main__":
    main()
