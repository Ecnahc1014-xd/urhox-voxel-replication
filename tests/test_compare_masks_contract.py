import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE_ROOT / 'scripts' / 'compare_masks.py'


class CompareMasksContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.make_mask('reference.png')
        self.rendered = self.make_mask('render.png')

    def make_mask(self, name, size=(32, 32), bounds=(8, 8, 15, 15)):
        image = Image.new('L', size, 0)
        if bounds is not None:
            ImageDraw.Draw(image).rectangle(bounds, fill=255)
        path = self.root / name
        image.save(path)
        return path

    def make_ignore(self, name='ignore.png', bounds=(16, 8, 19, 15), size=(32, 32)):
        return self.make_mask(name, size, bounds)

    def sha256(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_json(self, name, document):
        path = self.root / name
        path.write_text(json.dumps(document), encoding='utf-8')
        return path

    def report(self, name, image=None, status='CANDIDATE', review='unreviewed',
               scope='whole-subject', binding='mask_sha256', **fields):
        document = {binding: self.sha256(image or self.reference),
                    'status': status, 'scope': scope, 'semantic_review': review}
        document.update(fields)
        return self.write_json(name, document)

    def run_tool(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *map(str, arguments)],
                              cwd=PACKAGE_ROOT, capture_output=True, text=True,
                              encoding='utf-8', timeout=60,
                              env={**os.environ, 'PYTHONUTF8': '1',
                                   'PYTHONDONTWRITEBYTECODE': '1'})

    def compare(self, *arguments, reference=None, rendered=None, mode='binary-mask', res=32):
        return self.run_tool('--ref', reference or self.reference,
                             '--render', rendered or self.rendered,
                             '--mode', mode, '--res', res, *arguments)

    def reading(self, process, code):
        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
        return json.loads(process.stdout)['results'][0]

    def assert_input_error(self, process, fragment):
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn('ERROR:', process.stderr)
        self.assertIn(fragment, process.stderr)
        self.assertEqual(process.stdout.strip(), '')

    def test_explicit_binary_mask_uses_pixels_not_opaque_alpha(self):
        reading = self.reading(self.compare(), 0)
        self.assertEqual(reading['intersection'], 64)
        self.assertEqual(reading['union'], 64)
        self.assertEqual(reading['iou'], 1.0)
        self.assertFalse(reading['degenerate'])
        self.assertEqual(reading['diagnostic_verdict'], 'pass')
        self.assertEqual(reading['status'], 'PASS')
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])
        self.assertIn('no semantic acceptance', ' '.join(reading['semantic_reasons']))

    def test_nonbinary_gray_and_color_images_fail_without_threshold_fallback(self):
        gray = Image.open(self.reference).copy()
        gray.putpixel((0, 0), 128)
        colored = gray.convert('RGB')
        colored.putpixel((0, 0), (255, 0, 0))
        for name, image in (('gray.png', gray), ('color.png', colored)):
            with self.subTest(name=name):
                path = self.root / name
                image.save(path)
                self.assert_input_error(self.compare(reference=path), 'binary mask')

    def test_high_bit_depth_values_cannot_be_clipped_into_binary(self):
        image = Image.new('I', (32, 32), 0)
        image.putpixel((8, 8), 256)
        path = self.root / 'high-depth.tif'
        image.save(path)
        self.assert_input_error(self.compare(reference=path), '8-bit')

    def test_binary_mode_refuses_transparency_instead_of_discarding_unknown_alpha(self):
        image = Image.open(self.reference).convert('RGBA')
        image.putpixel((0, 0), (0, 0, 0, 0))
        path = self.root / 'transparent.png'
        image.save(path)
        self.assert_input_error(self.compare(reference=path), 'opaque')

    def test_binary_mode_requires_matching_input_sizes(self):
        smaller = self.make_mask('smaller.png', (16, 16), (4, 4, 7, 7))
        self.assert_input_error(self.compare(rendered=smaller), 'size mismatch')

    def test_ignore_requires_binary_values_and_native_input_size(self):
        wrong_size = self.make_ignore('wrong-size.png', size=(16, 32))
        invalid = self.root / 'invalid-ignore.png'
        Image.new('L', (32, 32), 127).save(invalid)
        for option in ('--ref-ignore', '--render-ignore'):
            with self.subTest(option=option):
                self.assert_input_error(self.compare(option, wrong_size), 'ignore size')
                self.assert_input_error(self.compare(option, invalid), 'binary mask')

    def test_candidate_cannot_be_promoted_by_permissive_cli_thresholds(self):
        reference_report = self.report('ref.json', review='reviewed')
        render_report = self.report('render.json', self.rendered, review='reviewed')
        process = self.compare('--ref-report', reference_report, '--render-report', render_report,
                               '--iou-target', 0, '--center-drift-pct', 10000,
                               '--size-drift-pct-front', 10000, '--luma-thr', 0, '--alpha-thr', 0)
        reading = self.reading(process, 3)
        self.assertEqual(reading['diagnostic_verdict'], 'pass')
        self.assertEqual(reading['status'], 'UNVERIFIED')
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])
        self.assertEqual(json.loads(process.stdout)['summary']['verdict'], 'unverified')

    def test_verified_status_without_semantic_review_is_unverified(self):
        reference_report = self.report('ref.json', status='VERIFIED')
        render_report = self.report('render.json', self.rendered, status='VERIFIED', review='verified')
        reading = self.reading(self.compare('--ref-report', reference_report,
                                            '--render-report', render_report), 3)
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertEqual(reading['diagnostic_verdict'], 'pass')
        self.assertIn('unreviewed', ' '.join(reading['semantic_reasons']))

    def test_missing_review_or_scope_or_second_report_never_accepts(self):
        verified_render = self.report('render.json', self.rendered,
                                      status='VERIFIED', review='verified')
        document = {'mask_sha256': self.sha256(self.reference), 'status': 'VERIFIED',
                    'scope': 'whole-subject', 'semantic_review': 'verified'}
        for field in ('scope', 'semantic_review'):
            with self.subTest(field=field):
                incomplete = dict(document)
                incomplete.pop(field)
                report = self.write_json('incomplete.json', incomplete)
                reading = self.reading(self.compare('--ref-report', report,
                                                    '--render-report', verified_render), 3)
                self.assertEqual(reading['verdict'], 'unverified')
        report = self.write_json('complete.json', document)
        reading = self.reading(self.compare('--ref-report', report), 3)
        self.assertFalse(reading['semantic_acceptance'])

    def test_scope_mismatch_does_not_promote_local_part_to_whole_subject(self):
        reference_report = self.report('ref.json', status='VERIFIED', review='verified', scope='local-part')
        render_report = self.report('render.json', self.rendered, status='VERIFIED', review='verified')
        reading = self.reading(self.compare('--ref-report', reference_report,
                                            '--render-report', render_report), 3)
        self.assertIn('scope mismatch', ' '.join(reading['semantic_reasons']))
        self.assertEqual(reading['metadata']['ref']['scope'], 'local-part')
        self.assertEqual(reading['verdict'], 'unverified')

    def test_verified_matching_scope_positive_control_is_mask_pair_local(self):
        reference_report = self.report('ref.json', status='VERIFIED', review='verified', scope='local-part')
        render_report = self.report('render.json', self.rendered,
                                    status='VERIFIED', review='verified', scope='local-part')
        reading = self.reading(self.compare('--ref-report', reference_report,
                                            '--render-report', render_report), 0)
        self.assertEqual(reading['verdict'], 'pass')
        self.assertTrue(reading['semantic_acceptance'])
        self.assertIn('view-local', reading['scope'])
        self.assertIsNone(reading['unaligned'])

    def test_unknown_scope_is_not_semantic_acceptance_even_with_reviewed_status(self):
        reference_report = self.report('ref.json', status='VERIFIED', review='verified', scope='unknown')
        render_report = self.report('render.json', self.rendered,
                                    status='VERIFIED', review='verified', scope='unknown')
        reading = self.reading(self.compare('--ref-report', reference_report,
                                            '--render-report', render_report), 3)
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])
        self.assertIn('scope missing or unsupported', ' '.join(reading['semantic_reasons']))

    def test_hash_binding_rejects_tampered_mask_and_source_hashes(self):
        for binding in ('mask_sha256', 'source_sha256'):
            with self.subTest(binding=binding):
                report = self.report('wrong.json', binding=binding, **{binding: '0' * 64})
                self.assert_input_error(self.compare('--ref-report', report), 'mismatch')

    def test_input_changed_after_report_binding_is_visible_error(self):
        report = self.report('ref.json')
        changed = Image.open(self.reference).copy()
        changed.putpixel((0, 0), 255)
        changed.save(self.reference)
        self.assert_input_error(self.compare('--ref-report', report), 'mask_sha256 mismatch')

    def test_report_missing_binding_or_conflicting_metadata_is_not_silently_usable(self):
        unbound = self.write_json('unbound.json', {'status': 'VERIFIED', 'scope': 'whole-subject',
                                                 'semantic_review': 'verified'})
        self.assert_input_error(self.compare('--ref-report', unbound), 'requires source_sha256 or mask_sha256')
        conflicting = self.report('conflict.json', metadata={'status': 'VERIFIED'})
        self.assert_input_error(self.compare('--ref-report', conflicting), 'conflicting report field')

    def test_report_image_size_mismatch_is_input_error(self):
        report = self.report('ref.json', metadata={'image_size': [16, 16]})
        self.assert_input_error(self.compare('--ref-report', report), 'image_size mismatch')


    def test_ignored_mismatch_cannot_be_promoted_to_a_passing_full_domain_score(self):
        extended = self.make_mask('extended.png', bounds=(8, 8, 19, 15))
        ignored = self.make_ignore()
        overlay = self.root / 'overlay.png'
        reading = self.reading(self.compare('--ref-ignore', ignored, '--iou-target', 1,
                                            '--out-overlay', overlay, rendered=extended), 3)
        self.assertEqual(reading['intersection'], 64)
        self.assertEqual(reading['union'], 64)
        self.assertEqual(reading['iou'], 1.0)
        self.assertEqual(reading['original_intersection'], 64)
        self.assertEqual(reading['original_union'], 96)
        self.assertAlmostEqual(reading['original_domain_diagnostic_iou'], 2 / 3)
        self.assertEqual(reading['original_denominator_pixels'], 1024)
        self.assertEqual(reading['valid_pixels'], 992)
        self.assertEqual(reading['ignored_pixels'], 32)
        self.assertAlmostEqual(reading['valid_domain_fraction'], 992 / 1024)
        self.assertAlmostEqual(reading['fg_ratio_ref'], 64 / 992)
        self.assertAlmostEqual(reading['fg_ratio_ref_original_denominator'], 64 / 1024)
        self.assertEqual(reading['diagnostic_verdict'], 'warn')
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])
        with Image.open(overlay) as image:
            self.assertEqual(image.getpixel((16, 8)), (255, 168, 0))
            self.assertEqual(image.getpixel((8, 8)), (255, 255, 255))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))

    def test_common_valid_domain_excludes_either_sides_unknown_pixels(self):
        reference_ignore = self.make_ignore('ref-ignore.png', (0, 0, 3, 3))
        render_ignore = self.make_ignore('render-ignore.png', (28, 28, 31, 31))
        reading = self.reading(self.compare('--ref-ignore', reference_ignore,
                                            '--render-ignore', render_ignore), 3)
        self.assertEqual(reading['valid_pixels'], 992)
        self.assertEqual(reading['ignored_pixels'], 32)
        self.assertEqual(reading['ignore']['ref_pixels_original'], 16)
        self.assertEqual(reading['ignore']['render_pixels_original'], 16)
        self.assertEqual(reading['iou'], 1.0)
        self.assertFalse(reading['semantic_acceptance'])

    def test_reviewed_metadata_cannot_accept_a_shrunken_ignore_domain(self):
        reference_report = self.report('ref.json', status='VERIFIED', review='verified')
        render_report = self.report('render.json', self.rendered, status='VERIFIED', review='verified')
        ignored = self.make_ignore()
        reading = self.reading(self.compare('--ref-report', reference_report,
                                            '--render-report', render_report,
                                            '--render-ignore', ignored, '--iou-target', 0), 3)
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])
        self.assertIn('shrinking', ' '.join(reading['semantic_reasons']))

    def test_empty_common_valid_domain_is_unknown_not_matching_background(self):
        ignored = self.root / 'all-unknown.png'
        Image.new('L', (32, 32), 255).save(ignored)
        reading = self.reading(self.compare('--ref-ignore', ignored), 3)
        self.assertTrue(reading['empty_common_domain'])
        self.assertEqual(reading['valid_pixels'], 0)
        self.assertEqual(reading['valid_domain_fraction'], 0.0)
        self.assertEqual(reading['original_denominator_pixels'], 1024)
        self.assertIsNone(reading['iou'])
        self.assertIsNone(reading['fg_ratio_ref'])
        self.assertIsNone(reading['bbox'])
        self.assertEqual(reading['intersection'], 0)
        self.assertEqual(reading['union'], 0)
        self.assertEqual(reading['verdict'], 'unverified')

    def test_whole_domain_empty_and_full_binary_masks_are_degenerate(self):
        for value in (0, 255):
            with self.subTest(value=value):
                mask = self.root / 'degenerate.png'
                Image.new('L', (32, 32), value).save(mask)
                reading = self.reading(self.compare(reference=mask, rendered=mask), 3)
                self.assertTrue(reading['full_domain_degenerate'])
                self.assertTrue(reading['degenerate'])
                self.assertIsNone(reading['iou'])
                self.assertEqual(reading['verdict'], 'unverified')

    def test_domain_only_empty_and_full_masks_are_degenerate(self):
        for hide_foreground in (False, True):
            with self.subTest(hide_foreground=hide_foreground):
                ignored = self.root / 'domain-ignore.png'
                image = Image.new('L', (32, 32), 0 if hide_foreground else 255)
                ImageDraw.Draw(image).rectangle((8, 8, 15, 15), fill=255 if hide_foreground else 0)
                image.save(ignored)
                reading = self.reading(self.compare('--ref-ignore', ignored), 3)
                self.assertFalse(reading['full_domain_degenerate'])
                self.assertTrue(reading['valid_domain_degenerate'])
                self.assertFalse(reading['empty_common_domain'])
                self.assertIsNone(reading['iou'])
                self.assertIsNone(reading['bbox'])
                if not hide_foreground:
                    self.assertEqual(reading['raw_iou'], 1.0)

    def test_thin_ignore_survives_analysis_downsampling(self):
        reference = self.make_mask('large-ref.png', (64, 64), (16, 16, 47, 47))
        rendered = self.make_mask('large-render.png', (64, 64), (16, 16, 47, 47))
        ignored = self.make_ignore('thin-ignore.png', (1, 1, 1, 1), (64, 64))
        reading = self.reading(self.compare('--ref-ignore', ignored,
                                            reference=reference, rendered=rendered, res=8), 3)
        self.assertEqual(reading['ignore']['ref_pixels_original'], 1)
        self.assertGreater(reading['ignored_pixels'], 0)
        self.assertLess(reading['valid_domain_fraction'], 1)
        self.assertEqual(reading['input_denominator_pixels']['ref'], 4096)
        self.assertEqual(reading['original_denominator_pixels'], 64)

    def test_subject_report_auto_propagates_bound_ignore_and_blocks_smaller_override(self):
        ignored = self.make_ignore()
        report = self.write_json('subject-report.json', {
            'schema': 'reference-subject-mask/1', 'status': 'CANDIDATE',
            'source_sha256': '1' * 64,
            'metadata': {'scope': 'local-part', 'semantic_review': 'unreviewed',
                         'image_size': [32, 32], 'ignored_pixels': 32},
            'artifacts': {'mask': str(self.reference), 'mask_sha256': self.sha256(self.reference),
                          'ignore': ignored.name, 'ignore_sha256': self.sha256(ignored)}})
        reading = self.reading(self.compare('--ref-report', report), 3)
        self.assertEqual(reading['metadata']['ref']['binding'], 'mask_sha256')
        self.assertEqual(reading['metadata']['ref']['scope'], 'local-part')
        self.assertEqual(reading['ignored_pixels'], 32)
        self.assertEqual(Path(reading['ignore']['ref']), ignored)
        smaller = self.make_ignore('smaller-ignore.png', bounds=None)
        self.assert_input_error(self.compare('--ref-report', report, '--ref-ignore', smaller),
                                'cannot shrink unknown domain')

    def test_report_declared_unknown_count_cannot_be_dropped(self):
        report = self.report('ref.json', metadata={'ignored_pixels': 32})
        self.assert_input_error(self.compare('--ref-report', report), 'ignored_pixels mismatch')

    def test_ignore_hash_tampering_is_visible_even_if_mask_hash_matches(self):
        ignored = self.make_ignore()
        report = self.report('ref.json', artifacts={'ignore': str(ignored),
                                                  'ignore_sha256': self.sha256(ignored)})
        changed = Image.open(ignored).copy()
        changed.putpixel((0, 0), 255)
        changed.save(ignored)
        self.assert_input_error(self.compare('--ref-report', report), 'ignore_sha256 mismatch')

    def test_aspect_mismatch_remains_unverified_under_loose_thresholds(self):
        wide = self.make_mask('wide.png', (64, 32), (16, 8, 31, 15))
        reading = self.reading(self.compare('--iou-target', 0, '--center-drift-pct', 10000,
                                            '--size-drift-pct-front', 10000,
                                            rendered=wide, mode='luma-fixed'), 3)
        self.assertTrue(reading['unaligned'])
        self.assertEqual(reading['status'], 'PASS-WATCH')
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertFalse(reading['semantic_acceptance'])

    def test_real_alpha_control_retains_legacy_diagnostic_behavior(self):
        path = self.root / 'alpha.png'
        image = Image.new('RGBA', (32, 32), (10, 50, 100, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 15, 15), fill=(10, 50, 100, 255))
        image.save(path)
        reading = self.reading(self.compare(reference=path, rendered=path, mode='alpha'), 0)
        self.assertEqual(reading['intersection'], 64)
        self.assertEqual(reading['iou'], 1.0)
        self.assertEqual(reading['status'], 'PASS')
        self.assertEqual(reading['verdict'], 'unverified')
        report = self.report('source.json', path, binding='source_sha256')
        reading = self.reading(self.compare('--ref-report', report,
                                            reference=path, rendered=path, mode='alpha'), 3)
        self.assertEqual(reading['metadata']['ref']['binding'], 'source_sha256')
        self.assertFalse(reading['semantic_acceptance'])

    def test_opaque_alpha_false_match_stays_degenerate(self):
        reading = self.reading(self.compare(mode='alpha'), 3)
        self.assertTrue(reading['degenerate'])
        self.assertIsNone(reading['iou'])
        self.assertEqual(reading['raw_iou'], 1.0)
        self.assertEqual(reading['verdict'], 'unverified')

    def test_pairs_accepts_binary_ignore_and_inline_or_file_reports(self):
        ignored = self.make_ignore()
        reference_report = {'mask_sha256': self.sha256(self.reference), 'status': 'CANDIDATE',
                            'scope': 'whole-subject', 'semantic_review': 'unreviewed'}
        render_report = self.report('render.json', self.rendered)
        pairs = self.write_json('pairs.json', {'analysis_res': 32, 'pairs': [{
            'name': 'contract-pair', 'ref': str(self.reference), 'render': str(self.rendered),
            'mode': 'binary-mask', 'ref_ignore': str(ignored),
            'ref_report': reference_report, 'render_report': str(render_report), 'iou_target': 0}]})
        process = self.run_tool('--pairs', pairs, '--center-drift-pct', 10000)
        reading = self.reading(process, 3)
        self.assertEqual(reading['name'], 'contract-pair')
        self.assertEqual(reading['mask_modes'], {'ref': 'binary-mask', 'render': 'binary-mask'})
        self.assertEqual(reading['ignored_pixels'], 32)
        self.assertEqual(reading['verdict'], 'unverified')
        self.assertEqual(json.loads(process.stdout)['summary']['unverified_views'], ['contract-pair'])

    def test_pairs_bad_hash_is_error_not_a_partial_green_report(self):
        pairs = self.write_json('pairs.json', {'pairs': [{
            'ref': str(self.reference), 'render': str(self.rendered), 'mode': 'binary-mask',
            'ref_report': {'mask_sha256': '0' * 64, 'status': 'CANDIDATE',
                           'scope': 'whole-subject', 'semantic_review': 'unreviewed'}}]})
        self.assert_input_error(self.run_tool('--pairs', pairs), 'mask_sha256 mismatch')

    def test_api_preserves_old_positional_calls_and_appends_new_optional_arguments(self):
        specification = importlib.util.spec_from_file_location('compare_masks_contract_api', SCRIPT)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        legacy = module.compare_pair(self.reference, self.rendered, 'luma-fixed', 'luma-fixed',
                                     'front', 32, module.DEFAULT_GATES)
        self.assertEqual(legacy['status'], 'PASS')
        self.assertEqual(legacy['diagnostic_verdict'], 'pass')
        self.assertEqual(legacy['verdict'], 'unverified')
        self.assertEqual(legacy['ref'], self.reference)
        self.assertEqual(legacy['render'], self.rendered)
        ignored = self.make_ignore()
        metadata = {'mask_sha256': self.sha256(self.reference), 'status': 'CANDIDATE',
                    'scope': 'whole-subject', 'semantic_review': 'unreviewed'}
        reading = module.compare_pair(self.reference, self.rendered, 'binary-mask', 'binary-mask',
                                      'front', 32, module.DEFAULT_GATES,
                                      ref_ignore=ignored, ref_report=metadata)
        self.assertEqual(reading['ignored_pixels'], 32)
        self.assertEqual(reading['verdict'], 'unverified')
        positional = module.compare_pair(self.reference, self.rendered, 'binary-mask', 'binary-mask',
                                         'front', 32, module.DEFAULT_GATES, None, 128, 8, None,
                                         None, ignored, None, metadata)
        self.assertEqual(positional['ignored_pixels'], 32)
        self.assertFalse(positional['semantic_acceptance'])
        self.assertEqual(module.mask_stats(Image.open(self.reference).copy(), 32)['fg'], 64)
        older = dict(legacy)
        for field in ('verdict', 'semantic_acceptance'):
            older.pop(field)
        self.assertEqual(module.summarize([older])['verdict'], 'unverified')


if __name__ == '__main__':
    unittest.main()
