# 参考图入包闸（视图角色矩阵 · 期望部件数 · 可量测性）

本文件是**G1 的入口闸**：一张图在进参考包、进来源表之前，必须先过这张表。
它不判断"像不像"（那是 `04` 的四类发布门禁），也不定来源分级（那是 `01`）。

分工（避免双出处）：

- `01-reference-evidence.md`：图的**等级与证据资格**（A/B/C/D、冲突、追溯链）。
- `09`/`09a`/`11`：**去哪抓、怎么抓、抓不到怎么留痕**。
- **本文件：抓回来之后、进来源表之前，图的"可量测性"与"视图完备性"检查。**
- 本文件**不新增 `04` 的四类门禁成员**；它只决定一张图能不能当 G2 制图的输入。

## 0 适用与不适用

| 适用 | 不适用 |
|---|---|
| 要用于**量测/注册/投影对账**的正视、侧视、顶视、轴测参考图 | 纯氛围/灵感图（那类不进参考包，按 `01` 归为灵感收藏） |
| 用于**部件切分与标志点**的设定图、特写图 | 宣传 CG（VFX 外溢，`01` §2 已禁止当几何口径） |
| 用于**渲染侧对照**的参考图（G5/G6 的 IoU 基准） | 已进入 `_src/` 但只作记录的历史件（标注 `intake: grandfathered` 即可，不重判） |

## 1 六个硬门禁（任一不过 → 不得作为 G2 制图输入）

| 编号 | 门禁 | 判据 | 不过的处置 |
|---|---|---|---|
| **H1 视图角色必须已声明** | 每张入包图必须落到 §2 矩阵的**恰好一个**角色；`unknown` 不允许入包 | 角色来自文件名/元数据 + 人工确认；`unknown` 一律降为灵感收藏 | 补角色或移出参考包 |
| **H2 可量测性达标** | 按 §4 判据，图的 `usability` 必须是 `usable`；不得是 `near_black` / `near_white` / `low_contrast` / `blurry` / `tiny` | 由 `scripts/reference_intake_gate.py` 计算并留证 | 换图，或降级为"仅形制参考"（不得参与尺寸推导） |
| **H3 结构件数已声明且可核** | 若该视图进入部件切分流程，`reference_manifest.json` 必须给出 `expected_parts`（**精确整数**）及原图绑定的人工 `observed_parts` / `observed_parts_evidence`，两数一致且证据可核 | 脚本只给 `component_count_proxy`；连通域不等于语义结构件，缺人工证据不得自动通过 | 补声明与原图标注；连续不一致 → 按 §6 路由 |
| **H4 正交基底存在** | 必须同时有：① 一张 `role ∈ {front, side, section}` 且 `usable` 且等级 `∈ {A,B}` 的**高度向**图；② 一张 `role ∈ {front, side, top}` 且 `usable` 且等级 `∈ {A,B}` 的**水平向**图 | 由脚本计算；等级来自 `01` 的来源表 | 回 `09`/`11` 补采；**不得**用 `iso`/`context` 顶替 |
| **H5 参考同一性** | 该图必须能回答 **对象 × 区域 × 版本** 三问，且每问自带**可核证据**（官方标签名 / 物种或 POI 清单 / 地名串 / 版本号 / 采集日期）；证据必须指向本流程之外的**独立件**（本图自身、我方渲染与我方测量脚本的产物**不算证据**）。三问任一给不出、证据不可解析、或“区域”问的独立一致性读数不达标 ⇒ **FAIL** | 判据与字段见 §1.2；由 `scripts/ref_identity_gate.py` 计算并留证 | 不得作 G2 制图输入；可降为 `EXPLORATORY` 留档；**零结果也要登记**（“查过但没有” = 该问未回答，同样是 FAIL） |
| **H6 对象在场性** | 图上必须出现**对象本体**：比例锚、配色锚、对照板、“参考”位与裁切片的**母图**均必须含本体。仅“局部特写”可例外，但必须显式声明 `close_up: true`、给出**本体位置框**与母图引用（框须落在帧内且非退化） | 判据与字段见 §1.2；由 `scripts/ref_identity_gate.py` 计算并留证 | 不得进对照板 / 比例锚 / 参考位；可降为 `context` 或氛围图 |

> **H4 存在的理由**：H1 只看“角色是否声明”，一张图都可以被声明成 `context` 从而把 H1 变成形式。H4 把“有没有可量测的正交证据”单独抽成一条硬门禁——**没有就是没有，不允许用“已声明角色”冒充已具备证据**。
> 它要的是**基底**而不是某一张图：高度向（front / side / section）+ 水平向（front / side / top）两半齐了才算有基底。只有 `top` 给得出足迹给不出层高，只有 `section` 给得出层高给不出另一水平向。

> **H5 / H6 存在的理由**：H1 只看“角色是否声明”、H4 只看“有没有可量测的正交证据”——**两者都不问“这张图是不是这个对象、里面有没有它”**。一张错区图、一张我方自造的测量可视化、一段不含对象的车内镜头，都能拿到完整角色、甚至凑出“正交基底”。2026-09-29 的 092802 批次实测：一个错区被当成目标区域跑了约 **90 轮**（雾带 p50 7 m vs 真值 69 m、环距 11 m vs 32 m）；另一路用**不含对象本体**的车内帧定出红白比例区间（0.47–2.43），模型随后 20+ 轮都在朝这个标准回调。两类都不是“角色没声明”，而是**身份与在场性没人问**。
> 按 `04` §0 的门禁准入条件，两条都满足：① 该类失效在近两批**各发生 ≥1 次**；② 返工成本**远超 1 轮**（错区 ~90 轮、错误比例锚 20+ 轮）。因此它们有资格作为**可拦人**门禁进入本表，而不是只做仪器（`10` I-11）。

