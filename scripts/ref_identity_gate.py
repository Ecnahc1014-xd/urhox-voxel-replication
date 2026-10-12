#!/usr/bin/env python3
"""参考图入包闸 H5 / H6 — 参考同一性与对象在场性（只读）。

判据的**唯一出处**：`references/19-reference-image-intake-gate.md` §1（H5 / H6）
与 §1.2（声明字段与机器判据 H5-1..H5-5 / H6-1..H6-2）。本脚本不定义语义，
只执行“声明是否可核、证据链是否闭合、独立一致性读数是否达标、在场性是否签核”。

usage:
  PYTHONUTF8=1 python ref_identity_gate.py \\
      --declarations <identity_declarations.json> \\
      [--refs-root <参考包根>] [--out <目录>] [--json-only]

exit: 0 无 FAIL（UNKNOWN 不拦人） · 1 有 FAIL · 2 用法 / 文件缺失

边界（必须读）：脚本**不能判语义真伪**。`present: true` 是人/视觉签核的结果
（declared_by / declared_at / declared_rule），脚本只保证“没有被静默跳过”。
把未签核的 present 当已核实 = 伪造 H6 通过（同 `10` I-01b 的空输入哈希假绿）。
"""

import argparse
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
except ImportError:            # 只影响 bbox 的“落在帧内”检查；不因此拦人
    Image = None

EVIDENCE_KINDS = {
    "official_label", "poi_list", "place_name", "version_id", "capture_date", "official_map",
    "source_id",
}
ANCHOR_USAGES = {"anchor", "compare_board", "reference_slot"}
GENERATORS = {"external", "self", "unknown"}
QUESTION_FIELDS = ("object", "region", "version")
MAX_BBOX_FRACTION = 0.98        # 位置框不许几乎占满整帧（等价于没框）


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(refs_root, p):
    if not p:
        return None
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(refs_root or ".", p))


