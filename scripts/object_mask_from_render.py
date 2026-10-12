#!/usr/bin/env python3
"""从"对象帧 + 控制帧"差出对象掩膜（渲染侧掩膜的唯一可靠来源）。

为什么需要它：`compare_masks.py` 做投影级对照时要两侧都有掩膜。投影侧我们能自算
（`projection_to_mask.py`），但**渲染侧没有**——正交渲染帧的 alpha 是全 255，
按亮度 Otsu 取到的往往是"整幅暗部"（含地面、触边），用它算 IoU 会得到
"bbox=全画面 + size_drift≈30%" 的假失败。

唯一可靠做法是**控制组**：同机位、同灯光、同时间，**只把被摄对象隐藏**再渲一次，
两帧相减即对象掩膜。这与本工程"参考侧必须有控制组"的既有纪律一致。

控制帧怎么出：在机位定义里跳过主体构建（或把主体根节点 SetEnabled(false)）后重渲同机位。
需要一次运行时渲染，属于 G6 侧工作；本脚本只负责"有了两帧之后的确定性地基"。

usage:
  python object_mask_from_render.py --object a.png --control b.png --out mask.png \
      [--thr 8] [--channel rgb|a|rgba] [--res 2040x1080] [--out-json info.json]

exit: 0 ok · 1 掩膜退化（几乎全画面或几乎为空）· 2 用法/IO 错
"""

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageChops, ImageFilter
except ImportError:
    print("FAIL Pillow required")
    raise SystemExit(2)


def load(p, channel):
    im = Image.open(p)
    im.load()
    if channel in ("a",) and "A" in im.getbands():
        return im.convert("RGBA")
    return im.convert("RGB")


def build_mask(obj, ctrl, thr, blur=0):
    if obj.size != ctrl.size:
        ctrl = ctrl.resize(obj.size, Image.NEAREST)
    diff = ImageChops.difference(obj, ctrl).convert("L")
    if blur:
        diff = diff.filter(ImageFilter.GaussianBlur(blur))
    return diff.point(lambda v: 255 if v > thr else 0), diff


def stats(mask):
    h = mask.histogram()
    tot = float(mask.width * mask.height)
    fg = sum(h[128:])
    # 触边检查：四边各取一圈 2px 采样
    W, H = mask.size
    px = mask.load()
    edge = 0
    for x in range(W):
        for y in (0, 1, H - 2, H - 1):
            if px[x, y] > 128:
                edge += 1
    for y in range(H):
        for x in (0, 1, W - 2, W - 1):
            if px[x, y] > 128:
                edge += 1
    bbox = mask.getbbox()
    return {"fgRatio": round(fg / tot, 5), "edgePixels": edge,
            "edgeRatio": round(edge / float(2 * (W + H) * 2 * 2), 5),
            "bbox": bbox}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", required=True, help="含被摄对象的正交渲染帧")
    ap.add_argument("--control", required=True, help="同机位、仅隐藏对象的控制帧")
    ap.add_argument("--out", required=True)
    ap.add_argument("--out-json")
    ap.add_argument("--thr", type=int, default=8, help="差分阈值（0-255）")
    ap.add_argument("--blur", type=int, default=1, help="差分前高斯模糊半径（抑制抗锯齿噪声）")
    ap.add_argument("--channel", choices=("rgb", "a", "rgba"), default="rgb")
    a = ap.parse_args()

    for p in (a.object, a.control):
        if not os.path.isfile(p):
            print("not found:", p)
            return 2
    obj, ctrl = load(a.object, a.channel), load(a.control, a.channel)
    if obj.size != ctrl.size:
        print("WARN size differs %s vs %s -> control resized" % (obj.size, ctrl.size))
    mask, diff = build_mask(obj, ctrl, a.thr, a.blur)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    mask.save(a.out)
    st = stats(mask)
    info = {"schema": "urhox-object-mask-from-control/1",
            "object": os.path.abspath(a.object), "control": os.path.abspath(a.control),
            "thr": a.thr, "blur": a.blur, "channel": a.channel,
            "size": list(obj.size), **st}
    # 退化判据（用于挡住"拿错帧也能算出数"的假结果）
    degenerate = []
    if st["fgRatio"] > 0.9:
        degenerate.append("前景占比 %.3f > 0.9：两帧几乎相同或对象未隐藏" % st["fgRatio"])
    if st["fgRatio"] < 1e-4:
        degenerate.append("前景占比 %.6f ≈ 0：控制帧没差出对象" % st["fgRatio"])
    info["degenerate"] = degenerate
    info["verdict"] = "OK" if not degenerate else "DEGENERATE"
    if a.out_json:
        json.dump(info, open(a.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0 if not degenerate else 1


if __name__ == "__main__":
    sys.exit(main())