> **H3 的计数口径**（引自外部实现，见 §5）：**装饰性元素不计入结构件**——飘带、光晕/光环、投影、参考辅助线、HUD、背景圆环、水印，除非 manifest 显式声明它是结构件。

### 1.1 外部模型政策（**不是门禁**，靠脚本检查）

> 2026-09-24 收敛：本条曾作为**入包闸的附加门禁**（与既有的 **H4「正交基底存在」编号冲突**，是“门禁扩散”的典型现场），现**降级为来源政策**（它是合法性边界，不是图质量闸；摆进门禁表只会抬高停手风险，并与其它文件重复）。

- **允许**：把现有 3D 模型的展示画面（含正交预览）**截图**后当参考图入包（登记 模型名/平台/URL/许可/机位）；**等级 ≤ C**；只作**形制与比例的方向性对照**，**不得作量测输入、不得据此改冻结值**。
- **禁止**：下载或导入模型**文件**（`.obj/.fbx/.glb/.gltf/.stl/.ply/.blend/.vox/.dae`），以及把其几何（含重网格 / 体素化 / 格式转换产物）用入我方产物。
- **机器检查**（后缀禁列清单 + **时间窗** + 引擎发行包/工程资产目录白名单，避免把引擎自带示例资产与我方自产导出误判）：窗口内出现禁列后缀即判违规（非零退出）。**文件不进工作区 ⇒ 不可能被导入。**
- 边界：脚本只能抽查“文件是否落地”，不能证明几何来源；最终靠来源追溯链（§15）与四信号仲裁（`10` I-03：几何指纹突变但无对应参数/生成器变更 → 触发审查）。

> **H3 的计数口径**（引自外部实现，见 §5）：**装饰性元素不计入结构件**——飘带、光晕/光环、投影、参考辅助线、HUD、背景圆环、水印，除非 manifest 显式声明它是结构件。

### 1.2 H5 / H6 的声明文件与机器判据（唯一出处）

H5/H6 的判据落在**同一份声明文件** `identity_declarations.json`（与 `reference_manifest.json` 并列存放，逐图一条）。

```text
file                 图文件（相对参考包根）
sha256               原图哈希（与 `01` §6 的清单同源）
object               三问之一：对象（官方名/通用名，非我方代号）
region               三问之二：区域（行政区 / 地图分区 / POI 集名）
version              三问之三：版本或采集日期（游戏版本号 / patch / 拍摄日期）
evidence[]           每问的证据：{question, kind, path_or_url, sha256?, note}
zero_result[]        查过但没有的检索：{question, queries[], searched_at}
generator            来源通道：external | self | unknown
usage[]              用途：reference_pack | reference_slot | compare_board | anchor | context | exploratory
present              仅 H6：对象本体是否在图中（true/false）
subject_bbox         H6：本体位置框 [x0,y0,x1,y1]（帧内像素坐标）
close_up / mother_image  仅 H6 局部特写：是否特写 + 母图引用
declared_by / declared_at / declared_rule   签核人与依据（“判级/角色/在场性”都要能回答是谁、按什么规则定的）
```

机器判据（实现：`scripts/ref_identity_gate.py`；逐图 PASS / FAIL / UNKNOWN，exit 0/1/2）：

| 编号 | 判据 | 不过的含义 |
|---|---|---|
| H5-1 | `object`/`region`/`version` 三字段齐备且非空，值不得为 `unknown`/`n/a`/空串 | 没问过身份 ⇒ 未回答 |
| H5-2 | 每问至少一条**非自造**证据（`generator == self` 的条目不计入证据），且 `kind ∈ {official_label, poi_list, place_name, version_id, capture_date, official_map, source_id}` | 答案没有可核凭据 |
| H5-3 | 所有证据条目的 `path` 存在、`sha256` 与记录一致；`generator ∈ {external, self, unknown}`（自造条目只作线索） | 证据链断（我方产物不能自证） |
| H5-4 | “区域”问凡以本区官方图 / POI 集为证据者，必须附 `02` §4.6 的独立一致性读数：落点一致率 ≥ `IdentityConsistencyMin` **且**裁剪覆盖率 ≥ `ClipCoverageMin`（两个参数的出处与初始标定见 `02` §4.6） | 区域对不上（实测例：62.9% vs 对照 84.2%） |
| H5-5 | `zero_result` 必须登记，但登记不等于通过：该问若无其他证据 ⇒ FAIL | 零结果被静默当成“没问题” |
| H6-1 | `usage` 命中 `reference_slot`/`compare_board`/`anchor` 时，`present` 必须为 `true` | 对象不在场仍被当参考 |
| H6-2 | `subject_bbox` 必须在帧内、面积占比 ∈ (0, 1)；`close_up == true` 时必须有 `mother_image` | 位置框不可核 ⇒ 声明无效 |

**纪律（比条款本身更重要）**：**声明 ≠ 核实**。`present: true` 是**人/视觉签核**的结果（`declared_by` + `declared_at` + 依据），脚本只保证“没有被静默跳过”。把未签核的 `present` 当已核实，等价于伪造 H6 通过——与 `10` I-01b 的“空输入哈希 = 永久假绿”是同一类洞。

**与其它文件的分工**：区域问的读数由 `02` §4.6 的独立一致性检验提供（`scripts/registration_crosscheck.py`）；等级判定仍归 `01` §3；本表只决定“这张图能不能进 G2”。

## 2 视图角色矩阵（轴契约的唯一出处）

每个角色必须自带**轴契约**；不同角色之间的共享轴是后续 `multiview-constraint-solver` 式冲突裁决的依据。

