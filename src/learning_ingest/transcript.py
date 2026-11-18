"""Transcript: đọc VTT/SRT, dựng segment có ID, ghi transcript.vtt / .jsonl."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import IngestError
from .timeutil import format_vtt, parse_timestamp, segment_id_for
from .util import write_jsonl, write_text

_TIMING = re.compile(r"^\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?$")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Segment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str

    def to_row(self, source_id: str) -> dict:
        return {
            "segment_id": self.segment_id,
            "source_id": source_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "start": format_vtt(self.start_ms),
            "end": format_vtt(self.end_ms),
            "text": self.text,
        }


def parse_subtitle_text(text: str) -> list[tuple[int, int, str]]:
    """Cue của VTT hoặc SRT -> [(start_ms, end_ms, text)]. Bỏ header WEBVTT,
    NOTE/STYLE, số thứ tự cue, thẻ <v ...>/<c>/<i>; nhiều dòng gộp làm một."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.split("\n")
        at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if at is None:
            continue
        m = _TIMING.match(lines[at])
        if not m:
            raise ValueError(f"dòng thời gian không đọc được: {lines[at].strip()!r}")
        start, end = parse_timestamp(m.group(1)), parse_timestamp(m.group(2))
        if end < start:
            raise ValueError(f"cue kết thúc trước khi bắt đầu: {lines[at].strip()!r}")
        body = " ".join(_TAG.sub("", line).strip() for line in lines[at + 1:] if line.strip())
        body = _SPACE.sub(" ", html.unescape(body)).strip()
        if body:
            cues.append((start, end, body))
    return cues


def read_subtitles(path: Path) -> list[tuple[int, int, str]]:
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError(f"Phụ đề {path} không phải UTF-8: {exc}") from exc
    try:
        cues = parse_subtitle_text(raw)
    except ValueError as exc:
        raise IngestError(f"Phụ đề {path}: {exc}") from exc
    if not cues:
        raise IngestError(f"Phụ đề {path} không có cue nào.")
    return cues


def clip_cues(cues: Iterable[tuple[int, int, str]], start_ms: int | None,
              end_ms: int | None) -> list[tuple[int, int, str]]:
    """Giữ các cue chạm vào đoạn [start_ms, end_ms). Mốc giữ nguyên theo video gốc."""
    lo = start_ms or 0
    hi = end_ms if end_ms is not None else float("inf")
    return [(s, e, t) for s, e, t in cues if e > lo and s < hi]


def build_segments(raw: Iterable[tuple[int, int, str]]) -> list[Segment]:
    """Sắp theo thời gian, bỏ cue rỗng và cue trùng y hệt, gán segment_id theo
    mốc bắt đầu (hai cue cùng mốc: thêm hậu tố -2, -3)."""
    seen: set[tuple[int, int, str]] = set()
    items = []
    for start, end, text in sorted(raw):
        text = _SPACE.sub(" ", text).strip()
        key = (start, end, text)
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(key)
    used: dict[str, int] = {}
    segments = []
    for start, end, text in items:
        base = segment_id_for(start)
        n = used.get(base, 0) + 1
        used[base] = n
        segments.append(Segment(base if n == 1 else f"{base}-{n}", start, max(start, end), text))
    return segments


def write_transcript(out_dir: Path, segments: list[Segment], source_id: str) -> None:
    vtt = ["WEBVTT", ""]
    for seg in segments:
        vtt += [seg.segment_id, f"{format_vtt(seg.start_ms)} --> {format_vtt(seg.end_ms)}", seg.text, ""]
    write_text(out_dir / "transcript.vtt", "\n".join(vtt))
    write_jsonl(out_dir / "transcript.jsonl", (s.to_row(source_id) for s in segments))
