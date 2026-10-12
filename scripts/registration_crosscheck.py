#!/usr/bin/env python3
"""配准 / 标定防伪四条 — hold-out · independent consistency · zero-residual · clip completeness.

判据的**唯一出处**：`references/02-drafting-and-registration.md` §4.6。
本脚本只产读数与结论（通过 / 未通过），不改任何工程数据、不重拟合变换：
它消费**已归档**的拟合参数与已归档的点集，去问“这次验证是不是自证”。

usage:
  PYTHONUTF8=1 python registration_crosscheck.py \\
      --spec <candidate.json> [--control <control.json>] [--out <目录>] [--json-only]

spec 字段（见 §4.6 最小算例）：
{
  "name": "...", "fit": {"kind": "similarity_offset", "scale": s, "offset": [tx,ty],
                         "crop_origin": [x0,y0]?, "residual_px": 0.02},
  "holdout": ["T01"], "fitted_on": ["T02", ...],
  "pois": {"file": "...", "format": "tsv_obc_game", "classes": [...]?},
  "clip": {"image": "...png", "width": 560, "height": 740},
  "land_mask": {"mode": "floodfill_sea", "hue": [165,215], "sat_min": 20, "val_min": 60},
  "thresholds": {"land_rate": 0.80, "margin_vs_baseline": 0.10}
}

exit: 0 通过 · 1 未通过 · 2 用法 / 输入缺失
"""

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image

try:
    from scipy import ndimage as _ndi
    _LABEL_BACKEND = "scipy.ndimage.label"
except ImportError:                                       # pragma: no cover
    try:
        import cv2 as _cv2
        _ndi = None
        _LABEL_BACKEND = "cv2.connectedComponents"
    except ImportError:
        _ndi = None
        _cv2 = None
        _LABEL_BACKEND = "none(no-connectivity)"

ZERO_RESIDUAL_PX = 0.5          # §4.6 第 3 条：低于它即触发自证警示（标定值，见 02 §4.6）


# ----------------------------------------------------------------- land mask
def border_connected_water(rgb, mask_spec):
    """水 = 与图像边界连通的“水色簇”；陆 = 其余。返回 (land: bool[H,W], backend, water_frac)"""
    hsv = np.array(Image.fromarray(rgb).convert("HSV"))
    hue = hsv[:, :, 0].astype(int) * 360 // 255
    sat, val = hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    lo, hi = mask_spec.get("hue", [165, 215])
    water = (hue >= lo) & (hue <= hi) & (sat >= mask_spec.get("sat_min", 20)) & \
            (val >= mask_spec.get("val_min", 60))
    if _LABEL_BACKEND.startswith("scipy"):
        lab, _n = _ndi.label(water)
    elif _LABEL_BACKEND.startswith("cv2"):
        n, lab = _cv2.connectedComponents(water.astype(np.uint8))
    else:                                                 # degraded: 不做连通性
        return ~water, _LABEL_BACKEND, float(water.mean())
    border = set(lab[0].tolist()) | set(lab[-1].tolist()) | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    sea = np.isin(lab, list(border))
    return ~sea, _LABEL_BACKEND, float(sea.mean())


# ----------------------------------------------------------------- POI reader
def read_pois(spec):
    """返回 (names, xy_px) —— 已经换算成该基准的像素坐标（含 crop_origin 扣除）。"""
    p = spec["pois"]["file"]
    fmt = spec.get("pois", {}).get("format", "tsv_obc_game")
    fit = spec["fit"]
    kind = fit.get("kind", "similarity_offset")
    names, xy = [], []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name = parts[1]
            m_obc = re.search(r"obc\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", parts[2])
            m_game = re.search(r"game\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", parts[3])
            if kind == "world_affine":
                # 游戏世界坐标 → 地图像素：p = s * [x, -z] @ R + t（与 r13 标定的 param 同式）
                if not m_game:
                    continue
                Rm = np.array(fit["R"], dtype=float)
                v = np.array([float(m_game.group(1)), -float(m_game.group(2))], dtype=float)
                q = fit["scale"] * (v @ Rm) + np.array(fit["t"], dtype=float)
                x, y = float(q[0]), float(q[1])
            else:
                if not m_obc:
                    continue
                sc = fit["scale"]
                sx, sy = (sc, sc) if isinstance(sc, (int, float)) else (sc[0], sc[1])
                x = sx * float(m_obc.group(1)) + fit["offset"][0]
                y = sy * float(m_obc.group(2)) + fit["offset"][1]
            if "crop_origin" in fit:
                x -= fit["crop_origin"][0]
                y -= fit["crop_origin"][1]
            names.append(name)
            xy.append((x, y))
    if not names:
        raise SystemExit("FAIL 点集为空：%s（空输入不是通过）" % p)
    return names, np.array(xy, dtype=float)


