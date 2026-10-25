import pya, sys
def V(o,n):
    a=getattr(o,n); return a() if callable(a) else a
ly = pya.Layout(); ly.read('/home/hatch/workspace/asic-puzzle-2026/puzzle.gds')
for cname in ['sky130_fd_sc_hd__nand2_2','sky130_fd_sc_hd__nor2_2','sky130_fd_sc_hd__inv_2']:
    cell = ly.cell(cname)
    print("="*64); print("CELL", cname)
    layers = [ly.layer(a,b) for a,b in [(65,20),(64,20),(66,20),(66,44),(67,20),(67,44),(67,5),(68,20),(68,5)]]
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, cell, layers))
    def P(a,b): return l2n.make_polygon_layer(ly.layer(a,b))
    def T(a,b): return l2n.make_text_layer(ly.layer(a,b))
    active = P(65,20); nwell = P(64,20); poly = P(66,20); polycon = P(66,44)
    li1 = P(67,20); mcon = P(67,44); met1 = P(68,20)
    pactive = active & nwell
    pgate = pactive & poly
    psd = pactive - pgate
    nactive = active - nwell
    ngate = nactive & poly
    nsd = nactive - ngate
    for reg, nm in [(pactive,'pactive'),(pgate,'pgate'),(psd,'psd'),(nactive,'nactive'),(ngate,'ngate'),(nsd,'nsd')]:
        l2n.register(reg, nm)
    pmos_ex = pya.DeviceExtractorMOS3Transistor("PMOS")
    nmos_ex = pya.DeviceExtractorMOS3Transistor("NMOS")
    l2n.extract_devices(pmos_ex, {"SD": psd, "G": pgate, "P": poly})
    l2n.extract_devices(nmos_ex, {"SD": nsd, "G": ngate, "P": poly})
    for ex in (pmos_ex, nmos_ex):
        for e in ex.each_error():
            print("  DEV EXTRACT ERROR:", e)
    # connectivity
    for L in [li1, mcon, met1, poly, polycon, psd, nsd, pgate, ngate]:
        l2n.connect(L)
    for a,b in [(psd,li1),(nsd,li1),(pgate,poly),(ngate,poly),(poly,polycon),(polycon,li1),(li1,mcon),(mcon,met1)]:
        l2n.connect(a,b)
    l2n.connect(li1, T(67,5))
    l2n.connect(met1, T(68,5))
    l2n.extract_netlist()
    nl = l2n.netlist(); nl.make_top_level_pins()
    topc = nl.top_circuit()
    print("  pins:", [V(p,'name') for p in topc.each_pin()])
    for dev in topc.each_device():
        dc = V(dev,'device_class')
        terms = []
        for t in range(4):
            try:
                net = dev.net_for_terminal(t)
                terms.append(net.name if net else None)
            except Exception as e:
                terms.append("?")
        print("  DEVICE %s terminals(S/D/G/B?): %s" % (V(dc,'name'), terms))
    # also list device class names properly
    for dev in topc.each_device():
        print("   dev class:", dev.device_class.name)
