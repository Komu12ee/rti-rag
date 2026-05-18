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
    # Binarize — used ONLY for detection, not reconstruction
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    speckle_mask = np.zeros_like(gray)
    speckle_count = 0

    for label in range(1, num_labels):  # skip background
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
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
    result = image.copy()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Find speckle locations (tiny noise dots)
    speckle_mask, speckle_count = _find_speckle_mask(gray, MIN_COMPONENT_AREA)
    noise_pixels = np.count_nonzero(speckle_mask)
    noise_ratio = noise_pixels / max(gray.size, 1)

    # Replace speckle pixels with local background color via inpainting.
    # This fills each speckle dot with the surrounding background so there's
    # no harsh white spot on tinted or off-white paper.
    if speckle_count > 0:
        result = cv2.inpaint(result, speckle_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

    stats = {
        "speckles_removed": speckle_count,
        "noise_ratio": round(noise_ratio, 6),
    }

    return result, stats
