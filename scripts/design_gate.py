#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设计驱动模式（design-driven）的通用门禁 G0–G8。

适用：**没有外部真值**的场景制造任务（设定稿 / brief 驱动）。
不适用：复刻任务的"像不像"验收——那用 `references/04` 四表 + `19` 入包闸；两者不可互替。

输入（全部为项目侧产物，脚本只读）：
  --declarations 设计声明 JSON（本案唯一权威的机器可读投影）
  --blueprint    Blueprint format 2（米制盒 + owner + group + 材质槽；可选 openings 语义层）
  --occupancy    占用栅格 .npz（键 `grid`，索引 [y][z][x]）
  --map          可选：iso-map-editor 存档 v4（提供 walkable 瓦片）
  --out          输出 JSON（判据 + 明细）

判据（可裁剪，但裁剪必须留痕：`--skip G3` 时输出会写 `skipped[]`）：
  G0 结构合法：盒尺寸为正 + 边界落在体素网格上
  G1 边界：逐轴落在声明 site 内（越界即 FAIL，不得静默裁剪）
  G2 接地：contact_groups 的盒脚与地面实心接触
  G3 高度带：檐口落带内、总高 ≤ 上限、**屋脊 − 檐口 = 半进深 × 坡度**（规则推导一致性）
  G4 覆盖：屋顶在水平投影上覆盖墙体（每 structure）
  G5 开口归属：每个 opening 落在其 owner 墙体范围内，且外侧邻接可行走面
  G6 可达：声明的点对之间存在可行走路径（BFS）
  G7 必需项：group_present / min_count 两类谓词
  G8 语义分组：所有盒的 group ∈ 声明集合

