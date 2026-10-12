# INDEX — 包导航（找得到、读得对、验得了）

> **本文件是导航层，不是规范层。** 规范在 `references/`，唯一实现位于 `scripts/`；`evals/` 和 `tests/` 是评测契约与回归输入，不自行授予整体通过。整体结论必须来自独立验收的实际产物。
> 规则/阈值/工具清单**不在本文件重复**——那会在两处漂移。本文件只回答三件事：
> **包里有什么、某类任务该读哪几篇、怎么证明这个包没坏。**

---

## 1 包结构（四层契约 + 附件）

| 层 | 目录 | 有权限 | 无权限 | 入口 |
|---|---|---|---|---|
| 入口 | `SKILL.md` | 路由、参数表、契约、G0–G7 阶段语义 | 不写细则（细则只在 references） | `SKILL.md` §1 工作流、§5 路由 |
| 规范层 | `references/` | 规范权（"应该怎么做"） | **无执行权**：不能直接改工程 | `references/00`（流程与门禁总纲） |
| 执行层 | `scripts/` | **唯一可执行真值** | 不定义语义（语义在 references） | `SKILL.md` §5.1 工具总表 |
| 案例层 | `cases/` | 快照与检索价值 | **不得当阈值**、不得当门禁依据 | `cases/README.md` |
| 测试层 | `evals/` + `tests/` | 行为评测契约 + 可执行质量检查 + 无答案盲测输入 | 不定义规范；前向评测仍需独立代理执行 | `evals/evals.json`、`tests/run_tests.py`、`tests/forward_eval_protocol.md` |
| 附件 | `assets/` | 机器可读索引与词表 | 不是规范 | `assets/README.md` |
| 模板 | `templates/` | 可直接填的空白表单 | 不是规范、不做门禁 | `templates/semantic_check_sheet.md`（可选层用） |
| 治理 | `VERSION` · `CHANGELOG.md` | **版本唯一权威是 CHANGELOG** | — | `CHANGELOG.md` 顶部 |
| 导航 | `INDEX.md` | 本文件 | — | — |

判读顺序（遇到冲突时谁说话）：**项目规则文件 > 引擎文档 > `references/` > `scripts/` 实现细节 > `cases/` 快照**。

## 2 按任务读（不要全量加载）

| 你的任务 | 最小阅读集 |
|---|---|
| **完全新手，先跑通一遍** | `SKILL.md` 全文 → `references/00` → `references/08` → 本文件 §5 基线 |
| 只做**取数/取证** | `references/09` → `09a` → `11` → `01` → **`19`（入包闸）**；拿到的图纸/BIM/实测怎么解析看 **`23`** |
| 只做**制图/注册** | `references/02` → `19` §2（轴契约）→ `07`；外部数据入图看 `02` §10.5 + `23` |
| 只做**建模** | `references/03` → `08` → `05`（引擎操作） |
| 只做**验收** | `references/04`（四张表 A–D）→ `10`（仪器）→ `12`（通道分歧）；想把“是不是房子/山”变成清单看可选层 `24`，可直接填 `templates/semantic_check_sheet.md` |
| 只做**出图（占用 → 图纸）** | **`references/21`** → `19` §3.1（实测基线）→ `SKILL.md` §5.1 |
| 只做**风格/特征标注** | **`references/22`** → `assets/feature-taxonomy-v1.json`；打分式现场分析看 `22` §8 |
| **接外部开源技能/包** | `references/18`（该不该用）→ `assets/README.md`（有什么）→ `references/20`（怎么跑） |
| 迭代"更像" | `references/06` → `00` §4（轮次协议）→ `16`（光照归因） |
| 换引擎/换对象类型 | `references/14` → `08` → `15` |
| 交付与汇报 | `references/07` → `13`（成本） |
| **交付到 Xdanger S2** | `references/25-xdanger-adaptation.md` → `05` → `07` → `20` |

## 3 `references/` 编号说明

`00`–`16` 是**主干**（流程、证据、制图、建模、验收、引擎、迭代、交付、类型、取数、仪器、取证、通道、成本、跨引擎、原生能力、光照）；
`18`–`25` 是**外部、输出、可选语义扩展与下游适配**：

