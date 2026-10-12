# 运行环境与依赖规范（解释器绑定 · 安装位置 · 依赖判据 · 环境验收）

本文件是**"跑外部件需要什么环境"的唯一出处**。它回答四件事：
用哪个解释器、装到哪里、怎么判断缺不缺依赖、以及**怎么证明这个环境没漂**。

与其它文件的分工（不重复正文）：

- `18-external-skill-adoption.md`：某个外部件**该不该采纳**（P1–P4 等级与许可证）。
- `assets/external-skills-index.json`：外部件的**清单与抽取范围**。
- `10-verification-instruments.md`：本工程自己的验收仪器。
- **本文件：外部件运行所依赖的解释器、包、外部软件，以及它们的登记与验收。**

## 0 六条纪律（违反任一条，该轮的"可跑"结论作废）

1. **一个外部件只绑定一个解释器**，绑定关系必须登记在 `assets/external-skills-index.json` 的
   `runtime` 字段（或该件的 `_DEPS.md`）。没登记的"跑通了"不算数。
2. **跨解释器调用必须显式写出**：例如用 FreeCAD 的 3.11 去调系统 3.12 的脚本是**禁止**的；
   要调就用子进程并写明命令行，不得假定 sys.path 互通。
3. **禁止凭静态 import 扫描就装包**。必须先区分硬依赖与可选依赖（§3），否则会装一堆不需要的包。
4. **环境本身要被验收**：`scripts/runtime_env_probe.py` 的期望表与本机实测必须一致；不一致即"环境漂移"，
   在漂移被解释清楚之前，任何"某件可跑"的结论降级为 `PASS-WATCH`。
5. **商业软件不进交付链路**：Rhino / SOLIDWORKS / Revit 等需授权的外部软件只能作为**算法与流程参考**（P4），
   不得让交付管线在运行时依赖它们。
6. **不把"装过"当"可复现"**：能复现的最小形态是**命令行 + 解释器绝对路径 + 包版本**三件套；
   只写"已装 numpy"不构成可复现描述。

## 1 解释器清单与绑定规则（唯一索引）

| id | 解释器 | 版本 | 用途 | 调用姿势 |
|---|---|---|---|---|
| `py312` | `D:\tools\Python312\python.exe` | 3.12.10 | **默认**：绝大多数纯 Python 外部件 | `PYTHONUTF8=1 python <script>` |
| `freecad311` | `D:\tools\FreeCAD\bin\python.exe` | 3.11.14 | 需 `FreeCAD` 模块的件（`cadstack` freecad 后端、`skill-freecad`、`openclaw-freecad-mcp`） | `"D:\tools\FreeCAD\bin\python.exe" <script>` |
| `freecadcmd` | `D:\tools\FreeCAD\bin\freecadcmd.exe` | 1.1.3 | FreeCAD **无头**批处理（不需要 GUI） | `freecadcmd.exe <script.py>` |
| `blender` | `D:\tools\Blender\blender-5.1.2-windows-x64\blender.exe` | 5.1.2 | 需 `bpy` 的件（`cc-blender-skill`） | `blender.exe --background --python <script.py>` |
| — | *Rhino* | 未安装 | `rhinoclaw` | **不绑定**（见 §5） |

**绑定规则**

- `FreeCAD.pyd` 只能被 FreeCAD 自带的 **3.11** 导入，`py312` **导不进去**。
  因此凡 `_DEPS.md` 里出现 `FreeCAD` / `FreeCADGui` / `Part` / `Mesh` / `ObjectsFem` / `PySide` 的件，
  一律绑 `freecad311`，并在该解释器里**单独**装它需要的第三方包（`py312` 装的不共享）。
- `bpy` 同理：**不要** `pip install bpy`。本机已有 Blender，直接用 `blender --background --python`。
- 一个件的"可跑"判定必须写明**在哪个解释器上可跑**。`py312` 缺 `FreeCAD` 不代表该件不可用。

## 2 安装位置与包管理器约定

