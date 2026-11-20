"""Trích chữ slide PDF theo trang (pypdf).

Trang có ít hơn MIN_TEXT_CHARS ký tự (không tính khoảng trắng) được đánh dấu
needs_ocr: thường là slide chỉ có hình / bản scan, cần người rà hoặc OCR sau.
Có thể bổ sung chữ từ Markdown OCR có sẵn.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import IngestError, MissingDependency
from .syllabus import DEFAULT_PAGE_MARKERS
from .util import sha256_bytes

EXTRACTOR_VERSION = "pypdf-text-1"
MIN_TEXT_CHARS = 20
_OCR_MARKERS = [re.compile(pattern, re.IGNORECASE) for pattern in DEFAULT_PAGE_MARKERS]


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


def read_slide_ocr(path: Path, source_id: str, page_count: int) -> tuple[dict[int, str], str]:
    """Đọc chữ OCR theo số trang và tính hash từ cùng nội dung file."""
    label = f"Slide {source_id}, OCR {path.name}"
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except FileNotFoundError:
        raise IngestError(f"{label}: không thấy file.") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise IngestError(f"{label}: không đọc được file ({exc}).") from exc

    chunks: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in text.split("\n"):
        matches = sorted((m for marker in _OCR_MARKERS for m in marker.finditer(line)),
                         key=lambda m: m.start())
        start = 0
        for match in matches:
            if current is not None:
                current.append(line[start:match.start()])
            try:
                number = int(match.group(1))
            except ValueError:
                raise IngestError(f"{label}: số tại mốc trang vượt phạm vi 1–{page_count}.") from None
            if not 1 <= number <= page_count:
                raise IngestError(f"{label}: mốc trang {number} ngoài phạm vi 1–{page_count}.")
            if number in chunks:
                raise IngestError(f"{label}: trùng mốc trang {number}.")
            current = chunks[number] = []
            start = match.end()
        if current is not None:
            current.append(line[start:])
    if not chunks:
        raise IngestError(f"{label}: không có mốc trang.")
    return {number: _clean("\n".join(lines)) for number, lines in chunks.items()}, sha256_bytes(raw)


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


PPTX_EXTRACTOR_VERSION = "python-pptx-text-1"


def extract_pptx(path: Path, source_id: str) -> dict:
    """Slide PowerPoint -> cùng hình dạng với extract_pdf (mỗi slide một "trang")."""
    try:
        import pptx
        from pptx.shapes.group import GroupShape
    except ImportError:
        raise MissingDependency(
            "Chưa cài python-pptx/python-docx. Cài: pip install -e \".[office]\"") from None
    if not Path(path).exists():
        raise IngestError(f"Không thấy slide {source_id}: {path}")
    try:
        prs = pptx.Presentation(str(path))
    except Exception as exc:
        raise IngestError(f"Slide {source_id} ({path}) không đọc được: {type(exc).__name__}: {exc}") from exc

    def position(shape):
        return (shape.top or 0, shape.left or 0)

    def shape_lines(shapes, skip_id) -> list[str]:
        lines: list[str] = []
        for shape in sorted(shapes, key=position):
            if shape.shape_id == skip_id and skip_id is not None:
                continue
            if isinstance(shape, GroupShape):
                lines += shape_lines(shape.shapes, None)
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells, seen = [], set()
                    for cell in row.cells:
                        if id(cell._tc) in seen:
                            continue
                        seen.add(id(cell._tc))
                        text = " ".join(cell.text.split())
                        if text:
                            cells.append(text)
                    if cells:
                        lines.append(" | ".join(cells))
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                lines.append(shape.text_frame.text)
        return lines

    pages = []
    for number, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        parts = []
        if title_shape is not None and title_shape.has_text_frame and title_shape.text_frame.text.strip():
            parts.append(title_shape.text_frame.text)
        parts += shape_lines(slide.shapes, title_shape.shape_id if title_shape is not None else None)
        body_chars = len(re.sub(r"\s", "", _clean("\n".join(parts))))   # chưa tính ghi chú người trình bày
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = " ".join(slide.notes_slide.notes_text_frame.text.split())
            if notes:
                parts.append(f"Ghi chú: {notes}")
        text = _clean("\n".join(parts))
        chars = body_chars
        needs_ocr = chars < MIN_TEXT_CHARS
        hidden = slide._element.get("show") == "0"
        note = ("slide chỉ có hình" if chars == 0 else
                "rất ít chữ, có thể là hình" if needs_ocr else None)
        if hidden:
            note = "slide ẩn" if note is None else f"slide ẩn; {note}"
        pages.append({"source_id": source_id, "pdf_page": number, "text": text, "char_count": chars,
                      "needs_ocr": needs_ocr, "note": note})
    return {"source_id": source_id, "page_count": len(pages), "extractor": PPTX_EXTRACTOR_VERSION, "pages": pages}
