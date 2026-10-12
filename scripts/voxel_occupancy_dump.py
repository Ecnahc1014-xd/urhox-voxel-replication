#!/usr/bin/env python3
"""逐体素占用导出（**日志通道**）: 以各工程自己的 `shot_template.lua` 为基底注入 dump。

## 为什么是这个形态（全部为 2026-09-23 实测结论）

1. **不能自带 Lua 模板**：结构相近的自制模板会让引擎在引导阶段直接崩
   （日志停在 `InputAdaptor`，连 `Loaded Lua script` 都不出现，无报错）；
   同一套参数 + 该工程自己的模板则完全正常。→ 改为**读工程模板 + 注入**。
2. **引擎 `File()` 写不了文件**：offline runtime 下 `File(path, FILE_WRITE)` 返回 nil
   （`docs` 与 `shots.py` 都写了这一点：*the offline runtime cannot open files outside its own tree*）。
   审计数据一直走日志里的 `AUDITJSON` 行。→ **占用也走日志**。
3. **不能不带 `-screenshot`**：离线 runtime 是游戏循环，没有截图请求永不退出。
4. **引擎不能建目录**：`project_info.json` 里的 `stage/log/audit` 目录不存在时脚本不会被加载。

## 为什么导剪影而不是全格列表

三视图只需要三个 2D 占用位图（front=X×Y / side=Z×Y / top=X×Z）；
全格列表在日志里要几 MB～几十 MB，而三个位图打包成 hex 只有几 KB，
且**逐体积计数**一起给出——真实体积 = Σcount × vs³（替掉体积盒那个 5.07× 上界估算）。

usage:
  python voxel_occupancy_dump.py --project <工程目录> --out <占用文件.json> [--timeout 900]

exit: 0 ok · 1 导出失败 · 2 用法/环境错
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VERSION_FILE = Path(r"D:/tools/UrhoXEditor/installation.json")
GEN_NAME = "_voxel_dump.lua"
BUILD_RX = re.compile(r"^(\s*)local\s+kit\s*=\s*VoxCore\.BuildSubject\(.*\)\s*$", re.M)
MARK = "[dump]"

HOOK = r'''
-- ==== 注入：逐体素占用导出（由 scripts/voxel_occupancy_dump.py 生成，请勿手改）====
local function __hexbits(bits, n)
    -- 按 8 位一组打包成 hex，位序：低位先（bit0 = 该组第一个像素）
    -- **必须显式传 n**：bits 是稀疏表，`#bits` 的边界未定义——
    -- 实测 `#front`/`#top` 会给出远小于真实值的结果（掩码被截断、top 直接空）。
    local out = {}
    for i = 1, n, 8 do
        local b = 0
        for j = 0, 7 do
            local idx = i + j
            if idx <= n and bits[idx] then b = b + 2 ^ j end
        end
        out[#out + 1] = string.format('%02x', b)
    end
    return table.concat(out)
end

local function DumpOccupancy(kit, subjName)
    -- 日志目录被所有工程共用：每条输出都带 subject 标签（与 kit:Log 的审计行同规）
    local pfx = '[' .. tostring(subjName) .. '] [dump] '
    if kit == nil or kit.cells == nil then print(pfx .. 'ERROR no kit.cells') return end
    local minx, miny, minz = math.huge, math.huge, math.huge
    local maxx, maxy, maxz = -math.huge, -math.huge, -math.huge
    local n = 0
    for k in pairs(kit.cells) do
        local x, y, z = k:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
        if x then
            x, y, z = tonumber(x), tonumber(y), tonumber(z)
            n = n + 1
            if x < minx then minx = x end
            if y < miny then miny = y end
            if z < minz then minz = z end
            if x > maxx then maxx = x end
            if y > maxy then maxy = y end
            if z > maxz then maxz = z end
        end
    end
    if n == 0 then print(pfx .. 'ERROR empty kit.cells') return end
    local dx, dy, dz = maxx - minx + 1, maxy - miny + 1, maxz - minz + 1
    local front, side, top = {}, {}, {}
    local vols = {}
    for k, owner in pairs(kit.cells) do
        local x, y, z = k:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
        x, y, z = tonumber(x), tonumber(y), tonumber(z)
        front[(y - miny) * dx + (x - minx) + 1] = true      -- DX 宽 / DY 高
        side[(y - miny) * dz + (z - minz) + 1] = true       -- DZ 宽 / DY 高
        top[(z - minz) * dx + (x - minx) + 1] = true        -- DX 宽 / DZ 高
        vols[owner] = (vols[owner] or 0) + 1
    end
    local vparts = {}
    for name, c in pairs(vols) do vparts[#vparts + 1] = string.format('"%s":%d', tostring(name), c) end
    table.sort(vparts)
    print(pfx .. 'meta ' .. string.format(
        '{"subject":"%s","voxelSize":%.6f,"base":%.6f,"cells":%d,"min":[%d,%d,%d],"max":[%d,%d,%d],"dims":[%d,%d,%d]}',
        tostring(subjName), kit.vs, kit.base, n, minx, miny, minz, maxx, maxy, maxz, dx, dy, dz))
    print(pfx .. 'front ' .. __hexbits(front, dx * dy))
    print(pfx .. 'side ' .. __hexbits(side, dz * dy))
    print(pfx .. 'top ' .. __hexbits(top, dx * dz))
    print(pfx .. 'volumes {' .. table.concat(vparts, ',') .. '}')
end
local function __dumpCall(kit, subjName)
    local ok, err = pcall(DumpOccupancy, kit, subjName)
    if not ok then print('[dump] ERROR pcall: ' .. tostring(err)) end
end
-- ==== 注入结束 ====
'''


def runtime_dir() -> Path:
    release = None
    if VERSION_FILE.exists():
        try:
            release = json.loads(VERSION_FILE.read_text(encoding="utf-8")).get("current_release")
        except json.JSONDecodeError:
            release = None
    root = Path(r"D:/tools/UrhoXEditor/versions")
    if release and (root / release / "UrhoXRuntime.exe").exists():
        return root / release
    cands = sorted([p for p in root.glob("*/UrhoXRuntime.exe")], key=lambda p: p.stat().st_mtime)
    if not cands:
        raise SystemExit("no UrhoXRuntime.exe under D:/tools/UrhoXEditor/versions")
    return cands[-1].parent


def lua_log_dir() -> Path:
    return runtime_dir() / "logs" / "lua"


def unwrap(text, ids):
    """hex → 位数组（低位先），返回 set 形式的下标集合。"""
    out = []
    for i, ch in enumerate(text):
        b = int(ch, 16)
        for j in range(8):
            out.append(bool(b & (1 << j)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--keep-lua", action="store_true")
    a = ap.parse_args()

    proj = Path(a.project).resolve()
    tpl = proj / "tools" / "shot_template.lua"
    for rel in ("scripts/voxcore.lua", "scripts/subject.lua", "tools/shot_template.lua"):
        if not (proj / rel).is_file():
            print("FAIL 工程缺少 %s" % rel)
            return 2

    # 引擎不能建目录：缺目录会导致脚本不被加载（日志停在 InputAdaptor、无报错）
    info_path = proj / "tools" / "project_info.json"
    subject_name = proj.name
    if info_path.is_file():
        pinfo = json.loads(info_path.read_text(encoding="utf-8"))
        subject_name = pinfo.get("subject") or subject_name
        for key in ("stage", "log", "audit"):
            raw = pinfo.get(key)
            if raw:
                d = Path(raw)
                (d.parent if key in ("log", "audit") else d).mkdir(parents=True, exist_ok=True)

    src = tpl.read_text(encoding="utf-8").replace("__VIEW_INDEX__", "1").replace("__CHANNEL__", "C")
    m = BUILD_RX.search(src)
    if not m:
        print("FAIL 在 shot_template.lua 里找不到 `local kit = VoxCore.BuildSubject(...)` 注入点")
        return 2
    src = src[:m.end()] + ("\n%s__dumpCall(kit, (subject and subject.NAME) or 'unknown')" % m.group(1)) + src[m.end():]
    gen = proj / "scripts" / GEN_NAME
    gen.write_text(HOOK + "\n" + src, encoding="utf-8")

    binary = runtime_dir() / "UrhoXRuntime.exe"
    stage = Path(json.loads(info_path.read_text(encoding="utf-8")).get("stage", "D:/tools/shots")) \
        if info_path.is_file() else Path("D:/tools/shots")
    stage.mkdir(parents=True, exist_ok=True)
    exit_png = stage / "_dump_exit.png"
    if exit_png.exists():
        exit_png.unlink()

    started = time.time()
    args = [GEN_NAME, "-tapcode_dir=%s" % proj, "-skip_login", "-log", "info",
            "-screenshot=%s" % exit_png, "-screenshot-frame=30", "-x", "320", "-y", "240"]
    try:
        proc = subprocess.run([str(binary), *args], cwd=str(binary.parent),
                              capture_output=True, timeout=a.timeout)
        log = (proc.stdout or b"").decode("utf-8", errors="replace")
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or b"").decode("utf-8", errors="replace")
        err = "TIMEOUT"
    if exit_png.exists():
        exit_png.unlink()
    if not a.keep_lua and gen.exists():
        gen.unlink()

    # 从 lua 日志里取 dump 行（日志目录被三个工程共用 → 按 subject 标签 + mtime 双重绑定）
    tag = "[" + subject_name + "]"
    blocks = {"meta": None, "front": None, "side": None, "top": None, "volumes": None}
    scanned = 0
    # 绑定键必须能唯一定位"本次运行"：lua 日志目录被所有工程共用，
    # 且**并发会话会持续写入新日志**，所以"取最新 N 个"会串台（实测踩到过）。
    # 用脚本名当唯一标记：`_voxel_dump.lua` 只可能来自本次导出。
    for path in sorted(lua_log_dir().glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.stat().st_mtime < started - 120.0:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # lua 日志只收 Lua 的 print()（engine 自己的 INFO 行走 stdout），
        # 所以绑定键用我们自己的 `[dump]` 标记，而不是脚本名。
        if (MARK + " meta") not in text:
            continue
        scanned += 1
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("m", "")
            if MARK not in msg or tag not in msg:
                continue
            body = msg.split(MARK, 1)[1].strip()
            for key in blocks:
                if body.startswith(key + " "):
                    blocks[key] = body[len(key) + 1:].strip()
        if all(blocks.values()):
            break
    if a.keep_lua and gen.exists():
        pass

    if not all(v is not None for v in blocks.values()):
        missing = [k for k, v in blocks.items() if v is None]
        print("FAIL 未从日志取到 dump 数据，缺: %s（扫了 %d 个日志）" % (missing, scanned))
        for ln in (log + err).splitlines():
            if any(k in ln for k in (MARK, "ERROR", "Loaded Lua script " + GEN_NAME)):
                print("   ", ln[:200])
        return 1

    meta = json.loads(blocks["meta"])
    dx, dy, dz = meta["dims"]
    masks = {}
    for view, expect in (("front", dx * dy), ("side", dz * dy), ("top", dx * dz)):
        bits = unwrap(blocks[view], None)
        if len(bits) < expect:
            bits += [False] * (expect - len(bits))
        masks[view] = bits[:expect]
    vols = json.loads(blocks["volumes"])

    def pack(bits):
        b = bytearray()
        for i in range(0, len(bits), 8):
            v = 0
            for j in range(8):
                if i + j < len(bits) and bits[i + j]:
                    v |= 1 << j
            b.append(v)
        return base64.b64encode(bytes(b)).decode("ascii")

    out_doc = {
        "schema": "urhox-occupancy-masks/1",
        "subject": meta["subject"],
        "voxelSizeMeters": meta["voxelSize"],
        "base": meta["base"],
        "cellCount": meta["cells"],
        "bbox": {"min": meta["min"], "max": meta["max"], "dims": meta["dims"]},
        "upAxis": "y",
        "views": {
            "front": {"h": dx, "v": dy, "hAxis": "x", "vAxis": "y", "bits": pack(masks["front"])},
            "side": {"h": dz, "v": dy, "hAxis": "z", "vAxis": "y", "bits": pack(masks["side"])},
            "top": {"h": dx, "v": dz, "hAxis": "x", "vAxis": "z", "bits": pack(masks["top"])},
        },
        "volumeCells": vols,
        "bitPacking": "row-major; within each byte bit0 = first pixel (LSB first)",
        "channel": "lua log line [dump] (引擎 File() 在 offline runtime 下不可用)",
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_doc, ensure_ascii=False, indent=1), encoding="utf-8")

    true_volume = meta["cells"] * (meta["voxelSize"] ** 3)
    print(json.dumps({
        "file": str(out), "subject": meta["subject"], "cells": meta["cells"],
        "dims": meta["dims"], "voxelSize": meta["voxelSize"],
        "trueSolidVolumeM3": round(true_volume, 3),
        "volumes": len(vols), "bytes": out.stat().st_size,
        "frontOn": sum(masks["front"]), "sideOn": sum(masks["side"]), "topOn": sum(masks["top"]),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
