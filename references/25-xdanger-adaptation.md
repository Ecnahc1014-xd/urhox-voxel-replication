# Xdanger S2 下游适配

> **适用范围**：把 UrhoX/TapTap Maker 体素复刻产物交给 Xdanger S2 的固定模板地图、世界快照或可复用组件链路时使用。
>
> **证据状态**：本章依据 2026-10-12 检查到的 Xdanger 参考工程快照整理。它是下游适配契约，不是 Xdanger 产品能力的永久承诺；目标工程升级后必须重新读取实现并重跑原生验证。

## 1. 先判交付形态

Xdanger 当前不是任意外部地图文件加载器。上游 Skill 负责把资产变成可转换、可审计、可回滚的适配包；下游工程负责注册、写入创作关卡数据、运行和保存。不要把下面四条路径混成一个“导入”：

| 上游产物 | Xdanger 目标路径 | 必须补齐的适配件 |
|---|---|---|
| 连续建筑、园区或城市片区 | 世界快照的 scenes[] | 目标网格重采样、固定模板对齐、场景块边界、模板相对编辑或稀疏 cells |
| 可独立摆放的墙、地面、门窗、家具 | 官方场景组件 | .vox、图标、manifest、scene_content 注册、尺寸/连通性/哈希 |
| 小型可复用形体 | 个人组件 | assetRevision、紧包围盒、局部原点、稀疏 cells、组件类型 |
| 带端口、信号、机械或任务行为的部件 | 功能组件 | craft.defs、端口/能力、Prefab 或代理体、运行时代码、专项测试 |

如果需求只是“把外部文件直接拖进 Xdanger”“发布到所有玩家”“分享/云同步”，本章应直接标记为 BLOCKED：当前上游交付包不具备这些能力。

## 2. Xdanger 世界契约

### 2.1 米制与边界

目标世界使用 0.1m 体素，采用整数网格和半开区间：

- 世界范围：x/z ∈ [-75, 75)，y ∈ [-5, 30) 米。
- 逻辑尺寸：1500 × 350 × 1500 格。
- WorldToGrid、GridToWorldMin 使用整数格；边界外坐标必须显式失败，不能静默夹回。
- 0.1 不能被二进制浮点精确表示；设计值先在米制主数据中保存，再用统一量化和格线容差转换，禁止在多个脚本各自四舍五入。
- 基础硬质地面覆盖世界 y < 0 的隐式区域；对应网格索引是 y=0，不是 50 米高度。

如果来源工程使用 0.125m、0.25m 或其他边长，不能只改 metadata。必须按世界米坐标重采样到 0.1m，并保留：源/目标体素边长、注册变换、占用差异、源哈希和目标哈希。

### 2.2 模板与场景块

- 默认模板是 bright_hard_plain_v2，兼容旧模板 bright_hard_plain_v1。
- 默认水平场景块为 6 × 6，每块 25m，共 36 块，覆盖 150m × 150m 世界平面。
- world_spec 中的 CHUNK_SIZE = 32 是探针/暂定数据值，不得当成最终渲染或物理场景块尺寸。
- 模板基础地面由下游重建；快照只保存相对模板的编辑，除非目标工程明确要求完整稀疏体素。

场景块的 origin、rotation、dimX/Y/Z 和 voxelSize 必须来自同一次目标网格转换。不能先按一个原点切块，再在注册表里用另一个原点补偿。

## 3. 世界快照适配

当前实现的世界快照版本为 3，可规范化读取版本 1 和 2。上游适配包应显式声明 snapshot_version，但不要直接伪造玩家本地 userdata.json。

顶层结构至少包括：

    {
      "version": 3,
      "scenes": [],
      "parts": [],
      "edges": [],
      "palette": {},
      "mission": {}
    }

### 3.1 scenes[]

每个场景条目至少记录 id、label、dimX/Y/Z、voxelSize、origin、rotation 和二选一的内容来源：

- 模板模式：填写 sceneTemplate，把用户编辑放入 edits；不要把模板基础地面再烘焙成一份无法区分的用户内容。
- 稀疏模式：填写非空 cells[]，每格带 x/y/z/material；仍需保留 edits，让增删和材质变化可追溯。

姿态数组按实现约定编码：位置为三元组，四元数为 [w, x, y, z]。场景块缺少体积、网格或可解码姿态时，适配必须失败，不得生成“看起来能加载”的半包。

### 3.2 parts[] 与 edges[]

parts[] 保存 instanceId、itemId、yaw/pitch/roll、center、rotation 和实例 settings。非个人组件的 itemId 必须能在下游目录解析；未注册组件应在静态阶段拒收。个人组件实例还要嵌入 personalSnapshot，保证模板被删除或改版后已有实例仍能还原。

edges[] 保存组件连接的 fromId、toId、端口、connectionKind、edgeType、jointType、占用端口和必要 metadata。只有形状没有端口/连接定义的部件不能被包装成功能组件。

创作关卡是玩家本地数据的一部分：当前实现最多 3 个命名槽位，快照写入 userdata.json 的 creativeLevels 节。这个文件是运行时存档，不是上游发布格式。

