"""Verify a candidate serial key against the puzzle netlist by simulating
the exact protocol from example_inputs.vcd:

  rst_n low 3 cycles -> rst_n high, 1 idle cycle -> enable high 121 cycles,
  clocking one I bit per cycle -> enable low -> observe success and O[7:0]
  for 12 cycles (O streams 1 byte/cycle on a pass or fail).

Also always runs the two example VCD streams as negative controls: a correct
netlist+simulator must show success==0 and O spelling 'TRY AGAIN' for both.

Usage: python3 verify_puzzle.py NETLIST [KEY]
  KEY: 121-char bitstring in time order (first char = first rising edge
  of the enable window). If omitted, only the controls are run.
"""
import sys, os
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist
from fastsim import FastSim

RUN1 = "0010101000000010110000101001100000000010000001110110000100101100001110011000000010110000001011100000000010000011001110000"
RUN2 = "1101011000010011110000000001000001000011000011101110000100001100001001011000000101110000110011100000000010000000000100000"


def run_protocol(sim, bits):
    """bits: iterable of 0/1, one per enable cycle. Returns (success_seen, o_bytes)."""
    # 3-cycle reset
    for _ in range(3):
        sim.cycle(rst_n=0, enable=0, I=0)
    # 1 idle cycle
    sim.cycle(rst_n=1, enable=0, I=0)
    # 121-cycle load window
    for b in bits:
        sim.cycle(rst_n=1, enable=1, I=int(b))
    # evaluate + stream
    o_bytes, success_seen = [], False
    for _ in range(12):
        sim.cycle(rst_n=1, enable=0, I=0)
        try:
            s = sim.read_output("success")
        except KeyError:
            s = 0
        if s == 1:
            success_seen = True
        byte = 0
        ok = True
        for i in range(8):
            try:
                byte |= sim.read_output(f"O[{i}]") << i
            except KeyError:
                ok = False
                break
        o_bytes.append(byte if ok else None)
    return success_seen, o_bytes


def main():
    if len(sys.argv) < 2:
        print("usage: verify_puzzle.py NETLIST [KEY]")
        return
    path = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else None
    nl = parse_netlist(path)
    print("inputs:", nl["inputs"], "outputs:", nl["outputs"])
    print("instances:", len(nl["instances"]))
    sim = FastSim(nl)

    print("\n-- negative controls (example VCD streams, must fail) --")
    for name, stream in (("run1", RUN1), ("run2", RUN2)):
        assert len(stream) == 121, len(stream)
        s, ob = run_protocol(sim, stream)
        txt = bytes(b for b in ob if b).decode("ascii", "replace") if ob[0] is not None else "(no O bus found)"
        print(f"{name}: success={s} O bytes={ob} text={txt!r}")

    if key is not None:
        print(f"\n-- candidate key ({len(key)} bits) --")
        print(key)
        s, ob = run_protocol(sim, key)
        txt = bytes(b for b in ob if b).decode("ascii", "replace") if ob and ob[0] is not None else "(no O bus found)"
        print(f"candidate: success={s} O bytes={ob} text={txt!r}")
        print("VERDICT:", "SUCCESS - key asserts success!" if s else "FAIL - key does not assert success")


if __name__ == "__main__":
    main()
