#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成/校验 cases/ 的索引（README.md），并把「三层参考价值标准」变成机器门禁。

三层标准（案例存在的意义，不是规范层）：
  L1 输入侧  —— `## 0A 起手冻结值`：下一个对象能不能照着开工
  L2 判据    —— `## 0B 冻结纪律` + `## 0C 拒收读数/伪读数筛查`：甄别能力能不能搬走
  L3 可复核  —— `## 0D 断言↔复核`：一条命令/一个文件能不能回到源头

反向规则：与规范层重复的通则、仪器原理解释、与表头同义的字段行、逐轮无变化行、
不可行动的限制项，都不该出现在案例里——缺 0A~0D 即为违反。

`--check` 一次跑五类门禁（任一失败退出码 1）：
  META      元数据键齐全、as-of 非空
  LAYERS    0A/0B/0C/0D 齐全且各自有实质内容
  VALUE     声明的 voxel 与正文一致；花费行的 as-of 与声明一致（防复制粘贴型错误）
  COVERAGE  声明覆盖的风险编号（rset）在正文里一个都不少（防重写时误删）
  TOOLS     0D 引用的 .py 脚本在工程侧真实存在（需 --project-root 或 $URHOX_REPLICATION_ROOT）

用法：
    python scripts/case_index.py                       # 重新生成 cases/README.md
    python scripts/case_index.py --check               # 门禁（META/LAYERS/VALUE/COVERAGE）
    python scripts/case_index.py --check --project-root "D:/项目/体素建模测试回"
    python scripts/case_index.py --check --cases /tmp/cases_copy   # 负样本测试用

负样本纪律：任何仪器都必须有负样本。改动本脚本后，至少用下面五类破坏各跑一次，
确认它们分别被判失败（历史实测：曾靠 COVERAGE 抓回被误删的 R-10 / R-13 / R-15）：
  a) 删掉 `## 0C` 整节            -> LAYERS 失败
  b) 把 voxel 声明改成 0.125      -> VALUE 失败
  c) 删掉 `asof:` 行              -> META 失败
  d) 删掉某条风险行（如 R-5）     -> COVERAGE 失败
  e) 0D 改成引用 tools/nope.py    -> TOOLS 失败
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CASES = os.path.join(ROOT, "cases")
REQUIRED = ("object", "type", "tag", "asof", "takeaway", "truth", "next",
            "project", "voxel", "costasof", "rset")
BLOCK = re.compile(r"<!--\s*case-meta\s*(.*?)-->", re.S)
HEADING = re.compile(r"^(#{1,5})\s*(.*)$", re.M)
LAYER = re.compile(r"^0([ABCD])\b\s*(.*)$")
VALUE_VOCAB = ("0.0625", "0.125", "0.25", "0.5", "1", "2")


# ---------------------------------------------------------------- 解析

def parse_meta(text: str) -> dict:
    m = BLOCK.search(text)
    meta: dict = {}
    if m:
        for line in m.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def parse_layers(text: str) -> dict:
    """切成 0A/0B/0C/0D 四段。"""
    marks = []
    for m in HEADING.finditer(text):
        lm = LAYER.match(m.group(2).strip())
        marks.append((m.start(), lm.group(1) if lm else None))
    out: dict = {}
    for i, (pos, letter) in enumerate(marks):
        if letter is None:
            continue
        end = len(text)
        for nxt, _ in marks[i + 1:]:
            end = nxt
            break
        out[letter] = text[pos:end]
    return out


def load(path: str) -> dict:
    text = io.open(path, encoding="utf-8").read()
    return {"file": os.path.basename(path), "text": text,
            "meta": parse_meta(text), "layers": parse_layers(text)}


def collect(cases_dir: str) -> list:
    if not os.path.isdir(cases_dir):
        return []
    files = sorted(f for f in os.listdir(cases_dir)
                   if f.endswith(".md") and f != "README.md")
    return [load(os.path.join(cases_dir, f)) for f in files]


# ---------------------------------------------------------------- 助手

def rows(section: str) -> int:
    return sum(1 for l in section.splitlines() if l.strip().startswith("|"))


