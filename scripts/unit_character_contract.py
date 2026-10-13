#!/usr/bin/env python3
"""单位方块与人物格数两条强规则 — 机器检查（`references/08` §3.1 的落地）。

判据的**唯一出处**：`references/08-subject-classes-and-scales.md` §3.1。
本脚本只读：扫描工程文件里的单位方块常量定义，核对契约 JSON，产读数与结论，
不改任何工程数据。它是**仪器**（报警不停手）；要升级成可拦人门禁，须先在真实
工程留下负样本并按 `references/04` §0 的两条前置条件登记。

usage:
  PYTHONUTF8=1 python unit_character_contract.py --contract <contract.json> [--scan <根目录>] [--out <目录>] [--json-only]
  python unit_character_contract.py --self-test

contract.json 字段：
{
  "world": {"voxel_size_m": 0.1, "grid_tolerance": 0.0001},
  "character": {"standing_height_m": 1.7, "crouch_height_m": 1.3, "prone_height_m": 0.6,
                "radius_m": 0.25, "stand_radius_m": 0.35},
  "scan": {"root": ".", "exts": [".lua", ".py", ".json", ".yaml", ".yml"],
           "exclude_dirs": ["tests", "tmp", "fixtures"],
           "allowed_definition_files": []},
  "clearances": [{"name": "door", "height_m": 2.1}]
}

检查项：
  C1 单位方块定义唯一：定义命中文件必须全部落在 allowed_definition_files（未给该字段时
     最多 1 个文件），且定义值 == voxel_size_m（容差内）。0 命中 = 口径未登记，判 FAIL。
  C2 人物站高整除方块：standing_height_m / voxel_size_m 为整数（容差内）；蹲/趴高非整数记 WARN。
  C3 姿态排序：0 < radius <= stand_radius、2*stand_radius <= height、2*radius <= prone、
     prone <= crouch <= height（缺字段跳过该项）。
  C4 净空量化：clearances[] 每个 height_m 整除方块（容差内）；空清单跳过该项。

exit: 0 通过 · 1 未通过 · 2 用法 / 输入缺失
"""

import argparse
import json
import os
import re
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# C1 定义形态：VOXEL_SIZE = 0.1 / M.VOXEL_SIZE = 0.1 / "voxelSize": 0.1 / voxel_size_m: 0.1
# （避免把 ~= / != / <= 的比较行当定义）
_DEF_PATTERN = re.compile(
    r"(?i)(voxel[\s_]?size(?:_m)?)\s*(?:(?<![~!<>])=(?!=)|:)\s*(\d+(?:\.\d+)?)"
)
_DEFAULT_EXTS = [".lua", ".py", ".json", ".yaml", ".yml"]
_EPS = 1e-9


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _num(value, name, positive=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("%s 必须是数值" % name)
    if positive and value <= 0:
        raise ValueError("%s 必须 > 0" % name)
    return float(value)


def _scan_definitions(root, exts, exclude_dirs):
    """返回 [(相对路径, 行号, 定义值)]，按发现顺序。"""
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith(".")]
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            full = os.path.join(dirpath, name)
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, start=1):
                for match in _DEF_PATTERN.finditer(line):
                    hits.append((os.path.relpath(full, root), idx, match.group(2)))
    return hits


def _is_integer_ratio(meters, voxel_size, tolerance):
    ratio = meters / voxel_size
    nearest = round(ratio)
    ok = abs(ratio - nearest) <= tolerance
    return ok, ratio, nearest


