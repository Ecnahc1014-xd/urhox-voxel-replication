"""Subprocess regressions for subject-constrained reference intake."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from PIL import Image, ImageChops, ImageDraw


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PACKAGE_ROOT / "scripts" / "reference_intake_gate.py"
HAS_SEGMENTATION = all(importlib.util.find_spec(name) is not None for name in ("numpy", "cv2"))
NO_RUNTIME_WRAPPER = textwrap.dedent("""
    import builtins
    from pathlib import Path
    import runpy
    import sys
    original_import = builtins.__import__
    def blocked_import(name, *arguments, **keywords):
        if name.split('.')[0] in ('numpy', 'cv2'):
            raise ImportError('segmentation runtime intentionally unavailable')
        return original_import(name, *arguments, **keywords)
    builtins.__import__ = blocked_import
    sys.argv = sys.argv[1:]
    sys.path.insert(0, str(Path(sys.argv[0]).parent))
    runpy.run_path(sys.argv[0], run_name='__main__')
""")


class ReferenceIntakeSubjectsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reference-intake-subjects-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.refs = self.root / "refs"
        self.refs.mkdir()
        self.out = self.root / "out"
        self.source = self.refs / "front.png"
        self.table = self.root / "sources.md"
        self.table.write_text("| SYN-01 | **A** | synthetic fixture | " + chr(96) + "front.png" + chr(96) + " |\n", encoding="utf-8")
        self.truth = Image.new("L", (320, 256), 0)
        ImageDraw.Draw(self.truth).rectangle((32, 32, 287, 223), fill=255)
        image = Image.new("RGB", self.truth.size, (95, 145, 85))
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((32, 32, 159, 223), fill=(18, 24, 30))
        drawing.rectangle((160, 32, 287, 223), fill=(238, 242, 230))
        image.save(self.source)
        self.sequence = 0

    def subject(self):
        return {
            "file": "front.png", "image_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "image_size": list(self.truth.size), "target": "known dark and light fixture rectangles",
            "scope": "whole-subject", "coordinate_space": "normalized_xy",
            "bbox": [0.06, 0.06, 0.94, 0.94],
            "foreground_strokes": [{"points": [[0.25, 0.5]], "radius": 0.01},
                                   {"points": [[0.75, 0.5]], "radius": 0.01}],
            "background_strokes": [{"points": [[0.02, 0.02], [0.02, 0.98]], "radius": 0.01},
                                   {"points": [[0.98, 0.02], [0.98, 0.98]], "radius": 0.01}],
            "ignore_polygons": [[[0.44, 0.16], [0.56, 0.16], [0.56, 0.24], [0.44, 0.24]]],
            "iterations": 5, "max_side": 320,
        }

    def make_alpha(self):
        with Image.open(self.source) as image:
            artwork = image.convert("RGBA")
        artwork.putalpha(self.truth)
        artwork.save(self.source)

    def run_gate(self, subjects=None, expected=None, extra=(), out=None, no_runtime=False, raw_subjects=None):
        self.sequence += 1
        destination = Path(out) if out is not None else self.out
        arguments = [str(SCRIPT_PATH), "--refs", str(self.refs), "--out", str(destination),
                     "--source-table", str(self.table), "--emit-masks"]
        if subjects is not None or raw_subjects is not None:
            specification = self.root / ("subjects_%d.json" % self.sequence)
            if raw_subjects is None:
                document = {"schema": "reference-subject-spec-set/1", "views": subjects} if isinstance(subjects, list) else subjects
                raw_subjects = json.dumps(document)
            specification.write_text(raw_subjects, encoding="utf-8")
            arguments += ["--subjects", str(specification)]
        if expected is not None:
            arguments += ["--declare", "front.png:front:%d" % expected, "--declared-by", "fixture author"]
        arguments += list(extra)
        command = [sys.executable, "-B"] + (["-c", NO_RUNTIME_WRAPPER] if no_runtime else []) + arguments
        completed = subprocess.run(command, cwd=self.refs,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
        return completed, destination

    def outputs(self, destination):
        report = json.loads((destination / "gate_report.json").read_text(encoding="utf-8"))
        manifest = json.loads((destination / "reference_manifest.json").read_text(encoding="utf-8"))
        record = json.loads((destination / "source_analysis" / "front.png.json").read_text(encoding="utf-8"))
        return record, manifest["views"][0], report

    def assert_readable(self, record):
        self.assertNotIn("error", record)
        self.assertEqual(record["image_usability"], "usable")
        self.assertEqual(record["usability"], "reject:mask_error" if record["mask_status"] == "ERROR" else "usable")
        self.assertEqual(record["role"], "front")
        self.assertEqual(record["source_id"], "SYN-01")
        self.assertEqual(record["grade"], "A")

    def assert_no_invented_parts(self, record, view):
        self.assertIsNone(record["observed_parts"])
        self.assertIsNone(view["observed_parts"])
        self.assertIsNone(view["part_count_ok"])
        self.assertNotIn("otsu", record["mask_mode"])

    def test_readable_without_subject_has_no_mask_or_parts_and_h3_is_unknown(self):
        for expected in (0, 1):
            with self.subTest(expected=expected):
                completed, destination = self.run_gate(expected=expected)
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                record, view, report = self.outputs(destination)
                self.assert_readable(record)
                self.assertEqual(record["mask_status"], "NEEDS_SUBJECT")
                self.assertEqual(record["components"], [])
                self.assertIsNone(record["component_count_proxy"])
                self.assertIsNone(record["coverage_frac"])
                self.assertIsNone(record["mirror_iou"])
                self.assert_no_invented_parts(record, view)
                for field in ("mask_status", "mask_metadata", "mask_artifacts"):
                    self.assertEqual(view[field], record[field])
                self.assertEqual(set(record["mask_artifacts"]), {"ignore"})
                self.assertEqual(report["H2_reject"], [])
                self.assertFalse(report["hardGatesPass"])
                self.assertIn("missing_manual_structure_evidence", report["H3_part_count_mismatch"][0]["reason"])
                self.assertIn("NEEDS_SUBJECT", (destination / "gate_report.md").read_text(encoding="utf-8"))
                self.assertEqual(list((destination / "overlay").glob("*.mask.png")), [])

    def test_alpha_and_needs_subject_paths_run_without_numpy_or_opencv(self):
        completed, destination = self.run_gate(expected=1, no_runtime=True)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assert_readable(record)
        self.assertEqual(record["mask_status"], "NEEDS_SUBJECT")
        self.make_alpha()
        completed, destination = self.run_gate(expected=1, no_runtime=True)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assertEqual(record["mask_status"], "CANDIDATE")
        self.assertEqual(record["mask_mode"], "source_alpha")
        self.assertEqual(record["component_count_proxy"], 1)
        self.assert_no_invented_parts(record, view)
        self.assertTrue({"mask", "ignore", "overlay", "mask_sha256"} <= set(record["mask_artifacts"]))

    @unittest.skipUnless(HAS_SEGMENTATION, "prompted segmentation requires numpy and OpenCV")
    def test_prompt_keeps_dark_and_light_subject_and_emits_ignore_and_overlay(self):
        completed, destination = self.run_gate(subjects=[self.subject()], expected=1)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assert_readable(record)
        self.assertEqual(record["mask_status"], "CANDIDATE")
        self.assertEqual(record["mask_mode"], "seeded_grabcut")
        self.assertEqual(record["component_count_proxy"], len(record["components"]))
        self.assert_no_invented_parts(record, view)
        self.assertEqual(record["mask_metadata"]["semantic_review"], "unreviewed")
        self.assertIsNone(record["mask_metadata"]["semantic_iou"])
        artifacts = record["mask_artifacts"]
        self.assertEqual(Path(artifacts["mask"]), destination / "overlay" / "front.png.mask.png")
        with Image.open(artifacts["mask"]) as mask, Image.open(artifacts["ignore"]) as ignore, Image.open(artifacts["overlay"]) as overlay:
            self.assertEqual((mask.mode, ignore.mode), ("L", "L"))
            self.assertEqual(overlay.size, self.truth.size)
            self.assertEqual(mask.getpixel((80, 128)), 255)
            self.assertEqual(mask.getpixel((240, 128)), 255)
            self.assertEqual(mask.getpixel((10, 10)), 0)
            self.assertEqual(ignore.getpixel((160, 48)), 255)
            self.assertEqual(mask.getpixel((160, 48)), 0)
            self.assertIsNone(ImageChops.difference(mask, ImageChops.subtract(self.truth, ignore)).getbbox())
        self.assertEqual(artifacts["mask_sha256"], hashlib.sha256(Path(artifacts["mask"]).read_bytes()).hexdigest())
        self.assertEqual(view["mask_artifacts"], artifacts)


    def test_hash_missing_invalid_and_mismatched_declarations_fail_visibly(self):
        for name, value in (("missing", None), ("malformed", "not-a-hash"), ("wrong", "0" * 64)):
            with self.subTest(binding=name):
                subject = self.subject()
                if value is None:
                    del subject["image_sha256"]
                else:
                    subject["image_sha256"] = value
                completed, destination = self.run_gate(subjects=[subject], out=self.root / name)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("image_sha256", completed.stdout)
                self.assertFalse((destination / "reference_manifest.json").exists())

    def test_image_size_missing_or_mismatched_is_visible_failure(self):
        for value in (None, [256, 320], [320, True]):
            with self.subTest(image_size=value):
                completed, destination = self.run_gate(subjects=[dict(self.subject(), image_size=value)])
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("image_size", completed.stdout)

    def test_duplicate_files_and_relative_path_aliases_are_not_overwritten(self):
        for alias in ("front.png", "./front.png", "folder/../front.png"):
            with self.subTest(alias=alias):
                subject = self.subject()
                completed, destination = self.run_gate(subjects=[subject, dict(subject, file=alias)])
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("duplicate subject file", completed.stdout)

    def test_bad_schema_nonlist_views_and_outside_paths_fail_visibly(self):
        documents = [[], {"schema": "wrong", "views": []},
                     {"schema": "reference-subject-spec-set/1", "views": {}},
                     {"schema": "reference-subject-spec-set/1", "views": [None]}]
        for relative in ("../outside.png", str(self.source)):
            documents.append({"schema": "reference-subject-spec-set/1", "views": [dict(self.subject(), file=relative)]})
        for document in documents:
            with self.subTest(document=document):
                completed, destination = self.run_gate(raw_subjects=json.dumps(document))
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("FAIL subjects", completed.stdout)

    def test_excluded_images_still_have_their_declared_bindings_checked(self):
        subject = dict(self.subject(), image_sha256="0" * 64)
        completed, destination = self.run_gate(subjects=[subject], extra=["--exclude", "front.png"])
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn("image_sha256 does not match", completed.stdout)

    def test_malformed_json_never_falls_back_to_threshold_masks(self):
        completed, destination = self.run_gate(raw_subjects="{not json")
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn("FAIL subjects", completed.stdout)

    def test_invalid_prompt_fields_never_produce_a_usable_mask(self):
        changes = [
            {"target": ""}, {"coordinate_space": "pixel_xy"}, {"scope": "largest-component"},
            {"bbox": [-0.1, 0.1, 0.9, 0.9]}, {"bbox": [0.5, 0.1, 0.5, 0.9]},
            {"foreground_strokes": "auto"}, {"foreground_strokes": [{"points": [[1.1, 0.5]]}]},
            {"background_strokes": [None]}, {"ignore_polygons": [[[0.1, 0.1], [0.2, 0.2]]]},
            {"iterations": 0}, {"max_side": 64},
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                completed, destination = self.run_gate(subjects=[dict(self.subject(), **change)], out=self.root / ("invalid_%d" % index))
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("MASK ERROR", completed.stdout)
                record, view, report = self.outputs(destination)
                self.assert_readable(record)
                self.assertEqual(record["mask_status"], "ERROR")
                self.assertTrue(record["mask_error"])
                self.assertEqual(record["mask_metadata"]["error"], record["mask_error"])
                self.assertEqual(record["reason"], record["mask_error"])
                self.assertEqual(view["mask_status"], "ERROR")
                self.assertEqual(view["mask_error"], record["mask_error"])
                self.assertEqual(record["mask_artifacts"], {})
                self.assertFalse(report["hardGatesPass"])
                self.assertFalse((destination / "overlay" / "front.png.mask.png").exists())

    @unittest.skipUnless(HAS_SEGMENTATION, "prompted segmentation requires numpy and OpenCV")
    def test_empty_and_conflicting_foreground_are_mask_errors_not_unreadable(self):
        base = self.subject()
        for name, change in (("empty", {"foreground_strokes": []}),
                             ("conflict", {"background_strokes": copy.deepcopy(base["foreground_strokes"])})):
            with self.subTest(prompt=name):
                completed, destination = self.run_gate(subjects=[dict(base, **change)], out=self.root / name)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                record, view, report = self.outputs(destination)
                self.assert_readable(record)
                self.assertEqual(record["mask_status"], "ERROR")
                self.assertIsNone(record["coverage_frac"])
                self.assertEqual(record["components"], [])
                self.assertEqual(record["mask_artifacts"], {})
                self.assertEqual(report["H2_reject"], [])
                self.assertFalse(report["hardGatesPass"])
                self.assertIn("MASK ERROR", completed.stdout)

    def test_invalid_stroke_is_rejected_for_alpha_input_too(self):
        self.make_alpha()
        subject = self.subject()
        subject["foreground_strokes"][0]["radius"] = 1
        completed, destination = self.run_gate(subjects=[subject], no_runtime=True)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn("radius", completed.stdout)

    def test_missing_runtime_is_an_explicit_mask_error_not_unreadable(self):
        completed, destination = self.run_gate(subjects=[self.subject()], no_runtime=True)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assert_readable(record)
        self.assertEqual(record["mask_status"], "ERROR")
        self.assertIn("numpy and OpenCV", record["mask_error"])
        self.assertEqual(record["components"], [])
        self.assertIsNone(record["coverage_frac"])
        self.assertEqual(record["mask_artifacts"], {})
        self.assertIn("MASK ERROR", completed.stdout)
        self.assertFalse(report["hardGatesPass"])

    def test_old_component_count_is_not_verified_observed_parts(self):
        self.make_alpha()
        self.out.mkdir()
        (self.out / "reference_manifest.json").write_text(json.dumps({"views": [
            {"file": "front.png", "expected_parts": 1, "observed_parts": 1, "part_count_ok": True}
        ]}), encoding="utf-8")
        completed, destination = self.run_gate()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assertEqual(record["component_count_proxy"], 1)
        self.assert_no_invented_parts(record, view)
        self.assertIn("unknown", view["part_count_reason"])
        self.assertFalse(report["hardGatesPass"])

    def test_manual_structural_observation_is_bound_to_current_original(self):
        self.make_alpha()
        self.out.mkdir()
        evidence = {"kind": "manual-structure-review", "by": "fixture author",
                    "source": "independently specified fixture rectangles",
                    "image_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}
        for digest, expected_code in ((evidence["image_sha256"], 0), ("0" * 64, 1)):
            with self.subTest(image_hash=digest):
                evidence["image_sha256"] = digest
                (self.out / "reference_manifest.json").write_text(json.dumps({"views": [
                    {"file": "front.png", "expected_parts": 1, "observed_parts": 1,
                     "observed_parts_evidence": evidence}
                ]}), encoding="utf-8")
                completed, destination = self.run_gate(no_runtime=True)
                self.assertEqual(completed.returncode, expected_code, completed.stdout + completed.stderr)
                record, view, report = self.outputs(destination)
                if expected_code == 0:
                    self.assertEqual(view["observed_parts"], 1)
                    self.assertIs(view["part_count_ok"], True)
                else:
                    self.assert_no_invented_parts(record, view)
                    self.assertIn("hash_mismatch", view["part_count_reason"])

    @unittest.skipUnless(HAS_SEGMENTATION, "prompted segmentation requires numpy and OpenCV")
    def test_rerun_without_subject_does_not_reuse_old_mask_or_overlay(self):
        completed, destination = self.run_gate(subjects=[self.subject()], expected=1)
        record, view, report = self.outputs(destination)
        previous_mask = Path(record["mask_artifacts"]["mask"])
        previous_overlay = Path(record["mask_artifacts"]["overlay"])
        self.assertTrue(previous_mask.exists())
        completed, destination = self.run_gate()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assertEqual(record["mask_status"], "NEEDS_SUBJECT")
        self.assertFalse(previous_mask.exists())
        self.assertFalse(previous_overlay.exists())
        self.assertEqual(set(record["mask_artifacts"]), {"ignore"})

    def test_pair_missing_subject_is_unverified_not_fake_iou_green(self):
        completed, destination = self.run_gate(extra=["--pair", "front=front.png:front.png"])
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        pair = report["pairs"][0]
        self.assertEqual(pair["verdict"], "unverified")
        self.assertEqual(pair["diagnostic_verdict"], "unknown")
        self.assertIsNone(pair["mask_iou"])
        self.assertIn("NEEDS_SUBJECT", pair["error"])
        self.assertFalse(report["hardGatesPass"])
        self.assertIn("PAIR UNVERIFIED", completed.stdout)

    @unittest.skipUnless(HAS_SEGMENTATION, "prompted segmentation requires numpy and OpenCV")
    def test_pair_uses_ignore_union_and_remains_semantically_unreviewed(self):
        with Image.open(self.source) as image:
            render = image.convert("RGBA")
        render.putalpha(self.truth)
        render.save(self.refs / "render.png")
        completed, destination = self.run_gate(subjects=[self.subject()],
            extra=["--include", "front.png", "--pair", "front=front.png:render.png"])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        pair = report["pairs"][0]
        self.assertEqual(pair["mask_iou"], 1.0)
        self.assertEqual(pair["verdict"], "unverified")
        self.assertEqual(pair["diagnostic_verdict"], "pass")
        self.assertIn("not geometric", pair["diagnostic_note"])
        self.assertEqual(pair["mask_status"], "CANDIDATE")
        self.assertEqual(pair["semantic_verdict"], "unverified")
        self.assertEqual(pair["mask_metadata"]["semantic_review"], "unreviewed")
        markdown = (destination / "gate_report.md").read_text(encoding="utf-8")
        self.assertIn("diagnostic_verdict", markdown)
        self.assertIn("不构成几何或语义通过", markdown)
        self.assertIn("| unverified | pass |", markdown)

    def test_alpha_pair_runs_without_segmentation_runtime(self):
        self.make_alpha()
        completed, destination = self.run_gate(no_runtime=True, extra=["--pair", "front=front.png:front.png"])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assertEqual(report["pairs"][0]["mask_iou"], 1.0)
        self.assertEqual(report["pairs"][0]["verdict"], "unverified")
        self.assertEqual(report["pairs"][0]["diagnostic_verdict"], "pass")
        self.assertEqual(report["pairs"][0]["semantic_verdict"], "unverified")

    def test_degenerate_subject_never_falls_back_to_another_mask(self):
        self.make_alpha()
        subject = dict(self.subject(), bbox=[0.01, 0.01, 0.05, 0.05], ignore_polygons=[],
                       foreground_strokes=[], background_strokes=[])
        completed, destination = self.run_gate(subjects=[subject], expected=1, no_runtime=True)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assert_readable(record)
        self.assertEqual(record["mask_status"], "DEGENERATE")
        self.assertEqual(record["components"], [])
        self.assertIsNone(record["coverage_frac"])
        self.assert_no_invented_parts(record, view)
        self.assertNotIn("mask", record["mask_artifacts"])

    def test_build_mask_tuple_and_missing_mask_value_error_in_subprocess(self):
        code = textwrap.dedent("""
            import json
            from pathlib import Path
            import sys
            from PIL import Image, ImageDraw
            sys.path.insert(0, str(Path(sys.argv[1]).parent))
            from reference_intake_gate import build_mask
            with Image.open(sys.argv[2]) as image:
                try:
                    build_mask(image)
                except ValueError as error:
                    missing = str(error)
                else:
                    raise AssertionError('opaque image yielded a guessed mask')
                alpha = Image.new('L', image.size, 0)
                ImageDraw.Draw(alpha).rectangle((32, 32, 287, 223), fill=255)
                artwork = image.convert('RGBA')
                artwork.putalpha(alpha)
                mask, mode, coverage = build_mask(artwork)
                print(json.dumps({'missing': missing, 'mode': mode,
                                  'mask_mode': mask.mode, 'coverage': coverage}))
        """)
        completed = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPT_PATH), str(self.source)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertIn("NEEDS_SUBJECT", result["missing"])
        self.assertEqual(result["mask_mode"], "L")
        self.assertEqual(result["mode"], "source_alpha")
        self.assertEqual(result["coverage"], 0.6)


    def batch_subjects(self):
        self.make_alpha()
        nested = self.refs / "views"
        nested.mkdir()
        second_source = nested / "side.png"
        second_source.write_bytes(self.source.read_bytes())
        primary = self.subject()
        secondary = dict(primary, file="views/side.png",
                         image_sha256=hashlib.sha256(second_source.read_bytes()).hexdigest())
        return [primary, secondary]

    def test_batch_hash_binding_and_source_analysis_artifact_paths(self):
        subjects = self.batch_subjects()
        completed, destination = self.run_gate(subjects=subjects, no_runtime=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        manifest = json.loads((destination / "reference_manifest.json").read_text(encoding="utf-8"))
        entries = {view["file"]: view for view in manifest["views"]}
        for subject in subjects:
            with self.subTest(file=subject["file"]):
                stem = subject["file"].replace("/", "__")
                record_path = destination / "source_analysis" / (stem + ".json")
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(record["mask_status"], "CANDIDATE")
                self.assertEqual(record["sha256"], subject["image_sha256"])
                self.assertEqual(hashlib.sha256((self.refs / subject["file"]).read_bytes()).hexdigest(), subject["image_sha256"])
                self.assertEqual(record["mask_artifacts"], entries[subject["file"]]["mask_artifacts"])
                for kind, suffix in (("mask", ".mask.png"), ("ignore", ".mask.ignore.png"), ("overlay", ".mask.overlay.png")):
                    artifact = Path(record["mask_artifacts"][kind])
                    self.assertTrue(artifact.is_absolute())
                    self.assertTrue(artifact.is_file())
                    self.assertEqual(artifact, destination / "overlay" / (stem + suffix))
                    with Image.open(artifact) as image:
                        self.assertEqual(image.size, tuple(subject["image_size"]))
                mask_path = Path(record["mask_artifacts"]["mask"])
                self.assertEqual(record["mask_artifacts"]["mask_sha256"], hashlib.sha256(mask_path.read_bytes()).hexdigest())

    def test_batch_second_file_hash_mismatch_is_a_visible_input_error(self):
        subjects = self.batch_subjects()
        subjects[1]["image_sha256"] = "0" * 64
        completed, destination = self.run_gate(subjects=subjects, no_runtime=True)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        diagnostic = next(json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{"))
        self.assertEqual(diagnostic["mask_status"], "ERROR")
        self.assertIn("views/side.png", diagnostic["mask_error"])
        self.assertIn("image_sha256", diagnostic["mask_error"])
        self.assertFalse((destination / "reference_manifest.json").exists())

    def test_batch_invalid_hint_is_recorded_as_error_not_ordinary_usable(self):
        subjects = self.batch_subjects()
        subjects[1]["background_strokes"] = [{"points": [[1.2, 0.5]]}]
        completed, destination = self.run_gate(subjects=subjects, no_runtime=True)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        record = json.loads((destination / "source_analysis" / "views__side.png.json").read_text(encoding="utf-8"))
        self.assertEqual(record["image_usability"], "usable")
        self.assertEqual(record["usability"], "reject:mask_error")
        self.assertEqual(record["mask_status"], "ERROR")
        self.assertIn("background_strokes", record["mask_error"])
        self.assertEqual(record["mask_metadata"]["error"], record["mask_error"])
        self.assertEqual(record["mask_artifacts"], {})
        self.assertIsNone(record["coverage_frac"])
        report = json.loads((destination / "gate_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["H2_reject"], [])
        self.assertFalse(report["hardGatesPass"])

    def test_batch_filtered_invalid_hint_is_not_silently_ignored(self):
        subjects = self.batch_subjects()
        subjects[1]["iterations"] = 0
        completed, destination = self.run_gate(subjects=subjects, no_runtime=True, extra=["--include", "front.png"])
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        record, view, report = self.outputs(destination)
        self.assertEqual(record["mask_status"], "CANDIDATE")
        self.assertEqual(report["images"], 1)
        error = report["mask_errors"][0]
        self.assertEqual(error["file"], "views/side.png")
        self.assertEqual(error["mask_status"], "ERROR")
        self.assertIn("iterations", error["error"])
        self.assertFalse(report["hardGatesPass"])


if __name__ == "__main__":
    unittest.main()
