# UrhoX 体素场景制造 · 工具说明（Tool Overview）

> **仓库**：https://github.com/Ecnahc1014-xd/urhox-voxel-replication
> **版本**：包内版本以 `VERSION` 与 `CHANGELOG.md` 为准（本文写作时 v3.50：27 篇规范 / 29 个脚本 / 13 条 evals / 6 个案例）
> **性质**：本文件是**导读与口径**，不是规范层。规范在 `references/`，唯一可执行真值在 `scripts/`。
> 本文不写胜负叙述；每条与官方文档的差异都标注来源（文件名 / 检索式 / 命中数），可独立复算；只陈述能力、证据与边界。

---

## 0 一句话定位

把"复刻得像不像"从主观感觉，变成**可复现、可审计、可回滚**的工程结论；**生产链只依赖目标引擎**（UrhoX / TapTap Maker）。

## 1 三条优势（对外口径）

### ① 不需要外部引擎——Maker 网页端即可使用

- 生产链只依赖目标引擎：主数据 → 整数格 → 引擎原生 `VoxelVolume`；不需要 UE / Unity / Blender / MagicaVoxel 应用 / AI 3D 服务。
- 产物是引擎原生件，**Web/WASM 目标可直接承载**；已有工程在 Web 预览上跑过（含 Web 回落策略）。
- 边界：工具链里的 Python 仪器跑在**主机侧**（它们是工具、不是引擎）。

### ② 支持 XDanger（S2 下游适配）

- 契约：0.1 m 体素、世界 `x/z = −75..75 m`、`y = −5..30 m`、默认模板 `bright_hard_plain_v2`、`6×6` 场景块（每块 25 m）、`world_snapshot v3`（`scenes[] / parts[] / edges[] / palette / mission`）、**三条组件路径**（个人组件 / 官方场景组件 / 官方功能组件 `craft.defs`）。
- 交付流：G0 目标卡 → G1 证据留证 → G2 目标网格归一化 → G3 语义切分与注册 → G4 紧包围盒与端口 → G5 地图快照适配 → G6 原生验证（7 项，多人须单独验收）→ G7 版本与回滚。细则见 `references/25-xdanger-adaptation.md`。
- 边界：上游只提供**可审计、可转换、可回滚**的地图源与组件源；不做玩家侧任意导入、不做发布/分享/云同步；`userdata.json` 是玩家本地存档，不是上游发布格式；没有下游 `craft.defs` 与运行时代码时，几何**不会**自动获得机械/任务能力。

### ③ 先进的验证工程

- **输入侧**：H1–H6 入包闸（视图角色 / 可量测性 / 期望部件数 / 正交基底 / 对象×区域×版本同一性 / 在场性）+ 配准防伪四条（留出法 / 独立一致性 / 零残差警示 / 裁剪完整性）。
- **产出侧**：四表 A–D（空间忠实度 / 体素工程 / 视觉语义 / 玩法物理）+ 状态语义（`EXPLORATORY` / `PASS-WATCH` / `PASS` / `BLOCKED`）+ 裁剪四段式留痕 + 失败件保留不降级。
- **反自欺**：禁止 AI 主动冻结（不写"已冻结/已完工"）；接入 `fidelity_gate.py` 时 4h 未动 = `NO-FIDELITY`；推进:收口 ≥ 2:1；证据分级（编译 / 导出 / 引擎内 / 多机位不同层级不可替代）。
- **包自检**：`scripts/skill_structure_check.py`（结构 + 路由 + 版本一致 + **引用存在性**）与 `scripts/check_crossrefs.py`（悬空指针）。
- **证明力边界**：能证"忠实 / 合规 / 自洽 / 可达 / 可复现 / 可回滚"；**不能**证"好看 / 好玩 / 有新意"。

## 2 工具是什么

