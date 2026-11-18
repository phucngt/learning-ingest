"""Trích chữ slide PDF theo trang (pypdf).

Trang có ít hơn MIN_TEXT_CHARS ký tự (không tính khoảng trắng) được đánh dấu
needs_ocr: thường là slide chỉ có hình / bản scan, cần người rà hoặc OCR sau.
MVP không tự OCR.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import IngestError

EXTRACTOR_VERSION = "pypdf-text-1"
MIN_TEXT_CHARS = 20


def _clean(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def extract_pdf(path: Path, source_id: str) -> dict:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover - pypdf là phụ thuộc bắt buộc
        raise IngestError("Thiếu pypdf: pip install -e .") from None
    if not Path(path).exists():
        raise IngestError(f"Không thấy slide {source_id}: {path}")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise IngestError(f"Slide {source_id} ({path}) bị khoá mật khẩu.") from None
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = _clean(page.extract_text() or "")
            except Exception as exc:   # một trang hỏng không làm hỏng cả file
                text, error = "", f"{type(exc).__name__}: {exc}"
            else:
                error = None
            chars = len(re.sub(r"\s", "", text))
            needs_ocr = chars < MIN_TEXT_CHARS
            pages.append({
                "source_id": source_id,
                "pdf_page": number,
                "text": text,
                "char_count": chars,
                "needs_ocr": needs_ocr,
                "note": (f"lỗi trích chữ: {error}" if error else
                         "không có lớp chữ" if chars == 0 else
                         "rất ít chữ, có thể là hình / scan" if needs_ocr else None),
            })
    except PdfReadError as exc:
        raise IngestError(f"Slide {source_id} ({path}) không đọc được: {exc}") from exc
    return {"source_id": source_id, "page_count": len(pages), "extractor": EXTRACTOR_VERSION, "pages": pages}
