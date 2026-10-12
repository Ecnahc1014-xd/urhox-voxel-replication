---
name: urhox-voxel-replication
description: "把真实或设定对象复刻为 UrhoX/TapTap Maker 体素场景，或审计这类场景的参考证据、坐标注册、占用/投影/运行时验收时使用；也用于 Xdanger S2 固定模板地图、世界快照和可复用组件的下游适配。适用于城市、建筑、室内、景观和道具。不要用于普通 3D/美术资产、纯动画或与场景几何无关的玩法开发。"
metadata:
  version: "3.50"
---

# 体素复刻（通用）

与复刻对象无关的生产方法：正式的“把某个东西在引擎里复刻成体素场景”任务——城市、街区、单体建筑、室内、地形海岸、山体、道具载具，或它们的混合——按需要启用 G0–G7；不要把审计、出图、局部迭代或纯咨询强行跑成全流程。

核心问题只有一个：**让“像不像”从主观感觉变成可复现、可审计、可回滚的工程结论；门禁只约束声明，不得替代保真推进。**

## 0.1 先分流，再决定要读哪些规则

每次响应先做两件事：判定任务模式，并给出当前状态。不要因为 Skill 被召回就默认启动 G0–G7 全套流程。

首轮输出只保留四项：**模式、状态、现在就能做的第一步/产物、若阻断则所缺的最小输入**。先给动作再给规则指针；不要把整包门禁、案例和报告模板倾倒给用户。

| 任务模式 | 典型请求 | 首个动作 | 不得做的事 |
|---|---|---|---|
| **正式复刻** | 从参考资料生成可验收的 UrhoX 体素场景 | 建立最小参数表与证据缺口，按对象类型启用必要阶段 | 缺关键尺度/注册依据时把猜测写成正式几何 |
| **保真迭代** | “看起来不像了”“把某处做得更像” | 先锁定可复现机位与一个最大视觉缺陷，马上提出能移动几何/材质指纹的最小改动 | 用报告、清单或门禁收口冒充视觉改善 |
| **审计/验收** | 查占用、投影、碰撞、证据包是否可信 | 只加载对应仪器与检查表，区分静态推断、运行时证据和未知项 | 把局部仪器 PASS 说成整体复刻通过 |
| **出图/测绘** | 三视图、投影、轮廓、占用反向出图 | 先做出图三体检，再选择盒版或逐体素版 | 用图纸容器字节或节点盒高冒充几何真值 |
| **注册/尺度变更** | “整体按 1.1 倍”“换原点/北向/坐标注册” | 只改唯一注册变换，生成新版本，重做配准与固定机位回归 | 只改节点局部 scale，或沿用旧 transform_id 冒充已验证 |
| **运行时修复** | “PIE 里看不见/碰撞不生效/烘焙后失效” | 用带 subject 标签的 PIE 复现，区分可见性/碰撞/动态体/烘焙来源，再修主数据并重测 | 用静态脚本、离线截图或编辑器树代替运行时复现 |
| **设计驱动制造**（无参考图） | “给个 brief/设定稿，造一个街区/内厅” | 先写 `DESIGN_CANON`（唯一权威）+ 设计声明，再跑 `scripts/design_gate.py` 的 G0–G8 | 把“门禁全过”说成好看/好玩/有新意；把设计值写成不在体素网格上的数 |
| **参考取证/采集** | “找参考、补官方数据、查别人做过没有” | 先做 prior-art 与结构化来源两线检索，落最小采集包和零结果登记，再过 H1–H6 | 用自造图、无本体图或未经登记的转载裁切作尺寸锚 |
| **视觉特征标注** | “标屋顶、色带、层次、风格特征” | 按词表版本输出视图局部标签、证据裁剪、置信度和排除项 | 把标签词直接当几何尺寸或验收结论 |
| **外部工具接入** | “这个包能不能用/装好了能不能跑” | 先判采纳等级、许可证、绑定解释器和环境漂移 | 只凭静态 import 或“本机能跑”放行 |
| **不适用请求** | 纯动画、普通 3D 资产、无场景几何的玩法 | 明确不适用，并转给合适的工作流 | 硬套 G0–G7 |

### 当前状态与下一步的最小契约

- `EXPLORATORY`：输入或口径不足，允许做**可逆、明确标未知的探索草模/假设**；不得写入正式基线或几何证据链。
- `PASS-WATCH`：当前检查项暂时达标，但证据、运行通道或风险尚未闭环；可以继续推进保真，不等于完成。
- `PASS`：只表示**指定检查项和指定版本**可复现地通过；不等于模型、材质或通道永久不再改。
- `BLOCKED`：当前主线被硬缺口阻断；先说明最小解阻动作。若仍能做不影响正式结论的探索，可另开 `EXPLORATORY`，不要把阻断项静默绕过。

缺参数时先问最小必要问题；若用户明确要看形态草模，可以在 `EXPLORATORY` 下继续，所有未知量写成假设并标出会影响哪些结论。**“不能宣称正式通过”不等于“不能继续让模型更像”。**

### 0.1a 各模式的最小执行回路

下列包内命令以 Skill 包根目录为工作目录，并绑定已确认的 Python 解释器；工程路径是显式输入。若在工程根执行，请用已定位的 Skill 绝对路径，不要把包内 scripts 与工程的 scripts/tools 混用。