| 角色 | 轴契约（宽X / 高Z / 深Y） | 典型来源 | 允许回答 | 不允许回答 |
|---|---|---|---|---|
| `front` | X 宽 · Z 高 | 官方立绘、游戏内正面 | 正面轮廓、正面部件数、对称性 | 进深、层数 |
| `side` | Y 深 · Z 高 | 侧视截图、设定集侧图 | 进深、屋顶出檐深度、层高比 | 正面宽度 |
| `back` | X 宽 · Z 高 | 背视截图 | 背面轮廓 | 进深 |
| `top` | X 宽 · Y 深 | 官方地图（俯视）、航拍式截图 | 平面足迹、绿化/道路关系 | **高度、层数**（俯视原理上给不出，`11` 已登记） |
| `section` | 竖向切割：Z 高 + 一个水平轴（**必须声明是哪根**） | 剖面图、南北剖/东西剖 | 层高、屋顶出檐深度、内部层叠 | 未被切到的另一水平向 |
| `iso` | 三轴同时可见 | 官方宣发、玩家截图 | 体量关系、层叠顺序 | 任何精确尺寸 |
| `detail` | 局部特写 | 檐口/台基/构件特写 | 构件形制、纹样、材质 | 整体比例 |
| `texture` | 无空间轴 | 材质图集、色卡 | 配色、材质分区 | 一切几何 |
| `context` | 视用途 | 场景全景、环境 | 环境关系、朝向 | 对象本体尺寸 |

**矩阵纪律**：

1. 一个文件只能有一个角色；需要多角色就复制成多个条目并各自声明（禁止一图两用而不声明）。
2. `top` 角色**不得**用于推导高度/层数——这是 `11` 已在实项目上确认过的边界，本表不重复解释。
3. 同一共享轴至少有 **两个**不同角色的图才能做交叉校验；只有一张 `front` 时不产生约束，登记为单源结论。
4. **角色由轴契约与投影几何判定，不由文件名或来源通道判定**：带注记文字且为俯视投影的图 ⇒ `top`（即使文件名为 `iso_*`）；实机多角度截图按 `01` §3 属 **B 级能力**，但**角色仍按本条判**。文件名、目录名与抓取通道只作**线索**；角色或等级的每次变更都必须写进 `declaration_log`（§8 第 3 条）。

## 3 阈值表（含注册状态）

**本表来源**：`cc-blender-skill` 的 `reference-analysis-validator/references/metrics-and-thresholds.md`（本地留档见 `18` Ⅰ-1），等级 **[外/文档]**。**未进 `04` 门禁**，因为尚未在本工程留下实测负样本；写入 `04` 前必须先跑出至少一条反例。

| 指标 | 定义 | 外部建议阈值 | 本工程状态 |
|---|---|---|---|
| Mask IoU（参考 vs 渲染） | `intersection / union` | ≥0.90 刚性/标志类；≥0.85 软表面 + 标志点通过；<0.80 不得作为最终导出 | [外/文档]，待实测 |
| Centroid drift | 二值 mask 质心偏移 | ≤12 px @1024 验证尺寸，或 ≤1.2% 宽 | [外/文档]，待实测 |
| Bbox drift（中心） | 参考与渲染 mask 的 bbox 中心差 | ≤12 px | [外/文档]，待实测 |
| Bbox drift（尺寸） | 宽/高差 | ≤图像尺寸的 3% | [外/文档]，待实测 |
| 标志点漂移 | 面部/关键点 | ≤图像尺寸 2%（已定义标志点时） | [外/文档]，待实测 |
| SSIM | 感知诊断 | ≥0.75 早期带材质；≥0.88 近收尾纯色叠合 | [外/文档]，**只作诊断不作唯一判据** |
| 结构件数 | §1 H3 | **精确相等** | [外/文档]，口径采纳（§1 引用） |

对比模态规则（**采纳**）：**同类比同类**。线稿边缘 mask 与着色渲染比会得到误导性的低 IoU；硬门禁必须比 flat silhouette/matte，或边缘比边缘。

### 3.1 边缘一致度（本工程实测，与 IoU 并列的另一个量）

**为什么另开一个量**：投影级对照除了掩膜 IoU，还有一种成本低得多的做法——**把投影轮廓叠到渲染帧上，量两者是否落在同一条边上**。它不是面积比，所以**不得**冒充 IoU；但它**不需要控制帧**，也不需要把主体从光照里拿出来。

定义（实现：`scripts/outline_vs_render.py`）：

| 指标 | 含义 | 怎么读 |
|---|---|---|
| `refToRender` | 我们轮廓上每个像素→最近渲染边的距离（px） | 小 = 轮廓落在真实边上 |
| `renderToRef` | 渲染边上每个像素→最近轮廓的距离（px） | **必然很大**；渲染里还有瓦垄/植被/地形/AO 等细节边，体积盒模型本就解释不了 → **不得当缺陷指标** |
| `bestPixelShift` | ±N px 平移中 p90 最小的那个位移 | 平移后 p90 明显下降 = 整体偏移；几乎不变 = 形状/尺度问题 |

**本工程首次实测（2026-09-23，天守阁 r4，分析宽 768 px，`--auto-flip`）**：

| 视图 | `refToRender` 均值 | p50 | p90 | ≤2px | ≤8px | ≤16px | 最佳平移 |
|---|---:|---:|---:|---:|---:|---:|---|
| top | **0.46** | 0 | **1** | 98.0% | 99.5% | 100% | (0,0) |
| side | 4.42 | 1 | 13 | 58.4% | 78.3% | 95.6% | — |
| front | — | — | 16 | 51.8% | 74.1% | 90.1% | (−1,+5) → p90 降至 14 |