| 类型 | 位置 | 工具 |
|---|---|---|
| 第三方 Python 包（`py312`） | `D:\tools\Python312\Lib\site-packages` | `python -m pip install` |
| 第三方 Python 包（`freecad311`） | FreeCAD 自带 `Lib\site-packages` | `"D:\tools\FreeCAD\bin\python.exe" -m pip install` |
| 独立软件 / 引擎 | **`D:\tools\<名称>`** | 优先 `winget install --location "D:\tools\<名称>"` |
| 浏览器内核（playwright） | `%LOCALAPPDATA%\ms-playwright` | `python -m playwright install chromium` |

- 装独立软件一律走 `D:\tools\<名称>`，与既有约定一致（`D:\tools` 下已有 `Python312`、`Blender`、`FreeCAD`、`UrhoXEditor`、`UE_5.8`）。
- `winget` 必须带 `--accept-package-agreements --accept-source-agreements`；`--location` 对部分安装器只是提示，
  安装后必须**回读实际落点**并写进 §6，不得假定生效。

## 3 依赖判据规范

对每个抽取件，`_DEPS.md` 必须区分三类，缺任一类视为漏检：

| 类别 | 判据 | 处理 |
|---|---|---|
| **硬依赖** | 模块级 `import`，不在 `try/except` 内 | 缺了就跑不了；装或降级为 P3/P4 |
| **可选依赖** | 位于 `try:` 块内（常见写法：`try: import rapidocr except: import paddleocr`） | **不计入缺失**；只在文档里列出后备方案 |
| **平台提供** | `bpy`（Blender）、`FreeCAD`（FreeCAD）、`System`/`clr`（Rhino） | 不装包，改绑对应解释器；Rhino 一类直接不绑定 |

**踩过的坑（必须记住）**：`ssq` 的技能写成 `try: rapidocr_onnxruntime` 优先、`except: paddleocr` 后备；
首轮静态扫描把 `paddleocr` 判成必需，差点白装一套 OCR。
`scripts/external_tool_fetch.py` 已实现 `try/except` 识别（`optionalImports`），
**看 `_DEPS.md` 时先看 `optionalImports`，再看 `missingHere`**。

## 4 环境验收（机器可跑）

```bash
PYTHONUTF8=1 python scripts/runtime_env_probe.py            # 人读报告
PYTHONUTF8=1 python scripts/runtime_env_probe.py --json      # 机器读
```

- 它逐个解释器核对：**存在性 + 版本 + 关键包可用性 + 浏览器内核**，并与本文件 §6 的期望表比对。
- 退出码：`0` 期望全中 · `1` 有漂移（缺件或版本不符） · `2` 解释器路径不存在。
- **环境漂移的处理**：先查是"没装"还是"换了版本/换了路径"，把结论写进 §6 的变更记录，再重跑。
  在漂移解释清楚前，相关件的"可跑"结论一律 `PASS-WATCH`。

## 5 商业软件边界

| 软件 | 状态 | 允许 |
|---|---|---|
| Rhino（`rhinoclaw`） | 未安装，需商业授权 | **只读算法与流程**（P4）；不得进交付链路；不得写"已支持 Rhino 出图" |
| SOLIDWORKS / Revit | 未安装 | 同上（`solidworks-modeling`、`copilot-for-revit` 归 P3/P4） |
| FreeCAD / OpenSCAD / Blender | 已装（开源） | 可作为第二实现或管线组成，但必须登记到 §6 |

## 6 环境变更记录（append-only，只追加不修改）

