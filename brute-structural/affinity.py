"""Test whether the puzzle machine is affine over GF(2) in the 121 load
bits (fixed reset/idle prefix), and if so solve for the key directly.

f(s) = 57-bit checker state after the protocol with load stream s.
Affine means: f(a^b) == f(a) ^ f(b) ^ f(0) for all a,b.
If affine: build columns col_i = f(e_i) ^ f(0), solve M x = req ^ f(0)
over GF(2), and verify the resulting stream by full simulation.
"""
import sys, json, random
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from fastsim import FastSim
from verify_puzzle import run_protocol  # noqa: F401  (protocol helper lives here)

PATH = "/home/hatch/workspace/asic-puzzle-2026/solution/puzzle_extracted.v"
N = 121


def eval_state(sim, stream, checker):
    """Run protocol; return checker-state bits as int mask (bit j = checker[j])."""
    for _ in range(3):
        sim.cycle(rst_n=0, enable=0, I=0)
    sim.cycle(rst_n=1, enable=0, I=0)
    for b in stream:
        sim.cycle(rst_n=1, enable=1, I=int(b))
    mask = 0
    for j, q in enumerate(checker):
        mask |= sim.val[sim.net_index[q]] << j
    return mask


def bits_of(mask, n):
    return [(mask >> i) & 1 for i in range(n)]


def main():
    nl = parse_netlist(PATH)
    req = json.load(open("firstpass_state.json"))
    checker = sorted(req)
    req_mask = 0
    for j, q in enumerate(checker):
        req_mask |= req[q] << j
    sim = FastSim(nl)
    zero = "0" * N
    f0 = eval_state(sim, zero, checker)
    print(f"f(0) popcount: {bin(f0).count('1')}")
    random.seed(1234)
    ok = True
    for t in range(4):
        a = "".join(random.choice("01") for _ in range(N))
        b = "".join(random.choice("01") for _ in range(N))
        fa = eval_state(sim, a, checker)
        fb = eval_state(sim, b, checker)
        ab = "".join(str(int(x) ^ int(y)) for x, y in zip(a, b))
        fab = eval_state(sim, ab, checker)
        good = fab == (fa ^ fb ^ f0)
        print(f"affinity test {t}: {'PASS' if good else 'FAIL'}")
        ok &= good
    if not ok:
        print("Machine is NOT affine in the load bits -> fall back to z3 on the unrolled circuit.")
        return
    print("Machine IS affine. Building 121 columns (this takes ~1 min)...")
    cols = []
    for i in range(N):
        e = ["0"] * N
        e[i] = "1"
        fe = eval_state(sim, "".join(e), checker)
        cols.append(fe ^ f0)
    # Solve M x = req ^ f0 over GF(2). Rows = checker bits (57), cols = 121.
    target = req_mask ^ f0
    # Gaussian elimination on augmented rows: row j = sum_i M[j][i] x_i
    rows = []
    for j in range(len(checker)):
        row = 0
        for i in range(N):
            if (cols[i] >> j) & 1:
                row |= 1 << i
        rows.append([row, (target >> j) & 1])
    pivots = {}
    r = 0
    for c in range(N):
        piv = next((k for k in range(r, len(rows)) if (rows[k][0] >> c) & 1), None)
        if piv is None:
            continue
        rows[r], rows[piv] = rows[piv], rows[r]
        for k in range(len(rows)):
            if k != r and ((rows[k][0] >> c) & 1):
                rows[k][0] ^= rows[r][0]
                rows[k][1] ^= rows[r][1]
        pivots[c] = r
        r += 1
        if r == len(rows):
            break
    inconsistent = any(row == 0 and rhs == 1 for row, rhs in rows)
    print(f"rank: {len(pivots)} / {len(checker)} rows; inconsistent: {inconsistent}")
    if inconsistent:
        print("No stream produces the required pattern (pattern may be one of several, or unreachable).")
        return
    x = 0
    for c, rr in pivots.items():
        if rows[rr][1]:
            x |= 1 << c
    key = "".join(str((x >> i) & 1) for i in range(N))
    print(f"candidate key (time order): {key}")
    # verify by full simulation
    sim2 = FastSim(nl)
    fkey = eval_state(sim2, key, checker)
    print(f"candidate reproduces required pattern: {fkey == req_mask}")
    with open("affine_key.txt", "w") as fh:
        fh.write(key + "\n")
    print("wrote affine_key.txt")


if __name__ == "__main__":
    main()
