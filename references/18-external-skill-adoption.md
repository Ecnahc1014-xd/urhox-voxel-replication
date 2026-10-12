# 外部 Agent Skill 采纳地图（图像驱动体素重建 · 两阶段目标）

本文件回答：**参考区里那 80+ 个外部技能，哪些能直接接、哪些只能借流程、哪些根本不能碰**，以及接进来以后落在 G0–G7 的哪一步。

与其它文件的分工（不重复正文）：

- `09` / `09a` / `11`：**去哪抓、怎么抓、抓不到怎么留痕**（通道与取证）。
- `14`：跨引擎**方法论**与对照分析刻度（哪些是方法、哪些是引擎特性）。
- `15`：**引擎原生能力**的语义、默认值与配套门禁。
- **本文件：外部技能包作为「可复用资产」的选型、接法与许可证边界。** 它不新增门禁，也不替 `01` 判定证据等级。

## 0. 使用边界（四条，违反任何一条结论作废）

1. **外部技能默认是未在本工程实测的外部产物**。任何一条只有读了 `SKILL.md` / 脚本 docstring 之后的**候选**身份，不能当判据。要变成判据，必须走 §6 的采纳流程并在本工程留下至少一次实测记录。
2. **图像生成类技能不得进几何证据链**。dark-fantasy / cyberpunk / neon / 水墨 / fantasy-map 这类只能产出**风格参考**，等级等同 `01` 的 C/D。把它们产出的图当量测口径是明确禁止的（`01` §2 已列同类事故）。
3. **许可证先于技术**。标「未声明许可证」的条目只允许**读方法、重写实现**，禁止搬代码、禁止随交付物分发。清单见 §7。
4. **技能包不是依赖**。不得让交付链路在运行时 import 参考区里的代码；允许的做法是**抄接口、重写实现**或**复制到隔离目录**（§6 第 2 步）。

## 1. 本地参考区（唯一索引）

| 包 | 路径 | 条目 | 离线校验 |
|---|---|---|---|
| 建筑/空间规划 | `docs/refs-staging/design-planning-skills/` | GitHub 15 + ClawHub 23 | `python _provenance/verify.py --check`（718 条） |
| 奇幻/科幻/自然风景 | `docs/refs-staging/genre-art-scene-skills/` | GitHub 8 + ClawHub 16 | 同上（3025 条） |
| 3D 资产 ↔ 设计图 | `docs/refs-staging/model-to-drawing-skills/` | GitHub 1 + ClawHub 20 | 同上（231 条） |

路径均相对 `D:/项目/体素建模测试回`。逐条来源（commit / zip sha256 / 许可证 / 拉取日期）在各包的 `MANIFEST.json`。
机器校验：`scripts/external_skill_map_check.py`（本文件表格 ↔ 现场文件 + MANIFEST + CHECKSUMS 三方对账）。

## 2. 采纳等级定义

| 等级 | 含义 | 允许的动作 |
|---|---|---|
| **P1 直接接** | 有可执行脚本或明确算法实现，接口可读，许可证允许 | 复制到隔离目录 → 改接口 → 进链路，登记改动与校验值 |
| **P2 借流程** | 无代码或代码不可直接用，但工作流/产物结构可抄 | 按其步骤序列**重写**本工程实现，产物文件名与字段可沿用 |
| **P3 借词表 / 口径** | 知识表、特征维度、评审清单、量化标准 | 抽成标签体系或参数表进了 `08` / 参数表，注明出处 |
| **P4 只作参照 / 反例** | 面向其它目的、许可证不明、或明确不能当证据 | 只读；不得进交付物，不得进几何证据链 |

## 3. 阶段 Ⅰ：规模化信息采集与视觉特征提取

按「对本阶段的杠杆」从高到低排。**★ = 首选**。

