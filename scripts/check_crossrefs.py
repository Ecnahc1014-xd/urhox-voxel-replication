#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""交叉引用检查器：让"其余文件只留指针"这条维护规则变成机器门禁。

背景：本 Skill 靠"一条规则只能有一个出处 + 其余文件只留指针"维持一致性；一旦指针
指向不存在的文件或不存在的节号，就会出现**看似有出处、实际无出处**的规则——这是文档
类仓库最隐蔽的漂移。本脚本把这种漂移变成可复现的退出码。

能查到的两类问题：
  MISSING-FILE     形如 `references/12-xxx.md` 的目标文件不存在
  MISSING-SECTION  目标文件存在，但其标题里没有 §<n> 这个节号

用法
----
  python scripts/check_crossrefs.py [--root <skill根>] [--json out.json]

退出码
------
  0 = 无悬空指针
  1 = 有悬空指针（逐条打印）
  2 = 输入非法（找不到 SKILL.md / references 目录）

已知局限（不谎报覆盖）：
  * 只认 "文件名 + §节号" 这种显式形式；只说"见上文/见下节"的指针查不到。
  * 只比对节号是否存在，不比对节号内容是否真的讲了那件事。
  * 表格里跨行书写的指针可能漏检。
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 目标文件形态：00-xx.md / 09a-xx.md / 90-xx.md / SKILL.md
FILE_TOKEN = r"(?:references/)?((?:0[0-9]|1[0-9]|9[0-9])[a-z]?(?:-[a-z0-9]+)*\.md)"
SECTION = r"§\s*([0-9]+(?:\.[0-9]+)*)"
# 本仓库更常用的简写：`07` §5、`10` I-03
BARE = r"`((?:0[0-9]|1[0-9]|9[0-9])[a-z]?)`"
TOKEN = r"([ABCDI]-?[0-9]+[a-z]?|[ABCD][0-9]+[a-z]?)"
PATTERNS = [
    re.compile(FILE_TOKEN + r"[^0-9§\n]{0,12}" + SECTION),
    re.compile(r"`" + FILE_TOKEN + r"`[^0-9§\n]{0,12}" + SECTION),
    re.compile(BARE + r"[^0-9§\n]{0,12}" + SECTION),
]
# `10` I-03 / `04` 表 B6 这类条目引用
ITEM_PATTERNS = [
    re.compile(BARE + r"[^\n]{0,10}?" + r"((?:I|B|C|D|A)-?[0-9]+[a-z]?)"),
]


def collect_targets(root):
    files = {}
    for p in sorted(glob.glob(os.path.join(root, "references", "*.md"))):
        files[os.path.basename(p)] = p
    skill = os.path.join(root, "SKILL.md")
    if os.path.isfile(skill):
        files["SKILL.md"] = skill
    return files


def short_map(targets):
    """`07` -> 07-delivery-and-reporting.md；`09a` -> 09a-source-catalog.md"""
    out = {}
    for name in targets:
        m = re.match(r"((?:0[0-9]|1[0-9]|9[0-9])[a-z]?)", name)
        if m and name != "SKILL.md":
            out.setdefault(m.group(1), name)
    return out


def section_ids(path):
    text = io.open(path, encoding="utf-8").read()
    ids = set()
    for m in re.finditer(r"^#{2,4}\s+([0-9]+(?:\.[0-9]+)*)", text, re.M):
        ids.add(m.group(1))
        # 允许父节指针命中：见 "§4" 时 4.1/4.2 存在也算命中
    for sid in list(ids):
        if "." in sid:
            ids.add(sid.split(".")[0])
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check that `file.md` §n pointers resolve")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(os.path.join(root, "references")):
        print("ERROR: no references/ under %s" % root, file=sys.stderr)
        return 2
    targets = collect_targets(root)
    if not targets:
        print("ERROR: no markdown targets found", file=sys.stderr)
        return 2
    heads = {name: section_ids(p) for name, p in targets.items()}
    shorts = short_map(targets)
    bodies = {name: io.open(p, encoding="utf-8").read() for name, p in targets.items()}

    problems = []
    checked = 0
    for name, path in sorted(targets.items()):
        text = bodies[name]
        for pat in PATTERNS:
            for m in pat.finditer(text):
                target, sec = m.group(1), m.group(2)
                if target in shorts:
                    target = shorts[target]
                if target == name:
                    continue
                checked += 1
                if target not in targets:
                    problems.append({"in": name, "kind": "MISSING-FILE",
                                     "target": target, "section": sec,
                                     "line": text[:m.start()].count("\n") + 1})
                elif sec not in heads[target]:
                    problems.append({"in": name, "kind": "MISSING-SECTION",
                                     "target": target, "section": sec,
                                     "line": text[:m.start()].count("\n") + 1})
        for pat in ITEM_PATTERNS:
            for m in pat.finditer(text):
                short, item = m.group(1), m.group(2)
                target = shorts.get(short)
                if not target or target == name:
                    continue
                checked += 1
                if item not in bodies[target]:
                    problems.append({"in": name, "kind": "MISSING-ITEM",
                                     "target": target, "section": item,
                                     "line": text[:m.start()].count("\n") + 1})

    seen, uniq = set(), []
    for p in problems:
        k = (p["in"], p["kind"], p["target"], p["section"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)

    report = {"tool": "check_crossrefs.py", "root": root,
              "files_scanned": len(targets), "pointers_checked": checked,
              "problem_count": len(uniq), "problems": uniq}
    if args.json_out:
        io.open(args.json_out, "w", encoding="utf-8").write(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print("crossref: %d files, %d pointers checked, %d dangling"
          % (len(targets), checked, len(uniq)))
    for p in uniq:
        print("  %-16s %s:%d  %s §%s" % (p["kind"], p["in"], p["line"],
                                         p["target"], p["section"]))
    return 1 if uniq else 0


if __name__ == "__main__":
    raise SystemExit(main())
