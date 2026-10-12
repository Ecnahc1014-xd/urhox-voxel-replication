#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UrhoX 原生体素能力探针（只读）。

回答一个问题：**这个工程里，引擎已经给了哪些原生能力、哪些还没被用上？**

为什么要它：`15-urhox-native-capabilities.md` 列的能力都带"采纳判据 + 开启后必须验什么"，
但"项目到底用没用上"每次都要人去 grep。本脚本把这件事变成可复核的 JSON。

用法
----
  python urhox_capability_probe.py --project <PROJECT_ROOT> [--out report.json] [--quiet]

输出
----
  * stdout：人类可读摘要（可用 / 已用 / 可用但未用）
  * --out：完整 JSON（逐能力证据：命中的 API、所在文件、证据来源）

退出码
------
  0 = 完成（含"全部未用"的情况；这是信息不是失败）
  2 = 工程根不存在或不像 UrhoX 工程（无 .emmylua 且无 engine-docs）

只读保证：不写被扫描工程内的任何文件（--out 由调用方给路径）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 能力目录：id -> {title, apis（.emmylua 里应出现的精确签名名）, props（属性/字段式用法）, gate（要配的验收）}
# apis 用 "Class:Method" 形式；存在性判定在 .emmylua/Voxel*.d.lua 里找 "function Class:Method("
# ---------------------------------------------------------------------------
CATALOG = [
    # --- 规模与性能 ---
    dict(id="mesh-lod", title="网格 LOD 环", group="规模",
         apis=["VoxelPhysicsWorld:SetMeshLodDistance", "VoxelVolume:GetMeshLodLevel"],
         props=[], gate="消失阈值登记：1/2/4 体素凹坑在 L1/L2/L3 的可见性写进参数表"),
    dict(id="mesh-streaming", title="网格流式 + 收敛判据", group="规模",
         apis=["VoxelPhysicsWorld:SetMeshStreamingEnabled", "VoxelPhysicsWorld:GetPendingMeshJobCount",
               "VoxelPhysicsWorld:SetMeshStreamingReferencePosition"],
         props=[], gate="取帧前 GetPendingMeshJobCount()==0"),
    dict(id="screen-cull", title="屏幕裁剪", group="规模",
         apis=["VoxelPhysicsWorld:SetMeshScreenCullSize"], props=[],
         gate="无相机/无头时记录该裁剪未生效"),
    dict(id="region-dirty", title="局部脏区重建", group="规模",
         apis=["VoxelVolume:MarkRegionDirty", "VoxelVolume:GetVertexCount"], props=[],
         gate="与整体 MarkGeometryDirty 对照登记顶点数变化"),
    dict(id="dda-render", title="DDA 渲染通道", group="规模",
         apis=["VoxelPhysicsWorld:SetDdaRenderingEnabled", "VoxelPhysicsWorld:GetDdaStatsString"],
         props=[], gate="桌面/移动双平台各留一组帧；GetDdaStatsString 基线"),
    dict(id="dda-residency", title="DDA 驻留源", group="规模",
         apis=["VoxelPhysicsWorld:SetDdaResidencySourcePosition",
               "VoxelPhysicsWorld:RemoveDdaResidencySource",
               "VoxelPhysicsWorld:ClearDdaResidencySources"], props=[],
         gate="固定机位验收前预载目标区域并留 DDA 遥测"),
    dict(id="derived-render-switch", title="派生渲染开关（服务器）", group="规模",
         apis=["VoxelPhysicsWorld:SetDerivedRenderingEnabled"], props=[],
         gate="专用服务器构建断言为关"),

    # --- 观感 ---
    dict(id="shadow-volume", title="体素阴影体（Teardown 风格）", group="观感",
         apis=["VoxelPhysicsWorld:InitializeShadowVolume",
               "VoxelPhysicsWorld:InitializeShadowVolumeFromCurrentVolumes",
               "VoxelPhysicsWorld:SetShadowVolumeQuery", "VoxelPhysicsWorld:SetShadowVolumeJitter"],
         props=[], gate="bounds 覆盖全部被摄体积 + 三档查询对照 + 逐像素验收时 jitter=0"),
    dict(id="cut-color", title="断面色（剖面材质）", group="观感",
         apis=["VoxelPhysicsWorld:SetPaletteCutColor", "VoxelGrid:IsFaceExposed"], props=[],
         gate="挖开后能区分外皮/剖面两类像素"),
    dict(id="palette-bank", title="调色板分库", group="观感",
         apis=["VoxelPhysicsWorld:GetPaletteBankCount", "VoxelVolume:SetPaletteBank"],
         props=[], gate="GetPaletteBankCount() 与素材实际用色组数对账"),
    dict(id="palette-pbr", title="调色板 PBR 层", group="观感",
         apis=["VoxelPhysicsWorld:SetPaletteEntryPBR", "VoxelPhysicsWorld:GetPaletteRoughness"],
         props=[], gate="材质分区与参考图一致性（表 C）"),
    dict(id="ugc-surface", title="UGC 自定义体素着色", group="观感",
         apis=["VoxelPhysicsWorld:GetPaletteTexture", "VoxelPhysicsWorld:GetPaletteMaterial"],
         props=[], gate="非 0 库体积的采样行偏移必须单独验"),

    # --- 物理 ---
    dict(id="analytic-proxy", title="解析碰撞代理", group="物理",
         apis=["VoxelVolume:SetCollisionShapeAuto", "VoxelVolume:SetCollisionBox",
               "VoxelVolume:SetCollisionCylinderAuto", "VoxelVolume:GetCollisionShapeType"],
         props=[], gate="破坏后断言 GetCollisionShapeType() 已回 Auto（无隐形碰撞体）"),
    dict(id="collision-group", title="碰撞分组/过滤", group="物理",
         apis=["VoxelVolume:SetCollisionGroup", "VoxelVolume:SetCollisionLayerAndMask"],
         props=["collisionGroup", "collisionLayer", "collisionMask"],
         gate="机器内部不互撞 + 对外仍碰撞，两侧都测"),
    dict(id="water-buoyancy", title="水面与浮力", group="物理",
         apis=["VoxelPhysicsWorld:SetWaterEnabled", "VoxelPhysicsWorld:SetWaterLevel",
               "VoxelVolume:SetBuoyancy", "VoxelVolume:SetComOffset"],
         props=["waterEnabled", "waterLevel", "buoyancy"],
         gate="浮力水位与视觉水面高度一致"),
    dict(id="contact-events", title="接触事件", group="物理",
         apis=["VoxelPhysicsWorld:SetContactEventThreshold"], props=["contactEventThreshold"],
         gate="设阈值后事件确实到达（默认 0 = 关闭）"),

    # --- 破坏与建造 ---
    dict(id="damage-basic", title="点位/世界点伤害", group="破坏",
         apis=["VoxelPhysicsWorld:ApplyDamage", "VoxelPhysicsWorld:ApplyDamageAtWorldPoint"],
         props=[], gate="连通性副作用单测（承重件是否掉落）"),
    dict(id="damage-shapes", title="形状伤害（锯/切/爆破）", group="破坏",
         apis=["VoxelPhysicsWorld:ApplyDamageCapsule", "VoxelPhysicsWorld:ApplyDamageBox",
               "VoxelPhysicsWorld:ApplyDamageCone"], props=[],
         gate="薄 box 平面切的截面是否走断面色"),
    dict(id="build-fill", title="建造（伤害对偶）", group="破坏",
         apis=["VoxelPhysicsWorld:ApplyFillAtWorldPoint"], props=[],
         gate="空区补不了必须报错或走建体积路径，不得静默无操作"),
    dict(id="debris-budget", title="碎块预算", group="破坏",
         apis=["VoxelPhysicsWorld:SetMinFragmentVoxels", "VoxelPhysicsWorld:SetMaxFrozenFragments",
               "VoxelPhysicsWorld:SetMaxSpallChunks", "VoxelPhysicsWorld:SetDebrisMaxAge"],
         props=[], gate="峰值碎块数与帧时写入 perf_<tag>.json"),
    dict(id="stress-break", title="应力断裂", group="破坏",
         apis=["VoxelPhysicsWorld:SetStressBreakFactor"], props=[],
         gate="断裂阈值要有过小/过大两个负样本"),
    dict(id="damage-noise", title="损伤噪声（边缘凌乱度）", group="破坏",
         apis=["VoxelPhysicsWorld:SetDamageNoise"], props=[],
         gate="噪声量必须进参数表（影响逐像素可复现）"),
    dict(id="volume-policies", title="可破坏/可淘汰/可碰撞 三策略", group="破坏",
         apis=["VoxelVolume:SetDestructible", "VoxelVolume:SetEvictable", "VoxelVolume:SetCollidable"],
         props=["destructible", "evictable", "collidable"],
         gate="三者独立设置；地形必须 destructible=false 防误挖"),

    # --- 玩法层 ---
    dict(id="assembly", title="装配体", group="玩法",
         apis=["VoxelPhysicsWorld:CreateAssembly", "VoxelAssembly:SetMemberBreakThreshold",
               "VoxelAssembly:GetMemberStress"], props=[], gate="成员连接阈值按 N / N·m 调，留断裂负样本"),
    dict(id="constraint", title="约束与机关", group="玩法",
         apis=["VoxelConstraint:SetAngularMotorVelocity", "VoxelConstraint:SetLinearSpring",
               "VoxelConstraint:SetAngularLimits", "VoxelConstraint:GetReactionForce"],
         props=[], gate="铰链相对轴 + disableCollision，先验抖动"),
    dict(id="vehicle", title="悬挂载具", group="玩法",
         apis=["VoxelVehicle:AddWheel", "VoxelVehicle:SetInput", "VoxelVehicle:IsWheelGrounded"],
         props=[], gate="停车手刹 SetInput(0,0,1)"),
    dict(id="rolling-contact", title="实体组装轮", group="玩法",
         apis=["VoxelRollingContact:SetLongitudinalGrip", "VoxelRollingContact:SetLateralGrip"],
         props=[], gate="滚阻/抓地曲线的支撑统计留证"),
    dict(id="character", title="体素角色控制器", group="玩法",
         apis=["VoxelPhysicsWorld:CreateCharacter", "VoxelPhysicsWorld:MoveCharacter",
               "VoxelCharacterController:Jump"], props=[],
         gate="位置=脚底；跳跃走 MoveCharacter 的 jumpSpeed 参数"),
    dict(id="grab", title="抓取推拽", group="玩法",
         apis=["VoxelPhysicsWorld:BeginGrab", "VoxelPhysicsWorld:EndGrab"], props=[],
         gate="抓取时体素被破坏的复位行为要验"),

    # --- 仪器 ---
    dict(id="cpu-grid-raycast", title="纯 CPU 网格射线（可无渲染）", group="仪器",
         apis=["VoxelPhysicsWorld:RaycastGridSingle", "VoxelPhysicsWorld:RaycastGrid"],
         props=[], gate="专用服务器/无头管线用它做朝向与接地检查"),
    dict(id="material-query", title="材质查询", group="仪器",
         apis=["VoxelPhysicsWorld:GetMaterialAtWorldPoint"], props=[],
         gate="越界/空返回 -1，脚本必须处理 -1"),
    dict(id="occupancy-count", title="占用计数（对账分子）", group="仪器",
         apis=["VoxelGrid:GetSolidCount"], props=[],
         gate="与占用表按 I-01 恒等式对账"),
    dict(id="lifecycle-predicates", title="生命周期谓词与 Ready", group="仪器",
         apis=["VoxelVolume:IsContentReady", "VoxelVolume:IsRemoteReplica"],
         props=["tumbling", "reSettling"], gate="断言'这一刻它处于什么状态'而不是靠推断"),
    dict(id="model-binding", title="来源模型引用与解绑", group="仪器",
         apis=["VoxelVolume:DetachFromVoxelModel", "VoxelVolume:HasVoxelModel",
               "VoxelVolume:SetVoxelModel"], props=[],
         gate="手改 grid 必须先 DetachFromVoxelModel，否则存档重载丢失"),
]

