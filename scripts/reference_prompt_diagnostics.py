"""Read-only prompt risks; RGB similarity and candidate topology are not semantics."""

import math

from PIL import Image, ImageDraw


def _unit_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Normalized coordinates must be finite numbers in [0, 1]")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Normalized coordinates must be finite numbers in [0, 1]")
    return value


def _point(point, size):
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("A point must contain normalized x and y")
    return tuple(round(_unit_number(value) * (extent - 1))
                 for value, extent in zip(point, size))


def _validate_prompt(subject, size):
    if not isinstance(subject, dict) or subject.get("image_size") != list(size):
        raise ValueError("subject image_size must match the source image")
    if subject.get("coordinate_space") != "normalized_xy":
        raise ValueError("subject coordinate_space must be normalized_xy")
    bounds = subject.get("bbox")
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError("bbox must contain normalized left, top, right, bottom")
    left, top = _point(bounds[:2], size)
    right, bottom = _point(bounds[2:], size)
    if left >= right or top >= bottom:
        raise ValueError("bbox must have positive source-pixel extent")
    max_side = subject.get("max_side", 1280)
    if isinstance(max_side, bool) or not isinstance(max_side, int) or not 128 <= max_side <= 4096:
        raise ValueError("max_side must be an integer in [128, 4096]")
    return max_side


def _raster_stroke(stroke, size, np):
    if not isinstance(stroke, dict) or not isinstance(stroke.get("points"), list) or not stroke["points"]:
        raise ValueError("Each stroke requires a nonempty points list")
    radius = stroke.get("radius", 0.008)
    if isinstance(radius, bool) or not isinstance(radius, (int, float)):
        raise ValueError("stroke radius must be finite and in (0, 0.10]")
    if not math.isfinite(radius) or not 0 < radius <= 0.10:
        raise ValueError("stroke radius must be finite and in (0, 0.10]")
    points = [_point(point, size) for point in stroke["points"]]
    pixel_radius = max(1, round(radius * min(size)))
    left = max(0, min(point[0] for point in points) - pixel_radius)
    top = max(0, min(point[1] for point in points) - pixel_radius)
    right = min(size[0], max(point[0] for point in points) + pixel_radius + 1)
    bottom = min(size[1], max(point[1] for point in points) + pixel_radius + 1)
    local_points = [(horizontal - left, vertical - top) for horizontal, vertical in points]
    centerline = Image.new("L", (right - left, bottom - top), 0)
    brush = Image.new("L", centerline.size, 0)
    center_drawing = ImageDraw.Draw(centerline)
    brush_drawing = ImageDraw.Draw(brush)
    if len(points) > 1:
        center_drawing.line(local_points, fill=255, width=1)
        brush_drawing.line(local_points, fill=255, width=2 * pixel_radius + 1)
    for horizontal, vertical in local_points:
        center_drawing.point((horizontal, vertical), fill=255)
        brush_drawing.ellipse((horizontal - pixel_radius, vertical - pixel_radius,
                               horizontal + pixel_radius, vertical + pixel_radius), fill=255)
    return {
        "bbox_pixels": [left, top, right, bottom],
        "points_pixels": [list(point) for point in points],
        "radius_pixels": pixel_radius,
        "centerline": np.asarray(centerline) > 0,
        "brush": np.asarray(brush) > 0,
    }


def _window(array, bounds):
    left, top, right, bottom = bounds
    return array[top:bottom, left:right]


def _pixel_box(bits, np, offset=(0, 0)):
    vertical, horizontal = np.nonzero(bits)
    if not horizontal.size:
        return None
    return [int(horizontal.min()) + offset[0], int(vertical.min()) + offset[1],
            int(horizontal.max()) + offset[0] + 1, int(vertical.max()) + offset[1] + 1]


def _review(report, kind, bounds, suggestion, stroke_ids=None):
    if bounds is not None:
        report["review_regions"].append({
            "kind": kind, "bbox_pixels": bounds,
            "stroke_ids": stroke_ids or [], "suggestion": suggestion,
            "interpretation": "numerical_risk_only",
        })


