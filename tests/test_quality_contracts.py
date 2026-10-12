import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PACKAGE_ROOT / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QualityContracts(unittest.TestCase):
    def run_script(self, script_name, *arguments):
        environment = dict(os.environ)
        environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, str(SCRIPT_ROOT / script_name), *arguments],
            cwd=PACKAGE_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_provenance_verify_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "sample.txt"
            payload.write_text("original\n", encoding="utf-8")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            (root / "_PROVENANCE.json").write_text(json.dumps({
                "id": "fixture",
                "files": [{"src": "sample.txt", "sha256": digest}],
            }), encoding="utf-8")

            passed = self.run_script("external_tool_fetch.py", "--verify", "--dest", str(root))
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

            payload.write_text("tampered\n", encoding="utf-8")
            rejected = self.run_script("external_tool_fetch.py", "--verify", "--dest", str(root))
            self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
            self.assertIn("hash drift", rejected.stdout)

    def test_external_map_rejects_missing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "docs" / "refs-staging").mkdir(parents=True)
            result = self.run_script(
                "external_skill_map_check.py",
                "--refs-root",
                str(workspace),
                "--no-checksums",
                "--json",
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["green"])
            self.assertTrue(report["missing"])

    def test_forward_contract_is_declared_but_skip_is_not_complete(self):
        runner = load_module("quality_runner", PACKAGE_ROOT / "tests" / "run_tests.py")
        contract = runner.validate_eval_contract()
        self.assertEqual(contract["status"], "pass")
        self.assertGreaterEqual(contract["count"], 10)
        blind = runner.validate_blind_forward_cases()
        self.assertEqual(blind["status"], "pass", blind["problems"])
        self.assertEqual(blind["count"], contract["count"])
        summary = runner.summarize([runner.skipped("fixture", "test")])
        self.assertEqual(summary["status"], "partial")
        self.assertFalse(summary["complete"])

    def test_legacy_root_paths_are_unambiguous_aliases(self):
        for reference in (PACKAGE_ROOT / 'references').glob('*.md'):
            alias = PACKAGE_ROOT / reference.name
            content = alias.read_text(encoding='utf-8')
            pointers = [part.split(')', 1)[0] for part in content.split('](')[1:]
                        if part.startswith('references/') ]
            self.assertEqual(pointers, ['references/' + reference.name])
            self.assertTrue((PACKAGE_ROOT / pointers[0]).is_file())

        for script in SCRIPT_ROOT.glob('*.py'):
            expected = self.run_script(script.name, '--help')
            alias = subprocess.run([sys.executable, str(PACKAGE_ROOT / script.name), '--help'],
                                   cwd=PACKAGE_ROOT, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=60)
            self.assertEqual(alias.returncode, expected.returncode, alias.stderr)
            self.assertEqual(alias.stdout, expected.stdout, script.name)

        canonical = self.run_script('check_crossrefs.py')
        legacy = subprocess.run([sys.executable, str(PACKAGE_ROOT / 'check_crossrefs.py')],
                                cwd=PACKAGE_ROOT, capture_output=True, text=True,
                                encoding='utf-8', timeout=60)
        self.assertEqual(legacy.returncode, canonical.returncode, legacy.stderr)
        self.assertEqual(legacy.stdout, canonical.stdout)


if __name__ == "__main__":
    unittest.main()
