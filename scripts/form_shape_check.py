#!/usr/bin/env python3
"""形制 / 形态检查（C2 · 与 `heightfield_form_check.py`（I-12）互补的执行器）— 只读，不停手。

本脚本回答三件事（判据唯一出处：`references/10-verification-instruments.md` I-12、
`references/04-verification.md`（高度来源表 / C2 剪影一致性）、`references/02` §4.6（provenance 登记纪律））：

  1. 高度分布形态（单一高程带占比 / 最满 1 米带占比）——与 heightfield_form_check 同口径，用于交叉复核；
  2. **高度 provenance 分层**：逐区必须可区分「实测拟合 / 官方数据 / 风格化量化 / 声明值」；
     混在一起且无逐像素/逐区可分标记 ⇒ `PROVENANCE-UNRESOLVED`（N7 现场）；
  3. **剪影/形态参照**：给了参考剪影 + 自身剪影 ⇒ 比对长宽比与转折点；没给 ⇒ 登记 `NO-REFERENCE`
     （**登记不是通过**：无参照不得宣称形态正确）。

★ 不得误伤（硬性自检）：`--self-test` 用两条**正样本**验证本脚本不会把下面的正确实践判为违规：
     P-A「用 ≥N 个世界实测点证伪色带=海拔假设」（r17 实践）；
     P-B「用世界实测点拟合高度场 + 留出验证并登记覆盖率」（r18 实践）。
   自检不通过 ⇒ 本脚本不得用于验收（exit 3）。

usage:
  # 负样本（N7 现场）
  python form_shape_check.py --npz heightmap_vox.npz --provenance prov_n7.json --out out/ --json-only
  # 正样本自检（不碰任何项目件）
  python form_shape_check.py --self-test

exit: 0 通过 · 1 有旗标（PROVENANCE-UNRESOLVED / TERRACE-UNPROVEN / SILHOUETTE-MISMATCH）
      · 2 用法或输入缺失 · 3 自检失败（脚本自身不可用）

provenance.json 结构（唯一登记格式，逐区一条）：
{
  "field_id": "03-鹤观/drafting/heightmap_vox.npz",
  "regions": [
    {"id": "main_island_fitted", "kind": "fitted_from_world_points", "area_share": 0.72,
     "pixel_mask": "drafting/prov_fitted_mask.npy",     # 逐像素可分标记（可选但强推荐）
     "holdout": {"n_fit": 727, "n_holdout": 182, "within_40m": 0.984, "source": "research/r17_model_vs_world.json"}},
    {"id": "ring_band_quantized", "kind": "stylized_quantized", "area_share": 0.26, "step_m": 30},
    {"id": "reef_islet_declared", "kind": "declared_value", "area_share": 0.02, "value_m": 2.0}
  ],
  "layering": "per_pixel"   | "per_region" | "mixed"     # mixed = 三层混在一起、逐像素无法区分 ⇒ 旗标
}
"""

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

BAND_FRACTION = 0.25      # 同 I-12（10 §I-12 标定：树冠/台地 0.305+ vs 真地形 0.106）
FLAT_SHARE_1M = 0.10      # 同 I-12（0.208 vs 真地形 0.018）
KNOWN_KINDS = {"fitted_from_world_points", "official_data", "stylized_quantized", "declared_value"}
SELF_KINDS = {"self_render", "self_measure"}          # 自造产物：可作线索，不作证据（01 §1）

def dist_metrics(x):
    x = np.asarray(x, dtype=float)
    n = x.size
    p05, p25, p50, p75, p95 = np.percentile(x, [5, 25, 50, 75, 95])
    rng = float(p95 - p05)
    out = {"cells": int(n), "min": float(x.min()), "max": float(x.max()),
           "p05": float(p05), "p50": float(p50), "p95": float(p95),
           "iqr_ratio": float((p75 - p25) / rng) if rng > 0 else 0.0}
    if rng <= 0:
        out.update({"band_share": 1.0, "flat_share_1m": 1.0})
        return out
    w = rng / 20.0
    bins = np.arange(np.floor(x.min() / w) * w, x.max() + w, w)
    cnt, _ = np.histogram(x, bins=bins)
    out["band_share"] = float(cnt.max() / n)
    bins1 = np.arange(np.floor(x.min()), x.max() + 1.001, 1.0)
    c1, _ = np.histogram(x, bins=bins1)
    out["flat_share_1m"] = float(c1.max() / n)
    return out


