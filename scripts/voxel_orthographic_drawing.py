#!/usr/bin/env python3
"""体素占用 → 正交三视图（真投影）→ 装配出图。

这条链补的正是外部件缺的那一半：`cadstack` 的 `lib/drawing.py` 自己注释写了投影是
**包围盒简化投影**（"A full implementation would use the actual model geometry"）。
本脚本做**真投影**（逐个体积盒投影到正/侧/顶/轴测），再把结果**覆盖**进
`ViewProjection.lines`，复用对方的图幅、标题栏、视图布置与 DXF/SVG/PDF 导出。

数据来源（二选一）：
  --audit <path>   路线自己的 `*_audit.json`，读 `volumes[]`（字段 origin / size / minY / maxY）
  --boxes <path>   [{"name":..,"origin":[x,y,z],"size":[sx,sy,sz]}, ...]（size 单位=体素）

输出（全部落在 --out）：
  projection.json   机器可读：逐视图的投影矩形（世界坐标，米）——供后续与渲染帧做 IoU/对账
  sheet.dxf/.svg/.pdf  装配后的交付图纸（需 --cadstack 指向抽取目录）
  sheet_fallback.svg   未提供 --cadstack 时的自绘 SVG（保证链条不因外部件缺失而断）

usage:
  python voxel_orthographic_drawing.py --audit <audit.json> --out <dir> \
      [--voxel-size 0.125] [--cadstack <tools/external/...cadstack>] [--title "..."]

exit: 0 ok · 1 nothing to project / export failed · 2 usage
"""

import argparse
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_VOXEL = 0.125          # 仅供 --voxel-size 显式指定时参考；默认走 auto 推断
COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))


def infer_voxel(vols, tol=1e-6):
    """从 (origin[1], minY) 与 (origin[1]+size[1]*v, maxY) 反推体素尺寸。

    实测教训：**体素尺寸不是全局常量**。SausageUFO 是 0.125 m，Tenshukaku 是 0.25 m；
    用错会让整张图纸缩放错一倍而看不出异常。这里用中位数估计，并用 maxY 交叉校验。
    返回 (voxel, evidence, warnings)。
    """
    ratios = []
    for v in vols:
        my, oy = v.get("minY"), (v.get("origin") or [None, None, None])[1]
        if my not in (None, 0) and oy is not None:
            ratios.append(oy / my)
    if not ratios:
        return DEFAULT_VOXEL, {"method": "fallback-default", "samples": 0}, \
               ["无 (origin[1], minY) 样本，体素尺寸退化到默认 %g；请用 --voxel-size 显式指定" % DEFAULT_VOXEL]
    ratios.sort()
    n = len(ratios)
    v = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2.0
    v = round(v, 6)
    evidence = {"method": "median(origin_y / minY)", "samples": n, "voxel": v,
                "ratioSpread": [round(ratios[0], 6), round(ratios[-1], 6)]}
    warnings = []
    if ratios[-1] - ratios[0] > 1e-4:
        warnings.append("同一包内 origin[1]/minY 比值不一致（%.6f ~ %.6f），可能存在多尺度体积"
                        % (ratios[0], ratios[-1]))
    for x in vols:
        oy, my, sy, ky = x.get("origin", [None, None, None])[1], x.get("minY"), \
                         (x.get("size") or [None, None, None])[1], x.get("maxY")
        if None in (oy, my, sy, ky):
            continue
        if abs(oy - my * v) > max(tol, 1e-3):
            warnings.append("%s: origin_y %.4f ≠ minY %.0f × %g = %.4f" % (x.get("name"), oy, my, v, my * v))
        if abs((oy + sy * v) - ky * v) > max(tol, 1e-3):
            warnings.append("%s: origin_y+size_y×v %.4f ≠ maxY %.0f × %g = %.4f（size_y 含非实心层？）"
                            % (x.get("name"), oy + sy * v, ky, v, ky * v))
    return v, evidence, warnings[:12]


