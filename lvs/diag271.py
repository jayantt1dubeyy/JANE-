import pya, sys
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
ly = pya.Layout(); ly.read('/home/hatch/workspace/asic-puzzle-2026/puzzle.gds')
top = ly.top_cell()
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,44),(72,5),(73,20)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 1
def P(a,b): return l2n.make_polygon_layer(ly.layer(a,b))
def T(a,b): return l2n.make_text_layer(ly.layer(a,b))
li1=P(67,20); mcon=P(67,44); met1=P(68,20); via1=P(68,44); met2=P(69,20); via2=P(69,44)
met3=P(70,20); via3=P(70,44); met4=P(71,20); via4=P(71,44); met5=P(72,20); via5=P(72,44); met6=P(73,20)
polys = [li1,mcon,met1,via1,met2,via2,met3,via3,met4,via4,met5,via5,met6]
for L in polys: l2n.connect(L)
for a,b in [(li1,mcon),(mcon,met1),(met1,via1),(via1,met2),(met2,via2),(via2,met3),(met3,via3),(via3,met4),(met4,via4),(via4,met5),(met5,via5),(via5,met6)]:
    l2n.connect(a,b)
l2n.connect(li1,T(67,5)); l2n.connect(met1,T(68,5)); l2n.connect(met3,T(70,5)); l2n.connect(met4,T(71,5)); l2n.connect(met5,T(72,5))
l2n.extract_netlist()
nl = l2n.netlist(); nl.make_top_level_pins()
topc = nl.top_circuit()
print("WITH met6/via5: top nets:", sum(1 for _ in topc.each_net()), "subckts:", sum(1 for _ in topc.each_subcircuit()))
# find net 271 equivalent: locate net feeding a31oi A1 / a311o A1 at that location - instead print nets with no driver among logic, and check via5 cell contents
# what is inside VIA_via5_6 cell?
vc = ly.cell('VIA_via5_6_2000_2000_1_1_1600_1600')
import collections
for li in ly.layer_indexes():
    info = ly.get_info(li)
    ss = list(vc.shapes(li).each())
    if ss: print("VIA5 cell layer", (info.layer, info.datatype), len(ss))