def _check(contract, root=None):
    """执行 C1–C4，返回 {"checks": [...], "verdict": "PASS"|"FAIL"}。"""
    checks = []
    verdict = "PASS"

    def add(check_id, status, detail):
        nonlocal verdict
        if status == "FAIL":
            verdict = "FAIL"
        checks.append({"id": check_id, "status": status, "detail": detail})

    world = contract.get("world") or {}
    voxel = _num(world.get("voxel_size_m"), "world.voxel_size_m", positive=True)
    tolerance = _num(world.get("grid_tolerance", 0.0001), "world.grid_tolerance", positive=True)

    # ---- C1 定义唯一 ----
    scan_cfg = contract.get("scan") or {}
    if root is None:
        root = scan_cfg.get("root") or "."
    exts = scan_cfg.get("exts") or _DEFAULT_EXTS
    exclude = set(scan_cfg.get("exclude_dirs") or [])
    allowed = set(scan_cfg.get("allowed_definition_files") or [])
    if not os.path.isdir(root):
        raise ValueError("扫描根目录不存在：%s" % root)

    hits = _scan_definitions(root, exts, exclude)
    if not hits:
        add("C1", "FAIL", "未找到任何单位方块定义命中（口径未登记），根目录=%s" % root)
    else:
        files = sorted({rel for rel, _, _ in hits})
        offsite = [f for f in files if f not in allowed]
        bad_values = [(rel, ln, v) for rel, ln, v in hits
                      if abs(float(v) - voxel) > tolerance + _EPS]
        if allowed:
            if offsite:
                add("C1", "FAIL",
                    "定义出现在未白名单文件（越界命中 %d 处；允许定义文件=%s）：%s"
                    % (len([h for h in hits if h[0] in offsite]), sorted(allowed) or "[]",
                       ", ".join("%s:%d" % (r, l) for r, l, _ in hits if r in offsite)))
            elif len(files) > len(allowed):
                add("C1", "FAIL", "定义文件数 %d > 允许数 %d：%s" % (len(files), len(allowed), files))
            elif bad_values:
                add("C1", "FAIL", "定义值与契约不符（voxel_size_m=%s，容差=%s）：%s"
                    % (voxel, tolerance, ", ".join("%s:%d=%s" % t for t in bad_values)))
            else:
                add("C1", "PASS", "定义唯一：%s（值=%s，命中 %d 处）" % (sorted(files), voxel, len(hits)))
        else:
            if len(files) > 1:
                add("C1", "FAIL", "定义文件数 %d > 1（未给 allowed_definition_files）：%s"
                    % (len(files), files))
            elif bad_values:
                add("C1", "FAIL", "定义值与契约不符（voxel_size_m=%s，容差=%s）：%s"
                    % (voxel, tolerance, ", ".join("%s:%d=%s" % t for t in bad_values)))
            else:
                add("C1", "PASS", "定义唯一：%s（值=%s）" % (files, voxel))

    # ---- C2 人物站高整除方块 ----
    char = contract.get("character") or {}
    if char:
        standing = _num(char.get("standing_height_m"), "character.standing_height_m", positive=True)
        ok, ratio, nearest = _is_integer_ratio(standing, voxel, tolerance)
        if ok:
            add("C2", "PASS", "站高 %.3f m = %.6f 格 ≈ %d 格" % (standing, ratio, nearest))
        else:
            add("C2", "FAIL", "站高 %.3f m = %.6f 格，不是整数格（最近整数 %d，容差 %s）"
                % (standing, ratio, nearest, tolerance))
        for key, label in (("crouch_height_m", "蹲高"), ("prone_height_m", "趴高")):
            value = char.get(key)
            if value is None:
                continue
            value = _num(value, "character.%s" % key, positive=True)
            ok2, ratio2, nearest2 = _is_integer_ratio(value, voxel, tolerance)
            if not ok2:
                add("C2", "WARN", "%s %.3f m = %.6f 格，不是整数格（最近整数 %d）"
                    % (label, value, ratio2, nearest2))
    else:
        add("C2", "WARN", "契约未提供 character，跳过人物格数检查")

    # ---- C3 姿态排序 ----
    if char and char.get("standing_height_m") is not None:
        height = float(char["standing_height_m"])
        prone = char.get("prone_height_m")
        crouch = char.get("crouch_height_m")
        radius = char.get("radius_m")
        stand_radius = char.get("stand_radius_m")
        required = [prone, crouch, radius, stand_radius]
        if any(v is None for v in required):
            add("C3", "WARN", "姿态字段不全（需 prone/crouch/radius/stand_radius），跳过排序校验")
        else:
            problems = []
            if not (radius > 0):
                problems.append("radius 必须 > 0")
            if not (radius <= stand_radius):
                problems.append("radius <= stand_radius 不成立")
            if not (2 * stand_radius <= height):
                problems.append("2*stand_radius <= height 不成立")
            if not (2 * radius <= prone):
                problems.append("2*radius <= proneHeight 不成立")
            if not (prone <= crouch <= height):
                problems.append("proneHeight <= crouchHeight <= height 不成立")
            if problems:
                add("C3", "FAIL", "; ".join(problems))
            else:
                add("C3", "PASS", "姿态排序成立：%.2f/%.2f/%.2f m，半径 %.2f/%.2f m"
                    % (prone, crouch, height, radius, stand_radius))
    else:
        add("C3", "WARN", "契约未提供 character，跳过姿态排序")

    # ---- C4 净空量化 ----
    clearances = contract.get("clearances") or []
    if clearances:
        bad = []
        for item in clearances:
            name = item.get("name", "<unnamed>")
            height = _num(item.get("height_m"), "clearances[%s].height_m" % name, positive=True)
            ok4, ratio4, nearest4 = _is_integer_ratio(height, voxel, tolerance)
            if not ok4:
                bad.append("%s=%.3f m（%.6f 格，最近整数 %d）" % (name, height, ratio4, nearest4))
        if bad:
            add("C4", "FAIL", "净空未按同一方块量化：%s" % "; ".join(bad))
        else:
            add("C4", "PASS", "净空全部按同一方块量化（%d 项）" % len(clearances))
    else:
        add("C4", "WARN", "契约未提供 clearances，跳过净空量化检查")

    return {"checks": checks, "verdict": verdict}


