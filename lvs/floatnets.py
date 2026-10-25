import pya, sys
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
ly = pya.Layout(); ly.read('/home/hatch/workspace/asic-puzzle-2026/puzzle.gds')
top = ly.top_cell()
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
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
il = l2n.internal_layout()
for i, net in enumerate(topc.each_net()):
    has_sub = any(True for _ in net.each_subcircuit_pin())
    if not has_sub:
        print("FLOATING net idx", i, "cluster", V(net,'cluster_id'), "name:", repr(net.name))
        for (ld, dt, nm) in [(68,20,'met1'),(69,20,'met2'),(70,20,'met3'),(71,20,'met4'),(72,20,'met5')]:
            sh = pya.Shapes()
            try:
                l2n.shapes_of_net(net, il.layer(ld,20), True, sh)
                boxes = [s.bbox() for s in sh.each()]
                if boxes:
                    xs = [b.left for b in boxes] + [b.right for b in boxes]
                    ys = [b.bottom for b in boxes] + [b.top for b in boxes]
                    print("   ", nm, len(boxes), "shapes, bbox um: (%.2f,%.2f)-(%.2f,%.2f)" % (min(xs)/1000, min(ys)/1000, max(xs)/1000, max(ys)/1000))
            except Exception as e:
                print("   ", nm, "err", str(e)[:100])
