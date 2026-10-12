# 来源目录（实测站点 / 端点 / 抓取参数）

本文件是 `references/09-reference-sourcing-and-capture.md` 的**实测补充**：09 给通用方法，本文件给**已经跑通过的具体站点、端点与参数**，以及实测踩到的限制。

维护规则：新站点追加到对应表；端点失效、被墙、需要登录时**就地标注日期与现象**，不要删除历史记录。**最后核实日期：2026-09-22。**

## 1. 米游社系（社区论坛，本项目主力来源）

| 站点 / 域名 | 能回答什么 | 检索入口 | 抓取要点 | 实测限制 |
|---|---|---|---|---|
| `bbs-api.miyoushe.com` | 社区帖子（建筑考据、实机摄影、地图、走查） | 搜索 API（见下） | 必须带 `Referer: https://www.miyoushe.com/` | 返回 JSON，需再从正文抽图 |
| `www.miyoushe.com` / `m.miyoushe.com` | 帖子页、图集 | 站内搜索、话题页、作者主页 | 帖子 JSON 可整篇落盘供回溯 | 移动版与桌面版结构不同 |
| `upload-bbs.miyoushe.com` | **帖子原图托管**（本项目最大图源，数千次命中） | 从帖子 JSON 里的图片字段取直链 | 直链可取；按扩展名过滤 | 预览图与 `origin_url` 原图不同，**取原图** |
| `prod-vod-sign.miyoushe.com` / `vod-static.miyoushe.com` | 帖子视频 | 从帖子 JSON 取 | 视频另存后抽帧（见 09 §4.1） | 签名链接有时效 |

**搜索 API（实测可用）**：

```text
https://bbs-api.miyoushe.com/post/wapi/searchPosts?gids=2&size=20&keyword=<URL编码关键词>
```

- `gids=2` 为原神；换作品换 gids。
- 关键词示例（能命中建筑考据类长文）：`<地名>建筑考据`、`<地名>建筑风格解读`、`<地标>平面`、`<地名>走查/摄影/全景`。
- 建议把搜索响应**原样落盘**（如 `search_<关键词md5前8位>.json`），后续换索引方式不必重抓。

**必需请求头**：

```python
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.miyoushe.com/",
    "Accept": "application/json,text/html,*/*",
}
```

**从帖子 JSON 抽图**：递归遍历 JSON，收集键名为 `url` / `cover` / `icon` / `origin_url` / `img` 且值为 `http` 开头、扩展名属于 `.png/.jpg/.jpeg/.webp` 的字符串。

**已知有料的帖子 ID（起点清单，非授权内容）**：

```text
建筑考据/摄影：1470766  1483888  5159132  5552225  29345837
               3893465  12872895  63225304
城市摄影/走查：74371503  78045859  74441445
全景/对比图：  48358228  48438087  27022957
```

**索引产物**：每条图记 `{post, i, file, url}`（post = 帖子 ID，i = 帖内序号），便于回查"这张图出自哪篇帖子"。

## 2. 米哈游官方与 HoYoLAB（一手权威）

| 站点 / 域名 | 能回答什么 | 注意 |
|---|---|---|
| `baike.mihoyo.com` | **官方百科**：命名、设定、地点定义 | 优先用于"名称与设定事实"这类 A 级问题 |
| `webstatic.mihoyo.com` / `act.mihoyo.com` / `uploadstatic.mihoyo.com` | 官方活动页与官网素材（含高清原画、地图切片） | 活动页会下线，取到即归档 |
| `upload-os-bbs.hoyolab.com` / `www.hoyolab.com` | 国际服社区（图文与米游社同构） | 语言/版本可能与国服不同，登记版本 |
| `fastcdn.hoyoverse.com` | 国际服 CDN | 同上 |

## 3. Wiki 系

| 站点 | 能回答什么 | 取图方法 | 实测限制 |
|---|---|---|---|
| `genshin-impact.fandom.com` | 条目、分类页、点位图、地区图 | ① MediaWiki API 批量（`https://genshin-impact.fandom.com/api.php`，标题列表分批，实测 40 个/批）② **回退：`/wiki/Special:FilePath/<文件名>` 直接重定向取原图**（不需要 API） | **实测：本项目网络下 API 超时、偶发 SSL/hostname 不匹配** → 走回退路径；两者都失败时按"未能刷新"登记，不得假装有证据 |
| `static.wikia.nocookie.net` | Fandom 图片 CDN | 从条目页/文件页取直链 | 同一图有多个缩放版本，取原图 |
| `wiki.biligame.com`（bwiki） | 中文条目与图集 | 页面解析取图 | 中文条目常比英文 wiki 更贴本地译名 |
| `ysmap.huijiwiki.com` | **可交互中文地图**（点位、区域边界） | 截图为主（见 09 §4.1 的瓦片/配准要点） | 地图元素会遮挡画面，需按污染旗标处理 |