换算：前/侧视 `orthoSize` 44 m、帧宽 2040 px，分析宽 768 → ≈ **0.030 m/px**；故 top 的 p90=1 px ≈ 3 cm，front 的 p90=16 px ≈ 0.5 m。

**读数与已知原因**：`top` 近乎完美（p50=0）说明**足迹与占地完全对得上**；`front`/`side` 的 p90 13–16 px 是结构性的，
来源有二：（a）轮廓粒度是体积盒并集，屋顶阶梯/檐口深度表达不出来；（b）`front` 存在小幅竖直整体偏移——已单独查过，见下。

**`front` 竖直偏移已查（摄像机中心 Y 扫描，分析宽 512，`--shift-scan 0`）**：

| 中心 Y | 16.0 | 16.5 | **17.0（实际）** | 17.25 | 17.5 | 17.75 | 18.0 | 18.5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mean | 6.34 | 5.23 | 4.01 | **3.95** | 4.04 | 4.38 | 4.58 | 5.24 |
| p50 | 4 | 3 | 2 | 2 | 3 | 4 | 5 | 5 |
| p90 | 15 | 13 | 12 | 11 | 10 | 9 | **8** | 9 |
| ≤18px 覆盖率 | 75.0% | 79.5% | 84.7% | 86.2% | 87.4% | 89.1% | **91.0%** | 81.4% |

**两条结论**：

1. **按均值/p50，最优在 `Y = 17.25`**，即存在约 **+0.25 m** 的系统性竖直偏移（对象高 34 m 的 **0.7%**）——
   量级与体积盒模型自身的误差同阶，**不值得单开一轮**；要修就与“逐体素占用”一起做。
2. **优化一个分位会牺牲另一个**：p90 在 `Y=18.0` 更低（8 vs 12），但 p50 从 2 涨到 5（多数轮廓点变差）。
   所以报告边缘一致度时**均值与分位必须并列给出**，并写明优化目标；只报单个数会变成“调参游戏”。

**注册状态**：本表的数是**首次实测**，与 §3 的 `[外/文档]` 阈值一样，**尚未进门禁**——
要进 `04` 必须先在本工程留下“人为做坏”的负样本对照（且跨轮比较必须固定渲染边的提取阈值）。

## 4 可量测性判据（本工程口径，脚本实现）

`usability` 由 `scripts/reference_intake_gate.py` 计算，判定顺序即优先级：

| verdict | 判据（在 ≤384 px 工作分辨率上计算） | 理由 |
|---|---|---|
| `reject:tiny` | 短边 < 128 px | 连轮廓都读不出 |
| `reject:near_black` | luma 均值 < 0.06 或近黑（luma<0.04）像素占比 > 70% | 与 `3dviz-pro-max` 的 near-black 类同源（见 `18` Ⅰ-2） |
| `reject:near_white` | luma 均值 > 0.94 | 同上，反向 |
| `reject:low_contrast` | luma 标准差 < 0.035 | 没有可分离的轮廓 |
| `reject:flat_wall` | 前景覆盖率 > 0.90 且最大连通域占比 > 0.95 | 被近平面墙/纯背景填满，等价于 `3dviz-pro-max` 的 wall-filled |
| `degraded:heavy_watermark` | 前景连通域中存在贴边且面积 > 15% 的块 | 水印/UI 遮挡，需人工确认是否能裁 |
| `degraded:low_detail` | 边缘能量低于**本批中位数**的 30% | 可能是模糊，也可能是**平滑/矢量化画风**（见 §9 局限 1） |
| `degraded:low_res` | 128 ≤ 短边 < 256 px | 可读形制与拓扑，**不足以支撑尺寸推导** |
| `usable` | 以上均不命中 | — |

> **阈值是甜的，不是硬的**：这些数字是本工程在现有参考包上标定的**初值**（标定依据见 §9），与 `3dviz-pro-max` 的阈值**不是同一套**（它的阈值按它的 eval 帧调过）。修改必须留下标定依据。

## 5 与外部实现的关系（诚实登记）

| 事项 | 外部实现（`cc-blender-skill`） | 本工程实现 |
|---|---|---|
| 语言/依赖 | Python + OpenCV + NumPy | 基础入包／透明域：Python + Pillow；复杂目标分割：另需 NumPy + OpenCV，绑定解释器 |
| Mask 提取 | alpha / Canny 边缘 / Otsu 双极性 | 有效源 alpha；否则目标框＋前／背景笔划驱动 GrabCut；缺目标则 NEEDS_SUBJECT，不猜亮／暗主体 |
| 连通域 | `cv2.findContours` + `contourArea` | 自写 BFS 标记 + 像素面积 |
| 阈值 | 同 §3 左列 | **同一套数值**（数值引自 `cc-blender-skill`） |
| 判定 | `refuse final export if hard gates fail` | 同一策略：硬门禁不过则不产出下游输入 |

**这是一次有意的"双实现"**：同一套指标定义、两套独立代码。两者结论不一致时按 `18` §5 开调查，不允许二选一。差异登记在本表，改实现必须同时改这张表。

### 5.1 参考主体掩膜：目标约束而不是明暗分类（3.46）

2026-10-01 的十张外部原件复查确认：旧 Otsu“取像素较少类”会把天空／白底当主体，漏掉暗建筑和亮色顶罩；这不是调整亮度阈值能消除的语义缺陷。该分支已从入包脚本移除。

