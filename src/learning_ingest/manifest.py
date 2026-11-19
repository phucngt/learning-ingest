"""Manifest của một buổi học (YAML hoặc JSON), kiểm tra theo
schemas/manifest.schema.json. Đường dẫn tương đối tính từ thư mục manifest."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import jsonschema
import yaml

from .errors import IngestError
from .registry import load_registry, subject
from .timeutil import parse_timestamp
from .util import resource_json, slugify


@dataclass(frozen=True)
class VideoSource:
    source_id: str
    title: str
    path: Path | None
    audio_path: Path | None
    subtitle_path: Path | None
    sharepoint_url: str | None
    link_template: str | None
    clip_start_ms: int | None
    clip_end_ms: int | None


@dataclass(frozen=True)
class PdfSource:
    source_id: str
    title: str
    path: Path
    sharepoint_url: str | None
    page_link_template: str | None


@dataclass(frozen=True)
class SyllabusSource:
    source_id: str
    title: str
    path: Path
    sharepoint_url: str | None
    page_link_template: str | None
    page_marker_pattern: str | None
    chapters: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptionConfig:
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "vi"
    beam_size: int = 5
    vad_filter: bool = True
    chunk_seconds: int = 600
    model_dir: str | None = None
    initial_prompt: str | None = None


@dataclass(frozen=True)
class ReviewConfig:
    chunk_minutes: int = 10
    max_chars_per_part: int = 150_000
    syllabus_max_sections: int = 12
    syllabus_max_chars: int = 40_000


@dataclass(frozen=True)
class Manifest:
    path: Path
    subject_id: str
    subject_name: str
    programs: list[str]
    subject_order: int
    subject_id_status: str
    course_id: str
    course_name: str | None
    session_id: str
    session_label: str
    video: VideoSource
    slides: list[PdfSource]
    syllabus: SyllabusSource | None
    related_chapter_ids: list[str]
    catalog_path: Path | None
    transcription: TranscriptionConfig
    review: ReviewConfig
    markdown_filename: str
    raw: dict = field(repr=False, default_factory=dict)

    def public_dict(self) -> dict:
        """Phần manifest ghi vào extract-manifest.json: ID, tên, link, mẫu link.
        Bước validate-export chỉ cần thư mục --out, nên mọi thứ nó cần nằm ở đây."""
        def src(d: dict) -> dict:
            return {k: (str(v) if isinstance(v, Path) else v) for k, v in d.items()}
        return {
            "manifest_path": str(self.path),
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "programs": self.programs,
            "subject_order": self.subject_order,
            "subject_id_status": self.subject_id_status,
            "course_id": self.course_id,
            "course_name": self.course_name,
            "session_id": self.session_id,
            "session_label": self.session_label,
            "video": src(asdict(self.video)),
            "slides": [src(asdict(s)) for s in self.slides],
            "syllabus": src(asdict(self.syllabus)) if self.syllabus else None,
            "related_chapter_ids": self.related_chapter_ids,
            "markdown_filename": self.markdown_filename,
        }


def _load_raw(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise IngestError(f"Không thấy manifest: {path}") from None
    try:
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise IngestError(f"Manifest {path} không đọc được: {exc}") from exc
    if not isinstance(data, dict):
        raise IngestError(f"Manifest {path} phải là một object.")
    return data


def _check_schema(data: dict, path: Path) -> None:
    validator = jsonschema.Draft202012Validator(resource_json("schemas/manifest.schema.json"))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"  - {'/'.join(str(p) for p in e.absolute_path) or '(gốc)'}: {e.message}" for e in errors]
        raise IngestError(f"Manifest {path} sai cấu trúc:\n" + "\n".join(lines))


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path).resolve()
    data = _load_raw(path)
    _check_schema(data, path)
    sid = data["subject_id"]
    canonical = subject(sid)
    if canonical is None:
        valid = ", ".join(item["subject_id"] for item in load_registry()["subjects"])
        raise IngestError(f"subject_id không có trong danh mục: {sid}. Mã hợp lệ: {valid}.")
    programs = list(canonical["programs"])
    if "programs" in data and set(data["programs"]) != set(programs):
        raise IngestError(f"programs của {sid} không khớp danh mục: manifest {data['programs']}, danh mục {programs}.")
    name = data.get("subject_name")
    if "subject_name" in data and name != canonical["name"]:
        raise IngestError(f"subject_name của {sid} không khớp danh mục: manifest {name!r}, danh mục {canonical['name']!r}.")

    base = path.parent

    def p(value) -> Path | None:
        return (base / value).resolve() if value else None

    v = data["video"]
    clip = v.get("clip") or {}
    try:
        clip_start = parse_timestamp(clip["start"]) if clip.get("start") not in (None, "") else None
        clip_end = parse_timestamp(clip["end"]) if clip.get("end") not in (None, "") else None
    except ValueError as exc:
        raise IngestError(f"video.clip: {exc}") from exc
    if clip_start is not None and clip_end is not None and clip_end <= clip_start:
        raise IngestError("video.clip: end phải sau start.")
    video = VideoSource(
        source_id=v["source_id"], title=v.get("title") or v["source_id"],
        path=p(v.get("path")), audio_path=p(v.get("audio_path")), subtitle_path=p(v.get("subtitle_path")),
        sharepoint_url=v.get("sharepoint_url"), link_template=v.get("link_template"),
        clip_start_ms=clip_start, clip_end_ms=clip_end,
    )
    if not (video.subtitle_path or video.path or video.audio_path):
        raise IngestError("video: cần subtitle_path, hoặc path / audio_path để chép lời.")

    slides = [PdfSource(source_id=s["source_id"], title=s.get("title") or s["source_id"], path=p(s["path"]),
                        sharepoint_url=s.get("sharepoint_url"), page_link_template=s.get("page_link_template"))
              for s in data.get("slides") or []]
    sy = data.get("syllabus")
    syllabus = SyllabusSource(
        source_id=sy["source_id"], title=sy.get("title") or sy["source_id"], path=p(sy["path"]),
        sharepoint_url=sy.get("sharepoint_url"), page_link_template=sy.get("page_link_template"),
        page_marker_pattern=sy.get("page_marker_pattern"), chapters=list(sy.get("chapters", [])),
    ) if sy else None

    ids = [video.source_id] + [s.source_id for s in slides] + ([syllabus.source_id] if syllabus else [])
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise IngestError(f"source_id bị trùng: {', '.join(dupes)}")

    label = data["session_label"]
    md_name = (data.get("export") or {}).get("markdown_filename") or f"{slugify(label)}-tri-thuc.md"
    return Manifest(
        path=path,
        subject_id=sid, subject_name=canonical["name"], programs=programs,
        subject_order=canonical["order"], subject_id_status=canonical["id_status"],
        course_id=data["course_id"], course_name=data.get("course_name"),
        session_id=data["session_id"], session_label=label,
        video=video, slides=slides, syllabus=syllabus,
        related_chapter_ids=list(data.get("related_chapter_ids") or []),
        catalog_path=p(data.get("catalog_path")),
        transcription=TranscriptionConfig(**(data.get("transcription") or {})),
        review=ReviewConfig(**(data.get("review") or {})),
        markdown_filename=md_name,
        raw=data,
    )