| 日期 | 变更 | 解释器 | 结果 |
|---|---|---|---|
| 2026-09-23 | 建立本规范；`py312` 装入 numpy 2.5.3 · opencv-python-headless(cv2 5.0.0) · ezdxf 1.4.4 · PyMuPDF(fitz 1.28.2) · matplotlib 3.11.2 · openpyxl 3.1.5 · trimesh 5.1.0 · scipy 1.18.1 · scikit-image 0.19→0.26.0 · playwright · **cadquery 2.8.0**(+OCP 7.9.3.1, shapely 2.1.2) · reportlab 5.0.1 · rapidocr_onnxruntime | `py312` | P1 可跑数 1/12 → **8/12** |
| 2026-09-23 | git bash 环境无 `pip` 前缀混用；统一用 `python -m pip` | `py312` | — |
| 2026-09-23 | `python -m playwright install chromium`（chromium-1243 / headless-shell-1243 / ffmpeg-1011 / winldd-1007） | `py312` | 3dviz 帧采集解封 |
| 2026-09-23 | `winget install FreeCAD.FreeCAD` → **`D:\tools\FreeCAD`**，版本 **1.1.3**，自带 Python **3.11.14**；`--location` 生效（已回读） | `freecad311` | FreeCAD 类件解封（`import FreeCAD, Part, Mesh` 实测通过） |
| 2026-09-23 | **发现既有**：Blender 5.1.2 在 `D:\tools\Blender\blender-5.1.2-windows-x64`，**不需要** `pip install bpy` | `blender` | `cc-blender-skill` 解封 |
| 2026-09-23 | `freecad311` 补装 `ezdxf` / `trimesh` / `PyMuPDF`（它自带 numpy/PIL/matplotlib） | `freecad311` | FreeCAD 后端的第三方依赖凑齐 |
| 2026-10-10 | 包版本巡检（P0 执行）：`@taptap/maker` **0.0.35 → 0.0.36**（npm 全局；bin=`taptap-maker`，engines node>=18.14.1）；上游另有 beta `0.0.37-beta.5`(2026-10-09) 未采用 | 宿主 node v24.19.0 | Maker 构建链路口径升级；**0.0.36 的 `dist/maker.js` 内含 "TapTap Maker managed AGENTS policy" 注入逻辑**，是 `AGENTS.md` 顶部策略块的唯一管理者 |
| 2026-10-10 | **ai-dev-kit 刷新**：`https://urhox-demo-platform.spark.xd.com/ai-dev-kit/rnd/latest/ai-dev-kit.zip`，`Last-Modified 2026-10-09 07:02:29Z`，60,380,549 B，sha256 `e08e3c525dc7ff7ff575184063701c6b5585cbd072767a2d267dccbb943a8f69`（md5 与响应 ETag 一致）。用 `UrhoXEditor/tools/taptap_code/create_agent_workspace.py` 的 `create_workspace(target, archive_data=…)` 就地安装到 `薪主test`（win32 过滤 6 个 skill，`run-lua-headless`/`run-lua-validate` 豁免保留） | 工程侧 | 每 provider `.claude/.codex/.cursor/.gemini/skills` 各 **22** 个 skill，链接悬空 **44 → 0**；`.installer/skills` 新增 10 个（`develop-editor-script` `develop-plugin` `operate-editor` `run-lua-headless` `run-lua-validate` `setup-achievements` `setup-iap` `ui-gilded-scroll` `ui-sweetopia` `vox-convert`），本地独有 `mdl-voxelize` 保留 |
| 2026-10-10 | **`tools/editor_mcp.py` 被上面这次 kit 刷新覆盖**（19,252 → 19,328 B；该文件在 `.gitignore:72`，属 kit 托管，本地无补丁）。行为变化：返回值改为 "`ok is False` ⇒ 不等待 + 退出码 1"，即**失败不再静默返回 0** | `py312` | 调用方若按"恒 0 退出码"写判据会失效；引用本工具的脚本必须显式判退出码 |

## 6.1 引擎侧操作陷阱（渲染/导出类工具必读）

以下均为 **2026-09-23 实测**（离线 runtime，`UrhoXRuntime.exe`），违反任一条都会得到**静默失败**而不是报错。

### （1）`File()` 写不了文件 —— 数据要走日志通道

离线 runtime 下 `File(path, FILE_WRITE)` 返回 **nil**。官方注释就写了这一点：
*"the offline runtime cannot open files outside its own tree"*。
审计数据一直不是写文件得到的，而是打印成 `AUDITJSON {...}` **日志行**再由工具侧解析。