- **注册/尺度变更**：记录 old_transform_id、new_transform_id、绝对尺度表达、受影响锚点和机位；只在注册源改一次，实际执行 python scripts/registration_crosscheck.py --spec <registration_spec.json> --out <registration_report.json> --json-only，至少重渲染一个全局机位和一个结构机位，并报告变更前后轮廓/掩膜读数。没有同源参考掩膜时只能写 UNVERIFIED。
- **运行时修复**：在 PIE 用同一场景、机位、动作和 subject 标签复现，最小记录为 scene、camera、action、expected、observed、log_path、frame_path；先分类为可见性、碰撞体、动态体或烘焙来源，再改主数据，重烘焙/重启，重复同一动作复测。shots.py、frame_qc.py 和 fidelity_gate.py 不是本包脚本；若项目有它们，只能从该工程 tools 目录解析真实路径，找不到就明确缺失。进不了 PIE 时只能标 BLOCKED，不能写“已修复”。
- **参考取证/采集**：最小包必须含查询词与端点、原件 URL/ID、原件哈希、对象×区域×版本证据、视图角色与比例锚、裁剪/注册元数据和零结果登记；先实际执行 python scripts/reference_intake_gate.py --refs <refs_dir> --out <gate_dir> --source-table <source_table> --emit-masks 生成入包初稿，再人工补 expected_parts/role，并执行 python scripts/ref_identity_gate.py --declarations <gate_dir>/identity_declarations.json --refs-root <refs_dir> --out <gate_dir>。通过 H1–H6 前，材料只能进候选区，不能进 G2 几何基线；--help 只查接口，不生成产物。
- **投影/IoU 对账**：输入绑定 projection_mask、render_mask、transform_id、view_id、axis、ortho_size、resolution、center 和两侧来源。投影侧执行 `python scripts/projection_to_mask.py --projection <projection.json> --view <front|side|top> --ortho-size <meters> --res <width>x<height> --center <x,y,z> --out <projection_mask.png>`；对明确为 0/255 的二值掩膜执行 `python scripts/compare_masks.py --ref <projection_mask.png> --render <render_mask.png> --mode luma-fixed --view <front|side|top> --res <analysis_resolution> --out-json <iou_report.json> --out-overlay <overlay.png>`。不要对全不透明 PNG 默认取 alpha，否则前景会退化成整幅图。交并集与 IoU 来自 compare_masks；边界距离另用 outline_vs_render，不能冒充 IoU。unaligned 为 null 表示没有相机配准签核，非‘已对齐’。**同一模型的投影↔渲染只检查通道一致性；判断忠于原对象还必须有独立参考。**
- **视觉特征标注**：按 references/22 的 schema 写旁路 feature_tags.json，保留 taxonomyVersion、images[].file、axes 六轴、provenance 和 note；用 `python scripts/feature_taxonomy_check.py --tags <feature_tags.json> --json` 检查实际文件。无 --tags 时只查包内词表一致性，不查本批标注。检查通过仍不证明标签视觉语义正确；标签只用于诊断与检索，不进入几何证据链。
- **外部工具接入**：拿到工作区和条目 ID 后先执行 python scripts/external_tool_fetch.py --refs-root <workspace> --list，再用 --id <id> --dest <dest> --probe 做只读探测；许可证、解释器和接口边界登记完成前不得加 --apply，也不得把 --help 或静态 import 当成可跑证据。

包内的 --help 只用于发现接口，不生成证据或交付产物；命令必须在输入路径、解释器和输出目录都明确后实际运行。任何未在包内找到的脚本都必须先定位到工程侧真实路径，不能凭名称补造。

复杂参考的主体掩膜另读 `references/19` §5.1：明确目标范围及前／背景笔划，用 `scripts/reference_subject_mask.py --image <original> --subject-spec <subject.json> --out <candidate.mask.png>` 实际生成候选并打开叠图；批量入包用 `reference_intake_gate.py --subjects <subject-set.json>`。无透明底也无目标提示时只记录 `NEEDS_SUBJECT`，不再按明暗面积猜主体。局部、遮挡和 UI 必须保留范围／ignore，不能把连通域数或 `CANDIDATE` 当语义验收。

## 0.2 状态语义优先级：参考登记 ≠ 模型冻结

本 Skill 与引用文档中的“冻结/FROZEN”是历史流程词。按以下解释执行：

1. 允许记录用户认可的**参考取值**（注册变换、基准读数、机位参数、目标定义）和可复现的**版本基线**。
2. 版本基线只是可回滚快照，不是对几何、材质、通道或结论的自锁；新证据或更像的改动可以产生新版本并替代它。
3. AI 不得主动写“几何已冻结、通道已验证完、已定案、以后只改文档/工具、复刻完成”等自锁结论。只有用户明确要求停止/交付时，才进入用户指定的收口动作。
4. 若引用文档把 `FROZEN` 映射到 `PASS`，只按“该注册/基线版本的证据状态”理解，不能扩展成整场景完成或不可修改。

## 0. 使用边界与适配

**适配一：引擎（8 项逐项确认，任一项未确认就不要外推 G5–G7 的结论）**

坐标系与手性、单位、场景/预制体格式、脚本语言、体素或网格表示、物理代理模型、离线批处理与截图能力、资源路径约定。

默认按 UrhoX / TapTap Maker（米制、Y-up 左手系、Lua + PIE 烘焙）。先读项目规则文件（`AGENTS.md`、引擎文档、README）；项目规则与引擎文档优先于本 Skill 的经验性建议。

**结构性主张（本链的重点）：生产链不依赖其它引擎或 DCC。** 从主数据（Blueprint / POI / iso-map 存档）到可运行体素场景，全部在目标引擎内完成——不需先开 UE / Unity / Blender / MagicaVoxel，也不需要 AI 3D 服务；几何在整数格上“构造即合法”，不过 mesh→体素的离散化取舍。

