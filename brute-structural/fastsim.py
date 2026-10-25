"""Compiled fast gate-level simulator (same models as gsim.py).

Nets become integer indices, gates become (out_idx, fn, [in_idx...]) tuples
evaluated over a plain list. One levelized pass settles combinational logic,
so a clock cycle costs two passes. Used for brute-force sweeps where the
dict-based Sim is too slow.
"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gsim import parse_netlist, CELL_MODELS


class FastSim:
    def __init__(self, netlist):
        self.nl = netlist
        self.net_index = {}
        self.names = []

        def idx(net):
            if net not in self.net_index:
                self.net_index[net] = len(self.names)
                self.names.append(net)
            return self.net_index[net]

        for p in netlist["inputs"]:
            idx(p)
        raw_comb, self.ffs = [], []
        for base, conns in netlist["instances"]:
            if base.startswith("dfrtp") or base.startswith("dfstp") or base.startswith("dfxtp"):
                self.ffs.append((idx(conns["CLK"]), idx(conns["D"]), idx(conns["Q"]),
                                 idx(conns["RESET_B"]) if "RESET_B" in conns else None,
                                 idx(conns["SET_B"]) if "SET_B" in conns else None))
            elif base.startswith("conb"):
                for net in conns.values():
                    idx(net)
                continue
            elif any(base.startswith(p) for p in ("tap", "decap", "diode", "fill")):
                continue
            else:
                out_port, fn = CELL_MODELS[base]
                ins = [(port, idx(net)) for port, net in conns.items()
                       if port != out_port and port not in ("VPWR", "VGND", "VPB", "VNB")]
                raw_comb.append((idx(conns[out_port]), fn, ins, conns))
        # levelize: order gates so all driver inputs are computed first
        driven = {g[0] for g in raw_comb}
        known = set(self.net_index[p] for p in netlist["inputs"])
        known |= {q for _c, _d, q, _r, _s in self.ffs}
        ordered, remaining = [], raw_comb
        while remaining:
            nxt, prog = [], False
            for g in remaining:
                if all(i in known or i not in driven for _p, i in g[2]):
                    ordered.append(g)
                    known.add(g[0])
                    prog = True
                else:
                    nxt.append(g)
            if not prog:
                ordered.extend(nxt)
                break
            remaining = nxt
        # precompile: (out_idx, fn, [in_idx in port order]) with port-name lookup
        self.gates = []
        for out_i, fn, ins, conns in ordered:
            # fn expects a dict keyed by port name; build a small closure
            port_order = [p for p, _i in ins]
            in_idx = [i for _p, i in ins]
            self.gates.append((out_i, fn, port_order, in_idx))
        self.val = [0] * len(self.names)
        # constant nets (conb)
        for base, conns in netlist["instances"]:
            if base.startswith("conb"):
                for port, net in conns.items():
                    if port == "HI":
                        self.val[idx(net)] = 1
                    elif port == "LO":
                        self.val[idx(net)] = 0

    def settle(self):
        v = self.val
        for out_i, fn, port_order, in_idx in self.gates:
            args = {p: v[i] for p, i in zip(port_order, in_idx)}
            v[out_i] = fn(args) & 1

    def set_inputs(self, **kw):
        v = self.val
        for k, val in kw.items():
            v[self.net_index[k]] = val & 1
            for alias in self.nl.get("input_aliases", {}).get(k, []):
                if alias in self.net_index:
                    v[self.net_index[alias]] = val & 1
        for _c, _d, q, r, s in self.ffs:
            if r is not None and v[r] == 0:
                v[q] = 0
            elif s is not None and v[s] == 0:
                v[q] = 1
        self.settle()

    def clock_edge(self):
        v = self.val
        updates = []
        for _c, d, q, r, s in self.ffs:
            if r is not None and v[r] == 0:
                updates.append((q, 0))
            elif s is not None and v[s] == 0:
                updates.append((q, 1))
            else:
                updates.append((q, v[d]))
        for q, val in updates:
            v[q] = val
        self.settle()

    def cycle(self, **inputs):
        """One clock cycle: inputs settle, rising edge samples, settle."""
        self.set_inputs(**inputs)
        self.clock_edge()

    def reset(self, cycles=2):
        kw = {p: 0 for p in self.nl["inputs"] if p != "rst_n"}
        for _ in range(cycles):
            self.cycle(rst_n=0, **kw)

    def read(self, net):
        return self.val[self.net_index[net]]

    def read_output(self, port):
        """Read a top-level output port, following the outputs_map."""
        net = self.nl.get("outputs_map", {}).get(port, port)
        return self.val[self.net_index[net]]
