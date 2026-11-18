"""Giáo trình Markdown có YAML front matter -> chương, mục, mốc trang PDF.

Chương lấy ID từ đâu (theo thứ tự):
  1. front matter `chapters:` - mỗi mục có chapter_id (hoặc id), title, tuỳ
     chọn heading (chữ của tiêu đề trong bài), pdf_page_start / pdf_page_end.
     Tiêu đề trong bài khớp heading/title, hoặc mang thuộc tính {#chapter_id},
     thì mở chương đó.
  2. Không có `chapters:` trong front matter: tiêu đề bắt đầu bằng
     "Chương / Chapter / Phần" và có thuộc tính {#id} -> chương mang id đó.
Không có ID rõ ràng thì chương không có ID: công cụ không tự đặt mã chương,
và không bao giờ suy chương từ số buổi học.

Mốc trang PDF: dòng chứa <!-- page: N -->, <!-- pdf_page: N --> hoặc
<!-- trang N --> (hoặc manifest syllabus.page_marker_pattern). Trong nội dung
gửi AI, mốc được thay bằng "[trang N]" để AI trích đúng trang.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .errors import IngestError
from .util import norm_text, slugify

DEFAULT_PAGE_MARKER = r"<!--\s*(?:pdf[_-]?page|page|trang)\s*[:=]?\s*(\d+)\s*-->"
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([A-Za-z0-9._:-]+)\})?\s*#*\s*$")
_CHAPTER_WORD = re.compile(r"^(chương|chuong|chapter|phần|phan)\b", re.IGNORECASE)
_FENCE = re.compile(r"^\s*(```|~~~)")


def split_front_matter(text: str) -> tuple[dict, str]:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = re.search(r"^(---|\.\.\.)\s*$", text[4:], re.MULTILINE)
    if not end:
        raise IngestError("Giáo trình: front matter mở bằng '---' nhưng không có dòng đóng.")
    raw = text[4:4 + end.start()]
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise IngestError(f"Giáo trình: front matter không đọc được: {exc}") from exc
    if not isinstance(data, dict):
        raise IngestError("Giáo trình: front matter phải là một object.")
    return data, text[4 + end.end():].lstrip("\n")


def _fm_chapters(fm: dict) -> list[dict]:
    out = []
    for i, item in enumerate(fm.get("chapters") or []):
        if not isinstance(item, dict):
            raise IngestError(f"Giáo trình: chapters[{i}] phải là object.")
        cid = item.get("chapter_id") or item.get("id")
        if not cid:
            raise IngestError(f"Giáo trình: chapters[{i}] thiếu chapter_id.")
        start = item.get("pdf_page_start", item.get("page_start"))
        end = item.get("pdf_page_end", item.get("page_end"))
        out.append({
            "chapter_id": str(cid),
            "title": str(item.get("title") or item.get("name") or cid),
            "heading": item.get("heading"),
            "pdf_page_start": int(start) if start is not None else None,
            "pdf_page_end": int(end) if end is not None else None,
        })
    ids = [c["chapter_id"] for c in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise IngestError(f"Giáo trình: chapter_id trùng trong front matter: {', '.join(dupes)}")
    return out


def parse_syllabus(path: Path, source_id: str, page_marker_pattern: str | None = None) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise IngestError(f"Không thấy giáo trình: {path}") from None
    fm, body = split_front_matter(text)
    chapters = _fm_chapters(fm)
    by_id = {c["chapter_id"]: c for c in chapters}
    by_heading = {}
    for c in chapters:
        for label in (c["heading"], c["title"]):
            if label:
                by_heading.setdefault(norm_text(str(label)), c["chapter_id"])

    try:
        marker = re.compile(page_marker_pattern or DEFAULT_PAGE_MARKER, re.IGNORECASE)
    except re.error as exc:
        raise IngestError(f"syllabus.page_marker_pattern sai regex: {exc}") from exc
    if marker.groups != 1:
        raise IngestError("syllabus.page_marker_pattern phải có đúng một nhóm bắt số trang.")

    sections: list[dict] = []
    found_chapters: dict[str, dict] = {}
    page: int | None = None
    marked_pages: set[int] = set()
    chapter: str | None = None
    in_fence = False
    current = {"heading": "(Mở đầu)", "level": 0, "chapter_id": None, "pages": set(), "lines": []}

    def close(sec):
        content = "\n".join(sec["lines"]).strip()
        if content or sec["level"] > 0:
            sections.append({**sec, "text": content})

    for line in body.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        pages_here = [int(n) for n in marker.findall(line)]
        marked_pages.update(pages_here)
        shown = marker.sub(lambda m: f"[trang {m.group(1)}]", line)
        bare = marker.sub("", line).strip()
        h = None if in_fence else _HEADING.match(bare) if bare.startswith("#") else None
        if h:
            for n in pages_here:      # mốc trang đứng cùng dòng tiêu đề: trang mở đầu mục
                page = n
            level, title, attr = len(h.group(1)), h.group(2).strip(), h.group(3)
            cid = None
            if chapters:
                if attr and attr in by_id:
                    cid = attr
                else:
                    cid = by_heading.get(norm_text(title))
            elif attr and _CHAPTER_WORD.match(title):
                cid = attr
                found_chapters.setdefault(cid, {"chapter_id": cid, "title": title, "heading": title,
                                                "pdf_page_start": None, "pdf_page_end": None})
            if cid:
                chapter = cid
            elif chapter and level <= _chapter_level(sections, current, chapter):
                chapter = None        # tiêu đề cùng cấp chương nhưng không phải chương: ra khỏi chương
            close(current)
            current = {"heading": title, "level": level, "chapter_id": chapter,
                       "pages": {page} if page is not None else set(), "lines": [],
                       "is_chapter_heading": bool(cid)}
            continue
        # Standalone markers move the cursor without claiming section pages.
        # Content spanning inline markers belongs to both sides of the move.
        if bare and page is not None:
            current["pages"].add(page)
        for n in pages_here:
            page = n
            if bare:
                current["pages"].add(n)
        current["lines"].append(shown)
    close(current)

    if not chapters:
        chapters = list(found_chapters.values())
        by_id = {c["chapter_id"]: c for c in chapters}

    # Mục chưa gắn chương nhưng front matter có khoảng trang của chương: gắn theo trang.
    ranged = [c for c in chapters if c["pdf_page_start"] is not None and c["pdf_page_end"] is not None]
    for sec in sections:
        if sec["chapter_id"] is None and sec["pages"] and ranged:
            first = min(sec["pages"])
            hit = [c["chapter_id"] for c in ranged if c["pdf_page_start"] <= first <= c["pdf_page_end"]]
            if len(hit) == 1:
                sec["chapter_id"] = hit[0]

    used_ids: dict[str, int] = {}
    out_sections = []
    for sec in sections:
        base = "sec-" + slugify(sec["heading"], 50)
        n = used_ids.get(base, 0) + 1
        used_ids[base] = n
        out_sections.append({
            "section_id": base if n == 1 else f"{base}-{n}",
            "heading": sec["heading"],
            "level": sec["level"],
            "chapter_id": sec["chapter_id"],
            "pdf_pages": sorted(sec["pages"]),
            "text": sec["text"],
        })

    pages_found = sorted(marked_pages)
    page_count = fm.get("pdf_page_count", fm.get("page_count"))
    headed = {s["chapter_id"] for s in out_sections if s["chapter_id"]}
    for c in chapters:
        c["found_in_text"] = c["chapter_id"] in headed
    warnings = []
    if not pages_found:
        warnings.append("Giáo trình không có mốc trang PDF: nguồn kiểu syllabus không xác thực được pdf_page. "
                        "Thêm <!-- page: N --> vào bài hoặc khai báo syllabus.page_marker_pattern.")
    if not chapters:
        warnings.append("Giáo trình không có chương mang ID (front matter chapters: hoặc tiêu đề {#id}): "
                        "mọi điểm kiến thức sẽ có chapter_id = null.")
    for c in chapters:
        if not c["found_in_text"]:
            warnings.append(f"Chương {c['chapter_id']} có trong front matter nhưng không khớp tiêu đề nào trong bài.")
    if fm.get("subject_id") is not None:
        fm_subject = str(fm["subject_id"])
    else:
        fm_subject = None
    return {
        "source_id": source_id,
        "front_matter": fm,
        "subject_id": fm_subject,
        "pdf_page_count": int(page_count) if page_count is not None else None,
        "chapters": [{k: v for k, v in c.items() if k != "heading"} for c in chapters],
        "pages_found": pages_found,
        "sections": out_sections,
        "warnings": warnings,
    }


def _chapter_level(sections: list[dict], current: dict, chapter: str) -> int:
    """Cấp tiêu đề của chương đang mở (để biết tiêu đề mới có đóng chương không)."""
    for sec in [current, *reversed(sections)]:
        if sec.get("is_chapter_heading") and sec["chapter_id"] == chapter:
            return sec["level"]
    return 0