# ---------------------------------------------------------------- inputs
def boxes_from_audit(path, voxel, voxel_mode="auto", y_source="minmax"):
    d = json.load(open(path, encoding="utf-8"))
    vols = d.get("volumes") or []
    warnings = []
    evidence = {"method": "explicit", "voxel": voxel}
    if voxel_mode == "auto":
        voxel, evidence, warnings = infer_voxel(vols)
    boxes = []
    for v in vols:
        ox, oy, oz = v["origin"]
        sx, sy, sz = v["size"]
        node_max = [ox + sx * voxel, oy + sy * voxel, oz + sz * voxel]
        y_min, y_max = oy, node_max[1]
        if y_source == "minmax" and v.get("minY") is not None and v.get("maxY") is not None:
            # 实测教训：size_y 是**节点盒高**，不是实心高度。
            # 例：Y星飞碟 HullDisc 节点盒 40 层→ 9.0 m，而实心只占 minY 32..maxY 43 → 4.0..5.5 m。
            # 直接拿节点盒会让高度虚高约 1.7 倍，且图纸上乍看看不出异常。
            y_min = v["minY"] * voxel
            y_max = (v["maxY"] + 1) * voxel
        boxes.append({
            "name": v.get("name") or v.get("group") or "volume",
            "group": v.get("group"),
            "solid": v.get("solid"),
            "minY_voxel": v.get("minY"),
            "maxY_voxel": v.get("maxY"),
            "xzSource": "node(origin+size)",
            "ySource": y_source if v.get("minY") is not None else "node(origin+size)",
            "nodeMax": [round(c, 6) for c in node_max],
            "min": [round(ox, 6), round(y_min, 6), round(oz, 6)],
            "max": [round(node_max[0], 6), round(y_max, 6), round(node_max[2], 6)],
            "voxels": [sx, sy, sz],
        })
    meta = {k: d.get(k) for k in ("subject", "format", "fingerprint", "layout_fingerprint",
                                  "material_fingerprint", "solid_cells", "volume_count",
                                  "ground_rate", "base_plane") if k in d}
    meta["voxelInference"] = evidence
    meta["voxelWarnings"] = warnings
    meta["note"] = ("X/Z 取节点盒（origin+size×voxel），Y 取 minY..maxY+1（实心层范围）；"
                    "两者不一致时在 voxelWarnings 里列出")
    return boxes, meta, voxel


def boxes_from_file(path, voxel):
    d = json.load(open(path, encoding="utf-8"))
    raw = d if isinstance(d, list) else (d.get("boxes") or d.get("volumes") or [])
    boxes = []
    for v in raw:
        if "min" in v and "max" in v:
            boxes.append(v)
            continue
        ox, oy, oz = v["origin"]
        sx, sy, sz = v["size"]
        boxes.append({"name": v.get("name", "box"), "min": [ox, oy, oz],
                      "max": [ox + sx * voxel, oy + sy * voxel, oz + sz * voxel],
                      "voxels": [sx, sy, sz]})
    return boxes, {}, voxel


# ---------------------------------------------------------------- projections
def rect_lines(x0, y0, x1, y1):
    return [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]


def project_box(b, view, up="y"):
    """World-space box -> 2D rectangle in that view's own plane.

    `up` 是关键，不是样式问题：审计数据里 `origin=[x, y, z]`，而 `minY/maxY` 就是**竖向**范围
    （UrhoX 米制 Y-up 左手系）。所以立面的高度轴是 **Y**，不是 Z。
    按 Z-up 误投影不会报错，但 front/side 会变成“俯视样的立面”——看着像图，其实完全不是立面。
    """
    mn, mx = b["min"], b["max"]
    if up == "y":
        height = (1, 1)
        front = (0, 1)      # 水平 X，竖向 Y
        side = (2, 1)       # 水平 Z，竖向 Y
        top = (0, 2)        # X / Z
        iso = lambda x, y, z: ((x - z) * COS30, (x + z) * SIN30 + y)   # noqa: E731
    else:
        height = (2, 2)
        front = (0, 2)      # 水平 X，竖向 Z
        side = (1, 2)       # 水平 Y，竖向 Z
        top = (0, 1)
        iso = lambda x, y, z: ((x - y) * COS30, (x + y) * SIN30 + z)   # noqa: E731
    if view == "front":
        return rect_lines(mn[front[0]], mn[height[0]], mx[front[0]], mx[height[0]])
    if view == "side":
        return rect_lines(mn[side[0]], mn[height[0]], mx[side[0]], mx[height[0]])
    if view == "top":
        return rect_lines(mn[top[0]], mn[top[1]], mx[top[0]], mx[top[1]])
    if view == "iso":
        pts = [iso(xs, ys, zs) for xs in (mn[0], mx[0]) for ys in (mn[1], mx[1])
               for zs in (mn[2], mx[2])]
        x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
        y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
        return rect_lines(x0, y0, x1, y1)
    raise ValueError(view)