def check_image(rec, refs_root):
    """returns (verdict, checks[])  verdict ∈ {PASS, FAIL, UNKNOWN}"""
    checks = []

    def add(name, ok, reason, unknown=False):
        checks.append({"check": name,
                       "verdict": "UNKNOWN" if unknown else ("PASS" if ok else "FAIL"),
                       "reason": reason})

    usage = set(rec.get("usage") or [])
    file_rel = rec.get("file") or ""
    path = resolve(refs_root, file_rel)

    # --- 文件与哈希（H5-3 的一半：证据链的物证侧）
    if not path or not os.path.isfile(path):
        add("file", False, "文件不存在：%s" % (file_rel or "<空>"))
        return "FAIL", checks
    actual = sha256_of(path)
    declared = rec.get("sha256")
    add("file", not declared or declared == actual,
        "sha256 %s" % ("一致" if declared == actual else "不符：声明 %s / 实际 %s" % (declared, actual)))

    # --- H5-1 三问齐备
    missing = [q for q in QUESTION_FIELDS
               if not str(rec.get(q) or "").strip() or str(rec.get(q)).strip().lower() in ("unknown", "n/a", "na", "-")]
    add("H5-1 三问", not missing,
        "对象/区域/版本齐备且非空" if not missing else "未回答：%s" % ",".join(missing))

    # --- H5-2 每问至少一条**非自造**证据，kind 在白名单
    ev = rec.get("evidence") or []
    gen = rec.get("generator", "unknown")
    by_q = {}
    for e in ev:
        if (e.get("generator") or gen) == "self":        # 我方产物不能自证（01 §1 / H5-3）
            continue
        by_q.setdefault(e.get("question"), []).append(e)
    bad_kinds = sorted({e.get("kind") for e in ev if e.get("kind") not in EVIDENCE_KINDS})
    thin = [q for q in QUESTION_FIELDS if not by_q.get(q)]
    add("H5-2 证据齐备", not thin and not bad_kinds,
        ("每问有非自造证据，kind 合法" if not (thin or bad_kinds)
         else "无非自造证据的提问 %s；非法 kind %s" % (thin, bad_kinds)))

    # --- H5-3 证据可解析（路径存在 / sha256 一致）；自造条目只作线索不作证据
    unresolved = []
    for e in ev:
        ep = resolve(refs_root, e.get("path"))
        if not ep or not os.path.isfile(ep):
            unresolved.append("%s:<%s>" % (e.get("question"), e.get("path")))
            continue
        if e.get("sha256") and sha256_of(ep) != e["sha256"]:
            unresolved.append("%s:sha256 不符" % e.get("question"))
    n_self = sum(1 for e in ev if (e.get("generator") or gen) == "self")
    add("H5-3 证据链", not unresolved and gen in GENERATORS,
        (("证据条目均可解析；其中自造条目 %d 条（不计入证据）" % n_self) if (not unresolved and gen in GENERATORS)
         else "不可解析 %s；generator=%s（自造条目 %d 条不计入）" % (unresolved, gen, n_self)))

    # --- H5-4 区域问的独立一致性读数
    region_ev = by_q.get("region") or []
    needs_consistency = any(e.get("kind") in ("poi_list", "official_map") for e in region_ev)
    if needs_consistency or rec.get("consistency"):
        c = rec.get("consistency") or {}
        thr = c.get("threshold")
        got = c.get("land_rate")
        base = c.get("baseline_land_rate")
        ok = (got is not None and thr is not None and got >= thr)
        clip = c.get("clip_complete")
        ok = ok and (clip is not False)
        add("H5-4 独立一致性",
            ok,
            ("落点一致率 %.3f ≥ 阈值 %s；裁剪完整性 %s" % (got, thr, clip)
             if got is not None else "未附独立一致性读数（区域问以官方图/POI 为证据时必须附）")
            + ("" if base is None else "；对照基准 %.3f" % base))
    else:
        add("H5-4 独立一致性", True, "区域问未以本区官方图/POI 为证据，本项不适用", unknown=False)

    # --- H5-5 零结果登记
    zr = rec.get("zero_result") or []
    bad_zero = []
    for z in zr:
        q = z.get("question")
        if not by_q.get(q):
            bad_zero.append(q)
    add("H5-5 零结果", not bad_zero,
        "零结果已登记且不充当通过；%s" % ("无" if not bad_zero else "有零结果且无其他证据的提问 %s" % bad_zero))

    # --- H6 在场性
    needs_present = bool(usage & ANCHOR_USAGES)
    present = rec.get("present")
    if needs_present:
        add("H6-1 在场性", present is True,
            "usage=%s，present=%s%s" % (sorted(usage), present,
                                        "" if present is not None else "（未声明）"))
    else:
        add("H6-1 在场性", True, "usage=%s 不要求在场性" % sorted(usage))

    bbox = rec.get("subject_bbox")
    if present is True:
        if not bbox or len(bbox) != 4:
            add("H6-2 位置框", False, "present=true 但未给 4 元位置框 [x0,y0,x1,y1]")
        elif Image is None:
            add("H6-2 位置框", True, "有位置框；Pillow 缺失，帧内性未验", unknown=True)
        else:
            w, h = Image.open(path).size
            x0, y0, x1, y1 = bbox
            inside = 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
            frac = ((x1 - x0) * (y1 - y0)) / float(w * h)
            add("H6-2 位置框", inside and 0 < frac < MAX_BBOX_FRACTION,
                "框 %s 于 %dx%d：帧内=%s 面积占比=%.3f" % (bbox, w, h, inside, frac))
        if rec.get("close_up") and not rec.get("mother_image"):
            add("H6-2b 特写母图", False, "close_up=true 但缺 mother_image")
    else:
        add("H6-2 位置框", True, "present≠true，本项不适用")

    # --- 签核（纪律项：声明≠核实）
    signed = bool(rec.get("declared_by")) and bool(rec.get("declared_at")) and bool(rec.get("declared_rule"))
    add("签核", signed, "declared_by/at/rule 齐备" if signed else "缺签核字段（声明≠核实）")

    verdict = "FAIL" if any(c["verdict"] == "FAIL" for c in checks) else (
        "UNKNOWN" if any(c["verdict"] == "UNKNOWN" for c in checks) else "PASS")
    return verdict, checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--declarations", required=True)
    ap.add_argument("--refs-root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.declarations):
        print("FAIL 声明文件不存在：%s" % a.declarations)
        return 2
    with open(a.declarations, encoding="utf-8") as fh:
        doc = json.load(fh)
    images = doc.get("images") if isinstance(doc, dict) else doc
    if not isinstance(images, list) or not images:
        print("FAIL 声明文件里没有 images 列表（空输入不是通过）")
        return 2

    refs_root = a.refs_root or doc.get("refs_root") if isinstance(doc, dict) else a.refs_root

    results = []
    for rec in images:
        verdict, checks = check_image(rec, refs_root)
        results.append({"file": rec.get("file"), "usage": rec.get("usage"),
                        "verdict": verdict, "checks": checks})

    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    report = {
        "subject": doc.get("subject") if isinstance(doc, dict) else None,
        "declarations": os.path.abspath(a.declarations),
        "refs_root": refs_root,
        "images": len(results),
        "fail": n_fail,
        "unknown": sum(1 for r in results if r["verdict"] == "UNKNOWN"),
        "results": results,
    }

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        jp = os.path.join(a.out, "identity_report.json")
        with open(jp, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        mp = os.path.join(a.out, "identity_report.md")
        with open(mp, "w", encoding="utf-8") as fh:
            fh.write("# H5/H6 参考同一性与在场性报告\n\n")
            fh.write("| 图 | 用途 | 判定 | 不通过的检查 |\n|---|---|---|---|\n")
            for r in results:
                bad = [c["check"] for c in r["checks"] if c["verdict"] == "FAIL"]
                fh.write("| %s | %s | %s | %s |\n" % (r["file"], ",".join(r["usage"] or []),
                                                      r["verdict"], "; ".join(bad) or "-"))
        print("report: %s / %s" % (jp, mp))

    if a.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in results:
            print("%-6s %s" % (r["verdict"], r["file"]))
            for c in r["checks"]:
                if c["verdict"] != "PASS" or True:
                    print("        [%s] %s — %s" % (c["verdict"], c["check"], c["reason"]))
        print("H5/H6: %d images · FAIL %d · UNKNOWN %d" % (len(results), n_fail, report["unknown"]))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
