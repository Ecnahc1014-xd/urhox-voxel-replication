#!/usr/bin/env python3
"""校验视觉特征词表：references/22-*.md 的 §2 表格 ↔ assets/feature-taxonomy-v1.json。

rules:
  * 两处的术语集合必须一致（文档里出现但 JSON 没有、或反之 → 报错）
  * 每个术语必须有非空 `source`；`measurable` 必填（true 时必须给 measure）
  * 轴必须是六轴之一；术语不得重复

usage: python feature_taxonomy_check.py [--json]
exit: 0 一致 · 1 不一致 · 2 用法/文件缺失
"""

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DOC = os.path.join(SKILL, "references", "22-visual-feature-taxonomy.md")
JSON_PATH = os.path.join(SKILL, "assets", "feature-taxonomy-v1.json")
AXES = ("form", "material", "lighting", "color", "composition", "style_dna")


def terms_from_doc(path):
    """解析 §2 各小节的表格首列格（形如 `term`，或 `term` 后面跟中文注释）。"""
    txt = open(path, encoding="utf-8").read()
    # 只取 §2 区块
    start = txt.find("## 2 ")
    end = txt.find("## 3 ")
    body = txt[start:end] if start >= 0 and end > start else txt
    order = []
    for m in re.finditer(r"^### 2\.\d+ .*$", body, re.M):
        order.append((m.start(), m.group(0)))
    out = {}
    for i, (pos, title) in enumerate(order):
        nxt = order[i + 1][0] if i + 1 < len(order) else len(body)
        chunk = body[pos:nxt]
        axis = None
        for a in AXES:
            if "`%s`" % a in title:
                axis = a
                break
        if axis is None:
            continue
        # 首格形如 `tile-blue` 蓝瓦 或 `layered-tier`（术语后面可以跟中文注释）
        found = set(re.findall(r"^\|\s*`([^`]+)`[^|]*\|", chunk, re.M))
        out.setdefault(axis, set()).update(found)
    return out


def validate_tags(path, taxonomy):
    tags = json.load(open(path, encoding='utf-8'))
    problems = []
    if tags.get('schema') != 'urhox-feature-tags/1':
        problems.append('feature tags schema must be urhox-feature-tags/1')
    if tags.get('taxonomyVersion') != taxonomy.get('version'):
        problems.append('feature tags taxonomy version mismatch')
    images = tags.get('images')
    if not isinstance(images, list) or not images:
        return problems + ['feature tags images must be a non-empty list']
    for position, entry in enumerate(images):
        if not isinstance(entry, dict):
            problems.append('image %d must be an object' % position)
            continue
        filename = entry.get('file')
        if not isinstance(filename, str) or not filename.strip():
            problems.append('image %d is missing its source file' % position)
        provenance = entry.get('provenance', '')
        if not isinstance(provenance, str) or not (provenance == 'human' or
                any(provenance.startswith(prefix) and len(provenance) > len(prefix)
                    for prefix in ('rule:', 'external:'))):
            problems.append('image %d has invalid provenance' % position)
        axes = entry.get('axes')
        if not isinstance(axes, dict):
            problems.append('image %d axes must be an object' % position)
            continue
        for axis, labels in axes.items():
            if axis not in AXES or not isinstance(labels, list):
                problems.append('image %d has invalid axis/list: %s' % (position, axis))
                continue
            allowed = taxonomy['axes'][axis]['terms']
            for label in labels:
                valid = isinstance(label, str) and '*' not in label and (label in allowed or
                    any(term.endswith('*') and label.startswith(term[:-1]) and
                        len(label) > len(term[:-1]) for term in allowed))
                if not valid:
                    problems.append('image %d has unknown %s label: %s' % (position, axis, label))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument('--tags', help='validate an actual feature_tags.json against this taxonomy')
    a = ap.parse_args()

    for p in (DOC, JSON_PATH):
        if not os.path.isfile(p):
            print("FAIL missing:", p)
            return 2

    doc = terms_from_doc(DOC)
    data = json.load(open(JSON_PATH, encoding="utf-8"))
    js = {ax: set((data["axes"].get(ax, {}) or {}).get("terms", {}).keys()) for ax in AXES}

    problems = []
    for ax in AXES:
        only_doc = sorted(doc.get(ax, set()) - js.get(ax, set()))
        only_json = sorted(js.get(ax, set()) - doc.get(ax, set()))
        for t in only_doc:
            problems.append("%s: 文档有、JSON 缺 -> `%s`" % (ax, t))
        for t in only_json:
            problems.append("%s: JSON 有、文档缺 -> `%s`" % (ax, t))

    seen = {}
    for ax, spec in (data["axes"] or {}).items():
        if ax not in AXES:
            problems.append("unknown axis: " + ax)
        for t, meta in ((spec or {}).get("terms") or {}).items():
            if t in seen:
                problems.append("duplicate term `%s`（%s 与 %s）" % (t, seen[t], ax))
            seen[t] = ax
            if not meta.get("source"):
                problems.append("%s/%s 缺 source" % (ax, t))
            if "measurable" not in meta:
                problems.append("%s/%s 缺 measurable" % (ax, t))
            elif meta["measurable"] and not meta.get("measure"):
                problems.append("%s/%s measurable=true 但缺 measure" % (ax, t))

    if a.tags:
        try:
            problems.extend(validate_tags(a.tags, data))
        except (OSError, ValueError, TypeError, KeyError) as error:
            print('FAIL feature tags:', error)
            return 2
    total = sum(len(v) for v in js.values())
    if a.json:
        print(json.dumps({"taxonomyVersion": data.get("version"), "axes": {k: len(v) for k, v in js.items()},
                          "terms": total, "tagFile": a.tags,
                          "scope": 'taxonomy/schema only; visual label truth is not verified',
                          "problems": problems}, ensure_ascii=False, indent=2))
    else:
        print("taxonomy %s  axes=%d  terms=%d" % (data.get("version"), len(AXES), total))
        for ax in AXES:
            print("  %-12s %2d 条" % (ax, len(js[ax])))
        if problems:
            print("PROBLEMS (%d):" % len(problems))
            for p in problems[:40]:
                print("   -", p)
    print("VERDICT:", "GREEN" if not problems else "PROBLEMS")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
