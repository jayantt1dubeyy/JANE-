# LVS extraction report — Jane Street ASIC puzzle 2026

Approach: KLayout's built-in netlist extractor (`LayoutToNetlist`), plus a
transistor-level spot-check of standard cells. This deliverable is an
**independent extraction** — it does not use or copy any other agent's netlist.
Nothing has been submitted anywhere.

## 0. Environment

- KLayout is **not** installed as a binary here, but the KLayout **Python
  package 0.30.12** lives in `~/workspace/.pydeps` and provides `pya`
  (including `LayoutToNetlist`, `DeviceExtractorMOS3Transistor`, `Netlist`,
  `NetlistWriter`). Use it with:
  `PYTHONPATH=/home/hatch/workspace/.pydeps python3 <script>`.
- Inputs: `~/workspace/asic-puzzle-2026/puzzle.gds` (1.4 MB),
  `warmup/00_source.v` … `warmup/04_final.gds`. SkyWater 130 nm, 1 DBU = 1 nm.

## 1. Method

### 1.1 Layers (REJS layer map)

| Layer | GDS layer/datatype | Role |
|---|---|---|
| li1 drawing | 67/20 | local interconnect |
| li1 pin labels | 67/5 | cell pin text |
| mcon | 67/44 | li1 ↔ met1 cuts |
| met1 | 68/20 | metal 1 (+ labels 68/5) |
| via1 | 68/44 | met1 ↔ met2 |
| met2 | 69/20 | metal 2 |
| via2 | 69/44 | met2 ↔ met3 |
| met3 | 70/20 | metal 3 (+ labels 70/5) |
| via3 | 70/44 | met3 ↔ met4 |
| met4 | 71/20 | metal 4 (+ labels 71/5) |
| via4 | 71/44 | met4 ↔ met5 |
| met5 | 72/20 | metal 5 (+ labels 72/5) |

The extractor is built from a `RecursiveShapeIterator(layout, top_cell,
[layer indexes])`, with polygon layers from `make_polygon_layer` and label
layers from `make_text_layer`. Inter-layer connectivity is the chain
li1–mcon–met1–via1–met2–via2–met3–via3–met4–via4–met5, plus
li1/met1/met3/met4/met5 ↔ their text layers. Top-level pins are created with
`netlist.make_top_level_pins()` (they are **not** created automatically).

### 1.2 The key fix: intra-layer `connect()` calls are REQUIRED

In KLayout 0.30's Python binding, `connect(a, b)` is inter-layer and
`connect(layer)` (single argument) is **intra-layer**: it merges touching
shapes on the same layer into one net. Without intra-layer connects, the
warmup extraction fragments into **1,642 nets with singleton nets** (e.g. 8×
lone `mux2 S` pins). With intra-layer connects on every layer, via cells
work as subcircuits as-is — **no via flattening is needed** (flattening was
tried: 1,099 → 230 top instances, and changed nothing once intra-layer
connects were present).

Other API facts learned (KLayout 0.30 binding): net identity across calls is
stable via `cluster_id`, **not** via Python object `id()`;
`SubCircuit.net_for_pin()` takes a pin id (`Pin.id`); `Pin.name` and
`Circuit.pin_count` are methods, not properties; there is no `layer()` method
on the extractor (use `make_polygon_layer` / `make_text_layer`).

### 1.3 Extraction script

`extract_puzzle.py` is the final deck (intra-layer + inter-layer connects,
label connects, `extract_netlist`, `make_top_level_pins`).
`export_puzzle.py` writes the Verilog/JSON outputs. Extraction takes ~0.3–1 s.

## 2. Warmup validation — EXACT structural match

Validated on `warmup/04_final.gds` against ground truth `warmup/01_netlist.v`
(`compare2.py`, `INTRA=1 FLAT=0`; output saved in
`warmup_validation_intra.txt`):

```
top pins: ['A', 'B', 'S', 'VGND', 'VPWR', 'clk', 'en', 'rst_n']
top nets: 89 | my nets: 84, gt nets: 84 | cellmatch: True | SIG EQUAL: True
```

- **79 logic cells, identical per-type counts** (16 dfrtp, 16 mux2, 8 nor2,
  7 and2, 5 xor2/or2/a31o, 4 nand2, 3 xnor2/clkbuf, 2 and4bb, 1 each of
  a21o/a21bo/a21boi/o21bai/and3).
- **84/84 net signatures identical** — each net compared as the multiset of
  connected (celltype, pin) pairs plus top-port markers, power pins dropped.
- All 8 top pins recovered. Top nets 89 = 84 logic + VPWR + VGND + 3 floating.
- Behavioural note: the ground-truth warmup netlist implements
  `success iff A + B == 496` by construction (two shift registers, adder,
  comparator, per the puzzle README/REJS writeup); the extracted netlist is
  structurally identical to it, so it implements the same function. No
  separate simulation run was done in this lane (simulation/SAT solving
  belongs to the solving agents, not the extraction).

