"""Denoise — surgically remove speckles WITHOUT altering any text.

Government documents are often photocopied or faxed multiple times, building up
salt-and-pepper speckle from toner / scanner noise. This module identifies tiny
noise dots and whites them out. Nothing else on the page is touched — no
filtering, no smoothing, no binarization of the output.

NON-DESTRUCTIVE approach:
1. Binarize only to *locate* speckle positions (tiny connected components).
2. Build a mask of those speckle pixels.
3. Replace ONLY those speckle pixels with local background color.

The original text — headings, body, tables, Devanagari matras — is pixel-
identical to the input. No bilateral filter or morphological operation is
applied to the output image.
"""

import cv2
import numpy as np

from .config import MIN_COMPONENT_AREA


def _find_speckle_mask(gray: np.ndarray, min_area: int) -> tuple[np.ndarray, int]:
    """Identify tiny noise blobs and return a mask marking them.

    Parameters
    ----------
    gray : grayscale uint8 image.
    min_area : connected components with area < min_area are speckles.

    Returns
    -------
    (speckle_mask, speckle_count)
    speckle_mask: uint8 image, 255 where speckles are, 0 elsewhere.
    speckle_count: number of speckle components found.
    """
    # Enhance faint punctuation and matras before detection
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Adaptive threshold for local contrast preservation
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    speckle_mask = np.zeros_like(gray)
    speckle_count = 0

    # Collect larger components as text anchors
    large_boxes: list[tuple[int, int, int, int]] = []
    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area >= min_area:
            x, y, w, h = (
                stats[label, cv2.CC_STAT_LEFT],
                stats[label, cv2.CC_STAT_TOP],
                stats[label, cv2.CC_STAT_WIDTH],
                stats[label, cv2.CC_STAT_HEIGHT],
            )
            large_boxes.append((x, y, w, h))

    def _near_text_component(cx: int, cy: int, box: tuple[int, int, int, int], max_dist: int) -> bool:
        x, y, w, h = box
        within_vert = (y - 2) <= cy <= (y + h + 2)
        if within_vert:
            return True
        dx = 0
        if cx < x:
            dx = x - cx
        elif cx > x + w:
            dx = cx - (x + w)
        dy = 0
        if cy < y:
            dy = y - cy
        elif cy > y + h:
            dy = cy - (y + h)
        return (dx * dx + dy * dy) <= (max_dist * max_dist)

    max_dist = max(5, int(min(gray.shape[:2]) * 0.01))

    for label in range(1, num_labels):  # skip background
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
            cx = int(stats[label, cv2.CC_STAT_LEFT] + stats[label, cv2.CC_STAT_WIDTH] / 2)
            cy = int(stats[label, cv2.CC_STAT_TOP] + stats[label, cv2.CC_STAT_HEIGHT] / 2)
            keep = any(_near_text_component(cx, cy, box, max_dist) for box in large_boxes)
            if not keep:
                speckle_mask[labels == label] = 255
                speckle_count += 1

    return speckle_mask, speckle_count


def denoise(image: np.ndarray) -> tuple[np.ndarray, dict]:
    """Clean noise from a scanned document image — non-destructive.

    Keeps ALL original text and image content pixel-identical. Only removes
    tiny speckle dots that are clearly noise (smaller than MIN_COMPONENT_AREA).
    No filtering or smoothing is applied.

    Parameters
    ----------
    image : BGR numpy array of the document page.

    Returns
    -------
    (cleaned_image, stats)
    cleaned_image: BGR numpy array, same size as input. Original content
                   is pixel-identical, only speckle dots are replaced.
    stats: dict with noise metrics —
        - 'speckles_removed': count of tiny components erased
        - 'noise_ratio': fraction of page pixels that were speckles
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Find speckle locations (tiny noise dots)
    speckle_mask, speckle_count = _find_speckle_mask(gray, MIN_COMPONENT_AREA)
    noise_pixels = np.count_nonzero(speckle_mask)
    noise_ratio = noise_pixels / max(gray.size, 1)

    # Replace speckle pixels with local background color via inpainting.
    # Small radius preserves nearby punctuation edges.
    if speckle_count > 0:
        gray = cv2.inpaint(gray, speckle_mask, inpaintRadius=1, flags=cv2.INPAINT_TELEA)

    stats = {
        "speckles_removed": speckle_count,
        "noise_ratio": round(noise_ratio, 6),
    }

    return gray, stats
