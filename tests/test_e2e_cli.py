from pathlib import Path

import pytest
import yaml

from learning_ingest.cli import main
from learning_ingest.manifest import load_manifest
from conftest import FIXTURES, read_json


def test_full_cli(tmp_path):
    out = tmp_path / "out"
    assert main(["extract", "--manifest", str(FIXTURES / "manifest.yaml"), "--out", str(out)]) == 0
    assert main(["prepare-review", "--manifest", str(FIXTURES / "manifest.yaml"), "--out", str(out)]) == 0
    assert main(["validate-export", "--input", str(FIXTURES / "ai-output-valid.json"), "--out", str(out)]) == 0
    markdown = (out / "export" / "buoi-02-tri-thuc.md").read_text(encoding="utf-8")
    for text in ["mốc **00:01:02**", "https://example.sharepoint.com/sites/hcns/fake/ngay-2.mp4)",
                 "#page=2", "chưa có link", "BẢN NHÁP", "Cần đối chiếu", "Các nguồn nói khác nhau"]:
        assert text in markdown

    assert "Môn chuyên môn số 1: Pháp luật về chứng khoán và thị trường chứng khoán" in markdown
    assert "Môi giới chứng khoán, Phân tích tài chính, Quản lý quỹ" in markdown
    assert "Giáo trình Luật Mẫu" in markdown
    assert "Giáo trình Giáo trình" not in markdown
    exported = read_json(out / "export" / "knowledge-points.json")
    assert len(exported["knowledge_points"]) == 5
    assert exported["package"]["subject_name"] == "Pháp luật về chứng khoán và thị trường chứng khoán"
    assert exported["package"]["programs"] == ["moi-gioi-chung-khoan", "phan-tich-tai-chinh", "quan-ly-quy"]
    assert exported["package"]["subject_order"] == 1
    assert exported["package"]["subject_id_status"] == "confirmed"


def test_bad_manifest_exit_two(tmp_path):
    data = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    del data["session_id"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert main(["extract", "--manifest", str(path), "--out", str(tmp_path / "out")]) == 2


@pytest.mark.parametrize(("day", "slide_ids"), [
    (1, ["slide-ngay-1"]),
    (2, ["slide-ngay-2-1", "slide-ngay-2-2"]),
])
def test_example_manifest_ids(day, slide_ids):
    session_id = f"luat-2025-buoi-{day:02d}"
    path = Path(__file__).parents[1] / "examples" / f"{session_id}.manifest.yaml"
    manifest = load_manifest(path)
    assert manifest.subject_id == "phap-luat-chung-khoan"
    assert manifest.course_id == "luat-2025"
    assert manifest.session_id == session_id
    assert manifest.video.source_id == f"video-ngay-{day}"
    assert [s.source_id for s in manifest.slides] == slide_ids
    assert manifest.syllabus.source_id == "giao-trinh-luat"
    assert manifest.related_chapter_ids == []
    assert [c["chapter_id"] for c in manifest.syllabus.chapters] == [f"plck-c{i:02d}" for i in range(1, 12)]
    assert all(c["id_status"] == "proposed" for c in manifest.syllabus.chapters)
    assert "chào bán chứng khoán ra công chúng" in manifest.transcription.initial_prompt


def test_subjects_cli(capsys):
    assert main(["subjects"]) == 0
    output = capsys.readouterr().out
    assert "8 môn chuyên môn" in output
    for subject_id in [
        "phap-luat-chung-khoan", "co-ban-chung-khoan", "phan-tich-dau-tu-chung-khoan",
        "moi-gioi-tu-van-dau-tu", "tu-van-tai-chinh-bao-lanh-phat-hanh", "phan-tich-bao-cao-tai-chinh",
        "quan-ly-quy-va-tai-san", "chung-khoan-phai-sinh",
    ]:
        assert subject_id in output
    for name, count in [("Môi giới chứng khoán", 4), ("Phân tích tài chính", 6), ("Quản lý quỹ", 7)]:
        assert f"{name} · {count} môn" in output
