# UrhoX 原生体素能力：选什么、怎么开、开了验什么

本文件是**引擎原生能力的唯一索引**，回答"这轮该开哪些原生能力、开了要付什么代价、开启后必须新增哪条验收"。

分工（避免双出处）：

- `05-urhox-operations.md`：怎么在引擎里干活（运行模式、目录、生命周期、烘焙、排错）。
- `14-cross-engine-methodology.md`：换引擎的方法学与对照分析刻度。
- **本文件：原生能力的语义、默认值、平台差异、采纳判据与配套门禁。**

能力清单来自引擎自带的 Lua 签名（`.emmylua/Voxel*.d.lua`，头部注明 `Auto-generated from VoxelPhysics/…`）与配方文档（`engine-docs/recipes/voxel-physics.md`）。**签名以 `.emmylua/` 为准，语义以 recipe 为准**；两者冲突时以签名 + 实测为准，并在此登记。

## 0. 使用纪律（三条，违反任何一条结论作废）

1. **默认值不是能力上限**：多数开关是**运行时标记、不随场景序列化**（LOD、流式、DDA、阴影体）。所以在编辑器里"看起来开了"不代表交付时开着，交付前必须由脚本显式设定。
2. **平台差异是默认值差异**：同一开关在桌面与移动端默认可能不同（DDA 已确认反例）。任何画质/性能结论必须写平台。
3. **每开一项都要配一条验收**：第 4 节给出对照表。没有对应门禁的能力**不得**在交付物里开启后不做验证。

## 1. 能力总表

### 1.1 规模与性能

| 能力 | 入口 | 语义要点（据签名注释） | 默认 / 平台 | 采纳判据 | 开启后必须验 |
|---|---|---|---|---|---|
| 网格 LOD 环 | `world:SetMeshLodDistance(m)` | 第一个环边界距离（米），之后每环 ×2（L1=2×、L2=4×），上限由引擎常量 `VOXEL_MAX_MESH_LOD` 决定（Lua 侧未导出该值）；**0 = 关闭**，是"怀疑 LOD 伪影"时的排查杠杆；环切换走异步 build-before-teardown，跨边界不会出现空窗 | 默认 100 | 对象有远距离观察位（机位距离 > 环边界）且体素数成为瓶颈 | 逐级渲染含 **1 / 2 / 4 体素凹坑**的测试件，登记"多少体素以下的构件在哪一级消失"；与 `04` 表 B 的"最小组件可辨识"对齐 |
| LOD 级只读探针 | `volume:GetMeshLodLevel()` | 级别 L 覆盖 2^L 体素单元，每轴 32·2^L 一组（整 256³ 体积在 L3 是单组）；**每体积统一级**（体积内混级会在内部边界开缝，跨体积空洞由 any-solid dilation 兜住） | — | 需要在验收里断言"这一级是几" | 断言必须用只读 API，不得用脚本推算 |
| 网格流式 | `world:SetMeshStreamingEnabled(b)` / `SetMeshStreamingDistance(m)` / `SetMeshStreamingReferencePosition(p)` / `ClearMeshStreamingReferencePosition()` | 渲染网格是 grid 的**可丢弃缓存**：远处丢 GPU mesh、回来异步重建；关闭则全部常驻。伤害重网格**两种情况都是异步** | 默认开 | 世界级 / 远景体积数量多 | `GetPendingMeshJobCount() == 0` 才是"这一代几何已经在画面里" |
| 收敛判据 | `world:GetPendingMeshJobCount()` | 已提交未落地的后台网格 job 数。**"volume 不脏"不等于表面是当前的**（脏标记在提交时就清了）——这是收敛的另一半 | — | 任何"取帧做证据"的场合 | 取帧前必须归零，否则帧可能仍是上一代 |
| 屏幕裁剪 | `world:SetMeshScreenCullSize(px)` | 世界包围盒**竖向投影**小于该像素数就整体流出（此尺度下已是亚像素噪声）。需要真相机做像素换算；**无相机时该裁剪惰性**（无头管线不生效） | 默认 4 px | 远景大量小体积 | 无头取帧时明确记录"该裁剪未生效"，不得据此断言"远处已裁掉" |
| 局部脏区 | `volume:MarkRegionDirty(x0,y0,z0,x1,y1,z1)` | 只重建受影响区域；注释原话是"**这就是让一次爆破不去重网格整栋楼的东西**" | — | 任何局部编辑 | 与"整体 `MarkGeometryDirty`"对照，登记顶点数变化（`GetVertexCount`） |
| 顶点数（诚实内存口径） | `volume:GetVertexCount()` | 当前表面网格顶点数；**LOD 过渡期同时统计新旧两张表**（旧级仍在屏上 + 新级在构建），因为它要反映真实显存占用 | — | 内存核算、LOD 切换断言 | 过渡期读数不得当作稳态读数 |
| DDA 渲染 | `world:SetDdaRenderingEnabled(b)` / `IsDdaRenderingEnabled()` | World 调色板体积在**渲染路径含 deferredvox** 时走 DDA；渲染路径见 `CoreData/Techniques/PBR/PBRVoxelDda*.xml`（另有 `Sparse4` 变体与 `*Inside` 机内变体） | **桌面默认开、移动默认关** | 桌面目标 + 大量静态体积 | 桌面/移动两套分别留证；不得把桌面表现外推 |
| DDA 驻留源 | `world:SetDdaResidencySourcePosition(id, pos)` / `RemoveDdaResidencySource(id)` / `ClearDdaResidencySources()` | 场景级**次级**驻留源，与主 pin/相机源取并集；ID 用正整数（≤2^53） | — | 固定机位验收 / 预载特定区域 | `GetDdaStatsString()` 留基线（atlas/upload/job） |
| DDA 遥测 | `world:GetDdaStatsString()` | 稳定的 `key=value` 形式；**查询本身不创建 atlas/table 资源**，适合做确定性基线 fixture | — | 任何 DDA 相关的回归 | 两次同输入取同样字符串（确定性） |
| 派生渲染开关 | `world:SetDerivedRenderingEnabled(b)` | 专用服务器关派生渲染（联网时引擎也会自动关） | 开 | 专用服务器构建 | 服务器构建里断言为关 |

