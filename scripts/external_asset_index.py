#!/usr/bin/env python3
"""Build / verify the external-asset index for the three reference skill packages.

Merges three sources of truth:
  1. each package's MANIFEST.json          -> provenance (source, commit, zip sha256, license)
  2. a file scan of the package directory  -> code / doc / data / asset counts, executable list
  3. assets/external-skill-curation.json   -> judgement (grade, basis, phase, target, extract, note)

Output: assets/external-skills-index.json  (machine-readable, one row per external asset)

usage:
  python external_asset_index.py --build [--refs-root DIR]
  python external_asset_index.py --check [--refs-root DIR] [--json]
  python external_asset_index.py --worklist [--phase I|II] [--grade P1]

exit: 0 ok · 1 check failed · 2 usage / missing inputs
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CURATION = os.path.join(SKILL, "assets", "external-skill-curation.json")
INDEX = os.path.join(SKILL, "assets", "external-skills-index.json")
DEFAULT_REFS = r"D:\项目\体素建模测试回\docs\refs-staging"
PKGS = ("design-planning-skills", "genre-art-scene-skills", "model-to-drawing-skills")

CODE_EXT = (".py", ".sh", ".js", ".ts", ".mjs", ".cjs", ".ps1", ".lua", ".rb")
DATA_EXT = (".json", ".yaml", ".yml", ".csv", ".toml", ".ini", ".xml")
DOC_EXT = (".md", ".txt", ".rst")
ASSET_EXT = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".glb", ".gltf", ".obj", ".stl", ".fbx")


def scan(path, cap=500):
    c = Counter()
    code_bytes = doc_bytes = 0
    executables = []
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for fn in sorted(files):
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, path).replace("\\", "/")
            ext = os.path.splitext(fn)[1].lower()
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            if ext in CODE_EXT:
                c["code"] += 1
                code_bytes += size
                if len(executables) < cap:
                    executables.append(rel)
            elif ext in DATA_EXT:
                c["data"] += 1
            elif ext in DOC_EXT:
                c["doc"] += 1
                doc_bytes += size
            elif ext in ASSET_EXT:
                c["asset"] += 1
            else:
                c["other"] += 1
            c["files"] += 1
    return c, code_bytes, doc_bytes, executables


def build(refs):
    cur = json.load(open(CURATION, encoding="utf-8"))
    entries = []
    problems = []
    for pkg in PKGS:
        mpath = os.path.join(refs, pkg, "MANIFEST.json")
        if not os.path.isfile(mpath):
            problems.append("MANIFEST missing: " + mpath)
            continue
        m = json.load(open(mpath, encoding="utf-8"))
        for kind in ("github", "clawhub"):
            for e in m.get(kind, []):
                if "error" in e:
                    continue
                local = e.get("localPath") or ""
                key = os.path.basename(local)
                eid = "%s/%s/%s" % (pkg, kind, key)
                d = os.path.normpath(os.path.join(refs, "..", "..", local.replace("/", os.sep)))
                if not os.path.isdir(d):
                    problems.append("path missing: " + local)
                    continue
                c, cb, db, ex = scan(d)
                row = {
                    "id": eid,
                    "package": pkg,
                    "kind": kind,
                    "key": key,
                    "category": e.get("category"),
                    "source": e.get("source"),
                    "license": e.get("license"),
                    "commit": e.get("commit"),
                    "zipSha256": e.get("zipSha256"),
                    "files": c["files"],
                    "codeFiles": c["code"],
                    "docFiles": c["doc"],
                    "dataFiles": c["data"],
                    "assetFiles": c["asset"],
                    "codeBytes": cb,
                    "docBytes": db,
                    "executables": ex,
                    "description": e.get("description"),
                }
                row.update(cur["entries"].get(eid) or {"g": None, "b": "uncurated"})
                entries.append(row)
    for eid in cur["entries"]:
        if not any(r["id"] == eid for r in entries):
            problems.append("curation id not found on disk: " + eid)
    entries.sort(key=lambda r: r["id"])
    index = {
        "schema": "urhox-external-asset-index/1",
        "generatedAt": "2026-09-23",
        "legend": cur["legend"],
        "refsRoot": refs,
        "packages": list(PKGS),
        "counts": {
            "entries": len(entries),
            "withCode": sum(1 for r in entries if r["codeFiles"]),
            "docOnly": sum(1 for r in entries if not r["codeFiles"]),
            "uncurated": sum(1 for r in entries if r.get("b") == "uncurated"),
            "provisional": sum(1 for r in entries if r.get("b") == "provisional"),
            "curated": sum(1 for r in entries if r.get("b") == "curated"),
        },
        "gradeCounts": dict(Counter(r.get("g") or "none" for r in entries)),
        "phaseCounts": dict(Counter(
            ",".join(r.get("ph") or []) or "stock" for r in entries)),
        "problems": problems,
        "entries": entries,
    }
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs-root", default=DEFAULT_REFS)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--worklist", action="store_true")
    ap.add_argument("--phase", default=None)
    ap.add_argument("--grade", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.build:
        idx = build(a.refs_root)
        json.dump(idx, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        c = idx["counts"]
        print("entries=%d  withCode=%d  docOnly=%d" % (c["entries"], c["withCode"], c["docOnly"]))
        print("curation: curated=%d provisional=%d uncurated=%d" % (c["curated"], c["provisional"], c["uncurated"]))
        print("grades:", idx["gradeCounts"])
        print("phases:", idx["phaseCounts"])
        if idx["problems"]:
            print("PROBLEMS (%d):" % len(idx["problems"]))
            for p in idx["problems"][:20]:
                print("   -", p)
        print("->", INDEX)
        return 0 if not idx["problems"] else 1

    if a.check:
        if not os.path.isfile(INDEX):
            print("FAIL index not built yet:", INDEX)
            return 2
        old = json.load(open(INDEX, encoding="utf-8"))
        new = build(a.refs_root)
        om = {r["id"]: r for r in old["entries"]}
        nm = {r["id"]: r for r in new["entries"]}
        drift = []
        for k in sorted(set(om) | set(nm)):
            if k not in om:
                drift.append("new entry not indexed: " + k)
            elif k not in nm:
                drift.append("indexed entry gone: " + k)
            elif {x: y for x, y in om[k].items() if x != "executables"} != \
                 {x: y for x, y in nm[k].items() if x != "executables"}:
                diff = [f for f in set(om[k]) | set(nm[k])
                        if om[k].get(f) != nm[k].get(f) and f != "executables"]
                drift.append("%s changed: %s" % (k, diff))
        nc = new["counts"]["uncurated"]
        res = {"entries": len(nm), "drift": drift, "uncurated": nc, "problems": new["problems"]}
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("entries=%d  uncurated=%d" % (len(nm), nc))
            print("drift=%d" % len(drift))
            for d in drift[:20]:
                print("   -", d)
            for p in new["problems"][:10]:
                print("   !", p)
        ok = not drift and not new["problems"]
        print("VERDICT:", "GREEN" if ok else "PROBLEMS")
        return 0 if ok else 1

    if a.worklist:
        idx = json.load(open(INDEX, encoding="utf-8"))
        rows = idx["entries"]
        if a.phase:
            rows = [r for r in rows if a.phase in (r.get("ph") or [])]
        if a.grade:
            rows = [r for r in rows if r.get("g") == a.grade]
        wl = [r for r in rows if (r.get("x") or r.get("k"))]
        print("worklist: %d entries" % len(wl))
        for r in wl:
            tag = "P" if r.get("b") == "provisional" else "C"
            print("[%s] %-34s code=%3d  x=%d  k=%d  %s" % (
                tag, r["id"][:34], r["codeFiles"],
                len(r.get("x") or []), len(r.get("k") or []),
                (r.get("n") or "")[:44]))
        print()
        print("x=", sum(len(r.get("x") or []) for r in wl),
              "extract specs · k=", sum(len(r.get("k") or []) for r in wl), "knowledge specs")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