`scripts/reference_subject_mask.py` 提供两个执行路径：
- 原件有有效透明域：复用 alpha（支持 RGBA/LA 和带 transparency 的调色板图），保留真实透明孔洞；这只说明原件已有抠图，不证明识别了目标结构。
- 不透明复杂图：声明 target、whole-subject/local-part/subject-region 范围，以 bbox、前景／背景笔划初始化 GrabCut。框内只是可能前景，不是已知主体；负笔划周围同时满足颜色相容和邻近约束的区域用来压制同色邻居／背景泄漏。只保留连接到前景种子的连通域，恢复原分辨率后仍受原框和排除区约束。

ignore 的原 RGB 在任何缩小滤波之前，先于原尺寸临时副本中用已知背景样本替代；工作尺寸求解图也保持此约束。只在缩放之后清除 ignore 不够，重采样会把未知颜色传播到外侧有效区域。原件保持不变，最终 mask 中 ignore 一律排除。这是求解器内部的替代值，不是补出的几何、不是参考真值。已知前景或背景笔划与 ignore 重叠必须报错，不能把未知像素同时声明成已知背景。

原图被缩小时，默认执行两轮原尺寸边缘细化；refine_edges=false 可单独禁用以做同提示消融。单次求解最多 4,000,000 像素：小图使用全图；较大图可使用原 bbox 加 16 像素背景上下文的 ROI，若 ROI 仍超预算或源图超过 16,000,000 像素则跳过。ROI 仅减少求解图规模，不扩大最终 bbox，也不缩小未知域。粗掩膜腐蚀后的内部和膨胀邻域外的远背景分别作为数值前／背景先验，只在粗轮廓附近 2–8 个原像素的窄带调整；原尺寸显式笔划仍优先。它不能修正连在一起的岩壁／邻屋实例归属，也不能恢复远离粗轮廓的所有遗漏细杆。

metadata.refinement 记录实际运行尺寸、原尺寸半开 ROI region_pixels、轮数、boundary_radius_pixels 和 skipped_reason。source_pixel_budget 表示源图超预算；refinement_region_pixel_budget 表示目标 ROI 超求解预算；disabled 表示显式关闭。不需缩放的图实际轮数为零。没有执行细化的图不能用合成细杆回归冒充原图细节恢复。

内部细节回补是实验选项，recover_details 默认 false；本批独立审图发现真实金饰回补同时新增水印字缘误选，因此不默认接入。显式设为 true 时，只有不与图外、ignore 或显式负种子相连的封闭孔分量，且像素接近原尺寸正笔划中心线颜色、与负颜色有分离时，才进入独立的受约束求解。该补充求解只允许添加有颜色支持的孔内像素，不改外边界；detail_recovery_enabled/status 与 seed_supported_hole_candidate_pixels/recovered_pixels 记录是否实际启用及候选／回补数。未知连通限制还会拒绝部分真实回补，这种代价必须披露，不能把新增像素或机制满足计为成功。

细杆的正笔划宽度可能超过杆身，缩放后更会混入背景色；不能把粗掩膜腐蚀后的内部一律当作正确主体。细化另以原尺寸负提示颜色和正笔划中心线颜色建模：像素到负色聚类的 RGB 均方距离不超过 4、到正中心线聚类距离大于 144，并且该颜色分量存在通往显式负笔划或框外的 8 连通路径时，才作为求解器背景约束，允许覆盖污染的粗内部先验；显式原尺寸正笔划仍优先，ignore 始终排除。必须加空间锚定：孤立的箱门或屋面实面与背景同色，不等于它就是背景。original_color_background_support_pixels 和 original_color_background_support_rule 记录此约束。它仍不会判断连续岩壁、树叶或近邻屋面的实例归属；近似同色或未涂到的真部件仍需实看，不能从合成通过推断语义可靠性。

metadata.bbox_contact 记录每个框边选中像素数和 internal_image_edge（此框边是否位于原图内部）；有内部框边接触时输出 boundary_warnings 与 requires_bbox_review=true。它只是截断或框内泄漏的疑点，不能断言主体一定完整或一定截断。先打开原图与提示核对框边，必要时更正输入后重出图；程序不自动扩框，不补画框外几何。

metadata.prompt_diagnostics 是只读诊断：逐笔划中心线／宽笔划的颜色跨度与异质性、正负笔划重叠与颜色近似、多正种子的候选连通、ignore 邻接、源图出画接触和薄部件工作分辨率支持。review_regions 给出原尺寸半开 xyxy 框、笔划编号与应核对动作；它不识别实例身份，不自动更正笔划，不改变 mask/ignore，不授予准确率。源 alpha 不启用这项复杂求解诊断。

无目标输入返回 NEEDS_SUBJECT，不产出猜测掩膜。提示与原图尺寸／哈希不符、前景笔划落在背景／ignore／框外必须报错，不得为了“有结果”回退 Otsu。缺 OpenCV 的环境仍可做基础入包和 alpha 路径，复杂分割必须明确补运行环境。

最小单图输入（x 向右、y 向下，0–1 对应原图；radius 是短边占比）：

```json
{
  "target": "指定建筑的可见立面",
  "scope": "local-part",
  "coordinate_space": "normalized_xy",
  "image_size": [1920, 1080],
  "image_sha256": "填原件文件的SHA-256",
  "bbox": [0.1, 0.15, 0.8, 0.9],
  "foreground_strokes": [{"points": [[0.35, 0.4], [0.55, 0.6]], "radius": 0.008}],
  "background_strokes": [{"points": [[0.15, 0.2], [0.7, 0.2]], "radius": 0.008}],
  "ignore_polygons": [],
  "max_side": 1280,
  "refine_edges": true,
  "recover_details": false,
  "iterations": 5
}
```