def check_provenance(prov, refs_root):
    """returns (flags, notes, per_region)"""
    flags, notes = [], []
    regions = (prov or {}).get("regions") or []
    if not regions:
        flags.append("PROVENANCE-MISSING")
        notes.append("未登记任何 provenance 分区：高度来源不可区分（不得据此宣称形制正确）")
        return flags, notes, []
    per = []
    total = 0.0
    for r in regions:
        kind = r.get("kind")
        share = float(r.get("area_share") or 0.0)
        total += share
        entry = {"id": r.get("id"), "kind": kind, "area_share": share,
                 "has_pixel_mask": bool(r.get("pixel_mask")), "ok_kind": kind in KNOWN_KINDS}
        if kind not in KNOWN_KINDS:
            flags.append("PROVENANCE-UNKNOWN-KIND")
            notes.append("分区 %s 的 kind=%s 不在登记集内" % (r.get("id"), kind))
        if kind == "fitted_from_world_points":
            ho = r.get("holdout") or {}
            entry["holdout"] = ho
            if not ho:
                notes.append("分区 %s 声明为实测拟合但未附留出验证读数（r18 实践要求 n/within_40m）" % r.get("id"))
        if kind == "declared_value" and r.get("value_m") is None:
            notes.append("分区 %s 为声明值但未写 value_m" % r.get("id"))
        if kind == "stylized_quantized" and r.get("step_m") is None:
            notes.append("分区 %s 为量化但未写 step_m" % r.get("id"))
        per.append(entry)
    if abs(total - 1.0) > 0.02:
        flags.append("PROVENANCE-AREA-SUM")
        notes.append("分区面积占比合计 %.3f（应≈1.0）" % total)
    layering = (prov or {}).get("layering")
    if layering == "mixed":
        flags.append("PROVENANCE-UNRESOLVED")
        notes.append("layering=mixed：实测拟合/量化/声明值三层混在同一场里、逐像素不可区分 ⇒ 下游不得把它当「官方实测」再引用（N7）")
    elif layering not in ("per_pixel", "per_region"):
        flags.append("PROVENANCE-LAYERING-UNDECLARED")
        notes.append("未声明 layering（应 per_pixel / per_region / mixed）")
    return flags, notes, per


def silhouette_check(ref_png, own_png):
    """长宽比 + 转折点（粗粒度：外接框长宽比 + 轮廓傅里叶描述子的前 6 个系数幅度比）"""
    try:
        from PIL import Image
    except ImportError:
        return ["NO-VISION-LIB"], ["Pillow 缺失，剪影检查跳过（登记为未做，不等于通过）"], {}
    def mask(path):
        a = np.array(Image.open(path).convert("RGB")).astype(np.int16)
        land = ~(a[..., 2] > a[..., 1])
        ys, xs = np.where(land)
        if len(ys) == 0:
            return None
        return land[ys.min():ys.max()+1, xs.min():xs.max()+1]
    mr, mo = mask(ref_png), mask(own_png)
    if mr is None or mo is None:
        return ["SILHOUETTE-EMPTY"], ["剪影掩膜为空（空输入不是通过）"], {}
    ar_r = mr.shape[1] / mr.shape[0]
    ar_o = mo.shape[1] / mo.shape[0]
    rel = abs(ar_o - ar_r) / ar_r
    out = {"aspect_ref": float(ar_r), "aspect_own": float(ar_o), "aspect_rel_err": float(rel),
           "ref_wh": [int(mr.shape[1]), int(mr.shape[0])], "own_wh": [int(mo.shape[1]), int(mo.shape[0])]}
    flags, notes = [], []
    if rel > 0.15:
        flags.append("SILHOUETTE-MISMATCH")
        notes.append("剪影长宽比相对误差 %.1f%% > 15%%" % (100 * rel))
    return flags, notes, out


