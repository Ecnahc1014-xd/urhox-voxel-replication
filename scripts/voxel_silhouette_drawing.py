#!/usr/bin/env python3
"""真体素剪影出图：从逐体素占用（voxel_occupancy_dump.py 的产物）出正交三视图。

与 `voxel_orthographic_drawing.py` 的分工：
  * 那个从**体积盒**（node box）投影 —— 快，但会把圆盘画成方块；
    实测体积比 5.07×（天守阁）、对战舰/飞碟这类对象外形完全不对。
  * **本工具从逐体素剪影投影** —— 才是真三视图。
给 `--compare-boxes <box 版 projection.json>` 时会打印两者的差异（面积比 / 包围盒比），
用来回答"盒版到底差多少"。

输入：`urhox-occupancy-masks/1`（见 `voxel_occupancy_dump.py`）
      views.{front,side,top} 各带 base64 打包的位图 + h/v 尺寸 + 轴名
输出：`projection.json`（voxel 级：剪影轮廓段 + 世界包围盒 + 掩膜统计）
      `sheet.svg` / `sheet.dxf` / `sheet.pdf`（复用外部绘制件的装配与导出层）

usage:
  python voxel_silhouette_drawing.py --occupancy <occ.json> --out <dir> \
      [--cadstack <cadstack 目录>] [--title "..."] [--compare-boxes <box_projection.json>]

exit: 0 ok · 1 无数据/导出失败 · 2 用法错
"""

import argparse
import base64
from datetime import date
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))


def unpack(b64, nbits):
    raw = base64.b64decode(b64)
    out = []
    for b in raw:
        for j in range(8):
            out.append(bool(b & (1 << j)))
    return out[:nbits]


def mask_outline(bits, h, v):
    """位图 → 边界线段（格坐标）。返回 [(x0,y0,x1,y1)]，已合并共线段。"""
    if len(bits) < h * v:
        bits = bits + [False] * (h * v - len(bits))
    at = lambda i, j: bits[j * h + i] if (0 <= i < h and 0 <= j < v) else False
    hseg, vseg = {}, {}
    for j in range(v):
        for i in range(h):
            if not at(i, j):
                continue
            if not at(i, j - 1):
                hseg.setdefault(j, []).append(i)
            if not at(i, j + 1):
                hseg.setdefault(j + 1, []).append(i)
            if not at(i - 1, j):
                vseg.setdefault(i, []).append(j)
            if not at(i + 1, j):
                vseg.setdefault(i + 1, []).append(j)
    segs = []
    for j, xs in hseg.items():
        for a, b in runs(sorted(xs)):
            segs.append((a, j, b, j))
    for i, ys in vseg.items():
        for a, b in runs(sorted(ys)):
            segs.append((i, a, i, b))
    segs.sort()
    return segs


def runs(sorted_ints):
    out, s = [], None
    p = None
    for v in sorted_ints:
        if s is None:
            s = p = v
            continue
        if v == p + 1:
            p = v
            continue
        out.append((s, p + 1))
        s = p = v
    if s is not None:
        out.append((s, p + 1))
    return out


def normalize(lines, target=280.0):
    xs = [c for l in lines for c in (l[0], l[2])]
    ys = [c for l in lines for c in (l[1], l[3])]
    if not xs:
        return [], (0.0, 0.0), 1.0
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
    k = min(target / w, target / h)
    return [((l[0] - minx) * k, (l[1] - miny) * k, (l[2] - minx) * k, (l[3] - miny) * k)
            for l in lines], (minx, miny), k


def occupied_rectangles(bits, width, height, horizontal_origin, vertical_origin, voxel_size):
    rectangles = []
    for row_index in range(height):
        occupied_columns = [column for column in range(width) if bits[row_index * width + column]]
        for start, stop in runs(occupied_columns):
            rectangles.append({'rect': [(horizontal_origin + start) * voxel_size,
                                        (vertical_origin + row_index) * voxel_size,
                                        (horizontal_origin + stop) * voxel_size,
                                        (vertical_origin + row_index + 1) * voxel_size]})
    return rectangles


