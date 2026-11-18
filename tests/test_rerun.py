import json

import pytest

from learning_ingest.cli import main
from learning_ingest.extract import run_extract
from learning_ingest.export import run_validate_export
from learning_ingest.review import run_prepare_review
from conftest import FIXTURES, FakeTranscriber, asr_manifest, read_json, write_json


def test_extract_repeated_is_byte_identical(tmp_path, manifest):
    out = tmp_path / "out"
    run_extract(manifest, out, log=lambda _: None)
    names = ["transcript.jsonl", "transcript.vtt", "slides.jsonl"]
    before = {name: (out / name).read_bytes() for name in names}
    result = run_extract(manifest, out, log=lambda _: None)
    assert before == {name: (out / name).read_bytes() for name in names}
    transcript = [json.loads(line) for line in (out / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    slides = [json.loads(line) for line in (out / "slides.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({x["segment_id"] for x in transcript}) == len(transcript)
    assert len({(x["source_id"], x["pdf_page"]) for x in slides}) == len(slides)
    assert result.cache["hits"]["pdf"] == 2


def test_asr_cached_run_makes_zero_calls(tmp_path):
    m = asr_manifest(tmp_path)
    out = tmp_path / "out"
    run_extract(m, out, transcriber=FakeTranscriber(), log=lambda _: None)
    fake = FakeTranscriber()
    result = run_extract(m, out, transcriber=fake, log=lambda _: None)
    assert fake.calls == []
    assert result.asr_chunks_run == 0
    assert result.cache["hits"]["asr-chunk"] == 2


def test_resume_only_missing_chunk(tmp_path):
    m = asr_manifest(tmp_path)
    out = tmp_path / "out"
    first = FakeTranscriber(fail_on=2)
    with pytest.raises(RuntimeError, match="interruption"):
        run_extract(m, out, transcriber=first, log=lambda _: None)
    resumed = FakeTranscriber()
    result = run_extract(m, out, transcriber=resumed, log=lambda _: None)
    assert resumed.calls == [(1200000, 1500000)]
    assert result.asr_chunks_run == 1
    assert result.segments == 2


def test_prepare_package_id_stable(prepared, manifest):
    first = read_json(prepared / "review" / "review-manifest.json")["package_id"]
    second = run_prepare_review(manifest, prepared, log=lambda _: None)
    assert second.package_id == first


def test_export_bytes_and_ids_stable(prepared, manifest):
    path = FIXTURES / "ai-output-valid.json"
    assert run_validate_export([path], prepared).ok
    names = ["knowledge-points.json", manifest.markdown_filename]
    before = {n: (prepared / "export" / n).read_bytes() for n in names}
    ids = [p["knowledge_point_id"] for p in read_json(prepared / "export" / names[0])["knowledge_points"]]
    assert run_validate_export([path], prepared).ok
    assert before == {n: (prepared / "export" / n).read_bytes() for n in names}
    assert ids == [p["knowledge_point_id"] for p in read_json(prepared / "export" / names[0])["knowledge_points"]]


def test_duplicate_title_merges_sources_with_warning(prepared):
    result = run_validate_export([FIXTURES / "ai-output-duplicate.json"], prepared)
    assert result.ok and result.knowledge_points == 1
    points = read_json(prepared / "export" / "knowledge-points.json")["knowledge_points"]
    sources = points[0]["sources"]
    assert len(sources) == 2
    assert {(source["type"], source["source_id"]) for source in sources} == {
        ("video", "video-ngay-2"), ("syllabus", "giao-trinh-luat"),
    }
    assert next(source for source in sources if source["type"] == "video")["segment_id"] == "seg-003006-000"
    assert next(source for source in sources if source["type"] == "syllabus")["pdf_page"] == 80
    assert points[0]["ai_local_ids"] == ["dup-001", "dup-002"]
    issues = read_json(prepared / "export" / "validation-report.json")["issues"]
    assert any(i["code"] == "duplicate_merged" and i["level"] == "warning" for i in issues)


def test_split_review_and_repeated_input_recombine(tmp_path, prepared, manifest):
    result = run_prepare_review(manifest, prepared, max_chars=1000, log=lambda _: None)
    assert len(result.parts) >= 2
    part_count = len(result.parts)
    assert [part.name for part in result.parts] == [
        f"package-part-{index:02d}-of-{part_count:02d}.md" for index in range(1, part_count + 1)
    ]
    assert not (prepared / "review" / "package.md").exists()
    data = read_json(FIXTURES / "ai-output-valid.json")
    parts = []
    for index, points in enumerate([data["knowledge_points"][:2], data["knowledge_points"][2:]]):
        path = tmp_path / f"part-{index}.json"
        parts.append(write_json(path, dict(data, knowledge_points=points)))
    args = ["validate-export", "--out", str(prepared)]
    for path in parts:
        args.extend(["--input", str(path)])
    assert main(args) == 0
    exported = read_json(prepared / "export" / "knowledge-points.json")["knowledge_points"]
    assert len(exported) == 5
    assert {(point["ai_local_ids"][0], point["title"]) for point in exported} == {
        (point["local_id"], point["title"]) for point in data["knowledge_points"]
    }
