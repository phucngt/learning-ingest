from pathlib import Path

import jsonschema
import pytest
import yaml

from learning_ingest.cli import main
from learning_ingest.documents import extract_docx
from learning_ingest.errors import IngestError
from learning_ingest.manifest import load_manifest
from learning_ingest.slides import extract_pptx
from learning_ingest.syllabus import parse_syllabus
from learning_ingest.util import resource_json
from conftest import read_json, write_json

DOCS = Path(__file__).parent / "fixtures" / "docs-fake"
MANIFEST = DOCS / "manifest.yaml"
PILOT = Path(__file__).parent / "fixtures" / "pilot-fake" / "manifest.yaml"


def _manifest_file(tmp_path, mutate):
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mutate(data)
    for key in ("slides", "documents"):
        for item in data.get(key) or []:
            item["path"] = str(DOCS / item["path"])
    if data.get("syllabus"):
        data["syllabus"]["path"] = str(DOCS / data["syllabus"]["path"])
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_manifest_without_video():
    m = load_manifest(MANIFEST)
    assert m.video is None
    assert m.public_dict()["video"] is None
    assert [d.source_id for d in m.documents] == ["van-ban-gia-lap"]
    assert m.public_dict() == load_manifest(MANIFEST).public_dict()


def test_video_package_public_dict_has_no_documents_key():
    assert "documents" not in load_manifest(PILOT).public_dict()


def test_empty_package_rejected(tmp_path):
    def mutate(d):
        for key in ("slides", "documents", "syllabus"):
            d.pop(key)
    with pytest.raises(IngestError, match="Gói rỗng"):
        load_manifest(_manifest_file(tmp_path, mutate))


def test_bad_suffixes_and_duplicates_rejected(tmp_path):
    with pytest.raises(IngestError, match=r"\.pdf hoặc \.pptx"):
        load_manifest(_manifest_file(tmp_path, lambda d: d["slides"][0].update(path="x.ppt")))
    with pytest.raises(IngestError, match=r"\.docx"):
        load_manifest(_manifest_file(tmp_path, lambda d: d["documents"][0].update(path="x.doc")))
    with pytest.raises(IngestError, match="trùng"):
        load_manifest(_manifest_file(tmp_path, lambda d: d["documents"][0].update(source_id="slide-pptx-gia-lap")))


def test_extract_pptx_shape():
    pytest.importorskip("pptx")
    doc = extract_pptx(DOCS / "fake-slides.pptx", "s")
    assert doc["extractor"] == "python-pptx-text-1" and doc["page_count"] == 4
    p1, p2, p3, p4 = doc["pages"]
    assert set(p1) == {"source_id", "pdf_page", "text", "char_count", "needs_ocr", "note"}
    assert p1["text"].splitlines()[0] == "Tổng quan gói tài liệu (giả lập)"
    assert p1["text"].splitlines()[-1].startswith("Ghi chú: ")
    assert "Chỉ tiêu | Giá trị" in p2["text"] and "Chữ nằm trong nhóm hình" in p2["text"]
    assert p3["needs_ocr"] and p3["note"] == "slide chỉ có hình"
    assert not p4["needs_ocr"] and p4["note"] == "slide ẩn"


def test_extract_docx_sections():
    pytest.importorskip("docx")
    doc = extract_docx(DOCS / "fake-van-ban.docx", "d")
    secs = doc["sections"]
    assert doc["section_count"] == 3 and doc["extractor"] == "python-docx-text-2"
    assert secs[0]["heading"] == "(Mở đầu)" and secs[0]["level"] == 0
    assert secs[1]["level"] == 1 and "Thời hạn nộp hồ sơ | 30 ngày (giả lập)" in secs[1]["text"]
    assert secs[1]["section_id"] == "sec-002-dieu-1-pham-vi-ap-dung-gia-lap"
    assert extract_docx(DOCS / "fake-van-ban.docx", "d") == doc


def test_pdf_syllabus_chapters_and_pages():
    chapters = [{"chapter_id": "c1", "heading_match": r"Chuong\s+I\b"},
                {"chapter_id": "c2", "heading_match": r"Chuong\s+II\b"}]
    sy = parse_syllabus(DOCS / "fake-giao-trinh.pdf", "gt", None, chapters)
    assert sy["pages_found"] == [1, 2, 3]
    by_id = {c["chapter_id"]: c for c in sy["chapters"]}
    assert (by_id["c1"]["pdf_page_start"], by_id["c1"]["pdf_page_end"]) == (1, 2)
    assert by_id["c2"]["pdf_page_start"] == 3


