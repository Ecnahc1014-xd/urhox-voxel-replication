import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageChops, ImageDraw


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PACKAGE_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPT_ROOT))
from reference_subject_mask import extract_subject, write_artifacts
from reference_mask_stability import summarize_variants


def specification(size, bbox, points):
    return {'target': 'synthetic object', 'scope': 'whole-subject', 'coordinate_space': 'normalized_xy', 'image_size': list(size), 'bbox': list(bbox), 'foreground_strokes': [{'points': [list(point)], 'radius': 0.001} for point in points], 'background_strokes': [{'points': [[0.05, 0.5]], 'radius': 0.005}], 'ignore_polygons': [], 'max_side': 1280}


def synthetic_result(mask, ignore):
    return {'mask': mask, 'ignore': ignore, 'mode': 'fixture', 'status': 'CANDIDATE', 'metadata': {'selected_pixels': mask.histogram()[255]}}


class ReferenceMaskExtensions(unittest.TestCase):
    def cli(self, filename, *arguments):
        return subprocess.run([sys.executable, '-B', str(SCRIPT_ROOT / filename), *map(str, arguments)], capture_output=True, text=True, encoding='utf-8', timeout=120)

    def test_large_source_uses_original_resolution_target_roi_without_bbox_expansion(self):
        image = Image.new('RGB', (4200, 1001), (208, 180, 140))
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((400, 300, 999, 849), fill=(35, 70, 145))
        drawing.rectangle((735, 150, 737, 299), fill=(35, 70, 145))
        subject = specification(image.size, (350 / 4199, 100 / 1000, 1050 / 4199, 900 / 1000), ((700 / 4199, 650 / 1000), (735 / 4199, 200 / 1000)))
        original_bytes = image.tobytes()
        original_subject = copy.deepcopy(subject)
        result = extract_subject(image, subject)
        self.assertEqual(result['status'], 'CANDIDATE')
        self.assertEqual(result['mask'].size, image.size)
        self.assertIsNone(result['metadata']['refinement']['skipped_reason'])
        region = result['metadata']['refinement']['region_pixels']
        self.assertLess((region[2] - region[0]) * (region[3] - region[1]), 4_000_000)
        self.assertNotEqual(result['metadata']['refinement']['image_size'], list(image.size))
        self.assertEqual(result['mask'].crop((500, 400, 900, 800)).getextrema(), (255, 255))
        self.assertEqual(result['mask'].crop((730, 155, 734, 290)).getextrema(), (0, 0))
        self.assertEqual(result['mask'].crop((738, 155, 740, 290)).getextrema(), (0, 0))
        self.assertEqual(result['mask'].getpixel((735, 155)), 255)
        self.assertEqual(result['mask'].crop((1200, 100, 4199, 950)).getextrema(), (0, 0))
        self.assertEqual(image.tobytes(), original_bytes)
        self.assertEqual(subject, original_subject)

    def test_enclosed_known_background_aperture_is_not_automatically_filled(self):
        image = Image.new('RGB', (1536, 256), (208, 180, 140))
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((400, 32, 1100, 224), fill=(35, 70, 145))
        drawing.rectangle((600, 72, 900, 180), fill=(208, 180, 140))
        subject = specification(image.size, (350 / 1535, 16 / 255, 1150 / 1535, 240 / 255), ((450 / 1535, 128 / 255),))
        result = extract_subject(image, subject)
        self.assertEqual(result['mask'].crop((625, 90, 875, 165)).getextrema(), (0, 0))
        self.assertEqual(result['mask'].crop((425, 60, 550, 200)).getextrema(), (255, 255))
        self.assertEqual(result['metadata']['semantic_review'], 'unreviewed')
        self.assertIsNone(result['metadata']['semantic_iou'])

    def test_mask_ignore_and_overlay_hashes_bind_saved_lossless_artifacts(self):
        """Artifact hashes describe candidates, not semantic approval."""
        image = Image.new('RGBA', (32, 24), (50, 60, 70, 0))
        ImageDraw.Draw(image).rectangle((6, 4, 24, 20), fill=(50, 60, 70, 255))
        result = extract_subject(image)
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = write_artifacts(image, result, Path(temporary) / 'mask.png')
            for key in ('mask', 'ignore', 'overlay'):
                self.assertEqual(artifacts[key + '_sha256'], hashlib.sha256(Path(artifacts[key]).read_bytes()).hexdigest())
            with Image.open(artifacts['mask']) as mask:
                self.assertEqual(set(mask.tobytes()), {0, 255})

    def test_detail_recovery_is_experimental_opt_in_and_rejects_non_boolean_values(self):
        image = Image.new("RGB", (1536, 256), (208, 180, 140))
        ImageDraw.Draw(image).rectangle((400, 32, 1100, 224), fill=(35, 70, 145))
        subject = specification(image.size, (350 / 1535, 16 / 255, 1150 / 1535, 240 / 255), ((450 / 1535, 128 / 255),))
        default = extract_subject(image, subject)
        disabled = extract_subject(image, {**subject, "recover_details": False})
        enabled = extract_subject(image, {**subject, "recover_details": True})
        self.assertIsNone(ImageChops.difference(default["mask"], disabled["mask"]).getbbox())
        self.assertFalse(default["metadata"]["refinement"]["detail_recovery_enabled"])
        self.assertEqual(default["metadata"]["refinement"]["detail_recovery_status"], "disabled_by_default_after_visual_regression")
        self.assertTrue(enabled["metadata"]["refinement"]["detail_recovery_enabled"])
        self.assertEqual(enabled["metadata"]["refinement"]["detail_recovery_status"], "experimental_opt_in")
        self.assertEqual(enabled["metadata"]["semantic_review"], "unreviewed")
        for value in (1, "true", None, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "recover_details"):
                    extract_subject(image, {**subject, "recover_details": value})

    def test_colliding_output_paths_and_input_spec_overwrite_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            Image.new('RGBA', (32, 24), (60, 60, 60, 0)).save(source)
            prompt = root / 'subject.json'
            prompt.write_text('{}', encoding='utf-8')
            original_source = source.read_bytes()
            original_prompt = prompt.read_bytes()
            destination = root / 'mask.png'
            for report in (destination, root / 'mask.ignore.png', root / 'mask.overlay.png', source, prompt):
                with self.subTest(report=report.name):
                    completed = self.cli('reference_subject_mask.py', '--image', source, '--out', destination, '--subject-spec', prompt, '--out-json', report)
                    self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                    self.assertFalse(destination.exists())
                    self.assertEqual(source.read_bytes(), original_source)
                    self.assertEqual(prompt.read_bytes(), original_prompt)

    def test_lossy_mask_destinations_are_rejected_before_artifact_creation(self):
        image = Image.new('RGBA', (32, 24), (60, 60, 60, 0))
        ImageDraw.Draw(image).rectangle((4, 4, 24, 18), fill=(60, 60, 60, 255))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            image.save(source)
            destination = root / 'mask.jpg'
            with self.assertRaisesRegex(ValueError, 'lossless'):
                write_artifacts(image, extract_subject(image), destination)
            completed = self.cli('reference_subject_mask.py', '--image', source, '--out', destination)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(list(root.iterdir()), [source])

    def test_stability_uses_unchanged_common_domain_not_automatic_unknown_growth(self):
        before = Image.new('L', (10, 10), 0)
        ImageDraw.Draw(before).rectangle((2, 2, 6, 6), fill=255)
        after = before.copy()
        ImageDraw.Draw(after).rectangle((7, 2, 7, 6), fill=255)
        ignored = Image.new('L', (10, 10), 0)
        ImageDraw.Draw(ignored).rectangle((7, 4, 7, 6), fill=255)
        old_bytes = [image.tobytes() for image in (before, after, ignored)]
        summary, disagreement = summarize_variants([synthetic_result(before, ignored), synthetic_result(after, ignored)])
        self.assertEqual(summary['source_pixels'], 100)
        self.assertEqual(summary['ignored_pixels'], 3)
        self.assertEqual(summary['common_valid_pixels'], 97)
        self.assertEqual(summary['disagreement_pixels'], 2)
        self.assertEqual(disagreement.getpixel((7, 3)), 255)
        self.assertEqual(disagreement.getpixel((7, 5)), 0)
        self.assertEqual([image.tobytes() for image in (before, after, ignored)], old_bytes)
        self.assertEqual(summary['semantic_verdict'], 'unverified')
        self.assertIsNone(summary['semantic_iou'])

    def test_stability_rejects_changed_ignore_domain_instead_of_shrinking_denominator(self):
        mask = Image.new('L', (10, 10), 0)
        ImageDraw.Draw(mask).rectangle((2, 2, 6, 6), fill=255)
        first_ignore = Image.new('L', mask.size, 0)
        changed_ignore = first_ignore.copy()
        changed_ignore.putpixel((8, 8), 255)
        with self.assertRaisesRegex(ValueError, 'ignore domain'):
            summarize_variants([synthetic_result(mask, first_ignore), synthetic_result(mask, changed_ignore)])

    def test_alpha_control_stability_has_no_semantic_acceptance_and_preserves_source(self):
        image = Image.new('RGBA', (32, 24), (60, 60, 60, 0))
        ImageDraw.Draw(image).rectangle((4, 4, 24, 18), fill=(60, 60, 60, 255))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            image.save(source)
            original = source.read_bytes()
            output = root / 'new-evidence'
            completed = self.cli('reference_mask_stability.py', '--image', source, '--out-dir', output)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads((output / 'stability.json').read_text(encoding='utf-8'))
            self.assertEqual(report['disagreement_pixels'], 0)
            self.assertEqual(report['semantic_verdict'], 'unverified')
            self.assertEqual({variant['metadata']['scope'] for variant in report['variants']}, {'source-alpha'})
            self.assertEqual(source.read_bytes(), original)
            repeat = self.cli('reference_mask_stability.py', '--image', source, '--out-dir', output)
            self.assertEqual(repeat.returncode, 2)


if __name__ == '__main__':
    unittest.main()
