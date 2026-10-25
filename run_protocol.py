#!/usr/bin/env python3
"""Feed a 121-bit key through the extracted netlist using the VCD-aligned
protocol and print success + the streamed O bytes.

Usage: run_protocol.py <netlist.json> <key_bits> [undriven_value]
  key_bits: 121 characters of 0/1, first char = first bit on I.
  undriven_value: 0 or 1 for the layout-undriven net (default 0).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulate import Circuit, run_cycles, protocol_cycles
from cells import Ops


def main():
    json_path, key = sys.argv[1:3]
    undriven_val = bool(int(sys.argv[3])) if len(sys.argv) > 3 else False
    assert len(key) == 121 and set(key) <= {"0", "1"}, "key must be 121 bits"
    data = json.load(open(json_path))
    circ = Circuit(data)
    bits = [c == "1" for c in key]
    cycles = protocol_cycles(bits, n_stream=16)
    ops = Ops(False)
    results, _ = run_cycles(circ, ops, cycles, undriven_value=undriven_val)
    # cycles: 0-2 reset, 3 gap, 4-124 shift, 125+ stream
    print("cycle: success O")
    stream = []
    for k in range(125, 125 + 16):
        out = results[k]
        print("%d: %d 0x%02x %r" % (k, 1 if out["success"] else 0, out["O"],
                                    chr(out["O"]) if 32 <= out["O"] < 127 else "."))
        stream.append(out["O"])
    text = bytes(b for b in stream if b != 0).decode("ascii", "replace")
    print("streamed text:", repr(text))
    print("success asserted during stream:",
          all(results[k]["success"] for k in range(125, 141)))


if __name__ == "__main__":
    main()
