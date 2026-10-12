#!/usr/bin/env python3
"""Environment acceptance probe — implements references/20-runtime-environment-and-dependencies.md.

Checks, per declared interpreter: existence + version + required module availability, plus the
playwright browser bundle.  Compares against the expectation table below and reports drift.

usage:
  python runtime_env_probe.py            # human report
  python runtime_env_probe.py --json     # machine report
  python runtime_env_probe.py --run <interpreter-id> --script <path>   # run a script on that interpreter

exit: 0 expectations met · 1 drift · 2 interpreter path missing
"""

import argparse
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)

# ---- expectation table (mirrors reference section 1 / section 6; change both together) ----
INTERPRETERS = [
    {
        "id": "py312",
        "path": r"D:\tools\Python312\python.exe",
        "expect_version": "3.12.",
        "role": "默认解释器：绝大多数纯 Python 外部件",
        "modules": ["numpy", "cv2", "ezdxf", "fitz", "matplotlib", "openpyxl", "trimesh",
                    "scipy", "skimage", "playwright", "cadquery", "reportlab",
                    "rapidocr_onnxruntime", "PIL", "shapely", "OCP"],
        "optional_modules": [],
    },
    {
        "id": "freecad311",
        "path": r"D:\tools\FreeCAD\bin\python.exe",
        "expect_version": "3.11.",
        "role": "FreeCAD 后端件（cadstack freecad backend / skill-freecad / openclaw-freecad-mcp）",
        # numpy/PIL/matplotlib ship with FreeCAD; ezdxf/trimesh/fitz do not
        "modules": ["FreeCAD", "Part", "Mesh", "numpy", "PIL", "matplotlib"],
        "optional_modules": ["ezdxf", "trimesh", "fitz"],
    },
]

EXTERNAL_APPS = [
    {"id": "blender", "path": r"D:\tools\Blender\blender-5.1.2-windows-x64\blender.exe",
     "role": "需 bpy 的件；用 --background --python 调用"},
    {"id": "freecadcmd", "path": r"D:\tools\FreeCAD\bin\freecadcmd.exe",
     "role": "FreeCAD 无头批处理"},
]

PLAYWRIGHT_DIRS = ["chromium-1243", "chromium_headless_shell-1243", "ffmpeg-1011"]

NOT_BOUND = [
    {"id": "rhino", "role": "rhinoclaw", "reason": "需商业授权；只读算法，不进交付链路（见 20 §5）"},
]


