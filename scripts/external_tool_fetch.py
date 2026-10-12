#!/usr/bin/env python3
"""Fetch (copy) selected executables from the reference packages into an isolated tools dir.

Never writes to the reference packages.  For every copied file it records sha256, and for
Python files it extracts the import list and separates stdlib from third-party, so `--probe`
can tell you whether the thing is actually runnable on this machine.

usage:
  python external_tool_fetch.py --list --grade P1
  python external_tool_fetch.py --id <index-id> [--id ...] [--dest DIR] [--apply]
  python external_tool_fetch.py --probe --id <index-id> [...]
  python external_tool_fetch.py --verify --dest DIR

exit: 0 ok · 1 some file missing / probe failed · 2 usage
"""

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
INDEX = os.path.join(SKILL, "assets", "external-skills-index.json")
DEFAULT_PROJECT = os.environ.get("URHOX_REPLICATION_ROOT") or os.path.abspath(
    os.path.join(SKILL, os.pardir, os.pardir))
DEFAULT_REFS = os.environ.get("URHOX_REFS_ROOT") or os.path.join(DEFAULT_PROJECT, "docs", "refs-staging")
DEFAULT_DEST = os.environ.get("URHOX_EXTERNAL_TOOLS_DIR") or os.path.join(DEFAULT_PROJECT, "tools", "external")

IMPORT_RX = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.M)
TRY_RX = re.compile(r"^([ \t]*)(?:try\s*:|if\s+.*?:)\s*$", re.M)


def resolve_refs_root(value):
    """Accept a workspace root or the direct docs/refs-staging root."""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    nested = os.path.join(path, "docs", "refs-staging")
    return nested if os.path.isdir(nested) else path


def split_imports(txt):
    """Return (hard, optional) module sets.

    Imports sitting inside a `try:` (or `if ...:` guard, the common “optional dependency”
    shape) are *optional*: the code is expected to run without them. Static import scanning
    that ignores this reports paddleocr as required for a skill that actually prefers
    rapidocr and only falls back to paddleocr.
    """
    lines = txt.splitlines()
    optional_lines = set()
    depth = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if depth is None and (stripped == "try:" or stripped.startswith("try:")):
            depth = len(ln) - len(ln.lstrip())
            continue
        if depth is not None:
            indent = len(ln) - len(ln.lstrip())
            if stripped and indent <= depth and not stripped.startswith(("except", "finally", "else")):
                depth = None
            else:
                optional_lines.add(i)
                if stripped.startswith(("except", "finally")):
                    depth = None
    hard, opt = set(), set()
    for i, ln in enumerate(lines):
        m = IMPORT_RX.match(ln)
        if not m:
            continue
        mod = m.group(1).split(".")[0]
        (opt if i in optional_lines else hard).add(mod)
    return hard, opt


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index():
    return json.load(open(INDEX, encoding="utf-8"))


def pkg_dir(refs, entry):
    m = json.load(open(os.path.join(refs, entry["package"], "MANIFEST.json"), encoding="utf-8"))
    for kind in ("github", "clawhub"):
        for e in m.get(kind, []):
            if os.path.basename(e.get("localPath") or "") == entry["key"]:
                local = e["localPath"].replace(chr(92), "/")
                prefix = "docs/refs-staging/"
                if local.startswith(prefix):
                    local = local[len(prefix):]
                return os.path.abspath(os.path.join(refs, local.replace("/", os.sep)))
    return None


def resolve_specs(src, specs):
    out = []
    for spec in specs:
        spec = spec.replace("\\", "/")
        if any(ch in spec for ch in "*?["):
            hits = glob.glob(os.path.join(src, spec.replace("/", os.sep)))
            out.extend(hits)
        else:
            p = os.path.join(src, spec.replace("/", os.sep))
            if os.path.exists(p):
                out.append(p)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def collect_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for base, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
                for fn in sorted(fs):
                    if fn.endswith((".pyc", ".meta")):
                        continue
                    files.append(os.path.join(base, fn))
        else:
            files.append(p)
    return files


