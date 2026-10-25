#!/usr/bin/env python3
"""Verify an extracted netlist against example_inputs.vcd (the golden
waveform recorded from the real chip).

For every rising clock edge in the VCD:
  - inputs  = signal values just before the edge (changes strictly before
              the edge timestamp; input changes never coincide with edges
              in this file, verified during parsing),
  - outputs = signal values just after the edge (all changes at the edge
              timestamp applied).
The simulator is driven with those inputs and its post-edge outputs are
compared with the VCD's post-edge outputs (success, O[7:0]).
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulate import Circuit, run_cycles
from cells import Ops

CODE2NAME = {}


def parse_vcd(path):
    code2name = {}
    timescale = None
    changes = []  # (time, name, value); value: int for buses, 0/1/'x' for bits
    time = 0
    in_header = True
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if in_header:
                m = re.match(r"\$var\s+\S+\s+(\d+)\s+(\S+)\s+(.+?)\s*\$end", line)
                if m:
                    width, code, name = int(m.group(1)), m.group(2), m.group(3).strip()
                    code2name[code] = (name, width)
                    continue
                m = re.match(r"\$timescale\s+(\S+)", line)
                if m:
                    timescale = m.group(1)
                    continue
                if line.startswith("$enddefinitions"):
                    in_header = False
                continue
            if line.startswith("#"):
                time = int(line[1:])
                continue
            if line.startswith("$"):
                continue
            if line.startswith("b"):
                m = re.match(r"b([01xXzZ]+)\s+(\S+)", line)
                val_s, code = m.group(1), m.group(2)
                name, width = code2name[code]
                val = None if "x" in val_s.lower() or "z" in val_s.lower() else int(val_s, 2)
                changes.append((time, name, val))
            elif len(line) >= 2 and line[0] in "01xXzZ":
                val = None if line[0] in "xXzZ" else int(line[0])
                code = line[1:]
                name, width = code2name[code]
                changes.append((time, name, val))
    return timescale, changes


def value_before(changes_by_sig, name, t):
    """Value just before time t (last change with time < t)."""
    val = None
    for time, v in changes_by_sig[name]:
        if time < t:
            val = v
        else:
            break
    return val


def value_at(changes_by_sig, name, t):
    """Value just after time t (last change with time <= t)."""
    val = None
    for time, v in changes_by_sig[name]:
        if time <= t:
            val = v
        else:
            break
    return val


def main():
    json_path, vcd_path = sys.argv[1:3]
    data = json.load(open(json_path))
    circ = Circuit(data)
    print("circuit: %d comb, %d FF, undriven nets: %s"
          % (len(circ.comb), len(circ.ffs), sorted(circ.undriven)))
    timescale, changes = parse_vcd(vcd_path)
    print("VCD timescale:", timescale, "changes:", len(changes))
    by_sig = {}
    for time, name, val in changes:
        by_sig.setdefault(name, []).append((time, val))
    # posedges: clk 0 -> 1
    clk_hist = by_sig["clk"]
    posedges = []
    prev = None
    for time, v in clk_hist:
        if prev == 0 and v == 1:
            posedges.append(time)
        prev = v
    print("posedges:", len(posedges))
    # sanity: no input change coincides with a posedge timestamp
    edge_set = set(posedges)
    for sig in ("rst_n", "enable", "I"):
        bad = [t for t, v in by_sig[sig] if t in edge_set]
        print("input %s changes on edge timestamps: %d" % (sig, len(bad)))
    cycles = []
    for t in posedges:
        cycles.append({
            "rst_n": bool(value_before(by_sig, "rst_n", t)),
            "enable": bool(value_before(by_sig, "enable", t)),
            "I": bool(value_before(by_sig, "I", t)),
        })
    ops = Ops(False)
    results, _ = run_cycles(circ, ops, cycles)
    mism = 0
    first = []
    for k, (t, out) in enumerate(zip(posedges, results)):
        exp_s = value_at(by_sig, "success", t)
        exp_o = value_at(by_sig, "O [7:0]", t)
        got_s = 1 if out["success"] else 0
        got_o = out["O"]
        if exp_s is not None and exp_s != got_s:
            mism += 1
            if len(first) < 10:
                first.append((k, t, "success", exp_s, got_s))
        if exp_o is not None and exp_o != got_o:
            mism += 1
            if len(first) < 10:
                first.append((k, t, "O", exp_o, got_o))
    print("edges checked:", len(posedges), "mismatches:", mism)
    for row in first:
        print("  MISMATCH edge", row[0], "t=%d" % row[1], row[2],
              "expected", row[3], "got", row[4])
    # decode O stream per run for the report
    runs = []
    cur = []
    for k, out in enumerate(results):
        if out["O"] != 0:
            cur.append(out["O"])
        elif cur:
            runs.append(bytes(cur).decode("ascii", "replace"))
            cur = []
    if cur:
        runs.append(bytes(cur).decode("ascii", "replace"))
    print("O streams decoded:", runs)
    print("VERDICT:", "PASS" if mism == 0 else "FAIL")


if __name__ == "__main__":
    main()