→ **规范**：任何需要落盘的数据导出，都走 `print()` → lua 日志（NDJSON）→ 工具侧抽取。
不要浪费轮次试图把 `File()` 修好；它是设计如此。

### （2）不带 `-screenshot` 就永不退出

离线 runtime 是个游戏循环，只能通过截图请求退出。任何"只跑逻辑不截图"的探针都会**挂到超时**。
→ 规范：总是传 `-screenshot=<ASCII 路径> -screenshot-frame=<N>`，哪怕不需要那张图；
导出类工作用 `frame=30` 足够（`Start()` 同步完成）。

### （3）引擎不会建目录 —— 缺目录会让入口脚本**静默不加载**

工程 `tools/project_info.json` 里的 `stage` / `log` / `audit` 目录不存在时，日志停在
`InputAdaptor` 之后就结束，**连 `Loaded Lua script <入口>` 都不出现，无任何报错**。
→ 规范：跑之前先 `mkdir` 这三个目录（各工程的 `shots.py` 每次都 `STAGE.mkdir`，这就是原因）。

### （4）**不要自带入口 Lua 模板**，要注入

自制一个结构相近的入口模板会让引擎在**引导阶段就崩**（同样停在 `InputAdaptor`、无报错）；
同一套调用参数 + **该工程自己的** `tools/shot_template.lua` 则完全正常。
→ 规范：加法式做法——**读工程模板 + 在内存里注入**，写到另一个生成文件名，不覆盖原生成文件，
不要改 `shots.py` / `shot_template.lua`（三路线同源，md5 一致本身就是证据）。

### （5）Lua 作用域：prepend 的代码看不到后面的 `local`

把 hook 放到文件开头时，它看不见模板稍后才声明的 `local subject`；
直接引用 `subject.NAME` 会报 `index a nil value` 并**静默中断整个 `setup()`**（后续打印全部消失）。
→ 规范：hook 只接收**参数**，不依赖外部 local；注入的调用用 `pcall` 包裹并把错误打印出来。

### （6）`#` 对稀疏表不可靠（典型陷阱）

掩码/集合用 `bits[i] = true` 记位，`for i = 1, #bits, 8` 会使用**未定义的表边界**：
实测一个 212×31 的剪影只导出 334 字符（应为 822），另一个直接为空。
→ 规范：长度必须**显式传入**（`__hexbits(bits, n)`），绝不用 `#` 推稀疏表长度。

### （7）共享日志目录 + 并发会话 = 串台

lua 日志目录被所有工程共用，且**并发会话会持续写入新日志**；"取最新 N 个"会把别的工程当自己的。
→ 规范：绑定键用**本次运行独有的标记**（如注入脚本名）+ **subject 标签** + **mtime 窗口**三道；
找不到本次的标志时必须**响亮失败**，禁止静默回退到"最新日志"。

### （8）写路径不能含中文

`-screenshot=` / `File()` 指向含中文的目录时**静默不写**（日志里连 `Screenshot` 行都没有）。
→ 规范：先写到纯 ASCII 暂存目录（如 `D:/tools/shots/_occupancy/`），再由工具侧拷到目标位置。

### （9）先查声明值，再反算

审计里已有**权威声明的体素边长**（`voxel_size` 字段）。反算（`origin[up]/minUp` 中位数）
应用于**交叉校验**与"声明缺失时的傅底"，不得在已有声明值的情况下只用反算。

## 7 与 18 / 19 的接口

| 场景 | 去哪 |
|---|---|
| 判断一个外部件该不该采纳 | `18`（等级与许可证） |
| 查某个件抽取了什么、可跑与否 | `assets/README.md` + `assets/external-skills-index.json` |
| 查该件绑哪个解释器、依赖怎么判 | **本文件**（§1 绑定、§3 判据） |
| 证明环境没漂 | 本文件 §4 的探针 |
| 新增/更换解释器或软件后要做什么 | 先改 §1 与 §6，再跑 §4 探针，最后重跑受影响件的 `_DEPS.md` |
