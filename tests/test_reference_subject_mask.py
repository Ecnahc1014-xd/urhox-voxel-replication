"""Independent synthetic regressions for reference subject extraction.

Run from the package root with:
    python -B -m unittest discover -s tests -p test_reference_subject_mask.py -v

Known rectangles are fixture truth, never inferred from the tool's output.
Exit 0 denotes a candidate, not semantic acceptance. These tests neither score
segmentation nor replace visual review of the ten external reference overlays.
"""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageChops, ImageDraw


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PACKAGE_ROOT / 'scripts' / 'reference_subject_mask.py'


def rectangle_truth(size, *rectangles):
    truth = Image.new('L', size, 0)
    drawing = ImageDraw.Draw(truth)
    for left, top, right, bottom in rectangles:
        drawing.rectangle((left, top, right - 1, bottom - 1), fill=255)
    return truth


def stroke(*points, radius=0.01):
    return {'points': [list(point) for point in points], 'radius': radius}


def subject_spec(size, bbox, foreground_points, scope='whole-subject'):
    return {
        'target': 'independently known synthetic rectangle',
        'scope': scope,
        'coordinate_space': 'normalized_xy',
        'image_size': list(size),
        'bbox': list(bbox),
        'foreground_strokes': [stroke(point) for point in foreground_points],
        'background_strokes': [stroke((0.02, 0.02)), stroke((0.98, 0.98))],
        'ignore_polygons': [],
        'iterations': 5,
        'max_side': 1024,
    }


def majority_fixture(background=(95, 145, 85), scope='whole-subject'):
    image = Image.new('RGB', (96, 80), background)
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((8, 8, 47, 71), fill=(18, 24, 30))
    drawing.rectangle((48, 8, 87, 71), fill=(238, 242, 230))
    truth = rectangle_truth(image.size, (8, 8, 88, 72))
    specification = subject_spec(
        image.size, (5 / 96, 5 / 80, 91 / 96, 75 / 80),
        ((0.25, 0.5), (0.75, 0.5)), scope)
    return image, truth, specification


def same_color_fixture():
    image = Image.new('RGB', (168, 96), (220, 180, 130))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((12, 16, 51, 79), fill=(35, 70, 145))
    drawing.rectangle((84, 12, 151, 83), fill=(35, 70, 145))
    return image, ((12, 16, 52, 80), (84, 12, 152, 84))


def transparent_fixtures():
    size = (32, 24)
    rgba = Image.new('RGBA', size, (120, 120, 120, 0))
    drawing = ImageDraw.Draw(rgba)
    drawing.rectangle((8, 6, 25, 19), fill=(120, 120, 120, 255))
    drawing.rectangle((17, 6, 25, 19), fill=(120, 120, 120, 128))
    luminance_alpha = Image.new('LA', size, (120, 0))
    drawing = ImageDraw.Draw(luminance_alpha)
    drawing.rectangle((8, 6, 25, 19), fill=(120, 255))
    drawing.rectangle((17, 6, 25, 19), fill=(120, 128))
    palette = Image.new('P', size, 0)
    palette.putpalette([120, 120, 120] * 256)
    ImageDraw.Draw(palette).rectangle((8, 6, 25, 19), fill=1)
    palette.info['transparency'] = 0
    palette_table = palette.copy()
    ImageDraw.Draw(palette_table).rectangle((17, 6, 25, 19), fill=2)
    palette_table.info['transparency'] = bytes([0, 255, 128] + [255] * 253)
    return (('rgba', rgba), ('luminance_alpha', luminance_alpha),
            ('palette_index', palette), ('palette_alpha_table', palette_table))


def opaque_fixtures():
    image = Image.new('RGB', (96, 80))
    pixels = image.load()
    for vertical in range(image.height):
        for horizontal in range(image.width):
            pixels[horizontal, vertical] = (
                (horizontal * 31 + vertical * 17) % 256,
                (horizontal * 7 + vertical * 43) % 256,
                (horizontal * 23 + vertical * 11) % 256)
    palette = Image.new('P', image.size, 1)
    palette.putpalette([120, 120, 120] * 256)
    palette.info['transparency'] = 0
    return (('rgb', image), ('rgba_opaque', image.convert('RGBA')),
            ('la_opaque', image.convert('LA')), ('luminance', image.convert('L')),
            ('palette_opaque', image.convert('P')),
            ('palette_unused_transparency', palette))