### 1.2 观感

| 能力 | 入口 | 语义要点 | 默认 / 平台 | 采纳判据 | 开启后必须验 |
|---|---|---|---|---|---|
| 体素阴影体 | `world:InitializeShadowVolume(boundsMin, boundsMax, texelSize)` / `InitializeShadowVolumeFromCurrentVolumes()` / `ShutdownShadowVolume()` / `IsShadowVolumeEnabled()` | Teardown 风格固定世界空间阴影体；**texelSize 通常取 2×voxelSize**（1 texel ≈ 2×2×2 子体素） | **默认关闭** | 需要体素级正确阴影 | 阴影体边界必须覆盖全部被摄体积，否则边界外阴影错误——边界外区域要单独留证 |
| 阴影查询档位 | `world:SetShadowVolumeQuery(VOXEL_SHADOW_QUERY_ACCURATE / _SPARSE / _SUPER_SPARSE)` | 完整占用层级 / 默认光照路径的稀疏层级 / 最便宜的带状环境阴影近似；**下一帧生效** | SPARSE（默认） | 按画质/性能预算选 | 三档各出一帧对照（同一机位），登记差异；**换档后必须重新取帧**，不得沿用旧帧 |
| 阴影抖动 | `world:SetShadowVolumeJitter(0..1)` | 0 = 无切向随机抖动；1 = 完整 Teardown `jitterPosition`（默认）；系统性光/法线偏置始终开启 | 1 | 需要确定性时 | 需要**逐像素可复现**的验收帧必须关抖动（=0），否则同输入不同像素 |
| 断面色 | `world:SetPaletteCutColor(index, color[, domain])` | 新暴露剖面渲染用的颜色（走"内部体素"位）。**未设置时默认取 albedo×0.6**（截面读起来比外皮暗，Teardown 默认语义）。设置后剖面成为独立材质（深树皮包浅木、砖外包灰浆） | 未设置=albedo×0.6 | 有挖掘/破坏/剖面展示 | 挖开后必须能区分"外皮/剖面"两类像素；这是"剖面语义"的门禁 |
| 内部体素判据 | `VoxelGrid:IsFaceExposed(x,y,z,face)` | 暴露面判定；内部体素 = 六邻居全实心 | — | 需要脚本侧判断剖面/暴露 | 不得用渲染结果反推暴露性（渲染会受 LOD/DDA 影响） |
| 调色板分库 | `world:SetPaletteEntry(index, color, hardness[, debrisStyle][, domain])`、`index = bank*256 + slot`、`GetPaletteBankCount()` | 全局索引；**写到超出当前库数会按需分配库**（上限 `MAX_PALETTE_BANKS`）；0–255 恒为 scene-wide bank 0（旧脚本兼容）；**体积的库在烘焙时选定** | 1 库 | 场景总色数 > 255 | `GetPaletteBankCount()` 与素材实际用色对账；库数不得无界增长 |
| 调色板纹理 / 材质 | `world:GetPaletteTexture([domain])`、`world:GetPaletteMaterial([bank][, domain])` | 图集固定 256×(库数×4)：每库 4 行 = albedo / PBR / 自发光 / 断面色。**材质自动默认本世界的调色板材质**；直接取缓存的通用调色板材质会渲成白色 | — | 任何体素渲染 | 断言 `volume.material` 不是通用缓存材质 |
| UGC 着色 | `material:SetSurfaceTexture("<sampler>", world:GetPaletteTexture())` | 自定义 SurfaceShader 的挂钩；**非 0 库体积必须把采样行偏移 `GetPaletteBank()*4`**；原始槽位索引归着色器代码生成所有 | — | 需要特殊外观（全息/水/发光） | 分库体积的外观必须单独验（偏移漏了会串库） |
| PBR 层 | `world:SetPaletteEntryPBR`、`GetPaletteRoughness/Metallic/Specular/Emissive` | 逐槽位 PBR 属性，随图集同传 | — | 需要材质分区观感 | 与参考图的材质分区一致性（`04` 表 C） |