退出码：0 全过 · 1 有 FAIL · 2 用法/IO 错 · 3 输入不足以判定（缺引用/缺策略）
"""
import argparse
import json
import os
import sys
from collections import deque

import numpy as np

sys.dont_write_bytecode = True


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def vox_i(v, o, s):
    return int(round((v - o) / s))


def gate(decl, bp, occ, amap, skip):
    s = float(decl.get("voxel_m", 0.5))
    site = decl["site"]
    boxes = bp["boxes"]
    checks, detail, skipped = {}, {}, list(skip)
    groups = {b["group"] for b in boxes}

    if "G0" in skip:
        pass
    else:
        bad = []
        for b in boxes:
            m, sz = b["min"], b["size"]
            if any(v <= 0 for v in sz):
                bad.append({"name": b["name"], "why": "size<=0", "size": sz})
                continue
            for a in range(3):
                for v in (m[a], m[a] + sz[a]):
                    if not near(v / s, round(v / s), 1e-6):
                        bad.append({"name": b["name"], "why": "off-grid", "axis": a, "value": v})
                        break
        checks["G0_struct"] = not bad
        detail["G0_struct"] = bad[:8]

    if "G1" in skip:
        pass
    else:
        over = []
        for b in boxes:
            m, sz = b["min"], b["size"]
            axes = "xyz"
            for a in range(3):
                lo = site[axes[a]][0]
                hi = site[axes[a]][1]
                if m[a] < lo - 1e-6 or m[a] + sz[a] > hi + 1e-6:
                    over.append({"name": b["name"], "axis": axes[a],
                                 "span": [m[a], m[a] + sz[a]], "site": [lo, hi]})
                    break
        checks["G1_bbox"] = not over
        detail["G1_bbox"] = over[:8]

    if "G2" in skip:
        pass
    else:
        y0 = site["y"][0]
        base = vox_i(0.0, y0, s) - 1
        bad = []
        for b in boxes:
            if b["group"] not in decl.get("contact_groups", []):
                continue
            if b["min"][1] > 0.1:
                continue
            x0 = vox_i(b["min"][0], 0.0, s); x1 = x0 + int(round(b["size"][0] / s))
            z0 = vox_i(b["min"][2], 0.0, s); z1 = z0 + int(round(b["size"][2] / s))
            if base < 0 or not (occ[base, z0:z1, x0:x1] > 0).all():
                bad.append({"name": b["name"], "why": "no support under footprint"})
        checks["G2_contact"] = not bad
        detail["G2_contact"] = bad[:8]

    structs = decl.get("structures", [])
    if "G3" in skip or not structs:
        if not structs and "G3" not in skip:
            skipped.append("G3(no structures declared)")
    else:
        rows, ok = {}, True
        for st in structs:
            sid = st["id"]
            wall = [b for b in boxes if b.get("owner") == sid and b["group"] in st.get("wall_groups", [])]
            roof = [b for b in boxes if b.get("owner") == sid and b["group"] in st.get("roof_groups", [])]
            if not wall:
                rows[sid] = {"why": "missing wall boxes"}
                ok = False
                continue
            eave = max(b["min"][1] + b["size"][1] for b in wall)
            if not st.get("require_roof", True):
                band = st.get("ceiling_band", st.get("eave_band", [0.0, 1e9]))
                row_ok = band[0] <= eave <= band[1]
                rows[sid] = {"ceiling": round(eave, 3), "band": band, "pass": row_ok}
                ok = ok and row_ok
                continue
            if not roof:
                rows[sid] = {"why": "missing roof boxes"}
                ok = False
                continue
            ridge = max(b["min"][1] + b["size"][1] for b in roof)
            z0 = min(b["min"][2] for b in wall); z1 = max(b["min"][2] + b["size"][2] for b in wall)
            expect = (z1 - z0) / 2.0 * float(st.get("slope", decl.get("slope", 0.5)))
            band = st.get("eave_band", [0.0, 1e9])
            ok_row = (band[0] <= eave <= band[1]
                      and ridge <= float(st.get("max_height_m", 1e9)) + 1e-6
                      and abs((ridge - eave) - expect) <= float(st.get("ridge_tol_m", 0.5)) + 1e-6)
            rows[sid] = {"eave": round(eave, 3), "ridge": round(ridge, 3),
                         "expected_rise": round(expect, 3), "pass": ok_row}
            ok = ok and ok_row
        checks["G3_height_bands"] = ok
        detail["G3_height_bands"] = rows

    roofed = [st for st in structs if st.get("require_roof", True)]
    if "G4" in skip or not roofed:
        if not roofed and "G4" not in skip:
            skipped.append("G4(no roof-bearing structures)")
    else:
        rows, ok = {}, True
        for st in roofed:
            sid = st["id"]
            wall = [b for b in boxes if b.get("owner") == sid and b["group"] in st.get("wall_groups", [])]
            roof = [b for b in boxes if b.get("owner") == sid and b["group"] in st.get("roof_groups", [])]
            if not wall or not roof:
                rows[sid] = False
                ok = False
                continue
            wx0 = min(b["min"][0] for b in wall); wx1 = max(b["min"][0] + b["size"][0] for b in wall)
            wz0 = min(b["min"][2] for b in wall); wz1 = max(b["min"][2] + b["size"][2] for b in wall)
            rx0 = min(b["min"][0] for b in roof); rx1 = max(b["min"][0] + b["size"][0] for b in roof)
            rz0 = min(b["min"][2] for b in roof); rz1 = max(b["min"][2] + b["size"][2] for b in roof)
            rows[sid] = bool(rx0 <= wx0 + 1e-6 and rx1 >= wx1 - 1e-6
                             and rz0 <= wz0 + 1e-6 and rz1 >= wz1 - 1e-6)
            ok = ok and rows[sid]
        checks["G4_roof_covers_wall"] = ok
        detail["G4_roof_covers_wall"] = rows

    walk = None
    if amap is not None and decl.get("walkable_tile_ids"):
        tile = float(amap.get("meta", {}).get("tile_m", decl.get("tile_m", 4.0)))
        walk = np.zeros(occ.shape[1:], dtype=bool)
        gid = amap["layers"][0]["tiles"] if amap.get("layers") else []
        for t in gid:
            if t["id"] not in decl["walkable_tile_ids"]:
                continue
            x0 = vox_i((t["x"] - 1) * tile, 0.0, s); x1 = x0 + int(round(tile / s))
            z0 = vox_i((t["y"] - 1) * tile, 0.0, s); z1 = z0 + int(round(tile / s))
            walk[z0:z1, x0:x1] = True

    if "G5" in skip or not decl.get("openings"):
        if not decl.get("openings") and "G5" not in skip:
            skipped.append("G5(no openings declared)")
    else:
        rows, ok = {}, True
        base = vox_i(0.0, site["y"][0], s) - 1
        for op in decl["openings"]:
            sid = op.get("owner")
            wall = [b for b in boxes if b.get("owner") == sid
                    and b["group"] in [g for st in structs if st["id"] == sid for g in st.get("wall_groups", [])]]
            if not wall:
                rows[op["id"]] = {"why": "owner has no wall boxes"}
                ok = False
                continue
            wx0 = min(b["min"][0] for b in wall); wx1 = max(b["min"][0] + b["size"][0] for b in wall)
            wz0 = min(b["min"][2] for b in wall); wz1 = max(b["min"][2] + b["size"][2] for b in wall)
            m = op["rect_m"]
            inside = (m[0] >= wx0 - 1e-6 and m[0] + m[3] <= wx1 + 1e-6
                      and m[2] >= wz0 - 1e-6 and m[2] + m[5] <= wz1 + 1e-6)
            adj = None
            if walk is not None:
                cx = vox_i(m[0] + m[3] / 2, 0.0, s)
                cz = vox_i(m[2] + m[5] / 2, 0.0, s)
                adj = bool(walk[max(0, cz - 3):cz + 4, max(0, cx - 3):cx + 4].any())
            row = {"inside_wall_bbox": bool(inside), "adjacent_walkable": adj}
            row["pass"] = bool(inside and (adj is not False))
            rows[op["id"]] = row
            ok = ok and row["pass"]
        checks["G5_opening_attribution"] = ok
        detail["G5_opening_attribution"] = rows

    if "G6" in skip or not decl.get("reachability"):
        if not decl.get("reachability") and "G6" not in skip:
            skipped.append("G6(no reachability pairs declared)")
    elif walk is None:
        checks["G6_reachability"] = False
        detail["G6_reachability"] = {"why": "walkable plane unavailable（缺 --map 或 walkable_tile_ids）"}
    else:
        rows, ok = {}, True
        for pair in decl["reachability"]:
            a = (vox_i(pair["a"][0], 0.0, s), vox_i(pair["a"][1], 0.0, s))
            b = (vox_i(pair["b"][0], 0.0, s), vox_i(pair["b"][1], 0.0, s))

            def snap(p):
                best, bd = None, 1 << 30
                for dz in range(-6, 7):
                    for dx in range(-6, 7):
                        x, z = p[0] + dx, p[1] + dz
                        if 0 <= x < walk.shape[1] and 0 <= z < walk.shape[0] and walk[z, x]:
                            d = dx * dx + dz * dz
                            if d < bd:
                                best, bd = (x, z), d
                return best

            sa, sb = snap(a), snap(b)
            okp = False
            if sa and sb:
                seen = np.zeros_like(walk, dtype=bool)
                dq = deque([sa]); seen[sa[1], sa[0]] = True
                while dq:
                    x, z = dq.popleft()
                    if (x, z) == sb:
                        okp = True
                        break
                    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, nz = x + dx, z + dz
                        if 0 <= nx < walk.shape[1] and 0 <= nz < walk.shape[0] \
                           and walk[nz, nx] and not seen[nz, nx]:
                            seen[nz, nx] = True; dq.append((nx, nz))
            rows[pair["id"]] = {"reachable": okp, "snapped": [sa, sb]}
            ok = ok and okp
        checks["G6_reachability"] = ok
        detail["G6_reachability"] = rows

    if "G7" in skip or not decl.get("required_items"):
        if not decl.get("required_items") and "G7" not in skip:
            skipped.append("G7(no required_items declared)")
    else:
        rows, ok = {}, True
        for item in decl["required_items"]:
            kind = item["kind"]
            if kind == "group_present":
                good = item["group"] in groups
            elif kind == "min_count":
                good = sum(1 for b in boxes if b["group"] == item["group"]) >= int(item["count"])
            elif kind == "volume_min_count":
                owners = {b.get("owner") for b in boxes if b["group"] == item["group"]}
                good = len(owners) >= int(item["count"])
            elif kind == "openings_min_count":
                good = len(decl.get("openings", [])) >= int(item["count"])
            else:
                good = False
            rows[item["id"]] = {"kind": kind, "pass": bool(good)}
            ok = ok and good
        checks["G7_required_items"] = ok
        detail["G7_required_items"] = rows

    if "G8" not in skip:
        unknown = sorted(groups - set(decl.get("groups", [])))
        checks["G8_groups"] = not unknown
        detail["G8_groups"] = {"unknown": unknown, "present": sorted(groups)}

    verdict = "PASS" if (checks and all(checks.values())) else "FAIL"
    return {"case": decl.get("case"), "input_contract": decl.get("input_contract", "design-driven"),
            "canon": decl.get("canon"), "checks": checks, "detail": detail, "skipped": skipped,
            "verdict": verdict,
            "claims_allowed": ["合规", "自洽", "可达", "可复现"],
            "claims_forbidden": ["好看", "好玩", "原创性", "与任何外部参考一致"],
            "note": "设计驱动模式门禁：无外部真值，不替代复刻模式的四表与入包闸"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--declarations", required=True)
    ap.add_argument("--blueprint", required=True)
    ap.add_argument("--occupancy", required=True)
    ap.add_argument("--map", dest="amap")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()
    for p in (a.declarations, a.blueprint, a.occupancy):
        if not os.path.isfile(p):
            print(f"缺输入：{p}", file=sys.stderr)
            return 3
    decl = load(a.declarations)
    bp = load(a.blueprint)
    occ = np.load(a.occupancy)
    grid = occ["grid"] if "grid" in occ else occ[occ.files[0]]
    amap = load(a.amap) if a.amap and os.path.isfile(a.amap) else None
    res = gate(decl, bp, grid, amap, a.skip)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    if not a.json_only:
        for k, v in res["checks"].items():
            print(("  PASS " if v else "  FAIL ") + k)
        if res["skipped"]:
            print("  裁剪（必须留痕）:", res["skipped"])
        print(f"[design_gate] {res['case']} verdict = {res['verdict']}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