def bullets(section: str) -> int:
    return sum(1 for l in section.splitlines()
               if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", l))


def substance(section: str) -> int:
    return max(rows(section) - 1, bullets(section))  # 表头行不算内容


def rset(spec: str) -> set:
    out: set = set()
    if not spec or spec.strip().lower() in ("none", "n/a", "-"):
        return out
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


# ---------------------------------------------------------------- 门禁

def gate_meta(items: list) -> list:
    bad = []
    for it in items:
        missing = [k for k in REQUIRED if not it["meta"].get(k)]
        if missing:
            bad.append(f'{it["file"]}: 缺字段 {", ".join(missing)}')
        elif it["meta"].get("asof") in ("", "UNVERIFIED"):
            bad.append(f'{it["file"]}: as-of 未填或未验证')
    return bad


def gate_layers(items: list) -> list:
    bad = []
    for it in items:
        L = it["layers"]
        for letter, name in (("A", "起手冻结值"), ("B", "冻结纪律"),
                             ("C", "拒收/筛查"), ("D", "断言↔复核")):
            if letter not in L:
                bad.append(f'{it["file"]}: 缺 `## 0{letter}`（{name}）')
                continue
            n = substance(L[letter])
            need = 1 if letter == "D" else 2
            if n < need:
                bad.append(f'{it["file"]}: 0{letter}（{name}）内容过薄'
                           f'（{n} 条，至少 {need} 条）')
        d = L.get("D", "")
        if d and not (".py" in d or ".json" in d or ".md" in d
                      or "无" in d or "python" in d):
            bad.append(f'{it["file"]}: 0D 既无命令/文件引用，也未明写"无"')
    return bad


def gate_value(items: list) -> list:
    bad = []
    for it in items:
        meta, text, L = it["meta"], it["text"], it["layers"]
        vox = (meta.get("voxel") or "").strip()
        if vox and vox.lower() not in ("n/a", "none", "-"):
            a = L.get("A", "")
            if not any("体素" in l and vox in l for l in a.splitlines()):
                bad.append(f'{it["file"]}: 0A 里没有“体素…{vox}”的行（声明 voxel={vox}）')
            for line in text.splitlines():
                if "voxel_size" not in line:
                    continue
                cells = [c.strip() for c in line.split("|")]
                nums = re.findall(r"\d+\.?\d*", cells[-2]) if len(cells) >= 3 else []
                if nums and abs(float(nums[-1]) - float(vox)) > 1e-9:
                    bad.append(f'{it["file"]}: 审计行 voxel_size={nums[-1]} '
                               f'与声明 voxel={vox} 冲突（防复制粘贴型错误）')
                break
        casof = (meta.get("costasof") or "").strip()
        cost_lines = [l for l in text.splitlines() if "花费" in l]
        if casof.lower() in ("n/a", "none", "-"):
            pass
        else:
            for l in cost_lines:
                if casof not in l:
                    bad.append(f'{it["file"]}: 花费行缺 as-of `{casof}` → {l.strip()[:60]}')
                    break
    return bad


def gate_coverage(items: list) -> list:
    bad = []
    for it in items:
        want = rset(it["meta"].get("rset", ""))
        if not want:
            continue
        got = {int(n) for n in re.findall(r"R-(\d+)", it["text"])}
        missing = sorted(want - got)
        if missing:
            bad.append(f'{it["file"]}: 声明覆盖的风险编号在正文里缺失 '
                       f'{["R-%d" % m for m in missing]}（rset={it["meta"].get("rset")}）')
    return bad


def gate_tools(items: list, project_root: str | None) -> tuple:
    """0D 里引用的 .py 必须在工程侧真实存在；无 project_root 则跳过。"""
    if not project_root or not os.path.isdir(project_root):
        return [], 0
    bad, checked = [], 0
    for it in items:
        proj = (it["meta"].get("project") or "").strip()
        if not proj or proj.lower() in ("n/a", "none", "-"):
            continue
        base = os.path.join(project_root, proj)
        if not os.path.isdir(base):
            bad.append(f'{it["file"]}: 工程目录不存在 {base}')
            continue
        seen = set()
        for tok in re.findall(r"[A-Za-z0-9_./-]+\.py", it["layers"].get("D", "")):
            tok = tok.lstrip("./").replace("*", "")
            if tok in seen:
                continue
            seen.add(tok)
            checked += 1
            if not os.path.exists(os.path.join(base, tok)):
                bad.append(f'{it["file"]}: 0D 引用的脚本不存在 → {proj}/{tok}')
    return bad, checked


# ---------------------------------------------------------------- 索引

def render(items: list) -> str:
    lines = [
        "# 案例包（随包发行快照）",
        "",
        "> **本目录是“某个对象当时做到了什么、还缺什么”的发行快照，不是规范。**",
        "> - 规范层（应当怎么做）在 `../references/`；",
        "> - 真值与逐轮更新在**工程侧** `docs/复刻数据记录/`，**引用任何数字前回查该处留证件**；",
        "> - 本目录默认**不读**（渐进披露第三层）：需要“看一份填好的记录长什么样”时再读，一次读一份。",
        "",
        f"共 **{len(items)}** 份。索引由 `scripts/case_index.py` 生成，请勿手工编辑本文件。",
        "",
        "| 文件 | 对象 | 类型 | 终轮/版本 | 工程目录 | as-of | 一句话可复用结论 |",
        "|---|---|---|---|---|---|---|",
    ]
    for it in items:
        m = it["meta"]
        lines.append("| `{f}` | {o} | {t} | `{g}` | `{p}` | {a} | {k} |".format(
            f=it["file"], o=m.get("object", "?"), t=m.get("type", "?"),
            g=m.get("tag", "?"), p=m.get("project", "?"), a=m.get("asof", "?"),
            k=m.get("takeaway", "?")))
    lines += ["", "## 每个对象的下一步唯一动作", ""]
    for it in items:
        m = it["meta"]
        lines.append("- **{o}**（`{f}`）：{n}".format(
            o=m.get("object", "?"), f=it["file"], n=m.get("next", "（未填）")))
    lines += [
        "",
        "## 三层参考价值标准（`scripts/case_index.py --check` 机器门禁）",
        "",
        "| 层 | 章节 | 门禁要求 | 反例（会被判失败） |",
        "|---|---|---|---|",
        "| L1 输入侧 | `## 0A 起手冻结值` | 至少 1 条实质内容 | 只有结果数字、没有冻结参数 → 下一个对象开不了工 |",
        "| L2 判据 | `## 0B 冻结纪律` + `## 0C 拒收/伪读数筛查` | 各至少 2 条 | 只写“某值已撤回”不写怎么识别 → 甄别能力不可搬 |",
        "| L3 可复核 | `## 0D 断言↔复核` | 至少 1 条，且含命令 / 文件引用；或明写“无” | 数字没有回源路径 → 结论不可自证 |",
        "",
        "另外四类门禁：**META** 键齐全、**VALUE** 声明的 `voxel`/`costasof` 与正文一致、",
        "**COVERAGE** 声明的 `rset` 风险编号一条不少、**TOOLS** 0D 引用的脚本在工程侧真实存在",
        "（后一类需 `--project-root` 或环境变量 `URHOX_REPLICATION_ROOT`）。",
        "",
        "反向规则：与规范层重复的通则、仪器原理解释、与表头同义的字段行、逐轮无变化行、",
        "不可行动的限制项都不该出现在案例里；缺 0A~0D 即视为违反。",
        "",
        "## 怎么用这些案例",
        "",
        "1. **只看格式**：任意一份即可，看的是“一份合格记录包含哪些字段”（0A~0D + 口径表 + 门禁 + 留证件 + 未闭合项）。",
        "2. **看判定边界**：接地率 `0.62` 是拆分口径不是缺陷、檐口比 `0.40` 被撤回、层数无 A 级确认=永久局限——这类“看似不达标其实是口径”的例子。",
        "3. **看反面教材**：每份的“未闭合”节是跨对象共性的“从没测过的东西”清单。",
        "",
        "## 边界",
        "",
        "- 案例里的数字**随轮次变化**（同一对象已出现 `final4→final9`、`r2r3→r2r9`、`r4→r6` 多轮）。",
        "- 跨对象复用前**必须重新测量**；案例数字不得作为阈值或门槛使用。",
        "- 门禁只保证“结构合格 + 声明与正文一致”，**不验数字与工程侧留证件一致**；那一条只能靠现场回查。",
        "- 新增/修改案例后跑 `python scripts/case_index.py`（生成）与 `--check`（门禁）。",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(description="生成/校验 cases/ 索引与三层门禁")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--cases", default=DEFAULT_CASES, help="案例目录（负样本测试用）")
    ap.add_argument("--project-root", default=os.environ.get("URHOX_REPLICATION_ROOT"),
                    help="工程侧根目录，用于校验 0D 引用的脚本是否存在")
    args = ap.parse_args()

    items = collect(args.cases)
    if not items:
        print(f"ERROR: {args.cases} 下没有案例文件", file=sys.stderr)
        return 1

    checks = [("META", gate_meta(items)),
              ("LAYERS", gate_layers(items)),
              ("VALUE", gate_value(items)),
              ("COVERAGE", gate_coverage(items))]
    tools_bad, tools_n = gate_tools(items, args.project_root)
    checks.append(("TOOLS", tools_bad))

    bad = []
    for name, errs in checks:
        note = ""
        if name == "TOOLS" and not args.project_root:
            note = "（跳过：未给 --project-root / $URHOX_REPLICATION_ROOT）"
        elif name == "TOOLS":
            note = f"（校验 {tools_n} 个引用）"
        elif name == "COVERAGE":
            cov = [it["meta"].get("rset") for it in items
                   if rset(it["meta"].get("rset", ""))]
            note = f"（{len(cov)} 份声明了 rset）"
        print(f'{name:<9} {"FAIL" if errs else "PASS":<4} {len(errs)} 个问题{note}')
        bad += errs

    if bad:
        print("\n失败明细：", file=sys.stderr)
        for b in bad:
            print("  - " + b, file=sys.stderr)
        return 1

    if args.check:
        print(f"\nOK: {len(items)} 份案例通过全部门禁")
        return 0
    io.open(os.path.join(args.cases, "README.md"), "w",
            encoding="utf-8", newline="\n").write(render(items))
    print(f"OK: 已生成 {os.path.join(args.cases, 'README.md')}（{len(items)} 份案例）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
