"""Stamp and Handwritten Annotation Detector.

Most government documents carry rubber stamps (red, blue, purple ink) and
handwritten notes / signatures. These cannot be reliably OCR'd but should be:
1. Detected and located (bounding boxes).
2. Flagged in metadata so downstream stages know they exist.
3. Optionally masked out so the OCR engine doesn't try to read them.

Detection strategy — color-based in HSV space:
- Government stamps are almost always red, blue, or purple ink on white paper.
- Convert to HSV and threshold for each stamp color range.
- Find contours of colored regions, filter by area.
- Handwritten annotations in blue/black ink overlap with stamp colors, so we
  also use shape analysis: stamps tend to be circular/rectangular with a
  specific aspect ratio, while handwriting is more irregular.
"""

import cv2
import numpy as np
from dataclasses import dataclass, field

from .config import STAMP_COLOR_RANGES, STAMP_MIN_AREA_RATIO, STAMP_MAX_AREA_RATIO


@dataclass
class StampRegion:
    """A detected stamp or annotation region."""

    x: int
    y: int
    w: int
    h: int
    color_name: str
    area_ratio: float  # fraction of page area
    is_circular: bool  # likely a round rubber stamp
    confidence: float  # 0-1, how confident we are this is a stamp


@dataclass
class StampDetectionResult:
    """Full result from stamp detection on one page."""

    has_stamps: bool = False
    has_handwriting: bool = False
    regions: list[StampRegion] = field(default_factory=list)
    mask: np.ndarray | None = None  # Binary mask: 255 = stamp region


def _circularity(contour) -> float:
    """Compute circularity of a contour (1.0 = perfect circle)."""
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if perimeter == 0:
        return 0.0
    return 4 * np.pi * area / (perimeter * perimeter)


def detect_stamps(image: np.ndarray) -> StampDetectionResult:
    """Detect stamps and handwritten annotations on a document page.

    Parameters
    ----------
    image : BGR numpy array of the page.

    Returns
    -------
    StampDetectionResult with regions, flags, and optional mask.
    """
    h, w = image.shape[:2]
    page_area = h * w
    min_area = int(page_area * STAMP_MIN_AREA_RATIO)
    max_area = int(page_area * STAMP_MAX_AREA_RATIO)

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    combined_mask = np.zeros((h, w), dtype=np.uint8)
    regions: list[StampRegion] = []

    for color_name, lower, upper in STAMP_COLOR_RANGES:
        lower_np = np.array(lower, dtype=np.uint8)
        upper_np = np.array(upper, dtype=np.uint8)
        color_mask = cv2.inRange(hsv, lower_np, upper_np)

        # Morphological close to fill gaps within stamp impressions
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue

            bx, by, bw, bh = cv2.boundingRect(cnt)
            circ = _circularity(cnt)
            is_circular = circ > 0.5
            area_ratio = area / page_area

            # Confidence heuristic:
            # High if circular (rubber stamps), medium for rectangular blocks
            confidence = 0.6
            if is_circular:
                confidence = 0.85
            if area_ratio > 0.01:
                confidence += 0.1  # larger colored regions are very likely stamps
            confidence = min(confidence, 1.0)

            regions.append(
                StampRegion(
                    x=bx, y=by, w=bw, h=bh,
                    color_name=color_name,
                    area_ratio=round(area_ratio, 5),
                    is_circular=is_circular,
                    confidence=round(confidence, 2),
                )
            )

            # Add to combined mask
            cv2.drawContours(combined_mask, [cnt], -1, 255, -1)

    # Detect possible handwritten annotations:
    # Look for thin, irregular strokes in blue/black that aren't stamps.
    # We use the blue mask but look for elongated, non-circular regions.
    has_handwriting = False
    for region in regions:
        if not region.is_circular and region.area_ratio < 0.005:
            has_handwriting = True
            break

    result = StampDetectionResult(
        has_stamps=len(regions) > 0,
        has_handwriting=has_handwriting,
        regions=regions,
        mask=combined_mask if len(regions) > 0 else None,
    )

    return result


def mask_stamps(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Replace stamp regions with white, so OCR ignores them.

    Parameters
    ----------
    image : BGR numpy array.
    mask : binary mask from StampDetectionResult (255 = stamp).

    Returns
    -------
    Image with stamp regions replaced by white.
    """
    result = image.copy()
    result[mask == 255] = 255
    return result