# ----------------------------------------------------------------- checks
def run_spec(spec, control_land_rate=None):
    R = {"name": spec.get("name"), "checks": []}

    # 1) 留出法
    holdout = spec.get("holdout") or []
    R["holdout"] = holdout
    R["checks"].append({
        "check": "1 留出法",
        "verdict": "PASS" if holdout else "FAIL",
        "detail": ("留出锚点 %s 未参与拟合" % holdout) if holdout else
                  "未声明 holdout（fitted_on=%s）⇒ 只能叫自洽" % (spec.get("fitted_on") or "未知"),
    })

    # 2) 残差与零残差警示
    resid = spec["fit"].get("residual_px")
    suspect = resid is not None and resid < ZERO_RESIDUAL_PX
    R["residual_px"] = resid
    R["zero_residual_suspect"] = bool(suspect)
    R["checks"].append({
        "check": "3 零残差警示",
        "verdict": "WARN" if suspect else "PASS",
        "detail": ("残差 %.3f px < %.1f px ⇒ 自证嫌疑成立：必须同时出示留出法与独立一致性"
                   % (resid, ZERO_RESIDUAL_PX)) if suspect else
                  ("残差 %.3f px" % resid if resid is not None else "未登记残差"),
    })

    # 3) 独立一致性 + 4) 裁剪完整性
    clip = spec["clip"]
    img = np.array(Image.open(clip["image"]).convert("RGB"))
    H, W = img.shape[:2]
    land, backend, water_frac = border_connected_water(img, spec.get("land_mask", {}))
    R["mask_backend"] = backend
    R["water_frac"] = round(water_frac, 4)

    names, xy = read_pois(spec)
    x, y = xy[:, 0], xy[:, 1]
    inside = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    outside = int((~inside).sum())
    R["pois_total"] = int(len(xy))
    R["pois_inside"] = int(inside.sum())
    R["pois_outside"] = outside
    R["clip"] = {"width": W, "height": H,
                 "declared_width": clip.get("width"), "declared_height": clip.get("height")}
    R["poi_bbox"] = [round(float(x.min()), 1), round(float(y.min()), 1),
                     round(float(x.max()), 1), round(float(y.max()), 1)]

    ix, iy = np.round(x[inside]).astype(int), np.round(y[inside]).astype(int)
    ok_land = land[iy, ix]
    R["land_rate"] = round(float(ok_land.mean()), 4)
    R["land_rate_count"] = "%d/%d" % (int(ok_land.sum()), int(inside.sum()))

    by_class, class_rates = {}, {}
    for nm, okl in zip(np.array(names)[inside], ok_land):
        by_class.setdefault(nm, [0, 0])
        by_class[nm][0] += 1
        by_class[nm][1] += int(okl)
    for nm, (tot, ok) in by_class.items():
        class_rates[nm] = {"total": tot, "on_land": ok, "rate": round(ok / tot, 4) if tot else None}
    R["by_class"] = class_rates

    thr = (spec.get("thresholds") or {}).get("land_rate", 0.80)
    margin = (spec.get("thresholds") or {}).get("margin_vs_baseline", 0.10)
    thr_cov = (spec.get("thresholds") or {}).get("clip_coverage", 0.95)
    _decl = spec.get("outside_declared")
    declared_outside = len(_decl) if isinstance(_decl, list) else int(_decl or 0)
    coverage = float(inside.sum()) / len(xy)
    R["coverage"] = round(coverage, 4)
    rel_ok = True if control_land_rate is None else (R["land_rate"] >= control_land_rate - margin)
    R["checks"].append({
        "check": "2 独立一致性",
        "verdict": "PASS" if (R["land_rate"] >= thr and rel_ok) else "FAIL",
        "detail": "落点一致率 %s（阈值 %.2f%s）" % (
            R["land_rate_count"] + " = %.1f%%" % (R["land_rate"] * 100), thr,
            "" if control_land_rate is None else "；对照基准 %.1f%%，裕量 %.2f" %
            (control_land_rate * 100, margin)),
    })
    R["checks"].append({
        "check": "4 裁剪完整性",
        "verdict": "PASS" if (coverage >= thr_cov and (outside == 0 or declared_outside)) else "FAIL",
        "detail": "点集覆盖率 %d/%d = %.3f（阈值 %.2f）；外接框 %s vs 裁剪 %dx%d ⇒ 越框 %d（已声明 %d）" %
                  (int(inside.sum()), len(xy), coverage, thr_cov, R["poi_bbox"], W, H, outside, declared_outside),
    })

    fails = [c["check"] for c in R["checks"] if c["verdict"] == "FAIL"]
    R["verdict"] = "未通过" if fails else "通过"
    R["fail_checks"] = fails
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--control", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()

    for p in (a.spec, a.control):
        if p and not os.path.isfile(p):
            print("FAIL 输入不存在：%s" % p)
            return 2

    with open(a.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    control = None
    if a.control:
        with open(a.control, encoding="utf-8") as fh:
            control = json.load(fh)
        ctrl = run_spec(control, None)
    else:
        ctrl = None

    cand = run_spec(spec, ctrl["land_rate"] if ctrl else None)
    report = {"candidate": cand, "control": ctrl,
              "verdict": cand["verdict"],
              "note": "零残差本身不算验证；未通过即该标定不得升 ORTHO_VERIFIED（02 §4.6）"}

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "registration_crosscheck.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)

    if a.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for who, r in (("候选", cand), ("对照", ctrl)):
            if not r:
                continue
            print("%s %s → %s" % (who, r["name"], r["verdict"]))
            for c in r["checks"]:
                print("   [%s] %s — %s" % (c["verdict"], c["check"], c["detail"]))
            print("   land_rate=%s landmark classes=%s" %
                  (r["land_rate_count"], {k: v["on_land"] for k, v in list(r["by_class"].items())[:4]}))
    return 1 if cand["verdict"] != "通过" else 0


if __name__ == "__main__":
    sys.exit(main())