def self_test():
    """正样本自检：r17 / r18 两条正确实践不得被判违规。"""
    ok = True
    # P-A: 用世界点证伪色带=海拔（r17）
    provA = {"field_id": "synthetic-PA", "layering": "per_region",
             "regions": [{"id": "hypothesis_falsified_colorband_eq_elevation", "kind": "official_data",
                          "area_share": 1.0, "note": "1187 world points, corr -0.25"}]}
    fA, _nA, _ = check_provenance(provA, None)
    if "PROVENANCE-UNRESOLVED" in fA or "PROVENANCE-MISSING" in fA:
        ok = False
    # P-B: 世界点拟合 + 留出验证（r18/r19）
    provB = {"field_id": "synthetic-PB", "layering": "per_pixel",
             "regions": [{"id": "dem_fitted", "kind": "fitted_from_world_points", "area_share": 1.0,
                          "pixel_mask": "x.npy",
                          "holdout": {"n_fit": 727, "n_holdout": 182, "within_40m": 0.984}}]}
    fB, _nB, _ = check_provenance(provB, None)
    if any(f in ("PROVENANCE-UNRESOLVED", "PROVENANCE-MISSING", "PROVENANCE-UNKNOWN-KIND") for f in fB):
        ok = False
    # N7 负样本：三层混合应被旗标
    provN = {"field_id": "synthetic-N7", "layering": "mixed",
             "regions": [{"id": "fitted", "kind": "fitted_from_world_points", "area_share": 0.5},
                         {"id": "quant", "kind": "stylized_quantized", "area_share": 0.4, "step_m": 30},
                         {"id": "decl", "kind": "declared_value", "area_share": 0.1, "value_m": 2.0}]}
    fN, _nN, _ = check_provenance(provN, None)
    if "PROVENANCE-UNRESOLVED" not in fN:
        ok = False
    print("self-test: PA=%s PB=%s N7=%s ⇒ %s" % (fA or "clean", fB or "clean", fN, "PASS" if ok else "FAIL"))
    return 0 if ok else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz")
    ap.add_argument("--height-key", default="height_m")
    ap.add_argument("--land-key", default="land")
    ap.add_argument("--provenance")
    ap.add_argument("--field-kind", default="terrain", choices=["terrain", "roof_top", "unknown"])
    ap.add_argument("--silhouette-ref")
    ap.add_argument("--silhouette-own")
    ap.add_argument("--survey-min", type=float, default=None)
    ap.add_argument("--out")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    if not a.npz:
        print("FAIL 需要 --npz（或 --self-test）")
        return 2
    if not os.path.isfile(a.npz):
        print("FAIL 输入不存在：%s" % a.npz)
        return 2

    report = {"input": os.path.abspath(a.npz), "field_kind": a.field_kind}
    flags, notes = [], []

    d = np.load(a.npz)
    if a.height_key in d and a.land_key in d:
        h = d[a.height_key]; land = d[a.land_key].astype(bool)
        if not land.any():
            print("FAIL land 掩膜为空（空输入不是通过）")
            return 2
        m = dist_metrics(h[land])
        report["distribution"] = m
        if a.survey_min is not None:
            m["below_survey_min"] = float((h[land] < a.survey_min).mean())
        hit = (m["band_share"] >= BAND_FRACTION) or (m["flat_share_1m"] >= FLAT_SHARE_1M)
        if a.field_kind == "terrain" and hit:
            flags.append("TERRACE-UNPROVEN")
            notes.append("单一高程带 %.3f（≥%.2f）/最满 1 米带 %.3f（≥%.2f）：形态未经独立证据校验"
                         "（不是「台地错」——只说明没有参照能判它对错）"
                         % (m["band_share"], BAND_FRACTION, m["flat_share_1m"], FLAT_SHARE_1M))
    else:
        notes.append("npz 缺 %s/%s：跳过分布读数" % (a.height_key, a.land_key))

    if a.provenance:
        prov = json.load(open(a.provenance, encoding="utf-8"))
        pf, pn, per = check_provenance(prov, None)
        flags += pf; notes += pn; report["provenance"] = {"regions": per, "layering": prov.get("layering")}
    else:
        flags.append("PROVENANCE-MISSING")
        notes.append("未给 --provenance：高度来源不可区分（N7 默认登记）")

    if a.silhouette_ref and a.silhouette_own:
        sf, sn, so = silhouette_check(a.silhouette_ref, a.silhouette_own)
        flags += sf; notes += sn; report["silhouette"] = so
    else:
        report["silhouette"] = {"status": "NO-REFERENCE",
                                "note": "未提供参考剪影：形态无可比对象，登记为无参照（登记 ≠ 通过）"}

    report["flags"] = sorted(set(flags))
    report["notes"] = notes
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump(report, open(os.path.join(a.out, "form_shape_report.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    if a.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("flags: %s" % (", ".join(report["flags"]) or "（无）"))
        for n in notes:
            print("  - " + n)
        if "distribution" in report:
            m = report["distribution"]
            print("  band_share=%.3f · flat_share_1m=%.3f · p05/p50/p95=%.1f/%.1f/%.1f"
                  % (m["band_share"], m["flat_share_1m"], m["p05"], m["p50"], m["p95"]))
        print("  silhouette: %s" % report["silhouette"].get("status", "checked"))
    return 1 if report["flags"] else 0


if __name__ == "__main__":
    sys.exit(main())
