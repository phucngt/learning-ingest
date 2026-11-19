"""Giáo trình Markdown -> chương, mục, mốc trang PDF.

Chương lấy ID từ đâu (theo thứ tự):
  1. manifest `syllabus.chapters`: mỗi mục ghép chapter_id với một regex tiêu đề.
  2. front matter `chapters:` - mỗi mục có chapter_id (hoặc id), title, tuỳ
     chọn heading (chữ của tiêu đề trong bài), pdf_page_start / pdf_page_end.
     Tiêu đề trong bài khớp heading/title, hoặc mang thuộc tính {#chapter_id},
     thì mở chương đó.
  3. Khi không có danh sách chương: tiêu đề bắt đầu bằng
     "Chương / Chapter / Phần" và có thuộc tính {#id} -> chương mang id đó.
Không có ID rõ ràng thì chương không có ID: công cụ không tự đặt mã chương,
và không bao giờ suy chương từ số buổi học.

Mốc trang PDF: dòng chứa <!-- page: N -->, <!-- pdf_page: N --> hoặc
<!-- trang N -->, hoặc tiêu đề Markdown `### Trang PDF N`. Có thể thay các mẫu
mặc định bằng manifest syllabus.page_marker_pattern. Trong nội dung
gửi AI, mốc được thay bằng "[trang N]" để AI trích đúng trang.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .errors import IngestError
from .util import norm_text, slugify

DEFAULT_PAGE_MARKER = r"<!--\s*(?:pdf[_-]?page|page|trang)\s*[:=]?\s*(\d+)\s*-->"
PDF_HEADING_PAGE_MARKER = r"^#{1,6}\s*Trang\s+PDF\s+(\d+)\s*$"
DEFAULT_PAGE_MARKERS = [DEFAULT_PAGE_MARKER, PDF_HEADING_PAGE_MARKER]
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([A-Za-z0-9._:-]+)\})?\s*#*\s*$")
_CHAPTER_WORD = re.compile(r"^(chương|chuong|chapter|phần|phan)\b", re.IGNORECASE)
_CHAPTER_TOKEN = re.compile(r"^\s+([ivxlcdm]+|\d+)\b", re.IGNORECASE)
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
            "id_status": "front_matter",
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


def _manifest_chapters(chapters: list[dict]) -> tuple[list[dict], dict[str, re.Pattern[str]]]:
    definitions = []
    patterns = {}
    for item in chapters:
        cid = item["chapter_id"]
        if cid in patterns:
            raise IngestError(f"syllabus.chapters: chapter_id trùng: {cid}")
        try:
            patterns[cid] = re.compile(item["heading_match"], re.IGNORECASE)
        except re.error as exc:
            raise IngestError(f"syllabus.chapters: heading_match của {cid} sai regex: {exc}") from exc
        definitions.append({
            "chapter_id": cid,
            "title": item.get("title"),
            "id_status": item.get("id_status"),
            "pdf_page_start": None,
            "pdf_page_end": None,
        })
    return definitions, patterns


def parse_syllabus(path: Path, source_id: str, page_marker_pattern: str | None = None,
                   chapters: list[dict] | None = None) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise IngestError(f"Không thấy giáo trình: {path}") from None
    fm, body = split_front_matter(text)
    warnings = []
    definitions, heading_patterns = _manifest_chapters(chapters or [])
    if heading_patterns and "chapters" in fm:
        warnings.append("syllabus.chapters trong manifest được ưu tiên hơn chapters trong front matter.")
    chapters = definitions if heading_patterns else _fm_chapters(fm)
    by_id = {c["chapter_id"]: c for c in chapters}
    by_heading = {}
    for c in chapters:
        for label in (c.get("heading"), c["title"]):
            if label:
                by_heading.setdefault(norm_text(str(label)), c["chapter_id"])

    marker_patterns = (page_marker_pattern,) if page_marker_pattern is not None else DEFAULT_PAGE_MARKERS
    try:
        markers = [re.compile(pattern, re.IGNORECASE) for pattern in marker_patterns]
    except re.error as exc:
        raise IngestError(f"syllabus.page_marker_pattern sai regex: {exc}") from exc
    if any(marker.groups != 1 for marker in markers):
        raise IngestError("syllabus.page_marker_pattern phải có đúng một nhóm bắt số trang.")

    sections: list[dict] = []
    candidates: list[dict] = []
    occurrences: Counter[str] = Counter()
    opened_manifest_chapters: set[str] = set()
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
        matches = sorted((match for marker in markers for match in marker.finditer(line)), key=lambda m: m.start())
        try:
            pages_here = [int(match.group(1)) for match in matches]
        except (TypeError, ValueError) as exc:
            raise IngestError(f"syllabus.page_marker_pattern không bắt được số trang: {line!r}") from exc
        marked_pages.update(pages_here)
        if matches and matches[0].re.pattern == PDF_HEADING_PAGE_MARKER:
            page = pages_here[0]
            continue
        bare, shown = line, line
        for match in reversed(matches):
            start, end = match.span()
            bare = bare[:start] + bare[end:]
            shown = shown[:start] + f"[trang {match.group(1)}]" + shown[end:]
        bare = bare.strip()
        h = None if in_fence else _HEADING.match(bare) if bare.startswith("#") else None
        if h:
            for n in pages_here:      # mốc trang đứng cùng dòng tiêu đề: trang mở đầu mục
                page = n
            level, title, attr = len(h.group(1)), h.group(2).strip(), h.group(3)
            chapter_word = _CHAPTER_WORD.match(title)
            if chapter_word:
                token = _CHAPTER_TOKEN.match(title[chapter_word.end():])
                key = token.group(1).upper() if token else norm_text(title)
                occurrences[key] += 1
                candidates.append({"heading": title, "level": level, "pdf_page": page,
                                   "occurrence": occurrences[key]})

            cid = None
            if heading_patterns:
                matched = [chapter_id for chapter_id, pattern in heading_patterns.items() if pattern.search(title)]
                if len(matched) > 1:
                    raise IngestError(f"syllabus.chapters: tiêu đề {title!r} khớp nhiều chapter_id: {', '.join(matched)}")
                if matched and matched[0] not in opened_manifest_chapters:
                    cid = matched[0]
                    opened_manifest_chapters.add(cid)
                    if by_id[cid]["title"] is None:
                        by_id[cid]["title"] = title
            elif chapters:
                if attr and attr in by_id:
                    cid = attr
                else:
                    cid = by_heading.get(norm_text(title))
            elif attr and chapter_word:
                cid = attr
                found_chapters.setdefault(cid, {"chapter_id": cid, "title": title, "heading": title,
                                                "id_status": "heading_attribute",
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
    assigned_pages: dict[str, list[int]] = defaultdict(list)
    for sec in out_sections:
        if sec["chapter_id"]:
            assigned_pages[sec["chapter_id"]].extend(sec["pdf_pages"])
    for c in chapters:
        if c["id_status"] != "front_matter":
            pages = assigned_pages[c["chapter_id"]]
            c["pdf_page_start"] = min(pages, default=None)
            c["pdf_page_end"] = max(pages, default=None)
        if c["title"] is None:
            c["title"] = c["chapter_id"]

    if not pages_found:
        warnings.append("Giáo trình không có mốc trang PDF: nguồn kiểu syllabus không xác thực được pdf_page. "
                        "Thêm <!-- page: N --> vào bài hoặc khai báo syllabus.page_marker_pattern.")
    if not chapters:
        warnings.append("Giáo trình không có chương mang ID (manifest, front matter hoặc tiêu đề {#id}): "
                        "mọi điểm kiến thức sẽ có chapter_id = null.")
    for c in chapters:
        if not c["found_in_text"]:
            origin = "syllabus.chapters trong manifest" if heading_patterns else "front matter"
            warnings.append(f"Chương {c['chapter_id']} có trong {origin} nhưng không khớp tiêu đề nào trong bài.")
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
        "chapter_candidates": candidates,
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