def _colors(rgb, selected, np):
    pixels = rgb[selected].astype(np.float64)
    if not pixels.size:
        return {"sample_pixels": 0, "mean_rgb": None, "median_rgb": None,
                "channel_range_rgb": None, "rgb_rms_spread": None}
    mean = pixels.mean(axis=0)
    return {
        "sample_pixels": int(pixels.shape[0]),
        "mean_rgb": [float(value) for value in mean],
        "median_rgb": [float(value) for value in np.median(pixels, axis=0)],
        "channel_range_rgb": [int(value) for value in np.ptp(pixels, axis=0)],
        "rgb_rms_spread": float(np.sqrt(np.mean((pixels - mean) ** 2))),
    }


def _overlap(first, second, field, np):
    first_bounds, second_bounds = first["bbox_pixels"], second["bbox_pixels"]
    left, top = max(first_bounds[0], second_bounds[0]), max(first_bounds[1], second_bounds[1])
    right, bottom = min(first_bounds[2], second_bounds[2]), min(first_bounds[3], second_bounds[3])
    if left >= right or top >= bottom:
        return 0, None
    first_part = first[field][top - first_bounds[1]:bottom - first_bounds[1],
                              left - first_bounds[0]:right - first_bounds[0]]
    second_part = second[field][top - second_bounds[1]:bottom - second_bounds[1],
                                left - second_bounds[0]:right - second_bounds[0]]
    overlap = first_part & second_part
    return int(overlap.sum()), _pixel_box(overlap, np, (left, top))


def _regions(bits, cv2, np):
    count, labels, statistics, unused_centroids = cv2.connectedComponentsWithStats(
        bits.astype(np.uint8), connectivity=8)
    regions = []
    for component_id in range(1, count):
        left, top, width, height, area = (int(value) for value in statistics[component_id])
        regions.append({"component_id": component_id, "pixels": area,
                        "bbox_pixels": [left, top, left + width, top + height]})
    return labels, regions


def _stroke_report(record, rgb, unknown, candidate, labels, opposite, report, np):
    bounds = record["bbox_pixels"]
    local_rgb = _window(rgb, bounds)
    local_unknown = _window(unknown, bounds)
    centerline = record["centerline"] & ~local_unknown
    brush = record["brush"] & ~local_unknown
    center_color = _colors(local_rgb, centerline, np)
    brush_color = _colors(local_rgb, brush, np)
    shell_color = _colors(local_rgb, brush & ~record["centerline"], np)
    mismatch = np.zeros(brush.shape, dtype=bool)
    if center_color["median_rgb"] is not None:
        distance = np.mean((local_rgb.astype(np.float64) - center_color["median_rgb"]) ** 2, axis=2)
        mismatch = brush & (distance > 144)
    local_labels = _window(labels, bounds)
    component_ids = sorted(int(value) for value in np.unique(local_labels[centerline]) if value)
    flags = []
    if center_color["rgb_rms_spread"] is not None and center_color["rgb_rms_spread"] > 12:
        flags.append("centerline_color_mixture")
    if brush_color["rgb_rms_spread"] is not None and brush_color["rgb_rms_spread"] > 12:
        flags.append("brush_color_mixture")
    if mismatch.any():
        flags.append("brush_differs_from_centerline_color_band")
        _review(report, "stroke_color_mixture", _pixel_box(mismatch, np, tuple(bounds[:2])),
                "Inspect this crop; consider a narrower or split stroke only after visual review.",
                [record["id"]])
    ignored_center = int((record["centerline"] & local_unknown).sum())
    ignored_brush = int((record["brush"] & local_unknown).sum())
    opposite_overlap = record["brush"] & _window(opposite, bounds)
    if ignored_brush:
        flags.append("stroke_touches_unknown_ignore")
        _review(report, "stroke_ignore_contact",
                _pixel_box(record["brush"] & local_unknown, np, tuple(bounds[:2])),
                "Review the stroke and unknown region together; do not relabel or shrink ignore.",
                [record["id"]])
    if opposite_overlap.any():
        flags.append("opposite_label_brush_overlap")
    selected_center = int((centerline & _window(candidate, bounds)).sum())
    unselected_center = int(centerline.sum()) - selected_center
    if record["kind"] == "foreground" and unselected_center:
        flags.append("foreground_centerline_outside_candidate")
        _review(report, "foreground_candidate_gap",
                _pixel_box(centerline & ~_window(candidate, bounds), np, tuple(bounds[:2])),
                "Inspect candidate support at the explicit foreground centerline; no repair is applied.",
                [record["id"]])
    return {
        "id": record["id"], "kind": record["kind"],
        "bbox_pixels": bounds, "points_pixels": record["points_pixels"],
        "radius_pixels": record["radius_pixels"],
        "centerline_color": center_color, "brush_color": brush_color,
        "brush_shell_color": shell_color,
        "brush_outside_centerline_color_band_pixels": int(mismatch.sum()),
        "ignore_centerline_pixels": ignored_center, "ignore_brush_pixels": ignored_brush,
        "opposite_brush_overlap_pixels": int(opposite_overlap.sum()),
        "candidate_centerline_pixels": selected_center,
        "unselected_known_centerline_pixels": unselected_center,
        "candidate_component_ids": component_ids, "risk_flags": flags,
    }