**优势三条（对外口径，按此顺序写）**：
1. **不需要外部引擎，Maker 网页端即可使用**：产物是引擎原生件，Web/WASM 目标可直接承载（已有工程在 Web 预览跑过，含 Web 回落策略）。
2. **支持 XDanger（S2 下游适配）**：按 `references/25` 的契约交付（0.1 m 世界与固定模板、6×6 场景块、world_snapshot v3、三条组件路径、G0–G7）；上游只提供**可审计/可转换/可回滚**的地图源与组件源。
3. **先进的验证工程**：H1–H6 入包闸、配准防伪四条、四表 A–D、状态语义、裁剪留痕、失败件保留、反自欺纪律、包自检（含引用存在性检查）。

边界（防误读）：
- 外部工具**只出现在两处**——① 验收侧的**独立第二实现**（FreeCAD 重算体积、OpenCV 掩膜对账等，是纪律要求的交叉验证，不是生产依赖）；② 参考数据解析（DWG/PDF/BIM/影像等）、它们只读，不进生产链。
- 例外范围：角色 / 载具类**精细资产**不在本主张内（历史上用过外部生成与 Blender 往返）。
- 工具链里的 Python 仪器跑在**主机侧**，不在 Maker 沙箱内；它们是工具，不是引擎。

**适配二：对象类型与尺度**

对象必须落到 `references/08-subject-classes-and-scales.md` 的类型与尺度等级上：它决定**哪些阶段必需、哪些门禁裁剪、体素尺寸与细节预算取什么量级**。用错类型会导致整轮工作的证据类型都不对。

其它边界：

- 不把透视截图、美术观感或单次运行成功当作完整验收。
- 主场景、辅助场景、交付范围由用户或项目文档确定，不能由本 Skill 推定。
- 不把“生成了 N 版方案”写成“有 N 套可用几何”：只有生成器显式接受随机种子、输出可追溯 hash 并通过同一套门禁时，才能声明存在多候选。
- 复刻虚构或风格化对象时，“忠实”改为**对指定参考/设定稿的忠实**；来源分级与冲突登记照旧，但不得伪造官方数据。
- **本 Skill 不适用**：非体素化的常规建模/纯美术资产生产、与场景几何无关的玩法系统开发。遇到这类任务不要硬套本流程。

## 1. 工作流（阶段语义的唯一权威）

```text
  G0 任务、对象类型与证据边界登记
G1 参考资料包与来源分级          ← 开工前先查“别人做过没有”（09 §2.5）
                                   ← 入口闸 H1–H6（19）
  G2 制图/测绘与唯一坐标注册基线
G3 基准面/边界/主数据要素灰盒与主体量
G4 构件、组团与场景装配
G5 严格网格、占用、接地与语义审计
G6 独立运行时投影与多机位回归     ← 图纸通道（出图三体检）
G7 玩法/物理烟测、烘焙、证据归档与交接
```

**主线一图（阶段 × 仪器 × 出处）**——每阶段的“能不能开工/能不能收工”各由哪个仪器回答：

```text
G0 ─┬─ 参数表登记（本文件 §2）
    └─ 能力探针      scripts/urhox_capability_probe.py   （15）
G1 ─┬─ 【先】同类复刻 + 结构化素材库检索  09 §2.5（Sketchfab / Commons 分类树）
    ├─ 通道与取证     09 / 09a / 11
    ├─ 来源分级/追溯  01（含 §3.2 能力清单、§6.1 语义去重）
    └─ 入包闸 H1–H6   scripts/reference_intake_gate.py（H1–H4）
                      scripts/ref_identity_gate.py（H5–H6，10 I-11）  （19）
G2 ─── 注册链与往返检查  02（含 §4.6 配准防伪四条：留出法/独立一致性/零残差警示/裁剪完整性）
G3 ─── 体量分配与量化口径  08 + 18 Ⅰ-9（外部量化标准，仅 P3 借用）
G4 ─── 生成器契约（种子 + 输出 hash）  00 / 03
G5 ─┬─ 占用/接地/越界   <目标工程>/tools/audit_phantom_check.py（项目侧，先确认存在；10）
    └─ 四类验收表 A–D  04
G6 ─┬─ 多机位回归 + 帧 QC   <目标工程>/tools/shots.py + frame_qc.py（项目侧，先确认存在；10）
    ├─ 形制/形态检查   scripts/heightfield_form_check.py （10 I-12）
    ├─ 形制/形态复核   scripts/form_shape_check.py （10 I-12 + 04 C2：provenance 分层/剪影/交叉复核）
    └─ 占用出图 + 轮廓   scripts/voxel_silhouette_drawing.py（逐体素）；voxel_orthographic_drawing.py（仅体积盒）
G7 ─┬─ 证据清单   scripts/build_evidence_manifest.py   （07）
    └─ 自包含报告  scripts/make_drawing_report.py
全程 ─┬─ 环境验收     scripts/runtime_env_probe.py      （20）
      └─ 外部件采纳   18 + assets/ + scripts/external_tool_fetch.py
```

主线纪律：**任何阶段的结论必须能指向一个仪器或一张检查表**；指不出来的结论只能写成“观察”，不得进证据包。

### 1.1 G1 的开场动作：先查“别人做过没有”

G1 不是直接从“搜图”开始，而是**先做一次 prior-art 扫描**，再决定主数据形态：

