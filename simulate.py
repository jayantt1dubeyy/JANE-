#!/usr/bin/env python3
"""Cycle-accurate simulator for an extracted netlist, shared by concrete
simulation and Z3 unrolling (same code path, parameterised by Ops).

Cycle semantics (matched to the example VCD):
  - One cycle = one rising clock edge. Inputs for cycle k are the values
    present just before that edge.
  - state_k = flip-flop Q values before edge k.
  - comb_k = combinational evaluation from state_k + inputs_k.
  - state_{k+1} = flip-flop next values from comb_k (async reset/set
    applied when the control pin is low).
  - outputs_k = combinational evaluation from state_{k+1} + inputs_k
    (i.e. values settled just after edge k, as recorded in the VCD).
  - Undriven nets (only net 1793 in the puzzle: two gate inputs with no
    driver in the layout) default to False/0 and are logged.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cells import load_all_models, eval_cell, Ops

POWER = {"VPWR", "VGND", "VPB", "VNB"}


class Circuit:
    def __init__(self, data):
        self.data = data
        self.models = load_all_models([i["cell"] for i in data["instances"]])
        self.instances = data["instances"]
        self.pads = data["pads"]
        self.power_nets = (set(data["power_nets"]["VPWR"]) |
                           set(data["power_nets"]["VGND"]))
        self.vpwr_nets = set(data["power_nets"]["VPWR"])
        # classify instances
        self.comb = []   # (inst, model)
        self.ffs = []    # (inst, model)
        for inst in self.instances:
            m = self.models[inst["cell"]]
            if m["ff"] is not None:
                self.ffs.append((inst, m))
            else:
                self.comb.append((inst, m))
        # driver map: net -> ('pad', padname) | ('cell', inst idx) | ('power', 0/1)
        self.driver = {}
        for pad, net in self.pads.items():
            self.driver.setdefault(net, ("pad", pad))
        for net in self.vpwr_nets:
            self.driver[net] = ("power", 1)
        for net in set(data["power_nets"]["VGND"]):
            self.driver[net] = ("power", 0)
        for idx, (inst, m) in enumerate(self.comb):
            for out in m["outputs"]:
                net = inst["pins"][out]
                if net in self.driver and self.driver[net][0] == "cell":
                    raise ValueError("net %d has two cell drivers" % net)
                self.driver[net] = ("cell", idx)
        # FF outputs are state sources, not comb drivers
        self.ff_out_net = {}
        for inst, m in self.ffs:
            self.ff_out_net[inst["pins"]["Q"]] = inst
        # topological order over combinational instances
        self.order = self._topo_order()
        # undriven input nets (excluding pads/power)
        driven_nets = set(self.driver) | set(self.ff_out_net)
        self.undriven = set()
        for inst, m in self.comb:
            for pin in m["inputs"]:
                if inst["pins"][pin] not in driven_nets:
                    self.undriven.add(inst["pins"][pin])
        for inst, m in self.ffs:
            for pin in ("D", "CLK"):
                if inst["pins"][pin] not in driven_nets:
                    self.undriven.add(inst["pins"][pin])
            ctl = m["ff"]["ctl_pin"]
            if ctl and inst["pins"][ctl] not in driven_nets:
                self.undriven.add(inst["pins"][ctl])

    def _topo_order(self):
        # net -> comb instance index producing it
        producer = {}
        for idx, (inst, m) in enumerate(self.comb):
            for out in m["outputs"]:
                producer[inst["pins"][out]] = idx
        indeg = [0] * len(self.comb)
        succ = [[] for _ in self.comb]
        for idx, (inst, m) in enumerate(self.comb):
            deps = set()
            for pin in m["inputs"]:
                net = inst["pins"][pin]
                if net in producer and producer[net] != idx:
                    deps.add(producer[net])
            indeg[idx] = len(deps)
            for d in deps:
                succ[d].append(idx)
        queue = [i for i, d in enumerate(indeg) if d == 0]
        order = []
        while queue:
            i = queue.pop()
            order.append(i)
            for j in succ[i]:
                indeg[j] -= 1
                if indeg[j] == 0:
                    queue.append(j)
        if len(order) != len(self.comb):
            raise ValueError("combinational cycle in netlist (%d/%d ordered)"
                             % (len(order), len(self.comb)))
        return order

    def initial_state(self, ops):
        state = {}
        for inst, m in self.ffs:
            if m["ff"]["udp"] == "PR":
                state[id(inst)] = ops.z3.BoolVal(False) if ops.is_z3 else False
            elif m["ff"]["udp"] == "PS":
                state[id(inst)] = ops.z3.BoolVal(True) if ops.is_z3 else True
            else:
                state[id(inst)] = ops.z3.BoolVal(False) if ops.is_z3 else False
        return state

    def eval_comb(self, nets, ops):
        """Evaluate all combinational cells in topo order, filling nets."""
        for idx in self.order:
            inst, m = self.comb[idx]
            pin_values = {pin: nets[inst["pins"][pin]] for pin in m["inputs"]}
            outs = eval_cell(m, pin_values, ops)
            for out_pin, val in outs.items():
                nets[inst["pins"][out_pin]] = val

    def ff_next(self, inst, m, nets, ops):
        """Next Q for one flip-flop, from current net values."""
        d = nets[inst["pins"]["D"]]
        ctl_pin = m["ff"]["ctl_pin"]
        if m["ff"]["udp"] == "PR":
            ctl = nets[inst["pins"][ctl_pin]]
            return ops.ITE(ops.NOT(ctl), ops.z3.BoolVal(False) if ops.is_z3 else False, d)
        if m["ff"]["udp"] == "PS":
            ctl = nets[inst["pins"][ctl_pin]]
            return ops.ITE(ops.NOT(ctl), ops.z3.BoolVal(True) if ops.is_z3 else True, d)
        return d


def run_cycles(circ, ops, input_cycles, undriven_value=False):
    """input_cycles: list of dicts {pad_name: value} for input pads
    (rst_n, enable, I; clk is implicit). Returns per-cycle output dicts
    {pad_name: value} for output pads (success, O[0..7]) sampled just
    after each edge, plus the final FF state."""
    pads = circ.pads
    # output pads = all pads except the ones driven per cycle + clk,
    # grouped: O[0..7] -> "O" int
    input_names = set(input_cycles[0].keys()) | {"clk"} if input_cycles else {"clk"}
    out_nets = {}
    for pad, net in pads.items():
        if pad in input_names:
            continue
        if pad.startswith("O["):
            out_nets.setdefault("O", {})[int(pad[2:-1])] = net
        else:
            out_nets[pad] = net
    state = circ.initial_state(ops)
    results = []
    for inputs in input_cycles:
        nets = {}
        for net in circ.vpwr_nets:
            nets[net] = ops.z3.BoolVal(True) if ops.is_z3 else True
        for net in set(circ.data["power_nets"]["VGND"]):
            nets[net] = ops.z3.BoolVal(False) if ops.is_z3 else False
        for net in circ.undriven:
            if ops.is_z3:
                nets[net] = ops.z3.BoolVal(bool(undriven_value))
            else:
                nets[net] = bool(undriven_value)
        for pad, val in inputs.items():
            nets[pads[pad]] = val
        # Clock value is arbitrary in this cycle model: verified that clock
        # nets feed only flip-flop CLK pins and clock-tree buffers, never
        # logic inputs, so the clock tree evaluates harmlessly to True.
        if "clk" in pads and pads["clk"] not in nets:
            nets[pads["clk"]] = ops.z3.BoolVal(True) if ops.is_z3 else True
        for inst, m in circ.ffs:
            nets[inst["pins"]["Q"]] = state[id(inst)]
        circ.eval_comb(nets, ops)
        nxt = {}
        for inst, m in circ.ffs:
            nxt[id(inst)] = circ.ff_next(inst, m, nets, ops)
        state = nxt
        for inst, m in circ.ffs:
            nets[inst["pins"]["Q"]] = state[id(inst)]
        circ.eval_comb(nets, ops)
        out = {}
        for pad, net in out_nets.items():
            if pad == "O":
                if ops.is_z3:
                    out["O_bits"] = {bit: nets[n] for bit, n in net.items()}
                    out["O"] = None
                else:
                    val = 0
                    for bit, n in net.items():
                        if nets[n]:
                            val |= (1 << bit)
                    out["O"] = val
            else:
                out[pad] = nets[net]
        results.append(out)
    return results, state


def protocol_cycles(key_bits, n_stream=16):
    """VCD-aligned protocol: 3 reset edges, 1 gap edge (rst=1,en=0),
    121 shift edges (en=1), then stream edges (en=0).
    key_bits[0] is the first bit presented on I."""
    assert len(key_bits) == 121
    cycles = []
    for _ in range(3):
        cycles.append({"rst_n": False, "enable": False, "I": False})
    cycles.append({"rst_n": True, "enable": False, "I": False})
    for b in key_bits:
        cycles.append({"rst_n": True, "enable": True, "I": bool(b)})
    for _ in range(n_stream):
        cycles.append({"rst_n": True, "enable": False, "I": False})
    return cycles
