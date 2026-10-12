#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""引擎无关的"参考 vs 产物"掩码对照仪器（对照分析流程的第 ③ 级：投影级）。

为什么单独做这一件：投影级指标（剪影 IoU / 包围盒漂移 / 质心漂移）在**跨域**
（参考照片 vs 引擎渲染）时会被"前景占比差"污染，必须先过合法性闸再谈数值。
本工具把这条闸、掩码提取模式的冻结、以及"均值 + 最差项"一起固化，避免每轮手算。

依赖：仅 Pillow（不依赖 numpy / opencv）。

用法
----
单对：
  python compare_masks.py --ref ref.png --render shot.png --mode alpha \
      --ref-mode luma-dark --render-mode luma-dark --view front \
      --out-json compare.json --out-overlay overlay.png

批量（推荐，会同时给均值与最差项）：
  python compare_masks.py --pairs pairs.json --out-json compare_all.json

pairs.json:
  {"analysis_res": 512,
   "pairs": [
     {"name": "front", "view": "front",
      "ref": "refs/front.png", "render": "shots/front.png",
      "ref_mode": "luma-dark", "render_mode": "luma-dark"},
     {"name": "side", "view": "side",
      "ref": "refs/side.png", "render": "shots/side.png",
      "ref_mode": "alpha", "render_mode": "luma-dark"}
   ]}

掩码提取模式（必须冻结并随版本登记，否则跨轮 IoU 不可比）
  alpha      : 取 alpha 通道 > alpha_thr
  luma-dark  : 亮底暗物（灰度按 Otsu 反向：前景 = 暗的一侧）
  luma-bright: 暗底亮物（前景 = 亮的一侧）
  luma-fixed : 固定阈值（--luma-thr），前景 = 亮的一侧
  edges      : 边缘（ImageFilter.FIND_EDGES + 阈值），只用于"线稿 vs 线稿"
  binary-mask: 显式同尺寸 0/255 掩膜，不取 alpha，不阈值化非二值图

追加输入（单对 CLI 与 pairs 字段一一对应，pairs 使用下划线）：
  --ref-ignore / --render-ignore：同原图尺寸的 0/255 未知区，白区排除两侧统计。
  --ref-report / --render-report：单图 JSON，绑定输入 source_sha256 或 mask_sha256，
      并声明 status、scope、semantic_review；也支持 metadata / artifacts 中的对应字段。
      已声明的 ignore 自动传递，显式 ignore 不得替换成更小的未知区。
compare_pair 在 overlay_path 后追加 ref_ignore、render_ignore、ref_report、render_report；
report 可为路径或 dict。旧 status / 退出码保留诊断兼容；verdict 才是主状态。
候选、未复核、缺 metadata、缩小有效域或比例不符不能获得语义通过。
diagnostic_verdict 和旧 status 仅描述数值诊断，不是几何验收。

退出码
  0 旧数值诊断满足阈值；语义资格另看 verdict，缺 metadata 不验收
  1 有门禁失败
  2 用法/IO 错误
  3 有效性告警或显式 metadata 未核实，需要人工裁决
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VALID_MODES = ("alpha", "luma-dark", "luma-bright", "luma-fixed", "edges", "binary-mask")
# 默认门禁：与 references/14 第 4.2 节的"外部惯例阈值"一致，仅作本工具默认值，
# 写进项目门禁表前必须在本工程留下负样本（见 10-verification-instruments I-04）。
DEFAULT_GATES = {
    "center_drift_pct": 1.5,   # 图宽的百分比
    "size_drift_pct_front": 3.0,
    "size_drift_pct_other": 5.0,
}
IOU_VALIDITY_MIN_FG_RATIO = 0.25


