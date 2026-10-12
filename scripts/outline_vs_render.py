#!/usr/bin/env python3
"""轮廓 vs 渲染边缘：把投影轮廓叠到正交渲染帧上，量"两者是否落在同一条边上"。

为什么不用控制帧差分：实测移走主体后**全局光照也变了**（控制帧退化成纯天空，
连四角差异都 >60），差分掩膜被气氛变化污染。控制帧路线要成立，需要"主体仍参与光照、
只对相机不可见"的能力，当前引擎 API 不提供。

本工具走的是"人类本来就会做的事"：把算出的轮廓叠在渲染帧上，量它落不落在渲染的真实边上。
指标不叫 IoU（不是同一类量的面积比），而叫 **边缘一致度**：
  * `refToRender.*`  ：我们轮廓上每个像素到最近渲染边的距离 → mean / p50 / p90 / 分档覆盖率
  * `renderToRef.*`  ：反过来，渲染边上每个像素到最近轮廓的距离（查"漏画了什么"）
  * `bestPixelShift` ：在 ±N px 平移里找最小 p90（区分"整体偏了"与"形状不对"）

依赖：仅 Pillow。距离变换用多源 BFS（不做 8SSEDT，够用且可复现）。

usage:
  python outline_vs_render.py --projection projection.json --view front \
      --render r4_02_front_ortho.png --ortho-size 44 --center 0,17,0 \
      --out-json edge.json --out-overlay overlay.png [--flip-h|--auto-flip] [--width 1024]

exit: 0 ok · 1 退化（任一侧没有边缘）· 2 用法/IO 错
"""

import argparse
import json
import math
import os
import sys
from collections import deque

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    print("FAIL Pillow required")
    raise SystemExit(2)

AXES = {"front": ("x", "y"), "side": ("z", "y"), "top": ("x", "z")}
IDX = {"x": 0, "y": 1, "z": 2}
NEIGH = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
BANDS = (2, 4, 8, 16)


