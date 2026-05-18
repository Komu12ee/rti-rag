"""Convert each page of a PDF to a high-resolution image (450 DPI).

Uses PyMuPDF (fitz) which is a self-contained library — no external
poppler installation required, works cleanly on Windows / Colab / Linux.
"""

import fitz  # PyMuPDF
import numpy as np
from pathlib import Path

from .config import DPI


def pdf_to_images(pdf_path: str | Path) -> list[np.ndarray]:
    """Convert every page of a PDF to a list of BGR numpy arrays at 450 DPI.

    Parameters
    ----------
    pdf_path : path to the PDF file.

    Returns
    -------
    List of numpy arrays (H, W, 3) in BGR color order, one per page.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    zoom = DPI / 72  # PDF standard is 72 DPI
    matrix = fitz.Matrix(zoom, zoom)

    doc = fitz.open(str(pdf_path))
    images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        # Convert to numpy array — PyMuPDF gives RGB
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3
        )
        # Convert RGB → BGR for OpenCV compatibility
        img_bgr = img[:, :, ::-1].copy()
        images.append(img_bgr)

    doc.close()
    return images


def pdf_page_to_image(pdf_path: str | Path, page_num: int) -> np.ndarray:
    """Convert a single page of a PDF to a BGR numpy array at 450 DPI.

    Parameters
    ----------
    pdf_path : path to the PDF file.
    page_num : zero-indexed page number.

    Returns
    -------
    Numpy array (H, W, 3) in BGR color order.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    zoom = DPI / 72
    matrix = fitz.Matrix(zoom, zoom)

    doc = fitz.open(str(pdf_path))
    if page_num < 0 or page_num >= len(doc):
        doc.close()
        raise ValueError(
            f"Page {page_num} out of range. PDF has {len(doc)} pages."
        )

    page = doc[page_num]
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3
    )
    img_bgr = img[:, :, ::-1].copy()
    doc.close()
    return img_bgr


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count