| 编号 | 主题 |
|---|---|
| `18` | 外部开源技能的采纳等级与许可证边界 |
| `19` | 参考图入包闸（H1–H6：角色 / 可量测性 / 部件数 / 正交基底 / **参考同一性** / **对象在场性**）+ §3.1 边缘一致度实测 + §9.1 负样本回归 |
| `20` | 运行环境与依赖（解释器绑定、引擎侧操作陷阱） |
| `21` | 从占用数据出图（出图三体检、并集轮廓、与渲染对账、**逐体素 vs 体积盒**） |
| `22` | 视觉特征词表（六轴 28 条，冻结 v1）+ §8 打分式现场特征提取 + §9 艺术指导合同 |
| `23` | 参考数据解析与产出契约（矢量/位图判定、各形态可取字段、哈希与版本四件套） |
| `24` | **（可选）**语义保真增强：必含项 / 关系检查 / 负样本；**不属 A–D、未启用无影响** |
| `25` | **Xdanger S2 下游适配**：固定模板世界、快照 `scenes[]/parts[]/edges[]`、三类组件路径、交接 manifest 与原生运行边界 |

**关于缺号 `17`**：`17-editor-shortcuts-and-alignment-pitfalls.md` 已于并行会话中**合并进 `references/05-urhox-operations.md`**，
编号不再占位。看到缺号不要以为是文件丢失——`scripts/skill_structure_check.py` 会把"允许的缺号"作为显式白名单校验。

`09a` 是 `09` 的姊妹篇（站点实测目录）；`90` 是案例附录（蒙德城），历史编号保留。

## 4 工具与路由

- **工具总表（唯一出处，含一句话作用与退出码）**：`SKILL.md` §5.1
- **任务路由（唯一出处）**：`SKILL.md` §5
- 本文件**不复制**这两张表。§4.1 只列**文件名**供检索——名字不改就不漂。

### 4.1 脚本清单（仅名字；语义与退出码见 `SKILL.md` §5.1）

`urhox_capability_probe.py` · `reference_intake_gate.py` · `check_crossrefs.py` ·
`skill_structure_check.py` · `audit_phantom_check.py` · `compare_masks.py` ·
`build_evidence_manifest.py` · `case_index.py` · `runtime_env_probe.py` ·
`external_asset_index.py` · `external_skill_map_check.py` · `external_tool_fetch.py` ·
`voxel_occupancy_dump.py` · `voxel_silhouette_drawing.py` · `voxel_orthographic_drawing.py` ·
`projection_to_mask.py` · `object_mask_from_render.py` · `reference_subject_mask.py` ·
`reference_prompt_diagnostics.py` · `reference_mask_stability.py` · `outline_vs_render.py` ·
`make_edge_report.py` · `make_drawing_report.py` ·
`cad_volume_crosscheck.py` · `feature_taxonomy_check.py` ·
`ref_identity_gate.py` · `registration_crosscheck.py` · `heightfield_form_check.py` · `form_shape_check.py` ·
`design_gate.py`（设计驱动模式门禁 G0–G8：无参考图场景用）

> 清单漏写或写错名字会被 `scripts/skill_structure_check.py` 拦住（它比对 `scripts/` 实际文件名）。

## 5 当前实测基线（新接手者从这里知道"起点在哪"）

> 这些是**已实测**的数，不是目标值。全部带出处文件，复算命令见对应章节。

