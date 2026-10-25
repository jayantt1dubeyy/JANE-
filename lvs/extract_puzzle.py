import pya, sys, json, collections, time
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
path, outdir = sys.argv[1], sys.argv[2]
ly = pya.Layout(); ly.read(path)
top = ly.top_cell()
print("TOP:", top.name, "bbox:", top.bbox(), "DBU:", ly.dbu)
# top-level instance census
census = collections.Counter()
for inst in top.each_inst():
    census[inst.cell.name] += 1
print("top instances total:", sum(census.values()), "distinct cells:", len(census))
layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 4
def P(a,b): return l2n.make_polygon_layer(ly.layer(a,b))
def T(a,b): return l2n.make_text_layer(ly.layer(a,b))
li1=P(67,20); mcon=P(67,44); met1=P(68,20); via1=P(68,44); met2=P(69,20); via2=P(69,44)
met3=P(70,20); via3=P(70,44); met4=P(71,20); via4=P(71,44); met5=P(72,20)
polys = [li1,mcon,met1,via1,met2,via2,met3,via3,met4,via4,met5]
for L in polys:
    l2n.connect(L)
for a,b in [(li1,mcon),(mcon,met1),(met1,via1),(via1,met2),(met2,via2),(via2,met3),(met3,via3),(via3,met4),(met4,via4),(via4,met5)]:
    l2n.connect(a,b)
l2n.connect(li1,T(67,5)); l2n.connect(met1,T(68,5)); l2n.connect(met3,T(70,5)); l2n.connect(met4,T(71,5)); l2n.connect(met5,T(72,5))
t0=time.time()
l2n.extract_netlist()
print("extract took %.1fs" % (time.time()-t0))
nl = l2n.netlist(); nl.make_top_level_pins()
topc = nl.top_circuit()
print("TOP pins:", sorted(V(p,'name') for p in topc.each_pin()))
print("TOP nets:", sum(1 for _ in topc.each_net()), "TOP subckts:", sum(1 for _ in topc.each_subcircuit()))
print("circuits:", sum(1 for _ in nl.each_circuit()))
# per-circuit stats
for circ in nl.each_circuit():
    print("CIRCUIT:", circ.name, "pins:", circ.pin_count(), "nets:", sum(1 for _ in circ.each_net()))
json.dump({"census": dict(census)}, open(outdir + "/puzzle_census.json","w"), indent=1)
l2n.write(outdir + "/puzzle.lvsdb")
print("wrote lvsdb")
