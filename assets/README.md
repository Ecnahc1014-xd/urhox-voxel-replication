# assets/ — 外部参考资产的机器可读索引

本目录是 **B（抽取）与 D（提炼）共用的地基**：把 `docs/refs-staging/` 里三个参考包的 83 个条目，
变成一份可查询、可校验、可驱动工作流的清单。

| 文件 | 角色 | 谁写 |
|---|---|---|
| `external-skill-curation.json` | **人的判断**：采纳等级、依据、阶段、目标环节、要抽的件、要提的知识 | 人（或 agent 代为初判后由 owner 复核） |
| `external-skills-index.json` | **机器产物**：把判断与包内实况合并后的行式索引 | `scripts/external_asset_index.py --build` |

判断与实况分离的理由：`--check` 能证明「索引没漂」，但它证明不了「判断是对的」。
`b` 字段（`curated` / `provisional`）就是用来区分这两件事的：
`curated` = 已读过该条目的 `SKILL.md` 或脚本头部；`provisional` = 仅依据包内 MANIFEST 的描述与文件清单。

## 字段

| 字段 | 含义 |
|---|---|
| `g` | 采纳等级 P1 直接接 / P2 借流程 / P3 借词表·口径 / P4 只作参照·反例 |
| `b` | 判定依据 curated / provisional / uncurated |
| `ph` | 适用阶段：`I` 规模化采集与视觉特征提取 · `II` 资源高效自动化 · `[]` = 库存 |
| `t` | 目标环节 G0–G7 |
| `x` | 建议抽取到 `tools/external/` 的可执行件（包内相对路径，可为 glob） |
| `k` | 建议提炼进 `references/2x` 的知识件 |
| `n` | 一句话备注（含风险提示） |

## 常用命令

```bash
# 重建索引（会打印等级/阶段分布与问题）
PYTHONUTF8=1 python scripts/external_asset_index.py --build

# 校验：索引 ↔ 现场文件 ↔ curation 三方对账（改过包或 curation 后必跑）
PYTHONUTF8=1 python scripts/external_asset_index.py --check

# 出工作清单（B 的抽取范围、D 的提炼范围）
PYTHONUTF8=1 python scripts/external_asset_index.py --worklist --grade P1
PYTHONUTF8=1 python scripts/external_asset_index.py --worklist --phase I
```

## 首轮统计（2026-09-23）

| 维度 | 分布 |
|---|---|
| 条目 | 83（GitHub 24 · ClawHub 59） |
| 含可执行件 | 47 · 纯文档 36 |
| 采纳等级 | **P1 12** · P2 15 · P3 38 · P4 18 |
| 阶段 | **I 24** · II 23 · I+II 3 · 库存 33 |
| 判定依据 | curated **50** · stock **34** · provisional **0** |

> **`provisional` 已清零**（2026-09-23）：84 条全部读过并定级。`stock` = 已判定当前阶段不需要，不是"未读"。

> `provisional` 的 57 条是**下一步要读掉的**；在它们变成 `curated` 之前，其等级不得作为决策依据。

## 相关

- 采纳纪律与红线：`references/18-external-skill-adoption.md`
- 抽取目标目录与依赖实况：`<工作区>/tools/external/`（每件带 `_PROVENANCE.json` 与 `_DEPS.md`）
- 抽取工具：`scripts/external_tool_fetch.py`（`--list` / `--apply` / `--probe`）

## 运行环境

**不在本文件重复**：解释器分工、安装位置、依赖判据与环境验收的唯一出处是
`references/20-runtime-environment-and-dependencies.md`；跑一次 `scripts/runtime_env_probe.py` 即可看环境是否漂。
一句结论：`py312` 跑大多数件，`freecad311`（FreeCAD 自带 3.11）跑 FreeCAD 件，`blender --background --python` 跑 bpy 件，Rhino 件不绑定。
