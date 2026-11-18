import pytest

from learning_ingest.cli import main
from learning_ingest.export import run_validate_export
from learning_ingest.validate import validate
from conftest import FIXTURES, read_json, write_json

CODES = ["segment_unknown", "timestamp_mismatch", "source_id_unknown", "page_out_of_range",
         "page_out_of_range", "section_unknown", "chapter_unknown", "chapter_reason_missing",
         "existing_unknown", "schema", "schema"]


def test_invalid_source_errors_associated_with_each_item(prepared):
    path = FIXTURES / "ai-output-invalid.json"
    result, _ = validate([path], prepared)
    assert not result.ok
    for index, code in enumerate(CODES, 1):
        matching = [i for i in result.errors if i.item == index and i.code == code]
        assert matching, (index, code, result.errors)
        assert all(i.local_id == "invalid-" + str(index) and i.title for i in matching)
        assert all(i.input_file == str(path) and i.path.startswith("knowledge_points[") for i in matching)
    assert main(["validate-export", "--input", str(path), "--out", str(prepared)]) == 1
    assert not (prepared / "export" / "knowledge-points.json").exists()
    assert not list((prepared / "export").glob("*-tri-thuc.md"))


def test_valid_five_points_and_warnings(prepared):
    result = run_validate_export([FIXTURES / "ai-output-valid.json"], prepared)
    assert result.ok and result.knowledge_points == 5
    exported = read_json(prepared / "export" / "knowledge-points.json")
    assert exported["package"]["review_status"] == "pending_review"
    assert all(p["review_status"] == "pending_review" for p in exported["knowledge_points"])
    report = read_json(prepared / "export" / "validation-report.json")
    assert {"page_needs_ocr", "package_stale"} <= {i["code"] for i in report["issues"]}


def test_invalid_run_removes_stale_exports(prepared, manifest):
    assert run_validate_export([FIXTURES / "ai-output-valid.json"], prepared).ok
    stale = [prepared / "export" / "knowledge-points.json", prepared / "export" / manifest.markdown_filename]
    assert all(p.exists() for p in stale)
    result = run_validate_export([FIXTURES / "ai-output-invalid.json"], prepared)
    assert not result.ok
    assert set(result.removed_stale) == set(stale)
    assert all(not p.exists() for p in stale)


@pytest.mark.parametrize("offset,valid", [(-1000, True), (-1001, False)])
def test_timestamp_start_tolerance(tmp_path, prepared, offset, valid):
    data = read_json(FIXTURES / "ai-output-valid.json")
    data["knowledge_points"] = data["knowledge_points"][:1]
    data["knowledge_points"][0]["sources"][0]["start_ms"] = 62000 + offset
    path = write_json(tmp_path / "adjusted.json", data)
    result, _ = validate([path], prepared)
    assert result.ok is valid
    assert any(i.code == "timestamp_mismatch" for i in result.errors) is (not valid)
