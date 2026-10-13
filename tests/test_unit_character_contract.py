#!/usr/bin/env python3
"""unit_character_contract.py 的确定性回归：自检负样本 + 好/坏契约端到端。

属于 tests/run_tests.py 的 regression-tests 组（unittest discover 自动发现）。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "unit_character_contract.py"

GOOD_CONTRACT = {
    "world": {"voxel_size_m": 0.1, "grid_tolerance": 0.0001},
    "character": {"standing_height_m": 1.7, "crouch_height_m": 1.3, "prone_height_m": 0.6,
                  "radius_m": 0.25, "stand_radius_m": 0.35},
    "scan": {"exts": [".lua"], "exclude_dirs": [],
             "allowed_definition_files": ["world_spec.lua"]},
    "clearances": [{"name": "door", "height_m": 2.1}],
}


def run_script(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, encoding="utf-8")


class UnitCharacterContractTests(unittest.TestCase):
    def test_selftest_negative_samples(self):
        result = run_script(["--self-test"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SELF-TEST 6/6 PASS", result.stdout)

    def test_good_contract_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "world_spec.lua").write_text("M.VOXEL_SIZE = 0.1\n", encoding="utf-8")
            contract = json.loads(json.dumps(GOOD_CONTRACT))
            contract["scan"]["root"] = tmp
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            result = run_script(["--contract", str(contract_path), "--json-only"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertTrue(all(c["status"] in ("PASS", "WARN") for c in payload["checks"]))

    def test_competing_size_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "world_spec.lua").write_text("M.VOXEL_SIZE = 0.125\n", encoding="utf-8")
            contract = json.loads(json.dumps(GOOD_CONTRACT))
            contract["scan"]["root"] = tmp
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            result = run_script(["--contract", str(contract_path), "--json-only"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertTrue(any(c["id"] == "C1" and c["status"] == "FAIL" for c in payload["checks"]))

    def test_standing_not_integer_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "world_spec.lua").write_text("M.VOXEL_SIZE = 0.1\n", encoding="utf-8")
            contract = json.loads(json.dumps(GOOD_CONTRACT))
            contract["character"]["standing_height_m"] = 1.75
            contract["scan"]["root"] = tmp
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            result = run_script(["--contract", str(contract_path), "--json-only"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any(c["id"] == "C2" and c["status"] == "FAIL" for c in payload["checks"]))


if __name__ == "__main__":
    unittest.main()