def invalid_subject_specs(base):
    cases = []
    for name, changes in (
        ('wrong_image_size', {'image_size': [80, 96]}),
        ('empty_target', {'target': ''}),
        ('unknown_scope', {'scope': 'largest-component'}),
        ('pixel_coordinate_space', {'coordinate_space': 'pixel_xy'}),
        ('empty_bbox', {'bbox': [0.5, 0.2, 0.5, 0.8]}),
        ('reversed_bbox', {'bbox': [0.8, 0.2, 0.2, 0.8]}),
        ('bbox_outside_image', {'bbox': [-0.1, 0.1, 0.9, 0.9]}),
        ('no_foreground', {'foreground_strokes': []}),
        ('empty_foreground_stroke', {
            'foreground_strokes': [{'points': [], 'radius': 0.01}]}),
        ('foreground_outside_image', {
            'foreground_strokes': [stroke((1.1, 0.5))]}),
        ('foreground_outside_bbox', {
            'foreground_strokes': [stroke((0.02, 0.5))]}),
        ('nonfinite_seed', {
            'foreground_strokes': [stroke((float('nan'), 0.5))]}),
        ('zero_radius', {'foreground_strokes': [stroke((0.25, 0.5), radius=0)]}),
        ('negative_radius', {
            'background_strokes': [stroke((0.02, 0.02), radius=-0.01)]}),
        ('opposed_seed_same_point', {
            'background_strokes': [stroke((0.25, 0.5))]}),
        ('opposed_seed_disks_overlap', {
            'foreground_strokes': [stroke((0.25, 0.5), radius=0.04)],
            'background_strokes': [stroke((0.28, 0.5), radius=0.04)]}),
        ('opposed_seed_segments_cross', {
            'foreground_strokes': [stroke((0.25, 0.25), (0.75, 0.75))],
            'background_strokes': [stroke((0.25, 0.75), (0.75, 0.25))]}),
        ('foreground_in_ignore', {
            'ignore_polygons': [[[0.2, 0.45], [0.3, 0.45],
                                 [0.3, 0.55], [0.2, 0.55]]]}),
        ('foreground_segment_crosses_ignore', {
            'foreground_strokes': [stroke((0.25, 0.5), (0.75, 0.5))],
            'ignore_polygons': [[[0.45, 0.4], [0.55, 0.4],
                                 [0.55, 0.6], [0.45, 0.6]]]}),
        ('background_in_ignore', {
            'ignore_polygons': [[[0, 0], [0.06, 0], [0.06, 0.06], [0, 0.06]]]}),
        ('invalid_ignore_polygon', {'ignore_polygons': [[[0.4, 0.4], [0.6, 0.6]]]}),
        ('zero_iterations', {'iterations': 0}),
        ('zero_max_side', {'max_side': 0}),
    ):
        specification = copy.deepcopy(base)
        specification.update(changes)
        cases.append((name, specification))
    specification = copy.deepcopy(base)
    del specification['foreground_strokes']
    cases.append(('missing_foreground', specification))
    return cases


class ReferenceSubjectMaskBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT_PATH.is_file():
            raise FileNotFoundError(
                f'Implementation not present: {SCRIPT_PATH}; do not report tests as passed.')
        specification = importlib.util.spec_from_file_location(
            '_reference_subject_mask_regression', SCRIPT_PATH)
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        previous_bytecode_setting = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            specification.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous_bytecode_setting
        cls.module = module

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='reference-subject-regression-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def extract(self, image, subject=None):
        return self.module.extract_subject(image.copy(), copy.deepcopy(subject))

    def save_image(self, image, name='source', **options):
        path = self.root / (name + '.png')
        image.save(path, **options)
        return path

    def run_cli(self, image_path, subject=None, name='candidate',
                raw_spec=None, out_json=True):
        mask_path = self.root / (name + '.png')
        report_path = self.root / (name + '.json')
        command = [sys.executable, '-B', str(SCRIPT_PATH),
                   '--image', str(image_path), '--out', str(mask_path)]
        if subject is not None or raw_spec is not None:
            spec_path = self.root / (name + '.subject.json')
            spec_path.write_text(raw_spec if raw_spec is not None else json.dumps(subject),
                                 encoding='utf-8')
            command.extend(['--subject-spec', str(spec_path)])
        if out_json:
            command.extend(['--out-json', str(report_path)])
        completed = subprocess.run(
            command, cwd=PACKAGE_ROOT,
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        return completed, mask_path, report_path

    def assert_box_value(self, image, box, value):
        self.assertEqual(image.crop(box).getextrema(), (value, value),
                         f'Expected {value} throughout independently specified box {box}')

    def assert_known_support(self, mask, truth):
        self.assertEqual(mask.mode, 'L')
        self.assertEqual(mask.size, truth.size)
        support = mask.point(lambda value: 255 if value else 0)
        self.assertIsNone(ImageChops.difference(support, truth).getbbox(),
                          'Support differs from the independent rectangle truth')

    def assert_disjoint(self, mask, ignore):
        foreground = mask.point(lambda value: 255 if value else 0)
        excluded = ignore.point(lambda value: 255 if value else 0)
        self.assertIsNone(ImageChops.multiply(foreground, excluded).getbbox(),
                          'Ignored pixels must never also be foreground')

    def assert_result(self, result, size, needs_subject=False, expected_mode='seeded_grabcut'):
        self.assertIsInstance(result, dict)
        self.assertTrue({'mask', 'ignore', 'mode', 'status', 'metadata'} <= result.keys())
        self.assertIsInstance(result['mode'], str)
        self.assertTrue(result['mode'])
        self.assertIsInstance(result['status'], str)
        self.assertTrue(result['status'])
        self.assertIsInstance(result['metadata'], dict)
        self.assertIsInstance(result['ignore'], Image.Image)
        self.assertEqual(result['ignore'].mode, 'L')
        self.assertEqual(result['ignore'].size, size)
        if needs_subject:
            self.assertEqual(result['status'], 'NEEDS_SUBJECT')
            self.assertIsNone(result['mask'])
        else:
            self.assertNotEqual(result['status'], 'NEEDS_SUBJECT')
            self.assertEqual(result['mode'], expected_mode)
            self.assertIsInstance(result['mask'], Image.Image)
            self.assertEqual(result['mask'].mode, 'L')
            self.assertEqual(result['mask'].size, size)
            self.assertIsNotNone(result['mask'].getbbox())
            self.assert_disjoint(result['mask'], result['ignore'])

    def assert_cli_candidate(self, image_path, subject=None, name='candidate',
                             out_json=True):
        completed, mask_path, report_path = self.run_cli(
            image_path, subject, name=name, out_json=out_json)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with Image.open(image_path) as source:
            expected_size = source.size
        artifacts = []
        for path in (mask_path, mask_path.with_name(mask_path.stem + '.ignore.png'),
                     mask_path.with_name(mask_path.stem + '.overlay.png')):
            self.assertTrue(path.is_file(), f'Missing CLI artifact: {path}')
            with Image.open(path) as artifact:
                artifact.load()
                self.assertEqual(artifact.size, expected_size)
                artifacts.append(artifact.copy())
        mask, ignore, overlay = artifacts
        self.assertEqual(mask.mode, 'L')
        self.assertEqual(ignore.mode, 'L')
        self.assertIsNotNone(mask.getbbox())
        self.assert_disjoint(mask, ignore)
        with Image.open(image_path) as source:
            self.assertIsNotNone(ImageChops.difference(
                overlay.convert('RGB'), source.convert('RGBA').convert('RGB')).getbbox(),
                'Overlay must visibly annotate the source rather than copy it unchanged')
        if out_json:
            self.assertTrue(report_path.is_file(), 'Requested CLI report is missing')
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertIsInstance(report, dict)
            self.assertNotEqual(report['status'], 'NEEDS_SUBJECT')
            self.assertEqual(report['mode'],
                             'source_alpha' if subject is None else 'seeded_grabcut')
        return mask, ignore, overlay

    def test_opaque_inputs_without_target_need_subject_instead_of_a_guessed_mask(self):
        for name, image in opaque_fixtures():
            with self.subTest(image=name):
                result = self.extract(image)
                self.assert_result(result, image.size, needs_subject=True)
                self.assertIsNone(result['ignore'].getbbox())

    def test_cli_unprompted_opaque_inputs_exit_three_and_do_not_write_a_mask(self):
        for name, image in opaque_fixtures():
            with self.subTest(image=name):
                source = self.save_image(image, name='source_' + name)
                completed, mask_path, report_path = self.run_cli(source, name=name)
                self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
                self.assertFalse(mask_path.exists(), 'Unprompted input produced a fake mask')
                report = json.loads(report_path.read_text(encoding='utf-8'))
                self.assertEqual(report['status'], 'NEEDS_SUBJECT')

    def test_valid_alpha_including_palette_transparency_is_used_by_api_and_cli(self):
        truth = rectangle_truth((32, 24), (8, 6, 26, 20))
        for name, image in transparent_fixtures():
            with self.subTest(image=name):
                result = self.extract(image)
                self.assert_result(result, image.size, expected_mode='source_alpha')
                self.assert_known_support(result['mask'], truth)
                self.assertIsNone(result['ignore'].getbbox())
                source = self.save_image(image, name='source_' + name)
                mask, ignore, overlay = self.assert_cli_candidate(source, name=name)
                self.assert_known_support(mask, truth)
                self.assertIsNone(ignore.getbbox())

    def test_majority_target_is_not_inverted_and_contains_dark_and_bright_parts(self):
        for background in ((70, 35, 90), (140, 190, 155)):
            for scope in ('whole-subject', 'local-part', 'subject-region'):
                with self.subTest(background=background, scope=scope):
                    image, truth, specification = majority_fixture(background, scope)
                    result = self.extract(image, specification)
                    self.assert_result(result, image.size)
                    self.assert_known_support(result['mask'], truth)
                    self.assert_box_value(result['mask'], (12, 12, 44, 68), 255)
                    self.assert_box_value(result['mask'], (52, 12, 84, 68), 255)
                    self.assertIsNone(result['ignore'].getbbox())

    def test_cli_majority_target_keeps_both_luminance_halves(self):
        for index, background in enumerate(((70, 35, 90), (140, 190, 155))):
            with self.subTest(background=background):
                image, truth, specification = majority_fixture(background)
                source = self.save_image(image, name=f'source_{index}')
                mask, ignore, overlay = self.assert_cli_candidate(
                    source, specification, name=f'candidate_{index}')
                self.assert_known_support(mask, truth)
                self.assertIsNone(ignore.getbbox())

    def test_bbox_distinguishes_target_from_same_color_distractor(self):
        image, rectangles = same_color_fixture()
        source = self.save_image(image)
        for name, rectangle, bbox, seed in (
            ('left', rectangles[0], (8 / 168, 12 / 96, 56 / 168, 84 / 96),
             (32 / 168, 0.5)),
            ('right', rectangles[1], (80 / 168, 8 / 96, 156 / 168, 88 / 96),
             (118 / 168, 0.5)),
        ):
            with self.subTest(target=name):
                specification = subject_spec(image.size, bbox, (seed,))
                truth = rectangle_truth(image.size, rectangle)
                result = self.extract(image, specification)
                self.assert_result(result, image.size)
                self.assert_known_support(result['mask'], truth)
                mask, ignore, overlay = self.assert_cli_candidate(
                    source, specification, name=name)
                self.assert_known_support(mask, truth)

    def test_only_seeded_components_survive_even_when_unseeded_object_is_larger(self):
        image, rectangles = same_color_fixture()
        source = self.save_image(image)
        bbox = (8 / 168, 8 / 96, 156 / 168, 88 / 96)
        for name, rectangle, seed in (
            ('small_seeded', rectangles[0], (32 / 168, 0.5)),
            ('large_seeded', rectangles[1], (118 / 168, 0.5)),
        ):
            with self.subTest(target=name):
                specification = subject_spec(image.size, bbox, (seed,))
                truth = rectangle_truth(image.size, rectangle)
                result = self.extract(image, specification)
                self.assert_result(result, image.size)
                self.assert_known_support(result['mask'], truth)
                mask, ignore, overlay = self.assert_cli_candidate(
                    source, specification, name=name)
                self.assert_known_support(mask, truth)

    def test_all_components_with_foreground_seeds_are_retained(self):
        image, rectangles = same_color_fixture()
        specification = subject_spec(
            image.size, (8 / 168, 8 / 96, 156 / 168, 88 / 96),
            ((32 / 168, 0.5), (118 / 168, 0.5)))
        truth = rectangle_truth(image.size, *rectangles)
        result = self.extract(image, specification)
        self.assert_result(result, image.size)
        self.assert_known_support(result['mask'], truth)
        source = self.save_image(image)
        mask, ignore, overlay = self.assert_cli_candidate(source, specification)
        self.assert_known_support(mask, truth)

    def test_ignore_is_separate_exclusion_not_background_hole_truth(self):
        image, truth, specification = majority_fixture()
        specification['ignore_polygons'] = [
            [[0.4, 0.3], [0.6, 0.3], [0.6, 0.7], [0.4, 0.7]]]
        result = self.extract(image, specification)
        self.assert_result(result, image.size)
        source = self.save_image(image)
        mask, ignore, overlay = self.assert_cli_candidate(source, specification)
        for channel, foreground, excluded in (
            ('api', result['mask'], result['ignore']), ('cli', mask, ignore),
        ):
            with self.subTest(channel=channel):
                self.assert_box_value(excluded, (42, 28, 54, 52), 255)
                self.assert_box_value(foreground, (42, 28, 54, 52), 0)
                self.assert_box_value(excluded, (0, 0, 96, 6), 0)
                self.assert_box_value(foreground, (12, 12, 34, 68), 255)
                self.assert_box_value(foreground, (62, 12, 84, 68), 255)
                self.assert_disjoint(foreground, excluded)
                self.assert_known_support(ImageChops.lighter(foreground, excluded), truth)

    def test_normalized_stroke_radius_uses_short_side_and_resize_restores_image_size(self):
        for long_side in (240, 1200):
            landscape = Image.new('RGB', (long_side, 80), (205, 170, 130))
            center = int(0.4 * long_side)
            ImageDraw.Draw(landscape).rectangle(
                (center - 16, 16, center + 15, 63), fill=(30, 70, 140))
            for orientation in ('landscape', 'portrait'):
                with self.subTest(orientation=orientation, long_side=long_side):
                    image = (landscape if orientation == 'landscape' else
                             landscape.transpose(Image.Transpose.TRANSPOSE))
                    bbox = ((0.25, 0.1, 0.75, 0.9) if orientation == 'landscape' else
                            (0.1, 0.25, 0.9, 0.75))
                    seed = ((0.4, 0.5) if orientation == 'landscape' else (0.5, 0.4))
                    foreground_box = ((center - 8, 24, center + 8, 56)
                                      if orientation == 'landscape' else
                                      (24, center - 8, 56, center + 8))
                    background_box = ((int(0.6 * long_side), 20, int(0.9 * long_side), 60)
                                      if orientation == 'landscape' else
                                      (20, int(0.6 * long_side), 60, int(0.9 * long_side)))
                    specification = subject_spec(image.size, bbox, (seed,))
                    specification['foreground_strokes'] = [stroke(seed, radius=0.1)]
                    specification['background_strokes'] = [stroke((0.5, 0.5), radius=0.05)]
                    result = self.extract(image, specification)
                    self.assert_result(result, image.size)
                    source = self.save_image(image, name=f'source_{orientation}_{long_side}')
                    mask, ignore, overlay = self.assert_cli_candidate(
                        source, specification, name=f'{orientation}_{long_side}')
                    for channel, foreground in (('api', result['mask']), ('cli', mask)):
                        with self.subTest(channel=channel):
                            self.assert_box_value(foreground, foreground_box, 255)
                            self.assert_box_value(foreground, background_box, 0)

    def test_seeds_disjoint_at_source_but_colliding_at_working_size_are_rejected(self):
        image = Image.new('RGB', (4097, 65), (205, 170, 130))
        ImageDraw.Draw(image).rectangle((1984, 16, 2001, 47), fill=(30, 70, 140))
        specification = subject_spec(
            image.size, (0.1, 0.1, 0.9, 0.9), ((2000 / 4096, 0.5),))
        specification['foreground_strokes'] = [stroke((2000 / 4096, 0.5), radius=0.001)]
        specification['background_strokes'] = [stroke((2003 / 4096, 0.5), radius=0.001)]
        with self.subTest(channel='api'):
            with self.assertRaises(ValueError):
                self.extract(image, specification)
        source = self.save_image(image)
        with self.subTest(channel='cli'):
            completed, mask_path, report_path = self.run_cli(source, specification)
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertFalse(mask_path.exists())

    def test_resized_result_is_clipped_to_bbox_at_full_resolution(self):
        image = Image.new('RGB', (2049, 65), (205, 170, 130))
        ImageDraw.Draw(image).rectangle((512, 8, 1939, 56), fill=(30, 70, 140))
        specification = subject_spec(image.size, (0.5, 0, 1, 1), ((0.8, 0.5),))
        specification['foreground_strokes'] = [stroke((0.8, 0.5), radius=0.04)]
        result = self.extract(image, specification)
        self.assert_result(result, image.size)
        source = self.save_image(image)
        mask, ignore, overlay = self.assert_cli_candidate(source, specification)
        for channel, foreground in (('api', result['mask']), ('cli', mask)):
            with self.subTest(channel=channel):
                self.assert_box_value(foreground, (0, 0, 1024, 65), 0)
                self.assertNotEqual(foreground.getpixel((1638, 32)), 0)

    def test_invalid_or_conflicting_prompts_raise_value_error(self):
        image, truth, specification = majority_fixture()
        for name, invalid in invalid_subject_specs(specification):
            with self.subTest(prompt=name):
                with self.assertRaises(ValueError):
                    self.extract(image, invalid)

    def test_cli_invalid_or_conflicting_prompts_exit_two_without_a_mask(self):
        image, truth, specification = majority_fixture()
        source = self.save_image(image)
        for name, invalid in invalid_subject_specs(specification):
            with self.subTest(prompt=name):
                completed, mask_path, report_path = self.run_cli(source, invalid, name=name)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(mask_path.exists(), 'Invalid prompt produced a candidate mask')

    def test_cli_subject_spec_is_one_object_and_malformed_json_is_an_error(self):
        image, truth, specification = majority_fixture()
        source = self.save_image(image)
        for name, raw_spec in (
            ('malformed_json', '{not valid json'),
            ('multiple_targets', json.dumps([specification, specification])),
            ('wrapped_targets', json.dumps({'subjects': [specification]})),
        ):
            with self.subTest(prompt=name):
                completed, mask_path, report_path = self.run_cli(
                    source, name=name, raw_spec=raw_spec)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(mask_path.exists())

    def test_cli_optional_sha256_binds_actual_file_bytes_not_decoded_pixels(self):
        image, truth, specification = majority_fixture()
        source = self.save_image(image, name='uncompressed', compress_level=0)
        same_pixels = self.save_image(image, name='compressed', compress_level=9)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        other_hash = hashlib.sha256(same_pixels.read_bytes()).hexdigest()
        self.assertNotEqual(source_hash, other_hash)
        with Image.open(source) as original, Image.open(same_pixels) as reencoded:
            self.assertEqual(original.tobytes(), reencoded.tobytes())
        specification['image_sha256'] = source_hash
        mask, ignore, overlay = self.assert_cli_candidate(
            source, specification, name='hash_bound')
        self.assert_known_support(mask, truth)
        for name, path, claimed_hash in (
            ('same_pixels_wrong_bytes', same_pixels, source_hash),
            ('wrong_digest', source, '0' * 64),
            ('malformed_digest', source, 'not-a-sha256'),
        ):
            with self.subTest(binding=name):
                invalid = copy.deepcopy(specification)
                invalid['image_sha256'] = claimed_hash
                completed, mask_path, report_path = self.run_cli(path, invalid, name=name)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(mask_path.exists(), 'Mismatched source hash produced a mask')

    def test_repeated_api_and_fresh_cli_runs_are_pixel_deterministic(self):
        """Compare repeatability only; a baseline is not a semantic oracle."""
        image, truth, specification = majority_fixture()
        specification['ignore_polygons'] = [
            [[0.4, 0.3], [0.6, 0.3], [0.6, 0.7], [0.4, 0.7]]]
        baseline = self.extract(image, specification)
        self.assert_result(baseline, image.size)
        for repeat in range(3):
            with self.subTest(api_repeat=repeat):
                result = self.extract(image, specification)
                self.assert_result(result, image.size)
                self.assertEqual(result['mode'], baseline['mode'])
                self.assertEqual(result['status'], baseline['status'])
                self.assertEqual(result['mask'].tobytes(), baseline['mask'].tobytes())
                self.assertEqual(result['ignore'].tobytes(), baseline['ignore'].tobytes())
        source = self.save_image(image)
        cli_baseline = self.assert_cli_candidate(source, specification, name='repeat_0')
        self.assertEqual(cli_baseline[0].tobytes(), baseline['mask'].tobytes())
        self.assertEqual(cli_baseline[1].tobytes(), baseline['ignore'].tobytes())
        for repeat in range(1, 3):
            with self.subTest(cli_repeat=repeat):
                artifacts = self.assert_cli_candidate(
                    source, specification, name=f'repeat_{repeat}')
                for actual, expected in zip(artifacts, cli_baseline):
                    self.assertEqual(actual.mode, expected.mode)
                    self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_cli_report_is_optional_and_companion_names_follow_output_stem(self):
        image, truth, specification = majority_fixture()
        source = self.save_image(image)
        mask, ignore, overlay = self.assert_cli_candidate(
            source, specification, name='subject.candidate', out_json=False)
        self.assert_known_support(mask, truth)
        self.assertIsNone(ignore.getbbox())

    def test_downscaled_connected_thin_rods_are_retained_beyond_foreground_strokes(self):
        """Unpainted rod spans and their junction are independently known foreground."""
        for rod_width in (1, 2):
            landscape = Image.new('RGB', (2049, 161), (208, 180, 140))
            drawing = ImageDraw.Draw(landscape)
            drawing.rectangle((640, 80, 1087, 144), fill=(35, 70, 145))
            drawing.rectangle((864, 16, 863 + rod_width, 79), fill=(35, 70, 145))
            for orientation in ('landscape', 'portrait'):
                with self.subTest(rod_width=rod_width, orientation=orientation):
                    image = (landscape if orientation == 'landscape' else
                             landscape.transpose(Image.Transpose.TRANSPOSE))

                    def oriented(point):
                        return point if orientation == 'landscape' else tuple(reversed(point))

                    def normalized(point):
                        horizontal, vertical = oriented(point)
                        return (horizontal / (image.width - 1), vertical / (image.height - 1))

                    def oriented_box(box):
                        left, top, right, bottom = box
                        return box if orientation == 'landscape' else (top, left, bottom, right)

                    bbox_start = normalized((608, 8))
                    bbox_end = normalized((1120, 153))
                    specification = subject_spec(
                        image.size, (*bbox_start, *bbox_end),
                        (normalized((864, 32)), normalized((928, 112))), scope='whole-subject')
                    specification['foreground_strokes'] = [
                        stroke(normalized((864, 32)), normalized((864, 40)), radius=0.001),
                        stroke(normalized((928, 112)), radius=0.001),
                    ]
                    self.assertGreater(max(image.size), specification['max_side'])
                    result = self.extract(image, specification)
                    self.assert_result(result, image.size)
                    source = self.save_image(image, name=f'rod_source_{rod_width}_{orientation}')
                    cli_mask, cli_ignore, overlay = self.assert_cli_candidate(
                        source, specification, name=f'rod_{rod_width}_{orientation}')
                    for channel, foreground in (('api', result['mask']), ('cli', cli_mask)):
                        with self.subTest(channel=channel):
                            self.assert_box_value(
                                foreground, oriented_box((864, 16, 864 + rod_width, 80)), 255)
                            self.assert_box_value(
                                foreground, oriented_box((864, 76, 864 + rod_width, 88)), 255)
                            self.assert_box_value(
                                foreground, oriented_box((864, 80, 929, 113)), 255)
                            self.assert_box_value(
                                foreground, oriented_box((912, 104, 944, 120)), 255)
                            self.assert_box_value(
                                foreground, oriented_box((848, 16, 856, 80)), 0)

    def test_internal_bbox_contact_reports_truncation_without_expanding_or_accepting(self):
        image = Image.new('RGB', (257, 129), (208, 180, 140))
        ImageDraw.Draw(image).rectangle((56, 32, 200, 95), fill=(35, 70, 145))
        specification = subject_spec(
            image.size, (64 / 256, 24 / 128, 192 / 256, 104 / 128),
            ((65 / 256, 64 / 128), (128 / 256, 64 / 128)), scope='whole-subject')
        specification['foreground_strokes'] = [
            stroke((65 / 256, 64 / 128), radius=1 / 129),
            stroke((128 / 256, 64 / 128)),
        ]
        result = self.extract(image, specification)
        self.assert_result(result, image.size)
        source = self.save_image(image)
        cli_mask, cli_ignore, overlay = self.assert_cli_candidate(
            source, specification, name='internal_bbox_contact')
        report = json.loads((self.root / 'internal_bbox_contact.json').read_text(encoding='utf-8'))
        outside_bbox = ImageChops.invert(rectangle_truth(image.size, (64, 24, 193, 105)))
        for channel, foreground, metadata, status in (
            ('api', result['mask'], result['metadata'], result['status']),
            ('cli', cli_mask, report['metadata'], report['status']),
        ):
            with self.subTest(channel=channel, check='contact_and_original_bbox'):
                self.assertNotEqual(foreground.getpixel((64, 64)), 0,
                                    'The foreground brush deliberately touches the internal bbox edge')
                self.assertIsNone(ImageChops.multiply(foreground, outside_bbox).getbbox(),
                                  'A truncation warning must not silently expand the requested bbox')
                if 'bbox_pixels' in metadata:
                    self.assertEqual(metadata['bbox_pixels'], [64, 24, 192, 104])
            with self.subTest(channel=channel, check='truncation_warning'):
                warnings = metadata.get('boundary_warnings')
                contact = metadata.get('bbox_contact')
                if isinstance(warnings, dict):
                    warnings = any(warnings.values())
                if isinstance(contact, dict):
                    contact = any(contact.values())
                self.assertTrue(warnings or contact,
                                'An interior bbox contact needs a boundary_warnings/bbox_contact signal')
                self.assertNotIn(str(status).lower(),
                                 ('pass', 'passed', 'accepted', 'approved', 'verified', 'semantic_pass'))
                self.assertNotIn(str(metadata.get('semantic_review', 'unreviewed')).lower(),
                                 ('pass', 'passed', 'accepted', 'approved', 'verified'))

    def test_downscaled_ignore_rgb_changes_do_not_affect_external_mask(self):
        """Output equality tests RGB invariance, never uses a mask as semantic truth."""
        reference = Image.new('RGB', (1536, 192), (208, 180, 140))
        ImageDraw.Draw(reference).rectangle((320, 40, 1215, 151), fill=(35, 70, 145))
        specification = subject_spec(
            reference.size, (288 / 1535, 24 / 191, 1248 / 1535, 168 / 191),
            ((384 / 1535, 96 / 191), (1152 / 1535, 96 / 191)), scope='whole-subject')
        specification['ignore_polygons'] = [
            [[700 / 1535, 64 / 191], [835 / 1535, 64 / 191],
             [835 / 1535, 127 / 191], [700 / 1535, 127 / 191]]]
        declared_ignore = rectangle_truth(reference.size, (700, 64, 836, 128))
        external = ImageChops.invert(declared_ignore)
        self.assertGreater(max(reference.size), specification['max_side'])
        baselines = {}
        for name, color in (
            ('foreground_rgb', (35, 70, 145)),
            ('magenta_rgb', (255, 0, 255)),
            ('black_rgb', (0, 0, 0)),
            ('white_rgb', (255, 255, 255)),
        ):
            image = reference.copy()
            ImageDraw.Draw(image).rectangle((700, 64, 835, 127), fill=color)
            input_difference = ImageChops.difference(image, reference)
            self.assertIsNone(ImageChops.multiply(
                input_difference, external.convert('RGB')).getbbox(),
                'Only RGB inside the independent ignore rectangle may change')
            result = self.extract(image, specification)
            self.assert_result(result, image.size)
            source = self.save_image(image, name='ignore_source_' + name)
            cli_mask, cli_ignore, overlay = self.assert_cli_candidate(
                source, specification, name='ignore_' + name)
            for channel, foreground, excluded in (
                ('api', result['mask'], result['ignore']), ('cli', cli_mask, cli_ignore),
            ):
                with self.subTest(channel=channel, variant=name, check='known_pixels'):
                    self.assert_box_value(foreground, (352, 64, 640, 128), 255)
                    self.assert_box_value(foreground, (896, 64, 1184, 128), 255)
                    self.assert_box_value(foreground, (0, 0, 128, 24), 0)
                    self.assert_box_value(excluded, (704, 68, 832, 124), 255)
                    self.assert_box_value(foreground, (704, 68, 832, 124), 0)
                    self.assert_disjoint(foreground, excluded)
                if channel not in baselines:
                    baselines[channel] = foreground.copy()
                else:
                    with self.subTest(channel=channel, variant=name, check='external_rgb_invariance'):
                        difference = ImageChops.difference(foreground, baselines[channel])
                        self.assertIsNone(ImageChops.multiply(difference, external).getbbox(),
                                          'Ignored RGB leaked into the external mask during downscaling')

    def test_refine_edges_defaults_true_and_rejects_non_boolean_ablation_values(self):
        """Ablation output is not truth; rod pixels come from the independent drawing."""
        image = Image.new('RGB', (1537, 129), (208, 180, 140))
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((320, 64, 1215, 111), fill=(35, 70, 145))
        drawing.rectangle((736, 16, 736, 63), fill=(35, 70, 145))
        specification = subject_spec(
            image.size, (288 / 1536, 8 / 128, 1248 / 1536, 120 / 128),
            ((736 / 1536, 40 / 128), (768 / 1536, 88 / 128)), scope='whole-subject')
        specification['foreground_strokes'] = [
            stroke((736 / 1536, 40 / 128), radius=0.001),
            stroke((768 / 1536, 88 / 128)),
        ]
        self.assertGreater(max(image.size), specification['max_side'])
        self.assertLessEqual(image.width * image.height, 4_000_000)
        source = self.save_image(image)
        api_results = {}
        cli_artifacts = {}
        for name in ('default', 'explicit_true', 'explicit_false'):
            subject = copy.deepcopy(specification)
            if name != 'default':
                subject['refine_edges'] = name == 'explicit_true'
            api_results[name] = self.extract(image, subject)
            self.assert_result(api_results[name], image.size)
            cli_artifacts[name] = self.assert_cli_candidate(
                source, subject, name='refinement_' + name)
        for channel, default_mask, explicit_mask in (
            ('api', api_results['default']['mask'], api_results['explicit_true']['mask']),
            ('cli', cli_artifacts['default'][0], cli_artifacts['explicit_true'][0]),
        ):
            with self.subTest(channel=channel, check='default_is_true'):
                self.assertIsNone(ImageChops.difference(default_mask, explicit_mask).getbbox(),
                                  'Omitting refine_edges must select the explicit True behavior')
            for name, foreground in (('default', default_mask), ('explicit_true', explicit_mask)):
                with self.subTest(channel=channel, mode=name, check='independent_rod_truth'):
                    self.assert_box_value(foreground, (736, 16, 737, 64), 255)
                    self.assert_box_value(foreground, (736, 60, 737, 72), 255)
                    self.assert_box_value(foreground, (752, 76, 792, 100), 255)
        self.assertEqual(api_results['default']['ignore'].tobytes(),
                         api_results['explicit_true']['ignore'].tobytes())
        self.assertEqual(cli_artifacts['default'][1].tobytes(),
                         cli_artifacts['explicit_true'][1].tobytes())
        for index, invalid_value in enumerate((None, 'true', 0, 1, [], {})):
            invalid = copy.deepcopy(specification)
            invalid['refine_edges'] = invalid_value
            with self.subTest(channel='api', refine_edges=repr(invalid_value)):
                with self.assertRaises(ValueError):
                    self.extract(image, invalid)
            with self.subTest(channel='cli', refine_edges=repr(invalid_value)):
                completed, mask_path, report_path = self.run_cli(
                    source, invalid, name=f'invalid_refinement_{index}')
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(mask_path.exists())


if __name__ == '__main__':
    unittest.main()
