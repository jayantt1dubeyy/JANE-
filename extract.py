#!/usr/bin/env python3
"""GDS -> gate-level netlist extractor (independent implementation).

Pipeline:
  1. Walk top-level instances; expand every instance's shapes into global
     coordinates (KLayout Trans applied to Points, so rotation/mirror/
     displacement are exact).
  2. Merge overlapping polygons per drawing layer with pya.Region.
  3. Union merged polygons across layers through via cuts (DSU + spatial
     hash grid) -> nets.
  4. Map instance pins (li1 text-label positions) and top-level pads
     (met3 text labels) to nets by point-in-polygon containment.
  5. Emit a JSON description and a structural Verilog netlist.

Power pins (VPWR/VGND/VPB/VNB) are not emitted as netlist ports: they do
not affect logic. Power nets are still identified (for the simulator to
tie them to 1/0) from the VPWR/VGND text labels.
"""
import sys, os, json
sys.path.insert(0, "/home/hatch/workspace/.pydeps")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pya
from collections import defaultdict

DRAW_LAYERS = [(67, 20), (68, 20), (69, 20), (70, 20), (71, 20), (72, 20)]
DRAW_IDX = {layer: i for i, layer in enumerate(DRAW_LAYERS)}
# cut layer -> (lower drawing layer, upper drawing layer), as indices
CUTS = {(67, 44): (0, 1), (68, 44): (1, 2), (69, 44): (2, 3),
        (70, 44): (3, 4), (71, 44): (4, 5)}
TEXT_TO_DRAW = {(67, 5): (67, 20), (68, 5): (68, 20), (70, 5): (70, 20),
                (71, 5): (71, 20), (72, 5): (72, 20)}
POWER = {"VPWR", "VGND", "VPB", "VNB"}
NONLOGIC = ("tap", "decap", "diode", "fill")
GRID = 2000  # spatial hash cell size in DBU


def shape_points(shape):
    """Return a list of (x, y) integer points for a polygon/box/path shape."""
    if shape.is_polygon():
        return [(pt.x, pt.y) for pt in shape.polygon.each_point_hull()]
    if shape.is_box():
        b = shape.box
        return [(b.left, b.bottom), (b.right, b.bottom),
                (b.right, b.top), (b.left, b.top)]
    if shape.is_path():
        return [(pt.x, pt.y) for pt in shape.path.polygon().each_point_hull()]
    return None


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def rect_overlaps_poly_pya(cut_box, poly):
    """Exact overlap test between a small rectangular cut and a polygon,
    using KLayout's own boolean engine (handles holes correctly)."""
    r = pya.Region(pya.Box(cut_box[0], cut_box[1], cut_box[2], cut_box[3]))
    return not r.interacting(pya.Region(poly)).is_empty()