def _selftest():
    """负样本回归：好契约 PASS；五个坏样本各判 FAIL。"""
    fixture_texts = {
        "good": {"world_spec.lua": "M.VOXEL_SIZE = 0.1\n"},
        "two-definition-sites": {"world_spec.lua": "M.VOXEL_SIZE = 0.1\n",
                                  "other.lua": "VOXEL_SIZE = 0.1\n"},
        "competing-size": {"world_spec.lua": "M.VOXEL_SIZE = 0.125\n"},
        "standing-not-integer": {"world_spec.lua": "M.VOXEL_SIZE = 0.1\n"},
        "stance-order-broken": {"world_spec.lua": "M.VOXEL_SIZE = 0.1\n"},
        "clearance-not-quantized": {"world_spec.lua": "M.VOXEL_SIZE = 0.1\n"},
    }
    final = []
    for name, expected in [("good", "PASS"), ("two-definition-sites", "FAIL"),
                           ("competing-size", "FAIL"), ("standing-not-integer", "FAIL"),
                           ("stance-order-broken", "FAIL"), ("clearance-not-quantized", "FAIL")]:
        with tempfile.TemporaryDirectory() as tmp:
            for fname, text in fixture_texts[name].items():
                with open(os.path.join(tmp, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            contract = _contract_for(name)
            contract["scan"]["root"] = tmp
            verdict = _check(contract, root=tmp)["verdict"]
            ok = verdict == expected
            final.append((name, verdict, expected, ok))
            print("  %-24s verdict=%-4s expected=%-4s %s" % (name, verdict, expected, "OK" if ok else "MISMATCH"))
    passed = sum(1 for _, _, _, ok in final if ok)
    print("SELF-TEST %d/%d PASS" % (passed, len(final)))
    return 0 if passed == len(final) else 1


def _contract_for(name):
    good_world = {"voxel_size_m": 0.1, "grid_tolerance": 0.0001}
    good_char = {"standing_height_m": 1.7, "crouch_height_m": 1.3, "prone_height_m": 0.6,
                 "radius_m": 0.25, "stand_radius_m": 0.35}
    good_scan = {"exts": [".lua"], "exclude_dirs": [],
                 "allowed_definition_files": ["world_spec.lua"]}
    if name == "good":
        return {"world": dict(good_world), "character": dict(good_char), "scan": dict(good_scan),
                "clearances": [{"name": "door", "height_m": 2.1}]}
    if name == "two-definition-sites":
        return {"world": dict(good_world), "character": dict(good_char), "scan": dict(good_scan),
                "clearances": []}
    if name == "competing-size":
        return {"world": dict(good_world), "character": dict(good_char), "scan": dict(good_scan),
                "clearances": []}
    if name == "standing-not-integer":
        return {"world": dict(good_world),
                "character": {**dict(good_char), "standing_height_m": 1.75},
                "scan": dict(good_scan), "clearances": []}
    if name == "stance-order-broken":
        return {"world": dict(good_world),
                "character": {**dict(good_char), "prone_height_m": 1.5},
                "scan": dict(good_scan), "clearances": []}
    return {"world": dict(good_world), "character": dict(good_char), "scan": dict(good_scan),
            "clearances": [{"name": "door", "height_m": 2.05}]}


def main():
    parser = argparse.ArgumentParser(
        description="单位方块与人物格数两条强规则的机器检查（references/08 §3.1）")
    parser.add_argument("--contract", help="契约 JSON 路径")
    parser.add_argument("--scan", help="扫描根目录（覆盖契约里的 scan.root）")
    parser.add_argument("--out", help="把 JSON 结论写到该目录（原子写）")
    parser.add_argument("--json-only", action="store_true", help="只输出 JSON")
    parser.add_argument("--self-test", action="store_true", help="跑负样本回归后退出")
    args = parser.parse_args()

    if args.self_test:
        return _selftest()
    if not args.contract:
        parser.error("需要 --contract（或 --self-test）")

    try:
        contract = _read_json(args.contract)
        root = args.scan if args.scan else (contract.get("scan") or {}).get("root")
        result = _check(contract, root=root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.json_only:
            print(json.dumps({"verdict": "USAGE", "error": str(exc)}, ensure_ascii=False))
        else:
            print("USAGE / 输入缺失：%s" % exc)
        return 2

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        target = os.path.join(args.out, "unit_character_contract.json")
        with open(target + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        os.replace(target + ".tmp", target)

    if args.json_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for check in result["checks"]:
            print("%-4s %-6s %s" % (check["id"], check["status"], check["detail"]))
        print("VERDICT:", result["verdict"])
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