### 1.3 物理与碰撞

| 能力 | 入口 | 语义要点 | 默认 / 平台 | 采纳判据 | 开启后必须验 |
|---|---|---|---|---|---|
| 解析碰撞代理 | `volume:SetCollisionBox/Sphere/Capsule/Cylinder(...)`、`SetCollisionCylinderAuto(localAxis)`、`SetCollisionShapeAuto()` | **尺寸参数是完整尺寸**（非半尺寸/半径）；`localOffset` 相对体素 occupied bounds 中心。代理**只改物理形状**，不复制也不替换渲染/破坏用的体素网格。涂色不会让它失效；**任何增删体素或拓扑分裂自动回退 Auto** | Auto | 轮胎/保险杠等规则零件 | 回退行为必须验：破坏后断言 `GetCollisionShapeType()` 已回 Auto，避免"看不见的碰撞体" |
| 碰撞分组 | `collisionLayer / collisionMask / collisionGroup` | 相同非零 group 的独立刚体互不碰撞（约束抖散架的解法之一） | — | 多体机械 | 断言机器内部不互撞、对外仍碰撞（两侧都要测） |
| 两套物理互斥 | `VoxelPhysicsWorld` vs Bullet `PhysicsWorld` | **两套互不碰撞的世界**，只共享渲染 Scene；体素体积不与 RigidBody 碰撞。一个 Scene 只能创建其中之一 | — | 选型 | 不得把两套结果混着解释；混用时必须写明"哪些物体归哪套" |
| 水面与浮力 | `world.waterEnabled / waterLevel / SetWaterDrag`、`volume.buoyancy / SetComOffset` | 全局水平面；动态体积在水下按 `1000/density` 得浮力，或用显式 `buoyancy` 覆盖（0=自动）。画面上的水面由自己画（`recipes/surface-shader.md`） | 关 | 涉水对象 | 浮力与"视觉水面"高度必须一致；破舱进水需监听 `VoxelDamaged` 调低 buoyancy |
| 接触事件 | `world:SetContactEventThreshold(x)` + `VoxelContact` | **默认 0 = 关闭**，不设阈值就没有事件 | 关 | 需要碰撞反馈（脚步声、火花） | 设阈值后必须验事件确实触发（默认关是常见哑火原因） |

### 1.4 破坏与建造