## 4. 三类组件的最小契约

### 4.1 个人组件

个人组件走局部体素快照，不承载任意运行时能力：

- assetRevision = 1，voxelSize = 0.1。
- dimensions.x/y/z 必须是正整数，cells[] 必须非空。
- 每格坐标必须是整数、位于尺寸内、不可重复，并带数值 material。
- 先校验，再裁剪：先拒绝越界和重复格，校验通过后才按占用格裁成紧包围盒。
- 局部原点固定在占用包围盒最小角；草稿世界旋转不写入模板，实例姿态另存。
- 组件类型仅使用 physical、mission_item、evacuation；任务端口由下游追加。
- 名称最多 24 个 UTF-8 字符，空名和同名拒收。

个人组件的 capabilities、ports 和自定义物理不能靠上游字段“声明出来”。需要这些能力时，改走功能组件。

### 4.2 官方场景组件

静态场景组件通常由 .vox、图标和 manifest 组成，并由 scene_content 注册。最小登记应同时给出：

- 稳定 id、family/variant 或场景分类；
- voxel_size_m、引擎尺寸、物理尺寸、体素数、连通分量；
- .vox 和 icon 输出路径；
- 源文件/产物哈希、生成器版本和注册 revision。

运行时定义通常包含 sceneProp = true、sceneAsset = true、freeSurface = false、rotationStep = 90 等下游字段；这些字段必须由目标工程实际注册代码确认，不能只凭 manifest 推断。

### 4.3 功能组件

机械、信号、任务和交互部件不属于“带颜色的个人组件”。除几何外，还必须交付端口方向与位置、连接种类、能力列表、Prefab/代理体、碰撞或物理策略、运行时代码和专项测试。静态 manifest 通过不等于功能可用。

## 5. 推荐适配回路

1. 登记目标契约：写 downstream_contract = "xdanger-s2"、目标模板、目标体素边长、世界边界、快照版本和注册 revision。
2. 米制重采样：由世界米坐标统一转换到 0.1m 整数格；记录源/目标占用、裁剪、材质和哈希差异。
3. 选下游路径：连续场景走 scenes[]；静态模块走官方场景组件；小型独立形体走个人组件；有行为的部件走功能组件。
4. 生成交接包：至少包含 manifest、主数据、目标输出、哈希、转换报告、未支持声明和回滚信息。
5. 静态核对：检查边界、网格整数性、模板/场景块、尺寸、空体素、重复格、组件注册、端口和 manifest 互相一致。
6. 原生运行回归：在目标 Xdanger 工程中做加载、摆放、旋转/连接、碰撞/任务（适用时）、保存、退出、重载；记录场景、动作、预期、观察、日志和帧。
7. 分级结论：静态检查只能给 PACKAGE_PASS 或 PASS-WATCH；只有目标工程原生运行和保存/重载证据齐全，才能声明对应通道可用。

## 6. 交接 manifest 最小字段

建议使用以下字段，字段名可由项目适配器扩展，但不得删掉来源和证据绑定：

    {
      "downstream_contract": "xdanger-s2",
      "source_revision": "...",
      "normalized_revision": "...",
      "snapshot_version": 3,
      "voxel_size_m": 0.1,
      "template_id": "bright_hard_plain_v2",
      "world_bounds_m": {"x": [-75, 75], "y": [-5, 30], "z": [-75, 75]},
      "registration": {"origin": [0, 0, 0], "rotation": [1, 0, 0, 0]},
      "outputs": [],
      "hashes": {},
      "runtime_evidence": [],
      "unsupported_claims": []
    }

runtime_evidence 为空时，必须把“未跑 Xdanger 原生运行/保存回载”写入 unsupported_claims，不能用离线截图、Lua 静态解析或 manifest 哈希替代。

## 7. 必须拒收的伪通过

- 只把 0.125m/0.25m 改成 0.1m 的 metadata-only 转换；
- 把 CHUNK_SIZE = 32 当作 Xdanger 的最终 25m 场景块；
- 把完整模板地面重复写进用户编辑，导致基础地面和用户内容不可区分；
- 个人组件先裁剪再校验，从而把越界格“裁”成合法；
- manifest、组件目录和 .vox/icon 路径或哈希不一致；
- 只注册形状，不注册行为端口、Prefab、任务或运行时代码；
- 直接修改或伪造 userdata.json，然后把它称为可发布上游包；
- 只做静态检查就声称 Xdanger 中可见、可碰撞、可保存或可多人使用。

## 8. 证据出处与维护

本章的实现锚点是目标工程中的以下契约模块：voxel_build.world_spec、voxel_build.default_world、app.world_snapshot、app.creative_levels、craft.personal_component、craft.scene_content、craft.defs 以及对应的 UGC/Indoor manifest。目标工程升级后，应重新检查这些模块的版本、边界、字段和运行路径；本 Skill 不复制它们的代码，也不把本地参考工程打包进公共仓库。

与通用流程的关系：网格/注册遵循 references/02，运行时证据遵循 references/05 与 references/12，交接清单遵循 references/07，环境漂移遵循 references/20。本章只定义 Xdanger 适配层的专属边界。