## 3. Puzzle extraction results

Top cell `puzzle`, bbox (0, −52720; 200000, 300000) DBU
= 200 µm × 352.72 µm. Top instances **9,875**.

### 3.1 Top pins (15)

`I, O[0]–O[7], clk, enable, rst_n, success, VGND, VPWR` — matches the
expected 13 signal pads + 2 power.

### 3.2 Cell counts — 728 logic instances (EXACT match to expectation)

Top nets **729** = 724 logic nets + VPWR + VGND + 3 floating.
**Logic instances 728**, after excluding:

| Category | Count | Note |
|---|---|---|
| VIA cells | 8,221 | VIA_M1M2_PR 3154, VIA_L1M1_PR_MR 2696, VIA_via2_3 618, VIA_via3_4 618, VIA_via4_5 618, VIA_M2M3_PR 333, VIA_via5_6 108, VIA_M3M4_PR 69, VIA_M1M2_PR_MR 7 |
| tapvpwrvgnd_1 | 676 | well taps |
| decap_3 | 204 | decoupling |
| diode_2 | 10 | antenna diodes |
| INTERNAL_3 / INTERNAL_7 | 21 / 15 | see §3.4 |

Full census: `puzzle_census.json` (80 cell types at top level).
Logic cell histogram (top counts; 68 distinct logic types):
dfrtp_2 84, nor2_2 49, nand2_2 39, o21a_2 31, and2b_2 30, xnor2_2 29,
a31o_2 26, and3_2 26, inv_2 25, nand2b_2 24, a22o_2 23, xor2_2 21,
mux2_1 21, a21oi_2 20, a21o_2 19, or3_2 18, and2_2 17, clkbuf_8 16,
clkbuf_4 15, nand4_2 15, and4bb_2 14, or2_2 13, o211a_2 12, o31a_2 11,
or4_2 10, or4b_2 9, and4_2 8, plus the remaining types in the census file.

### 3.3 Comparison with the expected scale

| Quantity | Expected (REJS) | This extraction | Verdict |
|---|---|---|---|
| Functional cells | ~728 | **728** | exact |
| Nets | ~741 | **729** | **12-net (~1.6%) discrepancy, unexplained** |
| Instance pins | 2,791 | not counted in this lane | — |

The 729-vs-741 net discrepancy is stated honestly: the warmup exact match is
evidence favouring 729, but the gap is unresolved. Possible causes: REJS
under-merging (e.g. a stricter polygon-union rule splitting some nets), or
this extraction over-merging somewhere. Cross-check against the parallel
scripted polygon-union extraction is the way to close it; it is flagged for
the parent agent, not silently adjusted.

### 3.4 INTERNAL_3 / INTERNAL_7 are NOT logic

Each contains a single box on layer (200,0); all 36 are placed in one row at
y = −52.72 µm at the die's bottom edge, 1.38 µm and 4.14 µm wide × 2.72 µm
tall. They have no metal and no pins; the extractor correctly produces no
circuit/subcircuit for them (hence 9,839 subcircuits = 9,875 − 36). They are
filler/edge cells.

### 3.5 Driver sanity (strong)

- **719 logic nets have exactly 1 driver, 0 multi-driver nets (no shorts).**
- 5 zero-driver logic nets: `rst_n` (drives 4× dfstp SET_B + 84× dfrtp
  RESET_B — global async reset ✓), `I` (very wide fanout into combinational
  gates), `enable` (single and2b B pin — one control point), `clk`
  (clkbuf_16 A — clock root ✓), and **one anomaly: net 271** (§3.6).
- 16 single-logic-pin nets: 8 O outputs, enable, clk, 5 conb HI nets
  (conb_1 constant cells).
- Structural findings: `success` is driven by a dfrtp Q (registered output);
  O[0]–O[7] are each driven by an and3 X gate (8× and3 — plausibly the
  "output generator" region the README says to ignore at first, then simulate
  for the final answer).

### 3.6 Anomaly: undriven net 271

Net 271 feeds a31oi A1 (instance 210, x ≈ 177.56 µm, y ≈ 92.48 µm) and
a311o A1 (instance 587, x ≈ 181.70 µm, y ≈ 92.48 µm), plus 4 via pins
(2× VIA_M1M2_PR, 2× VIA_L1M1_PR_MR) that are just that net's own cross-layer
routing. Adding met6/via5 layers changed nothing (still 729 nets); the
VIA_via5_6 cell actually contains met4/met5/via4 shapes, not met5/met6 — so
no missing layer explains net 271. Candidates: a point-touch connection
missed by the extractor, or a genuinely floating puzzle input. Flagged for
cross-check against the parallel scripted extraction.

### 3.7 Floating nets (3)

Nets idx 126, 128, 146: large met2 meshes (596 / 470 / 300 shapes) spanning
roughly x 35–52 µm, y 35–52 µm, with no cell connections and no labels —
most likely dummy metal fill. No logic impact.

