"""Lệnh prepare-review: dữ liệu đã trích -> gói đầu vào cho AI được công ty duyệt.

Không gọi AI nào. Gói ghi vào <out>/review/:
  package.md (hoặc package-part-01-of-NN.md nếu dài quá max_chars_per_part)
      đủ để dán / tải lên AI: prompt + slide + giáo trình liên quan +
      danh mục + transcript (chia theo đoạn thời gian, mỗi dòng có segment_id)
  prompt.md, transcript.md, slides.md, syllabus.md, catalog.md  từng phần riêng
  ai-output.schema.json                                       schema AI phải theo
  review-manifest.json                                        package_id, các phần, cách chọn giáo trình

Phần giáo trình liên quan: các chương HCNS khai báo (related_chapter_ids);
không khai báo thì xếp hạng mục theo số cụm hai âm tiết trùng với slide và
transcript (từ hiếm được tính nặng hơn), lấy tối đa syllabus_max_sections mục.
Không suy từ số buổi.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .errors import IngestError
from .extract import load_extracted
from .manifest import Manifest
from .timeutil import format_clock
from .util import norm_text, resource_json, resource_text, sha256_json, write_json, write_text

PROMPT_VERSION = "kp-prompt-2"

TRANSCRIPT_NOTES = {
    "asr": (
        "Transcript do máy chép lời (faster-whisper), có thể sai chính tả hoặc sai thuật ngữ "
        "(ví dụ 'tài dính' thay cho 'tài chính', 'chào bản' thay cho 'chào bán'). "
        "Viết title và summary bằng thuật ngữ đúng, đối chiếu slide và giáo trình. "
        "Trường quote (nếu có) chép nguyên văn transcript, không sửa. "
        "Nếu chỗ chép sai làm đổi nghĩa một số liệu, thời hạn hoặc điều khoản, ghi vào review_notes "
        "và thêm verification_flags; không tự đoán con số."
    ),
    "subtitle": "Transcript lấy từ phụ đề có sẵn; vẫn đối chiếu thuật ngữ với slide và giáo trình.",
}

EXAMPLE = {
    "schema_version": "1.0",
    "package_id": "pkg-…",
    "subject_id": "…",
    "session_id": "…",
    "knowledge_points": [{
        "local_id": "kp-001",
        "title": "Tên ý kiến thức ngắn gọn",
        "summary": "Hai đến năm câu, nói đúng như nguồn.",
        "subject_id": "…",
        "chapter_id": None,
        "chapter_id_reason": "Transcript nói tới nội dung này nhưng giáo trình trong gói không có mục tương ứng.",
        "session_id": "…",
        "existing_knowledge_point_id": None,
        "existing_match_reason": None,
        "sources": [
            {"type": "video", "source_id": "…", "segment_id": "seg-001203-120"},
            {"type": "slide", "source_id": "…", "pdf_page": 4},
        ],
        "verification_flags": [
            {"kind": "number", "text": "con số đúng như nguồn ghi", "note": None,
             "sources": [{"type": "slide", "source_id": "…", "pdf_page": 4}]},
        ],
        "conflicts": [],
        "review_status": "pending_review",
        "review_notes": "",
    }],
}


@dataclass
class ReviewResult:
    review_dir: Path
    package_id: str
    parts: list[Path]
    total_chars: int
    syllabus_method: str
    warnings: list[str]



def _bigrams(text: str) -> set[str]:
    tokens = [t for t in norm_text(text).split() if len(t) > 1 or t.isdigit()]
    return {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}


def select_syllabus(syllabus: dict, related: list[str], session_text: str,
                    max_sections: int, max_chars: int) -> tuple[list[dict], dict]:
    sections = [s for s in syllabus.get("sections") or [] if s.get("text")]
    order = {s["section_id"]: i for i, s in enumerate(sections)}
    if related:
        chosen = [s for s in sections if s["chapter_id"] in set(related)]
        scored = [(1.0, s) for s in chosen]
        method = "declared"
    else:
        session = _bigrams(session_text)
        grams = {s["section_id"]: _bigrams(s["heading"] + "\n" + s["text"]) for s in sections}
        df = Counter(g for gs in grams.values() for g in gs)
        n = len(sections)
        common_cut = max(1, n * 0.5)
        scored = []
        for s in sections:
            gs = grams[s["section_id"]]
            hit = [g for g in gs if g in session and df[g] <= common_cut]
            if not hit:
                continue
            score = sum(math.log(1 + n / df[g]) for g in hit) / math.sqrt(len(gs))
            scored.append((round(score, 4), s))
        scored.sort(key=lambda x: (-x[0], order[x[1]["section_id"]]))
        scored = scored[:max_sections]
        method = "lexical"
    picked, used = [], 0
    for score, s in scored:
        size = len(s["text"]) + len(s["heading"]) + 80
        if picked and used + size > max_chars:
            continue
        picked.append((score, s))
        used += size
    picked.sort(key=lambda x: order[x[1]["section_id"]])
    info = {
        "method": method,
        "declared_chapter_ids": related,
        "sections_considered": len(sections),
        "selected": [{"section_id": s["section_id"], "chapter_id": s["chapter_id"], "score": sc} for sc, s in picked],
        "chars": used,
    }
    return [s for _, s in picked], info



def _transcript_windows(segments: list[dict], minutes: int) -> list[tuple[int, int, list[dict]]]:
    size = minutes * 60_000
    windows: dict[int, list[dict]] = {}
    for seg in segments:
        windows.setdefault(seg["start_ms"] // size, []).append(seg)
    out = []
    for k in sorted(windows):
        segs = windows[k]
        out.append((segs[0]["start_ms"], segs[-1]["end_ms"], segs))
    return out


def _render_window(title: str, start: int, end: int, segs: list[dict]) -> str:
    lines = [f"### Transcript {title} · {format_clock(start)}–{format_clock(end)}", ""]
    for s in segs:
        lines.append(f"[{s['segment_id']} | {format_clock(s['start_ms'])}–{format_clock(s['end_ms'])}] {s['text']}")
    return "\n".join(lines) + "\n"


def _render_slides(meta: dict, slides: list[dict], index: dict) -> str:
    if not slides:
        return "## Slide\n\n(Buổi này không có slide.)\n"
    out = ["## Slide (nội dung theo trang)", ""]
    titles = {s["source_id"]: s.get("title") or s["source_id"] for s in meta["manifest"]["slides"]}
    for sid, info in index.items():
        out += [f"### Slide `{sid}`: {titles.get(sid, sid)} ({info['page_count']} trang)", ""]
        for page in (p for p in slides if p["source_id"] == sid):
            out.append(f"#### `{sid}` · trang {page['pdf_page']}")
            if page["needs_ocr"]:
                out.append("[Trang không có lớp chữ hoặc rất ít chữ: cần rà/OCR. Không trích nội dung từ trang này.]")
                if page["text"]:
                    out.append(page["text"])
            else:
                out.append(page["text"])
            out.append("")
    return "\n".join(out) + "\n"


def _render_syllabus(meta: dict, sections: list[dict], info: dict) -> str:
    sy = meta["manifest"].get("syllabus")
    if not sy:
        return "## Giáo trình\n\n(Không khai báo giáo trình.)\n"
    out = [f"## Giáo trình `{sy['source_id']}`: các phần liên quan", ""]
    if not sections:
        out.append("(Không tìm được phần giáo trình liên quan.)")
    for s in sections:
        pages = ", ".join(str(p) for p in s["pdf_pages"]) or "không rõ"
        out += [f"### {s['heading']}",
                f"section_id: `{s['section_id']}` · chapter_id: `{s['chapter_id'] or 'null'}` · trang PDF: {pages}",
                "", s["text"], ""]
    return "\n".join(out) + "\n"


def _render_catalog(catalog: list[dict]) -> str:
    if not catalog:
        return "## Danh mục điểm kiến thức đã có\n\n(Chưa có danh mục: để existing_knowledge_point_id = null.)\n"
    out = ["## Danh mục điểm kiến thức đã có", "",
           "Chỉ đề xuất existing_knowledge_point_id khi ý trùng thật sự.", ""]
    for kp in catalog:
        summary = (kp.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 240:
            summary = summary[:237] + "…"
        out.append(f"- `{kp['knowledge_point_id']}` · chương `{kp.get('chapter_id') or 'null'}` · "
                   f"{kp['title']}" + (f": {summary}" if summary else ""))
    return "\n".join(out) + "\n"


def _chapters_text(syllabus: dict) -> str:
    chapters = syllabus.get("chapters") or []
    if not chapters:
        return "(Giáo trình không có chương mang mã: mọi chapter_id phải là null, kèm lý do.)"
    lines = []
    for c in chapters:
        rng = ""
        if c.get("pdf_page_start") is not None:
            rng = f" (trang {c['pdf_page_start']}–{c.get('pdf_page_end') or '?'})"
        lines.append(f"- `{c['chapter_id']}`: {c['title']}{rng}")
    return "\n".join(lines)


def _fill(template: str, values: dict) -> str:
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise KeyError(f"prompt thiếu giá trị cho {{{{{key}}}}}")
        return str(values[key])
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def run_prepare_review(m: Manifest, out_dir: Path, *, max_chars: int | None = None, log=print) -> ReviewResult:
    out_dir = Path(out_dir)
    ex = load_extracted(out_dir)
    meta = ex["meta"]
    current = m.public_dict() | {"manifest_path": None}
    extracted = meta["manifest"] | {"manifest_path": None}
    if current != extracted:
        raise IngestError("Manifest đã đổi sau lần extract (hoặc --out là của buổi khác). Chạy lại 'extract'.")
    budget = max_chars or m.review.max_chars_per_part
    warnings: list[str] = []

    segments, slides, index, syllabus, catalog = (ex["segments"], ex["slides"], ex["slides_index"],
                                                  ex["syllabus"], ex["catalog"])
    session_text = "\n".join([s["text"] for s in segments] + [p["text"] for p in slides if not p["needs_ocr"]])
    sy_sections, sy_info = select_syllabus(syllabus, m.related_chapter_ids, session_text,
                                           m.review.syllabus_max_sections, m.review.syllabus_max_chars)
    if m.syllabus and sy_info["method"] == "lexical":
        warnings.append("Phần giáo trình được chọn tự động theo độ trùng từ ngữ; khai báo related_chapter_ids "
                        "nếu HCNS đã biết buổi này dạy chương nào.")

    video = meta["manifest"]["video"]
    slides_md = _render_slides(meta, slides, index)
    syllabus_md = _render_syllabus(meta, sy_sections, sy_info)
    catalog_md = _render_catalog(catalog)
    spans = _transcript_windows(segments, m.review.chunk_minutes)
    windows = [_render_window(video["title"], a, b, segs) for a, b, segs in spans]

    sy = meta["manifest"].get("syllabus")
    pages_found = syllabus.get("pages_found") or []
    slide_lines = "\n".join(
        f"  - `{sid}`: {info['title']} ({info['page_count']} trang"
        + (f"; trang cần rà/OCR: {info['pages_needing_ocr']}" if info["pages_needing_ocr"] else "") + ")"
        for sid, info in index.items()) or "  - (không có)"
    base_values = {
        "subject_id": m.subject_id,
        "subject_name": m.subject_name or m.subject_id,
        "programs": ", ".join(f"`{p}`" for p in m.programs) or "(không khai báo)",
        "course_id": m.course_id,
        "session_id": m.session_id,
        "session_label": m.session_label,
        "video_source": f"`{video['source_id']}`: {video['title']}",
        "video_source_id": video["source_id"],
        "transcript_note": TRANSCRIPT_NOTES[meta["transcript"]["origin"]],
        "slide_sources": slide_lines,
        "syllabus_source": (f"`{sy['source_id']}`: {sy['title']}"
                            + (f" (mốc trang có trong bài: {pages_found[0]}–{pages_found[-1]})" if pages_found
                               else " (giáo trình không có mốc trang: không trích nguồn giáo trình theo trang)"))
        if sy else "(không khai báo)",
        "syllabus_source_id": sy["source_id"] if sy else "(không có)",
        "chapters": _chapters_text(syllabus),
        "selection_note": (
            "Phần giáo trình trong gói là các chương HCNS đã xác nhận cho buổi này."
            if sy_info["method"] == "declared" else
            "Phần giáo trình trong gói được **chọn tự động** theo độ trùng từ ngữ với slide và transcript, "
            "có thể thiếu hoặc thừa. Chỉ gán chapter_id khi nội dung khớp rõ."),
        "output_schema": json.dumps(resource_json("schemas/ai-output.schema.json"), ensure_ascii=False, indent=2),
        "example": json.dumps(EXAMPLE, ensure_ascii=False, indent=2),
    }
    template = resource_text("prompts/knowledge-points.prompt.md")

    def prompt(package_id: str, i: int, n: int, part_note: str) -> str:
        return _fill(template, base_values | {"package_id": package_id, "part_number": i, "part_count": n,
                                              "part_note": part_note})

    shared = "\n".join([slides_md, syllabus_md, catalog_md])
    probe = prompt("pkg-000000000000", 1, 1, "")
    fixed = len(probe) + len(shared) + 200
    if fixed >= budget:
        warnings.append(f"Riêng prompt + slide + giáo trình + danh mục đã {fixed} ký tự, vượt max_chars_per_part "
                        f"{budget}: mỗi phần sẽ dài hơn giới hạn.")
    groups: list[list[int]] = [[]]
    used = fixed
    for i, w in enumerate(windows):
        if groups[-1] and used + len(w) > budget:
            groups.append([])
            used = fixed
        groups[-1].append(i)
        used += len(w)

    n = len(groups)
    package_id = "pkg-" + sha256_json({
        "extract_id": meta["extract_id"], "prompt": PROMPT_VERSION, "template": template,
        "shared": shared, "windows": windows, "groups": groups, "values": base_values,
    })[:12]
    parts_text, part_info = [], []
    for k, idx in enumerate(groups, start=1):
        texts = [windows[i] for i in idx]
        lo, hi = spans[idx[0]][0], spans[idx[-1]][1]
        note = ""
        if n > 1:
            note = (f"**Gói chia {n} phần.** Phần này chứa transcript {format_clock(lo)}–{format_clock(hi)}. "
                    "Chỉ tạo điểm kiến thức có nguồn video nằm trong phần này; slide và giáo trình dùng chung. "
                    "Trả về một JSON riêng cho phần này, cùng package_id.")
        body = "\n".join([prompt(package_id, k, n, note), "---", "", "# Dữ liệu buổi học", "",
                          shared, "## Transcript (mã đoạn | mốc thời gian theo video gốc)", "", *texts])
        parts_text.append(body)
        part_info.append({"part": k, "transcript_from": format_clock(lo), "transcript_to": format_clock(hi),
                          "windows": len(idx), "chars": len(body)})

    review_dir = out_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    for old in review_dir.glob("package*.md"):     # gói cũ của lần chạy trước
        old.unlink()
    if n == 1:
        names = ["package.md"]
    else:
        names = [f"package-part-{k:02d}-of-{n:02d}.md" for k in range(1, n + 1)]
    for name, text in zip(names, parts_text):
        write_text(review_dir / name, text)
    write_text(review_dir / "prompt.md", prompt(package_id, 1, n, ""))
    write_text(review_dir / "transcript.md", "# Transcript\n\n" + "\n".join(windows))
    write_text(review_dir / "slides.md", slides_md)
    write_text(review_dir / "syllabus.md", syllabus_md)
    write_text(review_dir / "catalog.md", catalog_md)
    write_json(review_dir / "ai-output.schema.json", resource_json("schemas/ai-output.schema.json"))
    write_json(review_dir / "review-manifest.json", {
        "tool": "learning-ingest", "version": __version__,
        "package_id": package_id, "prompt_version": PROMPT_VERSION,
        "extract_id": meta["extract_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parts": [{"file": name, **info} for name, info in zip(names, part_info)],
        "max_chars_per_part": budget,
        "syllabus_selection": sy_info,
        "warnings": warnings,
    })
    return ReviewResult(review_dir=review_dir, package_id=package_id, parts=[review_dir / x for x in names],
                        total_chars=sum(len(t) for t in parts_text), syllabus_method=sy_info["method"],
                        warnings=warnings)
