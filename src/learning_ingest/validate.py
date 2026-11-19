"""Kiểm tra đầu ra JSON của AI so với dữ liệu đã trích.

Lỗi (error) chặn việc xuất gói import; cảnh báo (warning) thì không. Mỗi vấn
đề ghi rõ thuộc điểm kiến thức nào (thứ tự, local_id, tiêu đề), vị trí trong
JSON và lý do.

Lỗi:
  - JSON hỏng, sai schema (thiếu trường, sai kiểu, review_status khác pending_review)
  - subject_id / session_id khác manifest
  - nguồn: source_id không có / sai loại (kể cả type video khi gói không có video),
    segment_id không có trong transcript, section_id không có trong văn bản (.docx),
    start_ms / end_ms lệch segment quá TOLERANCE_MS, trang slide ngoài số trang,
    trang giáo trình không có trong bài, section_id không có
  - chapter_id không có trong giáo trình; chapter_id null mà không ghi lý do
  - existing_knowledge_point_id không có trong danh mục
Cảnh báo:
  - trích trang slide không có lớp chữ (cần mở PDF xem)
  - nguồn giáo trình thuộc chương khác chapter_id của điểm
  - đề xuất trùng điểm đã có mà không ghi lý do
  - hai điểm trùng tiêu đề (được gộp khi xuất)
  - package_id không khớp gói review hiện tại (đầu ra làm từ gói cũ)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import jsonschema

from .extract import load_extracted
from .timeutil import format_clock
from .util import read_json, resource_json, sha256_bytes

TOLERANCE_MS = 1000


@dataclass
class Issue:
    level: str                  # "error" | "warning"
    code: str
    message: str
    path: str = ""
    item: int | None = None     # thứ tự điểm kiến thức (bắt đầu từ 1) trong file
    local_id: str | None = None
    title: str | None = None
    input_file: str | None = None


@dataclass
class Context:
    """Dữ liệu đã trích, dựng sẵn để tra."""
    meta: dict
    subject_id: str
    session_id: str
    video_id: str | None
    segments: dict[str, dict]
    slides: dict[str, dict]            # source_id -> {page_count, needs_ocr: set}
    documents: dict[str, set[str]]     # source_id -> các section_id
    document_rows: list[dict]
    syllabus_id: str | None
    syllabus_pages: set[int]
    syllabus_page_count: int | None
    sections: dict[str, dict]
    page_chapters: dict[int, set]
    chapters: set[str]
    chapter_titles: dict[str, str]
    catalog: dict[str, dict]
    package_id: str | None
    extract_id: str

    @classmethod
    def load(cls, out_dir: Path) -> "Context":
        ex = load_extracted(out_dir)
        meta = ex["meta"]
        man = meta["manifest"]
        slides = {}
        needs = {}
        for p in ex["slides"]:
            needs.setdefault(p["source_id"], set())
            if p["needs_ocr"]:
                needs[p["source_id"]].add(p["pdf_page"])
        for sid, info in ex["slides_index"].items():
            slides[sid] = {"page_count": info["page_count"], "needs_ocr": needs.get(sid, set()),
                           "title": info.get("title") or sid, "unit": info.get("unit", "page")}
        sy = ex["syllabus"]
        page_chapters: dict[int, set] = {}
        for s in sy.get("sections") or []:
            for p in s["pdf_pages"]:
                page_chapters.setdefault(p, set()).add(s["chapter_id"])
        review_meta = Path(out_dir) / "review" / "review-manifest.json"
        return cls(
            meta=meta, subject_id=man["subject_id"], session_id=man["session_id"],
            video_id=(man.get("video") or {}).get("source_id"),
            segments={s["segment_id"]: s for s in ex["segments"]},
            slides=slides,
            documents={sid: {d["section_id"] for d in ex["documents"] if d["source_id"] == sid}
                       for sid in ex["documents_index"]},
            document_rows=ex["documents"],
            syllabus_id=(man.get("syllabus") or {}).get("source_id"),
            syllabus_pages=set(sy.get("pages_found") or []),
            syllabus_page_count=sy.get("pdf_page_count"),
            sections={s["section_id"]: s for s in sy.get("sections") or []},
            page_chapters=page_chapters,
            chapters={c["chapter_id"] for c in sy.get("chapters") or []},
            chapter_titles={c["chapter_id"]: c["title"] for c in sy.get("chapters") or []},
            catalog={k["knowledge_point_id"]: k for k in ex["catalog"]},
            package_id=read_json(review_meta)["package_id"] if review_meta.exists() else None,
            extract_id=meta["extract_id"],
        )


@dataclass
class Validation:
    issues: list[Issue] = field(default_factory=list)
    outputs: list[tuple[Path, dict, str]] = field(default_factory=list)   # (file, data, sha256)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.DOTALL)


def _read_output(path: Path, v: Validation) -> tuple[dict | None, str]:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        v.issues.append(Issue("error", "file_missing", f"Không thấy file {path}", input_file=str(path)))
        return None, ""
    digest = sha256_bytes(raw)
    text = raw.decode("utf-8-sig", errors="replace")
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
        v.issues.append(Issue("warning", "code_fence", "Đầu ra AI bọc trong ```json```; đã bỏ phần bọc.",
                              input_file=str(path)))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        v.issues.append(Issue("error", "json_invalid", f"Không phải JSON hợp lệ: dòng {exc.lineno}, cột {exc.colno}: {exc.msg}",
                              input_file=str(path)))
        return None, digest
    return data, digest


def _path(parts) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


class _Checker:
    def __init__(self, ctx: Context, v: Validation, file: str):
        self.ctx, self.v, self.file = ctx, v, file
        self.item = None
        self.kp: dict = {}

    def issue(self, level: str, code: str, path: str, message: str) -> None:
        self.v.issues.append(Issue(level, code, message, path, self.item,
                                   self.kp.get("local_id") if isinstance(self.kp, dict) else None,
                                   self.kp.get("title") if isinstance(self.kp, dict) else None, self.file))

    def source(self, src: dict, path: str) -> set:
        """Kiểm một nguồn; trả về các chương mà nguồn giáo trình này thuộc về."""
        ctx = self.ctx
        kind, sid = src["type"], src["source_id"]
        if kind == "video":
            if ctx.video_id is None:
                self.issue("error", "source_id_unknown", f"{path}.source_id",
                           "Gói này không có video: không trích nguồn type 'video'.")
                return set()
            if sid != ctx.video_id:
                self.issue("error", "source_id_unknown", f"{path}.source_id",
                           f"'{sid}' không phải video của buổi (video là '{ctx.video_id}').")
                return set()
            seg = ctx.segments.get(src["segment_id"])
            if seg is None:
                self.issue("error", "segment_unknown", f"{path}.segment_id",
                           f"segment_id '{src['segment_id']}' không có trong transcript.")
                return set()
            lo, hi = seg["start_ms"], seg["end_ms"]
            span = f"{format_clock(lo)}–{format_clock(hi)} ({lo}–{hi} ms)"
            if "start_ms" in src and not (lo - TOLERANCE_MS <= src["start_ms"] <= hi):
                self.issue("error", "timestamp_mismatch", f"{path}.start_ms",
                           f"start_ms {src['start_ms']} nằm ngoài segment {src['segment_id']} {span}.")
            if "end_ms" in src and not (lo <= src["end_ms"] <= hi + TOLERANCE_MS):
                self.issue("error", "timestamp_mismatch", f"{path}.end_ms",
                           f"end_ms {src['end_ms']} nằm ngoài segment {src['segment_id']} {span}.")
            if "start_ms" in src and "end_ms" in src and src["end_ms"] < src["start_ms"]:
                self.issue("error", "timestamp_mismatch", f"{path}.end_ms", "end_ms nhỏ hơn start_ms.")
            return set()
        if kind == "slide":
            slide = ctx.slides.get(sid)
            if slide is None:
                hint = " (đây là mã video/giáo trình, sai type)" if sid in (ctx.video_id, ctx.syllabus_id) else ""
                self.issue("error", "source_id_unknown", f"{path}.source_id", f"Không có slide '{sid}'{hint}.")
                return set()
            page = src["pdf_page"]
            unit = "slide" if slide.get("unit") == "slide" else "trang"
            if page > slide["page_count"]:
                self.issue("error", "page_out_of_range", f"{path}.pdf_page",
                           f"Slide '{sid}' chỉ có {slide['page_count']} {unit}, không có {unit} {page}.")
            elif page in slide["needs_ocr"]:
                self.issue("warning", "page_needs_ocr", f"{path}.pdf_page",
                           (f"Slide {page} của '{sid}' không có chữ: HCNS cần mở file PowerPoint xem slide này."
                            if unit == "slide" else
                            f"Trang {page} của '{sid}' không có lớp chữ: HCNS cần mở PDF xem trang này."))
            return set()
        if kind == "document":
            sections = ctx.documents.get(sid)
            if sections is None:
                self.issue("error", "source_id_unknown", f"{path}.source_id", f"Không có văn bản '{sid}'.")
            elif src["section_id"] not in sections:
                self.issue("error", "section_unknown", f"{path}.section_id",
                           f"section_id '{src['section_id']}' không có trong văn bản '{sid}'.")
            return set()
        # syllabus
        if ctx.syllabus_id is None:
            self.issue("error", "source_id_unknown", f"{path}.source_id", "Buổi này không khai báo giáo trình.")
            return set()
        if sid != ctx.syllabus_id:
            self.issue("error", "source_id_unknown", f"{path}.source_id",
                       f"'{sid}' không phải giáo trình của buổi (giáo trình là '{ctx.syllabus_id}').")
            return set()
        page = src["pdf_page"]
        if ctx.syllabus_pages:
            if page not in ctx.syllabus_pages:
                pages = sorted(ctx.syllabus_pages)
                self.issue("error", "page_out_of_range", f"{path}.pdf_page",
                           f"Trang {page} không có trong giáo trình đã trích (mốc trang có: {pages[0]}–{pages[-1]}).")
                return set()
        elif ctx.syllabus_page_count:
            if page > ctx.syllabus_page_count:
                self.issue("error", "page_out_of_range", f"{path}.pdf_page",
                           f"Giáo trình chỉ có {ctx.syllabus_page_count} trang.")
                return set()
            self.issue("warning", "page_unverified", f"{path}.pdf_page",
                       "Giáo trình không có mốc trang: chỉ kiểm được số trang nằm trong tổng số trang.")
        else:
            self.issue("error", "page_unverifiable", f"{path}.pdf_page",
                       "Giáo trình không có mốc trang và không khai báo pdf_page_count: không xác thực được trang.")
            return set()
        section_id = src.get("section_id")
        if section_id:
            sec = ctx.sections.get(section_id)
            if sec is None:
                self.issue("error", "section_unknown", f"{path}.section_id",
                           f"section_id '{section_id}' không có trong giáo trình.")
            elif sec["pdf_pages"] and page not in sec["pdf_pages"]:
                self.issue("warning", "page_section_mismatch", f"{path}.pdf_page",
                           f"Trang {page} không nằm trong mục '{section_id}' (trang {sec['pdf_pages']}).")
            elif sec is not None:
                return {sec["chapter_id"]}
        return ctx.page_chapters.get(page, set())

    def knowledge_point(self, kp: dict, i: int) -> None:
        self.item, self.kp = i, kp
        ctx = self.ctx
        base = f"knowledge_points[{i - 1}]"
        if kp["subject_id"] != ctx.subject_id:
            self.issue("error", "subject_mismatch", f"{base}.subject_id",
                       f"subject_id '{kp['subject_id']}' khác manifest '{ctx.subject_id}'.")
        if kp["session_id"] != ctx.session_id:
            self.issue("error", "session_mismatch", f"{base}.session_id",
                       f"session_id '{kp['session_id']}' khác manifest '{ctx.session_id}'.")
        chapter = kp["chapter_id"]
        if chapter is None:
            if not (kp["chapter_id_reason"] or "").strip():
                self.issue("error", "chapter_reason_missing", f"{base}.chapter_id_reason",
                           "chapter_id = null thì phải ghi lý do trong chapter_id_reason.")
        elif chapter not in ctx.chapters:
            known = ", ".join(sorted(ctx.chapters)) or "(giáo trình không có chương mang mã)"
            self.issue("error", "chapter_unknown", f"{base}.chapter_id",
                       f"chapter_id '{chapter}' không có trong giáo trình. Có: {known}.")
        existing = kp["existing_knowledge_point_id"]
        if existing is not None:
            if existing not in ctx.catalog:
                self.issue("error", "existing_unknown", f"{base}.existing_knowledge_point_id",
                           f"'{existing}' không có trong danh mục điểm kiến thức.")
            if not (kp["existing_match_reason"] or "").strip():
                self.issue("warning", "existing_reason_missing", f"{base}.existing_match_reason",
                           "Đề xuất trùng điểm đã có nhưng không ghi lý do.")
        cited_chapters: set = set()
        for j, src in enumerate(kp["sources"]):
            cited_chapters |= self.source(src, f"{base}.sources[{j}]")
        for j, flag in enumerate(kp["verification_flags"]):
            for k, src in enumerate(flag.get("sources") or []):
                self.source(src, f"{base}.verification_flags[{j}].sources[{k}]")
        for j, conflict in enumerate(kp["conflicts"]):
            for k, claim in enumerate(conflict["claims"]):
                self.source(claim["source"], f"{base}.conflicts[{j}].claims[{k}].source")
        cited_chapters.discard(None)
        if chapter and chapter in ctx.chapters and cited_chapters and chapter not in cited_chapters:
            self.issue("warning", "chapter_source_mismatch", f"{base}.chapter_id",
                       f"chapter_id '{chapter}' nhưng nguồn giáo trình thuộc chương {sorted(cited_chapters)}.")


def validate(inputs: list[Path], out_dir: Path) -> tuple[Validation, Context]:
    ctx = Context.load(out_dir)
    v = Validation()
    schema = jsonschema.Draft202012Validator(resource_json("schemas/ai-output.schema.json"))
    package_ids = set()
    for path in inputs:
        data, digest = _read_output(path, v)
        if data is None:
            continue
        file = str(path)
        chk = _Checker(ctx, v, file)
        bad_items: set[int] = set()
        top_bad = False
        for err in sorted(schema.iter_errors(data), key=lambda e: list(map(str, e.absolute_path))):
            parts = list(err.absolute_path)
            if len(parts) >= 2 and parts[0] == "knowledge_points" and isinstance(parts[1], int):
                idx = parts[1]
                bad_items.add(idx)
                kp = data["knowledge_points"][idx]
                chk.item, chk.kp = idx + 1, kp if isinstance(kp, dict) else {}
            else:
                top_bad = True
                chk.item, chk.kp = None, {}
            chk.issue("error", "schema", _path(parts) or "(gốc)", err.message)
        if top_bad or not isinstance(data, dict) or not isinstance(data.get("knowledge_points"), list):
            continue
        chk.item, chk.kp = None, {}
        if data["subject_id"] != ctx.subject_id:
            chk.issue("error", "subject_mismatch", "subject_id",
                      f"subject_id '{data['subject_id']}' khác manifest '{ctx.subject_id}'.")
        if data["session_id"] != ctx.session_id:
            chk.issue("error", "session_mismatch", "session_id",
                      f"session_id '{data['session_id']}' khác manifest '{ctx.session_id}'.")
        if ctx.package_id is None:
            chk.issue("warning", "package_unknown", "package_id",
                      "Chưa có review/review-manifest.json: không kiểm được đầu ra làm từ gói nào.")
        elif data["package_id"] != ctx.package_id:
            chk.issue("warning", "package_stale", "package_id",
                      f"package_id '{data['package_id']}' khác gói review hiện tại '{ctx.package_id}': "
                      "đầu ra có thể làm từ gói cũ. Mọi nguồn vẫn được kiểm với dữ liệu hiện tại.")
        package_ids.add(data["package_id"])
        if not data["knowledge_points"]:
            chk.issue("error", "empty", "knowledge_points", "Không có điểm kiến thức nào.")
        for i, kp in enumerate(data["knowledge_points"]):
            if i not in bad_items:
                chk.knowledge_point(kp, i + 1)
        v.outputs.append((Path(path), data, digest))
    if len(package_ids) > 1:
        v.issues.append(Issue("warning", "package_mixed",
                              f"Các file đầu vào thuộc nhiều gói khác nhau: {sorted(package_ids)}."))
    return v, ctx


def report_dict(v: Validation, ctx: Context | None) -> dict:
    return {
        "ok": v.ok,
        "errors": len(v.errors),
        "warnings": len(v.warnings),
        "extract_id": ctx.extract_id if ctx else None,
        "package_id_current": ctx.package_id if ctx else None,
        "inputs": [{"file": str(p), "sha256": d, "knowledge_points": len(data.get("knowledge_points") or [])}
                   for p, data, d in v.outputs],
        "issues": [asdict(i) for i in v.issues],
    }


def report_markdown(v: Validation, ctx: Context | None, exported: bool) -> str:
    lines = ["# Báo cáo kiểm tra đầu ra AI", ""]
    if v.ok:
        lines.append(f"**Kết quả: hợp lệ.** {len(v.warnings)} cảnh báo cần HCNS xem."
                     + (" Đã xuất gói import." if exported else ""))
    else:
        lines.append(f"**Kết quả: KHÔNG hợp lệ.** {len(v.errors)} lỗi, {len(v.warnings)} cảnh báo. "
                     "Chưa xuất gói import; sửa đầu ra AI (hoặc chạy lại AI) rồi kiểm tra lại.")
    lines.append("")
    for level, label in (("error", "Lỗi (chặn xuất)"), ("warning", "Cảnh báo")):
        group = [i for i in v.issues if i.level == level]
        if not group:
            continue
        lines += [f"## {label}", ""]
        by_item: dict[tuple, list[Issue]] = {}
        for i in group:
            by_item.setdefault((i.input_file, i.item, i.local_id, i.title), []).append(i)
        for (file, item, local_id, title), items in by_item.items():
            head = "Cả file" if item is None else f"Điểm #{item}" + (f" `{local_id}`" if local_id else "") + (
                f": {title}" if title else "")
            lines.append(f"### {head}" + (f" ({Path(file).name})" if file else ""))
            for i in items:
                lines.append(f"- `{i.code}` tại `{i.path or '-'}`: {i.message}")
            lines.append("")
    return "\n".join(lines) + "\n"