def _thin_support(candidate, unknown_neighborhood, foreground, factor, report, cv2, np):
    padded = np.pad(candidate, 2)
    left = padded[2:-2, 1:-3]
    right = padded[2:-2, 3:-1]
    far_left = padded[2:-2, :-4]
    far_right = padded[2:-2, 4:]
    above = padded[1:-3, 2:-2]
    below = padded[3:-1, 2:-2]
    far_above = padded[:-4, 2:-2]
    far_below = padded[4:, 2:-2]
    horizontal_long = (left & right) | (left & far_left) | (right & far_right)
    vertical_long = (above & below) | (above & far_above) | (below & far_below)
    thin = candidate & (~horizontal_long | ~vertical_long)
    single = candidate & ((~left & ~right) | (~above & ~below))
    labels, regions = _regions(thin, cv2, np)
    for region in regions:
        bounds = region["bbox_pixels"]
        local_region = _window(labels, bounds) == region["component_id"]
        one_pixel_count = int((local_region & _window(single, bounds)).sum())
        minimum_span = 1 if one_pixel_count else 2
        touches_ignore = bool((local_region & _window(unknown_neighborhood, bounds)).any())
        touches_image = bounds[0] == 0 or bounds[1] == 0 or bounds[2] == candidate.shape[1] or bounds[3] == candidate.shape[0]
        region.update({
            "one_pixel_axis_run_pixels": one_pixel_count,
            "two_pixel_axis_run_pixels": region["pixels"] - one_pixel_count,
            "minimum_axis_run_source_pixels": minimum_span,
            "projected_minimum_axis_run_working_pixels": minimum_span * factor,
            "foreground_centerline_pixels": int((local_region & _window(foreground, bounds)).sum()),
            "ignore_censored": touches_ignore, "image_edge_censored": touches_image,
            "subpixel_after_downsampling": minimum_span * factor < 1,
        })
        if region["subpixel_after_downsampling"]:
            _review(report, "thin_source_support", bounds,
                    "Inspect original pixels and place a centerline hint on a visible thin part; axis runs are not physical thickness.")
    return {
        "basis": "candidate_axis_runs_at_source_resolution",
        "interpretation": "sampling_support_only_not_accuracy_or_physical_thickness",
        "regions": regions,
    }