| # | 包内 ID | 等级 | 拿它的什么 | 接到哪一步 | 代价 / 风险 |
|---|---|---|---|---|---|
| Ⅰ-1 ★ | `genre-art-scene-skills/github/RobLe3__cc-blender-skill` → `plugin/skills/reference-analysis-validator` | **P1** | 把"看起来接近"变成**硬门禁**：`reference_manifest.json`（视图分类 + **期望部件数** + 阈值）、`source_analysis/*.json`（mask / 连通域 / 标志点）、`validation/front_mask_validation.json`（IoU / SSIM / bbox / centroid），并**在门禁不过时拒绝导出** | G1（参考包结构与视图角色矩阵）、G5（投影验收） | 依赖 Blender MCP 渲染侧；本工程要用引擎内投影替换渲染侧 |
| Ⅰ-2 ★ | 同上 → `multiview-constraint-solver` | **P1** | **多视图矛盾先裁决再动手**：把 front/side/top/back 归一化到统一轴契约（front=宽X高Z、side=深Y高Z、top=宽X深Y），比共享轴比例，超差则出冲突报告并选 canonical 策略 | G1→G2 之间（`01` 冲突表的上游自动化） | 它假设"刚性模型 + 无可辩解数"；风格化对象要先声明"忠实于哪一版设定稿" |
| Ⅰ-3 ★ | 同上 → `source-part-segmentation` / `contour-to-mesh` / `orthographic-registration` / `landmark-fit-repair` / `multiview-fit-loop` / `quality-refinement-autoloop` | **P1/P2** | **部件切分 → 轮廓 → 正交注册 → 标志点拟合 → 迭代修复**的完整序列；`quality-refinement-autoloop` 是"自动迭代直到过闸"的闭环写法 | G1（切部件）→ G2（注册）→ G5（拟合残差） | 面向单体/道具/吉祥物尺度；城市尺度要按 `08` 裁剪 |
| Ⅰ-4 ★ | `genre-art-scene-skills/github/viettranx__3dviz-pro-max` → `scripts/capture_view_quality.py` + `capture.py` | **P1** | **第二套独立的帧可用性判据**：near-black / 被近平面墙填满 / 无对比度 三类拒收，`--expect-usable`（帧不可用即非零退出）、`--expect-motion`（两帧相同即失败），每帧无论是否检查都写 `view_quality` 数字进 `capture-log.json` | 阶段Ⅰ采集侧：**"这批帧到底能不能用"的自动闸**；与 `10` 的 `frame_qc.py` 互为跨实现对照 | 跑在浏览器/Playwright 侧，阈值是按它的 eval 帧调的（**不是本工程阈值**）；抄判据不抄阈值 |
| Ⅰ-5 | 同上 → `scripts/manifest_contract.py` + `references/catalog-index.md`、`catalog-knowledge/` | **P2/P3** | 检索清单的**契约式校验**（kind 白名单：`style-profile` / `lighting-profile` / `composition-profile` / `geometry-profile` / `material-profile` / `validation-profile` …），以及按 kind 组织的**视觉特征词表** | 阶段Ⅰ特征库的 schema；`08` 的类型划分可与之对齐 | 词表面向通用 3D 可视化，不是游戏场景；直接照抄会引入无关维度 |
| Ⅰ-6 ★ | `design-planning-skills/github/Maximilianogc32__floorplan-vectorizer` | **P1** | 位图 → **可测量、可交互 SVG** 的最小可用范式（`scripts/vectorize.py` / `floorplan.py`） | 阶段Ⅰ：把参考图批量转成**可计算的轮廓**，替代人工在图上量像素 | 面向户型图；透视/非正交图不适用，需要先有正视投影约束 |
| Ⅰ-7 ★ | `model-to-drawing-skills/clawhub/ssq`、`drawing-insight-pro`、`eplan-drawing-parser` | **P1** | 图纸 → 结构化数据：`ssq`（文字 / 段落 / 材料表 / 尺寸标注）、`drawing-insight-pro`（PDF/DWG 批量 + OCR 预处理 + 跨图纸索引 + 中文注释分类 + **版本差异**）、`eplan-drawing-parser`（元件表 + 线/引脚拓扑） | 阶段Ⅰ**规模化的主体**：把成批参考图纸变成机器可读表，再进 `01` 的来源表 | 依赖 ezdxf / pdfplumber / fitz 等；版本差异需人工确认阈值 |
| Ⅰ-8 | `model-to-drawing-skills/clawhub/cad-to-data`、`batch-cad-converter` | **P1** | Revit / IFC / DWG / DGN → 结构化数据；批量转换带进度跟踪与错误处理 | 阶段Ⅰ批量入口 | 依赖 DDC 转换器链；工具链较重 |
| Ⅰ-9 | `design-planning-skills/github/Abhinavbwj__Urban-Design-Skills-Claude` | **P3** | 量化标准表与 7 个 Python 计算器（`far-calculator` / `density-metrics` / `walkability` / `green_space` / `parking` / `block_optimizer` / `cost_estimator`） | 把"看起来多大"换成**每公顷口径**，供 G3 体量分配与 G5 统计 | 欧美规范语境；中国项目要换成本地标准 |
| Ⅰ-10 | `genre-art-scene-skills/clawhub/mapbox-cartography` | **P3** | 分幅、图幅、比例与表达规范（采集组织方式） | 阶段Ⅰ采集计划的**分幅表** | 面向现代地图；风格化场景仅借"分幅"这一层 |
| Ⅰ-11 | `genre-art-scene-skills/clawhub/{dark-fantasy-art-generator, cyberpunk-image-generator, neon-art-generator, steampunk-art-generator, chinese-ink-painting-generator, gothic-portrait-generator, surreal-art-generator}` | **P3（仅词表）** | 风格**特征维度**：配色、材质、光比、气氛、构图 | 给参考图打**特征标签**，做"同风格不改几何"的数据增广 | **P4 红线**：其产出图不得当几何证据；不得用于尺寸推断 |
| Ⅰ-12 | **未镜像发现记录**：fantasy-map-generator / terrain-route-video | **P4** | 奇幻总图 / 地形动画的**版式**参考 | 只作构图灵感 | 当前未进入本地参考归档；生成内容与目标几何无关，**禁止进证据链**；如需启用必须先补 MANIFEST、校验和与许可证登记 |

