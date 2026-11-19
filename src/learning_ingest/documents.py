"""Trích chữ văn bản Word (.docx) theo mục (python-docx).

Mục mở ra ở mỗi đoạn có style Title (cấp 0) hoặc Heading N (cấp N). Văn bản
không dùng style tiêu đề nào (hay gặp ở file Word thật chỉ có Normal / List
Paragraph) thì coi đoạn ngắn in đậm toàn bộ là tiêu đề cấp 1; các đoạn đậm liền
nhau (tiêu đề xuống dòng) gộp thành một. Chế độ dùng được ghi ở heading_mode:
"styles" | "bold" | "none". Phần chữ trước tiêu đề đầu tiên thành mục
"(Mở đầu)". Bảng được đọc theo dòng, các ô nối bằng " | ", đúng thứ tự xuất
hiện trong văn bản; khối nội dung điều khiển (w:sdt) được đi vào trong, trừ mục
lục tự động của Word. Mã mục ổn định: sec-<số thứ tự>-<slug tiêu đề>.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import IngestError, MissingDependency
from .slides import _clean
from .util import slugify

DOCX_EXTRACTOR_VERSION = "python-docx-text-2"
PREAMBLE_HEADING = "(Mở đầu)"
BOLD_HEADING_MAX_CHARS = 150
_HEADING_STYLE = re.compile(r"^heading\s*(\d+)$", re.IGNORECASE)


def import_docx():
    try:
        import docx
    except ImportError:
        raise MissingDependency(
            "Chưa cài python-pptx/python-docx. Cài: pip install -e \".[office]\"") from None
    return docx


def _heading_level(paragraph) -> int | None:
    try:
        style = paragraph.style
        name = (style.name if style is not None else "") or ""
    except Exception:
        return None
    if name.strip().lower() == "title":
        return 0
    m = _HEADING_STYLE.match(name.strip())
    return int(m.group(1)) if m else None


def _is_bold_heading(paragraph, text: str) -> bool:
    if not text or len(text) > BOLD_HEADING_MAX_CHARS:
        return False
    try:
        style_bold = bool(paragraph.style is not None and paragraph.style.font.bold)
    except Exception:
        style_bold = False
    runs = [r for r in paragraph.runs if r.text.strip()]
    if not runs:
        return False
    return all((r.bold if r.bold is not None else style_bold) for r in runs)


def _table_lines(table) -> list[str]:
    lines = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if id(cell._tc) in seen:        # ô gộp lặp lại cùng một ô
                continue
            seen.add(id(cell._tc))
            text = " ".join(cell.text.split())
            if text:
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _is_toc_sdt(sdt) -> bool:
    from docx.oxml.ns import qn
    pr = sdt.find(qn("w:sdtPr"))
    if pr is None:
        return False
    for gallery in pr.iter(qn("w:docPartGallery")):
        if (gallery.get(qn("w:val")) or "").strip().lower() == "table of contents":
            return True
    return False


def _blocks(parent, document):
    """Đoạn và bảng theo thứ tự văn bản, đi vào w:sdt (trừ mục lục Word)."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in parent.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield "p", Paragraph(child, document)
        elif tag == "tbl":
            yield "tbl", Table(child, document)
        elif tag == "sdt" and not _is_toc_sdt(child):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _blocks(content, document)


def extract_docx(path: Path, source_id: str) -> dict:
    docx = import_docx()
    if not Path(path).exists():
        raise IngestError(f"Không thấy văn bản {source_id}: {path}")
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise IngestError(f"Văn bản {source_id} ({path}) không đọc được: {type(exc).__name__}: {exc}") from exc

    blocks = list(_blocks(document.element.body, document))
    texts = {id(obj): " ".join(obj.text.split()) for kind, obj in blocks if kind == "p"}
    if any(kind == "p" and texts[id(obj)] and _heading_level(obj) is not None for kind, obj in blocks):
        mode = "styles"
    elif any(kind == "p" and _is_bold_heading(obj, texts[id(obj)]) for kind, obj in blocks):
        mode = "bold"
    else:
        mode = "none"

    raw: list[dict] = []
    current = {"heading": PREAMBLE_HEADING, "level": 0, "lines": [], "opened_by_heading": False}
    last_was_heading = False
    for kind, obj in blocks:
        if kind == "tbl":
            current["lines"].extend(_table_lines(obj))
            last_was_heading = False
            continue
        text = texts[id(obj)]
        if not text:
            continue
        if mode == "styles":
            level = _heading_level(obj)
        elif mode == "bold":
            level = 1 if _is_bold_heading(obj, text) else None
        else:
            level = None
        if level is None:
            current["lines"].append(text)
            last_was_heading = False
        elif mode == "bold" and last_was_heading:     # tiêu đề xuống dòng: gộp
            current["heading"] += " " + text
        else:
            raw.append(current)
            current = {"heading": text, "level": level, "lines": [], "opened_by_heading": True}
            last_was_heading = True
    raw.append(current)

    sections = []
    for sec in raw:
        text = _clean("\n".join(sec["lines"]))
        if not sec["opened_by_heading"] and not text:
            continue                        # không có phần mở đầu
        sections.append({"heading": sec["heading"], "level": sec["level"], "text": text})
    if not any(s["text"] for s in sections):
        raise IngestError(f"Văn bản {source_id} ({path}) rỗng: không có chữ nào.")
    out = []
    for i, sec in enumerate(sections, start=1):
        out.append({
            "source_id": source_id,
            "section_id": f"sec-{i:03d}-{slugify(sec['heading'])[:40].rstrip('-') or 'x'}",
            "heading": sec["heading"],
            "level": sec["level"],
            "text": sec["text"],
            "char_count": len(re.sub(r"\s", "", sec["text"])),
        })
    return {"source_id": source_id, "extractor": DOCX_EXTRACTOR_VERSION, "heading_mode": mode,
            "section_count": len(out), "sections": out}