def binary_mask(img: Image.Image, label: str) -> Image.Image:
    if img.mode not in ("1", "L", "LA", "RGB", "RGBA", "P"):
        raise ValueError("%s: binary mask requires 8-bit grayscale 0/255" % label)
    rgba = img.convert("RGBA")
    if rgba.getchannel("A").getextrema() != (255, 255):
        raise ValueError("%s: binary mask must be opaque; use alpha mode for transparency" % label)
    red, green, blue = rgba.convert("RGB").split()
    if ImageChops.difference(red, green).getbbox() or ImageChops.difference(red, blue).getbbox():
        raise ValueError("%s: binary mask must be grayscale 0/255" % label)
    if sum(red.histogram()[1:255]):
        raise ValueError("%s: binary mask contains values other than 0/255" % label)
    return red


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_ignore(path, size, label):
    if path is None:
        return Image.new("L", size, 0)
    with Image.open(path) as image:
        if image.size != size:
            raise ValueError("%s: ignore size %s does not match input %s" % (label, image.size, size))
        return binary_mask(image, label + " ignore")


def report_field(document, metadata, field):
    values = [container[field] for container in (document, metadata) if field in container]
    if values and any(value != values[0] for value in values):
        raise ValueError("conflicting report field: %s" % field)
    return values[0] if values else None


def bind_report(report, image_path, mode, ignore_path, size, label):
    if report is None:
        return None, read_ignore(ignore_path, size, label)
    base = Path.cwd()
    if isinstance(report, dict):
        document = report
    else:
        report_path = Path(report).resolve()
        base = report_path.parent
        with report_path.open(encoding="utf-8-sig") as stream:
            document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError("%s report must be a single-image JSON object" % label)
    metadata, artifacts = document.get("metadata", {}), document.get("artifacts", {})
    if not isinstance(metadata, dict) or not isinstance(artifacts, dict):
        raise ValueError("%s report metadata/artifacts must be objects" % label)
    hashes = {}
    for field in ("source_sha256", "mask_sha256", "ignore_sha256"):
        values = [container[field] for container in (document, artifacts) if field in container]
        if values:
            if any(not isinstance(value, str) or len(value) != 64 or
                   any(character not in "0123456789abcdefABCDEF" for character in value)
                   for value in values):
                raise ValueError("%s report has invalid %s" % (label, field))
            if len({value.lower() for value in values}) != 1:
                raise ValueError("%s report has conflicting %s" % (label, field))
            hashes[field] = values[0].lower()
    binding = "mask_sha256" if mode == "binary-mask" and "mask_sha256" in hashes else "source_sha256"
    if binding not in hashes:
        binding = "mask_sha256"
    if binding not in hashes:
        raise ValueError("%s report requires source_sha256 or mask_sha256 binding" % label)
    actual = file_sha256(image_path)
    if actual != hashes[binding]:
        raise ValueError("%s report %s mismatch for %s" % (label, binding, image_path))
    declared_size = report_field(document, metadata, "image_size")
    if declared_size is not None and declared_size != list(size):
        raise ValueError("%s report image_size mismatch" % label)
    info = {field: report_field(document, metadata, field)
            for field in ("status", "scope", "semantic_review")}
    for field, value in info.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("%s report has invalid %s" % (label, field))
    info.update(binding=binding, input_sha256=actual)
    declared = artifacts.get("ignore")
    if declared is not None and not isinstance(declared, str):
        raise ValueError("%s report artifacts.ignore must be a path" % label)
    declared_path = (base / declared).resolve() if declared else None
    if ignore_path is None:
        ignore_path = declared_path
    ignored = read_ignore(ignore_path, size, label)
    if declared_path is not None and ignore_path is not None:
        declared_mask = read_ignore(declared_path, size, label)
        if ImageChops.difference(ignored, declared_mask).getbbox():
            raise ValueError("%s ignore differs from bound report; cannot shrink unknown domain" % label)
    if "ignore_sha256" in hashes:
        if ignore_path is None or file_sha256(ignore_path) != hashes["ignore_sha256"]:
            raise ValueError("%s report ignore_sha256 mismatch or missing ignore" % label)
    declared_count = report_field(document, metadata, "ignored_pixels")
    if declared_count is not None:
        if not isinstance(declared_count, int) or isinstance(declared_count, bool) or declared_count < 0:
            raise ValueError("%s report has invalid ignored_pixels" % label)
        if ignored.histogram()[255] != declared_count:
            raise ValueError("%s report ignored_pixels mismatch; preserve the declared ignore" % label)
    info["ignore"] = str(ignore_path) if ignore_path is not None else None
    info["ignored_pixels"] = ignored.histogram()[255]
    return info, ignored