## 4. 阶段 Ⅱ：资源高效的自动化流程

| # | 包内 ID | 等级 | 拿它的什么 | 接到哪一步 | 代价 / 风险 |
|---|---|---|---|---|---|
| Ⅱ-1 ★ | `model-to-drawing-skills/clawhub/cadstack` → `lib/drawing.py` | **P1** | `ViewType`（TOP/FRONT/RIGHT/LEFT/BACK/BOTTOM/**ISOMETRIC**/**SECTION**）+ `DimensionType` + `DrawingSheet.standard_size()` + 标题栏 + `layout_views()` + `_project_view()`：**3D → 正交/等轴测/剖面 → 标注 → DXF/SVG/PDF** | G6/G7：把"多机位截图"升级为**矢量图纸产出**（可 diff、可进版本控制） | 后端绑 CAD 内核；投影算法可单独抽出（纯数学，易重写） |
| Ⅱ-2 ★ | `model-to-drawing-skills/clawhub/skill-drawing-diff-analyzer` → `scripts/parse_2d.py` / `parse_3d.py` / `compare.py` | **P1** | **2D 图纸 ↔ 3D 模型自动比对**：默认**正交投影**、按特征比对、识别 Ø/R/角度/带公差尺寸，输出 `diff_report.json` + `diff_report.md` | G6：作为**第四条独立验收通道**（现有：体积清单 / 占用对账 / 帧内容门禁） | 几何公差需人工复核（它自己声明了这一点）；依赖 ezdxf / trimesh / cadquery |
| Ⅱ-3 ★ | `model-to-drawing-skills/github/github__awesome-copilot/freecad-scripts` + `model-to-drawing-skills/clawhub/{skill-freecad, openclaw-freecad-mcp, openscad-automation}` | **P1/P2** | 参数化 CAD 自动化：FreeCAD（Draft + **TechDraw**）、OpenSCAD（纯文本建模 + CLI 渲染导出）、MCP 直控 | **第二条独立抽取路径**：把体素占用/包络写成脚本重新算一遍体积与投影，与引擎内结果对账（同 `10` 的"不同路线用不同第二实现"） | 需本机装对应 CAD；OpenSCAD 无引擎内材质概念，只适合几何对账 |
| Ⅱ-4 | `model-to-drawing-skills/clawhub/gb-cad-figure` | **P2** | 国标图纸模板层：A3 图框、标题栏、线型、尺寸标注、字体、比例、等轴测 + 引线标注、**PDF + DXF 三格式交付** | G7 图纸产出模板 | 面向机械/回转体；建筑/场景要换图框与线型约定 |
| Ⅱ-5 | `model-to-drawing-skills/clawhub/gcadclaw` | **P2** | **"生成 → 截图反馈 → 实体验证 → 修复"** 闭环（`scripts/capture_feedback.py`、`validate_env.py`），以及"默认输出顶/前/右三视图"的约定 | G6 反馈式修复循环；默认视图约定可直接进机位清单 | Windows + pygcadwin；只作范式更省事 |
| Ⅱ-6 | `genre-art-scene-skills/clawhub/goldenseed` | **P2** | 确定性熵流：同种子 → 同输出 + hash 校验 | 生成器契约（对应 `00` 对"种子可复现 + 输出 hash"的要求） | **GPL-3.0+**：copyleft，集成进交付物前必须评估 |
| Ⅱ-7 | `genre-art-scene-skills/github/ismael-joffroy-chandoutis__claude-skills-public` → `procedural-generation`、`prompt-to-game`、`art-consistency` | **P2** | 程序化生成的**种子/约束/验证闸**三件套；一致性检查 | G4 生成器契约；G5 一致性 | 单体技能、文档为主；需重写实现 |
| Ⅱ-8 | `genre-art-scene-skills/github/adryanmoldokkr32-pixel__threejs-skill-package` | **P2** | 24 个"**确定性**"技能的分层（core / errors / impl / syntax）与 `DECISIONS.md` / `LESSONS.md` / `WHY` 式的决策留痕 | 本 Skill 自身的组织参照；技能分层法 | 面向 Three.js，不提供几何算法 |
| Ⅱ-9 | `genre-art-scene-skills/github/Xander-Rudolph__game-asset-engine` | **P2** | 容器化流水线（ComfyUI in Docker）+ `prompts/{buildings,characters,creatures,...}` **提示词模板库** + `AUDIT.md` | 批量资产生成侧；提示词模板可借用作场景描述规范 | 面向角色/单体资产；几何不精确 |
| Ⅱ-10 | `model-to-drawing-skills/clawhub/pindou-pattern` | **P2** | **"一份数据两种产出"**：SVG 图纸（色号/坐标/加重线）+ HTML 预览 + **CSV 物料清单** | G7 证据包形态：图给人看、表给机器读 | 领域无关（拼豆），只借结构 |
| Ⅱ-11 | `model-to-drawing-skills/clawhub/batch-cad-converter` + **未镜像发现记录**：批处理工程化通配候选 | **P2** | 批量任务的工程化：进度跟踪、错误处理、汇总报告 | 阶段Ⅱ 批处理骨架 | 只记录发现结论，不代表现场已有其它通配路径；启用前必须先镜像并补 provenance |
| Ⅱ-12 | `model-to-drawing-skills/clawhub/{character-design-sheet, ip-character-consistency-studio}` | **P3** | 资产**设定表**结构（turnaround 视图 + 变体 + 约束） | 若复刻对象含角色/道具，其设定表可对齐 `01` 的视图角色矩阵 | 图像侧，不产出几何 |
| Ⅱ-13 | `genre-art-scene-skills/clawhub/level-design-checklist-skill` + **未镜像发现记录**：game-designer-toolkit | **P3** | 关卡评审清单与 GDD 结构 | `04` 表 D（玩法/物理）的清单来源 | 设计评审 ≠ 几何验收，不得混入 A/B 表；未镜像记录不得直接采纳 |
| Ⅱ-14 | `model-to-drawing-skills/clawhub/copilot-for-revit`、`model-to-drawing-skills/clawhub/solidworks-modeling`、`model-to-drawing-skills/clawhub/sketchup-ppt-generator` + **未镜像发现记录**：OSM 场地底图抓取 | **P3/P4** | Revit 图纸/标注/视图操作；SolidWorks 工程图；SketchUp → 汇报 PPT；OSM → SVG/DXF 场地底图 | 仅在目标管线确实用这些工具时启用 | 各需本机装重软件；未镜像发现记录不进入现场资产清单，底图等级按 `09` 判（B/C） |

