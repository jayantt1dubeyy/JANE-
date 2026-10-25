import pya, sys, json, collections
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
path = sys.argv[1]
ly = pya.Layout(); ly.read(path)
top = ly.top_cell()
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 4
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

# cell pin lists
cell_pins = {}
for circ in nl.each_circuit():
    cell_pins[circ.name] = [V(p,'name') for p in circ.each_pin()]

# build net -> logic pins, and instance list
net_logic = collections.defaultdict(list)   # net index -> [(inst_id, celltype, pin)]
net_all = collections.defaultdict(list)
inst_list = []  # (inst_id, celltype, {pin: net_index})
net_name = {}
for i, net in enumerate(topc.each_net()):
    net_name[i] = net.name
for i, net in enumerate(topc.each_net()):
    for sp in net.each_subcircuit_pin():
        sc = V(sp, "subcircuit"); pin = V(sp, "pin")
        ctype = V(V(sc, "circuit_ref"), "name")
        net_all[i].append((ctype, V(pin,"name")))
        if is_logic(ctype) and V(pin,"name") not in POWER:
            net_logic[i].append((ctype, V(pin,"name")))
# instances with pin->net
inst_id = 0
inst_counter = collections.Counter()
pin_to_net = collections.defaultdict(dict)  # inst_id -> {pin: net}
for sc in topc.each_subcircuit():
    ctype = V(V(sc, "circuit_ref"), "name")
    if not is_logic(ctype): continue
    inst_counter[ctype] += 1
    circ = V(sc, "circuit_ref")
    d = {}
    for p in circ.each_pin():
        pn = V(p, "name")
        net = sc.net_for_pin(V(p, "id")) if False else None
        d[pn] = None
    inst_list.append((inst_id, ctype, d))
    inst_id += 1
# redo pin->net via net iteration (need sc identity): use id(sc)
sc_by_id = {}
for sc in topc.each_subcircuit():
    sc_by_id[id(sc)] = sc
# Instead: iterate nets and record (id(sc), ctype, pin) -> net
inst_pin_net = collections.defaultdict(dict)
sc_ctype = {}
for i, net in enumerate(topc.each_net()):
    for sp in net.each_subcircuit_pin():
        sc = V(sp, "subcircuit"); pin = V(sp, "pin")
        ctype = V(V(sc, "circuit_ref"), "name")
        if not is_logic(ctype): continue
        inst_pin_net[id(sc)][V(pin,"name")] = i
        sc_ctype[id(sc)] = ctype
print("logic instances with pins:", len(inst_pin_net), "sum counter:", sum(inst_counter.values()))
print("logic pins mapped (incl power/unnamed):", sum(len(d) for d in inst_pin_net.values()))
print("logic signal pins (excl power/unnamed):", sum(1 for d in inst_pin_net.values() for pn in d if pn not in POWER))
# net categories
n_logic_nets = sum(1 for i in net_logic if net_logic[i])
n_zero = sum(1 for i in net_all if not net_all[i])
n_only_power = 0
print("top nets total:", len(net_all))
print("nets touching >=1 logic signal pin:", n_logic_nets)
print("nets with no subcircuit pins at all:", n_zero)
print("named nets:", {i: n for i, n in net_name.items() if n})
# driver analysis: output pins
OUTPINS = {"X","Y","Q","Q_N","HI","LO"}
drv = collections.Counter()
multi = []
for i, pins in net_logic.items():
    d = sum(1 for (ct, pn) in pins if pn in OUTPINS)
    drv[d] += 1
    if d > 1: multi.append((i, pins))
print("driver-count distribution over logic nets (0/1/2+):", dict(sorted(drv.items())))
print("multi-driver logic nets:", len(multi))
for i, pins in multi[:10]:
    print("   net", i, net_name[i], pins)
# nets with exactly 1 logic pin (possible stubs)
single = [(i,p) for i,p in net_logic.items() if len(p)==1]
print("single-logic-pin nets:", len(single))
for i,p in single[:15]: print("   net", i, net_name[i], p)
# top-port nets
for p in topc.each_pin():
    pn = V(V(p,"pin"),"name")
    net = topc.net_for_pin(p)
    print("PORT", pn, "-> net has logic pins:", len(net_logic.get(id(net),[])) if False else "")
json.dump({"cell_pins": cell_pins}, open("/tmp/lvs/puzzle_cell_pins.json","w"), indent=1)
