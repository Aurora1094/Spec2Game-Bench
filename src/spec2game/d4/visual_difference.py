from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


VISUAL_DIFFERENCE_POLICY = "material_pixel_change_v1"
PIXEL_DELTA_THRESHOLD = 16
MIN_CHANGED_PIXEL_FRACTION = 0.01
MIN_CHANGED_PIXEL_FRACTION_WITH_SPAN = 0.001
MIN_DIFFERENCE_SPAN_FRACTION = 0.15


def analyze_visual_difference(
    first_path: str | Path,
    second_path: str | Path,
) -> dict[str, Any]:
    """Measure whether two rendered frames differ enough for separate questions."""
    first = Path(first_path)
    second = Path(second_path)
    try:
        with Image.open(first) as first_image, Image.open(second) as second_image:
            left = first_image.convert("RGB")
            right = second_image.convert("RGB")
    except Exception as exc:
        return {
            "policy": VISUAL_DIFFERENCE_POLICY,
            "materially_different": False,
            "reason": "image_decode_failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    if left.size != right.size:
        return {
            "policy": VISUAL_DIFFERENCE_POLICY,
            "materially_different": True,
            "reason": "frame_dimensions_changed",
            "first_size": list(left.size),
            "second_size": list(right.size),
            "changed_pixel_fraction": 1.0,
            "difference_span_fraction": 1.0,
            "difference_bbox_area_fraction": 1.0,
        }

    difference = ImageChops.difference(left, right)
    strongest_channel = difference.getchannel("R")
    strongest_channel = ImageChops.lighter(
        strongest_channel, difference.getchannel("G")
    )
    strongest_channel = ImageChops.lighter(
        strongest_channel, difference.getchannel("B")
    )
    mask = strongest_channel.point(
        lambda value: 255 if value >= PIXEL_DELTA_THRESHOLD else 0
    )
    histogram = mask.histogram()
    changed_pixel_count = int(histogram[255])
    width, height = left.size
    total_pixels = max(1, width * height)
    changed_fraction = changed_pixel_count / total_pixels
    bbox = mask.getbbox()
    if bbox is None:
        span_fraction = 0.0
        bbox_area_fraction = 0.0
        bbox_value = None
    else:
        bbox_width = bbox[2] - bbox[0]
        bbox_height = bbox[3] - bbox[1]
        span_fraction = max(bbox_width / width, bbox_height / height)
        bbox_area_fraction = (bbox_width * bbox_height) / total_pixels
        bbox_value = list(bbox)

    materially_different = changed_fraction >= MIN_CHANGED_PIXEL_FRACTION or (
        changed_fraction >= MIN_CHANGED_PIXEL_FRACTION_WITH_SPAN
        and span_fraction >= MIN_DIFFERENCE_SPAN_FRACTION
    )
    return {
        "policy": VISUAL_DIFFERENCE_POLICY,
        "materially_different": materially_different,
        "reason": (
            "material_change_threshold_met"
            if materially_different
            else "near_duplicate_below_material_threshold"
        ),
        "pixel_delta_threshold": PIXEL_DELTA_THRESHOLD,
        "changed_pixel_count": changed_pixel_count,
        "changed_pixel_fraction": round(changed_fraction, 8),
        "difference_span_fraction": round(span_fraction, 8),
        "difference_bbox_area_fraction": round(bbox_area_fraction, 8),
        "difference_bbox": bbox_value,
        "thresholds": {
            "min_changed_pixel_fraction": MIN_CHANGED_PIXEL_FRACTION,
            "min_changed_pixel_fraction_with_span": (
                MIN_CHANGED_PIXEL_FRACTION_WITH_SPAN
            ),
            "min_difference_span_fraction": MIN_DIFFERENCE_SPAN_FRACTION,
        },
    }


def select_materially_distinct_frames(
    frames: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Greedily retain frames that are materially different from every retained one."""
    selected: list[dict[str, Any]] = []
    for frame in frames:
        path = frame.get("path")
        if not isinstance(path, str) or not Path(path).is_file():
            continue
        if not selected or all(
            analyze_visual_difference(existing["path"], path)[
                "materially_different"
            ]
            for existing in selected
        ):
            selected.append(frame)
    return selected


__all__ = [
    "MIN_CHANGED_PIXEL_FRACTION",
    "MIN_CHANGED_PIXEL_FRACTION_WITH_SPAN",
    "MIN_DIFFERENCE_SPAN_FRACTION",
    "PIXEL_DELTA_THRESHOLD",
    "VISUAL_DIFFERENCE_POLICY",
    "analyze_visual_difference",
    "select_materially_distinct_frames",
]