## 4. Transistor-level spot-check (nand2_2, nor2_2, inv_2)

### 4.1 Confirmed

- **Cell frame (all sky130 hd cells):** row height 2.72 µm; two (65,20)
  diffusion strips — lower y 235–885 (NMOS) and upper y 1485–2485 (PMOS,
  inside the (64,20) n-well box y 1305–2910); poly (66/20) stripes vertical,
  spanning y 105–2615, crossing both strips.
- **Poly stripe count = number of gate inputs:** nand2_2: 2, nor2_2: 2,
  inv_2: 1. (Poly stripes are comb-shaped with a narrowed neck at
  y 995–1325 where the gate-contact li1 boxes sit — bbox-only analysis is
  misleading; true polygon vertices were used.)
- **Transistor counts from poly×diffusion intersections — all correct:**
  nand2_2: 2 stripes × 2 strips = 4 transistors (2 NMOS + 2 PMOS) ✓;
  nor2_2: 2 × 2 = 4 ✓; inv_2: 1 × 2 = 2 ✓.
- **Pin/rail identification from labels:** nand2_2 — Y label on the
  cross-strip li1 polygon, A/B labels on the two gate-contact li1 boxes,
  VGND/VPWR on the met1 rails (mcon connects rails to the li1 rail
  polygons). Consistent with the cell names.

### 4.2 NOT resolved geometrically: series vs. parallel topology

The NAND-vs-NOR distinction (NMOS series + PMOS parallel for NAND, the
opposite for NOR) could **not** be read off plan-view geometry in this
session, and the report does not pretend otherwise:

- The li1 polygons are complex combs whose true-polygon overlap with the
  diffusion segments touches **multiple** segments per polygon (e.g. in
  nand2_2 one li1 polygon overlaps all three NMOS segments). Mere overlap
  therefore cannot be the li1↔diffusion contact rule — if it were, the cell
  would be shorted — so the contact-defining rule (which cut layer, if any,
  gates li1↔diffusion contact in this GDS) was not identified.
- The (66,44) boxes do not yield a clean segment map under any simple
  hypothesis tested (bbox overlap over-counts; true-polygon overlap via
  (66,44) boxes collapses every strip's segments onto a single li1 polygon).
- KLayout's `DeviceExtractorMOS3Transistor` (with SD = strip-minus-gate,
  G = strip∩poly, P = poly, per its own documented recipe) extracts devices
  but, with overlap-based SD↔li1 connectivity, over-merges nets (nand2_2
  came out as 8 devices with all terminals on one merged net) for the same
  reason. Script: `devcheck.py` (documents the failure mode; it is not a
  silent method switch — the gate-level LVS extraction in §2–§3 stands on
  its own).
- **Functional evidence instead:** the warmup exact-match validation (§2)
  proves the extracted connectivity of these very cell types reproduces the
  ground-truth netlist, whose Boolean function is fixed by construction.
  That, plus the confirmed stripe/transistor counts and label/rail
  identification, is the evidence that the cells function as named. A
  definitive transistor-level series/parallel proof would need the foundry
  contact rule or a device extraction with the correct contact layer, and
  is left as an open item.

## 5. Outputs in this directory

- `puzzle_lvs.v` — structural Verilog, 728 instances. Power pins
  (VPWR/VGND/VPB/VNB) and unnamed well pins dropped; O[i] port nets connected
  as bit-selects, not escaped wires. Behavioural models: standard
  SkyWater sky130_fd_sc_hd PDK cells.
- `puzzle_lvs.json` — instances with celltype, pin→net-index map, x/y in µm;
  top-port→net map; net names.
- `puzzle.lvsdb` — KLayout extraction database.
- `puzzle_census.json` — full top-level instance census (80 types).
- `warmup_validation_intra.txt` — reproduced warmup validation output.
- Scripts: `lvs_extract.py` (early deck), `extract_puzzle.py` (final puzzle
  deck), `export_puzzle.py`, `analyze_puzzle.py`, `compare2.py`
  (FLAT×INTRA warmup experiment — the validation script),
  `compare_warmup.py` / `compare_warmup_flat.py` (pre-fix variants, kept for
  the record: they show the fragmented pre-fix result),
  `diag271.py`, `diag271b.py` (net-271 investigation), `floatnets.py`
  (floating-net investigation), `spotcheck.py`, `devcheck.py`
  (transistor/device-extractor investigation, §4).

## 6. Limitations / open items for the parent agent

1. **729 vs 741 nets** — 12-net discrepancy vs REJS (§3.3); cross-check
   against the parallel scripted extraction.
2. **Net 271 undriven** (§3.6) — point-touch miss vs genuinely floating input.
3. **Series/parallel transistor topology** not geometrically resolved (§4.2).
4. No simulation, no SAT solving, no `example_inputs.vcd` replay in this
   lane — those belong to the solving agents. No submission made anywhere.
