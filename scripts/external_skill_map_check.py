#!/usr/bin/env python3
"""Cross-check references/18-external-skill-adoption.md against the on-disk reference archive.

Three-way reconciliation:
  1. every package path written in the doc resolves to a real directory / file;
  2. that path is covered by the package's MANIFEST.json (so it has provenance);
  3. the package's CHECKSUMS.sha256 still verifies (no silent edits).

Package ids in the doc look like:
    `genre-art-scene-skills/github/RobLe3__cc-blender-skill` → `plugin/skills/multiview-constraint-solver`
    `model-to-drawing-skills/clawhub/{ssq, drawing-insight-pro, eplan-drawing-parser}`
    `genre-art-scene-skills/clawhub/{blammectrappora/fantasy-map-generator, jack4world/terrain-route-video}`

Exit codes: 0 all green · 1 problems found · 2 usage / doc missing.

usage:
    python external_skill_map_check.py [--refs-root DIR] [--no-checksums] [--json]
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PKGS = ("design-planning-skills", "genre-art-scene-skills", "model-to-drawing-skills")
DEFAULT_PROJECT = os.environ.get("URHOX_REPLICATION_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir))
DEFAULT_ROOT = os.environ.get("URHOX_REFS_ROOT") or DEFAULT_PROJECT

BACKTICK = re.compile(r"`([^`]+)`")
PKG_START = re.compile(r"^(%s)(/.*)?$" % "|".join(PKGS))


def resolve_refs_root(value):
    """Accept a workspace root or the direct docs/refs-staging root."""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    nested = os.path.join(path, "docs", "refs-staging")
    return nested if os.path.isdir(nested) else path


def expand(raw):
    """Expand `pkg/...{a, b/c}` and comma lists into concrete package-relative ids."""
    raw = raw.strip().strip("`")
    # `pkg/path → sub/path` : the arrow tail is a sub-path of the head
    if "→" in raw:
        head, tail = raw.split("→", 1)
        heads = expand(head.strip())
        tail = tail.strip().strip("`")
        out = []
        for h in heads:
            out.append(h.rstrip("/") + "/" + tail.strip("/") if tail else h)
        return out

    m = PKG_START.match(raw)
    if not m:
        return []
    pkg, rest = m.group(1), (m.group(2) or "").strip("/")

    # brace group: prefix{a, b/c}
    bm = re.search(r"\{([^{}]*)\}", rest)
    if bm:
        prefix = rest[: bm.start()].strip("/")
        suffix = rest[bm.end():].strip("/")
        out = []
        for part in bm.group(1).split(","):
            part = part.strip().strip("`").strip("/")
            if not part:
                continue
            pieces = [p for p in (prefix, part, suffix) if p]
            out.extend(expand(pkg + "/" + "/".join(pieces)))
        return out

    return [pkg + ("/" + rest if rest else "")]


def ids_in_doc(path):
    text = open(path, encoding="utf-8").read()
    found = []
    for raw in BACKTICK.findall(text):
        for resolved in expand(raw):
            if resolved not in found:
                found.append(resolved)
    return found


def manifest_entries(pkg_dir):
    mp = os.path.join(pkg_dir, "MANIFEST.json")
    if not os.path.isfile(mp):
        return None
    m = json.load(open(mp, encoding="utf-8"))
    return m


def covered_by_manifest(pkg_dir, rel):
    """True if any manifest localPath is a prefix of (or equal to) pkg/rel."""
    m = manifest_entries(pkg_dir)
    if m is None:
        return None
    target = ("docs/refs-staging/" + os.path.basename(pkg_dir) + "/" + rel).replace("\\", "/").rstrip("/")
    for e in list(m.get("github", [])) + list(m.get("clawhub", [])):
        lp = (e.get("localPath") or "").replace("\\", "/").rstrip("/")
        if not lp:
            continue
        if target == lp or target.startswith(lp + "/"):
            return lp
    return False


def run_checksums(pkg_dir):
    script = os.path.join(pkg_dir, "_provenance", "verify.py")
    if not os.path.isfile(script):
        return None
    if not os.path.isfile(os.path.join(pkg_dir, "CHECKSUMS.sha256")):
        return None
    try:
        r = subprocess.run([sys.executable, script, "--check"], cwd=pkg_dir,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [str(exc)]
    return r.returncode == 0, (r.stdout or "").strip().splitlines()[-1:] 


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs-root", default=DEFAULT_ROOT,
                    help="workspace root or direct docs/refs-staging root")
    ap.add_argument("--doc", default=None)
    ap.add_argument("--no-checksums", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    refs = resolve_refs_root(a.refs_root)

    doc = a.doc or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "references", "18-external-skill-adoption.md")
    doc = os.path.abspath(doc)
    if not os.path.isfile(doc):
        print("FAIL doc not found:", doc)
        return 2

    if not os.path.isdir(refs):
        print("FAIL refs-staging not found:", refs)
        return 2

    ids = ids_in_doc(doc)
    missing, uncovered, ok = [], [], []
    for pid in ids:
        pkg, rest = pid.split("/", 1) if "/" in pid else (pid, "")
        pkg_dir = os.path.join(refs, pkg)
        if not os.path.isdir(pkg_dir):
            missing.append(pid)
            continue
        # "package name only" rows (e.g. the whole package) are fine
        if not rest:
            ok.append((pid, "package"))
            continue
        abs_path = os.path.join(pkg_dir, *rest.split("/"))
        if not os.path.exists(abs_path):
            missing.append(pid)
            continue
        cov = covered_by_manifest(pkg_dir, rest)
        if cov is False:
            uncovered.append(pid)
        elif cov is None:
            uncovered.append(pid + "  (no MANIFEST.json)")
        ok.append((pid, cov or "package"))

    checks = {}
    if not a.no_checksums:
        for p in PKGS:
            d = os.path.join(refs, p)
            checks[p] = run_checksums(d) if os.path.isdir(d) else None

    report = {
        "doc": doc,
        "refsRoot": refs,
        "idsTotal": len(ids),
        "idsOk": len(ok),
        "missing": missing,
        "uncoveredByManifest": uncovered,
        "checksums": {k: (v[0] if v else None) for k, v in checks.items()},
        "checksumsDetail": {k: (v[1] if v else None) for k, v in checks.items()},
        "green": not missing and not uncovered and all(
            (v[0] if v else False) for v in checks.values()),
    }

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("doc:", doc)
        print("package ids in doc: %d  resolved: %d" % (len(ids), len(ok)))
        for p, v in checks.items():
            txt = "skipped" if not v else ("PASS" if v[0] else "FAIL")
            print("  checksums %-26s %s  %s" % (p, txt, (v[1][0] if v and v[1] else "")))
        if missing:
            print("MISSING on disk (%d):" % len(missing))
            for x in missing:
                print("   -", x)
        if uncovered:
            print("NOT covered by MANIFEST (%d):" % len(uncovered))
            for x in uncovered:
                print("   -", x)
        print("VERDICT:", "GREEN" if report["green"] else "PROBLEMS")

    return 0 if report["green"] else 1


if __name__ == "__main__":
    sys.exit(main())