def extract(gds_path, module_name, dump_nodes_path=None):
    layout = pya.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    layer_index = {info: layout.layer(info) for info in layout.layer_infos()}

    # ---- 1. per-cell-definition geometry (computed once per cell type) --
    cell_geom = {}   # cell name -> {layer: [point lists], texts: {layer: [(pt, str)]}}
    for cell in layout.each_cell():
        geom = defaultdict(list)
        texts = defaultdict(list)
        for info in layout.layer_infos():
            key = (info.layer, info.datatype)
            if key not in DRAW_IDX and key not in CUTS and key not in TEXT_TO_DRAW:
                continue
            li = layer_index[info]
            for shape in cell.shapes(li).each():
                if shape.is_text():
                    t = shape.text
                    d = t.trans.disp
                    texts[key].append(((d.x, d.y), t.string))
                else:
                    pts = shape_points(shape)
                    if pts:
                        geom[key].append(pts)
        cell_geom[cell.name] = (geom, texts)

    # ---- 2. expand all top-level instances into global geometry --------
    draw_polys = defaultdict(list)   # draw layer -> [point lists]
    cuts = []                        # (cut layer, (x1,y1,x2,y2))
    top_texts = defaultdict(list)    # text layer -> [(point, string)]
    instances = []                   # logic instances
    for inst in top.each_inst():
        name = inst.cell.name
        geom, texts = cell_geom[name]
        tr = inst.trans
        for layer, polys in geom.items():
            if layer in DRAW_IDX:
                for pts in polys:
                    gp = [tr.trans(pya.Point(x, y)) for x, y in pts]
                    draw_polys[layer].append([(p.x, p.y) for p in gp])
            elif layer in CUTS:
                for pts in polys:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    # transform corners to get the global bbox of the cut
                    gpts = [tr.trans(pya.Point(x, y)) for x, y in pts]
                    gx = [p.x for p in gpts]
                    gy = [p.y for p in gpts]
                    cuts.append((layer, (min(gx), min(gy), max(gx), max(gy))))
        # texts of this instance (pin labels, power labels)
        for layer, tlist in texts.items():
            for (lx, ly), s in tlist:
                gp = tr.trans(pya.Point(lx, ly))
                if name.startswith("sky130_fd_sc_hd__") and \
                        not name[len("sky130_fd_sc_hd__"):].startswith(NONLOGIC):
                    pass  # handled below via pin collection
                top_texts[layer].append(((gp.x, gp.y), s))
        # logic instance record
        if name.startswith("sky130_fd_sc_hd__"):
            base = name[len("sky130_fd_sc_hd__"):]
            if not base.startswith(NONLOGIC):
                pin_labels = defaultdict(list)  # pin -> [global points]
                for (lx, ly), s in texts.get((67, 5), []):
                    if s in POWER:
                        continue
                    gp = tr.trans(pya.Point(lx, ly))
                    pin_labels[s].append((gp.x, gp.y))
                instances.append({"cell": name, "pins_labels": dict(pin_labels)})
    # top cell's own shapes (routing + pads)
    for info in layout.layer_infos():
        key = (info.layer, info.datatype)
        li = layer_index[info]
        for shape in top.shapes(li).each():
            if shape.is_text():
                t = shape.text
                d = t.trans.disp
                top_texts[key].append(((d.x, d.y), t.string))
            elif key in DRAW_IDX:
                pts = shape_points(shape)
                if pts:
                    draw_polys[key].append(pts)
            elif key in CUTS:
                pts = shape_points(shape)
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    cuts.append((key, (min(xs), min(ys), max(xs), max(ys))))

    # ---- 3. merge polygons per drawing layer ---------------------------
    merged = {}   # draw layer -> [pya.Polygon]
    for layer in DRAW_LAYERS:
        region = pya.Region()
        for pts in draw_polys[layer]:
            region.insert(pya.Polygon([pya.Point(x, y) for x, y in pts]))
        region.merge()
        merged[layer] = [poly for poly in region.each()]
    node_layer = []
    node_poly = []
    for layer in DRAW_LAYERS:
        for poly in merged[layer]:
            node_layer.append(DRAW_IDX[layer])
            node_poly.append(poly)
    print("merged polygons per layer:", {str(k): len(v) for k, v in merged.items()},
          "total nodes:", len(node_poly))

    # ---- 4. DSU over vias ----------------------------------------------
    dsu = DSU(len(node_poly))
    grids = defaultdict(lambda: defaultdict(list))  # layer idx -> grid cell -> nodes
    for idx, poly in enumerate(node_poly):
        b = poly.bbox()
        for gx in range(b.left // GRID, b.right // GRID + 1):
            for gy in range(b.bottom // GRID, b.top // GRID + 1):
                grids[node_layer[idx]][(gx, gy)].append(idx)

    def candidates(layer_idx, box):
        out = set()
        for gx in range(box[0] // GRID, box[2] // GRID + 1):
            for gy in range(box[1] // GRID, box[3] // GRID + 1):
                out.update(grids[layer_idx].get((gx, gy), ()))
        return out

    n_cuts_used = 0
    for cut_layer, box in cuts:
        lo, hi = CUTS[cut_layer]
        below = [i for i in candidates(lo, box)
                 if rect_overlaps_poly_pya(box, node_poly[i])]
        above = [i for i in candidates(hi, box)
                 if rect_overlaps_poly_pya(box, node_poly[i])]
        if below and above:
            n_cuts_used += 1
            base = below[0]
            for i in below[1:] + above:
                dsu.union(base, i)
    print("via cuts: %d total, %d bridging both layers" % (len(cuts), n_cuts_used))

    root_to_net = {}
    node_net = []
    for i in range(len(node_poly)):
        r = dsu.find(i)
        if r not in root_to_net:
            root_to_net[r] = len(root_to_net)
        node_net.append(root_to_net[r])
    n_nets = len(root_to_net)
    print("nets:", n_nets)
    if dump_nodes_path:
        with open(dump_nodes_path, "w") as f:
            for i, poly in enumerate(node_poly):
                b = poly.bbox()
                f.write(json.dumps({"net": node_net[i], "layer": DRAW_LAYERS[node_layer[i]],
                                    "bbox": [b.left, b.bottom, b.right, b.top]}) + "\n")
        print("wrote node dump", dump_nodes_path)

    # ---- 5. point -> net lookup ----------------------------------------
    def net_at(layer_idx, point):
        px, py = point
        cands = grids[layer_idx].get((px // GRID, py // GRID), [])
        for i in cands:
            b = node_poly[i].bbox()
            if b.left <= px <= b.right and b.bottom <= py <= b.top:
                if node_poly[i].inside(pya.Point(px, py)):
                    return node_net[i]
        # fallback: bbox containment (point on polygon boundary)
        for i in cands:
            b = node_poly[i].bbox()
            if b.left <= px <= b.right and b.bottom <= py <= b.top:
                return node_net[i]
        # fallback: nearest polygon within 500 nm by bbox distance
        best, bestd = None, 10 ** 9
        for i in cands:
            b = node_poly[i].bbox()
            dx = max(b.left - px, 0, px - b.right)
            dy = max(b.bottom - py, 0, py - b.top)
            d = dx * dx + dy * dy
            if d < bestd:
                best, bestd = i, d
        if best is not None and bestd <= 500 * 500:
            return node_net[best]
        return None

    warnings = []
    # instance pins (li1)
    for inst in instances:
        pins = {}
        for pin, points in inst["pins_labels"].items():
            nets = set()
            for pt in points:
                n = net_at(0, pt)
                if n is not None:
                    nets.add(n)
            if len(nets) == 0:
                warnings.append("UNMAPPED pin %s of %s" % (pin, inst["cell"]))
            elif len(nets) > 1:
                warnings.append("MULTI-NET pin %s of %s -> %s" % (pin, inst["cell"], sorted(nets)))
            if nets:
                pins[pin] = sorted(nets)[0]
        inst["pins"] = pins
        del inst["pins_labels"]
    # pads (met3 texts at top level)
    pads = {}
    for pt, s in top_texts.get((70, 5), []):
        n = net_at(3, pt)
        if n is None:
            warnings.append("UNMAPPED pad %s" % s)
        else:
            pads[s] = n
    # power nets (any VPWR/VGND text, on its own layer)
    power_nets = {"VPWR": set(), "VGND": set()}
    for text_layer, draw_layer in TEXT_TO_DRAW.items():
        for pt, s in top_texts.get(text_layer, []):
            if s in ("VPWR", "VGND"):
                n = net_at(DRAW_IDX[draw_layer], pt)
                if n is not None:
                    power_nets[s].add(n)
    print("instances:", len(instances), "pads:", pads)
    print("power nets:", {k: sorted(v) for k, v in power_nets.items()})
    print("warnings:", len(warnings))
    for w in warnings[:20]:
        print("  WARN:", w)

    return {"module": module_name, "n_nets": n_nets, "instances": instances,
            "pads": pads, "power_nets": {k: sorted(v) for k, v in power_nets.items()},
            "warnings": warnings}


def emit_verilog(data, path, port_dirs):
    """port_dirs: {pad_name: 'input'|'output'} (bus pads handled by caller)."""
    lines = []
    lines.append("`timescale 1ns/1ps")
    # bus grouping: O[0]..O[7] -> O[7:0]
    buses = defaultdict(dict)
    singles = {}
    for pad, net in data["pads"].items():
        if "[" in pad and pad.endswith("]"):
            base, idx = pad[:-1].split("[")
            buses[base][int(idx)] = net
        else:
            singles[pad] = net
    ports = []
    for pad in sorted(singles):
        ports.append(pad)
    for base in sorted(buses):
        ports.append(base)
    lines.append("module %s (%s);" % (data["module"], ", ".join(ports)))
    for pad in sorted(singles):
        lines.append("  %s wire %s;" % (port_dirs[pad], pad))
    for base in sorted(buses):
        idxs = sorted(buses[base])
        lines.append("  %s wire [%d:%d] %s;" % (port_dirs[base], max(idxs), min(idxs), base))
    for i in range(data["n_nets"]):
        lines.append("  wire net_%d;" % i)
    for pad, net in sorted(singles.items()):
        if port_dirs[pad] == "input":
            lines.append("  assign net_%d = %s;" % (net, pad))
        else:
            lines.append("  assign %s = net_%d;" % (pad, net))
    for base in sorted(buses):
        for idx, net in sorted(buses[base].items()):
            if port_dirs[base] == "input":
                lines.append("  assign net_%d = %s[%d];" % (net, base, idx))
            else:
                lines.append("  assign %s[%d] = net_%d;" % (base, idx, net))
    for iid, inst in enumerate(data["instances"]):
        conns = ", ".join(".%s(net_%d)" % (pin, net)
                           for pin, net in sorted(inst["pins"].items()))
        lines.append("  %s inst_%d (%s);" % (inst["cell"], iid, conns))
    lines.append("endmodule")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    gds_path, module_name, json_out, verilog_out = sys.argv[1:5]
    data = extract(gds_path, module_name)
    with open(json_out, "w") as f:
        json.dump(data, f)
    print("wrote", json_out)
    if len(sys.argv) > 5 and sys.argv[5] == "--emit-verilog":
        # directions derived later by the caller; here emit with placeholders
        # replaced by derive_dirs.py -- this branch is unused in practice.
        pass