| 项 | 值 | 出处 |
|---|---|---|
| **轮廓 vs 渲染 边缘一致度**（天守阁 r4，分析宽 768） | top：mean 0.46 / p50 0 / p90 **1** / ≤2px **98.0%**；side：mean 4.42 / p90 13；front：p90 16 | `references/19` §3.1 |
| **真三视图 vs 体量关系图** | 体积盒并集 vs 审计实心：**5.07×**（天守阁 24 盒 21,189 m³ vs 4,181 m³）；且**圆盘类对象外形会被画成方块** | `references/21` §4–§6 |
| **逐体素导出可行性** | 已跑通（走日志通道；产物仅 20 KB 量级）：实测量例 283,560 格 · 212×60×384 格 · vs 0.125 m · 真实体积 553.83 m³ · 18 个体积 | `references/21` §4.3 |
| front 竖直偏移（摄像机中心 Y 扫描） | 均值最优在 **Y=17.25**（≈ +0.25 m，对象高的 0.7%）；p90 在 Y=18.0 更低（8）但 p50 从 2 涨到 5 → **优化分位会牺牲另一个**，不值得单开一轮 | 同上（§3.1 附注） |
| **体积交叉校验**（FreeCAD 第二实现 vs 引擎审计） | 审计 4,181.30 m³ · FreeCAD 24 盒并集 **21,189.44 m³** → **5.07×**（上界校验：X/Z 是节点盒） | `references/21` §4 |
| **参考图入包闸**（5 个现有参考包） | 全部 **FAIL**；`mondstadt` H1 已清零（规则声明）、H4 只缺 `MD-02_南北剖面` 的**等级**；`Tenshukaku` 有 15 件原件未登记 | `references/19` §9 |
| **参考同一性 / 在场性（H5–H6）** | 2026-09-29 负样本回归：错区图 **FAIL**（落陆率 62.9% vs 对照 84.2%、越框 129/1214）、自造图 **FAIL**（`generator=self`）、车内帧当比例锚 **FAIL**；含本体的外部帧 **PASS** | `references/19` §9.1 + `10` I-11 |
| **形制 / 形态读数（I-12）** | 台地实测：`band_share` **0.305** · `flat_share_1m` **0.208** · 无实测支撑 **0.420** ⇒ `TERRACE-UNPROVEN`（形态未经独立校验；不是“台地错”）；真地形对照（Rushmore DEM）0.106 / 0.018 不命中；城市屋顶场 0.271 / 0.113 ⇒ 必须按 `field_kind` 排除 | `references/10` I-12 |
| **外部资产** | 84 条：P1 **12** · P2 15 · P3 39 · P4 18；`curated` **50** / `stock` **34** / `provisional` **0** | `assets/external-skills-index.json` |
| **P1 可跑数** | 系统 Python **8/12**；加专用解释器（FreeCAD 3.11 / Blender）**11/12**；仅 Rhino 类不可用 | `references/20` §6 |
| **视觉特征词表** | v1 冻结：**6 轴 28 条**，两处同源 | `assets/feature-taxonomy-v1.json` |
| **主干路线状态** | WitchHut / SausageUFO / Tenshukaku 已收口（tag `r2r6` 等）；Mondstadt 与 TravelFrog 为测试语料 | `cases/` |

## 6 门禁：怎么证明这个包没坏

**统一质量门禁，改完包必须全跑**（命令从包根目录执行）：

```bash
PYTHONUTF8=1 python tests/run_tests.py --json --project-root $URHOX_REPLICATION_ROOT
```

工作区交付还必须通过 `skill-creator` 的 `quick_validate.py`，输出 **Skill is valid!**；只做跨机器包体检查时可加 `--skip-environment`，参考归档未挂载时可加 `--skip-external`，但报告必须标注对应门禁未执行。发布时再加 `--require-complete`。

**这些门禁不是"文档检查"**：它们分别挡住五类真实事故——
（1）改了文件忘了登记 → 工具/参考成了孤儿；
（2）改了一处引用了另一处 → 悬空指针；
（3）词表两处漂移 → 跨轮标签不可比；
（4）环境变了没说 → "某件可跑"结论失效；
（5）参考目录缺失或清单不可信 → 工具静默报绿、外部件失去来源。

## 7 状态与未决项（新接手者先看这里）

| 项 | 状态 |
|---|---|
| 四类发布门禁 A–D | 已定义（`references/04`）；阈值中标注 `[外/文档]` 者**尚未取得本工程负样本**，不得当门禁 |
| 边缘一致度阈值 | **已实测但与门禁无关**：缺"人为做坏"的负样本对照 → 下一步 |
| 逐体素占用 | **已跑通**（`voxel_occupancy_dump.py`，走日志通道）：真三视图与精确体积可用；工具层已完结，待接进各工程的出图链 |
| 控制帧差分 | **已证伪**（移走主体会改全局光照）；需要"主体参与光照但相机不可见"的能力，当前引擎 API 不提供 |
| 外部资产 `provisional` | **已清零**（84 条全部为 `curated` 50 / `stock` 34）；后续新引入外部件按 18/20/assets 三份文档走 |
| 参考图同一性 / 在场性（H5–H6） | **已落地并有负样本回归**（2026-09-29，三条路线）；未决：各工程补齐 `identity_declarations.json` 与签核人 |
| 高度来源 provenance | **已定义字段**（`04` §3.1）；未决：各工程把现有高度列逐条登记（`palette_inverse` 一律标 `declared`） |
| 配准防伪四条（`02` §4.6） | **已定义并有最小算例**；未决：把留出法写进各工程的注册冻结流程 |
| FreeCAD 后端 | 已跑通（`freecad311` + `cad_volume_crosscheck.py`）；`skill-freecad` / `cadstack` 的完整链路尚未逐件验 |
| Rhino 类 | 需商业授权，**显式不绑定**，只读算法 |
| Xdanger S2 适配 | 已形成静态下游契约章节；当前参考工程快照未提供可复用 Git HEAD，目标工程仍需自行做注册、保存/重载和原生运行验证 |