```bash
python scripts/reference_subject_mask.py --image <original.png> --subject-spec <subject.json> --out <candidate.mask.png> --out-json <candidate.json>
python scripts/reference_intake_gate.py --refs <refs_root> --subjects <subject-set.json> --out <gate_dir> --emit-masks
```

批量 subject-set 是 `{"schema":"reference-subject-spec-set/1","views":[...]}`，每个单图输入再加 `file`（相对 refs_root）及真实 image_sha256。重复 file 或错误哈希不能静默跳过。外部原件保持只读；mask、ignore、overlay、提示及报告落在独立工作目录。

掩膜产物必须使用无损 .png。mask、ignore、overlay、JSON 各自路径必须不同，并且不能覆盖原件或 subject-spec；artifacts 同时保存三种图的 SHA-256。下游绑定报告时，不能换掉或缩小对应 ignore 再继续沿用旧掩膜证据。

二值 mask 表示算法选中像素；同尺寸 ignore 白区表示未知／遮挡／不适用区域；overlay 洋红表示选中，橙色表示 ignore。标题遮挡不能补成已知几何，角色／水印不能算结构件，局部屋顶不能改称完整建筑。ignore 必须随掩膜传递；未采用相同 ignore 口径的下游不能据此计算正式几何 IoU。

对二值候选使用 compare_masks.py 的 binary-mask 模式，并传 --ref-report/--render-report 绑定对应 SHA、尺寸、scope 和 semantic_review；ignore 可由报告自动加载或显式传 --ref-ignore/--render-ignore。计算域只能是两侧非 ignore 的交集，同时保留原分母、有效域比例和不排除未知域的原始诊断读数。候选／未复核报告的主 verdict 必须 unverified；阈值另存 diagnostic_verdict。没有报告的旧调用只提供历史提取／几何诊断，不授予语义通过；零共同域、空／满幅、域内退化与宽高比不一致也不得自动放行。

可单独执行分辨率敏感性实验：

```bash
python scripts/reference_mask_stability.py --image <original.png> --subject-spec <subject.json> --out-dir <fresh_directory> --max-sides 960 1536
```

基准使用 subject 原来的 max_side；附加变体仅改变这个数值参数，target、scope、bbox、笔划、ignore 均不变。resolution-disagreement.png／青色叠图表示这些求解配置在共同有效域内不一致的位置，不是新增 ignore，也不是自动挑选最佳掩膜。报告绑定原件、提示、实现 SHA 与实际开始／结束时间；一致性高不表示分割正确，低敏感性的误选仍是误选。若图像本身小于所有 max_side，记录的是相同实际求解尺寸的控制，不得声称通过了多尺度压力测试。

退出码 0 只表示产生 CANDIDATE，不是语义验收；3 表示 NEEDS_SUBJECT／退化，2 表示输入／环境错误。实际打开叠图看漏主体、吃背景、细杆、暗部、孔洞和相邻实例；修提示或算法后重出图。coverage 只是诊断，不是准确率；图像 usable、H5/H6 在场性和连通域数也不代替这一步。

这是一条目标提示辅助的分割通道，不是无人干预语义模型。同色前／背景、连续岩体、发光材质、细杆、裁切仍可能失败；component_count_proxy 不等于已核实结构件 observed_parts。没有独立像素真值时，不报语义准确率／IoU，不从同图调提示的成功推断未见任务效果。

## 6 失败路由

| 症状 | 路由 |
|---|---|
| 视图角色缺失或冲突 | 回 `09`/`11` 补采；必要时降级为灵感收藏 |
| 可量测性不达标 | 换图；若该角色只有这一张，登记为"该角色无合格证据"（**不得**用 `iso` 顶替 `front`） |
| 结构件数对不上 | 先查计数口径（装饰件是否被算进去），再查切分阈值；连续两轮不一致 → 该视图退出部件切分链 |
| 共享轴比例矛盾 | 走 `multiview-constraint-solver` 式裁决（`18` Ⅰ-1），先出冲突报告再动手 |
| H5 同一性不成立（区域/版本对不上） | 该图降 `EXPLORATORY` 并移出 G2；回 `09`/`11` 重找**本区本版本**证据；已消费该图的结论按 `04` §8“指标好、投影源为空”处置（重采证据后重算，不得沿用旧结论） |
| H6 对象不在场 | 换帧或换图；**比例锚必须重定**（不许“将就用”）；对照板重出 |
| 参考 vs 渲染 IoU 不达标 | 走 `06` 的缺陷关闭循环；不得调参考图去迁就模型 |

## 7 产物（唯一清单）

| 文件 | 内容 | 生成者 |
|---|---|---|
| `reference_manifest.json` | 视图角色矩阵 + 每视图 `expected_parts` + 阈值 + 来源条目（含等级） | 脚本生成初稿，**人填 `expected_parts`** |
| `identity_declarations.json` | H5/H6 声明：对象×区域×版本三问 + 证据链 + 在场性与位置框（字段见 §1.2） | **人填**（`reference_intake_gate.py` 只读它，不代填） |
| `identity_report.json` / `.md` | 逐图 H5/H6 的 PASS / FAIL / UNKNOWN + 原因 + 证据解析结果 | `scripts/ref_identity_gate.py` |
| `source_analysis/<name>.json` | 每图的尺寸/mode/mask 模式/覆盖率/连通域/质心/标志点代理/可量测性 verdict | 脚本 |
| `gate_report.json` / `gate_report.md` | 逐项 PASS / FAIL / UNKNOWN + 按角色的计数 + 按等级的计数 | 脚本 |
| `overlay/<name>.mask.png` + `.ignore.png` + `.overlay.png` | 候选 mask、未知区和原图叠图；缺提示时不产生猜测 mask | 脚本（`--emit-masks`） |