def probe_modules(python, modules):
    """Ask the interpreter itself — never guess from the host's sys.path."""
    code = (
        "import json,importlib.util,sys\n"
        "mods=%r\n"
        "out={}\n"
        "for m in mods:\n"
        "    ok=importlib.util.find_spec(m) is not None\n"
        "    v=None\n"
        "    if ok:\n"
        "        try:\n"
        "            mod=__import__(m); v=getattr(mod,'__version__',None)\n"
        "        except Exception as e:\n"
        "            v='import-error:'+type(e).__name__\n"
        "    out[m]=[ok,str(v) if v else None]\n"
        "print(json.dumps({'version':sys.version.split()[0],'modules':out}))\n"
    ) % (modules,)
    r = subprocess.run([python, "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "").strip()[:300]
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), None
    except Exception as exc:
        return None, "parse: %s" % exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run", default=None, help="interpreter id to run a script on")
    ap.add_argument("--script", default=None)
    ap.add_argument("--args", default="")
    a = ap.parse_args()

    if a.run:
        interp = next((i for i in INTERPRETERS if i["id"] == a.run), None)
        if not interp:
            print("unknown interpreter:", a.run)
            return 2
        if not os.path.isfile(interp["path"]):
            print("MISSING:", interp["path"])
            return 2
        cmd = [interp["path"], a.script] + ([a.args] if a.args else [])
        print("+", " ".join(cmd))
        return subprocess.run(cmd, env=dict(os.environ, PYTHONUTF8="1")).returncode

    report = {"interpreters": [], "apps": [], "playwright": {}, "notBound": NOT_BOUND, "drift": []}

    for spec in INTERPRETERS:
        rec = {"id": spec["id"], "path": spec["path"], "role": spec["role"],
               "exists": os.path.isfile(spec["path"]), "problems": []}
        if not rec["exists"]:
            rec["problems"].append("interpreter missing")
            report["interpreters"].append(rec)
            report["drift"].append("%s: interpreter missing at %s" % (spec["id"], spec["path"]))
            continue
        data, err = probe_modules(spec["path"], spec["modules"] + spec["optional_modules"])
        if data is None:
            rec["problems"].append("probe failed: " + str(err))
            report["drift"].append("%s: probe failed (%s)" % (spec["id"], err))
            report["interpreters"].append(rec)
            continue
        rec["version"] = data["version"]
        if not data["version"].startswith(spec["expect_version"]):
            rec["problems"].append("version %s != expected %s*" % (data["version"], spec["expect_version"]))
            report["drift"].append("%s: version %s != %s*" % (spec["id"], data["version"], spec["expect_version"]))
        rec["required"] = {}
        for m in spec["modules"]:
            ok, v = data["modules"].get(m, [False, None])
            rec["required"][m] = {"ok": ok, "version": v}
            if not ok:
                rec["problems"].append("missing required module: " + m)
                report["drift"].append("%s: missing %s" % (spec["id"], m))
        rec["optional"] = {}
        for m in spec["optional_modules"]:
            ok, v = data["modules"].get(m, [False, None])
            rec["optional"][m] = {"ok": ok, "version": v}
        report["interpreters"].append(rec)

    for app in EXTERNAL_APPS:
        rec = {"id": app["id"], "path": app["path"], "exists": os.path.isfile(app["path"]), "role": app["role"]}
        if not rec["exists"]:
            report["drift"].append("%s: app missing at %s" % (app["id"], app["path"]))
        report["apps"].append(rec)

    pw = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    report["playwright"]["dir"] = pw
    for d in PLAYWRIGHT_DIRS:
        present = os.path.isdir(os.path.join(pw, d))
        report["playwright"][d] = present
        if not present:
            report["drift"].append("playwright bundle missing: " + d)

    report["verdict"] = "GREEN" if not report["drift"] else "DRIFT"

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== 运行环境验收（references/20 §4）===")
        for rec in report["interpreters"]:
            print("\n[%s] %s" % (rec["id"], rec["path"]))
            print("  角色: %s" % rec["role"])
            if not rec["exists"]:
                print("  **解释器不存在**")
                continue
            print("  版本: %s (期望 %s*)" % (rec["version"], next(
                s["expect_version"] for s in INTERPRETERS if s["id"] == rec["id"])))
            ok = [m for m, v in rec["required"].items() if v["ok"]]
            bad = [m for m, v in rec["required"].items() if not v["ok"]]
            print("  必需模块: %d/%d 可用%s" % (len(ok), len(ok) + len(bad),
                                          ("  缺: " + ",".join(bad)) if bad else ""))
            if rec["optional"]:
                opt_ok = [m for m, v in rec["optional"].items() if v["ok"]]
                print("  可选模块: %s" % (",".join(opt_ok) if opt_ok else "（均未装）"))
        print("\n=== 外部程序 ===")
        for rec in report["apps"]:
            print("  %-12s %s  %s" % (rec["id"], "OK " if rec["exists"] else "缺失", rec["path"]))
        print("\n=== playwright 内核 ===")
        for d in PLAYWRIGHT_DIRS:
            print("  %-28s %s" % (d, "OK" if report["playwright"].get(d) else "缺失"))
        print("\n=== 显式不绑定 ===")
        for rec in NOT_BOUND:
            print("  %-8s %s —— %s" % (rec["id"], rec["role"], rec["reason"]))
        print("\nVERDICT: %s" % report["verdict"])
        for d in report["drift"]:
            print("  ! " + d)

    return 0 if not report["drift"] else 1


if __name__ == "__main__":
    sys.exit(main())
