from pathlib import Path

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
    assert len(read_json(out / "export" / "knowledge-points.json")["knowledge_points"]) == 5


def test_bad_manifest_exit_two(tmp_path):
    data = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    del data["session_id"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert main(["extract", "--manifest", str(path), "--out", str(tmp_path / "out")]) == 2


def test_example_manifest_ids():
    manifest = load_manifest(Path(__file__).parents[1] / "examples" / "luat-2025-buoi-02.manifest.yaml")
    assert manifest.subject_id == "phap-luat-chung-khoan"
    assert manifest.course_id == "luat-2025"
    assert manifest.session_id == "luat-2025-buoi-02"
    assert manifest.video.source_id == "video-ngay-2"
    assert [s.source_id for s in manifest.slides] == ["slide-ngay-2-1", "slide-ngay-2-2"]
    assert manifest.syllabus.source_id == "giao-trinh-luat"
