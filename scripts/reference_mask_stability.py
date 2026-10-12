"""Measure resolution sensitivity without voting masks into semantic truth."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops

from reference_subject_mask import extract_subject, write_artifacts


def summarize_variants(results):
    if not results or any(result['mask'] is None for result in results):
        raise ValueError('All variants must produce a nondegenerate candidate mask')
    baseline = results[0]
    size = baseline['mask'].size
    ignored = baseline['ignore']
    disagreement = Image.new('L', size, 0)
    comparisons = []
    for result in results:
        if result['mask'].size != size or result['ignore'].size != size:
            raise ValueError('Variant dimensions differ')
        if ImageChops.difference(ignored, result['ignore']).getbbox():
            raise ValueError('Resolution variants must not change the declared ignore domain')
        difference = ImageChops.difference(baseline['mask'], result['mask'])
        difference = ImageChops.multiply(difference, ImageChops.invert(ignored))
        disagreement = ImageChops.lighter(disagreement, difference)
        comparisons.append({'changed_valid_pixels_from_baseline': difference.histogram()[255], 'selected_pixels': result['metadata']['selected_pixels'], 'mode': result['mode'], 'status': result['status']})
    total = size[0] * size[1]
    excluded = ignored.histogram()[255]
    valid = total - excluded
    if not valid:
        raise ValueError('No common valid pixels remain')
    changed = disagreement.histogram()[255]
    return {'source_pixels': total, 'ignored_pixels': excluded, 'common_valid_pixels': valid, 'disagreement_pixels': changed, 'disagreement_fraction_of_valid': changed / valid, 'comparisons': comparisons, 'semantic_verdict': 'unverified', 'semantic_iou': None, 'interpretation': 'Sensitivity to numerical working resolution only; neither agreement nor disagreement proves correctness. This map never modifies candidate masks or ignore polygons.'}, disagreement


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--subject-spec')
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--max-sides', type=int, nargs='+', default=[960, 1536])
    arguments = parser.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    try:
        source = Path(arguments.image)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        subject_bytes = Path(arguments.subject_spec).read_bytes() if arguments.subject_spec else None
        subject = json.loads(subject_bytes.decode('utf-8-sig')) if subject_bytes is not None else None
        implementation_paths = [Path(__file__), Path(__file__).with_name('reference_subject_mask.py'), Path(__file__).with_name('reference_prompt_diagnostics.py')]
        implementation_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in implementation_paths}
        if subject is not None and not isinstance(subject, dict):
            raise ValueError('subject-spec must contain one target object')
        if subject and subject.get('image_sha256') and subject['image_sha256'] != source_hash:
            raise ValueError('subject image_sha256 does not match the original file')
        destination = Path(arguments.out_dir)
        if destination.exists():
            raise ValueError('Sensitivity outputs require a fresh directory; old evidence is never overwritten')
        sides = list(dict.fromkeys([subject.get('max_side', 1280) if subject else 1280, *arguments.max_sides]))
        if any(isinstance(side, bool) or not isinstance(side, int) or not 128 <= side <= 4096 for side in sides):
            raise ValueError('max-sides must be integers in [128, 4096]')
        with Image.open(source) as image:
            image.load()
            results = [extract_subject(image, {**subject, 'max_side': side} if subject else None) for side in sides]
            summary, disagreement = summarize_variants(results)
            destination.mkdir(parents=True)
            variants = []
            for side, result in zip(sides, results):
                artifacts = write_artifacts(image, result, destination / ('max-side-' + str(side) + '.mask.png'))
                variants.append({'max_side': side, 'metadata': result['metadata'], 'artifacts': artifacts})
            disagreement_path = destination / 'resolution-disagreement.png'
            disagreement.save(disagreement_path)
            original = Image.alpha_composite(Image.new('RGBA', image.size, (220, 220, 220, 255)), image.convert('RGBA')).convert('RGB')
            overlay = Image.composite(Image.blend(original, Image.new('RGB', image.size, (0, 220, 255)), 0.65), original, disagreement)
            overlay_path = destination / 'resolution-disagreement.overlay.png'
            overlay.save(overlay_path)
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise ValueError('Source bytes changed during the sensitivity run')
        if subject_bytes is not None and Path(arguments.subject_spec).read_bytes() != subject_bytes:
            raise ValueError('Subject specification changed during the sensitivity run')
        if implementation_hashes != {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in implementation_paths}:
            raise ValueError('Implementation changed during the sensitivity run')
        report = {'schema': 'reference-mask-stability/1', 'started_at_utc': started, 'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'source': str(source), 'source_sha256': source_hash, 'subject_spec_sha256': hashlib.sha256(subject_bytes).hexdigest() if subject_bytes is not None else None, 'implementation_sha256': implementation_hashes, 'numerical_variation': {'parameter': 'max_side', 'values': sides, 'target_bbox_strokes_ignore_unchanged': True}, **summary, 'variants': variants, 'artifacts': {'disagreement': str(disagreement_path), 'disagreement_sha256': hashlib.sha256(disagreement_path.read_bytes()).hexdigest(), 'overlay': str(overlay_path)}}
        (destination / 'stability.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: report[key] for key in ('source', 'disagreement_pixels', 'common_valid_pixels', 'semantic_verdict')}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'status': 'ERROR', 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
