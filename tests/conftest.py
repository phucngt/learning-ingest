import json
from pathlib import Path

import pytest

from learning_ingest.extract import run_extract
from learning_ingest.manifest import load_manifest
from learning_ingest.review import run_prepare_review

FIXTURES = Path(__file__).parent / "fixtures" / "pilot-fake"


@pytest.fixture
def manifest():
    return load_manifest(FIXTURES / "manifest.yaml")


@pytest.fixture
def prepared(tmp_path, manifest):
    out = tmp_path / "out"
    run_extract(manifest, out, log=lambda _: None)
    run_prepare_review(manifest, out, log=lambda _: None)
    return out


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class FakeTranscriber:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def fingerprint(self):
        return {"engine": "fake", "version": 1}

    def duration_ms(self, media):
        return 1_500_000

    def transcribe_range(self, media, start_ms, end_ms):
        self.calls.append((start_ms, end_ms))
        if len(self.calls) == self.fail_on:
            raise RuntimeError("simulated interruption")
        return [(start_ms, start_ms + 2000, "Nội dung giả lập")]


def asr_manifest(tmp_path, *, declared_clip=True):
    media = tmp_path / "dummy.mp4"
    media.write_bytes(b"fake media, never decoded")
    video = {"source_id": "video-fake-asr", "path": media.name}
    if declared_clip:
        video["clip"] = {"start": "00:10:00", "end": "00:25:00"}
    data = {
        "schema_version": 1,
        "subject_id": "phap-luat-chung-khoan",
        "course_id": "fake-course",
        "session_id": "fake-session",
        "session_label": "Buổi giả lập",
        "video": video,
        "transcription": {"chunk_seconds": 600},
    }
    path = write_json(tmp_path / "asr-manifest.json", data)
    return load_manifest(path)
