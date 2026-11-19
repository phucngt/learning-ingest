"""Lệnh validate-export: kiểm tra đầu ra AI, hợp lệ thì xuất
  <out>/export/knowledge-points.json    gói import cho app (pending_review)
  <out>/export/<buoi-xx>-tri-thuc.md    bản đọc duyệt cho HCNS
  <out>/export/validation-report.json / .md
Có lỗi thì chỉ ghi báo cáo, và xoá gói import cũ (nếu có) để không ai nhầm
nó là kết quả của lần kiểm tra này.

Chạy lại không tạo bản ghi trùng:
  - knowledge_point_id = "kp-" + sha256(subject_id | session_id | tiêu đề đã chuẩn hoá)[:12],
    cùng đầu vào cho cùng ID; file được ghi đè chứ không nối thêm.
  - hai điểm cùng tiêu đề (trong một file hay giữa các phần của gói) được gộp
    làm một, nguồn và ghi chú hợp lại, kèm cảnh báo.
  - knowledge-points.json không chứa thời điểm chạy: cùng đầu vào cho cùng nội dung.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from . import __version__
from .errors import IngestError
from .registry import program_names
from .timeutil import format_clock
from .util import norm_text, resource_json, write_json, write_text
from .validate import Context, Issue, Validation, report_dict, report_markdown, validate

FLAG_LABEL = {"number": "Số liệu", "deadline": "Thời hạn", "legal_reference": "Điều khoản / văn bản", "other": "Khác"}


@dataclass
class ExportResult:
    ok: bool
    export_dir: Path
    knowledge_points: int
    errors: int
    warnings: int
    files: list[Path]
    removed_stale: list[Path]


def kp_id(subject_id: str, session_id: str, title: str) -> str:
    key = f"{subject_id}|{session_id}|{norm_text(title)}"
    return "kp-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _fmt(template: str, **values) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise IngestError(f"Mẫu link '{template}' sai: {exc}. Dùng các biến {sorted(values)}.") from exc


class _Resolver:
    """Nguồn AI trích -> nguồn có tiêu đề, nhãn, link cho app và Markdown."""

    def __init__(self, ctx: Context):
        man = ctx.meta["manifest"]
        self.ctx = ctx
        self.video = man["video"]
        self.slides = {s["source_id"]: s for s in man["slides"]}
        self.syllabus = man.get("syllabus") or {}

    def __call__(self, src: dict) -> dict:
        kind, sid = src["type"], src["source_id"]
        out = {"type": kind, "source_id": sid}
        if kind == "video":
            seg = self.ctx.segments[src["segment_id"]]
            start = src.get("start_ms", seg["start_ms"])
            end = src.get("end_ms", seg["end_ms"])
            stamp = format_clock(start)
            url, tpl = self.video.get("sharepoint_url"), self.video.get("link_template")
            if url and tpl:
                link, link_kind = _fmt(tpl, url=url, seconds=start // 1000, ms=start, timestamp=stamp), "timestamp"
            else:
                link, link_kind = url, ("file" if url else "none")
            excerpt = seg["text"] if len(seg["text"]) <= 280 else seg["text"][:277] + "…"
            out |= {"title": self.video.get("title") or sid, "label": f"{self.video.get('title') or sid} · {stamp}",
                    "url": link, "link_kind": link_kind, "segment_id": src["segment_id"],
                    "start_ms": start, "end_ms": end, "timestamp": stamp, "excerpt": excerpt}
        else:
            meta = self.slides[sid] if kind == "slide" else self.syllabus
            page = src["pdf_page"]
            url, tpl = meta.get("sharepoint_url"), meta.get("page_link_template")
            if url and tpl:
                link, link_kind = _fmt(tpl, url=url, page=page), "page"
            else:
                link, link_kind = url, ("file" if url else "none")
            title = meta.get("title") or sid
            out |= {"title": title, "label": f"{title} · trang {page}", "url": link, "link_kind": link_kind,
                    "pdf_page": page}
            if kind == "slide":
                out["needs_ocr"] = page in self.ctx.slides[sid]["needs_ocr"]
            else:
                out["section_id"] = src.get("section_id")
        if src.get("quote"):
            out["quote"] = src["quote"]
        return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for x in items:
        key = json.dumps(x, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def build_knowledge_points(v: Validation, ctx: Context) -> tuple[list[dict], list[Issue]]:
    resolve = _Resolver(ctx)
    merged: dict[str, dict] = {}
    notes: list[Issue] = []
    for path, data, _digest in v.outputs:
        for i, kp in enumerate(data["knowledge_points"], start=1):
            kid = kp_id(ctx.subject_id, ctx.session_id, kp["title"])
            entry = {
                "knowledge_point_id": kid,
                "title": kp["title"].strip(),
                "summary": kp["summary"].strip(),
                "subject_id": kp["subject_id"],
                "chapter_id": kp["chapter_id"],
                "chapter_id_reason": kp["chapter_id_reason"],
                "session_id": kp["session_id"],
                "existing_knowledge_point_id": kp["existing_knowledge_point_id"],
                "existing_match_reason": kp["existing_match_reason"],
                "sources": [resolve(s) for s in kp["sources"]],
                "verification_flags": [{"kind": f["kind"], "text": f["text"], "note": f.get("note"),
                                        "sources": [resolve(s) for s in f.get("sources") or []]}
                                       for f in kp["verification_flags"]],
                "conflicts": [{"topic": c["topic"], "note": c.get("note"),
                               "claims": [{"source": resolve(cl["source"]), "statement": cl["statement"]}
                                          for cl in c["claims"]]} for c in kp["conflicts"]],
                "review_status": "pending_review",
                "review_notes": kp["review_notes"].strip(),
                "ai_local_ids": [kp["local_id"]],
            }
            if kid not in merged:
                merged[kid] = entry
                continue
            first = merged[kid]
            notes.append(Issue("warning", "duplicate_merged",
                               f"Trùng tiêu đề với {first['ai_local_ids'][0]}: đã gộp làm một điểm ({kid}).",
                               item=i, local_id=kp["local_id"], title=kp["title"], input_file=str(path)))
            first["sources"] = _dedupe(first["sources"] + entry["sources"])
            first["verification_flags"] = _dedupe(first["verification_flags"] + entry["verification_flags"])
            first["conflicts"] = _dedupe(first["conflicts"] + entry["conflicts"])
            first["ai_local_ids"].append(kp["local_id"])
            extra = []
            if entry["summary"] and entry["summary"] != first["summary"]:
                extra.append(f"Tóm tắt của {kp['local_id']} (bản trùng): {entry['summary']}")
            if entry["chapter_id"] != first["chapter_id"]:
                extra.append(f"Bản trùng {kp['local_id']} gán chương {entry['chapter_id'] or 'null'}, "
                             f"khác {first['chapter_id'] or 'null'}: HCNS chọn.")
            if entry["existing_knowledge_point_id"] and not first["existing_knowledge_point_id"]:
                first["existing_knowledge_point_id"] = entry["existing_knowledge_point_id"]
                first["existing_match_reason"] = entry["existing_match_reason"]
            if entry["review_notes"]:
                extra.append(entry["review_notes"])
            first["review_notes"] = " | ".join(x for x in [first["review_notes"], *extra] if x)
    return list(merged.values()), notes


def _md_source(s: dict) -> str:
    kind = {"video": "Video", "slide": "Slide", "syllabus": "Giáo trình"}[s["type"]]
    title = s["title"].strip()
    label = title if title.casefold().startswith(kind.casefold()) else f"{kind} {title}"
    if s["type"] == "video":
        where = f"mốc **{s['timestamp']}**"
        if s["link_kind"] == "timestamp":
            return f"[{label} · {s['timestamp']}]({s['url']}) (`{s['segment_id']}`)"
        if s["link_kind"] == "file":
            return (f"[{label}]({s['url']}), {where} (link chưa nhảy tới đúng đoạn, tua tới mốc này) "
                    f"(`{s['segment_id']}`)")
        return f"{label}, {where} (`{s['segment_id']}`, chưa có link)"
    page = f"trang **{s['pdf_page']}**"
    extra = " ⚠ trang không có lớp chữ, mở PDF để xem" if s.get("needs_ocr") else ""
    if s["link_kind"] == "page":
        text = f"[{label} · trang {s['pdf_page']}]({s['url']})"
    elif s["link_kind"] == "file":
        text = f"[{label}]({s['url']}), {page}"
    else:
        text = f"{label}, {page} (chưa có link)"
    if s.get("section_id"):
        text += f" (mục `{s['section_id']}`)"
    return text + extra


def render_markdown(kps: list[dict], ctx: Context, warnings: list[Issue]) -> str:
    man = ctx.meta["manifest"]
    names = program_names()
    programs = ", ".join(names.get(pid, pid) for pid in man.get("programs") or [])
    subject_name = man.get("subject_name") or man["subject_id"]
    subject_order = man.get("subject_order")
    subject_label = (f"Môn chuyên môn số {subject_order}: {subject_name}" if subject_order is not None
                     else f"Môn chuyên môn: {subject_name}")
    lines = [
        f"# {man['session_label']}: điểm kiến thức (chờ rà soát)",
        "",
        "> **BẢN NHÁP – cần HCNS kiểm tra trước khi đưa vào app.** Nội dung do AI tóm tắt từ bài giảng, "
        "slide và giáo trình; mỗi điểm phải được đối chiếu với nguồn ghi bên dưới.",
        "",
        f"- {subject_label}",
        f"- Lộ trình: {programs or '(không có)'}",
        f"- Khoá: `{man['course_id']}` · Buổi: `{man['session_id']}` ({man['session_label']})",
        f"- Số điểm kiến thức: {len(kps)} · Trạng thái: chờ rà soát (`pending_review`)",
        f"- Cảnh báo khi kiểm tra: {len(warnings)} (xem validation-report.md)",
        "",
        "## Mục lục",
        "",
    ]
    for n, kp in enumerate(kps, 1):
        lines.append(f"{n}. [{kp['title']}](#{kp['knowledge_point_id']})")
    lines.append("")
    for n, kp in enumerate(kps, 1):
        chap = kp["chapter_id"]
        lines += [
            f'<a id="{kp["knowledge_point_id"]}"></a>',
            f"## {n}. {kp['title']}",
            "",
            f"- Mã: `{kp['knowledge_point_id']}` (AI: {', '.join(kp['ai_local_ids'])})",
            (f"- Chương: `{chap}` ({ctx.chapter_titles.get(chap, '')})" if chap
             else f"- Chương: **chưa xác định**: {kp['chapter_id_reason']}"),
        ]
        if kp["existing_knowledge_point_id"]:
            lines.append(f"- Có thể trùng điểm đã có `{kp['existing_knowledge_point_id']}`: "
                         f"{kp['existing_match_reason'] or '(AI không ghi lý do)'}")
        lines += ["", kp["summary"], "", "**Nguồn**", ""]
        for s in kp["sources"]:
            lines.append(f"- {_md_source(s)}")
            if s.get("excerpt"):
                lines.append(f"  > {s['excerpt']}")
            if s.get("quote"):
                lines.append(f"  > Trích: {s['quote']}")
        if kp["verification_flags"]:
            lines += ["", "**⚠ Cần đối chiếu**", ""]
            for f in kp["verification_flags"]:
                srcs = "; ".join(_md_source(s) for s in f["sources"]) or "không ghi nguồn"
                lines.append(f"- {FLAG_LABEL[f['kind']]}: \"{f['text']}\""
                             + (f" ({f['note']})" if f.get("note") else "") + f". Nguồn: {srcs}")
        if kp["conflicts"]:
            lines += ["", "**⚠ Các nguồn nói khác nhau (HCNS quyết định)**", ""]
            for c in kp["conflicts"]:
                lines.append(f"- {c['topic']}" + (f" ({c['note']})" if c.get("note") else ""))
                for cl in c["claims"]:
                    lines.append(f"  - {_md_source(cl['source'])}: \"{cl['statement']}\"")
        if kp["review_notes"]:
            lines += ["", f"**Ghi chú cho người rà soát:** {kp['review_notes']}"]
        lines += ["", "Rà soát: [ ] Duyệt  [ ] Sửa  [ ] Loại  · Người rà soát: ______  · Ngày: ______", ""]
    return "\n".join(lines).rstrip() + "\n"


def run_validate_export(inputs: list[Path], out_dir: Path, log=print) -> ExportResult:
    out_dir = Path(out_dir)
    export_dir = out_dir / "export"
    v, ctx = validate(inputs, out_dir)
    md_name = ctx.meta["manifest"]["markdown_filename"]
    kp_path, md_path = export_dir / "knowledge-points.json", export_dir / md_name
    files: list[Path] = []
    removed: list[Path] = []
    kps: list[dict] = []
    if v.ok:
        kps, merge_notes = build_knowledge_points(v, ctx)
        v.issues += merge_notes
    report_json = report_dict(v, ctx)
    write_json(export_dir / "validation-report.json", report_json)
    files.append(export_dir / "validation-report.json")
    if not v.ok:
        for stale in (kp_path, md_path):
            if stale.exists():
                stale.unlink()
                removed.append(stale)
        write_text(export_dir / "validation-report.md", report_markdown(v, ctx, exported=False))
        files.append(export_dir / "validation-report.md")
        return ExportResult(False, export_dir, 0, len(v.errors), len(v.warnings), files, removed)

    man = ctx.meta["manifest"]
    package = {
        "schema_version": "1.0",
        "package": {
            "subject_id": man["subject_id"], "subject_name": man.get("subject_name"),
            "programs": man.get("programs") or [],
            **{key: man[key] for key in ("subject_order", "subject_id_status") if key in man},
            "course_id": man["course_id"], "course_name": man.get("course_name"),
            "session_id": man["session_id"], "session_label": man["session_label"],
            "review_status": "pending_review",
            "generator": f"learning-ingest {__version__}",
            "extract_id": ctx.extract_id,
            "package_ids": sorted({data["package_id"] for _p, data, _d in v.outputs}),
            "input_sha256": [d for _p, _data, d in v.outputs],
        },
        "knowledge_points": kps,
    }
    errors = sorted(jsonschema.Draft202012Validator(resource_json("schemas/knowledge-points.schema.json"))
                    .iter_errors(package), key=lambda e: list(map(str, e.absolute_path)))
    if errors:   # lỗi của chính công cụ, không phải của đầu ra AI
        raise IngestError("Gói import tự kiểm không đạt schema: " + "; ".join(e.message for e in errors[:5]))
    write_json(kp_path, package)
    write_text(md_path, render_markdown(kps, ctx, v.warnings))
    write_text(export_dir / "validation-report.md", report_markdown(v, ctx, exported=True))
    write_json(export_dir / "validation-report.json", report_dict(v, ctx))
    files += [kp_path, md_path, export_dir / "validation-report.md"]
    return ExportResult(True, export_dir, len(kps), 0, len(v.warnings), files, removed)