## 5. 其余 60+ 个条目怎么用（四种用法）

| 用法 | 适用对象 | 具体动作 |
|---|---|---|
| **借词表** | 全部美术风格生成器（P3 组） | 抽出配色 / 材质 / 光比 / 气氛四类标签，进参考图的特征标注体系 |
| **当第二实现或交叉校验** | `cadstack` 投影、OpenSCAD/FreeCAD 脚本、`skill-drawing-diff-analyzer`、`3dviz-pro-max` 的帧判据 | 用**不同实现**重算同一量（体积、包络、投影 IoU、帧可用性），结果不一致即开调查，不许二选一 |
| **当反例 / 警示** | 图像生成类、`fantasy-map-generator`、AI 生成素材站 | 写进 `01` 的来源分级示例：哪些图**永远不能**当量测口径 |
| **当库存** | `design-planning-skills` 的建筑 / 室内 / 结构 / BIM 造价那一批 | 当前两阶段用不上；若复刻对象扩展到室内空间或需要造价口径时再启用，激活前重走 §6 |

## 6. 采纳流程（五步，缺一步不算采纳）

1. **读**：只读 `SKILL.md` 与脚本头部 docstring，判断是否真有可执行逻辑（很多技能是纯提示词，别当库用）。
2. **隔离**：复制到工作区内的 `tools/external/<id>/`，**不改参考区原包**；登记来源 URL + commit/zip sha256 + 许可证。
3. **试跑**：dry-run 一次，记录输入 / 输出 / 耗时 / 依赖缺失情况；失败也要留记录（同 `11` 的零结果登记）。
4. **接线**：只有通过本工程对应门禁的部分才允许进交付链路；产物必须落在证据包里并自带校验值。
5. **登记**：在参数表的"本轮开启的引擎原生能力"相邻位置登记外部采纳项（id、等级、改动摘要、回滚命令）。