def resize_ignore(ignore, res):
    averaged = ignore.convert("F").resize((res, res), Image.Resampling.BOX)
    pixels = averaged.load()
    small = Image.new("L", (res, res))
    small.putdata([255 if pixels[column, row] > 0 else 0
                   for row in range(res) for column in range(res)])
    return small


def semantic_reasons(reports):
    reasons = []
    for label, report in reports.items():
        if report is None:
            reasons.append("%s metadata missing; no semantic acceptance" % label)
            continue
        if (report.get("status") or "").upper() not in ("VERIFIED", "APPROVED", "REVIEWED"):
            reasons.append("%s status is not verified: %s" % (label, report.get("status")))
        if (report.get("semantic_review") or "").lower() not in ("verified", "approved", "reviewed"):
            reasons.append("%s semantic_review is missing or unreviewed" % label)
        if (report.get("scope") or "").lower() not in ("whole-subject", "local-part", "subject-region"):
            reasons.append("%s scope missing or unsupported; no whole-subject inference" % label)
    reference, rendered = reports["ref"], reports["render"]
    if reference and rendered and reference.get("scope") != rendered.get("scope"):
        reasons.append("scope mismatch; local-part cannot establish whole-subject acceptance")
    return reasons


def otsu_threshold(gray: Image.Image) -> int:
    hist = gray.histogram()[:256]
    total = sum(hist)
    if total == 0:
        return 128
    sum_all = sum(i * hist[i] for i in range(256))
    sum_bg = 0.0
    w_bg = 0
    best_thr, best_var = 128, -1.0
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        m_bg = sum_bg / w_bg
        m_fg = (sum_all - sum_bg) / w_fg
        var = w_bg * w_fg * (m_bg - m_fg) ** 2
        if var > best_var:
            best_var, best_thr = var, t
    return best_thr


def extract_mask(img: Image.Image, mode: str, luma_thr: int = 128, alpha_thr: int = 8) -> Image.Image:
    """返回 mode='L'、取值 0/255 的前景掩码。"""
    if mode not in VALID_MODES:
        raise ValueError("unknown mask mode: %s (valid: %s)" % (mode, ", ".join(VALID_MODES)))
    if mode == "binary-mask":
        return binary_mask(img, "input")
    if mode == "alpha":
        if img.mode not in ("RGBA", "LA"):
            img = img.convert("RGBA")
        alpha = img.getchannel("A").convert("L")
        return alpha.point(lambda v: 255 if v > alpha_thr else 0)
    gray = img.convert("L")
    if mode == "edges":
        edges = gray.filter(ImageFilter.FIND_EDGES)
        return edges.point(lambda v: 255 if v > max(luma_thr, 1) else 0)
    thr = otsu_threshold(gray) if mode != "luma-fixed" else luma_thr
    if mode == "luma-dark":
        return gray.point(lambda v: 255 if v <= thr else 0)
    return gray.point(lambda v: 255 if v > thr else 0)


def mask_stats(mask: Image.Image, res: int, valid_pixels=None) -> dict:
    small = mask.resize((res, res), Image.NEAREST)
    hist = small.histogram()
    fg = hist[255] if len(hist) > 255 else 0
    bbox = small.getbbox()
    cx = cy = None
    if fg:
        sx = sy = 0
        px = small.load()
        for y in range(res):
            row = 0
            for x in range(res):
                if px[x, y]:
                    row += 1
                    sx += x
        # 第二次遍历只为纵向和，保证内存恒定
        for y in range(res):
            for x in range(res):
                if px[x, y]:
                    sy += y
        cx = sx / fg
        cy = sy / fg
    denominator = res * res if valid_pixels is None else valid_pixels
    return {"res": res, "fg": fg, "fg_ratio": fg / float(denominator) if denominator else None,
            "bbox": bbox, "centroid": (cx, cy)}