EMMYLUA_GLOB = re.compile(r"^Voxel.*\.d\.lua$")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def scan_api_surface(root):
    """返回 {api_name: (file, line)}，来自 .emmylua/Voxel*.d.lua。"""
    surface = {}
    em = os.path.join(root, ".emmylua")
    if not os.path.isdir(em):
        return surface, []
    files = []
    for fn in sorted(os.listdir(em)):
        if not EMMYLUA_GLOB.match(fn):
            continue
        p = os.path.join(em, fn)
        files.append(os.path.relpath(p, root))
        for i, line in enumerate(read_text(p).split("\n"), 1):
            m = re.match(r"function\s+([A-Za-z_][\w.:]*)\s*\(", line)
            if m:
                surface.setdefault(m.group(1), (os.path.relpath(p, root), i))
    return surface, files


def scan_usage(root):
    """扫描工程脚本里的标识符引用。

    排除：引擎生成物（.emmylua）、只读包（.cache）、引擎资源（CoreData/Data）、
    文档样例（engine-docs/editor-docs/examples/templates）、备份与临时目录。
    每条引用带 scope：project = 在工程自己会改的目录里；other = 库/工具目录。
    """
    usage = {}
    skip_dirs = {".emmylua", ".cache", ".git", ".tmp", "node_modules",
                 "CoreData", "Data", "Res", "engine-docs", "editor-docs",
                 "examples", "templates", "schemas", "plugin-docs", "docs"}
    scope_dirs = ("scripts", "assets", "src", "Source", "Lua", "lua")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if not fn.endswith(".lua"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            top = rel.split("/", 1)[0]
            scope = "project" if top in scope_dirs else "other"
            text = read_text(p)
            for i, line in enumerate(text.split("\n"), 1):
                if line.lstrip().startswith("--"):
                    continue
                for m in re.finditer(r"[:.](\w+)\s*\(", line):
                    usage.setdefault(m.group(1), []).append((rel, i, scope))
                for m in re.finditer(r"(\w+)\s*=", line):
                    usage.setdefault(m.group(1), []).append((rel, i, scope))
    return usage


def main(argv):
    ap = argparse.ArgumentParser(description="UrhoX native voxel capability probe (read-only)")
    ap.add_argument("--project", required=True, help="UrhoX project root")
    ap.add_argument("--out", help="write full JSON report here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv[1:])

    root = os.path.abspath(args.project)
    if not os.path.isdir(root):
        print("ERROR: not a directory: %s" % root, file=sys.stderr)
        return 2
    surface, emmylua_files = scan_api_surface(root)
    if not surface and not os.path.isdir(os.path.join(root, "engine-docs")):
        print("ERROR: %s does not look like an UrhoX project (no .emmylua/Voxel*.d.lua and no engine-docs/)"
              % root, file=sys.stderr)
        return 2

    usage = scan_usage(root)

    # 环境证据（存在性）
    env = {
        "emmylua_voxel_files": emmylua_files,
        "voxel_recipe_doc": os.path.isfile(os.path.join(root, "engine-docs", "recipes", "voxel-physics.md")),
        "voxel_network_doc": os.path.isfile(os.path.join(root, "engine-docs", "recipes", "voxel-networking.md")),
        "dda_techniques": [],
        "official_voxel_tool": [],
        "runtime_voxel_tests": [],
    }
    tech = os.path.join(root, "CoreData", "Techniques", "PBR")
    if os.path.isdir(tech):
        env["dda_techniques"] = sorted(f for f in os.listdir(tech) if f.startswith("PBRVoxelDda"))
    pkg = os.path.join(root, ".cache", "packages")
    if os.path.isdir(pkg):
        for name in sorted(os.listdir(pkg)):
            if "Voxel" not in name:
                continue
            for ver in sorted(os.listdir(os.path.join(pkg, name))):
                conv = os.path.join(pkg, name, ver, "scripts", "VoxelConvert")
                if os.path.isdir(conv):
                    env["official_voxel_tool"].append({
                        "package": "%s/%s" % (name, ver),
                        "scripts": sorted(f for f in os.listdir(conv) if f.endswith(".lua")),
                    })
    lua_dir = os.path.join(root, "Data", "LuaScripts")
    if os.path.isdir(lua_dir):
        env["runtime_voxel_tests"] = sorted(f for f in os.listdir(lua_dir)
                                            if f.startswith("Voxel") and f.endswith(".lua"))

    results = []
    for cap in CATALOG:
        found_api, missing_api, api_evidence = [], [], []
        for api in cap["apis"]:
            simple = api.split(":")[-1]
            if api in surface:
                found_api.append(api)
                api_evidence.append({"api": api, "declared_in": surface[api][0], "line": surface[api][1]})
            elif any(k.endswith(":" + simple) or k == api for k in surface):
                hit = next(k for k in surface if k.endswith(":" + simple) or k == api)
                found_api.append(hit)
                api_evidence.append({"api": hit, "declared_in": surface[hit][0], "line": surface[hit][1]})
            else:
                missing_api.append(api)

        refs = []
        for token in [a.split(":")[-1] for a in cap["apis"]] + list(cap["props"]):
            for (rel, ln, scope) in usage.get(token, []):
                refs.append({"token": token, "file": rel, "line": ln, "scope": scope})
        # 去重（同一 token 同一文件只留一处）
        seen, refs_u = set(), []
        for r in refs:
            k = (r["token"], r["file"])
            if k in seen:
                continue
            seen.add(k)
            refs_u.append(r)
        project_refs = [r for r in refs_u if r["scope"] == "project"]

        if not found_api:
            status = "MISSING-IN-BUILD"      # 该发行版没导出这些 API
        elif project_refs:
            status = "USED"
        elif refs_u:
            status = "REF-ONLY-OUTSIDE-PROJECT"  # 只在库/工具目录里出现
        else:
            status = "AVAILABLE-UNUSED"
        results.append({
            "id": cap["id"], "title": cap["title"], "group": cap["group"], "status": status,
            "apis_found": found_api, "apis_missing": missing_api, "api_evidence": api_evidence,
            "project_references": project_refs[:20], "project_reference_count": len(project_refs),
            "other_reference_count": len(refs_u) - len(project_refs),
            "required_gate": cap["gate"],
        })

    used = [r for r in results if r["status"] == "USED"]
    unused = [r for r in results if r["status"] in ("AVAILABLE-UNUSED", "REF-ONLY-OUTSIDE-PROJECT")]
    missing = [r for r in results if r["status"] == "MISSING-IN-BUILD"]
    report = {
        "tool": "urhox_capability_probe.py",
        "project": root,
        "note": "只读扫描；AVAILABLE-UNUSED = 引擎已导出且工程内无引用；"
                "REF-ONLY-OUTSIDE-PROJECT = 只在库/工具目录被引用。两种都可能有反射/字符串调用造成的漏报。",
        "environment": env,
        "api_surface_size": len(surface),
        "summary": {
            "total": len(results),
            "used": len(used), "available_unused": len(unused), "missing_in_build": len(missing),
            "unused_ids": [r["id"] for r in unused],
            "missing_ids": [r["id"] for r in missing],
        },
        "capabilities": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)

    if not args.quiet:
        s = report["summary"]
        print("UrhoX 原生体素能力探针  project=%s" % root)
        print("  引擎导出体素 API 数: %d   能力项: %d" % (len(surface), s["total"]))
        print("  已用 %d / 可用未用 %d / 该发行版缺失 %d" % (s["used"], s["available_unused"], s["missing_in_build"]))
        if unused:
            print("\n  ── 可用但工程内未引用（按 15 §4 必须先配门禁再开）──")
            for r in unused:
                kind = "未引用" if r["status"] == "AVAILABLE-UNUSED" else "仅库目录引用"
                print("    [%s] %s  (%s, %s)" % (r["group"], r["title"], r["id"], kind))
                print("        门禁: %s" % r["required_gate"])
        if missing:
            print("\n  ── 该发行版未导出（换发行版需重跑）──")
            for r in missing:
                print("    [%s] %s  <- %s" % (r["group"], r["title"], ", ".join(r["apis_missing"])))
        if used:
            print("\n  ── 已引用 ──")
            print("    " + ", ".join(r["id"] for r in used))
        print("\n  环境: DDA techniques=%d, official-Voxel-Tool=%d, 运行时体素自测=%d, recipe=%s"
              % (len(env["dda_techniques"]), len(env["official_voxel_tool"]),
                 len(env["runtime_voxel_tests"]), env["voxel_recipe_doc"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