## 7. 许可证边界（截至 2026-09-23）

| 类别 | 条目 | 允许 |
|---|---|---|
| **MIT / Apache-2.0 / CC** | 三个包内大多数 GitHub 仓库（`cc-blender-skill`、`3dviz-pro-max`、`threejs-skill-package`、`Urban-Design-Skills-Claude`、`floorplan-vectorizer`、`game-asset-engine`(Apache) 等） | 复制代码、改接口、随交付物分发（保留版权声明） |
| **GPL-3.0+** | `goldenseed` | **copyleft**：集成进交付物前评估传染性；可只借方法重写 |
| **未声明（⚠）** | **ClawHub 全部 39 个** + 4 个 GitHub 仓库（`chacha71/urban-rural-planning`、`zhuzhaoyun/ZZY-SKILLS`、`nicoguyon/3dplan`、`artavision360/Lebanese-Building-Law`、`op7418/guizang-yingzao-skill`） | 只读方法、**重写实现**；禁止搬代码、禁止随交付分发 |

> 本表的许可证判定来自各包 `MANIFEST.json` 的 `license` 字段（GitHub 取仓库 LICENSE 文件关键词匹配，ClawHub 无字段即判未声明）。**判定不是法律意见**，对外交付前逐条复核原始文件。

## 8. 维护

- 本文件的表格是**数据**：`scripts/external_skill_map_check.py` 会拿它跟现场文件、`MANIFEST.json`、`CHECKSUMS.sha256` 三方对账。新增条目必须同时可被脚本解析（包内 ID 形如 `<包名>/<相对路径>`）。
- 采纳等级变化（P4 → P3 → P1）必须在「代价 / 风险」列留下依据，不允许静默升级。
- 参考区条目数变化时先跑三个包的 `_provenance/verify.py --check`，再更新 §1 的计数。
