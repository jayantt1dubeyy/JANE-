# Jane Street ASIC puzzle 2026 — brute-force + structural-tracing approach

## RESULT (verified by full simulation)

**Key (121 bits, time order — first bit = first rising edge of the enable window):**

```
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

**Protocol:** 3-cycle reset (`rst_n` low) → 1 idle cycle → `enable` high for
121 cycles, clocking one key bit per cycle on `I` → `enable` low.

**Outcome on the extracted netlist (`solution/puzzle_extracted.v`):**
- `success` goes high and **stays high** (latched) for all 40 observed
  post-enable cycles.
- `O[7:0]` streams the flag: **`(* TWO STARS *)`** followed by NUL.
- Single-bit flips at positions 0, 60, and 120 all fail with `TRY AGAIN` —
  the key is exact, not a near-miss.

## Warmup proof (both methods validated before touching the puzzle)

Netlist: `warmup/01_netlist.v` (76 logic instances; simulator built in
pure Python — no iverilog in this sandbox).

### (a) Brute-force simulation
- Full serial protocol per (A, B) pair: reset, then 8 shift cycles
  (MSB first) with `en` high, then read `S`.
- All 65,536 pairs swept in 52.5 s: exactly **15** success pairs, and they
  are exactly the pairs with **A + B == 496**
  (241+255, 242+254, …, 255+241). Spot checks: (100,100)→S=0, (250,246)→S=1.

### (b) Structural trace
- Backward cone walk from `S`: 44 gates; leaves exactly `a_reg[7:0]`,
  `b_reg[7:0]`.
- Forcing every (a_reg, b_reg) combination into the cone: S asserts for
  exactly the 15 pairs above; the sum across asserting pairs is uniquely
  **496** — the compared constant read off the structure.
- A small DPLL solver over the cone's definitional CNF independently
  returns an assignment with a + b == 496 (e.g. 248 + 248).

## Puzzle: what the circuit turned out to be

- The extracted netlist has **728 instances, 92 flip-flops** (84 dfrtp,
  4 dfstp, 4 dfxtp). `success` is a **registered** output (Q of a dfrtp,
  D = `net_87`).
- The success FF's D-cone is only **47 gates over 57 FF leaves** — the
  checker is a pure function of 57 state bits (plus a latch term on the
  success bit itself, which is why success stays high once set).
- Forcing `success`-current = 0 gives the genuine first-pass condition:
  a unique 57-bit required evaluation-time state
  (`firstpass_state.json`). Uniqueness was not assumed — the DPLL
  assignment is the first-pass pattern; the key below reproduces it.
- There is **no 121-bit shift register**: only 92 FFs exist. Dynamic
  analysis (simulating the example protocol and watching FFs) shows an
  11-bit shift window fed by `I` (`net_1230 <- I <- ... <- net_1218`,
  holding the last 11 input bits) feeding a nonlinear state machine
  (affinity test over GF(2) **fails** — the machine is not linear, so no
  linear-algebra shortcut exists; brute force over 2^121 is impossible).
- The key was therefore obtained by an unrolled SAT solve over the
  cone of influence of the success D net (57,333 (net, step) pairs,
  `zsolve.py`, z3) and then **verified by simulation**, not trusted
  from the solver. The structural trace (checker pattern) and the SAT
  result agree through the simulation check.

## The bug that almost sank the verification (read this)

The first z3 candidate **failed** in simulation, and differential
checking (z3 model vs simulator, step by step, `diffcheck.py`) traced the
divergence to a single cell type: **`o2bb2a`**. My Python cell model had
`X = (A1_N | A2_N) & (B1 | B2)`, but the PDK functional model is:

```
nand nand0 (nand0_out, A2_N, A1_N);   // !(A1_N & A2_N)
or   or0   (or0_out, B2, B1);
and  and0  (X, nand0_out, or0_out);    // X = !(A1_N&A2_N) & (B1|B2)
```

i.e. the `_N` pins feed the NAND **directly**, not inverted first.
The z3 model (group-based) had it right; the Python simulator had it
wrong. Every other `_N` cell was checked against its PDK primitives
and confirmed correct (several only via De Morgan equivalence).
After fixing `gsim.py`, `diffcheck.py` reports **zero divergence over
steps 0–122** and the z3 key verifies: success = 1, flag out.

## Negative controls (simulator + netlist validated against ground truth)

Both example VCD streams, simulated on the extracted netlist, give
`success = 0` and `O = TRY AGAIN` — exactly matching `example_inputs.vcd`.
The key above is the only tested stream that flips this to success.

## Files in this directory

- `gsim.py` — structural Verilog parser + sky130 cell models + simulator
- `fastsim.py` — compiled index-based fast simulator (used for sweeps)
- `brute_warmup.py`, `trace_warmup.py` — warmup proofs (methods a, b)
- `trace_puzzle.py` — success-D cone walk + DPLL read-off
- `trace_firstpass.py`, `firstpass_state.json` — first-pass checker pattern
- `dynamics.py` — load-window FF dynamics, shift-link detection
- `affinity.py` — GF(2) affinity test (negative: machine is nonlinear)
- `zsolve.py` — unrolled z3 solve over the success-D cone of influence
- `z3_key.txt` — the verified 121-bit key
- `diffcheck.py` — step-by-step z3-vs-simulator differential check
- `verify_puzzle.py` — full-protocol verifier + example-stream controls
- `trace_puzzle_out.txt`, `trace_result.json` — raw trace outputs

## Nothing submitted anywhere

No solution, key, or flag was sent to Jane Street or any other party.
This directory is a local verification record only.
