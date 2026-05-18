"""Deskew — straighten pages scanned at a slight angle.

Even 2-3° of tilt causes OCR to misread Devanagari characters. This module
detects the dominant text-line angle and rotates the image to correct it.

Approach:
1. Convert to grayscale → binary (Otsu threshold).
2. Detect long horizontal edges via morphological closing with a wide kernel.
3. Find contours of those edge blobs, fit minimum-area bounding rectangles.
4. Collect the angles of those rectangles — the median is the skew angle.
5. Rotate the image by the negative of that angle to straighten it.

Falls back gracefully: if no reliable angle is found, returns the image unchanged.
"""

import cv2
import numpy as np

from .config import MAX_SKEW_ANGLE, MIN_SKEW_ANGLE


def estimate_skew_angle(image: np.ndarray) -> float:
    """Estimate the skew angle of a document image in degrees.

    Parameters
    ----------
    image : BGR or grayscale numpy array.

    Returns
    -------
    Skew angle in degrees. Positive = counter-clockwise tilt.
    Returns 0.0 if no reliable angle can be determined.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Binary inversion — text becomes white on black background
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morphological closing with a wide horizontal kernel to connect text into
    # long horizontal blobs. Kernel width relative to image width.
    kernel_width = max(image.shape[1] // 20, 30)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return 0.0

    angles = []
    for cnt in contours:
        if len(cnt) < 5:
            continue
        rect = cv2.minAreaRect(cnt)
        w, h = rect[1]
        # Only use elongated rectangles (likely text lines)
        if min(w, h) == 0:
            continue
        aspect = max(w, h) / min(w, h)
        if aspect < 3:
            continue

        angle = rect[2]
        # OpenCV minAreaRect returns angles in [-90, 0). Normalize:
        # If the rectangle is wider than tall, angle is fine.
        # If taller than wide, add 90.
        if w < h:
            angle = angle + 90

        # Normalize to [-45, 45) range
        if angle > 45:
            angle -= 90
        if angle < -45:
            angle += 90

        angles.append(angle)

    if not angles:
        return 0.0

    median_angle = float(np.median(angles))

    # Sanity check
    if abs(median_angle) > MAX_SKEW_ANGLE:
        return 0.0
    if abs(median_angle) < MIN_SKEW_ANGLE:
        return 0.0

    return median_angle


def deskew(image: np.ndarray) -> tuple[np.ndarray, float]:
    """Straighten a tilted document image.

    Parameters
    ----------
    image : BGR numpy array.

    Returns
    -------
    (corrected_image, skew_angle_degrees)
    If no correction was needed, returns (original_image, 0.0).
    """
    angle = estimate_skew_angle(image)

    if angle == 0.0:
        return image, 0.0

    h, w = image.shape[:2]
    center = (w // 2, h // 2)

    # Rotate to correct the skew. Use white border fill (typical document bg).
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    corrected = cv2.warpAffine(
        image,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    return corrected, angle