| 能力 | 入口 | 语义要点 | 默认 | 采纳判据 | 开启后必须验 |
|---|---|---|---|---|---|
| 点位伤害 | `ApplyDamage(volume, center, radius, power[, scorch][, onlyMaterial])` | 移除体素后**重新检查连通性**；非零 scorch 会给外面幸存壳涂烧痕 | — | 射击/挖掘 | 连通性副作用（承重件是否会掉）必须单测 |
| 世界点伤害 | `ApplyDamageAtWorldPoint(center, radius, ...)` | 广播给胶囊/球可达的**每个体积** | — | 通用挖掘 | 误伤非目标体积（地形/道路）—— 用 `destructible=false` 防 |
| 形状伤害 | `ApplyDamageCapsule` / `ApplyDamageBox` / `ApplyDamageCone` | 胶囊=锯切；**薄 box = 平面切**；锥=定向爆破 | — | 机关、切割、爆破 | 薄 box 的平面切要给"切面是否用断面色"留证 |
| 建造（对偶） | `ApplyFillAtWorldPoint(center, radius, material)` | 只填空体素，**不动已有实体（含其材质）**；动态体积重建代理与质量；**不会新建体积**（空区补不了） | — | 补石/封堵 | 空区必须报错或走建体积路径，不得静默无操作 |
| 碎块预算三件套 | `SetMinFragmentVoxels` / `SetMaxFrozenFragments` / `SetMaxSpallChunks` / `SetSpallChunkVoxels` / `SetSpallSpeed` / `SetDebrisMaxAge` | 小于 `minFragmentVoxels` 的连通块**直接删除**而非释放成碎块；`debrisMaxAge=0`（默认）关闭老化，**只有可淘汰碎块会老化，结构永不过期** | 按平台给 | 移动端从小值起步 | 峰值碎块数与帧时不超预算；`minDamageableVoxels` 以下的体素是"惰性鹅卵石"（刻意） |
| 应力断裂 | `SetStressBreakFactor(f)` | 伤害后"几乎被切断"的结构会在**最弱水平层**折断，而不是永远挂在细条上 | 0/关 | 结构破坏真实感 | 断裂阈值要给负样本（过小=自己塌，过大=不塌） |
| 损伤噪声 | `SetDamageNoise(a)` | 0（默认）关闭；细体素把形状逼近得太精确时孔洞像机加工，噪声恢复"砸出来"的边缘 | 0 | 观感 | 噪声量必须记入参数表（影响逐像素可复现） |
| 材质门槛 | `SetPaletteEntry(index, color, hardness, debrisStyle)` | `power < hardness` **完全免疫**（刻意语义，不是 bug） | — | 材质分区 | 硬度表必须与"哪些材质可挖"的玩法声明一致 |
| 可破坏/可淘汰/可碰撞 | `volume.destructible / evictable / collidable` | `destructible=false` 免疫伤害（地形/道路防误挖）；`evictable` 控制碎块预算能否删它；`collidable=false` **只渲染不碰撞**（如载具视觉轮，避免挂在悬挂锚点上） | 按类型 | 混合场景 | 三者是**独立**策略，不能用一个开关代三个 |

### 1.5 玩法层（对象含动态体时才用）

| 能力 | 入口 | 语义要点 | 采纳判据 |
|---|---|---|---|
| 装配体 | `world:CreateAssembly(rootVolume)`、`AddVolume/RemoveVolume/SetRootVolume/Dissolve`、`SetMemberBreakThreshold(volume, breakForce, breakTorque)`、`GetMemberStress(volume)` | 多体积作为一个刚体运动；成员可设断裂阈值与应力遥测；连接断裂由引擎滞回处理 | 整机构（风车、吊桥、机器） |
| 约束 | `VoxelConstraint`：Hinge/Slider、Motor/Servo/LinearSpring、角/线限位、反力遥测、`SetDisableCollision` | 铰链相对轴优先于 `SetDirectionalAngularDamping`；**角度接口用 degree / degree/s，刚体角速度用 rad/s**（单位刻意不一致） | 门、吊桥、旋转臂 |
| 悬挂载具 | `VoxelVehicle`：`AddWheel`、`SetInput`、`SetMaxDriveForce/SteerAngle/Speed/Grip`、`SetSkidSteer`、`GetWheelCompression/IsWheelGrounded/GetWheelContactPoint` | 射线悬挂；停车用手刹（`SetInput(0,0,1)`） | 载具 |
| 实体组装轮 | `VoxelRollingContact`：纵横抓地曲线、胎侧摩擦、滚阻、支撑统计 | 非射线悬挂的轮子（组装式） | 需要真实轮地接触 |
| 角色 | `VoxelCharacterController` 或 `world:CreateCharacter/MoveCharacter` | **位置是脚底**；跳跃走 `MoveCharacter` 的 `jumpSpeed` 参数，不是给 `vel.y` | 有玩家 |
| 抓取 | `BeginGrab/UpdateGrab/EndGrab/GetGrabbedVolume` | 求解器抓取（门、抽屉、搬箱） | 交互玩法 |

### 1.6 测量与验收（这些是"引擎免费给的仪器"，不要自己造）

