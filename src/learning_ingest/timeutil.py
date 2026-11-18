"""Mốc thời gian: đọc, định dạng và segment_id.

Mọi mốc tính bằng mili giây kể từ đầu video gốc, kể cả khi chỉ chép lời thử
một đoạn: đoạn 00:10:00-00:20:00 cho các segment bắt đầu từ 600000 ms, không
phải từ 0. Nhờ vậy mốc trong tài liệu luôn tua được trên video gốc.
"""
from __future__ import annotations

import re

_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")
_SECONDS = re.compile(r"^\d+(?:\.\d+)?$")


def parse_timestamp(value) -> int:
    """'01:02:03.450', '01:02:03,450' (SRT), '02:03.450' (VTT ngắn), '3723.45'
    (giây) hoặc số -> mili giây. Sai định dạng -> ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"mốc thời gian không hợp lệ: {value!r}")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"mốc thời gian âm: {value!r}")
        return int(round(value * 1000))
    s = str(value).strip()
    if _SECONDS.match(s):
        return int(round(float(s) * 1000))
    m = _CLOCK.match(s)
    if not m:
        raise ValueError(f"mốc thời gian không hợp lệ: {value!r}")
    hours = int(m.group(1) or 0)
    minutes, seconds = int(m.group(2)), int(m.group(3))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"mốc thời gian không hợp lệ: {value!r}")
    frac = (m.group(4) or "0").ljust(3, "0")[:3]
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(frac)


def _split(ms: int) -> tuple[int, int, int, int]:
    if ms < 0:
        raise ValueError(f"mốc thời gian âm: {ms}")
    hours, rest = divmod(int(ms), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return hours, minutes, seconds, millis


def format_vtt(ms: int) -> str:
    h, m, s, x = _split(ms)
    return f"{h:02d}:{m:02d}:{s:02d}.{x:03d}"


def format_srt(ms: int) -> str:
    return format_vtt(ms).replace(".", ",")


def format_clock(ms: int) -> str:
    """Mốc đọc được cho người: 'HH:MM:SS' (bỏ phần mili giây)."""
    h, m, s, _ = _split(ms)
    return f"{h:02d}:{m:02d}:{s:02d}"


def segment_id_for(start_ms: int) -> str:
    """ID ổn định theo vị trí trong video: 00:12:03.120 -> 'seg-001203-120'.
    Chép lời lại cùng nội dung cho cùng ID, nên nguồn AI trích không bị lệch."""
    h, m, s, x = _split(start_ms)
    return f"seg-{h:02d}{m:02d}{s:02d}-{x:03d}"