def test_scanned_pdf_syllabus_rejected():
    with pytest.raises(IngestError, match="không có lớp chữ"):
        parse_syllabus(DOCS / "fake-giao-trinh-scan.pdf", "gt")


def _ai_output(out, sources):
    package_id = read_json(out / "review" / "review-manifest.json")["package_id"]
    return {
        "schema_version": "1.0", "package_id": package_id, "subject_id": "phap-luat-chung-khoan",
        "session_id": "fake-tai-lieu-01",
        "knowledge_points": [{
            "local_id": "kp-001", "title": "Điều kiện giả lập", "summary": "Tóm tắt giả lập.",
            "subject_id": "phap-luat-chung-khoan", "chapter_id": None, "chapter_id_reason": "Giả lập.",
            "session_id": "fake-tai-lieu-01", "existing_knowledge_point_id": None, "existing_match_reason": None,
            "sources": sources, "verification_flags": [], "conflicts": [], "review_status": "pending_review",
            "review_notes": "",
        }],
    }


def _run(tmp_path):
    pytest.importorskip("pptx")
    pytest.importorskip("docx")
    out = tmp_path / "out"
    assert main(["extract", "--manifest", str(MANIFEST), "--out", str(out)]) == 0
    assert main(["prepare-review", "--manifest", str(MANIFEST), "--out", str(out)]) == 0
    return out


def test_e2e_documents_only(tmp_path):
    out = _run(tmp_path)
    assert not (out / "transcript.vtt").exists()
    assert (out / "transcript.jsonl").read_text(encoding="utf-8") == ""
    package = (out / "review" / "package.md").read_text(encoding="utf-8")
    assert "_Gói này không có video/transcript._" in package and "mục `sec-002-" in package
    sources = [{"type": "slide", "source_id": "slide-pptx-gia-lap", "pdf_page": 1},
               {"type": "document", "source_id": "van-ban-gia-lap",
                "section_id": "sec-002-dieu-1-pham-vi-ap-dung-gia-lap"}]
    ai = write_json(tmp_path / "ai.json", _ai_output(out, sources))
    assert main(["validate-export", "--input", str(ai), "--out", str(out)]) == 0
    exported = read_json(out / "export" / "knowledge-points.json")
    jsonschema.validate(exported, resource_json("schemas/knowledge-points.schema.json"))
    labels = [s["label"] for s in exported["knowledge_points"][0]["sources"]]
    assert labels == ["Slide PowerPoint (giả lập) · slide 1",
                      "Quy chế (giả lập) · mục Điều 1. Phạm vi áp dụng (giả lập)"]
    md = (out / "export" / "tai-lieu-gia-lap-tri-thuc.md").read_text(encoding="utf-8")
    assert "slide **1**" in md and "Gói tài liệu" in md and "Văn bản" in md


def test_validate_document_and_video_errors(tmp_path):
    out = _run(tmp_path)
    sources = [{"type": "document", "source_id": "van-ban-gia-lap", "section_id": "sec-999-khong-co"},
               {"type": "document", "source_id": "khong-co", "section_id": "sec-001-mo-dau"},
               {"type": "video", "source_id": "video-x", "segment_id": "seg-000000-1"}]
    ai = write_json(tmp_path / "ai.json", _ai_output(out, sources))
    assert main(["validate-export", "--input", str(ai), "--out", str(out)]) == 1
    codes = [i["code"] for i in read_json(out / "export" / "validation-report.json")["issues"]]
    assert codes.count("section_unknown") == 1 and codes.count("source_id_unknown") == 2


def test_schema_rejects_document_with_pdf_page(tmp_path):
    out = _run(tmp_path)
    sources = [{"type": "document", "source_id": "van-ban-gia-lap", "section_id": "sec-001-mo-dau", "pdf_page": 1}]
    ai = write_json(tmp_path / "ai.json", _ai_output(out, sources))
    assert main(["validate-export", "--input", str(ai), "--out", str(out)]) == 1