def build(occ):
    vs = occ["voxelSizeMeters"]
    mn = occ["bbox"]["min"]
    views = {}
    for name in ("front", "side", "top", "iso"):
        if name == "iso":
            # 轴测：把三个剪影并起来做一个粗略投影盒（保留信息，不假装是真轴测立体）
            continue
        v = occ["views"][name]
        h, vv = v["h"], v["v"]
        bits = unpack(v["bits"], h * vv)
        segs_cell = mask_outline(bits, h, vv)
        # 格坐标 → 世界米：world = (min_index + i) * vs
        off_h = mn[0] if v["hAxis"] == "x" else mn[2]
        off_v = mn[1] if v["vAxis"] == "y" else mn[2]
        segs_world = [((off_h + a) * vs, (off_v + b) * vs,
                       (off_h + c) * vs, (off_v + d) * vs) for (a, b, c, d) in segs_cell]
        drawn, origin, k = normalize(segs_world)
        views[name] = {
            "h": h, "v": vv, "hAxis": v["hAxis"], "vAxis": v["vAxis"],
            "onCells": sum(bits), "outlineSegments": len(segs_cell),
            "outline": [[round(c, 4) for c in s] for s in segs_world],
            "rects": occupied_rectangles(bits, h, vv, off_h, off_v, vs),
            "lines_mm": [[round(c, 4) for c in s] for s in drawn],
            "worldOrigin": [round(origin[0], 4), round(origin[1], 4)],
            "mmPerMeter": round(k, 6),
        }
    # 轴测：用 top 的剪影做斜投影占位（标注清楚，不冒充真 3D）
    if "top" in views:
        t = views["top"]
        segs = []
        for s in t["outline"]:
            u0 = (s[0] - s[1]) * COS30
            v0 = (s[0] + s[1]) * SIN30
            u1 = (s[2] - s[3]) * COS30
            v1 = (s[2] + s[3]) * SIN30
            segs.append((u0, v0, u1, v1))
        drawn, origin, k = normalize(segs)
        views["iso"] = {"h": t["h"], "v": t["v"], "hAxis": "x-z", "vAxis": "x+z",
                        "onCells": t["onCells"], "outlineSegments": len(segs),
                        "outline": [[round(c, 4) for c in s] for s in segs],
                        "lines_mm": [[round(c, 4) for c in s] for s in drawn],
                        "worldOrigin": [round(origin[0], 4), round(origin[1], 4)],
                        "mmPerMeter": round(k, 6), "approx": "由 top 剪影斜投影，仅示意"}
    common_scale = min(
        min(165.0 / max(max(segment[0] for segment in view['outline']) - view['worldOrigin'][0],
                        max(segment[2] for segment in view['outline']) - view['worldOrigin'][0], 1e-9),
            100.0 / max(max(segment[1] for segment in view['outline']) - view['worldOrigin'][1],
                        max(segment[3] for segment in view['outline']) - view['worldOrigin'][1], 1e-9))
        for view in views.values() if view['outline'])
    for view in views.values():
        horizontal_origin, vertical_origin = view['worldOrigin']
        view['lines_mm'] = [[round((segment[0] - horizontal_origin) * common_scale, 4),
                             round((segment[1] - vertical_origin) * common_scale, 4),
                             round((segment[2] - horizontal_origin) * common_scale, 4),
                             round((segment[3] - vertical_origin) * common_scale, 4)]
                            for segment in view['outline']]
        view['mmPerMeter'] = round(common_scale, 6)
    return views


def write_cadstack(views, cadstack, out, title, subject):
    if cadstack not in sys.path:
        sys.path.insert(0, cadstack)
    from lib.drawing import DrawingGenerator, ViewType, ExportFormat
    VT = {"front": ViewType.FRONT, "side": ViewType.RIGHT, "top": ViewType.TOP,
          "iso": ViewType.ISOMETRIC}
    cells = {"front": (30, 155), "side": (215, 155), "top": (30, 35), "iso": (215, 35)}
    g = DrawingGenerator()
    g.set_model({"source": "voxel-occupancy"}, bounds=(0, 0, 0, 1, 1, 1))
    g.set_title(title)
    g.set_sheet_size("A3_L")
    g.set_title_block(title=title, part_number=subject, material="voxel",
                      scale="per view", drawn_by="voxel_silhouette_drawing.py",
                      date=date.today().isoformat(), revision="r1")
    drawing_views = {}
    for view, vts in VT.items():
        if view not in views:
            continue
        vw = g.add_view(vts, scale=1.0, offset=cells[view], label=view)
        vw.lines = [tuple(segment) for segment in views[view]['lines_mm']]
        vw.dimensions.clear()
        drawing_views[view] = vw
    res = {}
    for fmt, name in ((ExportFormat.SVG, "sheet.svg"), (ExportFormat.DXF, "sheet.dxf"),
                      (ExportFormat.PDF, "sheet.pdf")):
        p = os.path.join(out, name)
        try:
            for view_name, drawing_view in drawing_views.items():
                horizontal_offset, vertical_offset = cells[view_name]
                drawing_view.offset = (horizontal_offset,
                                       297 - vertical_offset if fmt == ExportFormat.SVG else vertical_offset)
                drawing_view.lines = [tuple(segment) if fmt != ExportFormat.SVG else
                                      (segment[0], -segment[1], segment[2], -segment[3])
                                      for segment in views[view_name]['lines_mm']]
            ok = g.export(p, fmt)
            res[name] = {"ok": bool(ok), "bytes": os.path.getsize(p) if os.path.exists(p) else 0}
        except Exception as exc:
            res[name] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return res