def imports_of(path):
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    mods = set()
    for m in IMPORT_RX.finditer(txt):
        mods.add(m.group(1).split(".")[0])
    return mods


def do_fetch(entries, refs, dest, apply_):
    summary = []
    for e in entries:
        src = pkg_dir(refs, e)
        if not src or not os.path.isdir(src):
            print("  SKIP (src missing)", e["id"])
            continue
        specs = list(e.get("x") or [])
        if not specs:
            print("  SKIP (no extract spec)", e["id"])
            continue
        # 用法文档不属于“可执行件”，但没它就无法调用：总是带上（存在才拿）
        for doc in ("SKILL.md", "skill-card.md", "README.md", "README_zh.md"):
            if os.path.isfile(os.path.join(src, doc)) and doc not in specs:
                specs.append(doc)
        resolved = resolve_specs(src, specs)
        files = collect_files(resolved)
        if not files:
            print("  SKIP (spec resolved to nothing)", e["id"])
            continue
        outdir = os.path.join(dest, e["id"].replace("/", "__"))
        records, mods, optmods = [], set(), set()
        local = set()
        for f in files:
            rel = os.path.relpath(f, src).replace("\\", "/")
            records.append({"src": rel, "bytes": os.path.getsize(f), "sha256": sha256(f)})
            if f.lower().endswith(".py"):
                local.add(os.path.splitext(os.path.basename(f))[0])
                try:
                    hard, opt = split_imports(open(f, encoding="utf-8", errors="replace").read())
                except OSError:
                    hard, opt = set(), set()
                mods |= hard
                optmods |= (opt - hard)
        skip = set(sys.stdlib_module_names) | local
        third = sorted(m for m in mods if m and m not in skip)
        optional = sorted(m for m in optmods if m and m not in skip)
        prov = {
            "id": e["id"],
            "package": e["package"],
            "source": e.get("source"),
            "license": e.get("license"),
            "grade": e.get("g"),
            "basis": e.get("b"),
            "extractedAt": "2026-09-23",
            "specs": specs,
            "files": records,
            "fileCount": len(records),
            "totalBytes": sum(r["bytes"] for r in records),
            "pythonImports": sorted(mods),
            "localModules": sorted(local),
            "thirdPartyImports": third,
            "optionalImports": optional,
            "runnableHere": [m for m in third if importlib.util.find_spec(m)] == third,
            "missingHere": [m for m in third if not importlib.util.find_spec(m)],
        }
        if apply_:
            os.makedirs(outdir, exist_ok=True)
            for f in files:
                rel = os.path.relpath(f, src)
                tgt = os.path.join(outdir, rel)
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                shutil.copy2(f, tgt)
            json.dump(prov, open(os.path.join(outdir, "_PROVENANCE.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            dep = ["# 依赖探测：%s" % e["id"], ""]
            dep.append("本机可跑：**%s**" % ("是" if prov["runnableHere"] else "否"))
            dep.append("")
            dep.append("第三方 import：%s" % (", ".join("`%s`" % m for m in third) if third else "（无）"))
            if prov["missingHere"]:
                dep.append("")
                dep.append("本机缺失：%s" % ", ".join("`%s`" % m for m in prov["missingHere"]))
            if prov.get("optionalImports"):
                dep.append("")
                dep.append("可选依赖（写在 `try/except` 里，缺了也能跑）：%s"
                           % ", ".join("`%s`" % m for m in prov["optionalImports"]))
            dep.append("")
            dep.append("| 模块 | 本机可用 |")
            dep.append("|---|---|")
            for m in third:
                dep.append("| `%s` | %s |" % (m, "✅" if importlib.util.find_spec(m) else "❌"))
            open(os.path.join(outdir, "_DEPS.md"), "w", encoding="utf-8", newline="\n").write("\n".join(dep) + "\n")
        tag = "OK " if apply_ else "DRY"
        print("  %s %-58s files=%3d  runnable=%-5s missing=%s" % (
            tag, e["id"][:58], len(records),
            "yes" if prov["runnableHere"] else "no",
            ",".join(prov["missingHere"][:4]) or "-"))
        summary.append(prov)
    return summary


def do_probe(entries, refs, dest):
    rc = 0
    for e in entries:
        outdir = os.path.join(dest, e["id"].replace("/", "__"))
        pp = os.path.join(outdir, "_PROVENANCE.json")
        if not os.path.isfile(pp):
            print("  NOT FETCHED", e["id"])
            rc = 1
            continue
        prov = json.load(open(pp, encoding="utf-8"))
        miss = [m for m in prov.get("thirdPartyImports", []) if not importlib.util.find_spec(m)]
        opt = prov.get("optionalImports", [])
        print("  %-58s deps=%d missing=%d%s %s" % (
            e["id"][:58], len(prov.get("thirdPartyImports", [])), len(miss),
            (" opt=%d" % len(opt)) if opt else "",
            ("→ " + ",".join(miss[:5])) if miss else "runnable"))
        if miss:
            rc = 1
        # verify every copied file still matches its recorded hash
        for r in prov["files"]:
            p = os.path.join(outdir, r["src"].replace("/", os.sep))
            if not os.path.isfile(p):
                print("      MISSING", r["src"])
                rc = 1
            elif sha256(p) != r["sha256"]:
                print("      HASH DRIFT", r["src"])
                rc = 1
    return rc


def do_verify(dest):
    """Check fetched bytes against provenance without importing external code."""
    dest = os.path.abspath(os.path.expandvars(os.path.expanduser(dest)))
    provenance = sorted(glob.glob(os.path.join(dest, "**", "_PROVENANCE.json"), recursive=True))
    if not provenance:
        print("FAIL no _PROVENANCE.json under:", dest)
        return 2
    failed = False
    for provenance_path in provenance:
        try:
            with open(provenance_path, encoding="utf-8") as stream:
                record = json.load(stream)
            records = record.get("files")
            if not isinstance(records, list) or not records:
                raise ValueError("empty or invalid files list")
            package_root = os.path.dirname(provenance_path)
            problems = []
            for item in records:
                relative = item["src"]
                path = os.path.abspath(os.path.join(package_root, relative.replace("/", os.sep)))
                if os.path.commonpath([package_root, path]) != package_root:
                    problems.append("path escapes package: " + relative)
                elif not os.path.isfile(path):
                    problems.append("missing: " + relative)
                elif sha256(path) != item["sha256"]:
                    problems.append("hash drift: " + relative)
            print("%s: %s (%d files)" % (record.get("id", package_root),
                                        "FAIL" if problems else "PASS", len(records)))
            for problem in problems:
                print("  !", problem)
            failed = failed or bool(problems)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print("FAIL", provenance_path, str(exc))
            failed = True
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs-root", default=DEFAULT_REFS, help="workspace root or direct docs/refs-staging root")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--grade", default=None)
    ap.add_argument("--phase", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--verify", action="store_true", help="verify copied bytes from provenance")
    a = ap.parse_args()

    if a.verify:
        return do_verify(a.dest)
    a.refs_root = resolve_refs_root(a.refs_root)

    idx = load_index()
    sel = idx["entries"]
    if a.id:
        sel = [e for e in sel if e["id"] in set(a.id)]
    else:
        if a.grade:
            sel = [e for e in sel if e.get("g") == a.grade]
        if a.phase:
            sel = [e for e in sel if a.phase in (e.get("ph") or [])]
        sel = [e for e in sel if e.get("x")]
    if not sel:
        print("nothing selected")
        return 2

    if a.list:
        print("selected %d" % len(sel))
        for e in sel:
            print("  %-58s x=%s" % (e["id"][:58], e.get("x")))
        return 0
    if a.probe:
        return do_probe(sel, a.refs_root, a.dest)
    s = do_fetch(sel, a.refs_root, a.dest, a.apply)
    print("total files=%d bytes=%d" % (
        sum(x["fileCount"] for x in s), sum(x["totalBytes"] for x in s)))
    if not a.apply:
        print("(dry run — add --apply to write to %s)" % a.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