| 仪器 | 入口 | 用途 |
|---|---|---|
| 纯 CPU 网格射线 | `world:RaycastGridSingle(ray, maxDist[, layerMask][, ignoreVolume])` / `RaycastGrid` | **不依赖 Drawable/Jolt/渲染**，专用服务器也能用；返回 `voxel / material / volumeId` |
| 物理射线 | `RaycastSingle` / `Raycast` / `SphereCast` | 走 Jolt body |
| 材质查询 | `world:GetMaterialAtWorldPoint(pos)` | 空或越界返回 **-1**；用于"先侦察再决策" |
| 占用计数 | `VoxelGrid:GetSolidCount()`、`IsSolid/GetVoxelMaterial` | 占用对账（`10` I-01）的分子 |
| 顶点数 | `volume:GetVertexCount()` | 网格规模与 LOD 过渡口径 |
| 生命周期谓词 | `volume.static / tumbling / reSettling`、`IsContentReady()`、`IsRemoteReplica()` | 断言"这一刻它处于什么状态" |
| 事件 | `VoxelContact / VoxelDamaged / VoxelSevered / VoxelFragmentFrozen / VoxelAssembly*` | 玩法与审计 |

### 1.7 光照与后处理（引擎侧入口；方法论、三通道纪律与外观刻度见 `16-lighting-and-postprocess-fidelity.md`）

本节只回答“引擎有哪些旋钮、默认什么、开了要验什么”；**“怎么用它鉴定保真”不在本节**。

| 能力 | 入口 | 语义要点 | 默认 / 平台 | 采纳判据 | 开启后必须验 |
|---|---|---|---|---|---|
| LightGroup 预设（大气+主光打包） | `cache:GetResource("XMLFile", "LightGroup/<preset>.xml")` + 节点 `LoadXML` | 内含 **Zone（priority = −1）+ 方向光**；IBL、SH、Bloom、雾一次性配好。**不要另外再建 Zone** | 无（项目自带副本） | 任何需要太阳/大气的场景 | 场景中**只有一个生效 Zone**；契约哈希入档 |
| 自定义 Zone（覆盖雾/环境光/后期） | `CreateComponent("Zone")` + `zone.priority` | priority 大于 −1 即接管；多 Zone 重叠时数大者赢 | priority = 0（**会自动赢过 LightGroup 的 −1**） | 需要非预设的雾/后期 | 记录 priority 与“接管了什么”；按 `16` §6 做字段快照 |
| 环境光模式 | `zone.ambientSource`（PREBAKED / SKYBOX / COLOR）、`zone.sourceTexture`、`zone.ambientColor` | **默认模式下 `ambientColor` 是 no-op**（引擎硬下发 0）；SH 球谐与环境 cubemap 未暴露给 Lua | PREBAKED/SKYBOX | 需要可控环境光或重烘 | 换模式后**重立像素基线**；`sourceTexture` 烘焙是后台任务，需等完成 |
| 雾（深度 / 高度） | `zone.fogColor/fogStart/fogEnd/fogDensity`、`heightFog/fogHeight/fogHeightScale`、`skyFogIntensity` | 两种可同时开；`fogDensity=0` 等价关闭深度雾；`<1` 稀薄 `>1` 浓厚，不影响高度雾 | LightGroup 预设已配 | 需要距离感/大气 | 距离—对比度衰减曲线入证（`16` §3.1） |
| 体积雾 / 上帝光 | Zone 的 `volumetricFog*` 一组 | 与 LightGroup 一同打包；**float 属性只能走 XML** | 由 LightGroup 决定 | 需要光朿 | 同上；**不得当“光照对”的证据** |
| 主光 / 点光 / 追光 | `Light` 全套：色温、`usePhysicalValues`、面积光尺寸、遮光板角/长、内外锥角、衰减距离、ramp/shape 贴图、阴影（分辨率/bias/级联/焦点/强度/nearFarRatio/maxExtrusion） | **LightGroup 只管太阳；点光与追光必须自建** | — | 室内、火把、车灯、霓虹 | 完整光源清单入契约（`16` §2） |
| 后处理（全部挂在 Zone） | tonemap（模式/LUT）、bloom（两套参数）、SSAO、SSGI、SSR、motion blur、FXAA、vignette、auto exposure、全屏高斯模糊、toon 着色 | 字段清单以 `Zone.d.lua` 为准（比文档列的常用子集多得多） | 多数 OFF | 需要氛围 | 开关快照哈希；**验收先关后效跑一遍，再开后效出片** |
| RenderPath 冻结/启停 | `RenderPath:Load/Append/SetEnabled(tag)/ToggleEnabled(tag)/IsEnabled(tag)/AddCommand/RemoveCommands(tag)/SetShaderParameter` | 后效可按 **tag** 整组启停；这是“关后效验收”与“逐像素基线绑定”的抓手 | 项目默认 | 任何要出无后效通道的场合 | 资源名 + 哈希 + **启用 tag 集合**入契约 |
| 无光照通道材质 | `Techniques/NoTextureUnlit.xml`、`NoTextureVCol.xml`、`DiffUnlit.xml` | 几何证据的唯一合法采集通道 | — | **每个机位都要出 A 通道** | 断言 A 通道确实无光照（与成片应有可辨的明暗差） |
| float 属性的设置通道 | 只能经 **XML 反序列化**；Lua 的 Variant 是 double，`SetAttribute` 对 float 属性会被拒 | 所以“改光照/雾参数”= 改主数据文件，不是运行时调参 | — | 任何光照/雾参数调整 | 自带一份 LightGroup XML 并版本化（哈希入档） |