1. **A 线：同类复刻作品**（其他游戏/Mod/体素/同人重建）—— 只能作**对照**，
   **不得当几何/尺寸依据**；产出进“对照”目录，不入证据目录。
2. **B 线：结构化素材库**（专业扫描站、开放图库、官方机构、地图/DEM）—— 可作证据候选，按 `01` 分级。
3. 两线都**必须登记**（含**零结果**）：查了哪些词、扫了哪些站、命中什么、为何不用。

为什么放在 G1 开头：① 别人可能已经把形状问题答过；② 可能发现对象**早已有专业扫描数据**，
省掉一整轮抓图；③ 能找到**别人做错的地方**。端点、分类树技巧与四条纪律见 `references/09` §2.5。

> 对象由多个可独立观察的子对象组成时（群像 / 多塔 / 多舰 / 聚落），**按子对象建目录分别检索**，
> 不做全局平均搜——这是 G3 体量分配的前置条件。

- G0 = 口径、对象类型、尺度、性能目标、参数表登记；G2 = 注册变换版本基线。两者用于追溯与回滚，不是 AI 对几何/材质/通道的主动冻结；需要修改时生成新版本并保留旧快照。
- **一轮一个主问题**；轮次协议、版本基线与升级规则见 `references/00-pipeline-and-gates.md` 第 4 节。
- 每轮交接六问：改了什么、为什么改、证据是什么、指标如何变化、未关闭风险、下一轮做什么。

## 2. 项目参数表（正式复刻首次使用必须先填；其它模式只填该模式最小字段）

正式复刻需要完整参数表；保真迭代、注册/尺度变更、运行时修复、取证、出图和标注不得因为无关字段未填而被全量阻塞。其它模式只补能决定本轮动作与证据边界的字段，例如：变更模式至少要有唯一注册源/受影响机位，运行时修复至少要有场景/动作/复现通道，取证至少要有对象×区域×版本，投影对账至少要有同源掩膜元数据。

```text
项目/对象名：
对象类型（08）:                        尺度等级（08）:
复刻目标：几何/视觉/玩法（排优先级）      预期视角（00 §3 G0 门禁）:
目标平台与目标硬件（00 §6 性能口径）      性能门槛（00 §3 G0 登记 / 00 §6）:
坐标系与手性（02 §4.1）:                引擎默认单位（02 §4.1）:
轴向与北向定义（02 §4.4 第 3 条往返检查）:
原点定义（02 §4.1）:
尺寸容差（02 §4.3 往返残差判定）:
复刻范围与边界（含裁切规则）（00 §3 G3）:
主场景入口（00 §3 G7）:                 辅助场景（00 §3 G7）:
体素单位与基线网格（03 §3）:
细节预算三项上限：总体素数 / 单对象体积数 / 动态体（08 §3）:
最小可辨识构件（08 §3，决定体素尺寸）:
跨尺度拼接声明（08 §3；未声明即按尺度溢出处理）:
最终网格硬约束（原点整数、单位尺度、基底轴对齐）（00 §3 G5）:
硬锚点清单（02 §4.4）:
坐标注册的唯一来源（02 §4.3）:
主数据形态（城市=POI/路网；单体=轮廓与三视图；景观=等高线与水位；室内=房型图；道具=主轴线与尺寸链）（08 §2）:
机位清单专项文件名（04 §6 / 06 §7；每个机位须含位置、朝向、FOV或正交尺寸、分辨率、clipping、时间、灯光组、参考图版本）:
接地率口径（03 §10 / 04 表 B6）：
本轮开启的引擎原生能力与各自配套门禁（15 §4；**未列出的能力视为不开**，开启前用 `scripts/urhox_capability_probe.py` 确认该发行版是否导出、工程是否已引用）：
证据板号前缀（01 §8）:
烘焙/构建入口与幂等要求（00 §3 G7）:
玩法与物理是否在场（可通行/可破坏/可交互/动态体）（04 §9 表 D）:
验收门禁指标与阈值（**必须与 04 §0 登记表符号 1:1，差集为空**）（04 §0）:
语义增强档位（**可选**：L0 未启用 / L1 诊断 / L2 自证；启用则写必含项来源。见 `24`，**不进 A–D、不加严任何门禁**）:
裁剪登记（四段式，见第 3 节）:
参考登记人与登记时间（00 §3 版本基线点）:
禁改边界（只读库、外部依赖、不可覆盖的证据）：
外部件运行解释器绑定（20 §1；每引入一个外部件必须登记，含绝对路径；环境验收见 `scripts/runtime_env_probe.py`）:
竖向轴与 up 轴声明（19 §2 轴契约；UrhoX 默认 Y-up → front 的竖向轴是 Y；**统一注册链必须包含这一条**）:
体素边长与其反算来源（20/drawings；写明“值 + 怎么反算出来的”，因为**体素尺寸不是全局常量**）:
参考图入包闸结果文件（`reference_manifest.json` + `identity_declarations.json` 路径；H1–H6 结论。G2 不得引用未过闸的图）:
参考同一性门禁参数（`IdentityConsistencyMin` / `ClipCoverageMin` / `ConsistencyMargin`；出处 `02` §4.6，初始标定 0.80 / 0.95 / 0.10）:
同类复刻检索登记（G1 开场动作；A 线对照目录 / B 线证据目录，含扫描过的端点与**零结果**）:
主数据形态与子对象切分（四张浮雕头像 / 多塔 / 多舰这类对象必须写清按什么子对象建目录）:
出图渠道与落点（三视图交付格式 DXF/SVG/PDF 的目录；对账/回滚认 `projection.json` 的哈希，不认 DXF 字节）:
```