| 维度 | 内容 |
|---|---|
| 适用 | 真实或设定对象 → UrhoX / TapTap Maker 体素场景：城市与聚落、街区与场地、单体建筑、室内、自然地形与水体、大型道具/载具/装置，及其混合 |
| 不适用 | 非体素化的常规 3D/美术资产生产；与场景几何无关的玩法；纯动画 |
| 引擎族 | UrhoX / TapTap Maker（米制、Y-up 左手系、Lua + PIE 烘焙） |
| 输入契约 | **复刻**（外部真值）· **设定驱动**（设定稿/brief，跑 `DESIGN_CANON`）· **改造**（已有场景 + 变更单） |

**与官方工具的分工**：网格/高度场→体素用官方 `official-Voxel-Tool`；UE 模型/地形/场景→VOX 或直接导 VoxelVolume 用官方 `UrhoXVoxelSuite`；编辑器内改 VOX 用官方体素编辑器；**"参考是否可信、坐标是否注册、像不像、能不能复现、能不能审计"归本工具**。

## 3 包体结构

| 层 | 目录 | 权限 |
|---|---|---|
| 入口 | `SKILL.md` | 路由、参数表、契约、G0–G7 阶段语义 |
| 规范层 | `references/`（27 篇） | 规范权；无执行权 |
| 执行层 | `scripts/`（29 个） | **唯一可执行真值** |
| 案例层 | `cases/` | 快照与检索价值；**不得当阈值或门禁依据** |
| 测试层 | `evals/` + `tests/` | 行为契约与回归输入 |
| 治理 / 导航 | `VERSION` · `CHANGELOG.md` · `INDEX.md` | 版本唯一权威 = CHANGELOG |

判读顺序：**项目规则文件 > 引擎文档 > `references/` > `scripts/` 实现细节 > `cases/` 快照**。

## 4 上下游与外部协作

**上游（输入侧）**：`09`/`09a`/`11` 检索与采集 · `23` 参考数据解析（CAD/BIM/PDF/位图/实测/OSM 的精度上限）· `19` 入包闸 H1–H6 · `02` 制图与唯一注册链 · `22` 特征词表 · `18` 外部技能采纳地图 · `cases/` 案例。

**下游（输出侧）**：`03` 建模语法（footprint + height band + semantic group）· `05` 引擎操作（Lua / PIE 烘焙 / 路径排错）· `04` 四表 + `10` 仪器 + `12` 通道分歧 · `16` 光照与后处理第二轴 · `21` 出图三体检 · `07` 交付与汇报 · `13` 成本口径 · `20` 环境绑定 · `24` 语义层（设计驱动模式下必开）。

**外部协作件（不在包内，同一条链上）**：官方 UE 插件包 · `official-Voxel-Tool` · 官方体素编辑器 · 引擎 `engine-docs/recipes` 与 `.emmylua` · 项目侧仪器（`shots.py` / `frame_qc.py` / `audit_phantom_check.py` / `fidelity_gate.py`）· 已隔离外部件（`tools/external/`）。

## 5 门禁一览（速查）

| 闸 | 内容 | 出处 |
|---|---|---|
| H1–H4 | 视图角色 / 可量测性 / 期望部件数 / 正交基底 | `references/19` |
| H5–H6 | 对象×区域×版本同一性 + 在场性 | `references/19` |
| 配准防伪四条 | 留出法 / 独立一致性 / 零残差警示 / 裁剪完整性 | `references/02 §4.6` |
| 四表 A–D | 空间忠实度 / 体素工程 / 视觉语义 / 玩法物理 | `references/04` |
| 设计驱动 G0–G8 | 结构合法 / 边界 / 接地 / 高度带（规则推导）/ 屋顶覆盖 / 开口归属 / 可达 / 必需项 / 语义分组 | `scripts/design_gate.py` |
| Xdanger G0–G7 | 目标卡 → 留证 → 网格归一化 → 切分注册 → 包围盒与端口 → 快照适配 → 原生验证 → 版本回滚 | `references/25` |

裁剪规则：裁的是**检查项**不是证据标准；必须留痕（`裁剪项 | 理由 | 替代检查项 | 确认人`）；无替代项最高只能 `PASS-WATCH`。

## 6 成果（历史，均带 as-of）