**MediaWiki 站内检索语法**（Fandom 与多数 wiki 通用）：

```text
Special:Search?search=<词>&ns0=1        条目检索
insource:"<原文片段>"                    正文命中（找引用与数据）
incategory:"<分类>"                      按分类成组取图（最快的成组入口）
intitle:<词>                             标题命中
```

## 4. 其它实测来源

| 站点 | 用途 | 分级倾向 |
|---|---|---|
| 知乎专栏（`zhuanlan.zhihu.com`） | 建筑风格解读、考据长文 | B/C（可作线索与交叉，不作硬锚点） |
| Twitter/X（`pbs.twimg.com`） | 官方与创作者发布图 | B（官方账号可 A） |
| YouTube（`i.ytimg.com` 缩略图） | 走查视频线索 | C；抽帧后按 B 处理 |
| Planet Minecraft（`static.planetminecraft.com`） | **体素作品参考**（比例、配色、构件语法） | C/D：只能作风格与做法参考，**不得当几何证据** |
| TapTap（`maker.taptap.cn` 等） | 项目发布侧资源 | 按项目文档 |

## 5. 抓取工程约定（实测可直接复用）

| 约定 | 实测值 / 做法 | 理由 |
|---|---|---|
| UA | 常规浏览器 UA；**米游社系必须带 Referer** | 反爬最少化，避免拿不到图 |
| 尺寸闸门 | 响应 < 800 B 视为失败；`text/html` 且 < 20 KB 视为无效页 | 过滤占位图与错误页 |
| 断点续抓 | 目标文件已存在且 > 4 KB → 跳过 | 重跑不重复下载 |
| 目录分层 | `_raw/` `_norm/` `_annot/`（通用形式）；项目实例按用途再分（地图/点位/高程/摄影/帖子） | 与 01 §6 派生链一致 |
| 每批产物 | 图片目录 + 运行日志 + `index.json` + 一份人工可读清单 | 让下一轮不必重抓就能复用 |
| 原样落盘 | 搜索响应与帖子 JSON 全存 | 换索引方式时不重抓 |
| 去重 | 按文件名主干去重（扩展名不参与） | 同图不同格式 |
| 限速 | 单域串行、请求间加延迟 | 见 09 §3 |
| 失败登记 | 端点被墙/超时**写进清单**（例：Fandom API 超时） | 不许用"大概有"代替证据 |

## 6. 制图与截图侧实测参数

- 参考图归档后进入制图：项目实例用 **A3 比例（3508 × 2480）**、纸色/线色语义固定、世界坐标 `origin = 城门中线`、`+X 东 / +Y 北`（结构可参考，具体取值按项目参数表）。
- 地图类素材先保留瓦片行列号与原始尺寸，再拼接并记录 seam、缩放级别与重叠率；交互地图至少 3 点配准（见 09 §4.1）。
- 游戏内截图必须关 HUD、固定时间/天气/光照、关后处理；相机参数登记与 `06` §7 相同的 8 个字段。

## 7. 使用者常用站点（已登记）

状态图例：**实测** = 本项目脚本跑通并有产物/日志；**未实测** = 使用者提供或通用做法，首次使用前必须先验证并更新“最后核实日期”，未验证前不得写进验收结论。

