#!/usr/bin/env python3
"""包结构门禁：挡住"改了文件忘了登记 / 版本不同步 / 编号不明不白"这三类事故。

checks:
  1. references/*.md 每一篇都被 SKILL.md 路由到
  2. scripts/*.py 每一个都在 SKILL.md §5.1 工具总表里
  3. assets/* 每一件都被 SKILL.md 或 references/ 里某篇引用
  4. INDEX.md 提到每一篇 reference 的编号与每一个 script 的文件名
  5. VERSION == SKILL.md metadata.version == CHANGELOG 最新条目标题
  6. references 编号连续性：允许的缺号必须写在 INDEX.md 的白名单里

usage: python skill_structure_check.py [--json]
exit: 0 全过 · 1 有结构问题 · 2 用法/文件缺失
"""

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ALLOWED_GAPS = {"17", "25"}   # 17 已合并进 05；25 下游适配章已移除（v3.51），强规则并入 08 §3.1，见 INDEX.md §3


def read(path):
    return open(path, encoding="utf-8", errors="replace").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    skill_md = os.path.join(SKILL, "SKILL.md")
    index_md = os.path.join(SKILL, "INDEX.md")
    for p in (skill_md, index_md):
        if not os.path.isfile(p):
            print("FAIL missing:", p)
            return 2
    sm, ix = read(skill_md), read(index_md)

    refs = sorted(f for f in os.listdir(os.path.join(SKILL, "references")) if f.endswith(".md"))
    scripts = sorted(f for f in os.listdir(os.path.join(SKILL, "scripts")) if f.endswith(".py"))
    assets_dir = os.path.join(SKILL, "assets")
    assets = sorted(os.listdir(assets_dir)) if os.path.isdir(assets_dir) else []
    doc_bodies = "\n".join(read(os.path.join(SKILL, "references", f)) for f in refs) + ix

    problems, stats = [], {}

    # 1 references routed
    unrouted = [f for f in refs if f not in sm]
    stats["references"] = len(refs)
    for f in unrouted:
        problems.append("reference 未进 SKILL.md 路由: " + f)

    # 2 scripts registered —— 两向校验：
    #    ① scripts/ 里的每个 .py 必须在 §5.1 出现；
    #    ② §5.1 「包内脚本」表里的每个 .py 必须真实存在（防"登记了不存在的工具"，
    #       也不把项目侧/外部工具混进来——它们写在 §5.1 顶部的位置表里）。
    unreg = [f for f in scripts if f not in sm]
    stats["scripts"] = len(scripts)
    for f in unreg:
        problems.append("script 未登记进 SKILL.md §5.1: " + f)
    sect = sm[sm.find("### 5.1"):]
    sect = sect[:sect.find("## 6")] if "## 6" in sect else sect
    on_disk = set(scripts)
    claimed = set()
    for m in re.finditer(r"^\|\s*`([^`]+\.py)`\s*\|", sect, re.M):
        claimed.add(m.group(1))
    for c in sorted(claimed - on_disk):
        problems.append("§5.1 登记了不存在的包内脚本: " + c)

    # 3 assets referenced
    for f in assets:
        if f not in doc_bodies and f not in sm:
            problems.append("asset 未被任何文档引用: " + f)
    stats["assets"] = len(assets)

    # 4 INDEX covers refs + scripts
    for f in refs:
        num = f.split("-")[0]
        if num not in ix:
            problems.append("INDEX.md 未提到编号 %s（%s）" % (num, f))
    for f in scripts:
        if f not in ix:
            problems.append("INDEX.md 未提到脚本: " + f)

    # 4b templates referenced —— 与 assets 同类：新增一层不能有孤儿文件
    tdir = os.path.join(SKILL, "templates")
    templates = sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []
    stats["templates"] = len(templates)
    for f in templates:
        if f not in doc_bodies and f not in sm:
            problems.append("template 未被任何文档引用: " + f)

    # 5 version consistency
    vfile = os.path.join(SKILL, "VERSION")
    ver_file = read(vfile).strip() if os.path.isfile(vfile) else None
    m = re.search(r'version:\s*"([0-9.]+)"', sm)
    ver_skill = m.group(1) if m else None
    chl = read(os.path.join(SKILL, "CHANGELOG.md"))
    m2 = re.search(r"^## \[([0-9.]+)\]", chl, re.M)
    ver_chl = m2.group(1) if m2 else None
    stats["version"] = {"VERSION": ver_file, "SKILL.md": ver_skill, "CHANGELOG": ver_chl}
    if not (ver_file == ver_skill == ver_chl):
        problems.append("版本不一致：VERSION=%s · SKILL.md=%s · CHANGELOG=%s"
                        % (ver_file, ver_skill, ver_chl))

    # 6 numbering continuity with explicit allowlist
    nums = sorted({f.split("-")[0] for f in refs})
    main_nums = [n for n in nums if n.isdigit() and not n.startswith("9")]
    gaps = [str(i).zfill(2) for i in range(int(main_nums[0]), int(main_nums[-1]) + 1)
            if str(i).zfill(2) not in main_nums]
    for g in gaps:
        if g in ALLOWED_GAPS and g in ix:
            continue
        problems.append("reference 编号 %s 缺号且未在 INDEX.md 白名单说明" % g)
    stats["numberingGaps"] = gaps

    # 7 引用存在性：文档里写到的包内路径必须在磁盘上真实存在
    #    （2026-10-14 加固：v3.49 曾出现 SKILL.md/INDEX.md/CHANGELOG 都指向一个
    #     references 文件、但文件根本没写的情况，旧检查只验编号不验存在）
    ref_pattern = re.compile(r"(?<![\w/.\-])(?:references|scripts)/[A-Za-z0-9_.\-]+\.(?:md|py)")
    numbered_ref = re.compile(r"(?<![\w/.\-])references/\d\d[a-z]?-[A-Za-z0-9_.\-]+\.md")
    missing = {}
    for label, body in (("SKILL.md", sm), ("INDEX.md", ix)):
        for hit in sorted(set(ref_pattern.findall(body))):
            if not os.path.isfile(os.path.join(SKILL, hit)):
                missing.setdefault(hit, set()).add(label)
    for f in refs:
        body = read(os.path.join(SKILL, "references", f))
        # 只查“编号引用”这一个强约定；references/ 正文里常引用外部包的同名文件，
        # 那些路径带包名前缀，不应被当成包内路径
        for hit in sorted(set(numbered_ref.findall(body))):
            if not os.path.isfile(os.path.join(SKILL, hit)):
                missing.setdefault(hit, set()).add("references/" + f)
    for hit in sorted(missing):
        problems.append("引用了不存在的文件：%s（来自 %s）"
                        % (hit, ", ".join(sorted(missing[hit]))[:140]))
    stats["missingReferencedFiles"] = sorted(missing)

    if a.json:
        print(json.dumps({"stats": stats, "problems": problems}, ensure_ascii=False, indent=2))
    else:
        print("structure: references=%d scripts=%d assets=%d templates=%d" % (
            stats["references"], stats["scripts"], stats["assets"], stats.get("templates", 0)))
        print("version:   VERSION=%s · SKILL.md=%s · CHANGELOG=%s" % (
            ver_file, ver_skill, ver_chl))
        print("numbering: gaps=%s（白名单 %s）" % (gaps, sorted(ALLOWED_GAPS)))
        if problems:
            print("PROBLEMS (%d):" % len(problems))
            for p in problems:
                print("   -", p)
    print("VERDICT:", "GREEN" if not problems else "PROBLEMS")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