运行（默认不写进被检参考包，产物落在 `--out`）：

```bash
PYTHONUTF8=1 python scripts/reference_intake_gate.py \
  --refs "<项目>/docs/refs" \
  --out  "docs/refs-gate/<subject>" \
  --source-table "<项目>/docs/refs/00-参考包与来源分级.md" \
  --emit-masks
```

退出码：`0` 全过 · `1` 有硬门禁不过 · `2` 用法/路径错误。`--strict` 时 `degraded` 也计入失败。

H5/H6 的检查在 `scripts/ref_identity_gate.py`（读同一份声明文件；只读，不写参考包）：

```bash
PYTHONUTF8=1 python scripts/ref_identity_gate.py \
  --declarations "<项目>/docs/refs-gate/<subject>/identity_declarations.json" \
  --refs-root   "<项目>/docs/refs" \
  --out         "<项目>/docs/refs-gate/<subject>"
```

退出码：`0` 无 FAIL（UNKNOWN 不拦人） · `1` 有 FAIL · `2` 用法/文件缺失。

## 8 两遍循环（怎么用）

1. **第一遍**：跑脚本 → 得到 `reference_manifest.json` → 人工按 `01` 的来源表逐视图填角色与**精确** `expected_parts`，并另附原图绑定的 `observed_parts` / `observed_parts_evidence`；不能直接复制 `component_count_proxy` 充当人工结构计数。
   命令行声明（会写进 `declaration_log`，带日期与人）：
   ```bash
   --declare "_src/render/Swamp_Hut.png:iso:1" --declared-by "<人>-<日期>-<依据>"
   ```
2. **第二遍**：再跑脚本（默认读取同名 manifest）→ 核对角色及「声明结构件数 vs 原图绑定的人工计数证据」；H3 证据缺失或计数不一致均 FAIL，即使连通域代理碰巧相等也不能通过。
   批量声明用 TSV（避免超长命令行），列：`file<TAB>role<TAB>parts<TAB>by<TAB>rule`（`#` 开头为注释）：
   ```bash
   --declare-file "<out>/declarations.tsv" --exclude "plans/prev_*" --exclude "plans/diff_*"
   ```
   `rule` 列会写进 `declaration_log`，使每条声明都能回答“为什么是这个角色”。
3. `role_declared`、`role_provenance` 与 `expected_parts` 的每一次修改都必须在 `declaration_log` 里留一行（时间、字段、旧值、新值、谁、依据规则）——**不许静默改数**。
4. **声明为 `context` 不等于通过**：H4 会单独检查主轴证据是否存在。允许用规则先把不确定的图默认为 `context`（保守、不当轴证据），但不得把 `context` 当作“已处理”。

## 9 首次实测（2026-09-23，三个现有参考包）

运行命令见 §7；受检范围 `--scope originals`（跳过 `_analyze` / `_measure_out` / `working` 等衍生物）。

| 参考包 | 受检图 | 去重后 | H1 未声明角色 | H2 reject | H2 degraded | H3 不符 | 产物 |
|---|---:|---:|---:|---:|---:|---:|---|
| `WitchHut/docs/refs`（第一遍） | 10 | 10 | 8 | 1 | 4 | 0 | `docs/refs-gate/witchhut/` |
| 同上（**第二遍**，已声明角色） | 10 | 10 | **0** | 1 | 4 | 0 | 同上（`declaration_log` 已写入） |
| `Tenshukaku/docs/refs`（`--exclude-dir map_thumb`） | 46 | 46 | 45 | 0 | 3 | 0 | `docs/refs-gate/tenshukaku/` |
| `SausageUFO/docs/refs` | 6 | 6 | 4 | 0 | 0 | 0 | `docs/refs-gate/sausageufo/` |
| `薪主test/docs/mondstadt-refs`（第一遍） | 328 | **298** | 311 | 52 | 35 | 0 | `docs/refs-gate/mondstadt/` |
| 同上（**第二遍**，规则声明 + 排 `prev_*`/`diff_*`） | 323 | **293** | **0** | 51 | 35 | 0 | 同上（`declarations.tsv`、`declaration_log` 已写入） |

`mondstadt` 的 52 个 reject 细分：`tiny` 32 · `low_contrast` 7 · `flat_wall` 6 · `near_black` 5 · `near_white` 1 · `unreadable` 1；
35 个 degraded：`low_detail` 16 · `low_res` 13 · `heavy_watermark` 6。

**实测结论（五条，均为可复算的现场结论）**

1. **五个参考包都没有合格的 `front` / `side` / `back` 正交主轴图，`top` 几乎全是 D 级。** `WitchHut` 与 `Tenshukaku` 各只有一张带 `top` 角色的图，在来源表里都是 **D 级**；`mondstadt` 的 16 张 `top` 里 8 对是同图的原图+预览（去重后 298/328），真正能用的俯视地图不到半打。这解释了为什么三条路线的层数/比例长期只能停在目视结论，而不是“团队没看图”。
2. **`Tenshukaku` 的主要短板不是画质而是角色缺失**：46 张里 43 张 `usable`（夜间实拍也过了 H2 的近黑闸），但 45 张的文件名不含视图角色词，角色只能人工声明；另有 **15 件 `_src/` 原件在来源表里没有条目**（10 件 `_src/img/` + 3 件地图瓦片 + 9 件 `_src/official/img/`）——它们现在无法指回证据 ID。
3. **`WitchHut` 的可用性受分辨率限制**：10 张里 4 张短边 127–150 px（wiki 缩略图）→ `degraded:low_res`，只能读形制/拓扑；其中 `WitchesHut.png`（127 px）直接 `reject:tiny`。
4. **`mondstadt-refs` 是体量最大、也最不工程化的一包**：323 张（去重 293）里 51 张直接不可用（`tiny` 32 张来自 Unity 导入的缩略/预览件）。第二遍用规则把 311 个未知角色降到 **0**（`context` 256 / `top` 48 / `detail` 18 / `section` 1），但 H1 清零**并不等于**证据齐了：H4 依旧 FAIL。
5. **H4 在四个包上全部 FAIL，且“缺哪一半”很清楚**：
   - `WitchHut` / `Tenshukaku` / `SausageUFO`：高度向与水平向**都缺**（`missing=['height','plan']`）。
   - `mondstadt`：唯一接近高度的 `plans/MD-02_南北剖面.png`（`section`、`usable`）**因为没有来源表条目所以没有等级**，被卡在 `grade` 一列——就差一次登记。
   - 另有 15 件 `Tenshukaku` / 293 件 `mondstadt` 原件未登记，已生成待补表（见 §10）。