def compare_boxes(occ, box_proj_path, views):
    """与体积盒版对照：面积比 / 包围盒比。"""
    box = json.load(open(box_proj_path, encoding="utf-8"))
    vs = occ["voxelSizeMeters"]
    out = {}
    for name in ("front", "side", "top"):
        if name not in views or name not in box.get("views", {}):
            continue
        v = occ["views"][name]
        vox_area = sum(unpack(v["bits"], v["h"] * v["v"])) * vs * vs
        rects = box["views"][name]["rects"]
        box_area = 0.0
        for r in rects:
            x0, y0, x1, y1 = r["rect"]
            box_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
        # 盒版面积是矩形并集的上界（有重叠），这里给"盒面积之和"与"体素面积"的比
        h0 = min(r["rect"][0] for r in rects); h1 = max(r["rect"][2] for r in rects)
        v0 = min(r["rect"][1] for r in rects); v1 = max(r["rect"][3] for r in rects)
        out[name] = {
            "voxelSilhouetteAreaM2": round(vox_area, 3),
            "boxRectAreaSumM2": round(box_area, 3),
            "boxRectOverVoxel": round(box_area / vox_area, 3) if vox_area else None,
            "boxExtentM": [round(h1 - h0, 3), round(v1 - v0, 3)],
            "voxelExtentM": [round(v["h"] * vs, 3), round(v["v"] * vs, 3)],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--occupancy", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cadstack", default=None)
    ap.add_argument("--title", default="Voxel silhouette — orthographic views")
    ap.add_argument("--compare-boxes", default=None)
    a = ap.parse_args()

    if not os.path.isfile(a.occupancy):
        print("occupancy not found:", a.occupancy)
        return 2
    if a.cadstack and not os.path.isfile(os.path.join(a.cadstack, 'lib', 'drawing.py')):
        print('cadstack drawing backend not found:', a.cadstack)
        return 2
    occ = json.load(open(a.occupancy, encoding="utf-8"))
    if occ.get("schema") != "urhox-occupancy-masks/1":
        print("unexpected schema:", occ.get("schema"))
        return 2

    views = build(occ)
    os.makedirs(a.out, exist_ok=True)
    vs = occ["voxelSizeMeters"]
    mn, mx = occ["bbox"]["min"], occ["bbox"]["max"]
    proj = {
        "schema": "urhox-voxel-projection/1",
        "subject": occ["subject"],
        "source": os.path.abspath(a.occupancy),
        "sourceKind": "voxel-occupancy-masks",
        "voxelSizeMeters": vs,
        "cellCount": occ["cellCount"],
        "trueSolidVolumeM3": round(occ["cellCount"] * vs ** 3, 3),
        "worldBounds": {"min": [round(c * vs, 4) for c in mn],
                        "max": [round((c + 1) * vs, 4) for c in mx],
                        "size": [round((mx[i] - mn[i] + 1) * vs, 4) for i in range(3)]},
        "upAxis": occ.get("upAxis", "y"),
        "views": {k: {kk: vv for kk, vv in v.items() if kk != "lines_mm"} for k, v in views.items()},
        "linesMm": {k: v["lines_mm"] for k, v in views.items()},
        "note": ("剪影来自**逐体素占用**（kit.cells），不是体积盒；"
                 "轮廓为掩膜边界（无遮挡消隐），轴测为 top 剪影斜投影占位。"),
    }
    if a.compare_boxes:
        proj["comparisonVsBoxModel"] = compare_boxes(occ, a.compare_boxes, views)
    json.dump(proj, open(os.path.join(a.out, "projection.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    res = {}
    if a.cadstack and os.path.isdir(a.cadstack):
        res = write_cadstack(views, os.path.abspath(a.cadstack), a.out, a.title, occ["subject"])
    summary = {
        "subject": occ["subject"], "cells": occ["cellCount"],
        "worldSizeM": proj["worldBounds"]["size"], "trueVolumeM3": proj["trueSolidVolumeM3"],
        "views": {k: {"onCells": v["onCells"], "segments": v["outlineSegments"],
                      "mmPerMeter": v["mmPerMeter"]} for k, v in views.items()},
        "exports": res,
        "artifactScope": 'geometry-and-drawing-files' if a.cadstack else 'geometry-only',
        "drawingLimitations": ['no dimensions or hidden-line removal',
                                 'isometric view is a top-silhouette schematic'],
    }
    if "comparisonVsBoxModel" in proj:
        summary["vsBoxModel"] = proj["comparisonVsBoxModel"]
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if any(isinstance(x, dict) and x.get("ok") is False for x in res.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
