#!/usr/bin/env python3
"""Parse ~/workspace/asic-puzzle-2026/example_inputs.vcd (Jane Street ASIC puzzle).

Extracts, at every rising clock edge:
  - rst_n, enable, I (sampled just before the edge)
  - O[7:0] and success (value just after the edge)
and reports timing structure: clock period, reset pulses, enable windows,
the I bitstream per enable window, and the O byte stream after each window.
Pure stdlib, no dependencies.
"""
import re
import sys
from pathlib import Path

VCD = Path.home() / "workspace/asic-puzzle-2026/example_inputs.vcd"

# VCD identifier codes from the header:
#   ! = clk, " = rst_n, # = enable, $ = I, % = O[7:0], & = success
ID = {"!": "clk", '"': "rst_n", "#": "enable", "$": "I", "%": "O", "&": "success"}

def parse(path):
    time = 0
    vals = {}          # signal -> current value (str), 'x' if unknown
    events = []        # (time_ps, signal, value) in file order
    for raw in open(path):
        line = raw.strip()
        if not line or line.startswith(("$", "#", "b")) and False:
            pass
        if line.startswith("#"):
            time = int(line[1:])
            continue
        m = re.match(r"^b([01xz]+)\s+(.)$", line)
        if m:
            events.append((time, ID[m.group(2)], m.group(1)))
            continue
        m = re.match(r"^([01xz])(.)$", line)
        if m:
            events.append((time, ID[m.group(2)], m.group(1)))
            continue
        # header / dumpvars / dumpall / $end etc: ignored
    return events

def main():
    events = parse(VCD)

    # --- clock edges -------------------------------------------------
    # clk starts 0 at t=0, rises at 5000ps, falls at 10000ps, ...
    clk_changes = [(t, v) for (t, s, v) in events if s == "clk"]
    rising = [t for (t, v) in clk_changes if v == "1"]
    falling = [t for (t, v) in clk_changes if v == "0"]
    periods = sorted({b - a for a, b in zip(rising, rising[1:])})
    print(f"clk: first rise {rising[0]} ps, {len(rising)} rising edges, "
          f"period(s) {periods} ps = {[p/1000 for p in periods]} ns")
    print(f"clk: falls at {[f for f in falling[:3]]} ... (every 10 ns)")

    # --- reconstruct signal values over time -------------------------
    # state just before each rising edge, and just after it
    timeline = {}  # signal -> sorted list of (time, value)
    for t, s, v in events:
        timeline.setdefault(s, []).append((t, v))

    def value_before(sig, t):
        val = "x"
        for tt, vv in timeline.get(sig, []):
            if tt < t:
                val = vv
            else:
                break
        return val

    def value_after(sig, t):
        val = "x"
        for tt, vv in timeline.get(sig, []):
            if tt <= t:
                val = vv
            else:
                break
        return val

    # --- rst_n transitions -------------------------------------------
    rst = [(t, v) for (t, s, v) in events if s == "rst_n"]
    print(f"\nrst_n transitions (time ps -> value): {rst}")
    for i in range(0, len(rst) - 1, 2):
        lo_t, hi_t = rst[i][0], rst[i + 1][0]
        n_edges = sum(1 for e in rising if lo_t <= e < hi_t)
        print(f"  reset pulse {lo_t}..{hi_t} ps = {(hi_t-lo_t)/1000} ns, "
              f"covers {n_edges} rising edges")

    # --- enable windows ----------------------------------------------
    en = [(t, v) for (t, s, v) in events if s == "enable"]
    print(f"\nenable transitions (time ps -> value): {en}")
    windows = []
    start = None
    for t, v in en:
        if v == "1" and start is None:
            start = t
        elif v == "0" and start is not None:
            windows.append((start, t))
            start = None
    if start is not None:
        windows.append((start, None))

    all_bits = []
    for wi, (ws, we) in enumerate(windows):
        edges = [e for e in rising if ws < e < we] if we else \
                [e for e in rising if ws < e]
        bits = "".join(value_before("I", e) for e in edges)
        all_bits.append(bits)
        print(f"\n=== enable window {wi+1}: {ws}..{we} ps "
              f"({(we-ws)/1000} ns), {len(edges)} rising edges, "
              f"{len(bits)} I bits ===")
        print(f"I bitstream (time order, 1 bit per rising edge):\n{bits}")
        print(f"  ones={bits.count('1')} zeros={bits.count('0')}")
        # group into bytes, both MSB-first and LSB-first
        for order in ("msb", "lsb"):
            byts = []
            for i in range(0, len(bits) - 7, 8):
                chunk = bits[i:i + 8]
                if order == "lsb":
                    chunk = chunk[::-1]
                byts.append(int(chunk, 2))
            txt = "".join(chr(b) if 32 <= b < 127 else "." for b in byts)
            print(f"  as bytes ({order}-first): {byts}")
            print(f"  as text  ({order}-first): {txt!r}")
        # O bytes streamed after the window ends (until next enable rise)
        nxt = windows[wi + 1][0] if wi + 1 < len(windows) else None
        o_edges = [e for e in rising if we < e and (nxt is None or e < nxt)]
        o_vals = []
        for e in o_edges:
            v = value_after("O", e)
            if v != "x":
                o_vals.append((e, v))
        # collapse consecutive duplicates (O only changes on some edges)
        seq = []
        for e, v in o_vals:
            if not seq or seq[-1][1] != v:
                seq.append((e, v))
        print(f"  O stream after window (edge time ps -> binary -> int -> char):")
        for e, v in seq:
            iv = int(v, 2) if set(v) <= {"0", "1"} else None
            ch = chr(iv) if iv is not None and 32 <= iv < 127 else ""
            print(f"    {e} ps: {v} = {iv} {ch!r}")
        # success over the whole window + stream phase
        succ = {value_after("success", e) for e in o_edges}
        succ_w = {value_before("success", e) for e in edges}
        print(f"  success during window: {sorted(succ_w)}, "
              f"during O stream: {sorted(succ)}")

    # --- success overall ---------------------------------------------
    succ_all = sorted({v for (t, s, v) in events if s == "success"})
    print(f"\nsuccess values seen anywhere in file: {succ_all}")
    print(f"total rising edges: {len(rising)}, "
          f"first {rising[0]} ps, last {rising[-1]} ps "
          f"({rising[-1]/1000} ns)")

    # --- window comparison -------------------------------------------
    if len(all_bits) == 2:
        print(f"\nwindow1 bits == window2 bits? {all_bits[0] == all_bits[1]}")
        if all_bits[0] != all_bits[1]:
            diff = [i for i, (a, b) in enumerate(zip(all_bits[0], all_bits[1]))
                    if a != b]
            print(f"  differing bit positions: {diff}")

    # --- I change times: do inputs move on falling edges only? -------
    i_changes = [t for (t, s, v) in events if s == "I"]
    off = [t for t in i_changes if t % 10000 != 0]
    print(f"\nI changes at {len(i_changes)} times; "
          f"not on a 10 ns grid: {off if off else 'none'}")

if __name__ == "__main__":
    main()
