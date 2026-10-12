#!/usr/bin/env python3
"""投影 → 正交掩膜：把 projection.json 按正交相机参数映射成与引擎渲染同尺寸的二值掩膜。

这是"占用出图"与"渲染通道"之间的桥：有了它，`compare_masks.py` 才能拿投影当 ref、
拿正交渲染当 render 求 IoU（同类比同类，见 references/21 §7）。

映射约定（Urho3D 正交相机）：
  orthoSize = **竖向**世界尺寸；横向 = orthoSize × (W/H)
  px_u = W/2 + (world_u - center_u) / (orthoSize × W/H) × W
  px_v = H/2 - (world_v - center_v) / orthoSize × H      （图像 y 向下）

水平手性：不同引擎/朝向会导致屏幕右方向相反。脚本对两个方向都算，
默认取"前景占比更接近渲染侧"的那个；也可用 --flip-h 强制，并会在产物里标注。

usage:
  python projection_to_mask.py --projection <projection.json> --view front \
      --ortho-size 44 --res 2040x1080 --center 0,17 --out mask_front.png [--flip-h]

exit: 0 ok · 1 视图不存在 · 2 用法错
"""

import argparse
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("FAIL Pillow required")
    raise SystemExit(2)

# 视图 → (水平轴, 竖向轴) ；up=y 时立面竖向轴是 Y（见 references/21 §3）
AXES = {
    "front": ("x", "y"),
    "side": ("z", "y"),
    "top": ("x", "z"),
}
IDX = {"x": 0, "y": 1, "z": 2}


def parse_res(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def parse_center(s):
    parts = [float(x) for x in s.split(",")]
    return parts + [0.0] * (3 - len(parts))


def rect_px(rect, view, ortho, W, H, center, flip_h):
    """rect = [u0, v0, u1, v1]（世界，米）→ 像素矩形 [x0,y0,x1,y1]。"""
    hu, vv = AXES[view]
    u0, v0, u1, v1 = rect
    cu, cv = center[IDX[hu]], center[IDX[vv]]
    sx = W / (ortho * W / float(H))          # 世界→像素（水平）
    sy = H / float(ortho)                    # 世界→像素（竖向）
    x0 = W / 2.0 + (u0 - cu) * sx
    x1 = W / 2.0 + (u1 - cu) * sx
    y0 = H / 2.0 - (v1 - cv) * sy            # 上边界
    y1 = H / 2.0 - (v0 - cv) * sy            # 下边界
    if flip_h:
        x0, x1 = W - x1, W - x0
    return [x0, y0, x1, y1]


def render_mask(proj, view, ortho, W, H, center, flip_h, mode="fill"):
    img = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(img)
    for r in proj["views"][view]["rects"]:
        x0, y0, x1, y1 = rect_px(r["rect"], view, ortho, W, H, center, flip_h)
        x0, y0 = math.ceil(x0 - 0.5), math.ceil(y0 - 0.5)
        x1, y1 = math.ceil(x1 - 0.5) - 1, math.ceil(y1 - 0.5) - 1
        if x1 < x0 or y1 < y0:
            continue
        if mode == "fill":
            dr.rectangle([x0, y0, x1, y1], fill=255)
        else:
            dr.rectangle([x0, y0, x1, y1], outline=255, width=3)
    return img


def fg_ratio(img):
    h = img.histogram()
    return sum(h[128:]) / float(img.width * img.height)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projection", required=True)
    ap.add_argument("--view", required=True, choices=sorted(AXES))
    ap.add_argument("--ortho-size", type=float, required=True, help="正交相机的竖向世界尺寸（米）")
    ap.add_argument("--res", required=True, help="WxH，例如 2040x1080")
    ap.add_argument("--center", required=True, help="相机 target 的世界坐标 x,y,z，例如 0,17,0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--flip-h", action="store_true")
    ap.add_argument("--auto-flip", action="store_true",
                    help="两个水平方向都算，输出两者；供人工/下游挑选")
    ap.add_argument("--mode", choices=("fill", "outline"), default="fill")
    a = ap.parse_args()

    if not os.path.isfile(a.projection):
        print("projection not found:", a.projection)
        return 2
    proj = json.load(open(a.projection, encoding="utf-8"))
    if a.view not in proj.get("views", {}):
        print("view not in projection:", a.view, list(proj.get("views", {})))
        return 1
    if proj.get("upAxis", "y") != "y":
        print("WARN upAxis=%s，本脚本的 AXES 按 Y-up 定义；请先确认轴契约" % proj.get("upAxis"))

    W, H = parse_res(a.res)
    center = parse_center(a.center)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    base = os.path.splitext(a.out)[0]
    info = {"view": a.view, "orthoSize": a.ortho_size, "res": [W, H], "center": center,
            "mode": a.mode, "upAxis": proj.get("upAxis")}
    if a.auto_flip:
        outs = {}
        for flip in (False, True):
            p = "%s%s.png" % (base, "_flipped" if flip else "")
            img = render_mask(proj, a.view, a.ortho_size, W, H, center, flip, a.mode)
            img.save(p)
            outs["flipped" if flip else "normal"] = {"path": p, "fgRatio": round(fg_ratio(img), 5)}
        info["outputs"] = outs
        json.dump(info, open(base + ".maskinfo.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0

    img = render_mask(proj, a.view, a.ortho_size, W, H, center, a.flip_h, a.mode)
    img.save(a.out)
    info.update({"flipH": a.flip_h, "path": a.out, "fgRatio": round(fg_ratio(img), 5)})
    json.dump(info, open(base + ".maskinfo.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