def compare_pair(ref_path, render_path, ref_mode, render_mode, view, res,
                 gates, iou_target=None, luma_thr=128, alpha_thr=8,
                 overlay_path=None, ref_ignore=None, render_ignore=None,
                 ref_report=None, render_report=None) -> dict:
    if not isinstance(res, int) or isinstance(res, bool) or res < 1:
        raise ValueError("analysis resolution must be a positive integer")
    with Image.open(ref_path) as image:
        ref = image.copy()
    with Image.open(render_path) as image:
        rnd = image.copy()
    if "binary-mask" in (ref_mode, render_mode) and ref.size != rnd.size:
        raise ValueError("binary-mask size mismatch: ref %s vs render %s" % (ref.size, rnd.size))
    m_ref = extract_mask(ref, ref_mode, luma_thr, alpha_thr)
    m_rnd = extract_mask(rnd, render_mode, luma_thr, alpha_thr)
    report_ref, ignore_ref = bind_report(ref_report, ref_path, ref_mode, ref_ignore, ref.size, "ref")
    report_rnd, ignore_rnd = bind_report(render_report, render_path, render_mode, render_ignore, rnd.size, "render")
    reports = {"ref": report_ref, "render": report_rnd}

    # IoU 在统一分析分辨率上算（PIL 的 logical_* 走 C，快）
    a = m_ref.resize((res, res), Image.NEAREST).point(lambda v: 255 if v else 0)
    b = m_rnd.resize((res, res), Image.NEAREST).point(lambda v: 255 if v else 0)
    original_intersection = ImageChops.darker(a, b).histogram()[255]
    original_union = ImageChops.lighter(a, b).histogram()[255]
    full_domain_degenerate = any(mask.histogram()[255] in (0, mask.width * mask.height)
                                 for mask in (m_ref, m_rnd, a, b))
    valid = ImageChops.invert(ImageChops.lighter(resize_ignore(ignore_ref, res),
                                               resize_ignore(ignore_rnd, res)))
    valid_pixels = valid.histogram()[255]
    a, b = ImageChops.multiply(a, valid), ImageChops.multiply(b, valid)
    inter = ImageChops.logical_and(a.convert("1"), b.convert("1")).convert("L")
    union = ImageChops.logical_or(a.convert("1"), b.convert("1")).convert("L")
    n_inter = inter.histogram()[255]
    n_union = union.histogram()[255]
    iou = (n_inter / n_union) if n_union else None

    s_ref = mask_stats(a, res, valid_pixels)
    s_rnd = mask_stats(b, res, valid_pixels)
    valid_domain_degenerate = not valid_pixels or any(stats['fg'] in (0, valid_pixels)
                                                     for stats in (s_ref, s_rnd))
    degenerate = full_domain_degenerate or valid_domain_degenerate
    raw_iou = iou
    if degenerate:
        iou = None
    aspect_mismatch = ref.width * rnd.height != rnd.width * ref.height

    out = {"name": None, "view": view, "ref": ref_path, "render": render_path,
           "mask_modes": {"ref": ref_mode, "render": render_mode},
           "analysis_res": res, "iou": iou, "iou_target": iou_target,
           "intersection": n_inter, "union": n_union, "raw_iou": raw_iou,
           "degenerate": degenerate, "full_domain_degenerate": full_domain_degenerate,
           "valid_domain_degenerate": valid_domain_degenerate,
           "empty_common_domain": not valid_pixels,
           "unaligned": True if aspect_mismatch else None,
           "scope": "view-local-mask-pair; camera registration must be verified separately",
           "fg_ratio_ref": s_ref["fg_ratio"], "fg_ratio_render": s_rnd["fg_ratio"],
           "fg_ratio_ref_original_denominator": s_ref["fg"] / float(res * res),
           "fg_ratio_render_original_denominator": s_rnd["fg"] / float(res * res),
           "valid_pixels": valid_pixels, "ignored_pixels": res * res - valid_pixels,
           "valid_domain_fraction": valid_pixels / float(res * res),
           "original_denominator_pixels": res * res,
           "original_intersection": original_intersection, "original_union": original_union,
           "original_domain_diagnostic_iou": original_intersection / original_union if original_union else None,
           "input_sizes": {"ref": list(ref.size), "render": list(rnd.size)},
           "input_denominator_pixels": {"ref": ref.width * ref.height, "render": rnd.width * rnd.height},
           "ignore": {"ref": report_ref["ignore"] if report_ref else str(ref_ignore) if ref_ignore is not None else None,
                      "render": report_rnd["ignore"] if report_rnd else str(render_ignore) if render_ignore is not None else None,
                      "ref_pixels_original": ignore_ref.histogram()[255],
                      "render_pixels_original": ignore_rnd.histogram()[255],
                      "resampling": "conservative BOX: any unknown source contribution stays unknown"},
           "metadata": reports, "metadata_provided": ref_report is not None or render_report is not None,
           "metrics_are_diagnostic": True}

    # —— 有效性闸：跨域前景占比失衡时，IoU 只能当诊断 ——
    warnings = []
    if degenerate:
        warnings.append('degenerate-mask: empty/full foreground on the full or common valid domain; IoU is not valid geometry evidence')
    if not valid_pixels:
        warnings.append('empty-common-domain: no mutually valid pixels; unknown is not background')
    if ignore_ref.histogram()[255] or ignore_rnd.histogram()[255]:
        warnings.append('ignored-domain: statistics are local to common valid pixels; shrinking ignore/domain cannot establish semantic acceptance')
    if aspect_mismatch:
        warnings.append('unaligned-aspect: image aspect ratios differ; square resizing is diagnostic only')
    if s_ref["fg_ratio"] and s_rnd["fg_ratio"]:
        fg_ratio = min(s_ref["fg_ratio"], s_rnd["fg_ratio"]) / max(s_ref["fg_ratio"], s_rnd["fg_ratio"])
        out["fg_ratio_minmax"] = fg_ratio
        if fg_ratio < IOU_VALIDITY_MIN_FG_RATIO:
            warnings.append(
                "iou-validity: 前景占比比 min/max=%.3f < %.2f，跨域 IoU 不得作最终判据（只作诊断）"
                % (fg_ratio, IOU_VALIDITY_MIN_FG_RATIO))
    else:
        out["fg_ratio_minmax"] = None
        warnings.append("empty-mask: 参考或渲染的前景为空，IoU 无定义（口径或提取模式可能错了）")

    # —— 包围盒漂移 ——
    if not degenerate and s_ref["bbox"] and s_rnd["bbox"]:
        x0, y0, x1, y1 = s_ref["bbox"]
        rw, rh = x1 - x0, y1 - y0
        u0, v0, u1, v1 = s_rnd["bbox"]
        uw, uh = u1 - u0, v1 - v0
        cx_ref, cy_ref = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        cx_rnd, cy_rnd = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        center_drift = ((cx_ref - cx_rnd) ** 2 + (cy_ref - cy_rnd) ** 2) ** 0.5
        out["bbox"] = {
            "ref": [x0 / res * 100, y0 / res * 100, rw / res * 100, rh / res * 100],
            "render": [u0 / res * 100, v0 / res * 100, uw / res * 100, uh / res * 100],
            "center_drift_px": center_drift,
            "center_drift_pct": center_drift / res * 100.0,
            "width_drift_pct": (abs(rw - uw) / rw * 100.0) if rw else None,
            "height_drift_pct": (abs(rh - uh) / rh * 100.0) if rh else None,
        }
        out["centroid_drift_pct"] = (
            ((s_ref["centroid"][0] - s_rnd["centroid"][0]) ** 2 +
             (s_ref["centroid"][1] - s_rnd["centroid"][1]) ** 2) ** 0.5 / res * 100.0
        )
    else:
        out["bbox"] = None
        out["centroid_drift_pct"] = None
        warnings.append("bbox-unavailable: 至少一侧没有前景包围盒")

    # —— 门禁 ——
    failures = []
    if iou_target is not None:
        if iou is None or iou < iou_target:
            failures.append("iou %.4f < target %.4f" % (iou or -1, iou_target))
    if out.get("bbox"):
        if out["bbox"]["center_drift_pct"] > gates["center_drift_pct"]:
            failures.append("center_drift %.3f%% > %.3f%%"
                            % (out["bbox"]["center_drift_pct"], gates["center_drift_pct"]))
        size_gate = gates["size_drift_pct_front"] if view == "front" else gates["size_drift_pct_other"]
        worst = max(v for v in (out["bbox"]["width_drift_pct"], out["bbox"]["height_drift_pct"]) if v is not None)
        if worst > size_gate:
            failures.append("size_drift %.3f%% > %.3f%% (view=%s)" % (worst, size_gate, view))
    out["warnings"] = warnings
    out["failures"] = failures
    diagnostic_status = "FAIL" if failures else ("PASS-WATCH" if warnings else "PASS")
    out["diagnostic_status"] = diagnostic_status
    out["diagnostic_verdict"] = {"FAIL": "fail", "PASS-WATCH": "warn", "PASS": "pass"}[diagnostic_status]
    reasons = semantic_reasons(reports)
    reasons.extend(warnings)
    out["semantic_reasons"] = reasons
    out["semantic_verdict"] = "unverified" if reasons else "verified"
    out["verdict"] = "unverified" if reasons else ("fail" if failures else "pass")
    out["semantic_acceptance"] = out["verdict"] == "pass"
    out["status"] = "UNVERIFIED" if out["metadata_provided"] and reasons else diagnostic_status
    out["status_role"] = "legacy diagnostic only; use verdict for acceptance"

    if overlay_path:
        make_overlay(a, b, overlay_path, valid)
    return out


