#!/usr/bin/env python3
"""参考图入包闸 — reference-image intake gate.

Implements references/19-reference-image-intake-gate.md:
  H1 view role declared · H2 measurability · H3 declared part count == observed

Design notes (see 19 §5, "双实现" registration):
  * Alpha masks and unprompted intake require **Pillow only**; prompted opaque
    segmentation requires NumPy / OpenCV. Metric *definitions* follow
    cc-blender-skill's reference-analysis-validator (local copy: docs/refs-staging/
    genre-art-scene-skills/github/RobLe3__cc-blender-skill), the *implementation* here is
    independent so the two can be cross-checked.
  * This script never writes into the inspected reference package unless --out points there.

usage:
  PYTHONUTF8=1 python reference_intake_gate.py --refs <refs-root> --out <out-dir> \\
      [--source-table <00-参考包与来源分级.md>] [--emit-masks] [--strict] [--json-only] \\
      [--subjects <reference-subject-spec-set.json>] \\
      [--pair <view>=<reference-image>:<render-image>] ...

exit: 0 all hard gates pass · 1 hard gate(s) failed · 2 usage / missing inputs
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import deque
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageChops, ImageFilter, ImageOps
except ImportError:  # pragma: no cover
    print("FAIL Pillow is required: pip install Pillow")
    raise SystemExit(2)

from reference_subject_mask import extract_subject, write_artifacts

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
WORK_MAX = 384                      # working resolution for blob analysis
SKIP_ALWAYS = {"__pycache__", ".git", "overlay", "source_analysis"}
# derived / working trees: not intake candidates (scope=originals)
SKIP_DERIVED = SKIP_ALWAYS | {"_analyze", "_analyze_out", "_measure_out", "working",
                              "tmp", "_tmp", "_out", "preview", "thumbs"}

# ---------------------------------------------------------------- view roles
# Ported from cc-blender-skill's reference_manifest_compiler.py VIEW_PATTERNS and
# extended with the Chinese/route-specific names actually used in this workspace.
ROLE_PATTERNS = [
    ("top", re.compile(r"top.?view|topdown|top_view|俯视|平面|鸟瞰|地图|map|overview|birdseye", re.I)),
    ("front", re.compile(r"front|正面|正立面|立绘|avatar|master|hero", re.I)),
    ("side", re.compile(r"side|侧面|侧视|profile", re.I)),
    ("back", re.compile(r"\bback\b|背面|背视", re.I)),
    ("iso", re.compile(r"iso|isometric|轴测|斜視|斜视|3\s*quarter|hero_shot", re.I)),
    ("section", re.compile(r"剖面|section|cross.?section|切面|南北剖|东西剖", re.I)),
    ("detail", re.compile(r"detail|close|macro|特写|局部|檐|台基|构件|纹样|_eaves|eave", re.I)),
    ("texture", re.compile(r"base.?color|albedo|diffuse|atlas|rough|bump|normal|light.?map|texture|素材|贴图|色卡", re.I)),
    ("context", re.compile(r"context|scene|environment|全景|环境|ward|city|street", re.I)),
]
GRADES = {"A", "B", "C", "D"}

THRESHOLDS = {
    "_source": "cc-blender-skill/reference-analysis-validator/references/metrics-and-thresholds.md [外/文档]",
    "_status": "not registered in 04; requires a measured negative sample in this workspace first",
    "mask_iou_final": 0.90,
    "mask_iou_soft": 0.85,
    "mask_iou_floor": 0.80,
    "centroid_drift_px_at_1024": 12,
    "centroid_drift_frac": 0.012,
    "bbox_center_drift_px": 12,
    "bbox_size_drift_frac": 0.03,
    "landmark_drift_frac": 0.02,
    "ssim_early": 0.75,
    "ssim_near_final": 0.88,
    "part_count": "exact",
}

MEASURABILITY = {    "min_short_side_reject": 128,     # below this: unusable at all
    "min_short_side_degraded": 256,   # below this: 形制/拓扑 only, no 尺寸推导
    "near_black_luma": 0.06,
    "near_black_ratio": 0.70,
    "near_black_px": 0.04,
    "near_white_luma": 0.94,
    "low_contrast_std": 0.035,
    "flat_wall_coverage": 0.90,
    "flat_wall_dominant": 0.95,
    "low_detail_edge_ratio": 0.30,    # batch-relative; smooth art style also trips this
    "_calibrated_on": "WitchHut / Tenshukaku / SausageUFO refs, 2026-09-23 (see 19 section 4)",
}


# ---------------------------------------------------------------- file discovery
def discover(refs_root, scope="originals", exclude_dirs=(), include=(), exclude=()):
    skip = SKIP_DERIVED if scope == "originals" else SKIP_ALWAYS
    skip = skip | {d for d in exclude_dirs if d}
    import fnmatch
    out, excluded = [], []
    for base, dirs, files in os.walk(refs_root):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in sorted(files):
            if not fn.lower().endswith(IMAGE_EXT):
                continue
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, refs_root).replace("\\", "/")
            if include and not any(fnmatch.fnmatch(rel, g) for g in include):
                excluded.append(rel)
                continue
            if any(fnmatch.fnmatch(rel, g) for g in exclude):
                excluded.append(rel)
                continue
            out.append((rel, p))
    return out, excluded


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def subject_path_key(path):
    return os.path.normcase(os.path.realpath(path))


def validate_subject_fields(subject):
    if not isinstance(subject, dict):
        raise ValueError("subject must be an object")
    if not isinstance(subject.get("target"), str) or not subject["target"].strip():
        raise ValueError("subject requires a named target")
    if subject.get("scope") not in ("whole-subject", "local-part", "subject-region"):
        raise ValueError("invalid subject scope")
    if subject.get("coordinate_space") != "normalized_xy":
        raise ValueError("coordinate_space must be normalized_xy")

    def normalized(number):
        return not isinstance(number, bool) and isinstance(number, (int, float)) and 0 <= number <= 1

    def point(value):
        return isinstance(value, (list, tuple)) and len(value) == 2 and all(normalized(number) for number in value)

    bbox = subject.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(normalized(number) for number in bbox):
        raise ValueError("bbox must contain four normalized coordinates in [0, 1]")
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must have positive width and height")
    for field in ("foreground_strokes", "background_strokes"):
        strokes = subject.get(field, [])
        if not isinstance(strokes, list):
            raise ValueError("%s must be a list" % field)
        for stroke in strokes:
            if not isinstance(stroke, dict):
                raise ValueError("%s must contain stroke objects" % field)
            points = stroke.get("points")
            radius = stroke.get("radius", 0.008)
            if not isinstance(points, list) or not points or not all(point(value) for value in points):
                raise ValueError("%s requires nonempty normalized points" % field)
            if not normalized(radius) or not 0 < radius <= 0.10:
                raise ValueError("%s radius must be in (0, 0.10]" % field)
    polygons = subject.get("ignore_polygons", [])
    if not isinstance(polygons, list):
        raise ValueError("ignore_polygons must be a list")
    for polygon in polygons:
        if not isinstance(polygon, list) or len(polygon) < 3 or not all(point(value) for value in polygon):
            raise ValueError("ignore_polygons requires polygons of at least three normalized points")
    for field, default, lower, upper in (("iterations", 5, 1, 20), ("max_side", 1280, 128, 4096)):
        value = subject.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise ValueError("%s must be an integer in [%d, %d]" % (field, lower, upper))


def validate_subject_binding(subject, path, image_size):
    if sha256(path) != subject["image_sha256"]:
        raise ValueError("image_sha256 does not match the original file: %s" % subject["file"])
    if list(image_size) != subject["image_size"]:
        raise ValueError("image_size does not match the original image: %s" % subject["file"])


def load_subjects(spec_path, refs_root):
    if spec_path is None:
        return {}
    with open(spec_path, encoding="utf-8-sig") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or document.get("schema") != "reference-subject-spec-set/1":
        raise ValueError("subjects schema must be reference-subject-spec-set/1")
    if not isinstance(document.get("views"), list):
        raise ValueError("subjects views must be a list")
    subjects = {}
    root_key = subject_path_key(refs_root)
    for index, view in enumerate(document["views"]):
        if not isinstance(view, dict):
            raise ValueError("subjects view %d must be an object" % index)
        relative = view.get("file")
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("subjects view %d requires file relative to refs root" % index)
        relative = relative.replace("\\", "/")
        if os.path.isabs(relative) or os.path.splitdrive(relative)[0]:
            raise ValueError("subject file must be relative to refs root: %s" % relative)
        path = os.path.join(refs_root, relative)
        path_key = subject_path_key(path)
        if os.path.commonpath((root_key, path_key)) != root_key:
            raise ValueError("subject file escapes refs root: %s" % relative)
        if path_key in subjects:
            raise ValueError("duplicate subject file: %s" % relative)
        digest = view.get("image_sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ValueError("subject file %s requires a valid image_sha256" % relative)
        image_size = view.get("image_size")
        if (not isinstance(image_size, list) or len(image_size) != 2 or
                any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size)):
            raise ValueError("subject file %s requires image_size [width, height]" % relative)
        subject = dict(view, file=os.path.relpath(path, refs_root).replace("\\", "/"), image_sha256=digest.lower())
        with Image.open(path) as image:
            validate_subject_binding(subject, path, image.size)
        subjects[path_key] = subject
    return subjects


def clear_mask_artifacts(path):
    stem = os.path.splitext(path)[0]
    for artifact in (path, stem + ".ignore.png", stem + ".overlay.png"):
        if os.path.isfile(artifact):
            os.remove(artifact)


def verified_observed_parts(previous, image_hash):
    """Require manual-structure-review evidence with by/source/image_sha256."""
    observed = previous.get("observed_parts")
    evidence = previous.get("observed_parts_evidence")
    if (isinstance(observed, bool) or not isinstance(observed, int) or observed < 0 or
            not isinstance(evidence, dict) or evidence.get("kind") != "manual-structure-review" or
            any(not isinstance(evidence.get(field), str) or not evidence[field].strip() for field in ("by", "source"))):
        return None, "unknown:missing_manual_structure_evidence"
    if not image_hash or evidence.get("image_sha256") != image_hash:
        return None, "unknown:manual_structure_evidence_hash_mismatch"
    return observed, "manual_structure_evidence"


# ---------------------------------------------------------------- source table
def parse_source_table(md_path, refs_root=None):
    """`| W-05 | ... | **A 一手权威** | ... | `_src/render/Swamp_Hut.png` | ... |`

    -> {relpath: {id, grade, grade_raw}}.  Grade cells in this workspace are annotated
    (e.g. ``**D 不可用**（原评 A 一手权威...）``), so take the FIRST grade letter that
    starts a cell rather than requiring a bare letter.  Glob paths (``_src/render/*.png``)
    are expanded against the refs root.
    """
    table = {}
    if not md_path or not os.path.isfile(md_path):
        return table
    glob_rows = []
    for line in open(md_path, encoding="utf-8", errors="replace"):
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        grade, grade_raw = None, None
        for c in cells:
            bare = c.strip("*_ `")
            m = re.match(r"^([ABCD])(?:\b|\s|\u4e00-\u9fff)", bare)
            if m and len(bare) <= 60:
                grade, grade_raw = m.group(1), c
                break
        specific, globbed = [], []
        for b in re.findall(r"`([^`]+)`", line):
            if not b.lower().endswith(IMAGE_EXT):
                continue
            if "*" in b and refs_root:
                import glob
                for hit in sorted(glob.glob(os.path.join(refs_root, b.replace("/", os.sep)))):
                    globbed.append(os.path.relpath(hit, refs_root).replace("\\", "/"))
            elif "*" not in b:
                specific.append(b.replace("\\", "/"))
        if not grade or not (specific or globbed):
            continue
        rid = cells[0].strip("* ") or (specific or globbed)[0]
        # specific rows win; glob rows (e.g. `_src/render/*.png`) only fill gaps.
        for t in specific:
            table[t] = {"id": rid, "grade": grade, "grade_raw": grade_raw, "listed_in": [rid]}
        glob_rows.append((rid, grade, grade_raw, globbed))
    for rid, grade, grade_raw, globbed in glob_rows:
        for t in globbed:
            if t in table:
                table[t]["listed_in"].append(rid)
            else:
                table[t] = {"id": rid, "grade": grade, "grade_raw": grade_raw, "listed_in": [rid]}
    return table


# ---------------------------------------------------------------- image measurement
def luma_stats(gray):
    h = gray.histogram()
    total = sum(h) or 1
    mean = sum(i * c for i, c in enumerate(h)) / total / 255.0
    var = sum(c * (i / 255.0 - mean) ** 2 for i, c in enumerate(h)) / total
    acc, p05, p50, p95 = 0, None, None, None
    for i, c in enumerate(h):
        acc += c
        if p05 is None and acc >= 0.05 * total:
            p05 = i / 255.0
        if p50 is None and acc >= 0.50 * total:
            p50 = i / 255.0
        if p95 is None and acc >= 0.95 * total:
            p95 = i / 255.0
    return {
        "mean": round(mean, 4),
        "std": round(var ** 0.5, 4),
        "p05": round(p05 or 0.0, 4),
        "p50": round(p50 or 0.0, 4),
        "p95": round(p95 or 0.0, 4),
        "near_black_ratio": round(sum(h[: max(1, int(0.04 * 255))]) / total, 4),
        "near_white_ratio": round(sum(h[int(0.96 * 255):]) / total, 4),
    }


def mask_tuple(result):
    """Return (binary 'L' image 0/255, mask_mode, coverage_frac)."""
    mask = result["mask"]
    if mask is None:
        reason = result["metadata"].get("reason", "no nondegenerate subject mask")
        raise ValueError("%s: %s" % (result["status"], reason))
    coverage = sum(mask.histogram()[128:]) / float(mask.width * mask.height)
    return mask, result["mode"], coverage


def build_mask(img, subject=None):
    if subject is not None:
        validate_subject_fields(subject)
    return mask_tuple(extract_subject(img, subject))


def downscale_bits(mask, work_max=WORK_MAX):
    w, h = mask.size
    scale = min(1.0, work_max / float(max(w, h)))
    ww, hh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    small = mask.resize((ww, hh), Image.NEAREST)
    data = small.tobytes()
    bits = bytearray(1 if v > 127 else 0 for v in data)
    return bits, ww, hh, scale


def components(bits, w, h, min_area):
    """8-connected labelling, iterative BFS."""
    seen = bytearray(w * h)
    comps = []
    for start in range(w * h):
        if not bits[start] or seen[start]:
            continue
        seen[start] = 1
        q = deque([start])
        area = 0
        minx = maxx = start % w
        miny = maxy = start // w
        sx = sy = 0
        while q:
            i = q.popleft()
            x, y = i % w, i // w
            area += 1
            sx += x
            sy += y
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                           (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if bits[j] and not seen[j]:
                        seen[j] = 1
                        q.append(j)
        if area >= min_area:
            comps.append({
                "area_frac": round(area / float(w * h), 5),
                "bbox_work": [minx, miny, maxx - minx + 1, maxy - miny + 1],
                "centroid_work": [round(sx / area, 2), round(sy / area, 2)],
                "touches_border": bool(minx == 0 or miny == 0 or maxx == w - 1 or maxy == h - 1),
            })
    comps.sort(key=lambda c: c["area_frac"], reverse=True)
    return comps


def mirror_iou(bits, w, h):
    inter = union = 0
    for y in range(h):
        row = y * w
        for x in range(w):
            a = bits[row + x]
            b = bits[row + (w - 1 - x)]
            if a or b:
                union += 1
                if a and b:
                    inter += 1
    return round(inter / union, 4) if union else 0.0


def edge_energy(gray):
    e = gray.filter(ImageFilter.FIND_EDGES)
    h = e.histogram()
    total = sum(h) or 1
    return round(sum(i * c for i, c in enumerate(h)) / total, 3)


def classify_role(relpath):
    name = os.path.basename(relpath)
    for role, rx in ROLE_PATTERNS:
        if rx.search(name):
            return role
    return "unknown"


def verdict_for(rec):
    m = MEASURABILITY
    short = min(rec["width"], rec["height"])
    if short < m["min_short_side_reject"]:
        return "reject:tiny", "短边 %d px < %d" % (short, m["min_short_side_reject"])
    ls = rec["luma"]
    if ls["mean"] < m["near_black_luma"] or ls["near_black_ratio"] > m["near_black_ratio"]:
        return "reject:near_black", "luma 均值 %.3f / 近黑占比 %.3f" % (ls["mean"], ls["near_black_ratio"])
    if ls["mean"] > m["near_white_luma"]:
        return "reject:near_white", "luma 均值 %.3f" % ls["mean"]
    if ls["std"] < m["low_contrast_std"]:
        return "reject:low_contrast", "luma std %.3f" % ls["std"]
    cov = rec["coverage_frac"]
    dom = rec["components"][0]["area_frac"] if rec["components"] else 0.0
    if cov is not None and cov > m["flat_wall_coverage"] and dom > m["flat_wall_dominant"]:
        return "reject:flat_wall", "覆盖率 %.3f / 主连通域 %.3f" % (cov, dom)
    if any(c["touches_border"] and c["area_frac"] > 0.15 for c in rec["components"][1:]):
        return "degraded:heavy_watermark", "存在贴边大块连通域"
    if rec.get("edge_energy_ratio", 1.0) < m["low_detail_edge_ratio"]:
        return "degraded:low_detail", "边缘能量比 %.2f（批内相对，平滑画风也会命中）" % rec["edge_energy_ratio"]
    if short < m["min_short_side_degraded"]:
        return "degraded:low_res", "短边 %d px，可读形制/拓扑，不足以支撑尺寸推导" % short
    return "usable", ""


# ---------------------------------------------------------------- pair metrics (IoU / SSIM)
def load_bits(path, work_max=WORK_MAX, subject=None):
    with Image.open(path) as im:
        im.load()
        if subject is not None:
            validate_subject_binding(subject, path, im.size)
        mask, mode, cov = build_mask(im, subject)
        bits, w, h, scale = downscale_bits(mask, work_max)
        return bits, w, h, mode


def mask_iou(a, b):
    (ab, aw, ah, _), (bb, bw, bh, _) = a, b
    if (aw, ah) != (bw, bh):
        return None
    inter = union = 0
    for i in range(aw * ah):
        x, y = ab[i], bb[i]
        if x or y:
            union += 1
            if x and y:
                inter += 1
    return round(inter / union, 4) if union else 0.0


def pair_mask_iou(reference_path, render_path, subjects):
    results = []
    for path in (reference_path, render_path):
        with Image.open(path) as image:
            image.load()
            subject = subjects.get(subject_path_key(path))
            if subject is not None:
                validate_subject_fields(subject)
                validate_subject_binding(subject, path, image.size)
            result = extract_subject(image, subject)
            mask_tuple(result)
            results.append(result)
    reference, render = results
    metadata = {"reference": reference["metadata"], "render": render["metadata"],
                "semantic_review": "unreviewed"}
    if reference["mask"].size != render["mask"].size:
        metadata["reason"] = "image sizes differ; aligned masks are required"
        return None, metadata
    ignored = ImageChops.lighter(reference["ignore"], render["ignore"])
    reference_mask = ImageChops.subtract(reference["mask"], ignored)
    render_mask = ImageChops.subtract(render["mask"], ignored)
    if ImageChops.lighter(reference_mask, render_mask).getbbox() is None:
        raise ValueError("DEGENERATE: pair has no foreground outside ignored regions")
    reference_bits, width, height, scale = downscale_bits(reference_mask)
    render_bits, render_width, render_height, render_scale = downscale_bits(render_mask)
    return mask_iou((reference_bits, width, height, reference["mode"]),
                    (render_bits, render_width, render_height, render["mode"])), metadata


def grayscale_ssim(pa, pb, size=64):
    with Image.open(pa) as ia, Image.open(pb) as ib:
        ga = ImageOps.grayscale(ia).resize((size, size), Image.BILINEAR)
        gb = ImageOps.grayscale(ib).resize((size, size), Image.BILINEAR)
        A, B = list(ga.getdata()), list(gb.getdata())
    n = len(A)
    ma, mb = sum(A) / n, sum(B) / n
    va = sum((x - ma) ** 2 for x in A) / n
    vb = sum((x - mb) ** 2 for x in B) / n
    cov = sum((A[i] - ma) * (B[i] - mb) for i in range(n)) / n
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return round(((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2)), 4)


PRIMARY_ROLES = ("front", "side")
# H4 needs an orthographic *basis*, not one magic view:
#   a height-bearing orthographic view (front / side / section)
#   + a horizontal-axis view (front / side / top)
HEIGHT_ROLES = ("front", "side", "section")
PLAN_ROLES = ("front", "side", "top")
NEAR_ROLES = ("front", "side", "back", "section")


def primary_axis_gate(records):
    """H4: does the package own an orthographic basis?

    Roles being declared is not the same as orthographic evidence existing; without this gate
    a package can pass H1 by declaring everything `context`.

    Returns (ok, near, why): `ok` = the qualifying files; `near` = partial orthographic
    evidence (including back views) that cannot alone support both height and footprint.
    """
    good = []
    near = []
    for r in records:
        role = r.get("role")
        if role not in NEAR_ROLES:
            continue
        image_usability = r.get("image_usability", r.get("usability"))
        usable = image_usability == "usable"
        grade = r.get("grade")
        qualifies = usable and grade in ("A", "B")
        if qualifies:
            good.append(r)
        near.append({"file": r["file"], "role": role,
                     "usability": image_usability, "grade": grade,
                     "blocked_by": ("grade" if (usable and not qualifies) else
                                    ("usability" if not usable else "-"))})
    height = [r["file"] for r in good if r["role"] in HEIGHT_ROLES]
    plan = [r["file"] for r in good if r["role"] in PLAN_ROLES]
    why = {"height": height, "plan": plan,
           "missing": [k for k, v in (("height", height), ("plan", plan)) if not v]}
    return height + plan, near, why


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-table", default=None)
    ap.add_argument("--subjects", default=None, metavar="JSON",
                    help="reference-subject-spec-set/1 views, bound to refs-root files by SHA256 and image size")
    ap.add_argument("--emit-masks", action="store_true")
    ap.add_argument("--strict", action="store_true", help="treat degraded:* as failure")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--max-images", type=int, default=0, help="0 = no limit")
    ap.add_argument("--scope", choices=("originals", "all"), default="originals",
                    help="originals = skip derived/working trees (default)")
    ap.add_argument("--exclude-dir", action="append", default=[],
                    help="skip any directory with this name (recorded in the report)")
    ap.add_argument("--include", action="append", default=[], metavar="GLOB")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    ap.add_argument("--pair", action="append", default=[], metavar="VIEW=REF:RENDER")
    ap.add_argument("--declare", action="append", default=[], metavar="FILE:ROLE[:PARTS]",
                    help="declare a view role (and optionally expected part count) for a file; "
                         "logged into reference_manifest.json declaration_log")
    ap.add_argument("--declare-file", action="append", default=[], metavar="TSV",
                    help="TSV/CSV of `file<TAB>role<TAB>parts<TAB>by<TAB>rule`, # comments allowed")
    ap.add_argument("--declared-by", default="unattributed", help="who declares (goes in the log)")
    a = ap.parse_args()

    refs = os.path.abspath(a.refs)
    if not os.path.isdir(refs):
        print("FAIL refs root not found:", refs)
        return 2
    try:
        subjects = load_subjects(a.subjects, refs)
    except (OSError, ValueError, TypeError) as exc:
        print("FAIL subjects:", exc)
        print(json.dumps({"mask_status": "ERROR", "mask_error": str(exc),
                          "mask_metadata": {"error": str(exc)}}, ensure_ascii=False))
        return 2
    subject_input_errors = {}
    for path_key, subject in subjects.items():
        try:
            validate_subject_fields(subject)
        except ValueError as exc:
            subject_input_errors[path_key] = {"file": subject["file"], "mask_status": "ERROR", "error": str(exc)}
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)

    prev_manifest = {}
    mp = os.path.join(out, "reference_manifest.json")
    if os.path.isfile(mp):
        try:
            old = json.load(open(mp, encoding="utf-8"))
            prev_manifest = {v.get("file"): v for v in old.get("views", [])}
        except Exception:
            prev_manifest = {}

    # ---- explicit declarations (apply before measuring so H1/H3/H4 see them)
    declarations = []
    specs = list(a.declare)
    for tsv in a.declare_file:
        if not os.path.isfile(tsv):
            print("WARN declare-file not found:", tsv)
            continue
        for line in open(tsv, encoding="utf-8-sig", errors="replace"):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.split(","))]
            cells += [""] * (5 - len(cells))
            f, role, parts, by, rule = cells[:5]
            specs.append("|".join([f, role, parts, by, rule]))
    for spec in specs:
        if "|" in spec:
            f, role, nparts_s, by, rule = (spec.split("|") + [""] * 5)[:5]
        else:
            parts = spec.split(":")
            f = parts[0]
            role = parts[1] if len(parts) > 1 else ""
            nparts_s = parts[2] if len(parts) > 2 else ""
            by, rule = a.declared_by, ""
        f = f.replace("\\", "/")
        nparts = int(nparts_s) if nparts_s else None
        entry = prev_manifest.setdefault(f, {"file": f})
        log = entry.setdefault("declaration_log", [])
        note = rule or by
        if role and entry.get("role_declared") != role:
            log.append({"date": date.today().isoformat(), "field": "role_declared",
                        "from": entry.get("role_declared"), "to": role,
                        "by": by or a.declared_by, "rule": rule or None})
            entry["role_declared"] = role
            entry["role_provenance"] = ("rule:" + rule) if rule else "manual"
        if nparts is not None and entry.get("expected_parts") != nparts:
            log.append({"date": date.today().isoformat(), "field": "expected_parts",
                        "from": entry.get("expected_parts"), "to": nparts,
                        "by": by or a.declared_by, "rule": rule or None})
            entry["expected_parts"] = nparts
        declarations.append(f)

    files, excluded = discover(refs, a.scope, a.exclude_dir, a.include, a.exclude)
    if a.max_images:
        files = files[: a.max_images]
    if not files:
        print("FAIL no images under", refs, "(scope=%s)" % a.scope)
        for error in subject_input_errors.values():
            print(json.dumps(error, ensure_ascii=False))
        return 2

    src_table = parse_source_table(a.source_table, refs)
    records = []
    for rel, path in files:
        rec = {"file": rel.replace("\\", "/"), "mask_status": "ERROR",
               "mask_mode": "none", "mask_metadata": {}, "mask_artifacts": {},
               "coverage_frac": None, "work_size": None, "components": [],
               "component_count_proxy": None, "observed_parts": None, "mirror_iou": None}
        try:
            with Image.open(path) as im:
                im.load()
                w, h = im.size
                mode = im.mode
                gray = im.convert("L")
                rec.update({
                    "file": rel.replace("\\", "/"),
                    "bytes": os.path.getsize(path),
                    "sha256": sha256(path),
                    "width": w,
                    "height": h,
                    "aspect": round(w / float(h), 4),
                    "mode": mode,
                    "has_alpha": "A" in im.getbands(),
                    "luma": luma_stats(gray),
                    "edge_energy": edge_energy(gray),
                })
                artifact_path = os.path.join(out, "overlay", rel.replace("/", "__") + ".mask.png")
                try:
                    if a.emit_masks:
                        clear_mask_artifacts(artifact_path)
                    subject = subjects.get(subject_path_key(path))
                    if subject is not None:
                        validate_subject_fields(subject)
                        validate_subject_binding(subject, path, im.size)
                    result = extract_subject(im, subject)
                    rec.update({"mask_status": result["status"], "mask_mode": result["mode"],
                                "mask_metadata": result["metadata"]})
                    if result["mask"] is not None:
                        mask, mask_mode, cov = mask_tuple(result)
                        bits, ww, hh, scale = downscale_bits(mask)
                        comps = components(bits, ww, hh, min_area=max(4, int(0.001 * ww * hh)))
                        rec.update({"coverage_frac": round(cov, 4), "work_size": [ww, hh],
                                    "components": comps, "component_count_proxy": len(comps),
                                    "mirror_iou": mirror_iou(bits, ww, hh) if ww * hh <= 200000 else None})
                    if a.emit_masks:
                        rec["mask_artifacts"] = write_artifacts(im, result, artifact_path)
                except Exception as exc:
                    rec.update({"mask_status": "ERROR", "mask_mode": "none", "mask_error": str(exc),
                                "mask_metadata": {"error": str(exc)}, "mask_artifacts": {},
                                "coverage_frac": None, "work_size": None, "components": [],
                                "component_count_proxy": None, "mirror_iou": None})
        except Exception as exc:
            rec["error"] = str(exc)
            rec["mask_metadata"] = {"reason": "image_unreadable", "error": str(exc)}
        records.append(rec)

    # batch-relative blur threshold
    energies = [r["edge_energy"] for r in records if "edge_energy" in r]
    if energies:
        energies_sorted = sorted(energies)
        median = energies_sorted[len(energies_sorted) // 2] or 1.0
        for r in records:
            if "edge_energy" in r:
                r["edge_energy_ratio"] = round(r["edge_energy"] / median, 3)
    for r in records:
        if "error" in r:
            r["role"], r["usability"], r["reason"] = "unknown", "reject:unreadable", r["error"]
            r["image_usability"], r["image_reason"] = r["usability"], r["reason"]
            continue
        r["role_auto"] = classify_role(r["file"])
        r["role"] = r["role_auto"]
        v, why = verdict_for(r)
        r["image_usability"], r["image_reason"] = v, why
        r["usability"], r["reason"] = ("reject:mask_error", r["mask_error"]) if "mask_error" in r else (v, why)
        st = src_table.get(r["file"])
        r["source_id"] = (st or {}).get("id")
        r["grade"] = (st or {}).get("grade")
        r["grade_raw"] = (st or {}).get("grade_raw")
        r["listed_in"] = (st or {}).get("listed_in")

    # ---- duplicate marking by content hash (Unity imports ship X.png + X_preview.jpg + prev_X.png)
    by_hash = {}
    for r in records:
        h = r.get("sha256")
        if not h:
            continue
        by_hash.setdefault(h, []).append(r)
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        keep = group[0]
        for r in group[1:]:
            r["duplicate_of"] = keep["file"]
    unique_files = len({r.get("sha256") or r["file"] for r in records})

    # ---- manifest (two-pass: keep previously declared expected_parts / role)
    views = []
    h3_fail = []
    for r in records:
        prev = prev_manifest.get(r["file"], {})
        declared = prev.get("expected_parts")
        observed, observation_reason = verified_observed_parts(prev, r.get("sha256"))
        r["observed_parts"] = observed
        r["observed_parts_evidence"] = prev.get("observed_parts_evidence")
        part_count_ok = None if declared is None or observed is None else declared == observed
        part_count_reason = ("unknown:expected_parts_not_declared" if declared is None else
                             observation_reason if observed is None else
                             "verified_match" if part_count_ok else "verified_count_mismatch")
        r["part_count_ok"], r["part_count_reason"] = part_count_ok, part_count_reason
        role_declared = prev.get("role_declared")
        role_effective = role_declared or r["role"]
        r["role"] = role_effective
        entry = {
            "id": r.get("source_id"),
            "grade": r.get("grade"),
            "listed_in": r.get("listed_in"),
            "file": r["file"],
            "duplicate_of": r.get("duplicate_of"),
            "role": role_effective,
            "role_auto": prev.get("role_auto") or r.get("role_auto"),
            "role_declared": role_declared,
            "role_provenance": prev.get("role_provenance"),
            "usability": r["usability"],
            "reason": r["reason"],
            "image_usability": r["image_usability"],
            "image_reason": r["image_reason"],
            "sha256": r.get("sha256"),
            "mask_status": r["mask_status"],
            "mask_metadata": r["mask_metadata"],
            "mask_artifacts": r["mask_artifacts"],
            "mask_error": r.get("mask_error"),
            "coverage_frac": r["coverage_frac"],
            "component_count_proxy": r["component_count_proxy"],
            "observed_parts": observed,
            "observed_parts_evidence": r["observed_parts_evidence"],
            "expected_parts": declared,
            "part_count_ok": part_count_ok,
            "part_count_reason": part_count_reason,
            "declaration_log": prev.get("declaration_log", []),
        }
        if declared is not None and part_count_ok is not True:
            h3_fail.append(entry)
        views.append(entry)

    manifest = {
        "schema": "urhox-reference-manifest/1",
        "generatedAt": date.today().isoformat(),
        "refsRoot": refs,
        "axisContract": {
            "front": "X width / Z height",
            "side": "Y depth / Z height",
            "back": "X width / Z height",
            "top": "X width / Y depth",
            "section": "vertical cut: Z height + one horizontal axis (state which)",
            "iso": "all three axes visible",
            "detail": "local crop, no global axis",
            "texture": "no spatial axis",
            "context": "environment, not the subject",
        },
        "thresholds": THRESHOLDS,
        "measurability": MEASURABILITY,
        "views": views,
    }
    json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    sa = os.path.join(out, "source_analysis")
    os.makedirs(sa, exist_ok=True)
    for r in records:
        fn = r["file"].replace("/", "__") + ".json"
        json.dump(r, open(os.path.join(sa, fn), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---- hard gates
    h1_fail = [r for r in records if r["role"] == "unknown"]
    h2_reject = [r for r in records if r["image_usability"].startswith("reject")]
    h2_degraded = [r for r in records if r["image_usability"].startswith("degraded")]
    h2_fail = list(h2_reject) + (list(h2_degraded) if a.strict else [])
    h4_ok, h4_near, h4_why = primary_axis_gate(records)
    mask_errors = [{"file": r["file"], "error": r["mask_error"]} for r in records if "mask_error" in r]
    processed_keys = {subject_path_key(os.path.join(refs, r["file"])) for r in records}
    mask_errors.extend(error for path_key, error in subject_input_errors.items() if path_key not in processed_keys)
    mask_status_counts = {}
    for r in records:
        status = r["mask_status"]
        mask_status_counts[status] = mask_status_counts.get(status, 0) + 1
    hard_ok = not h1_fail and not h2_fail and not h3_fail and bool(h4_ok) and not mask_errors

    # ---- optional reference vs render
    pairs = []
    for spec in a.pair:
        try:
            view, rest = spec.split("=", 1)
            ref_img, render_img = rest.split(":", 1)
            iou, mask_metadata = pair_mask_iou(ref_img, render_img, subjects)
            ssim = grayscale_ssim(ref_img, render_img)
            diagnostic_verdict = "unknown"
            if iou is not None:
                if iou >= THRESHOLDS["mask_iou_final"]:
                    diagnostic_verdict = "pass"
                elif iou >= THRESHOLDS["mask_iou_soft"]:
                    diagnostic_verdict = "pass_soft"
                elif iou < THRESHOLDS["mask_iou_floor"]:
                    diagnostic_verdict = "fail"
                else:
                    diagnostic_verdict = "watch"
            pairs.append({"view": view, "reference": ref_img, "render": render_img,
                          "mask_iou": iou, "ssim": ssim, "verdict": "unverified",
                          "diagnostic_verdict": diagnostic_verdict,
                          "diagnostic_note": "Candidate-mask thresholds only; not geometric or semantic acceptance.",
                          "mask_status": "CANDIDATE", "mask_metadata": mask_metadata,
                          "semantic_verdict": "unverified"})
        except Exception as exc:
            pairs.append({"view": spec, "error": str(exc), "mask_iou": None, "ssim": None,
                          "verdict": "unverified", "semantic_verdict": "unverified",
                          "diagnostic_verdict": "unknown",
                          "diagnostic_note": "No valid candidate-mask comparison; not geometric or semantic acceptance."})
    pair_errors = [pair for pair in pairs if "error" in pair]
    hard_ok = hard_ok and not pair_errors

    roles = {}
    for r in records:
        roles.setdefault(r["role"], []).append(r["file"])
    grades = {}
    for r in records:
        g = r.get("grade") or "ungraded"
        grades[g] = grades.get(g, 0) + 1

    report = {
        "schema": "urhox-reference-intake-report/1",
        "generatedAt": date.today().isoformat(),
        "refsRoot": refs,
        "out": out,
        "scope": a.scope,
        "excludedDirs": a.exclude_dir,
        "excludedFiles": len(excluded),
        "images": len(records),
        "uniqueBySha256": unique_files,
        "roles": {k: len(v) for k, v in sorted(roles.items())},
        "grades": grades,
        "mask_status_counts": mask_status_counts,
        "mask_errors": mask_errors,
        "H1_missing_role": [r["file"] for r in h1_fail],
        "H2_reject": [{"file": r["file"], "verdict": r["image_usability"], "reason": r["image_reason"]} for r in h2_reject],
        "H2_degraded": [{"file": r["file"], "verdict": r["image_usability"], "reason": r["image_reason"]} for r in h2_degraded],
        "H3_part_count_mismatch": [{"file": e["file"], "expected": e["expected_parts"],
                                    "observed": e["observed_parts"], "reason": e["part_count_reason"]} for e in h3_fail],
        "H3_undeclared": [r["file"] for r in records if r.get("observed_parts") is not None
                          and prev_manifest.get(r["file"], {}).get("expected_parts") is None],
        "H4_primary_axis_ok": h4_ok,
        "H4_primary_axis_detail": h4_why,
        "H4_primary_axis_near": h4_near,
        "pairs": pairs,
        "hardGatesPass": hard_ok,
    }
    json.dump(report, open(os.path.join(out, "gate_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if not a.json_only:
        L = []
        L.append("# 参考图入包闸报告\n")
        L.append("| 字段 | 值 |")
        L.append("|---|---|")
        L.append("| 生成日期 | %s |" % report["generatedAt"])
        L.append("| 参考包 | `%s` |" % refs)
        L.append("| 扫描范围 | %s%s |" % (a.scope,
                  ("（另排除目录：%s）" % "、".join(a.exclude_dir)) if a.exclude_dir else ""))
        L.append("| 受检图数 | %d（被 `--include/--exclude` 排除 %d；目录级排除不计入） |" % (report["images"], report["excludedFiles"]))
        L.append("| 去重后（sha256） | **%d** |" % report["uniqueBySha256"])
        L.append("| H1 未声明角色 | %d |" % len(h1_fail))
        L.append("| H2 不可量测（reject） | %d |" % len(h2_reject))
        L.append("| H2 降级（degraded，仅形制参考） | %d |" % len(h2_degraded))
        L.append("| H3 部件数不符 / 缺核实证据 | %d |" % len(h3_fail))
        L.append("| 掩膜状态 | %s |" % mask_status_counts)
        L.append("| H4 主轴证据（usable 且 A/B 的 front·side） | %d |" % len(h4_ok))
        L.append("| **硬门禁%s** | **%s** |" % ("（strict）" if a.strict else "", "PASS" if hard_ok else "FAIL"))
        L.append("")
        L.append("## 视图角色矩阵\n")
        L.append("| 角色 | 张数 | 文件 |")
        L.append("|---|---|---|")
        for role in ["front", "side", "back", "top", "iso", "detail", "texture", "context", "unknown"]:
            fl = roles.get(role, [])
            if fl:
                L.append("| %s | %d | %s |" % (role, len(fl), "、".join("`%s`" % f for f in fl[:6]) + (" …" if len(fl) > 6 else "")))
        missing = [rr for rr in ("front", "side", "back", "top") if rr not in roles]
        L.append("")
        L.append("缺失的主轴角色：%s" % ("、".join(missing) if missing else "无"))
        L.append("")
        if not h4_ok:
            L.append("**H4 FAIL：该包没有可量测的正交基底（usable 且来源等级 A/B 的「高度向 front/side/section」+「水平向 front/side/top」）。**")
            L.append("")
            L.append("缺哪一半：%s" % ("、".join(h4_why["missing"]) or "-"))
            L.append("")
            if h4_near:
                L.append("接近但未达标的主轴图：")
                L.append("")
                L.append("| file | role | 可量测性 | 等级 | 挡在哪 |")
                L.append("|---|---|---|---|---|")
                for x in h4_near:
                    L.append("| `%s` | %s | %s | %s | %s |" % (
                        x["file"], x["role"], x["usability"], x["grade"], x.get("blocked_by", "-")))
                L.append("")
        L.append("## 逐图\n")
        L.append("| file | id | 等级 | 角色 | 可量测性 | mask_status | 连通域代理 | 覆盖率 | 镜像 IoU | 边缘能量比 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in records:
            if "error" in r:
                L.append("| %s | - | - | - | **%s** | ERROR | - | - | - | - |" % (r["file"], r["usability"]))
                continue
            L.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %.2f |" % (
                r["file"], r.get("source_id") or "-", r.get("grade") or "-", r["role"], r["usability"],
                r["mask_status"], "-" if r["component_count_proxy"] is None else r["component_count_proxy"],
                "-" if r["coverage_frac"] is None else "%.3f" % r["coverage_frac"],
                "-" if r.get("mirror_iou") is None else "%.3f" % r["mirror_iou"],
                r.get("edge_energy_ratio", 1.0)))
        L.append("")
        if report["H2_reject"] or report["H2_degraded"]:
            L.append("## 不可量测 / 降级明细\n")
            L.append("| file | verdict | 原因 |")
            L.append("|---|---|---|")
            for x in report["H2_reject"] + report["H2_degraded"]:
                L.append("| `%s` | %s | %s |" % (x["file"], x["verdict"], x["reason"]))
            L.append("")
        if report["H3_part_count_mismatch"]:
            L.append("## 部件数不符 / 缺核实证据\n")
            L.append("| file | 声明 | 核实 | 原因 |")
            L.append("|---|---|---|---|")
            for x in report["H3_part_count_mismatch"]:
                L.append("| `%s` | %s | %s | %s |" % (x["file"], x["expected"], x["observed"], x["reason"]))
            L.append("")
        if mask_errors:
            L.append("## 掩膜错误（不等于原图不可读）\n")
            for error in mask_errors:
                L.append("- %s: %s" % (error["file"], error["error"]))
            L.append("")
        if pairs:
            L.append("## 参考 vs 渲染\n")
            L.append("IoU / SSIM 和阈值诊断仅针对候选掩膜，不构成几何或语义通过。\n")
            L.append("| view | candidate mask IoU | SSIM | 判定 | diagnostic_verdict（仅阈值诊断，非几何通过） |")
            L.append("|---|---|---|---|---|")
            for p in pairs:
                if "error" in p:
                    L.append("| %s | - | - | unverified: %s | unknown |" % (p["view"], p["error"]))
                else:
                    L.append("| %s | %s | %s | %s | %s |" % (p["view"], p["mask_iou"], p["ssim"], p["verdict"], p["diagnostic_verdict"]))
            L.append("")
        L.append("## 下一步\n")
        L.append("1. 填 `reference_manifest.json` 的 `expected_parts`，并附原图绑定的人工结构计数及 observed_parts_evidence；连通域代理不是核实部件数。")
        L.append("2. `unknown` 角色的图：补角色声明，或移出参考包（按 19 §1 H1）。")
        L.append("3. `reject:*` 的图：换图；若该角色只剩这一张，登记「该角色无合格证据」，不得用 `iso` 顶替。")
        L.append("")
        open(os.path.join(out, "gate_report.md"), "w", encoding="utf-8").write("\n".join(L))

    print("images=%d  unique(sha256)=%d  roles=%s  grades=%s" % (
        report["images"], report["uniqueBySha256"], report["roles"], report["grades"]))
    print("H1 missing role : %d %s" % (len(h1_fail), [r["file"] for r in h1_fail][:5]))
    print("H2 reject       : %d" % len(h2_reject))
    for r in h2_reject[:8]:
        print("   - %-58s %s (%s)" % (r["file"], r["usability"], r["reason"]))
    print("H2 degraded     : %d" % len(h2_degraded))
    for r in h2_degraded[:8]:
        print("   - %-58s %s (%s)" % (r["file"], r["usability"], r["reason"]))
    print("H3 mismatches   : %d" % len(h3_fail))
    for entry in h3_fail[:8]:
        print("   - %s: %s" % (entry["file"], entry["part_count_reason"]))
    print("Mask states     :", mask_status_counts)
    for error in mask_errors[:8]:
        print("MASK ERROR %s: %s" % (error["file"], error["error"]))
    for pair in pair_errors[:8]:
        print("PAIR UNVERIFIED %s: %s" % (pair["view"], pair["error"]))
    print("H4 primary axis : %s (ok=%d, near=%d, missing=%s)" % (
        "PASS" if h4_ok else "FAIL", len(h4_ok), len(h4_near), h4_why["missing"]))
    print("HARD GATES      : %s" % ("PASS" if hard_ok else "FAIL"))
    print("out ->", out)
    return 2 if mask_errors or pair_errors else 0 if hard_ok else 1


if __name__ == "__main__":
    sys.exit(main())