| 类型 | 对象 | 记录值 | as-of |
|---|---|---|---|
| 城市/聚落 | 蒙德城 | v107 全城可破坏；占用 437,501 体素（1 m）；地标足迹 IoU 0.9693；岸线误差 0.483 m | 2026-09-17 |
| 地标 | 天守阁 | R3 收口：4 层天守；24 体积自洽；10 帧像素校验全 ok | 2026-09-22 |
| 自然景观 | 鹤观岛 | A1 基准：θ254°+镜像、0.490 px/obc；四判据 0.964/0.942/7-7/同构 | 2026-09-30 |
| 建筑/道具 | 女巫小屋 · 旅行青蛙 · Y星飞碟 | 旅行青蛙 r3；Y星飞碟 R2 tag `r2r6`，fp `83127889`，8 体积，五项门禁全绿 | 2026-09-14 / 09-24 |
| 载具/机械 | 银河战舰 · 总统山 | R1 指纹 `295888/848ea5fc/968903ed/6d90ef36`（14 机位）；R3 尺度裁定（区域真×2 + 1.0 m 栅格 + 上限 1.5 M） | 2026-09-24 |
| 场景 | ValorantAirport / Icebox | r2v60：222,819 格 / 79 体积；13 回合基线零改写 + 2 个已声明 carve | 2026-10-02 |
| **设定驱动** | 青槐巷（街区）· 青槐茶馆内厅（室内） | 两案主数据 + 引擎出帧 + `design_gate` 跑通；失败件保留 | 2026-10-14 |

**流程工程成果**：五份复刻案例文档 v3（§0 可搬运抽出物 + 三层机器门禁）· 一条龙技能可用性测试（22 条踩坑台账）· v3.40 落版与交接件回写 · 0924 冷启动三项目 · 092802 三条线 + 第二条线 A–E · 092802 质量异常诊断 · 外部件采纳地图（三包 84 条）。

## 7 上手（最小集）

- 新手：`SKILL.md` → `references/00` → `references/08` → `INDEX.md §5`
- 只做取证：`09` / `09a` / `11` / `01` / `19`
- 只做建模：`03` / `08` / `05`
- 只做验收：`04` / `10` / `12`
- 出图：`21` · 迭代更像：`06` / `00 §4` / `16` · 交付 Xdanger：`25`

```bash
# 参考入包闸（H1–H4）
python scripts/reference_intake_gate.py --refs <refs_dir> --out <gate_dir> \
       --source-table <source_table.csv> --emit-masks
# 参考同一性 + 在场性（H5–H6）
python scripts/ref_identity_gate.py --declarations <gate_dir>/identity_declarations.json \
       --refs-root <refs_dir> --out <gate_dir>
# 配准防伪四条
python scripts/registration_crosscheck.py --spec <registration_spec.json> \
       --out <registration_report.json> --json-only
# 设计驱动门禁（无参考图场景）
python scripts/design_gate.py --declarations <case>/11-design_declarations.json \
       --blueprint <case>/20-blueprint.json --occupancy <case>/21-occupancy.npz \
       --map <case>/10-iso-map.json --out <case>/30-design_gate.json
# 包自检
python scripts/skill_structure_check.py && python scripts/check_crossrefs.py
```

## 8 判读边界（防误用）

- "只依托引擎"限定于**建模与运行**；验收侧**刻意**使用非引擎的独立第二实现（FreeCAD 重算体积 / OpenCV 掩膜对账），那是纪律要求的交叉验证，不是生产依赖。
- 场景几何全程体素成立；NPC / 玩家 / 天空 / 占位件仍是 mesh。
- 历史数字均为**记录值**并带 as-of 日期；跨项目复用前必须重新测量并重填参数表。
- 未跑运行时的结论一律标 `PASS-WATCH` / `UNVERIFIED`；本文不含任何"已冻结 / 已完工"表述。
- **例外范围**：角色 / 载具类精细资产不在"零外部引擎"主张内（历史上用过外部生成与 Blender 往返）。
