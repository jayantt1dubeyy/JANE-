# Example-waveform analysis — Jane Street ASIC puzzle 2026

Source: `~/workspace/asic-puzzle-2026/example_inputs.vcd`, parsed with
`parse_vcd.py` in this directory (pure stdlib; run it to reproduce every
number below). Timescale is 1 ps; all times below are in ns unless noted.
`success` is `x` at t = 0 and `0` from the first clock edge onward — it
**never goes high** in this file, confirming these are example inputs,
not a solution.

## 1. Timing table (verified from the file, not from the REJS writeup)

| Quantity | Value | Evidence |
|---|---|---|
| Clock period | **10 ns (100 MHz)**, 50% duty | Rises every 10 ns: 5, 15, 25, … 3115 ns; 312 rising edges total |
| Clock first rise | 5 ns | `clk` = 0 at t = 0, rises at 5000 ps |
| Reset pulse 1 | 0 → 30 ns, covers **3 rising edges** (5, 15, 25 ns) | `rst_n` 0 at t = 0, rises at 30000 ps |
| Reset pulse 2 | 1560 → 1590 ns, covers **3 rising edges** (1565, 1575, 1585 ns) | `rst_n` falls at 1560000 ps, rises at 1590000 ps |
| Enable window 1 | 40 → 1250 ns = **1210 ns = 121 rising edges** (45 … 1245 ns) | `enable` rises at 40000 ps, falls at 1250000 ps |
| Enable window 2 | 1600 → 2810 ns = **1210 ns = 121 rising edges** (1605 … 2805 ns) | `enable` rises at 1600000 ps, falls at 2810000 ps |
| Idle gap between runs | O stream ends 1345 ns; reset pulse at 1560 ns | — |
| Post-run idle | File ends at 3120 ns; last O byte at 2905 ns | 21 idle cycles after run 2 |

### Check against the REJS writeup's claims

- "rst_n stays low for the first 3 clock cycles, then goes high" — **confirmed**,
  and it happens **twice** (a second identical 3-cycle pulse precedes run 2).
- "enable goes high at 40 ns and stays high for 121 cycles until 1250 ns,
  then drops and O[7:0] is streamed" — **confirmed exactly** for window 1,
  and window 2 is a perfect repeat of the same shape (1600 → 2810 ns, 121 cycles).
- The writeup's summary understates the file: it contains **two full runs**,
  not one, each with its own reset + load window + output stream.

### Sampling convention (why rising-edge sampling is the right read)

`I` changes **only** on the 10 ns grid, i.e. exactly at falling-clock-edge
times (the parser confirms: zero `I` changes off-grid). A testbench that
moved inputs on the sampling edge would race, so the design almost
certainly samples `I` on rising edges. Each enable window therefore loads
exactly **121 bits**, one per rising edge. (If the design sampled on
falling edges instead, the stream would be the same bits shifted by half a
cycle — the bit *count* and the protocol below are unaffected.)

### Fixed phase relationship

Both runs follow the same skeleton, one cycle apart at each step:

```
rst_n low 3 cycles → rst_n high → 1 idle cycle → enable high 121 cycles
→ enable low → O streams 1 byte/cycle for 10 cycles → idle
```

Run 1: reset 0–30 ns, enable 40–1250 ns, O stream 1255–1345 ns.
Run 2: reset 1560–1590 ns, enable 1600–2810 ns, O stream 2815–2905 ns.

## 2. The I bitstreams (time order, first bit = first rising edge of the window)

### Run 1 (121 bits, 38 ones / 83 zeros)

```
0010101000000010110000101001100000000010000001110110000100101100001110011000000010110000001011100000000010000011001110000
```

### Run 2 (121 bits, 38 ones / 83 zeros)

```
1101011000010011110000000001000001000011000011101110000100001100001001011000000101110000110011100000000010000000000100000
```

The two streams differ in 30 bit positions. They are **not** related by
reversal, complement, rotation, or a one-bit shift (all checked).

### Structure tests on the I streams (all negative)

- As bytes, MSB-first or LSB-first, full 121 bits or either 120-bit
  framing (drop first or last bit): **no ASCII text**. Sample decodes —
  run 1 MSB-first: `2A 02 C2 98 02 07 61 2C 39 80 B0 2E 00 83 38`
  (`*.....a,9.....8`); run 1 LSB-first: `54 40 43 19 40 E0 86 34 9C 01
  0D 74 00 C1 1C` (`T@C.@..4...t...`). Run 2 is likewise non-text in all
  four framings. The `T`/`a` bytes that appear are single-byte
  coincidences, not messages.
- No counter, no repeated byte pattern, no periodicity. Longest zero runs
  are 9–10 bits; longest one runs are 3–4 bits — sparse, irregular data.
