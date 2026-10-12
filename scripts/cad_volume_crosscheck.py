#!/usr/bin/env python3
"""体积交叉校验：用 FreeCAD（第二实现）独立重算占用体积，与引擎审计对账。

为什么做：`14`/`18` 的既有纪律是"不同路线用不同第二实现"。体积是最容易跨实现复算的量——
引擎审计给 `solid_cells × voxel³`，FreeCAD 给 `Shape.Volume`，两者必须能对上（或差异可解释）。

**本工具算的是"上界校验"，不是"相等校验"**：几何源里的体积盒 X/Z 取的是**节点盒**
（审计未提供 X/Z 的实心范围），只有 Y 取了实心层范围，所以 FreeCAD 的并集体积
**必然 ≥ 审计实心体积**。它回答的是"盒子有没有超出实心范围太多"，不是"两者相等"。

usage:
  python cad_volume_crosscheck.py --projection <projection.json> --audit <audit.json> \
      --freecad-python "D:/tools/FreeCAD/bin/python.exe" \
      --cad-engine "<...>/skill-freecad/scripts/cad_engine.py" \
      [--work-dir <scratch>] [--json-out out.json] [--tolerance-ratio 1.35]

exit: 0 在上界容差内 · 1 超出（盒子显著大于实心）· 2 用法/执行错
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_steps(boxes, prefix="V"):
    steps = []
    names = []
    for i, b in enumerate(boxes):
        mn, mx = b["min"], b["max"]
        dx, dy, dz = (round(mx[j] - mn[j], 6) for j in range(3))
        if dx <= 0 or dy <= 0 or dz <= 0:
            continue
        name = "%s%02d" % (prefix, i)
        names.append(name)
        # FreeCAD makeBox(length,width,height) = (X, Y, Z)；世界是 Y-up，
        # 但本工具只比体积（轴序不影响体积），故仅记录映射作为注记。
        steps.append({"operation": "create_primitive",
                      "parameters": {"type": "box", "name": name,
                                     "length": dx, "width": dz, "height": dy}})
        steps.append({"operation": "transform",
                      "parameters": {"target": name,
                                     "translate": [round(mn[0], 6), round(mn[2], 6), round(mn[1], 6)]}})
    fused = names[0] if names else None
    for n in names[1:]:
        new = fused + "_fuse"
        steps.append({"operation": "boolean",
                      "parameters": {"type": "fuse", "base": fused, "tool": n, "name": new}})
        fused = new
    return steps, fused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projection", required=True)
    ap.add_argument("--audit", default=None)
    ap.add_argument("--expect-volume", type=float, default=None,
                    help="直接给期望体积（m³）；与 --audit 二选一")
    ap.add_argument("--freecad-python", required=True)
    ap.add_argument("--cad-engine", required=True)
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--tolerance-ratio", type=float, default=1.35,
                    help="上界容差：computed / expected 不得超过它")
    a = ap.parse_args()

    proj = json.load(open(a.projection, encoding="utf-8"))
    boxes = proj.get("boxes") or []
    if not boxes:
        print("no boxes in projection")
        return 2

    expect = a.expect_volume
    audit_meta = {}
    if expect is None:
        if not a.audit or not os.path.isfile(a.audit):
            print("need --audit or --expect-volume")
            return 2
        au = json.load(open(a.audit, encoding="utf-8"))
        cells = au.get("solid_cells")
        voxel = au.get("voxel_size") or proj.get("voxelSizeMeters")
        if cells is None or voxel is None:
            print("audit lacks solid_cells / voxel_size")
            return 2
        expect = cells * (voxel ** 3)
        audit_meta = {"solid_cells": cells, "voxel_size": voxel,
                      "audit_field": "solid_cells × voxel_size³"}

    engine_dir = os.path.dirname(os.path.abspath(a.cad_engine))
    work = a.work_dir or tempfile.mkdtemp(prefix="cadvol_")
    os.makedirs(work, exist_ok=True)

    steps, fused = build_steps(boxes)
    cmd_json = json.dumps({"operation": "batch", "parameters": {"steps": steps}})
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=engine_dir,
               FREECAD_PATH=os.path.dirname(a.freecad_python))
    proc = subprocess.run([a.freecad_python, os.path.abspath(a.cad_engine), cmd_json],
                          cwd=work, capture_output=True, text=True, env=env, timeout=1800)
    out = (proc.stdout or "").strip()
    try:
        res = json.loads(out[out.find("{"):])
    except Exception as exc:
        print("engine output not JSON: %s\n%s\n%s" % (exc, out[-800:], (proc.stderr or "")[-500:]))
        return 2

    objects = res.get("objects") or []
    vol_of = {o["name"]: o.get("volume") for o in objects}
    computed = vol_of.get(fused)
    if computed is None:
        computed = max([v for v in vol_of.values() if v] or [0])
    ratio = (computed / expect) if expect else None
    ok = ratio is not None and ratio <= a.tolerance_ratio

    info = {"schema": "urhox-cad-volume-crosscheck/1",
            "projection": os.path.abspath(a.projection),
            "boxCount": len(boxes), "fusedObject": fused,
            "expectedVolumeM3": round(expect, 4), "expectedSource": audit_meta or "explicit",
            "computedVolumeM3": round(float(computed), 4),
            "ratioComputedOverExpected": round(ratio, 4) if ratio else None,
            "toleranceRatio": a.tolerance_ratio,
            "verdict": "WITHIN-UPPER-BOUND" if ok else "EXCEEDS-UPPER-BOUND",
            "engineStatus": res.get("status"),
            "workDir": work,
            "note": ("这是上界校验：几何源的 X/Z 是节点盒，Y 是实心层范围，"
                     "故 computed ≥ expected；比值反映节点盒相对实心外扩多少。")}
    if a.json_out:
        json.dump(info, open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