> 一句话记法：**光照与大气是主数据文件，不是运行时参数；后处理是机位级比较契约。** 改变它应生成新版本并重跑受影响机位，不得把旧版本写成“以后不可改”。

## 2. 摄取：优先用引擎自带的转换管线

| 路径 | 何时用 | 关键约束 |
|---|---|---|
| 手建 `VoxelGrid` | 参数化生成、程序化布局 | 越界行为**未文档化**：声明尺寸必须 ≥ 几何（见 `10` I-02） |
| `.vox` 导入 | 外部体素美术 | MagicaVoxel 格式，**索引 0 = 空**；单库 ≤255 槽；导入时**自动认领空槽位**——所以 `SetPaletteEntry` 必须**先做完再导入**；`.vox` 属**启动前预加载**（不能走懒加载） |
| 官方体素工具包（**首选**） | 三角网格 / 高度场 → 体素 | `<PROJECT>/.cache/packages/official-Voxel-Tool/<ver>/scripts/`，分工：`VoxelConvert/`（`Convert` 主流程、`Occupancy` 占据判定、`TriAccel` 保守三角形加速、`Grid` 网格与对称/膨胀/粗化、`Landscape` 高度场、`StrictInput` 输入校验、`VoxIO`/`VoxWrite` 读写、`VoxelMesh`、`Material`/`MaterialSemantics`/`ColorSpace`）、`FbxExport/`（`MeshRead`/`Json`/`MaterialDump`） |
| 高度场 / DEM | 地形、岸线 | 列数据 + top/crust/dirt 分层；建筑轮廓需另接注册链 |

判据：**能走官方包就不要自写**——官方实现已含保守加速（不漏格）、薄构件壳化、内部挖空（与"内部体素/断面色"语义同构）、按面朝向 UV 上色。

## 3. 采纳决策树

| 对象/场景 | 必开 | 建议开 | 不要开 |
|---|---|---|---|
| 静态单体建筑（中近景） | **A 无光照通道**、局部脏区、解析代理（若需碰撞）、断面色（若可挖） | LOD（若有远景机位）、体素阴影体 | 流式（体积少）、DDA 驻留源 |
| 城市/街区（大范围） | **A 无光照通道**、流式 + 收敛判据、屏幕裁剪、LOD 环 | DDA 通道（桌面）、DDA 驻留源、体素阴影体、雾（远近感） | 一次大半径伤害、体积雾（大范围成本高，除非就是要它） |
| 地形与水体 | **A 无光照通道**、高度场摄取、`waterEnabled/Level`、`destructible=false` | 雾 + 环境光模式（大气是地形的一半观感）、浮力显式覆盖、LOD | 依赖 `ambientColor` 调环境光（默认模式 no-op） |
| 室内 | **A 无光照通道**、自建点光/追光、局部脏区、断面色、可碰撞策略 | 解析代理、SSAO | DDA 驻留、LOD、体积雾（室内除了光朿几乎无意义） |
| 道具/载具 | **A 无光照通道**、动态体积 + 解析代理 + 碰撞分组 | 装配体/约束/载具/实体轮、光源清单（车灯） | 静态 LOD |
| 可破坏玩法 | **A 无光照通道**、破坏族 + 碎块预算 + 应力断裂 + 连通性 | 损伤噪声、烧痕材质、断面色 | —— |
| 多人 | 服务器权威语义、色板域（Replicated/Local）、Ready 契约 | 服务器关派生渲染、**后处理只归客户端表现** | 把后效参数当玩法同步内容 |

