#!/usr/bin/env python3
"""形制 / 形态读数（I-12）— 高度分布形态 + “形态未经独立证据校验”判定。

判据与阈值的**唯一出处**：`references/10-verification-instruments.md` I-12
（指标定义、阈值、`field_kind=terrain` 的适用边界）。
本脚本只产读数并给 `TERRACE-UNPROVEN` 结论；**不停手**，也不改任何数据。
结论名不是“台地=坏”——世界实测点最低 151.4 m，高原台地**可能是对的**；
本仪器只负责说“无独立证据能判它对错”。

usage:
  # 高度场（npz 需含 height_m / land；可选 voxel_m）
  PYTHONUTF8=1 python heightfield_form_check.py --npz <heightmap.npz> \\
      --field-kind terrain --height-source fit_from_survey --survey-min 151.4 [--out <dir>] [--json-only]

  # 三维占用网格（如 01-外滩 evidence/G4/voxels.npz 的 grid[x,y,z]）→ 顶面高程
  PYTHONUTF8=1 python heightfield_form_check.py --npz <voxels.npz> --grid-key grid \\
      --field-kind roof_top --height-source derived_other

exit: 0 正常 · 1 命中 TERRACE-UNPROVEN（形态未经独立证据校验） · 2 用法 / 输入缺失
"""

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

BAND_FRACTION = 0.25      # 单一高程带占比阈值（10 I-12 标定：0.305 vs 真地形 0.106）
FLAT_SHARE_1M = 0.10      # 最满 1 米带占比阈值（10 I-12 标定：0.208 vs 真地形 0.018）