def parse_res(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def parse_center(s):
    p = [float(x) for x in s.split(",")]
    return p + [0.0] * (3 - len(p))


def world_to_px(u, v, view, ortho, W, H, center, flip_h):
    hu, vv = AXES[view]
    cu, cv = center[IDX[hu]], center[IDX[vv]]
    sx = H / float(ortho)                      # 竖向上的 px/m
    x = W / 2.0 + (u - cu) * sx
    y = H / 2.0 - (v - cv) * sx
    return (W - x if flip_h else x), y


def raster_outline(proj, view, ortho, W, H, center, flip_h, width=2):
    img = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in proj["views"][view]["outline"]:
        a = world_to_px(x0, y0, view, ortho, W, H, center, flip_h)
        b = world_to_px(x1, y1, view, ortho, W, H, center, flip_h)
        dr.line([a, b], fill=255, width=width)
    return img


def render_edges(path, W, H, thr=None):
    im = Image.open(path).convert("L")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    e = im.filter(ImageFilter.FIND_EDGES)
    if thr is None:
        h = e.histogram()
        tot = sum(h)
        # Otsu
        sa = sum(i * c for i, c in enumerate(h)); wb = 0; sb = 0; best = (0, -1)
        for t in range(256):
            wb += h[t]
            if not wb:
                continue
            wf = tot - wb
            if not wf:
                break
            sb += t * h[t]
            v = wb * wf * ((sb / wb) - ((sa - sb) / wf)) ** 2
            if v > best[1]:
                best = (t, v)
        thr = max(best[0], 12)
    return e.point(lambda v: 255 if v > thr else 0), thr, e


def distance_map(bits, W, H):
    """多源 BFS：每个像素到最近 true 像素的距离（px）。"""
    INF = 1 << 30
    dist = [INF] * (W * H)
    q = deque()
    for i, b in enumerate(bits):
        if b:
            dist[i] = 0
            q.append(i)
    while q:
        i = q.popleft()
        d = dist[i] + 1
        x, y = i % W, i // W
        for dx, dy in NEIGH:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                j = ny * W + nx
                if dist[j] > d:
                    dist[j] = d
                    q.append(j)
    return dist


def stat(vals):
    if not vals:
        return None
    vals = sorted(vals)
    n = len(vals)
    pick = lambda p: vals[min(n - 1, int(p * n))]
    return {"n": n,
            "mean": round(sum(vals) / n, 3),
            "p50": pick(0.50), "p90": pick(0.90), "p99": pick(0.99),
            "max": vals[-1],
            "within": {str(b): round(sum(1 for v in vals if v <= b) / n, 4) for b in BANDS}}


def evaluate(ref_img, render_img, W, H, shift=(0, 0)):
    rf = list(ref_img.getdata())
    rd = list(render_img.getdata())
    if shift != (0, 0):
        sx, sy = shift
        out = []
        for y in range(H):
            sy2 = y - sy
            for x in range(W):
                sx2 = x - sx
                out.append(rf[sy2 * W + sx2] if 0 <= sx2 < W and 0 <= sy2 < H else 0)
        rf = out
    ref_bits = [1 if v > 127 else 0 for v in rf]
    ren_bits = [1 if v > 127 else 0 for v in rd]
    if not any(ref_bits) or not any(ren_bits):
        return None
    d_ren = distance_map(ren_bits, W, H)
    d_ref = distance_map(ref_bits, W, H)
    a = [d_ren[i] for i, b in enumerate(ref_bits) if b]
    b_ = [d_ref[i] for i, b in enumerate(ren_bits) if b]
    return {"refToRender": stat(a), "renderToRef": stat(b_)}


def overlay(render_path, ref_img, render_img, W, H, out):
    base = Image.open(render_path).convert("RGB")
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)
    base = base.point(lambda v: int(v * 0.55))            # 压暗底图
    ov = base.copy()
    px = ov.load()
    rp, ep = ref_img.load(), render_img.load()
    for y in range(H):
        for x in range(W):
            if ep[x, y] > 127:
                px[x, y] = (0, 190, 190)                  # 渲染边 = 青
    for y in range(H):
        for x in range(W):
            if rp[x, y] > 127:
                px[x, y] = (255, 60, 60)                  # 我们的轮廓 = 红
    ov.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projection", required=True)
    ap.add_argument("--view", required=True, choices=sorted(AXES))
    ap.add_argument("--render", required=True)
    ap.add_argument("--ortho-size", type=float, required=True)
    ap.add_argument("--center", required=True)
    ap.add_argument("--res", default=None, help="WxH，默认取渲染帧尺寸")
    ap.add_argument("--width", type=int, default=1024, help="分析宽度（等比缩放）")
    ap.add_argument("--flip-h", action="store_true")
    ap.add_argument("--auto-flip", action="store_true", help="两个手性都算，取 p90 更小者")
    ap.add_argument("--shift-scan", type=int, default=8, help="在 ±N px 内找最佳整体平移（0=关闭）")
    ap.add_argument("--edge-thr", type=int, default=None)
    ap.add_argument("--out-json")
    ap.add_argument("--out-overlay")
    a = ap.parse_args()

    proj = json.load(open(a.projection, encoding="utf-8")) if os.path.isfile(a.projection) else None
    if proj is None:
        print("projection not found:", a.projection)
        return 2
    if not os.path.isfile(a.render):
        print("render not found:", a.render)
        return 2
    if a.view not in proj.get("views", {}):
        print("view not in projection:", a.view)
        return 1

    rw, rh = Image.open(a.render).size if not a.res else parse_res(a.res)
    W = a.width
    H = max(1, int(round(W * rh / float(rw))))
    center = parse_center(a.center)

    render_img, thr, _ = render_edges(a.render, W, H, a.edge_thr)
    flips = [True, False] if (a.auto_flip or a.flip_h is False and a.auto_flip) else [a.flip_h]
    if a.auto_flip:
        flips = [False, True]

    results = {}
    best = None
    for flip in flips:
        ref_img = raster_outline(proj, a.view, a.ortho_size, W, H, center, flip)
        ev = evaluate(ref_img, render_img, W, H)
        if ev is None:
            results["flip" if flip else "normal"] = {"degenerate": True}
            continue
        entry = {"flipH": flip, **ev}
        if a.shift_scan > 0:
            base_p90 = ev["refToRender"]["p90"]
            best_shift, best_p90 = (0, 0), base_p90
            for sx in range(-a.shift_scan, a.shift_scan + 1):
                for sy in range(-a.shift_scan, a.shift_scan + 1):
                    if abs(sx) + abs(sy) > a.shift_scan:
                        continue
                    e2 = evaluate(ref_img, render_img, W, H, (sx, sy))
                    if e2 and e2["refToRender"]["p90"] < best_p90:
                        best_p90, best_shift = e2["refToRender"]["p90"], (sx, sy)
            entry["bestPixelShift"] = list(best_shift)
            entry["p90AtBestShift"] = best_p90
            entry["p90AtZeroShift"] = base_p90
        results["flip" if flip else "normal"] = entry
        key = entry["refToRender"]["p90"]
        if best is None or key < best[1]:
            best = (flip, key, ref_img)

    if best is None:
        print("DEgenerate: 没有可用边缘")
        return 1
    flip, _, best_ref = best
    if a.out_overlay:
        overlay(a.render, best_ref, render_img, W, H, a.out_overlay)
    info = {"schema": "urhox-outline-vs-render/1",
            "view": a.view, "render": os.path.abspath(a.render),
            "orthoSize": a.ortho_size, "center": center, "analysisRes": [W, H],
            "renderEdgeThreshold": thr, "edgeBands": list(BANDS),
            "chosenFlipH": flip, "results": results,
            "note": ("边缘一致度，不是掩膜 IoU（两者不是同一类量）；"
                     "refToRender=我们轮廓被渲染支持的程度，renderToRef=我们漏掉了多少渲染边")}
    if a.out_json:
        json.dump(info, open(a.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"view": a.view, "chosenFlipH": flip,
                      "refToRender": results["flip" if flip else "normal"]["refToRender"],
                      "renderToRef": results["flip" if flip else "normal"]["renderToRef"],
                      "shift": results["flip" if flip else "normal"].get("bestPixelShift"),
                      "p90@0": results["flip" if flip else "normal"].get("p90AtZeroShift"),
                      "p90@best": results["flip" if flip else "normal"].get("p90AtBestShift")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
