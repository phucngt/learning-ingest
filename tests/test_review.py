from learning_ingest.extract import run_extract
from learning_ingest.review import run_prepare_review
from conftest import FakeTranscriber, asr_manifest, read_json


def test_prepare_review_subtitle_note(prepared):
    review = prepared / "review"
    assert read_json(review / "review-manifest.json")["prompt_version"] == "kp-prompt-3"
    assert (
        "- Transcript: Transcript lấy từ phụ đề có sẵn; vẫn đối chiếu thuật ngữ với slide và giáo trình."
        in (review / "package.md").read_text(encoding="utf-8")
    )


def test_prepare_review_asr_note(tmp_path):
    manifest = asr_manifest(tmp_path)
    out = tmp_path / "out"
    extracted = run_extract(manifest, out, transcriber=FakeTranscriber(), log=lambda _: None)
    assert extracted.transcript_origin == "asr"
    raw = (out / "transcript.jsonl").read_bytes()
    result = run_prepare_review(manifest, out, log=lambda _: None)
    package = result.parts[0].read_text(encoding="utf-8")
    for fragment in [
        "- Transcript: Transcript do máy chép lời (faster-whisper)",
        "'tài dính' thay cho 'tài chính', 'chào bản' thay cho 'chào bán'",
        "Trường quote (nếu có) chép nguyên văn transcript, không sửa.",
        "ghi vào review_notes và thêm verification_flags; không tự đoán con số.",
    ]:
        assert fragment in package
    assert (out / "transcript.jsonl").read_bytes() == raw