def normalize(lines, gap=12.0, target=280.0):
    """Fit projected lines into a box of `target` mm and push them next to the origin."""
    xs = [c for l in lines for c in (l[0], l[2])]
    ys = [c for l in lines for c in (l[1], l[3])]
    if not xs:
        return [], (0.0, 0.0), 1.0
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
    k = min(target / w, target / h)
    out = [((l[0] - minx) * k, (l[1] - miny) * k, (l[2] - minx) * k, (l[3] - miny) * k) for l in lines]
    return out, (minx, miny), k


def build_projection(boxes, voxel=None, up="y"):
    views = {}
    for view in ("front", "side", "top", "iso"):
        rects, lines = [], []
        for b in sorted(boxes, key=lambda x: (x.get("name") or "", x["min"])):
            ls = project_box(b, view, up)
            lines.extend(ls)
            xs = [c for l in ls for c in (l[0], l[2])]
            ys = [c for l in ls for c in (l[1], l[3])]
            rects.append({"name": b.get("name"), "solid": b.get("solid"),
                          "rect": [round(min(xs), 6), round(min(ys), 6),
                                   round(max(xs), 6), round(max(ys), 6)]})
        outline = union_outline([r["rect"] for r in rects], voxel) if voxel else []
        drawn_src = outline if outline else lines
        drawn, origin, k = normalize(drawn_src)
        views[view] = {"rects": rects, "outline": [[round(v, 6) for v in s] for s in outline],
                       "lines_mm": [[round(v, 4) for v in l] for l in drawn],
                       "source": "outline(union)" if outline else "rects",
                       "worldOrigin": [round(origin[0], 6), round(origin[1], 6)],
                       "mmPerMeter": round(k, 6)}
    return views


def union_outline(rects, cell):
    """把重叠矩形并集变成一个正交轮廓（真正的立面剪影，而不是一堆重叠矩形边）。

    做法：按 cell（默认=检出的体素边长）栅格化，取“内→外”的边，再把共线的相邻段合并。
    cell 太大会把细节吃掉；脚本会把实际使用的 cell 写进 projection.json。
    """
    if not rects:
        return []
    x0 = min(r[0] for r in rects); x1 = max(r[2] for r in rects)
    y0 = min(r[1] for r in rects); y1 = max(r[3] for r in rects)
    if x1 <= x0 or y1 <= y0:
        return []
    cell = max(cell or 0, 1e-6)
    nx = max(1, int(math.ceil((x1 - x0) / cell)))
    ny = max(1, int(math.ceil((y1 - y0) / cell)))
    if nx * ny > 4_000_000:
        cell = max((x1 - x0) / 2000.0, (y1 - y0) / 2000.0)     # 限幅，避免内存爆
        nx = min(nx, 2000); ny = min(ny, 2000)
    g = bytearray(nx * ny)
    for rx0, ry0, rx1, ry1 in rects:
        i0 = max(0, int(math.floor((rx0 - x0) / cell)))
        i1 = min(nx - 1, int(math.ceil((rx1 - x0) / cell)) - 1)
        j0 = max(0, int(math.floor((ry0 - y0) / cell)))
        j1 = min(ny - 1, int(math.ceil((ry1 - y0) / cell)) - 1)
        for j in range(j0, j1 + 1):
            base = j * nx
            for i in range(i0, i1 + 1):
                g[base + i] = 1
    W = lambda i: round(x0 + i * cell, 6)     # noqa: E731
    H = lambda j: round(y0 + j * cell, 6)     # noqa: E731
    hseg, vseg = {}, {}
    for j in range(ny):
        base = j * nx
        for i in range(nx):
            if not g[base + i]:
                continue
            if j == 0 or not g[base - nx + i]:
                hseg.setdefault(j, []).append(i)
            if j == ny - 1 or not g[base + nx + i]:
                hseg.setdefault(j + 1, []).append(i)
            if i == 0 or not g[base + i - 1]:
                vseg.setdefault(i, []).append(j)
            if i == nx - 1 or not g[base + i + 1]:
                vseg.setdefault(i + 1, []).append(j)
    segs = []
    for j, xs in hseg.items():
        xs.sort()
        s = p = xs[0]
        for v in xs[1:] + [None]:
            if v is not None and v == p + 1:
                p = v; continue
            segs.append((W(s), H(j), W(p + 1), H(j)))
            if v is None:
                break
            s = p = v
    for i, ys in vseg.items():
        ys.sort()
        s = p = ys[0]
        for v in ys[1:] + [None]:
            if v is not None and v == p + 1:
                p = v; continue
            segs.append((W(i), H(s), W(i), H(p + 1)))
            if v is None:
                break
            s = p = v
    segs.sort()
    return segs


