"""Synthetic, independent prompt-risk checks; passing is not semantic acceptance."""

import builtins
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

from PIL import Image, ImageDraw


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "reference_prompt_diagnostics.py"


def rectangle_truth(size, *rectangles):
    truth = Image.new("L", size, 0)
    drawing = ImageDraw.Draw(truth)
    for left, top, right, bottom in rectangles:
        drawing.rectangle((left, top, right - 1, bottom - 1), fill=255)
    return truth


def pixel_stroke(size, *points, radius_pixels=1):
    return {
        "points": [[horizontal / (size[0] - 1), vertical / (size[1] - 1)]
                   for horizontal, vertical in points],
        "radius": radius_pixels / min(size),
    }


def subject_spec(size, foreground=None, background=None, max_side=1280):
    return {
        "target": "independently drawn synthetic subject",
        "scope": "whole-subject", "coordinate_space": "normalized_xy",
        "image_size": list(size), "bbox": [0, 0, 1, 1],
        "foreground_strokes": foreground if foreground is not None else [pixel_stroke(size, (24, 24))],
        "background_strokes": background if background is not None else [pixel_stroke(size, (4, 4))],
        "ignore_polygons": [], "iterations": 5, "max_side": max_side,
    }


def gray_fixture():
    size = (65, 49)
    image = Image.new("RGB", size, (120, 120, 120))
    mask = rectangle_truth(size, (16, 12, 40, 36))
    return image, subject_spec(size), mask, Image.new("L", size, 0)


def snapshot(image):
    return image.mode, image.size, image.tobytes(), copy.deepcopy(image.info), image.getpalette()


class ReferencePromptDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        specification = importlib.util.spec_from_file_location("reference_prompt_diagnostics_regression", SCRIPT_PATH)
        cls.module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(cls.module)

    def assert_inputs_unchanged(self, image, subject, mask, ignore):
        before = snapshot(image), copy.deepcopy(subject), snapshot(mask) if mask is not None else None, snapshot(ignore)
        report = self.module.analyze_prompt(image, subject, mask, ignore)
        after = snapshot(image), copy.deepcopy(subject), snapshot(mask) if mask is not None else None, snapshot(ignore)
        self.assertEqual(after, before, "Diagnostics changed source pixels, hints, mask, ignore, or image metadata")
        json.dumps(report, allow_nan=False)
        return report

    def run_without_numerical_imports(self, image, subject, mask, ignore):
        original_import = builtins.__import__
        attempted = []

        def guarded_import(name, *arguments, **keywords):
            if name.split(".")[0] in {"numpy", "cv2"}:
                attempted.append(name)
                raise AssertionError("Skipped path attempted numerical import: " + name)
            return original_import(name, *arguments, **keywords)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertEqual(attempted, [])
        return report

    def test_all_four_inputs_and_image_metadata_remain_unchanged(self):
        image, subject, mask, ignore = gray_fixture()
        image.info["fixture"] = {"unchanged": [1, 2]}
        mask.info["independent_truth"] = True
        ignore.paste(255, (38, 12, 45, 36))
        subject["ignore_polygons"] = [[[38 / 64, 12 / 48], [44 / 64, 12 / 48],
                                        [44 / 64, 35 / 48], [38 / 64, 35 / 48]]]
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["semantic_verdict"], "not_evaluated")

    def test_reports_are_json_safe_and_repeatable_without_accuracy_fields(self):
        arguments = gray_fixture()
        first = self.assert_inputs_unchanged(*arguments)
        second = self.assert_inputs_unchanged(*arguments)
        self.assertEqual(json.dumps(first, allow_nan=False, sort_keys=True),
                         json.dumps(second, allow_nan=False, sort_keys=True))
        forbidden = {"score", "accuracy", "precision", "semantic_iou",
                     "is_correct", "hole_count", "background_truth"}

        def inspect_keys(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for nested in value.values():
                    inspect_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    inspect_keys(nested)

        inspect_keys(first)

    def test_gray_body_matching_background_is_ambiguity_not_background_truth(self):
        report = self.assert_inputs_unchanged(*gray_fixture())
        foreground = report["strokes"][0]
        self.assertEqual(foreground["centerline_color"]["mean_rgb"], [120.0] * 3)
        self.assertEqual(foreground["brush_color"]["rgb_rms_spread"], 0.0)
        self.assertEqual(report["cross_label_pairs"][0]["centerline_mean_rgb_mse"], 0.0)
        self.assertTrue(report["cross_label_pairs"][0]["color_ambiguity"])
        self.assertIn("does_not_identify_background", report["cross_label_pairs"][0]["interpretation"])
        self.assertEqual(report["semantic_verdict"], "not_evaluated")

    def test_foreground_centerline_crossing_colors_has_a_reproducible_source_crop(self):
        image, subject, mask, ignore = gray_fixture()
        image.paste((20, 30, 40), (0, 0, 32, 49))
        image.paste((200, 210, 220), (32, 0, 65, 49))
        subject["foreground_strokes"] = [pixel_stroke(image.size, (16, 24), (48, 24), radius_pixels=3)]
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        stroke = report["strokes"][0]
        self.assertEqual(stroke["points_pixels"], [[16, 24], [48, 24]])
        self.assertEqual(stroke["centerline_color"]["sample_pixels"], 33)
        self.assertEqual(stroke["centerline_color"]["channel_range_rgb"], [180] * 3)
        self.assertAlmostEqual(stroke["centerline_color"]["mean_rgb"][0], (16 * 20 + 17 * 200) / 33)
        self.assertIn("centerline_color_mixture", stroke["risk_flags"])
        crops = [region for region in report["review_regions"] if region["kind"] == "stroke_color_mixture"]
        self.assertTrue(crops)
        left, top, right, bottom = crops[0]["bbox_pixels"]
        self.assertTrue(left <= 20 < right and top <= 24 < bottom)
        self.assertLessEqual(right, 32)
        self.assertEqual(report["bbox_convention"], "half_open_xyxy")

    def test_wide_brush_can_mix_background_while_centerline_stays_uniform(self):
        size = (65, 49)
        image = Image.new("RGB", size, (220, 220, 220))
        image.paste((20, 50, 180), (32, 8, 33, 41))
        mask = rectangle_truth(size, (32, 8, 33, 41))
        subject = subject_spec(size, [pixel_stroke(size, (32, 12), (32, 36), radius_pixels=4)])
        report = self.assert_inputs_unchanged(image, subject, mask, Image.new("L", size, 0))
        stroke = report["strokes"][0]
        self.assertEqual(stroke["centerline_color"]["mean_rgb"], [20.0, 50.0, 180.0])
        self.assertEqual(stroke["centerline_color"]["rgb_rms_spread"], 0.0)
        self.assertGreater(stroke["brush_color"]["rgb_rms_spread"], 12)
        self.assertIn("brush_differs_from_centerline_color_band", stroke["risk_flags"])
        self.assertGreater(stroke["brush_outside_centerline_color_band_pixels"], 0)
        self.assertNotIn("centerline_color_mixture", stroke["risk_flags"])

    def test_background_strokes_receive_the_same_color_mixture_diagnostics(self):
        image, subject, mask, ignore = gray_fixture()
        image.paste((20, 20, 20), (0, 0, 32, 49))
        image.paste((230, 230, 230), (32, 0, 65, 49))
        subject["background_strokes"] = [pixel_stroke(image.size, (16, 4), (48, 4), radius_pixels=2)]
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        background = next(stroke for stroke in report["strokes"] if stroke["kind"] == "background")
        self.assertEqual(background["centerline_color"]["channel_range_rgb"], [210] * 3)
        self.assertIn("centerline_color_mixture", background["risk_flags"])
        self.assertTrue(any(region["stroke_ids"] == ["background:0"]
                            for region in report["review_regions"] if region["kind"] == "stroke_color_mixture"))

    def test_opposite_wide_brush_overlap_is_reported_without_changing_hints(self):
        image, subject, mask, ignore = gray_fixture()
        subject["foreground_strokes"] = [pixel_stroke(image.size, (26, 24), radius_pixels=3)]
        subject["background_strokes"] = [pixel_stroke(image.size, (30, 24), radius_pixels=3)]
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        pair = report["cross_label_pairs"][0]
        self.assertEqual(pair["source_centerline_overlap_pixels"], 0)
        self.assertGreater(pair["source_brush_overlap_pixels"], 0)
        left, top, right, bottom = pair["source_overlap_bbox_pixels"]
        self.assertTrue(left <= 28 < right and top <= 24 < bottom)
        for stroke in report["strokes"]:
            self.assertIn("opposite_label_brush_overlap", stroke["risk_flags"])

    def test_source_disjoint_seeds_can_overlap_at_working_resolution(self):
        size = (4097, 65)
        image = Image.new("RGB", size, (120, 120, 120))
        mask = rectangle_truth(size, (1990, 20, 2002, 45))
        subject = subject_spec(size, [pixel_stroke(size, (2000, 32))],
                               [pixel_stroke(size, (2004, 32))], max_side=128)
        report = self.assert_inputs_unchanged(image, subject, mask, Image.new("L", size, 0))
        pair = report["cross_label_pairs"][0]
        self.assertEqual(pair["source_brush_overlap_pixels"], 0)
        self.assertGreater(pair["working_brush_overlap_pixels"], 0)
        self.assertEqual(report["working_size"], [128, 2])
        crops = [region for region in report["review_regions"] if region["kind"] == "opposite_seed_overlap"]
        self.assertEqual(crops[0]["bbox_pixels"], [1999, 31, 2006, 34])

    def test_ignore_boundary_adjacency_is_unknown_and_has_a_local_review_box(self):
        image, subject, mask, unused_ignore = gray_fixture()
        ignore = rectangle_truth(image.size, (40, 12, 45, 36))
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        contact = report["ignore_boundary"]
        self.assertEqual(contact["semantics"], "unknown_not_background")
        self.assertEqual(contact["mask_overlap_pixels"], 0)
        self.assertEqual(contact["adjacent_candidate_boundary_pixels"], 24)
        self.assertEqual(contact["contact_regions"][0]["bbox_pixels"], [39, 12, 40, 36])
        crops = [region for region in report["review_regions"] if region["kind"] == "ignore_boundary_contact"]
        self.assertEqual(crops[0]["bbox_pixels"], [38, 11, 41, 37])
        self.assertIn("not_observed_hole_truth", contact["interpretation"])

    def test_ignore_overlap_is_reported_but_not_erased_or_relabelled(self):
        image, subject, mask, unused_ignore = gray_fixture()
        ignore = rectangle_truth(image.size, (28, 18, 33, 30))
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertEqual(report["ignore_boundary"]["mask_overlap_pixels"], 60)
        self.assertEqual(mask.getpixel((30, 24)), 255)
        self.assertEqual(ignore.getpixel((30, 24)), 255)
        self.assertEqual(report["ignore_semantics"], "unknown_not_background")

    def test_unknown_rgb_cannot_contaminate_stroke_color_diagnostics(self):
        image, subject, mask, unused_ignore = gray_fixture()
        subject["foreground_strokes"] = [pixel_stroke(image.size, (37, 24), radius_pixels=4)]
        ignore = rectangle_truth(image.size, (40, 12, 46, 36))
        first_image, second_image = image.copy(), image.copy()
        first_image.paste((0, 0, 0), (40, 12, 46, 36))
        second_image.paste((255, 0, 255), (40, 12, 46, 36))
        first = self.assert_inputs_unchanged(first_image, subject, mask, ignore)
        second = self.assert_inputs_unchanged(second_image, subject, mask, ignore)
        self.assertEqual(first, second)
        self.assertGreater(first["strokes"][0]["ignore_brush_pixels"], 0)
        self.assertEqual(first["strokes"][0]["brush_color"]["mean_rgb"], [120.0] * 3)

    def test_diagonal_candidate_paths_use_eight_connectivity_not_instance_truth(self):
        size = (65, 49)
        image = Image.new("RGB", size, (120, 120, 120))
        mask = rectangle_truth(size, (8, 8, 16, 16), (20, 20, 28, 28))
        drawing = ImageDraw.Draw(mask)
        for diagonal in range(16, 20):
            drawing.point((diagonal, diagonal), fill=255)
        subject = subject_spec(size, [pixel_stroke(size, (11, 11)), pixel_stroke(size, (24, 24))])
        report = self.assert_inputs_unchanged(image, subject, mask, Image.new("L", size, 0))
        pair = report["foreground_connectivity"][0]
        self.assertTrue(pair["candidate_connected"])
        self.assertEqual(report["candidate_component_count"], 1)
        self.assertEqual(pair["instance_identity"], "not_inferred")
        self.assertGreater(pair["centerline_bbox_gap_pixels"], 0)

    def test_disconnected_foreground_seeds_report_separate_candidate_support(self):
        size = (65, 49)
        image = Image.new("RGB", size, (120, 120, 120))
        mask = rectangle_truth(size, (8, 8, 16, 16), (40, 20, 48, 28))
        subject = subject_spec(size, [pixel_stroke(size, (11, 11)), pixel_stroke(size, (44, 24))])
        report = self.assert_inputs_unchanged(image, subject, mask, Image.new("L", size, 0))
        self.assertFalse(report["foreground_connectivity"][0]["candidate_connected"])
        self.assertEqual(report["candidate_component_count"], 2)
        self.assertEqual(report["foreground_connectivity"][0]["instance_identity"], "not_inferred")

    def test_ignore_can_hide_a_connection_and_fully_ignore_a_foreground_centerline(self):
        image, subject, unused_mask, unused_ignore = gray_fixture()
        mask = rectangle_truth(image.size, (8, 12, 56, 36))
        ignore = rectangle_truth(image.size, (31, 0, 34, 49))
        subject["foreground_strokes"] = [pixel_stroke(image.size, (24, 24)), pixel_stroke(image.size, (44, 24))]
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertFalse(report["foreground_connectivity"][0]["candidate_connected"])
        self.assertIn("unknown_regions_can_hide_connections", report["foreground_connectivity"][0]["interpretation"])
        subject["foreground_strokes"][1] = pixel_stroke(image.size, (32, 24))
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertIsNone(report["foreground_connectivity"][0]["candidate_connected"])
        self.assertIsNone(report["strokes"][1]["centerline_color"]["mean_rgb"])
        self.assertIn("stroke_touches_unknown_ignore", report["strokes"][1]["risk_flags"])

    def test_source_image_edge_contacts_do_not_expand_frame_or_prove_truncation(self):
        image, unused_subject, unused_mask, ignore = gray_fixture()
        mask = rectangle_truth(image.size, (0, 0, 12, 49))
        subject = subject_spec(image.size, [pixel_stroke(image.size, (6, 24))], [pixel_stroke(image.size, (60, 24))])
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        edges = report["image_edge_contact"]
        self.assertEqual(edges["left"]["candidate_pixels"], 49)
        self.assertEqual(edges["top"]["candidate_pixels"], 12)
        self.assertEqual(edges["bottom"]["candidate_pixels"], 12)
        self.assertEqual(edges["right"]["candidate_pixels"], 0)
        self.assertEqual(edges["left"]["bbox_pixels"], [0, 0, 1, 49])
        self.assertIn("not_proof_of_truncation", edges["left"]["interpretation"])

    def test_one_and_two_pixel_source_rods_report_sampling_support_without_scoring(self):
        size = (257, 129)
        for rod_width in (1, 2):
            with self.subTest(rod_width=rod_width):
                image = Image.new("RGB", size, (200, 200, 200))
                mask = rectangle_truth(size, (128, 12, 128 + rod_width, 64), (120, 64, 140, 110))
                image.paste((20, 50, 180), (128, 12, 128 + rod_width, 64))
                image.paste((20, 50, 180), (120, 64, 140, 110))
                subject = subject_spec(size, [pixel_stroke(size, (128, 20), (128, 40)),
                                             pixel_stroke(size, (128, 88))], max_side=128)
                report = self.assert_inputs_unchanged(image, subject, mask, Image.new("L", size, 0))
                support = report["thin_source_support"]
                self.assertEqual(len(support["regions"]), 1)
                region = support["regions"][0]
                self.assertEqual(region["bbox_pixels"], [128, 12, 128 + rod_width, 64])
                self.assertEqual(region["pixels"], rod_width * 52)
                self.assertEqual(region["minimum_axis_run_source_pixels"], rod_width)
                self.assertAlmostEqual(region["projected_minimum_axis_run_working_pixels"], rod_width * 128 / 257)
                self.assertTrue(region["subpixel_after_downsampling"])
                self.assertEqual(region["foreground_centerline_pixels"], 21)
                self.assertFalse(region["ignore_censored"])
                self.assertIn("not_accuracy_or_physical_thickness", support["interpretation"])

    def test_a_wide_known_rectangle_does_not_create_thin_source_regions(self):
        image, subject, mask, ignore = gray_fixture()
        report = self.assert_inputs_unchanged(image, subject, mask, ignore)
        self.assertEqual(report["thin_source_support"]["regions"], [])

    def test_source_alpha_and_palette_transparency_skip_numerical_dependencies(self):
        image, subject, mask, ignore = gray_fixture()
        rgba = image.convert("RGBA")
        rgba.putalpha(mask)
        luminance_alpha = image.convert("LA")
        luminance_alpha.putalpha(mask)
        palette = Image.new("P", image.size, 0)
        palette.putpalette([120, 120, 120] * 256)
        ImageDraw.Draw(palette).rectangle((16, 12, 39, 35), fill=1)
        palette.info["transparency"] = 0
        palette_table = palette.copy()
        palette_table.info["transparency"] = bytes([0, 128] + [255] * 254)
        empty = Image.new("RGBA", image.size, (120, 120, 120, 0))
        for name, source, candidate in (("rgba", rgba, mask), ("la", luminance_alpha, mask),
                                        ("palette", palette, mask), ("palette_table", palette_table, mask),
                                        ("empty", empty, None)):
            with self.subTest(source=name):
                report = self.run_without_numerical_imports(source, subject, candidate, ignore)
                self.assertEqual(report["mode"], "source_alpha")
                self.assertEqual(report["status"], "not_applicable")
                self.assertEqual(report["review_regions"], [])

    def test_opaque_rgba_is_still_eligible_for_prompt_diagnostics(self):
        image, subject, mask, ignore = gray_fixture()
        report = self.assert_inputs_unchanged(image.convert("RGBA"), subject, mask, ignore)
        self.assertEqual(report["mode"], "opaque_prompted")
        self.assertEqual(report["status"], "diagnostics_only")

    def test_unprompted_and_missing_candidate_paths_skip_numerical_dependencies(self):
        image, subject, mask, ignore = gray_fixture()
        for specification, candidate, reason in ((None, None, "no_subject"), (subject, None, "no_candidate_mask")):
            with self.subTest(reason=reason):
                report = self.run_without_numerical_imports(image, specification, candidate, ignore)
                self.assertEqual(report["reason"], reason)
                self.assertEqual(report["status"], "not_applicable")

    def test_invalid_sizes_masks_coordinates_and_strokes_are_rejected_without_mutation(self):
        image, subject, mask, ignore = gray_fixture()
        cases = []
        for key, value in (("image_size", [64, 49]), ("coordinate_space", "pixels"),
                           ("bbox", [0, 0, 0, 1]), ("max_side", True),
                           ("foreground_strokes", [{"points": [[float("nan"), 0.5]], "radius": 0.01}]),
                           ("background_strokes", [{"points": [[0.1, 0.1]], "radius": float("inf")}]),
                           ("foreground_strokes", [{"points": [], "radius": 0.01}])):
            invalid = copy.deepcopy(subject)
            invalid[key] = value
            cases.append((key, invalid, mask, ignore))
        cases.extend((("mask-size", subject, Image.new("L", (64, 49)), ignore),
                      ("mask-mode", subject, mask.convert("RGB"), ignore),
                      ("ignore-size", subject, mask, Image.new("L", (64, 49)))))
        source_before, mask_before, ignore_before = snapshot(image), snapshot(mask), snapshot(ignore)
        for name, specification, candidate, unknown in cases:
            with self.subTest(invalid=name):
                prompt_before = json.dumps(specification, sort_keys=True)
                with self.assertRaises(ValueError):
                    self.module.analyze_prompt(image, specification, candidate, unknown)
                self.assertEqual(json.dumps(specification, sort_keys=True), prompt_before)
                self.assertEqual(snapshot(image), source_before)
                self.assertEqual(snapshot(mask), mask_before)
                self.assertEqual(snapshot(ignore), ignore_before)


if __name__ == "__main__":
    unittest.main()