- **The one real structural clue: both streams have popcount exactly 38.**
  For uniform random 121-bit strings the mean popcount is 60.5 with
  σ ≈ 5.5, so 38 is ~4σ low — twice in a row is not what uniform random
  guesses look like. This suggests the example inputs were generated with
  a zero-biased or fixed-weight process (e.g. sparse random keys, or a
  generator with a set bit density), *not* that the streams encode text.
  Treat this as a weak hint about how Jane Street generated the examples,
  not as information about the true key.

Conclusion: the example `I` streams look like **two plausible-but-wrong
key guesses** — same length, same format, different bits, both rejected.
They are not a test pattern (no counting/ASCII structure) and not the key
(success stays 0 for both).

## 3. O[7:0] trace — identical after both runs

One byte per rising edge, starting on the first rising edge after `enable`
falls (5 ns later), then `O` returns to 0:

| Cycle after enable falls | Run 1 (ns) | Run 2 (ns) | Binary | Value | Char |
|---|---|---|---|---|---|
| 1 | 1255 | 2815 | 1010100 | 84 | T |
| 2 | 1265 | 2825 | 1010010 | 82 | R |
| 3 | 1275 | 2835 | 1011001 | 89 | Y |
| 4 | 1285 | 2845 | 100000 | 32 | (space) |
| 5 | 1295 | 2855 | 1000001 | 65 | A |
| 6 | 1305 | 2865 | 1000111 | 71 | G |
| 7 | 1315 | 2875 | 1000001 | 65 | A |
| 8 | 1325 | 2885 | 1001001 | 73 | I |
| 9 | 1335 | 2895 | 1001110 | 78 | N |
| 10 | 1345 | 2905 | 0 | 0 | NUL terminator |

(VCD omits leading zeros, so e.g. `1010100` is the 8-bit value `01010100`.)

The failure message is therefore **`TRY AGAIN\0`**, streamed from what
looks like a fixed ROM. On a successful run the output generator
(the region the puzzle README says to ignore at first, then simulate)
presumably streams something else instead — most plausibly the flag —
and `success` goes high. That is exactly what the netlist/SAT approaches
must confirm; the VCD alone cannot show it.

## 4. Protocol hypothesis

**Evidence (from the file itself):**
1. Two complete, identically shaped runs: 3-cycle reset → 1 idle cycle →
   121-cycle `enable` window → 10-cycle byte stream on `O`.
2. `I` changes only between rising edges, so one bit is consumed per
   rising edge while `enable` is high: **121 bits per run**.
3. `O` is silent during the load window and streams only after `enable`
   falls — evaluation happens at/after the falling edge of `enable`.
4. Both runs produce the identical failure message, so the output does
   not depend on *which* wrong key was entered, only on pass/fail.
5. The chip is re-runnable: reset + reload gives a second independent
   attempt with no leftover state visible in the outputs.

**Hypothesis (inference, not evidence):**
- The chip is a **serial-key lock**: while `enable` is high it shifts
  `I` into a 121-bit register; when `enable` falls it checks the register
  (against a stored key, or through some function of it); on match it
  asserts `success` and streams the secret via `O`, on mismatch it
  streams `TRY AGAIN\0`.
- The expected key is therefore most likely a **121-bit value**
  (or 120 bits plus one framing/control bit — e.g. the first or last
  clocked bit may be a start/stop bit rather than key material).
- Bit order (MSB-first vs LSB-first into the register) **cannot** be
  determined from this file; the netlist extraction must settle it.

**What this file cannot tell you:**
- The correct key (both examples fail; no partial-credit signal in `O`
  distinguishes "close" from "far" — the output is identical for both
  wrong guesses, so there is no oracle gradient to climb).
- Whether the check is a plain equality compare or a more complex
  function (hash, arithmetic, state machine) of the 121 bits.
- What `success` does on a pass (level vs pulse, timing) or what bytes
  `O` streams on a pass.

## 5. What this means for the other solving approaches

- **For the netlist/SAT approach:** the target is now sharply defined —
  find a 121-bit serial input (plus the 3-cycle reset and 121-cycle
  enable framing) that makes `success` = 1. Any candidate solution must
  reproduce this exact skeleton: reset 3 cycles, `enable` high exactly
  121 cycles while clocking the bits, then `enable` low. A SAT model
  should constrain the input to this framing rather than searching over
  arbitrary waveforms.
- **For the structural-tracing approach:** trace back from `success`
  through the compare logic; the register feeding it should be ~121 bits
  wide, and the constant it compares against (if it is a plain compare)
  is the key.
- **For the by-eye/KLayout approach:** the two identical run shapes
  confirm the chip is a small state machine (reset → load → evaluate →
  stream), not a free-running datapath — the interesting logic is the
  load register, the checker, and the output ROM.

## Reproduction

```
python3 parse_vcd.py          # prints timing, bitstreams, O trace
python3 parse_vcd.py > parse_output.txt   # full output saved alongside
```