> “A 无光照通道”在所有行都是必开，因为它不是风格选择，而是**几何证据的合法性前提**（`16` §1）。

## 4. 开启后必须新增的验证项

| 能力 | 新增门禁 | 判据 | 这条能拦住什么（负样本） |
|---|---|---|---|
| 网格 LOD | 消失阈值登记 | 1/2/4 体素凹坑在 L1/L2/L3 的可见性写进参数表 | "远看一致"的空口断言 |
| 流式 | 收敛判据 | 取帧前 `GetPendingMeshJobCount()==0` | 取到上一代几何当成这一代 |
| 屏幕裁剪 | 生效条件声明 | 无头/无相机时记录"未生效" | 无头验收里假装远处已裁 |
| DDA | 双平台留证 | 桌面与移动各一组帧 | 把桌面默认当全平台默认 |
| 阴影体 | 边界覆盖 | 阴影体 bounds 覆盖全部被摄体积并留边界外对照 | 边界外阴影错误漏检 |
| 阴影抖动 | 确定性开关 | 逐像素验收帧必须 `jitter=0` | 同输入不同像素却当"无变化" |
| 断面色 | 剖面语义 | 挖开后能区分外皮/剖面 | "剖面色没设"导致截面读数错误 |
| 调色板分库 | 库数对账 | `GetPaletteBankCount()` == 素材实际用色组数 | 库数无界增长、串库 |
| UGC 着色 | 分库偏移 | 非 0 库体积外观单独验 | 漏偏移导致串库 |
| 解析代理 | 回退验证 | 破坏后 `GetCollisionShapeType()` 已回 Auto | 隐形碰撞体 |
| 水与浮力 | 双高度一致 | 浮力水位与视觉水面高度一致 | 船浮在空气中 |
| 接触事件 | 触发验证 | 设阈值后事件确实到达 | 默认阈值 0 导致哑火 |
| 碎块预算 | 峰值登记 | 峰值碎块数与帧时写入 `perf_<tag>.json` | 大半径伤害造成的巨帧 |
| **灯光组契约** | 契约哈希 + 单一 Zone | ID+版本+内容哈希全等；场景中只有一个生效 Zone | “另建 Zone 静默顶掉 IBL/SH/Bloom/雾” |
| **RenderPath 与后处理快照** | 版本绑定 | 资源名+哈希+启用 tag 集合、Zone 后期字段快照均相等 | 换 tonemap/bloom 后沿用旧逐像素基线 |
| **无光照（A）通道** | 存在性 + 差异可辨 | 每机位有无光照帧，且与成片存在可辨明暗差 | bloom/DOF/tonemap 掩盖几何与 LOD 缺陷 |
| **光源清单** | 清单齐全 | 每个光源的位置/朝向/强度/颜色/阴影参数都有值 | 点光/追光漏登记（LightGroup 只管太阳） |
| **环境光模式** | 模式声明 | `ambientSource` 明确且与契约一致；换模式后基线重立 | 默认模式下调 `ambientColor` 白费功夫 |

## 5. 坑与反面清单