参数缺失时**先补最小必要参数，不要把猜测写成正式建模依据**。口径不清时暂停正式结论；若用户要预览，可做带假设标签的可逆 `EXPLORATORY` 草模，并明确它不能进入证据链。

## 3. 门禁与裁剪

- **门禁的唯一来源是 `references/04-verification.md` 的四张检查表**（A 空间忠实度 / B 体素工程质量 / C 视觉语义 / D 玩法物理）。任何文件里出现的“G5 通过”“G6 通过”都只表示对应检查表在指定版本上通过；本 Skill 不再另列门禁成员表，也不得把它扩大解释成整体完成。
- **上游另有一道入包闸，不属于上述四类**：`references/19-reference-image-intake-gate.md` 的 **H1–H6** 决定“**一张图能不能当 G2 制图的输入**”，在 G1 阶段执行。它**不判“像不像”**，也不得与 A–D 四表互相替代；四表管产出，入包闸管输入。
- 裁剪遵守四条：
  1. 裁剪的是**检查项**，不是证据标准；B 表全部检查项与“指标可追溯”在任何类型与尺度下都不可裁剪（清单见 `08` 第 4 节）。
  2. 裁剪必须留痕，固定四段式，缺任一段视为漏检：`裁剪项 | 理由 | 替代检查项 | 确认人`。
  3. 无替代检查项的裁剪，对应门禁最高只能 `PASS-WATCH`；不得以“该类对象不需要”当作放行理由。
  4. 四类门禁不得合并，任何一类不得替代其他三类。

## 4. 不可破坏的工程契约

以下 9 条是本 Skill 的硬约束；其余操作细则的唯一出处是 `references/00-pipeline-and-gates.md`（单位与网格、冻结点、口径变更、轮次协议），本节不重复。

1. **唯一注册链**：参考素材、锚点、轮廓、结构线、机位、生成器、烘焙产物共享同一套注册变换；禁止多处各自维护缩放或偏移（检查方法见 `02` §4.4）。
2. **主数据与派生结果分离**：测绘数据、锚点表、轮廓/等高线/房型图、布局脚本、资产库是主数据；编辑器或烘焙产生的节点树是派生结果，可删除重建且必须幂等。
3. **锚点纪律**：禁止跨轮引用行号与文件字节数做判断；持久锚点用符号名、固定字符串或固定搜索的**命中条数**，字节数只用于同一轮内的前后对比。
4. **零样本不下结论**：本轮无新样本时只能写“无法判断改善或恶化”，不得写“无变化”“已修复”，不得伪造样本。
5. **静态证据有边界**：静态解析、离线计算、结构对账不能推出运行时正确/画面已修复/物理已生效；此类结论必须写明“未跑运行时 + 静态关系推断”。
6. **改动可回滚**：任何资产或配置写入前先备份，记录改动前后的字节数与校验值（登记位见 `07` §2），并给出可粘贴的回滚命令。工具默认 dry-run，显式 `--apply` 才落盘。
7. **解释器绑定**：外部件的“可跑”必须指明**在哪个解释器上可跑**，不得用“本机能跑”含糊带过。
   `FreeCAD.pyd` 只能被 FreeCAD 自带的 **3.11** 导入，`bpy` 只能走 `blender --background --python`；
   跨解释器调用必须写成显式子进程命令。环境本身的验收用 `scripts/runtime_env_probe.py`，
   **环境漂移未解释清楚前，相关件的结论一律 `PASS-WATCH`**（详 `20`）。
8. **出图三体检 + 哈希选择**：任何“从数据出图纸/出量测”的链路开工前先做三项体检，
   三项任一未确认就不得声明图可用：
   （a）**单位/体素边长的反算来源**（体素尺寸不是全局常量，用错只缩放错不报错）；
   （b）**高度轴的取值来源**（节点盒高 ≠ 实心高度）；
   （c）**up 轴**（数据是 Y-up 还是 Z-up，直接决定立面画的是不是立面）。
   并且：**对账与回滚认几何源（如 `projection.json`）的哈希，不认导出图纸的字节**
   （DXF 一类会写时间戳与自增句柄，字节不可复现）。
9. **保真主线 + 禁止 AI 主动冻结**（用户级裁定，**优先级最高**）：
   （a）**主线只有一件：把模型做得更像参考**；收口/交接/文档/门禁/报告/定案均为**附属**，不得占主线。
   （b）**禁止一切主动冻结**：不写/不沿用“几何已冻结”“通道已验证完”“已定案”“此后只改文档与工具”这类**自锁结论**；
   已有此类叙述**删除或标 VOIDED**。**除用户明说停，模型永远可以做得更像。**
   （c）仅允许冻结“**参考取值**”（= 目标定义，如注册变换、基准读数、交付身份哈希集合）—— 那不表示“活干完了”。
（d）在工作区已接入 `tools/fidelity_gate.py` 时，机器判据为：**4h 内几何/材质（或 `.vox` 导出件集合哈希）未动 = `NO-FIDELITY`**；**存在未作废自冻结声明 = `SELF-FREEZE`**。未接入该工具时不得伪造 4h 读数或门禁结果，应把“尚未测量”写明。
违规 ⇒ **补“保真推进”卡**（`--verify` 必写“几何/材质指纹**必须移动**，附新值”）+ 唤醒 owner；没有 owner/卡片系统时，给出可执行的下一次保真改动与验证命令，不要假装已触发流程。
   （e）备卡配比 **推进:收口 ≥ 2:1**（收口卡每路 ≤1 张）；**禁写“冻结/完工/定案”类卡**。

