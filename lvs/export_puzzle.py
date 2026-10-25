import pya, sys, json, collections
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
path, outdir = sys.argv[1], sys.argv[2]
ly = pya.Layout(); ly.read(path)
top = ly.top_cell()
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 1
def P(a,b): return l2n.make_polygon_layer(ly.layer(a,b))
def T(a,b): return l2n.make_text_layer(ly.layer(a,b))
li1=P(67,20); mcon=P(67,44); met1=P(68,20); via1=P(68,44); met2=P(69,20); via2=P(69,44)
met3=P(70,20); via3=P(70,44); met4=P(71,20); via4=P(71,44); met5=P(72,20)
polys = [li1,mcon,met1,via1,met2,via2,met3,via3,met4,via4,met5]
for L in polys: l2n.connect(L)
for a,b in [(li1,mcon),(mcon,met1),(met1,via1),(via1,met2),(met2,via2),(via2,met3),(met3,via3),(via3,met4),(met4,via4),(via4,met5)]:
    l2n.connect(a,b)
l2n.connect(li1,T(67,5)); l2n.connect(met1,T(68,5)); l2n.connect(met3,T(70,5)); l2n.connect(met4,T(71,5)); l2n.connect(met5,T(72,5))
l2n.extract_netlist()
nl = l2n.netlist(); nl.make_top_level_pins()
topc = nl.top_circuit()
def is_logic(n):
    if n.startswith("VIA"): return False
    if n in ("INTERNAL_3","INTERNAL_7"): return False
    base = n.replace("sky130_fd_sc_hd__","")
    return not any(base.startswith(p) for p in ("tap","decap","diode","fill"))
POWER = {"VPWR","VGND","VPB","VNB",""}
# net index map (stable by iteration order)
net_index = {}
for i, net in enumerate(topc.each_net()):
    net_index[V(net, "cluster_id")] = i
# verify net_for_pin(pin.id) works on one subcircuit
for sc in topc.each_subcircuit():
    ctype = V(V(sc, "circuit_ref"), "name")
    if not is_logic(ctype): continue
    circ = V(sc, "circuit_ref")
    for p in circ.each_pin():
        net = sc.net_for_pin(V(p, "id"))
        assert net is not None
    print("net_for_pin(pin.id) OK for", ctype)
    break
# build instances
instances = []
for sc in topc.each_subcircuit():
    ctype = V(V(sc, "circuit_ref"), "name")
    if not is_logic(ctype): continue
    circ = V(sc, "circuit_ref")
    conns = {}
    for p in circ.each_pin():
        pn = V(p, "name")
        if pn in POWER: continue
        net = sc.net_for_pin(V(p, "id"))
        conns[pn] = net_index[V(net, "cluster_id")] if net is not None else None
    tr = V(sc, "trans")
    instances.append({"cell": ctype, "pins": conns,
                      "x": tr.disp.x, "y": tr.disp.y})
print("logic instances exported:", len(instances))
# net names / port map
net_names = {}
port_net = {}
for i, net in enumerate(topc.each_net()):
    if net.name: net_names[i] = net.name
for p in topc.each_pin():
    pn = V(p, "name")
    net = topc.net_for_pin(p)
    port_net[pn] = net_index[V(net, "cluster_id")]
print("named nets:", net_names)
print("port nets:", port_net)
# net -> logic pins (for analysis)
net_logic = collections.defaultdict(list)
for inst in instances:
    for pn, ni in inst["pins"].items():
        net_logic[ni].append((inst["cell"], pn))
OUTPINS = {"X","Y","Q","Q_N","HI","LO"}
zero_drv = []
for ni, pins in net_logic.items():
    if not any(pn in OUTPINS for _, pn in pins):
        zero_drv.append((ni, net_names.get(ni), pins))
print("zero-driver logic nets:", len(zero_drv))
for z in zero_drv: print("   ", z)
# floating nets: no subcircuit pins at all
all_nets_with_subpins = set()
for net in topc.each_net():
    if any(True for _ in net.each_subcircuit_pin()):
        all_nets_with_subpins.add(net_index[V(net, "cluster_id")])
floating = [i for i in range(len(net_index)) if i not in all_nets_with_subpins]
print("floating nets (no subcircuit pins):", floating)
# write JSON
json.dump({"top_ports": port_net, "net_names": {str(k): v for k, v in net_names.items()},
           "instances": instances},
          open(outdir + "/puzzle_lvs.json", "w"), indent=1)
# write Verilog
def vnet(i):
    if i in port_net.values():
        for pn, ni in port_net.items():
            if ni == i: return pn
    return "net_%d" % i
lines = []
lines.append("// Structural netlist extracted from puzzle.gds with KLayout's built-in")
lines.append("// LayoutToNetlist extractor (validated on warmup/04_final.gds: exact")
lines.append("// structural match to warmup/01_netlist.v).")
lines.append("// Power pins (VPWR/VGND/VPB/VNB) and unnamed well pins dropped.")
lines.append("// Behavioural models: standard SkyWater sky130_fd_sc_hd PDK cells.")
lines.append("module puzzle (clk, rst_n, enable, I, success, O);")
lines.append("  input clk, rst_n, enable, I;")
lines.append("  output success;")
lines.append("  output [7:0] O;")

# collect used nets
used = set()
for inst in instances:
    for ni in inst["pins"].values():
        if ni is not None: used.add(ni)
for ni in sorted(used):
    if ni not in port_net.values():
        lines.append("  wire %s;" % vnet(ni))
for idx, inst in enumerate(instances):
    conns = ", ".join(".%s(%s)" % (pn, vnet(ni) if ni is not None else "1'bx") for pn, ni in sorted(inst["pins"].items()))
    lines.append("  %s inst_%d (%s);" % (inst["cell"], idx, conns))

lines.append("endmodule")
open(outdir + "/puzzle_lvs.v", "w").write("\n".join(lines) + "\n")
print("wrote", outdir + "/puzzle_lvs.json", "and", outdir + "/puzzle_lvs.v")