1. **`SetPaletteEntry` 晚于 `.vox` 导入 ⇒ 颜色错乱**：导入会自动认领空槽位，调色板必须**先设完**。
2. **体积隐形**：手改 grid 后忘了 `RebuildGeometry()` / `MarkGeometryDirty()`。⇒ 规则与完整序列**单一出处见 `05-urhox-operations.md` §3**，本条仅作坑目录索引。
3. **体积渲成纯白**：材质取了通用缓存的调色板材质，而非 `world:GetPaletteMaterial()`。
4. **手改 grid 的建造在存档重载后消失**：从 `.vox` 创建的体积先要 `DetachFromVoxelModel()`（引擎在**首次伤害写**时才自动解绑）。⇒ 规则与三组对照读数**单一出处见 `14-cross-engine-methodology.md` §10.5**，本条仅作坑目录索引。
5. **带朝向摆放位置飞了**：体积原点在**最小角**，旋转会甩脚印，必须按 dims 补偿。
6. **角色悬空/陷地半截**：位置是**脚底**；跳跃必须走 `MoveCharacter` 的 `jumpSpeed`。
7. **手改 grid 后碰撞是旧的**：动态体要 `RebuildDynamicProxy(volume)`。
8. **铰链抖散架 / 门推不开**：`disableCollision=true` 或同 `collisionGroup`；平接被摩擦焊死时留 1 体素缝。
9. **载具把地面挖出沟**：地形没设 `destructible=false`。
10. **打不动某材质**：`power < hardness` 完全免疫，是刻意的。
11. **`VoxelContact` 不触发**：`contactEventThreshold` 默认 0。
12. **LOD / 流式 / DDA / 阴影体"在编辑器里是开的"**：它们是运行时标记、不序列化，交付前必须脚本显式设定。
13. **把 `GetMeshLodLevel()` 当可控参数**：它只读，环由世界所有；脚本只能读不能设。
14. **在同一个 Scene 混用两套物理并解释结果**：体素世界与 Bullet 互不碰撞。
15. **一次大半径伤害**：单次移除上千体素 + 数百碎块会造成巨帧，拆成几帧几次。
16. **加载 LightGroup 后又建一个 Zone**：新 Zone 默认 priority=0 > 预设的 −1，**整套 IBL/SH/Bloom/雾静默失效**。
17. **脚本里 set float 光照/雾属性**：会被拒或静默无效，必须走 LightGroup XML 主数据。
18. **默认模式下调 `zone.ambientColor`**：no-op（环境光由 SH 驱动）。
19. **拿 `DiffUnlit.xml` 当天空 technique**：它是普通几何材质，会按距离吃雾，近景浓雾下天空会被染成雾色。
20. **用成片（后效全开）当几何证据**：后处理是非线性不可逆的，会掩盖缺陷也会造出假差异。

## 6. 证据等级与来源

| 事实类别 | 来源 | 等级 |
|---|---|---|
| API 签名、枚举值、默认值、注释语义 | `<PROJECT>/.emmylua/Voxel*.d.lua`（`Auto-generated from VoxelPhysics/…`） | A（引擎生成物，只读） |
| 流程语义、陷阱表、性能提示、"四条铁规" | `engine-docs/recipes/voxel-physics.md`（§一–§十五） | A（引擎配方文档） |
| 联网语义、色板域、Ready 契约 | `engine-docs/recipes/voxel-networking.md` | A |
| DDA 渲染路径存在性 | `CoreData/Techniques/PBR/PBRVoxelDda*.xml`（含 `Sparse4`、`*Inside`） | A（引擎资源） |
| 面合并存在（非算法名） | 引擎运行时自测脚本 `Data/LuaScripts/VoxelVolumeRenderTest.lua` 注释 | A（注释级；算法名未公开） |
| LOD 行为（逐级消失、颜色收敛） | 引擎运行时自测脚本 `Data/LuaScripts/VoxelLodRingTest.lua` | A（脚本级） |
| 官方摄取实现（保守加速、薄壳、挖空、面朝向 UV） | `.cache/packages/official-Voxel-Tool/<ver>/scripts/VoxelConvert/*` | A（只读包） |
| 灯光/大气/后处理的字段与语义 | `.emmylua/Zone.d.lua`、`Light.d.lua`、`RenderPath.d.lua`；`engine-docs/recipes/rendering.md` | A |
| float 属性只能经 XML 设置 | 项目自带 LightGroup XML 的注释（实测踩坑记录） | B（单点记录，换发行版需重验） |
| 无光照通道 technique 存在 | `CoreData/Techniques/{NoTextureUnlit,NoTextureVCol,DiffUnlit}.xml` | A |
| 编辑器是否有体素专用工具 | 编辑器 MCP 工具清单 | B（随发行版变化，用前重查） |

**UNVERIFIED / 不宣称**：`VOXEL_MAX_MESH_LOD` 的具体数值（Lua 未导出）；面合并的具体算法；LOD 与流式的默认值在不同发行版是否变化。

## 工具

- `scripts/urhox_capability_probe.py`：扫描一个 UrhoX 工程，输出**能力卡**（哪些原生能力存在、各自证据、项目脚本里是否已引用、未被引用的有哪些），用于"这轮还能开什么"的可复核问答。只读，不写工程。

## 本文件的通用性边界

- 本文件绑定 UrhoX / TapTap Maker 的**某一发行版**。换发行版必须重跑探针并重核默认值。
- 第 3 节的决策树是**判据**但不是门禁；具体对象仍受 `08` 的对象类型与尺度等级约束。
- 本文件不覆盖：联网协议细节、音频、UI、编辑器扩展开发。