## 5. 任务路由

按当前任务只读需要的参考，不要无差别全量加载：

| 任务 | 必读参考 |
|---|---|
| **确定对象类型、尺度等级与门禁裁剪** | `references/08-subject-classes-and-scales.md` |
| 排轮次、轮次协议、冻结点、状态语义、性能必录项 | `references/00-pipeline-and-gates.md` |
| 资料检索、来源分级、标定、冲突与归档 | `references/01-reference-evidence.md`（§3.2 等级↔能力清单，§6.1 语义去重，§7 锚点须含本体） |
| **自己找参考图：站点目录、检索语法、批量抓取与截图方法** | `references/09-reference-sourcing-and-capture.md` |
| **开工前先查“别人做过没有”：同类复刻作品 + 结构化素材库检索（端点/分类树/纪律）** | `references/09` §2.5 |
| **实测站点/端点/抓取参数（米游社系、官方、wiki 系等）** | `references/09a-source-catalog.md` |
| 制图/测量、图签容差、注册链与冻结流程 | `references/02-drafting-and-registration.md`（§4.6 配准防伪四条） |
| **外部数据入图：矢量/位图判定、产出契约、实测导出入图、任务书先行** | `references/02` §10.5 + `references/23` |
| 体素建模语法、资产分层、各类对象建模要点 | `references/03-voxel-modeling.md` |
| 四类验收检查表、阈值登记、多机位回归 | `references/04-verification.md` |
| 引擎 Lua、离线批处理、PIE 烘焙、动态体素、路径排错 | `references/05-urhox-operations.md` |
| 迭代“更像”的固定机位与缺陷关闭循环 | `references/06-visual-fidelity-loop.md` |
| 证据包落点、清单校验、交接、管理层汇报 | `references/07-delivery-and-reporting.md` |
| **验收仪器与门禁实现（哈希/stats/帧 QC/越界闸/日志隔离/参考同一性/形制形态）** | `references/10-verification-instruments.md`（I-11 / I-12） |
| **取证通道、API 复现、限流与零结果登记** | `references/11-reference-harvest-playbook.md` |
| 看一个填好的城市类案例 | `references/90-case-mondstadt.md` |
| **看某个对象的完整数据记录（案例包，默认不读）** | `cases/README.md`（三层参考价值标准由 `scripts/case_index.py --check` 机器门禁把关） |
| **离线渲染 vs 引擎内运行：只在运行通道暴露的缺陷** | `references/12-channel-divergence.md` |
| **多线任务的成本核算与播报** | `references/13-cost-accounting.md` |
| **换引擎 / 选表示 / 对照分析方法学与指标有效性域 / 跨引擎能力探针** | `references/14-cross-engine-methodology.md` |
| **本轮该开哪些引擎原生能力 / 各能力默认值与平台差异 / 开启后要配哪条验收** | `references/15-urhox-native-capabilities.md` |
| **光照与后处理的保真：三通道纪律 / 光照契约 / 外观归因 / 后期冻结** | `references/16-lighting-and-postprocess-fidelity.md` |
| **接外部开源技能/包：哪些能直接用、哪些只能借流程、哪些不能碰、许可证边界** | `references/18-external-skill-adoption.md`（机器校验：`scripts/external_skill_map_check.py`） |
| **参考图入包：视图角色矩阵、可量测性、期望部件数、参考同一性与对象在场性（G1 入口闸）** | `references/19-reference-image-intake-gate.md`（实现：`scripts/reference_intake_gate.py` + `scripts/ref_identity_gate.py`） |
| **外部资产清单：84 个参考包条目的等级/阶段/可抽取件与提炼范围** | `assets/README.md`（索引：`assets/external-skills-index.json`；重建与校验：`scripts/external_asset_index.py`） |
| **跑外部件需要什么环境：解释器绑定、装到哪、依赖怎么判、环境怎么验收** | `references/20-runtime-environment-and-dependencies.md`（验收：`scripts/runtime_env_probe.py`） |
| **从占用/体积数据反向出图：出图三体检、并集轮廓、与外部绘制件的分工、可复现性** | `references/21-occupancy-to-drawing.md`（实现：`scripts/voxel_orthographic_drawing.py`） || **投影 ↔ 渲染对账（两侧掩膜怎么来、为何不能拿亮度猜前景、控制帧为何被证伪）** | `references/21` §7 + `references/19` §3.1（首次实测值） |
| **视觉特征词表：六轴标签、冻结词表 v1、标签 schema 与禁止用途** | `references/22-visual-feature-taxonomy.md`（词表：`assets/feature-taxonomy-v1.json`；校验：`scripts/feature_taxonomy_check.py`） |
| **参考数据解析：矢量/位图判定、各形态可取字段、产出契约、精度与合法性** | `references/23-reference-data-parsing.md` |
| **（可选）语义保真增强：必含项清单、关系检查、负样本协议（不属门禁）** | `references/24-semantic-enhancement-optional.md`——只在项目主动启用时才适用；可直接填 `templates/semantic_check_sheet.md` |
| **Xdanger S2 下游适配：固定模板、0.1m 世界、快照、场景/个人/功能组件与运行验证** | `references/25-xdanger-adaptation.md`——只在明确交付到 Xdanger 时启用；不能替代 Xdanger 工程内注册和原生运行验证 |

### 5.1 工具总表

**本表只收包内 `scripts/`。** 另有两项**不随包发**，按位置调用：