def analyze_prompt(image, subject, mask, ignore):
    """Return JSON-safe, read-only prompt diagnostics in source-pixel half-open boxes.

    Alpha, unprompted and missing-candidate paths do not import NumPy/OpenCV.
    Unknown ignore pixels never contribute RGB samples or hole truth.
    """
    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL image")
    for name, supplied in (("mask", mask), ("ignore", ignore)):
        if supplied is None and name == "mask":
            continue
        if not isinstance(supplied, Image.Image) or supplied.mode != "L" or supplied.size != image.size:
            raise ValueError(name + " must be a source-sized PIL L image")
    report = {
        "schema": "reference-prompt-diagnostics/1", "status": "not_applicable",
        "image_size": list(image.size), "coordinate_space": "source_pixels_xy",
        "bbox_convention": "half_open_xyxy", "read_only": True,
        "semantic_verdict": "not_evaluated", "ignore_semantics": "unknown_not_background",
        "review_regions": [],
    }
    alpha_min, alpha_max = image.convert("RGBA").getchannel("A").getextrema()
    if alpha_min <= 8:
        report.update(mode="source_alpha", reason="fully_transparent_source" if alpha_max <= 8 else "source_alpha_not_prompted_segmentation")
        return report
    if subject is None or mask is None:
        report.update(mode="unprompted" if subject is None else "opaque_prompted",
                      reason="no_subject" if subject is None else "no_candidate_mask")
        return report
    max_side = _validate_prompt(subject, image.size)
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError("Opaque prompted diagnostics require NumPy and OpenCV") from error
    rgb = np.asarray(image.convert("RGB"))
    unknown = np.asarray(ignore) > 0
    supplied_candidate = np.asarray(mask) > 0
    candidate = supplied_candidate & ~unknown
    factor = min(1.0, max_side / max(image.size))
    working_size = tuple(max(2, round(extent * factor)) for extent in image.size)
    unions = {kind: np.zeros(candidate.shape, dtype=bool) for kind in ("foreground", "background")}
    foreground_centerlines = np.zeros(candidate.shape, dtype=bool)
    records = []
    for kind in ("foreground", "background"):
        strokes = subject.get(kind + "_strokes", [])
        if not isinstance(strokes, list):
            raise ValueError(kind + "_strokes must be a list")
        for index, stroke in enumerate(strokes):
            record = _raster_stroke(stroke, image.size, np)
            record.update(id=kind + ":" + str(index), kind=kind,
                          working=_raster_stroke(stroke, working_size, np))
            _window(unions[kind], record["bbox_pixels"])[:] |= record["brush"]
            if kind == "foreground":
                _window(foreground_centerlines, record["bbox_pixels"])[:] |= record["centerline"]
            records.append(record)
    labels, components = _regions(candidate, cv2, np)
    report.update(status="diagnostics_only", mode="opaque_prompted",
                  working_size=list(working_size), working_scale=factor,
                  numerical_rules={"rgb_rms_mixture_above": 12, "centerline_band_rgb_mse_above": 144,
                                   "similar_centerline_mean_rgb_mse_at_most": 4, "connectivity": 8},
                  candidate_component_count=len(components))
    report["strokes"] = [
        _stroke_report(record, rgb, unknown, candidate, labels,
                       unions["background" if record["kind"] == "foreground" else "foreground"], report, np)
        for record in records
    ]
    stroke_reports = {stroke["id"]: stroke for stroke in report["strokes"]}
    foreground_records = [record for record in records if record["kind"] == "foreground"]
    background_records = [record for record in records if record["kind"] == "background"]
    report["cross_label_pairs"] = []
    for positive in foreground_records:
        for negative in background_records:
            overlap_pixels, overlap_box = _overlap(positive, negative, "brush", np)
            center_overlap, unused_box = _overlap(positive, negative, "centerline", np)
            working_overlap, unused_box = _overlap(positive["working"], negative["working"], "brush", np)
            positive_mean = stroke_reports[positive["id"]]["centerline_color"]["mean_rgb"]
            negative_mean = stroke_reports[negative["id"]]["centerline_color"]["mean_rgb"]
            color_mse = None if positive_mean is None or negative_mean is None else float(
                np.mean((np.asarray(positive_mean) - negative_mean) ** 2))
            pair = {
                "stroke_ids": [positive["id"], negative["id"]],
                "source_brush_overlap_pixels": overlap_pixels,
                "source_centerline_overlap_pixels": center_overlap,
                "source_overlap_bbox_pixels": overlap_box,
                "working_brush_overlap_pixels": working_overlap,
                "centerline_mean_rgb_mse": color_mse,
                "color_ambiguity": color_mse is not None and color_mse <= 4,
                "interpretation": "shared_color_does_not_identify_background_or_a_wrong_hint",
            }
            report["cross_label_pairs"].append(pair)
            if overlap_pixels or working_overlap:
                source_box = [min(positive["bbox_pixels"][0], negative["bbox_pixels"][0]),
                              min(positive["bbox_pixels"][1], negative["bbox_pixels"][1]),
                              max(positive["bbox_pixels"][2], negative["bbox_pixels"][2]),
                              max(positive["bbox_pixels"][3], negative["bbox_pixels"][3])]
                _review(report, "opposite_seed_overlap", overlap_box or source_box,
                        "Inspect seed spacing at source and working sizes; changing hints requires visual review.",
                        pair["stroke_ids"])
    report["foreground_connectivity"] = []
    for first_index, first in enumerate(foreground_records):
        for second in foreground_records[first_index + 1:]:
            first_ids = stroke_reports[first["id"]]["candidate_component_ids"]
            second_ids = stroke_reports[second["id"]]["candidate_component_ids"]
            connected = bool(set(first_ids) & set(second_ids)) if first_ids and second_ids else None
            first_points, second_points = first["points_pixels"], second["points_pixels"]
            horizontal_gap = max(0, min(point[0] for point in first_points) - max(point[0] for point in second_points),
                                 min(point[0] for point in second_points) - max(point[0] for point in first_points))
            vertical_gap = max(0, min(point[1] for point in first_points) - max(point[1] for point in second_points),
                               min(point[1] for point in second_points) - max(point[1] for point in first_points))
            report["foreground_connectivity"].append({
                "stroke_ids": [first["id"], second["id"]],
                "candidate_connected": connected,
                "centerline_bbox_gap_pixels": math.hypot(horizontal_gap, vertical_gap),
                "instance_identity": "not_inferred",
                "interpretation": "unknown_regions_can_hide_connections; connectivity_is_not_instance_truth",
            })
    kernel = np.ones((3, 3), dtype=np.uint8)
    unknown_neighborhood = cv2.dilate(unknown.astype(np.uint8), kernel) > 0
    interior = cv2.erode(candidate.astype(np.uint8), kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    contact = candidate & ~interior & unknown_neighborhood
    unused_labels, contact_regions = _regions(contact, cv2, np)
    report["ignore_boundary"] = {
        "semantics": "unknown_not_background",
        "mask_overlap_pixels": int((supplied_candidate & unknown).sum()),
        "adjacent_candidate_boundary_pixels": int(contact.sum()),
        "contact_regions": contact_regions,
        "interpretation": "missing_candidate_inside_ignore_is_not_observed_hole_truth",
    }
    for region in contact_regions:
        left, top, right, bottom = region["bbox_pixels"]
        _review(report, "ignore_boundary_contact",
                [max(0, left - 1), max(0, top - 1), min(image.width, right + 1), min(image.height, bottom + 1)],
                "Inspect the candidate/unknown junction in the original; continuation remains unknown.")
    report["image_edge_contact"] = {}
    for side, bounds in (("left", [0, 0, 1, image.height]),
                         ("right", [image.width - 1, 0, image.width, image.height]),
                         ("top", [0, 0, image.width, 1]),
                         ("bottom", [0, image.height - 1, image.width, image.height])):
        edge = _window(candidate, bounds)
        edge_box = _pixel_box(edge, np, tuple(bounds[:2]))
        report["image_edge_contact"][side] = {"candidate_pixels": int(edge.sum()), "bbox_pixels": edge_box,
                                               "interpretation": "frame_contact_not_proof_of_truncation"}
        _review(report, "image_edge_contact", edge_box,
                "Inspect frame limits; do not invent out-of-frame geometry or automatically expand the image.")
    report["thin_source_support"] = _thin_support(
        candidate, unknown_neighborhood, foreground_centerlines, factor, report, cv2, np)
    return report
