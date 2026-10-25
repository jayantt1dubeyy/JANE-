import pya, sys
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
ly = pya.Layout(); ly.read('/home/hatch/workspace/asic-puzzle-2026/puzzle.gds')
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
# find nets and print ALL pins for nets feeding a31oi/a311o at y~92.48um (92480 DBU)
for net in topc.each_net():
    pins = []
    for sp in net.each_subcircuit_pin():
        sc = V(sp,'subcircuit'); pin = V(sp,'pin')
        ct = V(V(sc,'circuit_ref'),'name')
        tr = V(sc,'trans')
        pins.append((ct, V(pin,'name'), tr.disp.x, tr.disp.y))
    # look for the cluster: a31oi and a311o both near x 177-182um, y 92.48um
    has_a31oi = any(p[0].endswith('a31oi_2') and p[1]=='A1' and abs(p[3]-92.48)<0.01 for p in pins)
    has_a311o = any(p[0].endswith('a311o_2') and p[1]=='A1' and abs(p[3]-92.48)<0.01 for p in pins)
    if has_a31oi and has_a311o:
        print("NET cluster_id", V(net,'cluster_id'), "name:", net.name)
        for p in pins: print("   ", p)
