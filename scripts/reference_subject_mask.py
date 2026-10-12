"""Target-constrained reference masks; candidates are not semantic approvals."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw


def _point(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("point must contain normalized x and y")
    if any(isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1 for number in value):
        raise ValueError("normalized coordinates must be finite numbers in [0, 1]")
    return tuple(min(extent - 1, int(round(number * (extent - 1)))) for number, extent in zip(value, size))


def _polygon_mask(polygons, size):
    if not isinstance(polygons, list):
        raise ValueError("ignore_polygons must be a list")
    canvas = Image.new("L", size, 0)
    drawing = ImageDraw.Draw(canvas)
    for polygon in polygons:
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError("ignore polygon must have at least three points")
        drawing.polygon([_point(point, size) for point in polygon], fill=255)
    return canvas


def _strokes(strokes, size):
    if not isinstance(strokes, list):
        raise ValueError("strokes must be a list")
    canvas = Image.new("L", size, 0)
    drawing = ImageDraw.Draw(canvas)
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise ValueError("each stroke must be an object")
        points = stroke.get("points", [])
        radius = stroke.get("radius", 0.008)
        if not points or isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 0 < radius <= 0.10:
            raise ValueError("stroke requires points and normalized radius in (0, 0.10]")
        converted = [_point(point, size) for point in points]
        pixel_radius = max(1, int(round(radius * min(size))))
        if len(converted) > 1:
            drawing.line(converted, fill=255, width=2 * pixel_radius + 1)
        for horizontal, vertical in converted:
            drawing.ellipse((horizontal - pixel_radius, vertical - pixel_radius, horizontal + pixel_radius, vertical + pixel_radius), fill=255)
    return canvas


def _stroke_centerlines(strokes, size):
    canvas = Image.new("L", size, 0)
    drawing = ImageDraw.Draw(canvas)
    for stroke in strokes:
        points = [_point(point, size) for point in stroke["points"]]
        if len(points) > 1:
            drawing.line(points, fill=255, width=1)
        for point in points:
            drawing.point(point, fill=255)
    return canvas


def _validate_subject(subject, size):
    if not isinstance(subject, dict) or not isinstance(subject.get("target"), str) or not subject["target"].strip():
        raise ValueError("subject requires a named target")
    if subject.get("scope") not in ("whole-subject", "local-part", "subject-region"):
        raise ValueError("scope must be whole-subject, local-part or subject-region")
    if subject.get("coordinate_space") != "normalized_xy":
        raise ValueError("coordinate_space must be normalized_xy")
    if "refine_edges" in subject and not isinstance(subject["refine_edges"], bool):
        raise ValueError("refine_edges must be a boolean")
    if "recover_details" in subject and not isinstance(subject["recover_details"], bool):
        raise ValueError("recover_details must be a boolean")
    if list(size) != subject.get("image_size"):
        raise ValueError("subject image_size does not match the original image")
    bbox = subject.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("bbox must contain normalized left, top, right, bottom")
    upper_left = _point(bbox[:2], size)
    lower_right = _point(bbox[2:], size)
    if upper_left[0] >= lower_right[0] or upper_left[1] >= lower_right[1]:
        raise ValueError("bbox must have positive width and height")
    return (*upper_left, *lower_right)


def _finish(mask, ignore, mode, metadata):
    histogram = mask.histogram()
    selected = sum(histogram[128:])
    total = mask.width * mask.height
    metadata.update({"selected_pixels": selected, "selected_fraction": selected / total, "ignored_pixels": sum(ignore.histogram()[128:]), "semantic_review": "unreviewed", "semantic_iou": None})
    bounds = metadata.get("bbox_pixels")
    metadata["bbox_contact"] = {}
    metadata["boundary_warnings"] = []
    if bounds:
        left, top, right, bottom = bounds
        edges = {"left": (left, top, left + 1, bottom + 1), "right": (right, top, right + 1, bottom + 1), "top": (left, top, right + 1, top + 1), "bottom": (left, bottom, right + 1, bottom + 1)}
        internal = {"left": left > 0, "right": right < mask.width - 1, "top": top > 0, "bottom": bottom < mask.height - 1}
        for side, edge in edges.items():
            count = sum(mask.crop(edge).histogram()[128:])
            metadata["bbox_contact"][side] = {"selected_pixels": count, "internal_image_edge": internal[side]}
            if count and internal[side]:
                metadata["boundary_warnings"].append("foreground_contacts_internal_bbox_edge:" + side)
    metadata["requires_bbox_review"] = bool(metadata["boundary_warnings"])
    if selected == 0 or selected == total:
        return {"mask": None, "ignore": ignore, "mode": mode, "status": "DEGENERATE", "metadata": metadata}
    return {"mask": mask, "ignore": ignore, "mode": mode, "status": "CANDIDATE", "metadata": metadata}


def _sample_colors(pixels, limit=4096):
    step = max(1, (len(pixels) + limit - 1) // limit)
    return pixels[::step].copy()


def _color_distance(image, samples, cv2, np, clusters=5):
    cluster_count = min(clusters, len(samples))
    _, _, centers = cv2.kmeans(samples.astype(np.float32), cluster_count, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.1), 1, cv2.KMEANS_PP_CENTERS)
    nearest = np.full(image.shape[:2], np.inf, dtype=np.float32)
    pixels = image.astype(np.float32)
    for center in centers:
        nearest = np.minimum(nearest, np.mean((pixels - center) ** 2, axis=2))
    return nearest


def _solve_original_region(image, labels, region, cv2, np):
    left, top, right, bottom = region
    local_labels = np.ascontiguousarray(labels[top:bottom, left:right])
    local_image = np.ascontiguousarray(image[top:bottom, left:right])
    cv2.setRNGSeed(0)
    cv2.grabCut(local_image, local_labels, None, np.zeros((1, 65), dtype=np.float64), np.zeros((1, 65), dtype=np.float64), 2, cv2.GC_INIT_WITH_MASK)
    labels[top:bottom, left:right] = local_labels
    return labels


def extract_subject(image, subject=None):
    size = image.size
    bounds = _validate_subject(subject, size) if subject is not None else None
    ignore = _polygon_mask(subject.get("ignore_polygons", []), size) if subject else Image.new("L", size, 0)
    metadata = {"target": subject.get("target") if subject else "source nontransparent artwork", "scope": subject.get("scope") if subject else "source-alpha", "image_size": list(size), "bbox_pixels": list(bounds) if bounds else None}
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    alpha_min, alpha_max = alpha.getextrema()
    if alpha_max <= 8:
        metadata["reason"] = "Source image is fully transparent"
        return {"mask": None, "ignore": ignore, "mode": "source_alpha", "status": "DEGENERATE", "metadata": metadata}
    if alpha_min <= 8 and alpha_max > 8:
        mask = alpha.point(lambda value: 255 if value > 8 else 0)
        if bounds:
            allowed = Image.new("L", size, 0)
            ImageDraw.Draw(allowed).rectangle(bounds, fill=255)
            from PIL import ImageChops
            mask = ImageChops.multiply(mask, allowed)
        from PIL import ImageChops
        mask = ImageChops.subtract(mask, ignore)
        metadata["alpha_threshold"] = 8
        return _finish(mask, ignore, "source_alpha", metadata)
    if subject is None:
        metadata["reason"] = "Opaque reference requires a target bbox and foreground/background strokes; luminance is not subject identity."
        return {"mask": None, "ignore": ignore, "mode": "none", "status": "NEEDS_SUBJECT", "metadata": metadata}
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError("Target segmentation requires numpy and OpenCV in the bound interpreter") from error
    max_side = subject.get("max_side", 1280)
    iterations = subject.get("iterations", 5)
    if isinstance(max_side, bool) or not isinstance(max_side, int) or not 128 <= max_side <= 4096:
        raise ValueError("max_side must be an integer in [128, 4096]")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 20:
        raise ValueError("iterations must be an integer in [1, 20]")
    factor = min(1.0, max_side / max(size))
    working_size = tuple(max(2, int(round(extent * factor))) for extent in size)
    foreground_full = _strokes(subject.get("foreground_strokes", []), size)
    background_full = _strokes(subject.get("background_strokes", []), size)
    allowed_full = Image.new("L", size, 0)
    ImageDraw.Draw(allowed_full).rectangle(bounds, fill=255)
    foreground_full_bits = np.asarray(foreground_full) > 0
    background_full_bits = np.asarray(background_full) > 0
    ignored_full_bits = np.asarray(ignore) > 0
    allowed_full_bits = np.asarray(allowed_full) > 0
    if (foreground_full_bits & (background_full_bits | ignored_full_bits | ~allowed_full_bits)).any():
        raise ValueError("Foreground strokes conflict with background, ignored area or bbox at original resolution")
    if (background_full_bits & ignored_full_bits).any():
        raise ValueError("Known background strokes conflict with unknown/ignored pixels")
    foreground = np.asarray(_strokes(subject.get("foreground_strokes", []), working_size)) > 0
    background = np.asarray(_strokes(subject.get("background_strokes", []), working_size)) > 0
    ignored = np.asarray(ignore.resize(working_size, Image.Resampling.NEAREST)) > 0
    working_bounds = _validate_subject({**subject, "image_size": list(working_size)}, working_size)
    allowed = np.zeros((working_size[1], working_size[0]), dtype=bool)
    left, top, right, bottom = working_bounds
    allowed[top:bottom + 1, left:right + 1] = True
    if not foreground.any():
        raise ValueError("At least one foreground stroke is required for an opaque reference")
    if (foreground & (background | ignored | ~allowed)).any():
        raise ValueError("Foreground strokes conflict with background, ignored area or bbox")
    if (background & ignored).any():
        raise ValueError("Known background strokes conflict with unknown/ignored pixels")
    if not ((background | ~allowed) & ~ignored).any():
        raise ValueError("At least one background constraint is required")
    labels = np.full(allowed.shape, cv2.GC_BGD, dtype=np.uint8)
    labels[allowed] = cv2.GC_PR_FGD
    source_rgb = np.asarray(image.convert("RGB")).copy()
    known_background_full = source_rgb[background_full_bits] if background_full_bits.any() else source_rgb[~allowed_full_bits & ~ignored_full_bits]
    if not len(known_background_full):
        raise ValueError("At least one known background pixel is required before resampling")
    neutral_background_full = known_background_full[len(known_background_full) // 2]
    source_rgb[ignored_full_bits] = neutral_background_full
    rgb = np.asarray(Image.fromarray(source_rgb).resize(working_size, Image.Resampling.LANCZOS))
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    foreground_colors = _sample_colors(bgr[foreground])
    background_colors = _sample_colors(bgr[(background | ~allowed) & ~ignored])
    if len(foreground_colors) < 5 or len(background_colors) < 5:
        raise ValueError("At least five known pixels are needed for each color model")
    cv2.setRNGSeed(0)
    foreground_color_distance = _color_distance(bgr, foreground_colors, cv2, np)
    background_color_distance = _color_distance(bgr, background_colors, cv2, np)
    foreground_distance = cv2.distanceTransform((~foreground).astype(np.uint8), cv2.DIST_L2, 5)
    background_distance = cv2.distanceTransform((~background).astype(np.uint8), cv2.DIST_L2, 5) if background.any() else np.full(allowed.shape, np.inf)
    background_color_compatible = (background_color_distance < 0.75 * foreground_color_distance) | ((background_color_distance <= 144) & (foreground_color_distance <= 144))
    background_support = (background_distance <= 0.10 * min(working_size)) & (background_distance < 0.4 * foreground_distance) & background_color_compatible
    labels[foreground] = cv2.GC_FGD
    labels[background | background_support | ignored] = cv2.GC_BGD
    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    cv2.setRNGSeed(0)
    try:
        solver_image = bgr.copy()
        known_background = bgr[background] if background.any() else background_colors
        neutral_background = known_background[len(known_background) // 2]
        solver_image[ignored] = neutral_background
        cv2.grabCut(solver_image, labels, None, background_model, foreground_model, iterations, cv2.GC_INIT_WITH_MASK)
    except cv2.error as error:
        raise ValueError("GrabCut failed for the supplied target constraints: " + str(error)) from error
    selected = (labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)
    component_count, components = cv2.connectedComponents(selected.astype(np.uint8), connectivity=8)
    retained = np.unique(components[foreground])
    selected &= np.isin(components, retained[retained != 0])
    selected &= allowed & ~ignored & ~background & ~background_support
    mask = Image.fromarray(selected.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
    refinement_size = None
    refinement_enabled = subject.get("refine_edges", True)
    refinement_background_support_pixels = 0
    refinement_hole_support_pixels = 0
    refinement_hole_recovered_pixels = 0
    detail_recovery_enabled = subject.get("recover_details", False)
    refinement_region = (0, 0, size[0], size[1])
    if size[0] * size[1] > 4_000_000:
        left, top, right, bottom = bounds
        refinement_region = (max(0, left - 16), max(0, top - 16), min(size[0], right + 17), min(size[1], bottom + 17))
    region_left, region_top, region_right, region_bottom = refinement_region
    region_size = (region_right - region_left, region_bottom - region_top)
    if refinement_enabled and working_size != size and region_size[0] * region_size[1] <= 4_000_000 and size[0] * size[1] <= 16_000_000:
        refinement_size = region_size
        refinement_labels = np.full((size[1], size[0]), cv2.GC_BGD, dtype=np.uint8)
        coarse_bits = np.asarray(mask) > 0
        refinement_labels[allowed_full_bits] = cv2.GC_PR_BGD
        refinement_labels[coarse_bits & allowed_full_bits] = cv2.GC_PR_FGD
        boundary_radius = min(8, max(2, int(round(2 / factor))))
        boundary_kernel = np.ones((boundary_radius * 2 + 1, boundary_radius * 2 + 1), dtype=np.uint8)
        coarse_interior = cv2.erode(coarse_bits.astype(np.uint8), boundary_kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
        coarse_neighborhood = cv2.dilate(coarse_bits.astype(np.uint8), boundary_kernel) > 0
        refinement_labels[~coarse_neighborhood] = cv2.GC_BGD
        refinement_labels[coarse_interior & allowed_full_bits] = cv2.GC_FGD
        coarse_background_support = np.asarray(Image.fromarray(background_support.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)) > 0
        refinement_labels[coarse_background_support | background_full_bits | ignored_full_bits] = cv2.GC_BGD
        foreground_centerlines = np.asarray(_stroke_centerlines(subject["foreground_strokes"], size)) > 0
        original_bgr = np.ascontiguousarray(source_rgb[:, :, ::-1])
        original_foreground_colors = _sample_colors(original_bgr[foreground_centerlines])
        original_background_colors = _sample_colors(known_background_full[:, ::-1])
        cv2.setRNGSeed(0)
        original_foreground_distance = _color_distance(original_bgr, original_foreground_colors, cv2, np)
        original_background_distance = _color_distance(original_bgr, original_background_colors, cv2, np)
        background_color_bits = (original_background_distance <= 4) & (original_foreground_distance > 144) & ~ignored_full_bits & ~foreground_full_bits
        _, background_color_components = cv2.connectedComponents(background_color_bits.astype(np.uint8), connectivity=8)
        original_background_anchors = (background_full_bits | ~allowed_full_bits) & background_color_bits
        anchored_background_components = np.unique(background_color_components[original_background_anchors])
        original_background_support = background_color_bits & allowed_full_bits & np.isin(background_color_components, anchored_background_components[anchored_background_components != 0])
        refinement_labels[original_background_support] = cv2.GC_BGD
        refinement_background_support_pixels = int(original_background_support.sum())
        hole_support = np.zeros(coarse_bits.shape, dtype=bool)
        if detail_recovery_enabled:
            _, hole_components = cv2.connectedComponents((~coarse_bits).astype(np.uint8), connectivity=8)
            exterior_components = np.unique(np.concatenate((hole_components[0], hole_components[-1], hole_components[:, 0], hole_components[:, -1])))
            uncertain_components = np.unique(hole_components[ignored_full_bits | background_full_bits])
            blocked_holes = np.union1d(exterior_components, uncertain_components)
            enclosed = ~coarse_bits & ~np.isin(hole_components, blocked_holes) & allowed_full_bits & ~ignored_full_bits
            positive_detail_distance = _color_distance(original_bgr, original_foreground_colors, cv2, np, clusters=16)
            negative_detail_distance = _color_distance(original_bgr, original_background_colors, cv2, np, clusters=16)
            hole_support = enclosed & (positive_detail_distance <= 144) & (positive_detail_distance * 1.5 < negative_detail_distance) & ~original_background_support & ~background_full_bits & ~coarse_background_support
        refinement_hole_support_pixels = int(hole_support.sum())
        refinement_labels[foreground_full_bits] = cv2.GC_FGD
        cv2.setRNGSeed(0)
        try:
            refinement_labels = _solve_original_region(original_bgr, refinement_labels, refinement_region, cv2, np)
        except cv2.error as error:
            raise ValueError("Full-resolution boundary refinement failed: " + str(error)) from error
        refined = (refinement_labels == cv2.GC_FGD) | (refinement_labels == cv2.GC_PR_FGD)
        if hole_support.any():
            detail_labels = np.where(refined, cv2.GC_FGD, cv2.GC_BGD).astype(np.uint8)
            detail_labels[hole_support] = cv2.GC_PR_FGD
            try:
                detail_labels = _solve_original_region(original_bgr, detail_labels, refinement_region, cv2, np)
            except cv2.error as error:
                raise ValueError("Seed-supported interior detail recovery failed: " + str(error)) from error
            recovered = hole_support & ((detail_labels == cv2.GC_FGD) | (detail_labels == cv2.GC_PR_FGD))
            refinement_hole_recovered_pixels = int((recovered & ~refined).sum())
            refined |= recovered
        refined &= allowed_full_bits & ~ignored_full_bits & ~background_full_bits
        _, refined_components = cv2.connectedComponents(refined.astype(np.uint8), connectivity=8)
        refined_retained = np.unique(refined_components[foreground_full_bits])
        refined &= np.isin(refined_components, refined_retained[refined_retained != 0])
        mask = Image.fromarray(refined.astype(np.uint8) * 255)
    full = np.asarray(mask).copy()
    full[foreground_full_bits] = 255
    full[background_full_bits | ignored_full_bits | ~allowed_full_bits] = 0
    mask = Image.fromarray(full)
    metadata["refinement"] = {"policy": "original-resolution seeded GrabCut inside a coarse-boundary neighborhood; coarse-interior and far-background are numerical priors, not semantic truth; only spatially anchored original negative colors can override a contaminated coarse-interior prior; at most 4000000 source pixels", "enabled": refinement_enabled, "image_size": list(refinement_size) if refinement_size else None, "iterations": 2 if refinement_size else 0, "boundary_radius_pixels": boundary_radius if refinement_size else None, "original_color_background_support_pixels": refinement_background_support_pixels, "original_color_background_support_rule": "mean squared RGB distance <=4 to original negative clusters and >144 to original positive centerlines, with an 8-connected color path to explicit negative strokes or outside bbox; explicit original foreground strokes take precedence", "skipped_reason": "disabled" if not refinement_enabled else "source_pixel_budget" if working_size != size and refinement_size is None else None}
    metadata.update({"working_size": list(working_size), "iterations": iterations, "opencv_version": cv2.__version__, "foreground_seed_pixels_work": int(foreground.sum()), "background_seed_pixels_work": int(background.sum()), "ignored_color_policy": "ignored RGB replaced by a known background exemplar before resampling and in temporary solver images only; source unchanged; ignored output never foreground", "background_support_pixels_work": int(background_support.sum()), "background_support_rule": "color-compatible and within 0.10 short-side of negative strokes; negative distance below 0.4 positive distance", "probable_foreground_prior": "target bbox minus constrained background, not known foreground", "components_before_seed_filter": component_count - 1, "retained_components": int(len(retained[retained != 0])), "rng_seed": 0, "prompted": True})
    metadata["refinement"]["seed_supported_hole_candidate_pixels"] = refinement_hole_support_pixels
    metadata["refinement"]["detail_recovery_enabled"] = detail_recovery_enabled
    metadata["refinement"]["detail_recovery_status"] = "experimental_opt_in" if detail_recovery_enabled else "disabled_by_default_after_visual_regression"
    metadata["refinement"]["seed_supported_hole_recovered_pixels"] = refinement_hole_recovered_pixels
    metadata["refinement"]["region_pixels"] = list(refinement_region) if refinement_size else None
    metadata["refinement"]["detail_policy"] = "Enclosed coarse holes with original positive-centerline color support may enter a separate constrained solve only if that hole component contains neither ignore nor explicit negative seeds; only supported hole pixels can be added, never exterior pixels; the declared ignore domain is unchanged"
    metadata["refinement"]["policy"] = "Original-resolution seeded GrabCut inside a coarse-boundary neighborhood, with at most 4000000 solver pixels; larger sources may use the target bbox plus a 16-pixel background context if the ROI fits, up to 16000000 source pixels; hard priors are numerical constraints, not semantic truth"
    if refinement_enabled and working_size != size and refinement_size is None:
        metadata["refinement"]["skipped_reason"] = "source_pixel_budget" if size[0] * size[1] > 16_000_000 else "refinement_region_pixel_budget"
    result = _finish(mask, ignore, "seeded_grabcut", metadata)
    diagnostics_path = Path(__file__).with_name("reference_prompt_diagnostics.py")
    diagnostics_spec = importlib.util.spec_from_file_location("reference_prompt_diagnostics_local", diagnostics_path)
    diagnostics_module = importlib.util.module_from_spec(diagnostics_spec)
    diagnostics_spec.loader.exec_module(diagnostics_module)
    metadata["prompt_diagnostics"] = diagnostics_module.analyze_prompt(image, subject, result["mask"], ignore)
    return result


def write_artifacts(image, result, path):
    destination = Path(path)
    if destination.suffix.lower() != ".png":
        raise ValueError("Binary mask artifacts require a lossless .png destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if result["mask"] is None and destination.exists():
        raise ValueError("No new mask was produced and the destination already exists; choose a fresh output path")
    ignore_path = destination.with_name(destination.stem + ".ignore.png")
    result["ignore"].save(ignore_path)
    artifacts = {"ignore": str(ignore_path)}
    if result["mask"] is None:
        return artifacts
    artifacts["ignore_sha256"] = hashlib.sha256(ignore_path.read_bytes()).hexdigest()
    result["mask"].save(destination)
    original = Image.alpha_composite(Image.new("RGBA", image.size, (220, 220, 220, 255)), image.convert("RGBA")).convert("RGB")
    overlay = Image.composite(Image.blend(original, Image.new("RGB", image.size, (255, 0, 180)), 0.5), original, result["mask"])
    overlay = Image.composite(Image.blend(original, Image.new("RGB", image.size, (255, 190, 0)), 0.6), overlay, result["ignore"])
    overlay_path = destination.with_name(destination.stem + ".overlay.png")
    overlay.save(overlay_path)
    artifacts.update({"mask": str(destination), "overlay": str(overlay_path), "mask_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "overlay_sha256": hashlib.sha256(overlay_path.read_bytes()).hexdigest()})
    return artifacts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--subject-spec")
    parser.add_argument("--out-json")
    arguments = parser.parse_args(argv)
    try:
        source = Path(arguments.image)
        destination = Path(arguments.out)
        outputs = [destination, destination.with_name(destination.stem + ".ignore.png"), destination.with_name(destination.stem + ".overlay.png")]
        if arguments.out_json:
            outputs.append(Path(arguments.out_json))
        resolved_outputs = [output.resolve() for output in outputs]
        inputs = [source.resolve()]
        if arguments.subject_spec:
            inputs.append(Path(arguments.subject_spec).resolve())
        if any(output in inputs for output in resolved_outputs):
            raise ValueError("Output artifacts must not overwrite the reference original or subject specification")
        if len(set(resolved_outputs)) != len(resolved_outputs):
            raise ValueError("Mask, ignore, overlay and JSON outputs must have distinct paths")
        if destination.suffix.lower() != ".png":
            raise ValueError("Binary mask artifacts require a lossless .png destination")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        subject = json.loads(Path(arguments.subject_spec).read_text(encoding="utf-8-sig")) if arguments.subject_spec else None
        if subject is not None and not isinstance(subject, dict):
            raise ValueError("subject-spec must contain one target object")
        if subject and subject.get("image_sha256") and subject["image_sha256"] != source_hash:
            raise ValueError("subject image_sha256 does not match the original file")
        with Image.open(source) as image:
            image.load()
            result = extract_subject(image, subject)
            artifacts = write_artifacts(image, result, arguments.out)
        report = {"schema": "reference-subject-mask/1", "source": str(source), "source_sha256": source_hash, "status": result["status"], "mode": result["mode"], "metadata": result["metadata"], "artifacts": artifacts}
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if arguments.out_json:
            report_path = Path(arguments.out_json)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(encoded, encoding="utf-8")
        print(encoded)
        return 0 if result["status"] == "CANDIDATE" else 3
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
