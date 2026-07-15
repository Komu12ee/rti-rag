from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin

import fitz
from bs4 import BeautifulSoup

from .config import Section4Config
from .schemas import DocumentPage, RetrievedDocument


class ExtractionError(RuntimeError):
    """A downloaded, approved document could not be safely converted to text."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DownloadedPayload:
    requested_url: str
    final_url: str
    domain: str
    status_code: int
    content_type: str
    content: bytes
    retrieved_at: str
    headers: Mapping[str, str] = field(default_factory=dict)


_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b"),
    re.compile(r"\b([0-3]?\d)[-/.]([01]?\d)[-/.](20\d{2})\b"),
)


def _decode_html(content: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", content_type, re.I)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(("utf-8", "utf-16", "windows-1252"))
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def _normalise_space(value: str) -> str:
    return re.sub(r"[\t\f\v ]+", " ", re.sub(r"\r\n?", "\n", value or "")).strip()


def _publication_date(soup: BeautifulSoup, text: str) -> str | None:
    meta_names = {
        "date",
        "article:published_time",
        "datepublished",
        "dc.date",
        "dcterms.date",
        "last-modified",
    }
    candidates: list[str] = []
    for node in soup.find_all("meta"):
        key = str(node.get("property") or node.get("name") or "").casefold()
        if key in meta_names:
            candidates.append(str(node.get("content") or ""))
    candidates.extend(node.get_text(" ", strip=True) for node in soup.find_all("time"))
    candidates.append(text[:3000])

    for candidate in candidates:
        raw = candidate.strip()
        if not raw:
            continue
        iso = re.search(r"\b(20\d{2}-[01]\d-[0-3]\d)", raw)
        if iso:
            return iso.group(1)
        for index, pattern in enumerate(_DATE_PATTERNS):
            match = pattern.search(raw)
            if not match:
                continue
            if index == 0:
                year, month, day = match.groups()
            else:
                day, month, year = match.groups()
            try:
                return datetime(int(year), int(month), int(day)).date().isoformat()
            except ValueError:
                continue
    return None


def extract_links(payload: DownloadedPayload) -> list[tuple[str, str]]:
    """Extract public link candidates without running page JavaScript."""
    markup = _decode_html(payload.content, payload.content_type)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    if payload.content_type in {"application/xml", "text/xml"}:
        for value in re.findall(r"<loc\b[^>]*>(.*?)</loc>", markup, flags=re.I | re.S):
            url = re.sub(r"\s+", "", BeautifulSoup(value, "html.parser").get_text())
            if url and url not in seen:
                seen.add(url)
                links.append((url.rsplit("/", 1)[-1], url))
        return links

    soup = BeautifulSoup(markup, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        url = urljoin(payload.final_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = _normalise_space(anchor.get_text(" ", strip=True))[:300]
        links.append((title or url.rsplit("/", 1)[-1], url))

    # The legacy CHiPS procurement portal uses a same-origin meta refresh.
    for meta in soup.find_all("meta"):
        if str(meta.get("http-equiv") or "").casefold() != "refresh":
            continue
        content = str(meta.get("content") or "")
        match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", content, re.I)
        if match:
            url = urljoin(payload.final_url, match.group(1).strip())
            if url not in seen:
                seen.add(url)
                links.append(("redirect target", url))
    return links


def _extract_html(payload: DownloadedPayload, source_id: str) -> RetrievedDocument:
    markup = _decode_html(payload.content, payload.content_type)
    soup = BeautifulSoup(markup, "html.parser")
    title = _normalise_space(soup.title.get_text(" ", strip=True) if soup.title else "")
    for node in soup.find_all(
        ["script", "style", "noscript", "template", "svg", "canvas", "nav", "header", "footer", "aside", "form"]
    ):
        node.decompose()

    headings = tuple(
        dict.fromkeys(
            _normalise_space(node.get_text(" ", strip=True))[:240]
            for node in soup.find_all(["h1", "h2", "h3", "h4"])
            if _normalise_space(node.get_text(" ", strip=True))
        )
    )[:60]
    lines: list[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th"]):
        value = _normalise_space(node.get_text(" ", strip=True))
        if value and (not lines or lines[-1] != value):
            lines.append(value)
    text = "\n".join(lines)
    max_chars = max(10_000, int(os.getenv("SECTION4_MAX_EXTRACTED_CHARS", "500000")))
    text = text[:max_chars].strip()
    if not text:
        raise ExtractionError("EMPTY_EXTRACTION", "The approved HTML page contained no usable public text.")
    access_probe = _normalise_space(f"{title}\n{text[:6000]}").casefold()
    if len(text) < 2000 and any(
        marker in access_probe
        for marker in ("captcha", "enter captcha", "security code", "कैप्चा")
    ):
        raise ExtractionError("CAPTCHA_REQUIRED", "The public page requires CAPTCHA and was not bypassed.")
    if len(text) < 1200 and any(
        marker in access_probe
        for marker in ("javascript is required", "enable javascript", "javascript has been disabled")
    ):
        raise ExtractionError("JAVASCRIPT_REQUIRED", "The public page requires browser rendering.")
    if len(text) < 1200 and any(
        marker in access_probe for marker in ("sign in", "log in", "login required", "user login")
    ):
        raise ExtractionError("AUTHENTICATION_REQUIRED", "The page is not publicly accessible without login.")

    return RetrievedDocument(
        source_id=source_id,
        title=title or payload.final_url,
        url=payload.requested_url,
        final_url=payload.final_url,
        domain=payload.domain,
        source_type="html",
        publication_date=_publication_date(soup, text),
        retrieved_at=payload.retrieved_at,
        content_type=payload.content_type,
        document_hash=hashlib.sha256(payload.content).hexdigest(),
        pages=(DocumentPage(page_number=1, text=text, section_headings=headings),),
        http_status=payload.status_code,
        byte_count=len(payload.content),
        etag=payload.headers.get("etag"),
        last_modified=payload.headers.get("last-modified"),
        extraction_method="beautifulsoup_html",
    )


def _existing_ocr_pages(document: fitz.Document, page_indexes: list[int]) -> tuple[dict[int, str], list[str]]:
    if not page_indexes:
        return {}, []
    maximum = max(0, int(os.getenv("SECTION4_MAX_OCR_PAGES", "20")))
    selected = page_indexes[:maximum]
    warnings: list[str] = []
    if len(page_indexes) > maximum:
        warnings.append("OCR_PAGE_LIMIT_REACHED")
    if not selected:
        return {}, warnings

    preprocessing_dir = Path(__file__).resolve().parents[3] / "01_preprocessing"
    if not preprocessing_dir.is_dir():
        return {}, [*warnings, "OCR_PIPELINE_NOT_FOUND"]
    path_value = str(preprocessing_dir)
    if path_value not in sys.path:
        sys.path.insert(0, path_value)

    try:
        from stage2_ocr import OCRPipeline
        from stage2_ocr.postprocess import postprocess_page_text
    except Exception:
        return {}, [*warnings, "OCR_PIPELINE_IMPORT_FAILED"]

    output: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="section4_ocr_") as temporary:
        temp_dir = Path(temporary)
        try:
            pipeline = OCRPipeline(output_dir=temp_dir, ocr_model=os.getenv("OCR_MODEL", "ollama"))
        except Exception:
            return {}, [*warnings, "OCR_PROVIDER_UNAVAILABLE"]

        for page_index in selected:
            image_path = temp_dir / f"page_{page_index + 1:04d}.png"
            try:
                page = document[page_index]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                pixmap.save(image_path)
                result = pipeline.process_single_image(image_path, page_index)
                value = postprocess_page_text(str(result.raw_text or "")).strip()
                if value:
                    output[page_index] = value
                else:
                    warnings.append(f"OCR_EMPTY_PAGE_{page_index + 1}")
            except Exception:
                warnings.append(f"OCR_FAILED_PAGE_{page_index + 1}")
    return output, warnings


def _extract_pdf(payload: DownloadedPayload, source_id: str, config: Section4Config) -> RetrievedDocument:
    if not payload.content.startswith(b"%PDF-"):
        raise ExtractionError("INVALID_PDF_SIGNATURE", "The approved response was not a valid PDF file.")
    try:
        document = fitz.open(stream=payload.content, filetype="pdf")
    except Exception as error:
        raise ExtractionError("CORRUPT_PDF", "The approved PDF could not be opened safely.") from error

    maximum_pages = max(1, int(os.getenv("SECTION4_MAX_PDF_PAGES", "500")))
    if document.page_count > maximum_pages:
        document.close()
        raise ExtractionError("PDF_PAGE_LIMIT", "The approved PDF exceeds the configured page limit.")

    direct: dict[int, str] = {}
    scanned_indexes: list[int] = []
    metadata = dict(document.metadata or {})
    for index in range(document.page_count):
        value = _normalise_space(document[index].get_text("text") or "")
        direct[index] = value
        if len(value) < 24:
            scanned_indexes.append(index)

    ocr_text: dict[int, str] = {}
    warnings: list[str] = []
    if scanned_indexes:
        if config.ocr_enabled:
            ocr_text, warnings = _existing_ocr_pages(document, scanned_indexes)
        else:
            warnings.append("SCANNED_PAGES_OCR_DISABLED")

    pages = tuple(
        DocumentPage(
            page_number=index + 1,
            text=(ocr_text.get(index) or direct[index]).strip(),
            ocr_used=index in ocr_text,
        )
        for index in range(document.page_count)
        if (ocr_text.get(index) or direct[index]).strip()
    )
    document.close()
    if not pages:
        raise ExtractionError("EMPTY_PDF_EXTRACTION", "No readable text could be extracted from the approved PDF.")

    publication_date = None
    raw_date = str(metadata.get("creationDate") or metadata.get("modDate") or "")
    match = re.search(r"D:(20\d{2})(\d{2})(\d{2})", raw_date)
    if match:
        try:
            publication_date = datetime(*(int(value) for value in match.groups())).date().isoformat()
        except ValueError:
            publication_date = None

    return RetrievedDocument(
        source_id=source_id,
        title=_normalise_space(str(metadata.get("title") or "")) or payload.final_url.rsplit("/", 1)[-1],
        url=payload.requested_url,
        final_url=payload.final_url,
        domain=payload.domain,
        source_type="pdf",
        publication_date=publication_date,
        retrieved_at=payload.retrieved_at,
        content_type=payload.content_type,
        document_hash=hashlib.sha256(payload.content).hexdigest(),
        pages=pages,
        http_status=payload.status_code,
        byte_count=len(payload.content),
        etag=payload.headers.get("etag"),
        last_modified=payload.headers.get("last-modified"),
        extraction_method="pymupdf+existing_ocr" if ocr_text else "pymupdf_text",
        warnings=tuple(dict.fromkeys(warnings)),
    )


def extract_document(
    payload: DownloadedPayload,
    source_id: str,
    config: Section4Config,
) -> RetrievedDocument:
    if payload.content_type == "application/pdf":
        return _extract_pdf(payload, source_id, config)
    if payload.content_type in {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}:
        return _extract_html(payload, source_id)
    raise ExtractionError("UNSUPPORTED_MIME", "The approved response type is not extractable.")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