def make_overlay(a: Image.Image, b: Image.Image, path: str, valid=None) -> None:
    """重合=白，仅参考=红，仅产物=蓝；共同有效域外=橙，不画成背景。"""
    px_a, px_b = a.load(), b.load()
    valid_pixels = valid.load() if valid is not None else None
    res = a.size[0]
    ov = Image.new("RGB", (res, res), (0, 0, 0))
    o = ov.load()
    for y in range(res):
        for x in range(res):
            if valid_pixels is not None and not valid_pixels[x, y]:
                o[x, y] = (255, 168, 0)
                continue
            ia, ib = bool(px_a[x, y]), bool(px_b[x, y])
            if ia and ib:
                o[x, y] = (255, 255, 255)
            elif ia:
                o[x, y] = (255, 0, 0)
            elif ib:
                o[x, y] = (0, 128, 255)
    ov.save(path)


def summarize(results) -> dict:
    scored = [r for r in results if r["iou"] is not None]
    ious = [r["iou"] for r in scored]
    centers = [r["bbox"]["center_drift_pct"] for r in results if r.get("bbox")]
    sizes = [max(v for v in (r["bbox"]["width_drift_pct"], r["bbox"]["height_drift_pct"]) if v is not None)
             for r in results if r.get("bbox")]
    worst = None
    if scored:
        worst = min(scored, key=lambda r: r["iou"])["name"]
    return {
        "verdict": "unverified" if not results or any(r.get("verdict", "unverified") == "unverified" for r in results)
                   else "fail" if any(r.get("verdict") == "fail" for r in results) else "pass",
        "semantic_acceptance": bool(results) and all(r.get("semantic_acceptance", False) for r in results),
        "unverified_views": [r["name"] for r in results if r.get("verdict", "unverified") == "unverified"],
        "metrics_are_diagnostic": True,
        "views": len(results),
        "iou_mean": (sum(ious) / len(ious)) if ious else None,
        "iou_worst": min(ious) if ious else None,
        "iou_worst_view": worst,
        "center_drift_pct_mean": (sum(centers) / len(centers)) if centers else None,
        "center_drift_pct_worst": max(centers) if centers else None,
        "size_drift_pct_mean": (sum(sizes) / len(sizes)) if sizes else None,
        "size_drift_pct_worst": max(sizes) if sizes else None,
        "warning_views": [r["name"] for r in results if r["warnings"]],
        "failed_views": [r["name"] for r in results if r["failures"]],
    }


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="engine-agnostic mask comparison for reference-vs-render")
    ap.add_argument("--pairs", help="batch JSON (see module docstring)")
    ap.add_argument("--ref")
    ap.add_argument("--render")
    ap.add_argument("--mode", default="alpha", choices=VALID_MODES, help="both sides use this unless overridden")
    ap.add_argument("--ref-mode", choices=VALID_MODES)
    ap.add_argument("--render-mode", choices=VALID_MODES)
    ap.add_argument("--ref-ignore", help="same-size binary 0/255 unknown mask; white is excluded")
    ap.add_argument("--render-ignore", help="same-size binary 0/255 unknown mask; white is excluded")
    ap.add_argument("--ref-report", help="hash-bound single-image metadata JSON; cannot override candidate status")
    ap.add_argument("--render-report", help="hash-bound single-image metadata JSON; cannot override unreviewed status")
    ap.add_argument("--view", default="front", choices=["front", "side", "back", "top", "other"])
    ap.add_argument("--res", type=int, default=512, help="analysis resolution (square)")
    ap.add_argument("--iou-target", type=float, default=None)
    ap.add_argument("--luma-thr", type=int, default=128)
    ap.add_argument("--alpha-thr", type=int, default=8)
    ap.add_argument("--center-drift-pct", type=float, default=DEFAULT_GATES["center_drift_pct"])
    ap.add_argument("--size-drift-pct-front", type=float, default=DEFAULT_GATES["size_drift_pct_front"])
    ap.add_argument("--size-drift-pct-other", type=float, default=DEFAULT_GATES["size_drift_pct_other"])
    ap.add_argument("--out-json")
    ap.add_argument("--out-overlay")
    args = ap.parse_args(argv[1:])

    gates = {"center_drift_pct": args.center_drift_pct,
             "size_drift_pct_front": args.size_drift_pct_front,
             "size_drift_pct_other": args.size_drift_pct_other}

    try:
        if args.pairs:
            cfg = json.load(open(args.pairs, encoding="utf-8"))
            res = int(cfg.get("analysis_res", args.res))
            results = []
            for i, p in enumerate(cfg["pairs"]):
                r = compare_pair(
                    p["ref"], p["render"],
                    p.get("ref_mode", p.get("mode", args.mode)),
                    p.get("render_mode", p.get("mode", args.mode)),
                    p.get("view", args.view), res, gates,
                    p.get("iou_target", args.iou_target), args.luma_thr, args.alpha_thr,
                    p.get("overlay"),
                    p.get("ref_ignore", args.ref_ignore), p.get("render_ignore", args.render_ignore),
                    p.get("ref_report", args.ref_report), p.get("render_report", args.render_report))
                r["name"] = p.get("name", "view%d" % i)
                results.append(r)
        else:
            if not (args.ref and args.render):
                ap.error("--ref/--render or --pairs required")
            r = compare_pair(args.ref, args.render,
                             args.ref_mode or args.mode, args.render_mode or args.mode,
                             args.view, args.res, gates, args.iou_target,
                             args.luma_thr, args.alpha_thr, args.out_overlay,
                             args.ref_ignore, args.render_ignore, args.ref_report, args.render_report)
            r["name"] = args.view
            results = [r]
    except Exception as e:  # IO / 解码 / 参数错误一律响亮失败
        print("ERROR: %s" % e, file=sys.stderr)
        return 2

    report = {"tool": "compare_masks.py",
              "note": "第③级投影诊断；status/diagnostic_verdict 和退出码不等于几何验收；缺语义 metadata 不验收，ignore 缩域不得冒充提分",
              "gates": gates,
              "iou_validity_min_fg_ratio": IOU_VALIDITY_MIN_FG_RATIO,
              "summary": summarize(results),
              "results": results}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out_json:
        open(args.out_json, "w", encoding="utf-8").write(text)
    print(text)

    s = report["summary"]
    if s["failed_views"]:
        return 1
    if s["warning_views"]:
        return 3
    if any(result["metadata_provided"] and result["verdict"] == "unverified" for result in results):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