**已登记的判据局限（改判据前必须读）**

1. **批内相对的边缘能量不能单独判“模糊”。** `Tenshukaku` 的官方地图瓦片边缘能量比只有 0.12–0.27，但它们不是模糊而是**平滑/矢量化画风**。因此该判据只产出 `degraded:low_detail`，**不产出 reject**；要升级成硬门禁必须先在本工程留下“同一张图的模糊副本 vs 清晰原件”对照。
2. **`reject:flat_wall` 在“白底产品图/纯色设定图”上会误伤**（前景本身就是主体）。当前未触发，但一旦有白底设定图入包，需人工复核。
3. 本次未产出任何 `--pair`（参考 vs 渲染）结果，§3 的 IoU/SSIM 阈值**仍是 `[外/文档]`，未在本工程实测**。
4. **同一图的多份副本会被当成多件证据。** Unity 导入目录里常见 `X.png` + `X_preview.jpg` + `prev_X.png`，`mondstadt-refs` 就有 328→293 的重复率。脚本已按 sha256 标 `duplicate_of` 并报 `uniqueBySha256`，但**尚未合并副本去参与 H1/H2 计数**；处理大规模包时先看去重后数字。
5. **规则声明不是人工声明**：`mondstadt` 第二遍的 311 条声明全部来自路径/文件名规则（`rule_provenance = rule:<id>`），其中 200 条是「玩家截图默认按 `context` 处理」的保守兜底。它们的作用是**把“角色未声明”与“角色已定但证据等级不足”分开**，**不能**被读成“已经看过每一张图”。

## 10 待补登记产物（本轮生成）

原始件在参考包里但来源表中没有条目的，按来源通道归类后生成两份待补表，**等级与用途两列留空给 owner**
（分级判断属于 `01`，本闸不代判）：

| 包 | 待补件数 | 文件 |
|---|---:|---|
| `mondstadt-refs` | 293 | `docs/refs-gate/mondstadt/proposed_source_table.{md,csv}` |
| `Tenshukaku/docs/refs` | 15 | `docs/refs-gate/tenshukaku/proposed_source_table.{md,csv}` |

生成器按 `plans/` / `_src/miyoushe/` / `_src/iter/03_obc/` 等路径前缀分来源通道。
补登记完成后再跑一次本闸：`mondstadt` 的 `plans/MD-02_南北剖面.png` 一旦拿到 A/B 等级，H4 的 `height` 一半即成立。

### 9.1 2026-09-29 负样本回归（H5 / H6）

受检对象：092802 批次的三条路线（`01-外滩` / `02-飞行巴士` / `03-鹤观`），**只读**，不动受试者产物。

| 用例 | 输入（真实物证） | 期望 | 实测 | 归因 |
|---|---|---|---|---|
| H5-自造图 | `03-鹤观/shots/r183_official_fog_measure.png`（被放进“参考”位的那张） | FAIL | **FAIL**（H5-2 三问无一条非自造证据；H5-5 零结果已登记但不充当通过；H6-1 占“参考”位而 `present` 未声明） | 自造测量可视化不是参考（`01` §1） |
| H5-错区 | `03-鹤观/shots/r232_tsurumi_candidate_crop.png`（“官方 2024 真鹤观”裁剪 + r232 拟合） | FAIL | **FAIL**（H5-4 落陆率 62.9% < 对照 84.2%；裁剪覆盖率 89.4% < 95%） | 区域问用独立 POI 一致性拦下；同批“官方实测”数字须重算 |
| H5-对照 | `03-鹤观/refs/orig/top_gamemap_3800x1900.png`（真·游戏内地图） | PASS | **PASS**（同一批 POI 落陆率 84.2%；覆盖率 99.2%） | 证明本闸不是“一律 FAIL” |
| H6-不在场 | `02-飞行巴士` 的 f0041/f0047/f0049（t240/276/288 s，车内镜头）作比例锚 | FAIL | **FAIL**（仅 H6-1：`usage=anchor` 而 `present` 未声明；H5 三问全过 ⇒ 单一归因） | 锚点母图必须含本体；真参考是 t330s 段（外部镜头） |
| H6-对照通过 | 同路的 f0056（t330s，含车体）+ 签核 bbox + 母图 | PASS | **PASS**（本体框 [225,60,448,189] 于 480×270，面积占比 0.222） | 证明本闸不是“一律 FAIL” |
| 角色判定 | `03-鹤观/refs/orig/iso_artwork_1021x630.png`（带注记俯视图） | 按几何判 `top` | **判 `top`**（§2 纪律 4） | 文件名 `iso_*` 只是线索 |

命令与读数归档：`documents/skill-v340-draft-20260929/regression/`（`regression_report.json` / `.md`）。