| 位置 | 工具 | 作用 | 出口 |
|---|---|---|---|
| **项目侧** | `audit_phantom_check.py` | 幽灵格/越界/三指纹核查 | 详 `10`；**位于各工程 `<工程>/tools/`** |
| **外部** | `quick_validate.py` | Skill frontmatter 校验 | 属 `skill-creator`；Windows 需 `PYTHONUTF8=1` |

根目录同名 Python 文件若存在，仅为兼容转发到 scripts/；规范、接口与实际实现以 scripts/ 为准，不得把根目录副本当第二实现。

包内脚本：

| 脚本 | 作用 | 出口 |
|---|---|---|
| `urhox_capability_probe.py` | 确认本发行版是否导出某原生能力、工程是否已引用 | 0 可用 · 非 0 不可用（详 `15` §4） |
| `reference_intake_gate.py` | 参考图入包闸 H1–H4（视图角色/可量测性/部件数/正交基底） | 0 硬门禁全过 · 1 有 FAIL · 2 用法错 |
| `ref_identity_gate.py` | 参考图入包闸 H5–H6（对象×区域×版本同一性 + 对象在场性；读 `identity_declarations.json`） | 0 无 FAIL · 1 有 FAIL · 2 用法错 |
| `design_gate.py` | **设计驱动模式门禁 G0–G8**（无外部真值：结构合法/边界/接地/高度带与规则推导/屋顶覆盖/开口归属/可达/必需项/语义分组）；入 = 设计声明 + Blueprint + 占用栅格 +（可选）iso-map 地板图 | 0 全过 · 1 有 FAIL · 2 用法/IO 错 · 3 输入不足（裁剪写入 `skipped[]` 留痕） |
| `registration_crosscheck.py` | 配准防伪四条（留出法 / 独立一致性落点率 / 零残差警示 / 裁剪完整性） | 0 通过 · 1 未通过 · 2 用法错 |
| `heightfield_form_check.py` | 形制/形态读数（单一高程带占比、最满 1 米带占比、无实测支撑占比；结论名 `TERRACE-UNPROVEN` = 形态未经独立证据校验；`field_kind=terrain` 才适用） | 0 正常 · 1 命中 `TERRACE-UNPROVEN` · 2 用法错 |
| `form_shape_check.py` | 形制/形态复核（高度 provenance 分层 / 剪影长宽比与转折点 / 与 I-12 读数交叉复核；`--self-test` 内置 r17/r18 正样本自检，防误伤正确实践） | 0 通过 · 1 有旗标（`PROVENANCE-UNRESOLVED`/`TERRACE-UNPROVEN`/`SILHOUETTE-MISMATCH`）· 2 用法错 · 3 自检失败 |
| `check_crossrefs.py` | 全库交叉引用体检（悬空指针） | 0 无悬空 · 1 有悬空 |
| `compare_masks.py` | 掩膜/轮廓对比；明确 binary-mask、共同有效域与候选报告绑定，候选不自动通过 | 详 `10`；候选契约见 `19` §5.1 |
| `reference_subject_mask.py` | 原图目标提示辅助分割；保存 lossless mask/ignore/overlay 与复核位置 | 0 候选 · 3 无目标/退化 · 2 输入错，不授予语义通过 |
| `reference_prompt_diagnostics.py` | 只读 API：analyze_prompt，定位笔划混色、未知边界、连通与细部风险 | 库模块，无独立 CLI；风险不是语义评分 |
| `reference_mask_stability.py` | 同一原图、同提示下改变工作分辨率，生成敏感区域图；不改 ignore、不投票成真值 | 0 敏感性实验完成 · 2 输入/求解错误，不授予语义通过 |
| `build_evidence_manifest.py` | 生成并校验证据清单 | 详 `07` §5 |
| `case_index.py` | 案例包索引与三层参考价值门禁 | 详 `cases/README.md` |
| `runtime_env_probe.py` | 运行环境验收（解释器/包/浏览器内核） | 0 期望全中 · 1 漂移 · 2 解释器缺失 |
| `external_asset_index.py` | 外部资产索引重建与校验（`--build/--check/--worklist`） | 0 无漂移 · 1 有异常 |
| `external_skill_map_check.py` | 18 号文档 ↔ 现场文件 ↔ MANIFEST 三方对账 | 0 GREEN · 1 PROBLEMS |
| `external_tool_fetch.py` | 外部件抽取+依赖探测（`optionalImports` 区分可选依赖） | 0 ok · 1 有缺失 |
| `voxel_orthographic_drawing.py` | **体积盒** → 真投影 + 并集轮廓 → A3 装配出图（体量关系图，**不是**真三视图） | 0 ok · 1 无数据/导出失败 · 2 用法错 |
| `voxel_occupancy_dump.py` | **逐体素占用导出**（注入工程模板 + 走日志通道；产物 = 三视图剪影位图 + 逐体积计数 + 真实体积） | 0 ok · 1 导出失败 · 2 用法/工程不符 |
| `voxel_silhouette_drawing.py` | 逐体素三视图；DXF/PDF/SVG 必须显式 `--cadstack <backend>`；无后端只出几何 JSON，轴测仅示意 | 0 请求的产物已生成 · 1 导出失败 · 2 输入/后端缺失 |
| `projection_to_mask.py` | 投影 → 正交掩膜（按 orthoSize/res/center 映射；`--auto-flip` 出两个手性） | 0 ok · 1 视图不存在 · 2 用法错 |
| `object_mask_from_render.py` | 渲染侧对象掩膜：对象帧 − 控制帧，带退化判据 | 0 OK · 1 掩膜退化 · 2 IO 错 |
| `outline_vs_render.py` | 投影轮廓 vs 渲染边：边缘一致度（含 `bestPixelShift`）；不需控制帧 | 0 ok · 1 退化 · 2 用法错 |
| `make_edge_report.py` | 边缘一致度结果 → **自包含单文件 HTML**（叠图内联为 data URI） | 0 ok |
| `cad_volume_crosscheck.py` | 用 FreeCAD（第二实现）独立重算体积并与审计对账（**上界校验**） | 0 在容差内 · 1 超出 · 2 用法/执行错 |
| `feature_taxonomy_check.py` | 词表一致性；加 `--tags` 才检查真实批次标注的 schema/词条，不判视觉真伪 | 0 一致 · 1 词表/标注不合法 · 2 输入缺失 |
| `skill_structure_check.py` | **包结构门禁**：路由/登记/版本一致/编号白名单 | 0 GREEN · 1 有结构问题 |
| `make_drawing_report.py` | 把图纸与投影数据打包成**自包含单文件 HTML**（手机可看） | 0 ok · 1 无可打包对象 |