def metrics(x):
    x = np.asarray(x, dtype=float)
    n = x.size
    p05, p25, p50, p75, p95 = np.percentile(x, [5, 25, 50, 75, 95])
    rng = float(p95 - p05)
    out = {
        "cells": int(n),
        "min": float(x.min()), "max": float(x.max()),
        "p05": float(p05), "p25": float(p25), "p50": float(p50),
        "p75": float(p75), "p95": float(p95),
        "iqr_ratio": float((p75 - p25) / rng) if rng > 0 else 0.0,
    }
    if rng <= 0:
        out["band_share"] = 1.0
        out["flat_share_1m"] = 1.0
        out["spike_ratio"] = None
        return out
    w = rng / 20.0
    bins = np.arange(np.floor(x.min() / w) * w, x.max() + w, w)
    cnt, _ = np.histogram(x, bins=bins)
    out["band_width"] = float(w)
    out["band_share"] = float(cnt.max() / n)
    bins1 = np.arange(np.floor(x.min()), x.max() + 1.001, 1.0)
    c1, _ = np.histogram(x, bins=bins1)
    nz = c1[c1 > 0]
    out["modal_height_1m"] = float(bins1[int(c1.argmax())])
    out["flat_share_1m"] = float(c1.max() / n)                       # 主判据（I-12）
    out["spike_ratio"] = float(c1.max() / np.median(nz)) if nz.size else None  # 诊断量
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", required=True)
    ap.add_argument("--height-key", default="height_m")
    ap.add_argument("--land-key", default="land")
    ap.add_argument("--grid-key", default=None, help="三维占用网格的键名；给了就走顶面高程")
    ap.add_argument("--voxel", type=float, default=None, help="体素边长（m）；npz 内有 voxel_m 时自动取")
    ap.add_argument("--field-kind", default="unknown", choices=["terrain", "roof_top", "unknown"])
    ap.add_argument("--height-source", default="unknown")
    ap.add_argument("--survey-min", type=float, default=None,
                    help="实测点集的最低高程（m）；给了就输出“无实测支撑占比”")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.npz):
        print("FAIL 输入不存在：%s" % a.npz)
        return 2
    d = np.load(a.npz)
    if a.grid_key:
        if a.grid_key not in d:
            print("FAIL npz 缺键 %s（有 %s）" % (a.grid_key, list(d.keys())))
            return 2
        g = d[a.grid_key]
        if g.ndim != 3:
            print("FAIL --grid-key 需要三维数组，得到 %s" % (g.shape,))
            return 2
        occ = g > 0
        top = np.zeros((g.shape[0], g.shape[2]), np.int32)
        ys, xs, zs = np.where(occ)
        if ys.size == 0:
            print("FAIL 网格为空（空输入不是通过）")
            return 2
        np.maximum.at(top, (xs, zs), ys)
        length = float(a.voxel or 1.0)
        x = top[top > 0].astype(float) * length
        mask_note = "verticals=%d" % int((top > 0).sum())
    else:
        if a.height_key not in d or a.land_key not in d:
            print("FAIL npz 缺键 %s / %s（有 %s）" % (a.height_key, a.land_key, list(d.keys())))
            return 2
        h, land = d[a.height_key], d[a.land_key].astype(bool)
        if not land.any():
            print("FAIL land 掩膜为空（空输入不是通过）")
            return 2
        vx = a.voxel if a.voxel is not None else (float(d["voxel_m"]) if "voxel_m" in d else None)
        x = h[land].astype(float) * (1.0 if vx is None else 1.0)
        mask_note = "voxel_m=%s" % (vx if vx is not None else "未提供")

    m = metrics(x)
    m["field_kind"] = a.field_kind
    m["height_source"] = a.height_source
    m["mask_note"] = mask_note
    m["min_observed"] = float(np.min(x))
    if a.survey_min is not None:
        m["survey_min"] = float(a.survey_min)
        m["below_survey_min"] = float((x < a.survey_min).mean())

    hit_band = m["band_share"] >= BAND_FRACTION
    hit_flat = m["flat_share_1m"] >= FLAT_SHARE_1M
    applicable = a.field_kind == "terrain"
    m["apps"] = {"band_share>=%.2f" % BAND_FRACTION: bool(hit_band),
                 "flat_share_1m>=%.2f" % FLAT_SHARE_1M: bool(hit_flat),
                 "applicable(field_kind==terrain)": applicable}
    if not applicable:
        m["verdict"] = "NOT-APPLICABLE"
        m["note"] = ("field_kind=%s ⇒ 本检查不适用（城市/建筑类的屋顶或占位高程天然聚类，"
                     "实测同一口径下某平地城市 flat_share_1m=0.113 / band_share=0.271 ⇒ 会误报）；"
                     "地形类必须显式声明 field_kind=terrain" % a.field_kind)
    elif hit_band or hit_flat:
        m["verdict"] = "TERRACE-UNPROVEN"
        m["note"] = ("单一高程带占比 %.3f（阈值 %.2f）与/或最满 1 米带占比 %.3f（阈值 %.2f）命中："
                     "形态**未经独立证据校验**（不是“台地错”——实测点最低 151.4 m，台地可能是对的）。"
                     "按 04 §3.1：C2 记 UNKNOWN，下一轮补同轴透视/剪影参考或官方 DEM/剖面。"
                     % (m["band_share"], BAND_FRACTION, m["flat_share_1m"], FLAT_SHARE_1M))
    else:
        m["verdict"] = "OK"
        m["note"] = "形态读数在阈值内（对照：Rushmore DEM 真地形 band_share 0.106 / flat_share_1m 0.018）"

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "heightfield_form_report.json"), "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=1)

    if a.json_only:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        print("verdict: %s" % m["verdict"])
        print("  band_share=%.3f (>=%.2f) · flat_share_1m=%.3f (>=%.2f) · iqr_ratio=%.3f"
              % (m["band_share"], BAND_FRACTION, m["flat_share_1m"], FLAT_SHARE_1M, m["iqr_ratio"]))
        print("  p05/p50/p95 = %.1f / %.1f / %.1f · 最满 1 米带 = %.0f m · spike_ratio(诊断)=%s · %s"
              % (m["p05"], m["p50"], m["p95"], m.get("modal_height_1m", float("nan")),
                 m["spike_ratio"], m["mask_note"]))
        if "below_survey_min" in m:
            print("  无实测支撑占比（< %.1f m）= %.3f" % (m["survey_min"], m["below_survey_min"]))
        print("  " + m["note"])
    return 1 if m["verdict"] == "TERRACE-UNPROVEN" else 0


if __name__ == "__main__":
    sys.exit(main())