# ---------------------------------------------------------------- rendering
def write_fallback_svg(views, path, title):
    W, H = 420.0, 297.0
    cells = {"front": (30, 190), "side": (215, 190), "top": (30, 45), "iso": (215, 45)}
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">' % (W, H, W, H),
           '  <rect width="%g" height="%g" fill="white" stroke="black"/>' % (W, H),
           '  <text x="12" y="20" font-size="7" font-family="sans-serif">%s</text>' % _esc(title)]
    labels = {"front": "正立面 front (X-Z)", "side": "侧立面 side (Y-Z)",
              "top": "顶视 top (X-Y)", "iso": "轴测 iso"}
    for view, (ox, oy) in cells.items():
        v = views[view]
        out.append('  <g id="%s" transform="translate(%g,%g)">' % (view, ox, oy))
        out.append('    <text x="0" y="-4" font-size="6" font-family="sans-serif">%s</text>' % labels[view])
        for l in v["lines_mm"]:
            out.append('    <line x1="%g" y1="%g" x2="%g" y2="%g" stroke="black" stroke-width="0.4"/>'
                       % (l[0], -l[1], l[2], -l[3]))
        out.append('  </g>')
    out.append('</svg>')
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    return path


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_with_cadstack(views, cadstack_dir, out, title, subject):
    if cadstack_dir not in sys.path:
        sys.path.insert(0, cadstack_dir)
    from lib.drawing import DrawingGenerator, ViewType, ExportFormat   # noqa: E402

    VT = {"front": ViewType.FRONT, "side": ViewType.RIGHT, "top": ViewType.TOP,
          "iso": ViewType.ISOMETRIC}
    cells = {"front": (30, 190), "side": (215, 190), "top": (30, 45), "iso": (215, 45)}
    g = DrawingGenerator()
    g.set_model({"source": "voxel-occupancy", "subject": subject}, bounds=(0, 0, 0, 1, 1, 1))
    g.set_title(title)
    g.set_sheet_size("A3_L")
    g.set_title_block(title=title, part_number=subject, material="voxel",
                      scale="per view", drawn_by="voxel_orthographic_drawing.py",
                      date="2026-09-23", revision="r1")
    for view, vts in VT.items():
        v = g.add_view(vts, scale=1.0, offset=cells[view], label=view)
        # 覆盖掉外部件的包围盒占位投影，换成真投影
        v.lines = [(l[0], -l[1], l[2], -l[3]) for l in views[view]["lines_mm"]]
    results = {}
    for fmt, name in ((ExportFormat.SVG, "sheet.svg"), (ExportFormat.DXF, "sheet.dxf"),
                      (ExportFormat.PDF, "sheet.pdf")):
        p = os.path.join(out, name)
        try:
            ok = g.export(p, fmt)
            results[name] = {"ok": bool(ok), "bytes": os.path.getsize(p) if os.path.exists(p) else 0}
        except Exception as exc:
            results[name] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return results


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit")
    ap.add_argument("--boxes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--voxel-size", type=float, default=None,
                    help="体素边长（米）；不传则按 origin/minY 自动推断（推荐），实测算例 SausageUFO=0.125 · Tenshukaku=0.25")
    ap.add_argument("--cadstack", default=None)
    ap.add_argument("--y-source", choices=("minmax", "nodebox"), default="minmax",
                    help="Y 轴取值：minmax=用 minY..maxY 实心层范围（默认，修正节点盒虚高）；nodebox=用 origin+size")
    ap.add_argument("--up-axis", choices=("y", "z"), default="y",
                    help="竖向轴（默认 y = UrhoX/审计数据的 Y-up；立面的高度轴是它，不是样式问题）")
    ap.add_argument("--no-silhouette", action="store_true",
                    help="关闭并集轮廓，回到逐体积盒矩形（用于对照，默认开启轮廓）")
    ap.add_argument("--silhouette-cell", type=float, default=None,
                    help="栅格化步长（米）；默认=检出的体素边长")
    ap.add_argument("--title", default="Voxel occupancy — orthographic views")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not (a.audit or a.boxes):
        print("need --audit or --boxes")
        return 2
    if a.audit and not os.path.isfile(a.audit):
        print("audit not found:", a.audit)
        return 2

    boxes, meta, voxel = (boxes_from_audit(a.audit, a.voxel_size or DEFAULT_VOXEL,
                                           "explicit" if a.voxel_size else "auto", a.y_source)
                          if a.audit else boxes_from_file(a.boxes, a.voxel_size or DEFAULT_VOXEL))
    if not boxes:
        print("no volumes/boxes to project")
        return 1

    subject = meta.get("subject") or os.path.splitext(os.path.basename(a.audit or a.boxes))[0]
    views = build_projection(boxes, voxel if not a.no_silhouette else None, a.up_axis)
    os.makedirs(a.out, exist_ok=True)

    world = [[min(b["min"][i] for b in boxes) for i in range(3)],
             [max(b["max"][i] for b in boxes) for i in range(3)]]
    proj = {
        "schema": "urhox-voxel-orthographic-projection/1",
        "generatedAt": "2026-09-23",
        "subject": subject,
        "source": os.path.abspath(a.audit or a.boxes),
        "voxelSizeMeters": voxel,
        "boxCount": len(boxes),
        "worldBounds": {"min": world[0], "max": world[1],
                        "size": [round(world[1][i] - world[0][i], 6) for i in range(3)]},
        "upAxis": a.up_axis,
        "projectionBasis": (
            {"front": "X width / **Y height** (look along +Z)",
             "side": "Z depth / **Y height** (look along +X)",
             "top": "X width / Z depth (look down -Y)",
             "iso": "u=(x-z)*cos30, v=(x+z)*sin30+y"} if a.up_axis == "y" else
            {"front": "X width / Z height (look along +Y)",
             "side": "Y depth / Z height (look along +X)",
             "top": "X width / Y depth (look down -Z)",
             "iso": "u=(x-y)*cos30, v=(x+y)*sin30+z"}),
        "views": {k: {"rects": v["rects"], "outline": v["outline"], "source": v["source"],
                       "mmPerMeter": v["mmPerMeter"], "worldOrigin": v["worldOrigin"]}
                  for k, v in views.items()},
        "outline": {"basis": "2D 并集轮廓（栅格化取内→外边 + 共线合并）",
                    "cellMeters": a.silhouette_cell or voxel,
                    "note": "粒度=体积盒栅格化，不是引擎内逐体素占用；cell 越小越细但越大"},
        "boxes": boxes,
        "auditMeta": meta,
    }
    json.dump(proj, open(os.path.join(a.out, "projection.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    write_fallback_svg(views, os.path.join(a.out, "sheet_fallback.svg"), a.title + " — " + subject)

    results = {}
    if a.cadstack:
        if not os.path.isdir(a.cadstack):
            results = {"error": "cadstack dir not found: " + a.cadstack}
        else:
            results = write_with_cadstack(views, os.path.abspath(a.cadstack), a.out, a.title, subject)

    summary = {"subject": subject, "boxes": len(boxes),
               "worldSize": proj["worldBounds"]["size"],
               "views": {k: {"rects": len(v["rects"]), "outlineSegments": len(v["outline"])}
                         for k, v in views.items()},
               "outlineCell": proj["outline"]["cellMeters"],
               "exports": results, "out": a.out}
    if not a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))
    if isinstance(results, dict) and results.get("error"):
        return 1
    if any(isinstance(v, dict) and v.get("ok") is False for v in results.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
