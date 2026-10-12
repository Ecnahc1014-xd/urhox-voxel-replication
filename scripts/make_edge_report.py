#!/usr/bin/env python3
"""把"轮廓 vs 渲染边缘"的实测结果打包成**自包含单文件 HTML**（叠图以 data URI 内联）。

inputs: --json <edge_front.json> ... --overlay <overlay.png>:<view>:<note> ...
output: 一个不依赖任何同目录资源的 .html

usage:
  python make_edge_report.py --out report.html \
      --json edge_front.json --json edge_side.json --json edge_top.json \
      --overlay "edge_front_overlay.png:front:..." ...
"""

import argparse
import base64
import html
import io
import json
import os
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
except ImportError:
    Image = None

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#171a1e;--dim:#697586;--line:#e2e6ea;--acc:#1f4e79;
--ok:#0f7b3f;--warn:#b45309;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif;-webkit-text-size-adjust:100%}
.wrap{max-width:1020px;margin:0 auto;padding:18px 14px 72px}
h1{font-size:21px;margin:6px 0 2px}
h2{font-size:17px;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--acc)}
.sub{color:var(--dim);font-size:13.5px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px;margin:11px 0}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:6px 0}
th,td{padding:6px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eff2f5;font-weight:600;color:#374151}
td.num{text-align:right;font-variant-numeric:tabular-nums}
code{font-family:ui-monospace,Menlo,Consolas,monospace;background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12.5px}
img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:8px;background:#000}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;border:1px solid var(--line);background:#f3f4f6}
.ok{color:var(--ok);border-color:#bfe3cd;background:#eefaf2}
.warn{color:var(--warn);border-color:#f3ddb5;background:#fdf6e9}
.note{font-size:13px;color:var(--dim)}
ul,ol{padding-left:20px}
@media(max-width:620px){h1{font-size:19px}table{font-size:12.5px}}
"""


def data_uri(path, max_w=1100):
    if Image is None or not os.path.isfile(path):
        return None
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    b = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii"), len(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="append", default=[])
    ap.add_argument("--overlay", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="投影轮廓 vs 正交渲染 · 边缘一致度实测")
    a = ap.parse_args()

    rows = []
    for p in a.json:
        if not os.path.isfile(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        key = "flip" if d.get("chosenFlipH") else "normal"
        r = d["results"][key]
        rows.append((d, r))

    ov = {}
    for spec in a.overlay:
        # 注意：Windows 路径自带盘符冒号，必须从右侧切，否则 "D:" 会被当成第一个分隔符
        parts = spec.rsplit(":", 2)
        path = parts[0]
        ov[os.path.basename(path)] = path

    L = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         "<title>%s</title><style>%s</style></head><body><div class=\"wrap\">" % (html.escape(a.title), CSS),
         "<h1>%s</h1>" % html.escape(a.title),
         '<div class="sub">快照 %s ｜ 工具 <code>scripts/outline_vs_render.py</code> ｜ '
         '数据源 <code>projection.json</code>（体积盒真投影轮廓）+ 对应机位正交渲染帧</div>' % date.today().isoformat()]

    L.append('<div class="card"><h2 style="margin-top:0;border:0;padding:0">一句话</h2>'
             '<p>把算出的轮廓叠到正交渲染帧上量“两者是否落在同一条边上”。'
             '这不是掩膜 IoU（两者不是同一类量），而是<b>边缘一致度</b>；'
             '但它不需要控制帧，且正是一位工程师手工对图时做的事。</p>'
             '<p class="note">先前的“控制帧差分”路线被证伪：移走主体后<b>全局光照也变了</b>'
             '（控制帧退化为纯天空，连四角差异都 &gt;60），差分掩膜被气氛变化污染。'
             '要成立需要“主体仍参与光照、只对相机不可见”的能力，当前引擎 API 不提供。</p></div>')

    L.append("<h2>实测值</h2><table>")
    L.append("<tr><th>视图</th><th>轮廓点</th><th>ref→render 均值</th><th>p50</th><th>p90</th>"
             "<th>≤2px</th><th>≤8px</th><th>≤16px</th></tr>")
    for d, r in rows:
        rr = r["refToRender"]
        L.append("<tr><td><b>%s</b></td><td class='num'>%d</td><td class='num'>%.2f</td>"
                 "<td class='num'>%s</td><td class='num'>%s</td>"
                 "<td class='num'>%.1f%%</td><td class='num'>%.1f%%</td><td class='num'>%.1f%%</td></tr>"
                 % (d["view"], rr["n"], rr["mean"], rr["p50"], rr["p90"],
                    100 * rr["within"]["2"], 100 * rr["within"]["8"], 100 * rr["within"]["16"]))
    L.append("</table>")
    L.append('<p class="note">单位：分析宽度 768 px 下的像素。'
             '换算到世界尺度 ≈ <code>orthoSize/帧宽</code>：前/侧视 44 m ÷ (768·2040/1080) px ≈ 0.030 m/px，'
             '故 p90=13 px ≈ 0.4 m、p90=16 px ≈ 0.5 m。</p>')

    L.append("<h2>叠图（红=我们的轮廓，青=渲染检测到的边）</h2>")
    for d, r in rows:
        v = d["view"]
        cand = [p for name, p in ov.items() if ("_%s_" % v) in name]
        shown = False
        for p in cand:
            uri = data_uri(p)
            if uri:
                L.append('<div class="card"><h3 style="margin:4px 0 8px">%s</h3>'
                         '<img src="%s" alt="%s overlay"><p class="note">%s</p></div>'
                         % (html.escape(v), uri[0], html.escape(v),
                            "青=渲染边，红=投影轮廓；青色远多于红色 = 渲染细节远超体积盒模型所能描述"))
                shown = True
                break
        if not shown:
            L.append('<p class="note">（%s 叠图缺失）</p>' % html.escape(v))

    L.append("<h2>怎么读这组数</h2><div class=\"card\"><ul>")
    L.append("<li><b>ref→render 小</b> = 我们的轮廓落在渲染的真实边上 → 体量与注册对。</li>")
    L.append("<li><b>render→ref 必然很大</b>：渲染里还有瓦垄、植被、地形、AO 等细节边，24 个体积盒<b>本来就解释不了</b>。"
             "所以 render→ref <b>不得</b>当作缺陷指标。</li>")
    L.append("<li><b>p90 与最佳平移</b>用来区分“整体偏了”与“形状不对”：平移后 p90 明显下降 = 整体偏移；"
             "几乎不变 = 形状/尺度问题。</li>")
    L.append("<li><b>不得</b>把本表的数当 `references/04` 的门禁阈值：它尚未在本工程留下“人为做坏”的负样本对照。</li>")
    L.append("</ul></div>")

    L.append("<h2>已知局限</h2><div class=\"card\"><ul>"
             "<li>轮廓粒度=体积盒并集，<b>不是</b>逐体素占用；屋顶阶梯、檐口深度等高阶形状表达不出来。</li>"
             "<li>X/Z 用节点盒（审计未给实心范围），可能比实心范围大。</li>"
             "<li>渲染边用 Otsu 自适应阈值，随画面内容漂移；跨轮比较必须固定阈值并登记。</li>"
             "<li>没有做遮挡消隐；正/侧视会被前景体积的边界“穿插”。</li>"
             "</ul></div>")

    L.append("</div></body></html>")
    doc = "".join(L)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8", newline="\n").write(doc)
    print("views=%d bytes=%d -> %s" % (len(rows), len(doc.encode("utf-8")), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