> 本表是**工具位置的唯一出处**：包内 = `scripts/`；项目侧 = 各工程 `<工程>/tools/`；外部 = 其它 Skill。
> `scripts/skill_structure_check.py` 会校验“包内行 ↔ 实际文件”两向一致，漏登记或多登记都会报错。

## 6. 证据包

归档清单、文件命名与必需文件的**唯一出处是 `references/07-delivery-and-reporting.md` 第 2 节**；本 Skill 只强调**七条**容易被漏掉的硬要求：

1. 每个机位必须有**原图 / 改后图 / 差异图三件套**，命名要能被清单脚本校验。
2. 指标必须同时给**均值与最差项**；只给均值视为无效。
3. 每轮的 9 项性能读数（见 `00` §6）必须落在 `perf_<tag>.json`，不能只在对话里出现。
4. **参考图入包闸的结果**（`reference_manifest.json` + `gate_report.json` + `identity_declarations.json` + `identity_report.json`）必须随轮归档：
   否则无法回答“本轮用的图有没有过闸”（`19`）。
5. **出图类产物进包的是几何源**（投影/轮廓 JSON）及其哈希，不是图纸容器的哈希（`21` §6）。
6. **环境验收输出**（`runtime_env_probe.py --json`）随轮归档：它是“外部件可跑”结论的唯一凭据（`20` §4）。
7. **G1 的同类复刻检索登记**（含零结果）必须随轮归档：否则无法回答“这轮到底查过没有、为什么选这个主数据形态”。

清单生成用 `scripts/build_evidence_manifest.py`（用法与退出码见 `07` §5）。

## 7. 停止条件

唯一出处是 `references/00-pipeline-and-gates.md` 第 4 节（轮次协议与升级阶梯）与 `references/06-visual-fidelity-loop.md` 第 14 节。本节不重复列条件，避免两处判据漂移。

## 8. 维护本 Skill

- 规范与案例分离：`00`–`08` 不含具体项目名/地名/绝对路径；数值进参数表或 `90-*` 案例。
- 一条规则只能有一个出处：新增规则先判断归属文件，其余文件只留指针，禁止复制正文。
- 外部技能采纳的**唯一出处是 `18-external-skill-adoption.md`**；其它文件引用外部包时只写“采纳等级 + 指向 18”，不复制路径清单（避免两处索引漂移）。
- 外部资产的**机器可读清单唯一出处是 `assets/external-skills-index.json`**（由 `assets/external-skill-curation.json` + 各包 MANIFEST + 现场扫描合成）。改过参考包或 curation 后必跑 `scripts/external_asset_index.py --check`。
- **`b: provisional` 的条目不得作为决策依据**：它只表示“文件清单看过”，不表示“内容读过”。
- 参考图入包判据的**唯一出处是 `19-reference-image-intake-gate.md`**；`01` 只管等级与证据资格，两张表的成员不得互相搬运。
- 从占用数据出图的**唯一出处是 `21-occupancy-to-drawing.md`**；项目里的出图记录只写“具体数值与复现命令”，不复制规范正文。
- 包级质量检查统一走 `python tests/run_tests.py --json`；在工作区内应加 `--project-root $URHOX_REPLICATION_ROOT`，它会串行执行结构、引用、词表、外部资产、外部映射、案例、脚本帮助、自检与环境门禁。
- 参考归档未挂载时可加 `--skip-external`，只做可移植包检查时可加 `--skip-environment`；任何跳过项都必须保留在 JSON 报告中，不得写成完整通过。
- 发布门禁加 `--require-complete`；只要有 skipped 项就以非零退出，防止把 partial 误报为完整通过。
- `scripts/external_tool_fetch.py --verify --dest <目录>` 只依据 `_PROVENANCE.json` 校验已抽取文件的字节哈希，不重新执行外部代码。
- **包结构与导航的唯一出处是 `INDEX.md`**：目录作用、阅读路径、门禁清单、当前实测基线、未决项。
  `SKILL.md` 保持薄路由入口，不复制索引内容。
- 视觉特征标签的**唯一出处是 `22-visual-feature-taxonomy.md`**；标签是描述符、**不得进几何证据链**。
- **工具表（§5.1）新增脚本时同步登记**，否则不算进主线。
- 改写后用 `skill-creator` 的 `quick_validate.py` 复核（Windows 需 `PYTHONUTF8=1`，否则校验器自身会以 GBK 读 UTF-8 报错）。
