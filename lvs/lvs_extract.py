import pya, time, sys, json

path, outprefix = sys.argv[1], sys.argv[2]
ly = pya.Layout()
ly.read(path)
top = ly.top_cell()
print("Top:", top.name, "DBU:", ly.dbu, flush=True)

layers_all = [ly.layer(a,b) for a,b in [(67,20),(67,44),(67,5),(68,20),(68,44),(68,5),(69,20),(69,44),(70,20),(70,44),(70,5),(71,20),(71,44),(71,5),(72,20),(72,5)]]
l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, layers_all))
l2n.threads = 4

def P(layer, dt, name):
    r = l2n.make_polygon_layer(ly.layer(layer, dt))
    return r
def T(layer, dt):
    return l2n.make_text_layer(ly.layer(layer, dt))

li1  = P(67, 20, "li1")
mcon = P(67, 44, "mcon")
met1 = P(68, 20, "met1")
via1 = P(68, 44, "via1")
met2 = P(69, 20, "met2")
via2 = P(69, 44, "via2")
met3 = P(70, 20, "met3")
via3 = P(70, 44, "via3")
met4 = P(71, 20, "met4")
via4 = P(71, 44, "via4")
met5 = P(72, 20, "met5")

t_li1  = T(67, 5)
t_met1 = T(68, 5)
t_met3 = T(70, 5)
t_met4 = T(71, 5)
t_met5 = T(72, 5)

# inter-layer connectivity chain
for a, b in [(li1, mcon), (mcon, met1), (met1, via1), (via1, met2),
             (met2, via2), (via2, met3), (met3, via3), (via3, met4),
             (met4, via4), (via4, met5)]:
    l2n.connect(a, b)
# attach labels to nets
l2n.connect(li1, t_li1)
l2n.connect(met1, t_met1)
l2n.connect(met3, t_met3)
l2n.connect(met4, t_met4)
l2n.connect(met5, t_met5)

t0 = time.time()
l2n.extract_netlist()
print("extract took %.1fs" % (time.time() - t0), flush=True)
for e in l2n.each_error():
    print("EXTRACT ERROR:", e)
for le in l2n.each_log_entry():
    print("LOG:", le)

nl = l2n.netlist()
print("num circuits:", sum(1 for _ in nl.each_circuit()))
summary = {}
for circ in nl.each_circuit():
    npins = circ.pin_count()
    nnets = sum(1 for _ in circ.each_net())
    nsub = sum(1 for _ in circ.each_subcircuit())
    ndev = sum(1 for _ in circ.each_device())
    summary[circ.name] = {"pins": npins, "nets": nnets, "subckts": nsub, "devices": ndev}
    print("CIRCUIT:", circ.name, "pins:", npins, "nets:", nnets, "subckts:", nsub, "devices:", ndev)
with open(outprefix + "_summary.json", "w") as f:
    json.dump(summary, f, indent=1)

# dump top circuit in detail
topc = nl.top_circuit()
print("TOP CIRCUIT:", topc.name)
print("TOP PINS:", [(p.name, topc.net_for_pin(p).name if topc.net_for_pin(p) else None) for p in topc.each_pin()])
import collections
subcnt = collections.Counter()
for sc in topc.each_subcircuit():
    subcnt[sc.circuit_ref.name] += 1
print("TOP SUBCKT COUNTS:")
for k, v in sorted(subcnt.items()):
    print("  ", k, v)
print("TOP total subckts:", sum(subcnt.values()))
print("TOP nets:", sum(1 for _ in topc.each_net()))
# write netlist in KLayout format for inspection
nl.write(outprefix + ".lvsdb.txt") if False else None
# Save via l2n write (lvsdb) for later querying
l2n.write(outprefix + ".lvsdb")
print("wrote", outprefix + ".lvsdb")
