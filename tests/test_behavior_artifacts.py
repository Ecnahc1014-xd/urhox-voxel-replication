import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PACKAGE_ROOT / 'scripts'


def asymmetric_occupancy():
    cells = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0),
             (0, 0, 1), (0, 0, 2), (0, 0, 3)}
    views = {}
    for name, axes, width, height in (('front', (0, 1), 3, 2),
                                      ('side', (2, 1), 4, 2),
                                      ('top', (0, 2), 3, 4)):
        occupied = {(cell[axes[0]], cell[axes[1]]) for cell in cells}
        packed = bytearray((width * height + 7) // 8)
        for horizontal, vertical in occupied:
            offset = vertical * width + horizontal
            packed[offset // 8] |= 1 << (offset % 8)
        views[name] = {'h': width, 'v': height, 'hAxis': 'xyz'[axes[0]],
                       'vAxis': 'xyz'[axes[1]],
                       'bits': base64.b64encode(packed).decode('ascii')}
    return {'schema': 'urhox-occupancy-masks/1', 'subject': 'asymmetric-fixture',
            'voxelSizeMeters': 0.5, 'cellCount': len(cells), 'upAxis': 'y',
            'bbox': {'min': [0, 0, 0], 'max': [2, 1, 3]}, 'views': views}


class ArtifactBehavior(unittest.TestCase):
    def run_tool(self, filename, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT_ROOT / filename), *map(str, arguments)],
            cwd=PACKAGE_ROOT, env={**os.environ, 'PYTHONUTF8': '1',
                                   'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, encoding='utf-8', timeout=60)

    def test_opaque_alpha_masks_cannot_pass_as_matching_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference, model = root / 'reference.png', root / 'model.png'
            Image.new('L', (32, 32), 0).save(reference)
            Image.new('L', (32, 32), 255).save(model)
            result = self.run_tool('compare_masks.py', '--ref', reference,
                                   '--render', model, '--res', '32')
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report['results'][0]['degenerate'])
            self.assertIsNone(report['results'][0]['iou'])

    def test_binary_mask_reports_known_intersection_and_union(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = Image.new('L', (32, 32), 0)
            model = Image.new('L', (32, 32), 0)
            ImageDraw.Draw(reference).rectangle((8, 8, 15, 15), fill=255)
            ImageDraw.Draw(model).rectangle((9, 8, 16, 15), fill=255)
            reference.save(root / 'reference.png')
            model.save(root / 'model.png')
            result = self.run_tool('compare_masks.py', '--ref', root / 'reference.png',
                                   '--render', root / 'model.png', '--mode', 'luma-fixed',
                                   '--res', '32')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            reading = json.loads(result.stdout)['results'][0]
            self.assertEqual(reading['intersection'], 56)
            self.assertEqual(reading['union'], 72)
            self.assertAlmostEqual(reading['iou'], 7 / 9)
            self.assertFalse(reading['degenerate'])
            self.assertEqual(reading['status'], 'FAIL')
            identical = self.run_tool('compare_masks.py', '--ref', root / 'reference.png',
                                      '--render', root / 'reference.png', '--mode', 'luma-fixed',
                                      '--res', '32')
            self.assertEqual(identical.returncode, 0, identical.stdout + identical.stderr)
            self.assertEqual(json.loads(identical.stdout)['results'][0]['iou'], 1.0)

    def test_true_voxel_projection_can_render_all_three_masks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occupancy = root / 'occupancy.json'
            occupancy.write_text(json.dumps(asymmetric_occupancy()), encoding='utf-8')
            result = self.run_tool('voxel_silhouette_drawing.py', '--occupancy', occupancy,
                                   '--out', root / 'drawing')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            projection_path = root / 'drawing' / 'projection.json'
            projection = json.loads(projection_path.read_text(encoding='utf-8'))
            self.assertEqual(projection['worldBounds']['size'], [1.5, 1.0, 2.0])
            self.assertEqual(projection['trueSolidVolumeM3'], 0.875)
            scales = {projection['views'][name]['mmPerMeter'] for name in ('front', 'side', 'top')}
            self.assertEqual(len(scales), 1)
            for segments in projection['linesMm'].values():
                self.assertTrue(all(0 <= segment[index] <= 165 for segment in segments for index in (0, 2)))
                self.assertTrue(all(0 <= segment[index] <= 100 for segment in segments for index in (1, 3)))
            for name, expected_area in (('front', 100), ('side', 125), ('top', 150)):
                mask_path = root / (name + '.png')
                mask = self.run_tool('projection_to_mask.py', '--projection', projection_path,
                                     '--view', name, '--ortho-size', '4', '--res', '40x40',
                                     '--center', '0.75,0.5,1', '--out', mask_path)
                self.assertEqual(mask.returncode, 0, mask.stdout + mask.stderr)
                with Image.open(mask_path) as image:
                    self.assertEqual(image.histogram()[255], expected_area)

    def test_missing_requested_cad_backend_cannot_report_export_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occupancy = root / 'occupancy.json'
            occupancy.write_text(json.dumps(asymmetric_occupancy()), encoding='utf-8')
            result = self.run_tool('voxel_silhouette_drawing.py', '--occupancy', occupancy,
                                   '--out', root / 'drawing', '--cadstack', root / 'missing-backend')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'drawing' / 'sheet.pdf').exists())

    def test_aspect_mismatch_cannot_pass_as_aligned_masks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, size, rectangle in (('reference', (32, 32), (8, 8, 15, 15)),
                                          ('model', (64, 32), (16, 8, 31, 15))):
                mask = Image.new('L', size, 0)
                ImageDraw.Draw(mask).rectangle(rectangle, fill=255)
                mask.save(root / (name + '.png'))
            result = self.run_tool('compare_masks.py', '--ref', root / 'reference.png',
                                   '--render', root / 'model.png', '--mode', 'luma-fixed', '--res', '32')
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            reading = json.loads(result.stdout)['results'][0]
            self.assertTrue(reading['unaligned'])
            self.assertEqual(reading['status'], 'PASS-WATCH')

    def test_actual_feature_tag_file_rejects_unknown_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'feature_tags.json'
            document = {'schema': 'urhox-feature-tags/1', 'taxonomyVersion': 'v1',
                        'images': [{'file': 'reference.png', 'axes': {'form': ['layered-tier'],
                                    'style_dna': ['era:modern']},
                                    'provenance': 'human', 'note': ''}]}
            path.write_text(json.dumps(document), encoding='utf-8')
            accepted = self.run_tool('feature_taxonomy_check.py', '--tags', path, '--json')
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            document['images'][0]['axes']['form'] = ['unsupported-geometry-claim']
            path.write_text(json.dumps(document), encoding='utf-8')
            rejected = self.run_tool('feature_taxonomy_check.py', '--tags', path, '--json')
            self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
            self.assertTrue(json.loads(rejected.stdout.split('VERDICT:')[0])['problems'])


if __name__ == '__main__':
    unittest.main()
