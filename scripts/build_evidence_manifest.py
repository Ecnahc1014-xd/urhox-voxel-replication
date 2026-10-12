#!/usr/bin/env python3
"""Create a deterministic size/SHA-256 manifest for an evidence package.

Generic form: accepts one or more directories, files or glob patterns and writes
a single JSON manifest listing every file with its byte size and SHA-256.

Object-agnostic: this tool knows nothing about the subject being replicated,
only about evidence files on disk.

Contract:
  * output JSON shape (schema / generated_at_utc / root / file_count /
    total_bytes / empty_files / files[] with path+size+sha256),
  * deterministic ordering by relative POSIX path,
  * exit codes: 0 = ok, 1 = zero-byte evidence file found (also when
    --require-files matched nothing, --require-channel found no shot for a
    channel, or --require-triplets found an incomplete before/after/diff set),
    2 = bad input,
  * zero-byte files are reported on stderr and make the run fail unless
    explicitly whitelisted with --allow-empty (matched against the
    manifest-relative POSIX path or the absolute path; bare names need
    the explicit --allow-empty-name opt-in, which is echoed on stderr).

Stdlib only. Python 3.8+ (verified on Python 3.12).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "voxel-replication-evidence-manifest/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_glob(pattern: str) -> bool:
    return any(char in pattern for char in "*?[")


def expand_inputs(raw_inputs: list[str]) -> tuple[list[Path], str | None]:
    """Resolve each CLI input (dir / file / glob) to concrete file paths.

    Returns (files, error_message). Order is not guaranteed here; the caller
    sorts. Directories are walked recursively.
    """
    found: dict[str, Path] = {}
    for raw in raw_inputs:
        if is_glob(raw):
            matches = [Path(item) for item in glob.glob(raw, recursive=True)]
            if not matches:
                return [], f"glob matched nothing: {raw}"
            for match in matches:
                if match.is_dir():
                    for path in match.rglob("*"):
                        if path.is_file():
                            found[str(path.resolve())] = path
                elif match.is_file():
                    found[str(match.resolve())] = match
        else:
            path = Path(raw)
            if path.is_dir():
                for item in path.rglob("*"):
                    if item.is_file():
                        found[str(item.resolve())] = item
            elif path.is_file():
                found[str(path.resolve())] = path
            else:
                return [], f"input not found: {path}"
    return [found[key] for key in sorted(found)], None


def pick_base(raw_inputs: list[str], files: list[Path]) -> Path | None:
    """Base directory used to render relative manifest paths.

    Single input: that directory (or the file's parent). Multiple inputs: their
    common parent, so entries stay comparable across the whole run. Returns
    None when inputs span different drives, in which case paths are absolute.
    """
    roots: list[str] = []
    for raw in raw_inputs:
        if is_glob(raw):
            matches = glob.glob(raw, recursive=True)
            if not matches:
                return None
            for match in matches:
                item = Path(match)
                roots.append(str(item if item.is_dir() else item.parent))
        else:
            item = Path(raw)
            roots.append(str(item if item.is_dir() else item.parent))
    if not files and not roots:
        return None
    if len(raw_inputs) == 1 and len(roots) == 1:
        return Path(roots[0]).resolve()
    try:
        return Path(os.path.commonpath(roots)).resolve()
    except ValueError:
        return None


def rel_key(path: Path, base: Path | None) -> str:
    if base is None:
        return path.resolve().as_posix()
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a size/SHA-256 manifest for one or more evidence inputs."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="Evidence directory, file or glob (e.g. 'out/run1' or 'out/**/*.png')",
    )
    parser.add_argument("--out", type=Path, required=True, help="Manifest JSON path")
    parser.add_argument(
        "--allow-empty",
        action="append",
        default=[],
        help="Path allowed to be zero-byte; may be repeated. Matched against the "
        "manifest-relative POSIX path or the absolute path.",
    )
    parser.add_argument(
        "--allow-empty-name",
        action="append",
        default=[],
        help="Bare file name allowed to be zero-byte; may be repeated. Opt-in "
        "escape hatch that whitelists every same-named file in the scan.",
    )
    parser.add_argument(
        "--schema",
        default=SCHEMA,
        help=f"Value written to the JSON 'schema' field (default: {SCHEMA})",
    )
    parser.add_argument(
        "--require-files",
        action="store_true",
        help="Also fail (exit 1) when no file matches at all",
    )
    parser.add_argument(
        "--require-channel",
        action="append",
        default=[],
        metavar="CH",
        help="Require at least one '*_<CH>_before.png' per listed channel "
        "(e.g. --require-channel A --require-channel C). Implements the "
        "two-axis channel rule; see references/07-delivery-and-reporting.md",
    )
    parser.add_argument(
        "--require-triplets",
        action="store_true",
        help="Require every '*_before.png' to have matching '_after.png' and "
        "'_diff.png' (and vice versa)",
    )
    args = parser.parse_args()

    out = args.out.resolve()
    tmp = out.with_name(out.name + ".tmp")
    files, err = expand_inputs(args.inputs)
    if err is not None:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    base = pick_base(args.inputs, files)
    allowed = {Path(item).as_posix() for item in args.allow_empty}
    allowed_names = {str(item) for item in args.allow_empty_name}
    entries: list[dict[str, object]] = []
    empty: list[str] = []

    for path in files:
        resolved = path.resolve()
        if resolved in (out, tmp):
            continue
        rel = rel_key(path, base)
        size = path.stat().st_size
        entries.append({"path": rel, "size": size, "sha256": sha256(path)})
        if size == 0 and not (
            rel in allowed
            or resolved.as_posix() in allowed
            or path.name in allowed_names
        ):
            empty.append(rel)

    entries.sort(key=lambda item: str(item["path"]))
    payload = {
        "schema": args.schema,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": base.as_posix() if base is not None else "",
        "inputs": list(args.inputs),
        "file_count": len(entries),
        "total_bytes": sum(int(item["size"]) for item in entries),
        "empty_files": empty,
        "files": entries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, out)

    if args.allow_empty_name:
        print(
            "NOTE: --allow-empty-name whitelists every same-named file: "
            + ", ".join(sorted(args.allow_empty_name)),
            file=sys.stderr,
        )
    if empty:
        print("ERROR: zero-byte evidence files: " + ", ".join(empty), file=sys.stderr)
        return 1
    if args.require_files and not entries:
        print("ERROR: no evidence files matched any input", file=sys.stderr)
        return 1

    names = [Path(str(item["path"])).name for item in entries]
    problems: list[str] = []
    for ch in args.require_channel:
        marker = f"_{ch}_before.png"
        if not any(n.endswith(marker) for n in names):
            problems.append(
                f"missing channel {ch}: no '*{marker}' found "
                f"(A=unlit/geometry evidence, B=lighting-contract, C=final look)"
            )
    if args.require_triplets:
        suffixes = ("_before.png", "_after.png", "_diff.png")
        stems = set()
        for n in names:
            for suf in suffixes:
                if n.endswith(suf):
                    stems.add(n[: -len(suf)])
                    break
        for stem in sorted(stems):
            for suf in suffixes:
                if f"{stem}{suf}" not in names:
                    problems.append(f"incomplete triplet: missing '{stem}{suf}'")
    if problems:
        for p in sorted(set(problems)):
            print("ERROR: " + p, file=sys.stderr)
        return 1

    print(f"OK: {len(entries)} files, manifest={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
