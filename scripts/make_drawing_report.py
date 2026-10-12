#!/usr/bin/env python3
"""把体素三视图图纸与投影数据打包成**自包含单文件 HTML**（样式与 SVG 全内联，无外部资源）。

用途：手机/远程查看时不必开 CAD；也便于把一轮结果作为一个文件发出去。

usage:
  python make_drawing_report.py --drawings <dir> --out <file.html> [--title "..."]
  # <dir> 下每个子目录应含 projection.json + sheet.svg + sheet.dxf(+pdf)
"""

import argparse
import html
import json
import os
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--dim:#6b7280;--line:#e3e6ea;
--ok:#0f7b3f;--warn:#b45309;--bad:#b91c1c;--acc:#1f4e79}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 64px}
h1{font-size:24px;margin:8px 0 4px;line-height:1.3}
h2{font-size:19px;margin:32px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--acc)}
h3{font-size:16px;margin:20px 0 8px;color:var(--acc)}
.sub{color:var(--dim);font-size:14px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.sheet{background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.sheet svg{display:block;width:100%;height:auto}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f0f2f5;font-weight:600;color:#374151}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:14px;margin:6px 0}
.kv dt{color:var(--dim)}
.kv dd{margin:0;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:#f3f4f6}
.ok{color:var(--ok);border-color:#bfe3cd;background:#eefaf2}
.warn{color:var(--warn);border-color:#f3ddb5;background:#fdf6e9}
.bad{color:var(--bad);border-color:#f3c6c6;background:#fdeeee}
code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:13px}
.note{font-size:14px;color:var(--dim)}
ol,ul{padding-left:22px}
li{margin:4px 0}
@media(max-width:560px){.kv{grid-template-columns:1fr}h1{font-size:20px}
table{font-size:13px}th,td{padding:5px 6px}}
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load(d):
    pj = os.path.join(d, "projection.json")
    if not os.path.isfile(pj):
        return None
    p = json.load(open(pj, encoding="utf-8"))
    svg = ""
    sp = os.path.join(d, "sheet.svg")
    if os.path.isfile(sp):
        svg = open(sp, encoding="utf-8").read()
        svg = svg[svg.find("<svg"):] if "<svg" in svg else ""
    files = {}
    for f in ("sheet.svg", "sheet.dxf", "sheet.pdf", "sheet_fallback.svg"):
        fp = os.path.join(d, f)
        if os.path.isfile(fp):
            files[f] = os.path.getsize(fp)
    return {"dir": d, "proj": p, "svg": svg, "files": files}


def render(objs, title):
    out = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           "<title>%s</title><style>%s</style></head><body><div class=\"wrap\">" % (esc(title), CSS),
           "<h1>%s</h1>" % esc(title),
           '<div class="sub">体素占用 → 正交真投影 → A3 装配出图 ｜ 生成日期 %s ｜ '
           '由 <code>scripts/voxel_orthographic_drawing.py</code> + '
           '<code>scripts/make_drawing_report.py</code> 产出</div>' % date.today().isoformat()]

    out.append('<div class="card"><h3>一句话结论</h3><p>这两张图不是截图，是'
               '<b>从审计数据里的体积盒做真投影</b>再装配成 A3 图纸。'
               '过程中报出三个"不报错但会画错"的坑（见文末），'
               '它们才是这轮最值钱的部分。</p></div>')

    for o in objs:
        p = o["proj"]
        out.append("<h2>%s</h2>" % esc(p.get("subject")))
        wb = p["worldBounds"]
        out.append('<div class="card"><dl class="kv">')
        for k, v in (("体积数", p["boxCount"]),
                     ("体素边长 (m)", p["voxelSizeMeters"]),
                     ("竖向轴", p.get("upAxis", "?")),
                     ("世界尺寸 W×H×D (m)", " × ".join("%g" % x for x in wb["size"])),
                     ("底面范围 (m)", "x %g..%g · z %g..%g" % (wb["min"][0], wb["max"][0],
                                                              wb["min"][2], wb["max"][2])),
                     ("高度范围 (m)", "%g..%g" % (wb["min"][1], wb["max"][1])),
                     ("轮廓栅格", "%g m（=检出体素）" % p["outline"]["cellMeters"]),
                     ("数据源", os.path.basename(p["source"]))):
            out.append("<dt>%s</dt><dd>%s</dd>" % (esc(k), esc(v)))
        out.append("</dl><p class=\"note\">体素尺寸推断：<code>%s</code>；样本 %s 个，比值区间 %s</p>"
                   % (esc(p["auditMeta"]["voxelInference"].get("method")),
                      esc(p["auditMeta"]["voxelInference"].get("samples")),
                      esc(p["auditMeta"]["voxelInference"].get("ratioSpread"))))
        out.append("</div>")

        if o["svg"]:
            out.append('<div class="sheet">%s</div>' % o["svg"])
            out.append('<p class="note">A3 横版（420×297mm）：正立面 / 侧立面 / 顶视 / 轴测，'
                       '各视图为 <b>并集轮廓</b>，不是 24 个重叠矩形。</p>')

        out.append("<h3>视图与轮廓</h3><table><tr><th>视图</th><th>体积盒</th>"
                   "<th>轮廓段数</th><th>比例 (mm/m)</th></tr>")
        for v in ("front", "side", "top", "iso"):
            vv = p["views"][v]
            out.append("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td>"
                       "<td class='num'>%.3f</td></tr>"
                       % (esc(v), len(vv["rects"]), len(vv["outline"]), vv["mmPerMeter"]))
        out.append("</table>")

        out.append("<h3>体积盒明细</h3><table><tr><th>名称</th><th>X (m)</th><th>高度 Y (m)</th>"
                   "<th>Z (m)</th><th>实心格</th><th>高度取值来源</th></tr>")
        for b in p["boxes"]:
            out.append("<tr><td>%s</td><td class='num'>%.2f..%.2f</td>"
                       "<td class='num'>%.2f..%.2f</td><td class='num'>%.2f..%.2f</td>"
                       "<td class='num'>%s</td><td class='note'>%s</td></tr>"
                       % (esc(b["name"]), b["min"][0], b["max"][0],
                          b["min"][1], b["max"][1], b["min"][2], b["max"][2],
                          esc(b.get("solid") or "-"), esc(b.get("ySource"))))
        out.append("</table>")

        warns = p["auditMeta"].get("voxelWarnings") or []
        if warns:
            out.append("<h3>一致性告警（%d 条，前 6 条）</h3><ul class=\"note\">" % len(warns))
            for w in warns[:6]:
                out.append("<li>%s</li>" % esc(w))
            out.append("</ul>")

        out.append("<h3>产物文件</h3><table><tr><th>文件</th><th>字节</th></tr>")
        for f, sz in sorted(o["files"].items()):
            out.append("<tr><td><code>%s</code></td><td class='num'>%d</td></tr>" % (esc(f), sz))
        out.append("</table>")

    out.append("""<h2>三个"不报错但会画错"的坑</h2>
<div class="card">
<ol>
<li><b>体素尺寸不是全局常量。</b>用 <code>origin_y / minY</code> 反算：Y星飞碟 <code>0.125 m</code>、
天守阁 <code>0.25 m</code>。用错不报错，只让整张图缩放错一倍。<br>
处置：<code>--voxel-size auto</code>（取中位数 + 用 <code>maxY</code> 交叉校验 + 告警）。</li>
<li><b><code>size_y</code> 是节点盒高，不是实心高度。</b>Y星飞碟 <code>HullDisc</code> 节点盒 40 层 = 9.0 m，
实心只占 12 层 = 1.5 m。直接用会让飞碟<b>虚高 1.7 倍</b>（4.625 → 9.0 m）。<br>
处置：<code>--y-source minmax</code>，Y 取 <code>minY..maxY+1</code>。</li>
<li><b>审计数据是 Y-up，不是 Z-up。</b><code>origin=[x,y,z]</code> 且 <code>minY/maxY</code> 就是竖向范围。
按 Z-up 投影会把"立面"画成"俯视样的立面"——看着像图纸，其实不是立面。<br>
处置：<code>--up-axis y</code>（默认），并把竖向轴的语义写进 <code>projection.json</code>。</li>
</ol></div>

<h2>已知局限</h2>
<div class="card"><ul>
<li>轮廓粒度 = <b>体积盒栅格化</b>后的并集，<b>不是引擎内逐体素占用</b>；所以出的是体量关系图，
不是体素级剪影。</li>
<li>X/Z 用的是体积盒的 <code>origin+size</code>；审计未提供 X/Z 的实心范围，可能比实心范围大。</li>
<li>视图之间不做遮挡消隐（no hidden-line removal）。</li>
<li><b>尚未与渲染帧做 IoU 对账</b>——<code>references/19</code> 的 IoU/SSIM 阈值仍是外部惯例值。</li>
<li><b>可复现的是 <code>projection.json</code>（逐字节一致），不是 <code>sheet.dxf</code></b>——
ezdxf 会写 <code>$TDCREATE</code>/<code>$TDUPDATE</code> 与自增句柄。对账与回滚认
<code>projection.json</code> 的哈希。</li>
</ul></div>
""")
    out.append("</div></body></html>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="体素占用 → 正交三视图（真投影出图）")
    a = ap.parse_args()

    if not os.path.isdir(a.drawings):
        print("drawings dir not found:", a.drawings)
        return 2
    objs = []
    for name in sorted(os.listdir(a.drawings)):
        d = os.path.join(a.drawings, name)
        if not os.path.isdir(d):
            continue
        o = load(d)
        if o:
            objs.append(o)
    if not objs:
        print("no projection.json found under", a.drawings)
        return 1
    doc = render(objs, a.title)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8", newline="\n").write(doc)
    print("objects: %d  bytes: %d  -> %s" % (len(objs), len(doc.encode("utf-8")), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
