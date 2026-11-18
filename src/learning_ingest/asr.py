"""Chép lời bằng faster-whisper khi chưa có phụ đề.

- Mặc định CPU / int8, language=vi; model cấu hình trong manifest.
- MP4 đọc trực tiếp qua PyAV (đi kèm faster-whisper), không cần ffmpeg. Nếu
  không decode được, tách âm thanh ra file riêng và khai báo video.audio_path.
- Chép theo khúc (transcription.chunk_seconds). Mỗi khúc chỉ giải mã đúng
  đoạn âm thanh của nó (seek), nên video 3 giờ không phải nạp hết vào RAM, và
  extract.py cache từng khúc: chạy lại sau khi dừng giữa chừng thì làm tiếp
  từ khúc chưa xong.
- Mốc trả về tính theo video gốc (đã cộng vị trí đầu khúc).

Giới hạn: một câu nói vắt qua ranh giới khúc có thể bị cắt làm hai segment.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from .errors import IngestError, MissingDependency
from .manifest import TranscriptionConfig

SAMPLE_RATE = 16_000


class Transcriber(Protocol):
    def fingerprint(self) -> dict:
        """Mọi thứ ảnh hưởng tới kết quả chép lời; đưa vào khoá cache."""

    def duration_ms(self, media: Path) -> int:
        ...

    def transcribe_range(self, media: Path, start_ms: int, end_ms: int) -> list[tuple[int, int, str]]:
        """Segment trong [start_ms, end_ms), mốc theo media gốc."""


def plan_chunks(start_ms: int, end_ms: int, chunk_ms: int) -> list[tuple[int, int]]:
    if end_ms <= start_ms:
        return []
    out, at = [], start_ms
    while at < end_ms:
        out.append((at, min(at + chunk_ms, end_ms)))
        at += chunk_ms
    return out


def _import_av():
    try:
        import av  # noqa: F401  (PyAV, cài cùng faster-whisper)
    except ImportError:
        raise MissingDependency(
            "Chưa cài faster-whisper / PyAV. Cài: pip install -e \".[asr]\" "
            "(hoặc cung cấp phụ đề VTT/SRT qua video.subtitle_path).") from None
    return av


def media_duration_ms(media: Path) -> int:
    av = _import_av()
    try:
        with av.open(str(media)) as container:
            if container.duration:
                return int(container.duration * 1000 / av.time_base)
            stream = container.streams.audio[0]
            if stream.duration and stream.time_base:
                return int(float(stream.duration * stream.time_base) * 1000)
    except (av.error.FFmpegError, IndexError, OSError) as exc:
        raise IngestError(f"Không đọc được {media}: {exc}. Tách âm thanh ra file riêng và khai báo video.audio_path.") from exc
    raise IngestError(f"Không xác định được độ dài {media}. Khai báo video.clip.end.")


def load_audio_range(media: Path, start_ms: int, end_ms: int):
    """Âm thanh mono 16 kHz float32 của [start_ms, end_ms) (numpy array)."""
    av = _import_av()
    import numpy as np

    try:
        container = av.open(str(media))
    except (av.error.FFmpegError, OSError) as exc:
        raise IngestError(f"Không mở được {media}: {exc}") from exc
    with container:
        if not container.streams.audio:
            raise IngestError(f"{media} không có luồng âm thanh.")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        if start_ms > 0:
            # seek tới khung khoá <= start, rồi bỏ phần thừa ở dưới
            container.seek(int(start_ms / 1000 / stream.time_base), stream=stream, backward=True)
        pieces = []
        base_ms = None
        try:
            for frame in container.decode(stream):
                if frame.pts is None:
                    continue
                t_ms = float(frame.pts * stream.time_base) * 1000
                if t_ms >= end_ms:
                    break
                frame_ms = frame.samples * 1000 / frame.sample_rate
                if t_ms + frame_ms <= start_ms:
                    continue
                if base_ms is None:
                    base_ms = t_ms
                for out in resampler.resample(frame):
                    pieces.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                pieces.append(out.to_ndarray().reshape(-1))
        except av.error.FFmpegError as exc:
            raise IngestError(f"Lỗi giải mã âm thanh {media}: {exc}. Thử tách âm thanh ra file riêng (video.audio_path).") from exc
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(pieces).astype(np.float32) / 32768.0
    skip = max(0, int(round((start_ms - (base_ms or start_ms)) * SAMPLE_RATE / 1000)))
    keep = int(round((end_ms - start_ms) * SAMPLE_RATE / 1000))
    return audio[skip:skip + keep]


class FasterWhisperTranscriber:
    def __init__(self, cfg: TranscriptionConfig):
        self.cfg = cfg
        self._model = None

    def _faster_whisper(self):
        try:
            import faster_whisper
        except ImportError:
            raise MissingDependency(
                "Chưa cài faster-whisper. Cài: pip install -e \".[asr]\" "
                "(hoặc cung cấp phụ đề VTT/SRT qua video.subtitle_path).") from None
        return faster_whisper

    def fingerprint(self) -> dict:
        fw = self._faster_whisper()
        cfg = asdict(self.cfg)
        cfg.pop("model_dir", None)      # nơi để model không đổi kết quả
        cfg.pop("chunk_seconds", None)  # đã nằm trong khoá từng khúc
        return {"engine": "faster-whisper", "engine_version": getattr(fw, "__version__", "?"), **cfg}

    @property
    def model(self):
        if self._model is None:
            fw = self._faster_whisper()
            try:
                self._model = fw.WhisperModel(self.cfg.model, device=self.cfg.device,
                                              compute_type=self.cfg.compute_type,
                                              download_root=self.cfg.model_dir)
            except Exception as exc:   # tải model / ctranslate2 báo đủ loại lỗi
                raise IngestError(f"Không nạp được model '{self.cfg.model}': {type(exc).__name__}: {exc}") from exc
        return self._model

    def duration_ms(self, media: Path) -> int:
        return media_duration_ms(media)

    def transcribe_range(self, media: Path, start_ms: int, end_ms: int) -> list[tuple[int, int, str]]:
        audio = load_audio_range(media, start_ms, end_ms)
        if audio.size == 0:
            return []
        segments, _info = self.model.transcribe(
            audio,
            language=self.cfg.language,
            beam_size=self.cfg.beam_size,
            vad_filter=self.cfg.vad_filter,
            initial_prompt=self.cfg.initial_prompt,
            condition_on_previous_text=False,   # tránh lặp câu kéo dài qua cả khúc
        )
        out = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            a = start_ms + int(round(seg.start * 1000))
            b = min(end_ms, start_ms + int(round(seg.end * 1000)))
            out.append((a, max(a, b), text))
        return out
