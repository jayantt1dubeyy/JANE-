import pya, sys
ly = pya.Layout(); ly.read('/home/hatch/workspace/asic-puzzle-2026/puzzle.gds')

def boxes(cell, la, dt):
    out = []
    for s in cell.shapes(ly.layer(la,dt)).each():
        try: out.append(s.bbox())
        except Exception: pass
    return out

def overlaps(a, b):
    # nonzero-area overlap
    return a.left < b.right and b.left < a.right and a.bottom < b.top and b.bottom < a.top

for cname in ['sky130_fd_sc_hd__nand2_2','sky130_fd_sc_hd__nor2_2','sky130_fd_sc_hd__inv_2']:
    cell = ly.cell(cname)
    print("="*70)
    print("CELL", cname)
    strips = sorted(boxes(cell,65,20), key=lambda b: b.bottom)
    polys = sorted(boxes(cell,66,20), key=lambda b: b.left)
    li1 = boxes(cell,67,20)
    mcon = boxes(cell,67,44)
    print(" strips (65/20):", [(b.left,b.bottom,b.right,b.top) for b in strips])
    print(" poly  (66/20):", [(b.left,b.right) for b in polys])
    print(" li1 polygons:")
    for i,b in enumerate(li1):
        print("   li1[%d] (%d,%d)-(%d,%d)" % (i,b.left,b.bottom,b.right,b.top))
    for si, strip in enumerate(strips):
        kind = "NMOS(lower)" if si==0 else "PMOS(upper)"
        # split strip x-range by poly intervals
        cuts = []
        for p in polys:
            cuts.append((p.left, p.right))
        pts = [strip.left] + [x for c in cuts for x in c] + [strip.right]
        segs = []
        # segments are regions NOT under poly: [left, p0left], [p0right, p1left], [p1right, right]
        bounds = [strip.left]
        for (pl, pr) in cuts:
            bounds.append(pl); bounds.append(pr)
        bounds.append(strip.right)
        # segments: (bounds[0],bounds[1]), (bounds[2],bounds[3]), ...
        for k in range(0, len(bounds)-1, 2):
            segs.append((bounds[k], bounds[k+1]))
        print(" %s strip segments:" % kind)
        for (sx0, sx1) in segs:
            segbox = pya.Box(sx0, strip.bottom, sx1, strip.top)
            # mcon overlapping segment
            nets = set()
            for m in mcon:
                if overlaps(m, segbox):
                    for li, lb in enumerate(li1):
                        if overlaps(m, lb):
                            nets.add(li)
            print("   segment x %d-%d -> li1 nets: %s" % (sx0, sx1, sorted(nets)))
