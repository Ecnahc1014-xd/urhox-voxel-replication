#!/usr/bin/env python3
"""Run the deterministic package checks without executing forward behavior evals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PACKAGE_ROOT / "scripts"
EVALS_PATH = PACKAGE_ROOT / "evals" / "evals.json"
BLIND_CASES_PATH = PACKAGE_ROOT / "tests" / "forward_eval_cases.json"


def normalize_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def discover_project_root() -> Path | None:
    configured = normalize_path(os.environ.get("URHOX_REPLICATION_ROOT"))
    if configured:
        return configured
    candidate = PACKAGE_ROOT.parent.parent
    if (candidate / "docs" / "refs-staging").is_dir():
        return candidate.resolve()
    return None


def discover_refs_root(project_root: Path | None) -> Path | None:
    configured = normalize_path(os.environ.get("URHOX_REFS_ROOT"))
    if configured:
        if (configured / "docs" / "refs-staging").is_dir():
            return (configured / "docs" / "refs-staging").resolve()
        return configured
    if project_root:
        candidate = project_root / "docs" / "refs-staging"
        if candidate.is_dir():
            return candidate.resolve()
    return None


def shorten(text: str, limit: int = 16000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[output truncated]"


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)


def run_command(name: str, arguments: list[str], timeout: float = 180) -> dict:
    command = [sys.executable, *arguments]
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=PACKAGE_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        output = stdout if not stderr else stdout + "\n[stderr]\n" + stderr
        return {
            "name": name,
            "status": "pass" if completed.returncode == 0 else "fail",
            "returncode": completed.returncode,
            "command": command,
            "commandText": command_text(command),
            "output": shorten(output.strip()),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "status": "fail",
            "returncode": 127,
            "command": command,
            "commandText": command_text(command),
            "output": str(exc),
        }


def skipped(name: str, reason: str) -> dict:
    return {"name": name, "status": "skipped", "reason": reason}


def validate_eval_contract(path: Path = EVALS_PATH) -> dict:
    result = {"name": "eval-contract", "status": "pass", "path": str(path), "problems": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["status"] = "fail"
        result["problems"].append(str(exc))
        return result
    if not isinstance(payload, dict):
        result["status"] = "fail"
        result["problems"].append("contract must be an object")
        return result
    if payload.get("skill_name") != "urhox-voxel-replication":
        result["problems"].append("skill_name must be urhox-voxel-replication")
    cases = payload.get("evals")
    if not isinstance(cases, list) or not cases:
        result["problems"].append("evals must be a non-empty list")
        cases = []
    identifiers = set()
    required = ("id", "prompt", "expected_output", "files")
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            result["problems"].append("eval %d is not an object" % index)
            continue
        missing = [field for field in required if field not in case]
        if missing:
            result["problems"].append("eval %d missing %s" % (index, ", ".join(missing)))
        identifier = case.get("id")
        if type(identifier) is not int or identifier <= 0:
            result["problems"].append("eval %d id must be a positive integer" % index)
        else:
            if identifier in identifiers:
                result["problems"].append("duplicate eval id: %s" % identifier)
            identifiers.add(identifier)
        if not isinstance(case.get("prompt"), str) or not case.get("prompt", "").strip():
            result["problems"].append("eval %s has empty prompt" % identifier)
        if not isinstance(case.get("expected_output"), str) or not case.get("expected_output", "").strip():
            result["problems"].append("eval %s has empty expected_output" % identifier)
        if not isinstance(case.get("files"), list):
            result["problems"].append("eval %s files must be a list" % identifier)
    if result["problems"]:
        result["status"] = "fail"
    result["count"] = len(cases)
    return result


def validate_blind_forward_cases(path: Path = BLIND_CASES_PATH) -> dict:
    result = {"name": "blind-forward-pack", "status": "pass", "path": str(path), "problems": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**result, "status": "fail", "problems": [str(exc)], "count": 0}
    if not isinstance(payload, dict) or payload.get("skill_name") != "urhox-voxel-replication":
        result["problems"].append("blind pack skill_name is invalid")
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        result["problems"].append("blind pack cases must be a non-empty list")
        cases = []
    identifiers = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            result["problems"].append("blind case %d is not an object" % index)
            continue
        forbidden = {"expected_output", "expected", "answer", "assertions"} & set(case)
        if forbidden:
            result["problems"].append("blind case %s exposes %s" % (case.get("id", index), sorted(forbidden)))
        identifier = case.get("id")
        if type(identifier) is not int or identifier <= 0 or identifier in identifiers:
            result["problems"].append("blind case %s has an invalid or duplicate id" % identifier)
        identifiers.add(identifier)
        for field in ("category", "prompt"):
            if not isinstance(case.get(field), str) or not case.get(field, "").strip():
                result["problems"].append("blind case %s has empty %s" % (identifier, field))
    if result["problems"]:
        result["status"] = "fail"
    result["count"] = len(cases)
    return result


def summarize(results: list[dict]) -> dict:
    failed = sum(item["status"] == "fail" for item in results)
    skipped_count = sum(item["status"] == "skipped" for item in results)
    return {
        "status": "fail" if failed else ("partial" if skipped_count else "pass"),
        "complete": not failed and not skipped_count,
        "total": len(results),
        "passed": sum(item["status"] == "pass" for item in results),
        "failed": failed,
        "skipped": skipped_count,
    }


def package_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == "SYNC.json":
            continue
        digest.update(path.relative_to(PACKAGE_ROOT).as_posix().encode("utf-8"))
        digest.update(bytes([0]))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run urhox-voxel-replication package checks")
    parser.add_argument("--json", action="store_true", help="emit one machine-readable report")
    parser.add_argument("--project-root", default=os.environ.get("URHOX_REPLICATION_ROOT"))
    parser.add_argument("--refs-root", default=os.environ.get("URHOX_REFS_ROOT"))
    parser.add_argument("--skip-environment", action="store_true")
    parser.add_argument("--skip-external", action="store_true")
    parser.add_argument("--require-complete", action="store_true", help="fail on any skipped deterministic check")
    parser.add_argument("--output", help="write the JSON report to this path")
    arguments = parser.parse_args()

    project_root = normalize_path(arguments.project_root) if arguments.project_root else discover_project_root()
    refs_root = normalize_path(arguments.refs_root) if arguments.refs_root else discover_refs_root(project_root)
    if refs_root and (refs_root / "docs" / "refs-staging").is_dir():
        refs_root = (refs_root / "docs" / "refs-staging").resolve()

    results = []
    if project_root and not project_root.is_dir():
        results.append({
            "name": "project-root",
            "status": "fail",
            "problems": ["project root does not exist: %s" % project_root],
        })

    results.append(run_command("skill-structure", [str(SCRIPT_ROOT / "skill_structure_check.py"), "--json"]))
    results.append(run_command("cross-references", [
        str(SCRIPT_ROOT / "check_crossrefs.py"), "--root", str(PACKAGE_ROOT),
    ]))
    results.append(run_command("feature-taxonomy", [str(SCRIPT_ROOT / "feature_taxonomy_check.py"), "--json"]))

    if arguments.skip_external:
        results.append(skipped("external-asset-index", "--skip-external"))
        results.append(skipped("external-skill-map", "--skip-external"))
    elif not refs_root:
        results.append(skipped("external-asset-index", "no refs root; pass --refs-root or URHOX_REFS_ROOT"))
        results.append(skipped("external-skill-map", "no refs root; pass --refs-root or URHOX_REFS_ROOT"))
    else:
        results.append(run_command("external-asset-index", [
            str(SCRIPT_ROOT / "external_asset_index.py"), "--check", "--refs-root", str(refs_root), "--json",
        ]))
        results.append(run_command("external-skill-map", [
            str(SCRIPT_ROOT / "external_skill_map_check.py"), "--refs-root", str(refs_root), "--json",
        ]))

    case_arguments = [str(SCRIPT_ROOT / "case_index.py"), "--check"]
    if project_root and project_root.is_dir():
        case_arguments.extend(["--project-root", str(project_root)])
    results.append(run_command("case-index", case_arguments))
    if not project_root:
        results.append(skipped("case-project-tools", "no project root; project-side tools not checked"))
    results.append(run_command("form-shape-self-test", [str(SCRIPT_ROOT / "form_shape_check.py"), "--self-test"]))
    eval_contract = validate_eval_contract()
    results.append(eval_contract)
    blind_cases = validate_blind_forward_cases()
    results.append(blind_cases)
    results.append(run_command("regression-tests", [
        "-B", "-m", "unittest", "discover", "-s", str(PACKAGE_ROOT / "tests"), "-p", "test_*.py", "-v",
    ]))

    help_checks = []
    for script_path in sorted(SCRIPT_ROOT.glob("*.py")):
        help_checks.append(run_command(
            "help:%s" % script_path.stem, [str(script_path), "--help"]))
    help_failures = [item for item in help_checks if item["status"] == "fail"]
    results.append({
        "name": "script-help",
        "status": "fail" if help_failures else "pass",
        "count": len(help_checks),
        "failures": [
            {"name": item["name"], "returncode": item["returncode"], "output": item["output"]}
            for item in help_failures
        ],
    })

    if arguments.skip_environment:
        results.append(skipped("runtime-environment", "--skip-environment"))
    else:
        results.append(run_command("runtime-environment", [
            str(SCRIPT_ROOT / "runtime_env_probe.py"), "--json",
        ]))

    summary = summarize(results)
    report = {
        "runner": "urhox-voxel-replication/tests/run_tests.py",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "packageHash": package_hash(),
        "packageRoot": str(PACKAGE_ROOT),
        "projectRoot": str(project_root) if project_root else None,
        "refsRoot": str(refs_root) if refs_root else None,
        "summary": summary,
        "results": results,
        "forwardEvals": {
            "status": "not-run",
            "count": eval_contract.get("count", 0),
            "blindInputCount": blind_cases.get("count", 0),
            "note": "The deterministic runner checks contracts and the answer-free blind pack only; it does not run forward behavior evals.",
        },
    }
    if arguments.output:
        output_path = normalize_path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== urhox-voxel-replication quality runner ===")
        print("package:", PACKAGE_ROOT)
        for item in results:
            print("%-24s %s" % (item["name"], item["status"].upper()))
            if item.get("status") == "fail":
                print("  ", item.get("output") or "; ".join(item.get("problems", [])))
        print("forward evals: NOT RUN (contract checked only)")
        print("VERDICT:", summary["status"].upper())
    return 1 if summary["failed"] or (arguments.require_complete and not summary["complete"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
