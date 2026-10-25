import pya, re, sys, os, collections
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
path, gtpath = sys.argv[1], sys.argv[2]
FLAT = os.environ.get("FLAT","0") == "1"
INTRA = os.environ.get("INTRA","0") == "1"
ly = pya.Layout(); ly.read(path)
top = ly.top_cell()
if FLAT:
    for inst in list(top.each_inst()):
        if inst.cell.name.startswith("VIA"):
            inst.flatten()
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 4
def P(a,b): return l2n.make_polygon_layer(ly.layer(a,b))
def T(a,b): return l2n.make_text_layer(ly.layer(a,b))
li1=P(67,20); mcon=P(67,44); met1=P(68,20); via1=P(68,44); met2=P(69,20); via2=P(69,44)
met3=P(70,20); via3=P(70,44); met4=P(71,20); via4=P(71,44); met5=P(72,20)
polys = [li1,mcon,met1,via1,met2,via2,met3,via3,met4,via4,met5]
if INTRA:
    for L in polys:
        l2n.connect(L)
for a,b in [(li1,mcon),(mcon,met1),(met1,via1),(via1,met2),(met2,via2),(via2,met3),(met3,via3),(via3,met4),(met4,via4),(via4,met5)]:
    l2n.connect(a,b)
l2n.connect(li1,T(67,5)); l2n.connect(met1,T(68,5)); l2n.connect(met3,T(70,5)); l2n.connect(met4,T(71,5)); l2n.connect(met5,T(72,5))
l2n.extract_netlist()
nl = l2n.netlist(); nl.make_top_level_pins()
topc = nl.top_circuit()
POWER = {"VPWR","VGND","VPB","VNB",""}
SKIP_CELL = lambda n: n.startswith("VIA") or "tapvpwrvgnd" in n or "decap" in n
my_nets = {}
my_celltypes = collections.Counter()
for i, net in enumerate(topc.each_net()):
    my_nets[i] = set()
for i, net in enumerate(topc.each_net()):
    for sp in net.each_subcircuit_pin():
        sc = V(sp, "subcircuit"); pin = V(sp, "pin")
        ctype = V(V(sc, "circuit_ref"), "name")
        if SKIP_CELL(ctype): continue
        my_nets[i].add((ctype, V(pin, "name")))
    for p in net.each_pin():
        my_nets[i].add(("PORT", V(V(p, "pin"), "name")))
for sc in topc.each_subcircuit():
    ctype = V(V(sc, "circuit_ref"), "name")
    if SKIP_CELL(ctype): continue
    my_celltypes[ctype] += 1
my_sigs = collections.Counter()
for i, s in my_nets.items():
    s2 = frozenset(x for x in s if x[1] not in POWER)
    if s2: my_sigs[s2] += 1
gt_text = open(gtpath).read()
gt_text = re.sub(r'//.*', '', gt_text)
inst_pat = re.compile(r'(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\((.*?)\)\s*;', re.DOTALL)
gt_celltypes = collections.Counter()
gt_nets = collections.defaultdict(set)
def norm_net(n):
    n = n.strip()
    if n.startswith("\\"): n = n[1:]
    return n.strip()
for m in inst_pat.finditer(gt_text):
    ctype, inst, ports = m.group(1), m.group(2), m.group(3)
    if "tapvpwrvgnd" in ctype or "decap" in ctype: continue
    gt_celltypes[ctype] += 1
    for pm in re.finditer(r'\.(\w+)\s*\(\s*([^)]*?)\s*\)', ports):
        pin, net = pm.group(1), norm_net(pm.group(2))
        if net: gt_nets[net].add((ctype, pin))
mod = re.search(r'module\s+adder_demo\s*\((.*?)\)\s*;', gt_text, re.DOTALL).group(1)
for p in [x.strip() for x in mod.split(",")]:
    if p in gt_nets: gt_nets[p].add(("PORT", p))
gt_sigs = collections.Counter()
for net, s in gt_nets.items():
    s2 = frozenset(x for x in s if x[1] not in POWER)
    if s2: gt_sigs[s2] += 1
print("FLAT=%s INTRA=%s | top pins: %s | top nets: %d | my nets: %d gt nets: %d | cellmatch: %s | SIG EQUAL: %s" % (
    FLAT, INTRA, sorted(V(p,'name') for p in topc.each_pin()),
    sum(1 for _ in topc.each_net()), sum(my_sigs.values()), sum(gt_sigs.values()),
    dict(my_celltypes)==dict(gt_celltypes), my_sigs==gt_sigs))
if my_sigs != gt_sigs:
    om, og = my_sigs-gt_sigs, gt_sigs-my_sigs
    print("  only MINE:", sum(om.values()), " only GT:", sum(og.values()))
    for s,c in list(om.items())[:12]: print("   M x%d" % c, sorted(s))
    for s,c in list(og.items())[:12]: print("   G x%d" % c, sorted(s))
