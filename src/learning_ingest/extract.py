"""Lệnh extract: manifest -> transcript, slide theo trang, giáo trình, danh mục.

Kết quả trong --out:
  transcript.vtt, transcript.jsonl   segment_id, start_ms, end_ms, text (gói không có video: chỉ
                                     transcript.jsonl rỗng, không có .vtt)
  slides.jsonl                       mỗi dòng một trang (slide .pptx: một slide): source_id, pdf_page, text, needs_ocr
  slides-index.json                  số trang, trang cần rà/OCR, đơn vị (page|slide), theo từng slide
  documents.jsonl                    văn bản .docx: mỗi dòng một mục (section_id, heading, text)
  documents-index.json               tiêu đề và số mục theo từng văn bản
  syllabus.json                      chương, mục, mốc trang của giáo trình
  catalog.json                       danh mục điểm kiến thức đã có (nếu khai báo)
  extract-manifest.json              manifest đã chuẩn hoá, hash đầu vào, extract_id

Chạy lại: file kết quả được ghi đè (không nối thêm), nên không sinh bản ghi
trùng; phần chép lời / trích PDF đọc từ cache nếu đầu vào và cấu hình không đổi.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .asr import FasterWhisperTranscriber, Transcriber, plan_chunks
from .cache import Cache
from .errors import IngestError
from .manifest import Manifest
from .documents import DOCX_EXTRACTOR_VERSION, extract_docx
from .slides import EXTRACTOR_VERSION, PPTX_EXTRACTOR_VERSION, extract_pdf, extract_pptx
from .syllabus import parse_syllabus
from .transcript import Segment, build_segments, clip_cues, read_subtitles, write_transcript
from .util import read_json, sha256_json, write_json, write_jsonl

SYLLABUS_PARSER_VERSION = "md-1"


@dataclass
class ExtractResult:
    out_dir: Path
    segments: int
    transcript_origin: str | None
    slide_pages: int
    pages_needing_ocr: int
    syllabus_sections: int
    extract_id: str
    cache: dict
    warnings: list[str] = field(default_factory=list)
    asr_chunks_run: int = 0
    document_sections: dict = field(default_factory=dict)    # source_id -> số mục
    document_heading_modes: dict = field(default_factory=dict)    # source_id -> styles|bold|none


def _load_catalog(path: Path) -> list[dict]:
    try:
        data = read_json(path)
    except FileNotFoundError:
        raise IngestError(f"Không thấy danh mục điểm kiến thức: {path}") from None
    except ValueError as exc:
        raise IngestError(f"Danh mục {path} không phải JSON hợp lệ: {exc}") from exc
    items = data.get("knowledge_points") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise IngestError(f"Danh mục {path}: cần một mảng, hoặc object có 'knowledge_points'.")
    out = []
    for i, kp in enumerate(items):
        if not isinstance(kp, dict) or not kp.get("knowledge_point_id") or not kp.get("title"):
            raise IngestError(f"Danh mục {path}: mục {i} thiếu knowledge_point_id hoặc title.")
        out.append({
            "knowledge_point_id": str(kp["knowledge_point_id"]),
            "title": str(kp["title"]),
            "subject_id": kp.get("subject_id"),
            "chapter_id": kp.get("chapter_id"),
            "summary": kp.get("summary"),
        })
    ids = [k["knowledge_point_id"] for k in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise IngestError(f"Danh mục {path}: knowledge_point_id trùng: {', '.join(dupes)}")
    return out


def _transcript(m: Manifest, cache: Cache, transcriber: Transcriber | None,
                clip: tuple[int | None, int | None], log) -> tuple[list[Segment], dict, list[str], int]:
    v = m.video
    start, end = clip
    warnings: list[str] = []
    if v.subtitle_path:
        if not v.subtitle_path.exists():
            raise IngestError(f"Không thấy phụ đề: {v.subtitle_path}")
        cues = clip_cues(read_subtitles(v.subtitle_path), start, end)
        if not cues:
            raise IngestError("Đoạn cắt thử không chứa cue nào của phụ đề.")
        log(f"Phụ đề có sẵn: {len(cues)} cue ({v.subtitle_path.name})")
        info = {"origin": "subtitle", "subtitle_sha256": cache.file_sha256(v.subtitle_path)}
        if v.path and not v.path.exists():
            warnings.append(f"Không thấy video {v.path}; dùng phụ đề, link video lấy từ sharepoint_url.")
        return build_segments(cues), info, warnings, 0

    media = v.audio_path or v.path
    if not media or not media.exists():
        raise IngestError(f"Chưa có phụ đề và không thấy file để chép lời: {media}")
    transcriber = transcriber or FasterWhisperTranscriber(m.transcription)
    media_sha = cache.file_sha256(media)
    fp = transcriber.fingerprint()
    lo = start or 0
    if end is None:
        dur_key = cache.key("duration", media_sha)
        cached = cache.get("duration", dur_key)
        end = cached["ms"] if cached else transcriber.duration_ms(media)
        cache.put("duration", dur_key, {"ms": end})
    chunks = plan_chunks(lo, end, m.transcription.chunk_seconds * 1000)
    if not chunks:
        raise IngestError("Đoạn chép lời rỗng (kiểm tra video.clip).")
    raw: list[tuple[int, int, str]] = []
    ran = 0
    for i, (a, b) in enumerate(chunks, 1):
        key = cache.key("asr-chunk", media_sha, a, b, fp)
        got = cache.get("asr-chunk", key)
        if got is None:
            t0 = time.time()
            log(f"Chép lời khúc {i}/{len(chunks)} ({a // 1000}s-{b // 1000}s)…")
            got = [list(x) for x in transcriber.transcribe_range(media, a, b)]
            cache.put("asr-chunk", key, got)
            ran += 1
            log(f"  xong {len(got)} segment trong {time.time() - t0:.0f}s")
        raw += [(int(s), int(e), str(t)) for s, e, t in got]
    info = {"origin": "asr", "media_sha256": media_sha, "media": str(media), "asr": fp,
            "chunks": len(chunks), "chunk_seconds": m.transcription.chunk_seconds}
    return build_segments(raw), info, warnings, ran


def run_extract(m: Manifest, out_dir: Path, cache_dir: Path | None = None, *,
                clip_start_ms: int | None = None, clip_end_ms: int | None = None,
                transcriber: Transcriber | None = None, use_cache: bool = True,
                log=print) -> ExtractResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Cache(cache_dir or out_dir / ".cache", enabled=use_cache)
    v = m.video
    clip = (clip_start_ms if clip_start_ms is not None else (v.clip_start_ms if v else None),
            clip_end_ms if clip_end_ms is not None else (v.clip_end_ms if v else None))
    if clip[0] is not None and clip[1] is not None and clip[1] <= clip[0]:
        raise IngestError("Đoạn cắt thử: điểm kết thúc phải sau điểm bắt đầu.")

    # 1. transcript
    if v is not None:
        segments, t_info, warnings, ran = _transcript(m, cache, transcriber, clip, log)
        if not segments:
            raise IngestError("Không có segment nào sau khi chép lời / đọc phụ đề.")
        write_transcript(out_dir, segments, v.source_id)
        t_info.update(segments=len(segments), clip={"start_ms": clip[0], "end_ms": clip[1]} if any(
            x is not None for x in clip) else None, first_ms=segments[0].start_ms, last_ms=segments[-1].end_ms)
    else:       # gói tài liệu: không có video, không có transcript
        segments, warnings, ran = [], [], 0
        t_info = {"origin": None, "segments": 0, "clip": None, "first_ms": None, "last_ms": None}
        write_jsonl(out_dir / "transcript.jsonl", [])
        (out_dir / "transcript.vtt").unlink(missing_ok=True)

    # 2. slide
    slide_rows, slide_index, inputs_slides = [], {}, {}
    for s in m.slides:
        if not s.path.exists():
            raise IngestError(f"Không thấy slide {s.source_id}: {s.path}")
        sha = cache.file_sha256(s.path)
        if s.path.suffix.lower() == ".pptx":
            kind, version, extractor, unit = "pptx", PPTX_EXTRACTOR_VERSION, extract_pptx, "slide"
        else:
            kind, version, extractor, unit = "pdf", EXTRACTOR_VERSION, extract_pdf, "page"
        key = cache.key(kind, sha, s.source_id, version)
        doc = cache.get(kind, key)
        if doc is None:
            doc = extractor(s.path, s.source_id)
            cache.put(kind, key, doc)
        slide_rows += doc["pages"]
        ocr = [p["pdf_page"] for p in doc["pages"] if p["needs_ocr"]]
        slide_index[s.source_id] = {"title": s.title, "page_count": doc["page_count"], "pages_needing_ocr": ocr,
                                    "unit": unit}
        inputs_slides[s.source_id] = sha
        if ocr:
            what = "slide thiếu chữ" if unit == "slide" else "trang thiếu lớp chữ"
            warnings.append(f"{s.source_id}: {len(ocr)} {what}, cần rà/OCR: {ocr}")
    write_jsonl(out_dir / "slides.jsonl", slide_rows)
    write_json(out_dir / "slides-index.json", slide_index)

    # 2b. văn bản .docx
    doc_rows, doc_index, inputs_docs = [], {}, {}
    for d in m.documents:
        if not d.path.exists():
            raise IngestError(f"Không thấy văn bản {d.source_id}: {d.path}")
        sha = cache.file_sha256(d.path)
        key = cache.key("docx", sha, d.source_id, DOCX_EXTRACTOR_VERSION)
        doc = cache.get("docx", key)
        if doc is None:
            doc = extract_docx(d.path, d.source_id)
            cache.put("docx", key, doc)
        doc_rows += doc["sections"]
        doc_index[d.source_id] = {"title": d.title, "section_count": doc["section_count"],
                                  "heading_mode": doc.get("heading_mode")}
        inputs_docs[d.source_id] = sha
    write_jsonl(out_dir / "documents.jsonl", doc_rows)
    write_json(out_dir / "documents-index.json", doc_index)

    # 3. giáo trình
    syllabus = None
    syllabus_sha = None
    if m.syllabus:
        if not m.syllabus.path.exists():
            raise IngestError(f"Không thấy giáo trình: {m.syllabus.path}")
        syllabus_sha = cache.file_sha256(m.syllabus.path)
        syllabus = parse_syllabus(m.syllabus.path, m.syllabus.source_id,
                                  m.syllabus.page_marker_pattern, m.syllabus.chapters)
        if syllabus["subject_id"] and syllabus["subject_id"] != m.subject_id:
            warnings.append(f"Front matter giáo trình ghi subject_id={syllabus['subject_id']}, "
                            f"manifest ghi {m.subject_id}.")
        warnings += syllabus["warnings"]
        unknown = [c for c in m.related_chapter_ids if c not in {x["chapter_id"] for x in syllabus["chapters"]}]
        if unknown:
            raise IngestError(f"related_chapter_ids không có trong giáo trình: {', '.join(unknown)}")
    elif m.related_chapter_ids:
        raise IngestError("related_chapter_ids cần khai báo syllabus.")
    write_json(out_dir / "syllabus.json", syllabus or {"source_id": None, "chapters": [], "sections": [],
                                                       "chapter_candidates": [], "pages_found": [],
                                                       "pdf_page_count": None})

    # 4. danh mục điểm kiến thức đã có
    catalog = _load_catalog(m.catalog_path) if m.catalog_path else []
    write_json(out_dir / "catalog.json", {"knowledge_points": catalog})

    hashed = {
        "manifest": m.public_dict() | {"manifest_path": None},
        "slides": slide_rows, "syllabus": syllabus, "catalog": catalog,
    }
    if v is not None:
        hashed["transcript"] = [s.to_row(v.source_id) for s in segments]
    if doc_rows:
        hashed["documents"] = doc_rows
    extract_id = "ext-" + sha256_json(hashed)[:16]
    write_json(out_dir / "extract-manifest.json", {
        "tool": "learning-ingest",
        "version": __version__,
        "extract_id": extract_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manifest": m.public_dict(),
        "inputs": {
            "slides": inputs_slides,
            **({"documents": inputs_docs} if inputs_docs else {}),
            "syllabus": syllabus_sha,
            "catalog": cache.file_sha256(m.catalog_path) if m.catalog_path else None,
        },
        "transcript": t_info,
        "slides": slide_index,
        "documents": doc_index,
        "syllabus": None if syllabus is None else {
            "chapters": len(syllabus["chapters"]), "sections": len(syllabus["sections"]),
            "pages_found": len(syllabus["pages_found"]),
        },
        "catalog": len(catalog),
        "cache": cache.stats(),
        "warnings": warnings,
    })
    return ExtractResult(
        out_dir=out_dir, segments=len(segments), transcript_origin=t_info["origin"],
        slide_pages=len(slide_rows), pages_needing_ocr=sum(len(v["pages_needing_ocr"]) for v in slide_index.values()),
        syllabus_sections=len(syllabus["sections"]) if syllabus else 0, extract_id=extract_id,
        cache=cache.stats(), warnings=warnings, asr_chunks_run=ran,
        document_sections={sid: info["section_count"] for sid, info in doc_index.items()},
        document_heading_modes={sid: info["heading_mode"] for sid, info in doc_index.items()},
    )


def load_extracted(out_dir: Path) -> dict:
    """Dữ liệu extract đã ghi, cho prepare-review và validate-export."""
    out_dir = Path(out_dir)
    meta_path = out_dir / "extract-manifest.json"
    if not meta_path.exists():
        raise IngestError(f"Chưa có {meta_path}. Chạy 'extract' với cùng --out trước.")
    from .util import read_jsonl
    meta = read_json(meta_path)
    docs_path, docs_index_path = out_dir / "documents.jsonl", out_dir / "documents-index.json"
    return {
        "meta": meta,
        "segments": read_jsonl(out_dir / "transcript.jsonl"),
        "slides": read_jsonl(out_dir / "slides.jsonl"),
        "slides_index": read_json(out_dir / "slides-index.json"),
        "documents": read_jsonl(docs_path) if docs_path.exists() else [],
        "documents_index": read_json(docs_index_path) if docs_index_path.exists() else {},
        "syllabus": read_json(out_dir / "syllabus.json"),
        "catalog": read_json(out_dir / "catalog.json")["knowledge_points"],
    }