| 站点 / 域名 | 用途（能回答什么） | 检索入口 / 语法 | 抓取或截图方法 | 实测限制 | 最后核实日期 |
|---|---|---|---|---|---|
| **米游社**　`www.miyoushe.com` `m.miyoushe.com` `bbs-api.miyoushe.com` `upload-bbs.miyoushe.com` | 建筑考据长文、实机摄影、走查、全景、点位（本项目**主力来源**） | 搜索 API（§1）：`bbs-api.miyoushe.com/post/wapi/searchPosts?gids=2&size=20&keyword=<URL编码>`；站内搜索与话题页 | ① `searchPosts` 搜帖子 ② `getPostFull?post_id=<pid>` 取正文 ③ 正则 `https://upload-bbs\.miyoushe\.com/[^"'\s<>]+` 取图；**必带 `Referer: https://www.miyoushe.com/`**；命名 `mys_<pid>_<序号>` | 预览图 ≠ `origin_url` 原图（取原图）；视频另域（`prod-vod-sign`）需另存后抽帧 | 2026-09-22（实测） |
| **NGA**　`bbs.nga.cn` `nga.178.com` | 攻略与考据讨论帖、局部构件细节、版本期玩家实测 | 站内搜索（多数版块需登录）；外部兜底 `site:bbs.nga.cn <关键词>` | 未实测。通用做法：公开可读页面用浏览器固定视口截图（09 §4.1），**不尝试绕过登录** | **本项目脚本中未出现**；通常需登录、反爬较强 → 登记为“需人工/浏览器截图” | 2026-09-22（未实测） |
| **B 站 wiki（bwiki）**　`wiki.biligame.com/ys` | 中文条目、图集、点位说明（比英文 wiki 更贴本地译名） | 目录页直取：`https://wiki.biligame.com/ys/<URL编码标题>`；站内搜索页 | 页面解析：正则 `//patchwiki\.biligame\.com/images/ys/[^\"'\s<>]+` 取图并补 `https:`；命名 `bili_<标题>` | 图片在 `patchwiki` CDN；条目质量参差，需与官方来源交叉 | 2026-09-22（实测） |
| **Fandom**　`genshin-impact.fandom.com` `static.wikia.nocookie.net` | 条目、分类页、点位图、区域图 | MediaWiki API（`api.php`）三种调用：批量文件 / 搜索（limit 50）/ 分类（limit 80）；站内 `insource:` `incategory:` | ① 批量标题分批（实测 40 个/批）② 搜索/分类取文件标题 ③ **回退路径 `Special:FilePath/<文件名>`**（不需 API）；命名 `wiki_<标题>` | **实测：本项目网络下 API 超时、偶发 SSL/hostname 不匹配**；回退路径可用；两者都失败时按“未能刷新”登记 | 2026-09-22（实测） |
| **灰机 wiki（HuijiWiki）**　`ysmap.huijiwiki.com`（本项目用量） | 可交互中文地图、点位与区域边界 | MediaWiki 常规检索（`Special:Search`、`incategory:`）；地图站以页面操作为主 | 曾试 `Special:FilePath/<URL编码文件名>` | **实测 403**（日志原文：`403 text/html ... final=https://ysmap.huijiwiki.com/wiki/Special:FilePath/<文件名>`）→ 改用页面截图；地图元素会遮挡画面，按污染旗标处理 | 2026-09-22（实测 403） |
| **Reddit**　`reddit.com` `old.reddit.com` | 玩家重建、跨版本对比、实拍与讨论 | 站内搜索；外部 `site:reddit.com <关键词>`；时间过滤取版本有效期内帖 | 未实测。通用做法：`old.reddit.com` 固定视口截图；列表/帖子 URL 末尾加 `.json` 取结构化字段与图片直链 | **本项目脚本中未出现**；`.json` 有速率限制且需常规 UA；第三方历史存档服务已停用 | 2026-09-22（未实测） |
| **Pinterest**　`pinterest.com` | 风格与配色灵感、同人图聚合（找线索，不当证据） | 站内搜索、看板；外部 `site:pinterest.com <关键词>` | 未实测。通用做法：浏览器固定视口截图 | **本项目脚本中未出现**；**强反爬**且图多为转载 → 只能 C/D 级，**必须反查原始出处**（09 §2.4） | 2026-09-22（未实测） |

已在上表登记的站点：米游社、NGA、B 站 wiki（bwiki）、Fandom、灰机 wiki、Reddit、Pinterest。其中前三项的端点细节见 §1–§3。

**后续追加位置**（新站按同一格式填，填完即生效）：

| 站点 / 域名 | 用途（能回答什么） | 检索入口 / 语法 | 抓取或截图方法 | 实测限制 | 最后核实日期 |
|---|---|---|---|---|---|
| | | | | | |

## 8. 本文件的通用性边界

- 域名、端点与参数**会变**；使用前先按本节方式实测一次，失效就更新日期与现象。
- 只登记**公开可达**的内容与常规取图方式；不提供绕过登录、付费、验证码或限速的手段，合规责任在使用者。
- 帖子 ID 与文件名清单是"已知有料的起点"，不代表内容授权；引用进正式证据包时仍按 `01` 分级与标定。
- 本项目实例的原始脚本与素材留在项目侧（`docs` 下的 harvest 脚本与参考素材目录），本文件只保留可迁移的方法与参数。
