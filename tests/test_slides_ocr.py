from hashlib import sha256
from shutil import copyfile

import pytest

from learning_ingest.errors import IngestError
from learning_ingest.export import run_validate_export
from learning_ingest.extract import load_extracted, run_extract
from learning_ingest.manifest import load_manifest
from learning_ingest.review import run_prepare_review
from learning_ingest.slides import read_slide_ocr
from learning_ingest.util import read_json, write_json
from learning_ingest.validate import Context

from conftest import FIXTURES


OCR_FILE = "scan/ocr.md"
PDF_ID = "slide-ngay-2-1"
PPTX_ID = "slide-pptx-gia-lap"


def _manifest_path(tmp_path, *, pptx=False):
    fixture = FIXTURES.parent / "docs-fake" if pptx else FIXTURES
    source = load_manifest(fixture / "manifest.yaml").slides[0]
    copyfile(source.path, tmp_path / source.path.name)
    path = tmp_path / "manifest.json"
    write_json(path, {
        "schema_version": 1,
        "subject_id": "phap-luat-chung-khoan",
        "course_id": "fake-course",
        "session_id": "fake-session",
        "session_label": "Buổi giả lập",
        "slides": [{
            "source_id": source.source_id, "path": source.path.name,
            "sharepoint_url": source.sharepoint_url, "page_link_template": source.page_link_template,
        }],
    })
    return path


def _configure_ocr(manifest_path, text):
    data = read_json(manifest_path)
    data["slides"][0]["ocr_path"] = OCR_FILE
    write_json(manifest_path, data)
    path = manifest_path.parent / OCR_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode("utf-8-sig"))
    return path


def test_read_slide_ocr_preserves_markdown_and_inline_text(tmp_path):
    path = tmp_path / "ocr.md"
    raw = (
        "Bỏ lời dẫn\r\n"
        "###### tRaNg pDf 1\r\n"
        "### Tiêu đề con\r\n\r\n"
        "![Hình giả lập](hinh.png)\r\n"
        "  Ghi chú ảnh  <!-- PDF_PAGE: 2 -->  Mở đầu mục 2\r\n"
        "<!-- trang 3 -->\r\n"
        "Nội dung  trang 3"
    ).encode("utf-8-sig")
    path.write_bytes(raw)

    pages, digest = read_slide_ocr(path, PDF_ID, 3)

    assert pages == {
        1: "### Tiêu đề con\n\n![Hình giả lập](hinh.png)\nGhi chú ảnh",
        2: "Mở đầu mục 2",
        3: "Nội dung trang 3",
    }
    assert digest == sha256(raw).hexdigest()


@pytest.mark.parametrize(("text", "message"), [
    (None, "không thấy file"),
    ("## Trang\nPDF 3\nKhông có mốc hợp lệ", "không có mốc trang"),
    ("## Trang PDF 1\n<!-- page: 1 -->", "trùng mốc trang 1"),
    ("<!-- page: 0 -->", "mốc trang 0 ngoài phạm vi"),
    ("## Trang PDF 4", "mốc trang 4 ngoài phạm vi"),
])
def test_invalid_ocr_is_reported_by_extract(tmp_path, text, message):
    manifest_path = _manifest_path(tmp_path)
    if text is not None:
        _configure_ocr(manifest_path, text)
    else:
        data = read_json(manifest_path)
        data["slides"][0]["ocr_path"] = OCR_FILE
        write_json(manifest_path, data)

    with pytest.raises(IngestError) as err:
        run_extract(load_manifest(manifest_path), tmp_path / "out", log=lambda _: None)
    assert PDF_ID in str(err.value)
    assert "ocr.md" in str(err.value)
    assert message in str(err.value)


def test_extract_merge_keeps_native_rows_and_reuses_slide_cache(tmp_path):
    manifest_path = _manifest_path(tmp_path)
    out = tmp_path / "out"
    baseline = run_extract(load_manifest(manifest_path), out, log=lambda _: None)
    base_lines = (out / "slides.jsonl").read_bytes().splitlines()
    assert baseline.pages_needing_ocr == 1

    path = _configure_ocr(manifest_path, "## Trang PDF 1\nBỏ qua chữ này.\n## Trang PDF 3\n  A  B\nC\n")
    manifest = load_manifest(manifest_path)
    first = run_extract(manifest, out, log=lambda _: None)
    extracted = load_extracted(out)
    assert manifest.slides[0].ocr_path == path
    assert extracted["meta"]["manifest"]["slides"][0]["ocr_path"] == str(path)
    assert extracted["meta"]["inputs"]["slides_ocr"] == {PDF_ID: sha256(path.read_bytes()).hexdigest()}
    assert extracted["slides_index"][PDF_ID]["pages_from_ocr"] == [3]
    assert extracted["slides_index"][PDF_ID]["pages_needing_ocr"] == []
    assert first.pages_needing_ocr == 0
    assert first.cache == {"hits": {"pdf": 1}, "misses": {}}
    assert (out / "slides.jsonl").read_bytes().splitlines()[:2] == base_lines[:2]
    assert extracted["slides"][-1] == {
        "source_id": PDF_ID, "pdf_page": 3, "text": "A B\nC", "char_count": 3,
        "needs_ocr": False, "text_origin": "ocr", "note": "chữ lấy từ OCR (ocr.md), cần đối chiếu ảnh trang",
    }
    assert first.warnings == [f"{PDF_ID}: bỏ qua mốc OCR trong ocr.md cho trang đã có chữ: [1]"]

    path.write_bytes("## Trang PDF 1\nSửa chữ bị bỏ qua.\n## Trang PDF 3\n  A  B\nC\n".encode("utf-8"))
    second = run_extract(manifest, out, log=lambda _: None)
    assert second.cache == first.cache
    assert second.extract_id != first.extract_id
    assert load_extracted(out)["slides"] == extracted["slides"]

    path.write_bytes("## Trang PDF 3\nChữ OCR đã sửa.".encode("utf-8"))
    third = run_extract(manifest, out, log=lambda _: None)
    assert third.cache == first.cache
    assert third.extract_id != second.extract_id
    assert load_extracted(out)["slides"][-1]["text"] == "Chữ OCR đã sửa."


@pytest.mark.parametrize("marker", ["## Trang PDF 2", "## Trang PDF 3"])
def test_missing_or_empty_page_remains_pending(tmp_path, marker):
    manifest_path = _manifest_path(tmp_path)
    _configure_ocr(manifest_path, marker + "\n \t\n")
    out = tmp_path / "out"

    result = run_extract(load_manifest(manifest_path), out, log=lambda _: None)

    assert result.pages_needing_ocr == 1
    ex = load_extracted(out)
    assert ex["slides_index"][PDF_ID]["pages_from_ocr"] == []
    assert ex["slides_index"][PDF_ID]["pages_needing_ocr"] == [3]
    assert ex["slides"][-1]["needs_ocr"] is True
    assert "text_origin" not in ex["slides"][-1]
    assert f"{PDF_ID}: trang chưa có mốc hoặc nội dung OCR trong ocr.md: [3]" in result.warnings
    assert f"{PDF_ID}: 1 trang thiếu lớp chữ, cần rà/OCR: [3]" in result.warnings


def test_null_and_absent_ocr_have_same_outputs(tmp_path):
    manifest_path = _manifest_path(tmp_path)
    out = tmp_path / "out"

    def snapshot():
        manifest = load_manifest(manifest_path)
        result = run_extract(manifest, out, use_cache=False, log=lambda _: None)
        review = run_prepare_review(manifest, out, log=lambda _: None)
        comparable = {}
        for path in out.rglob("*"):
            if path.name in ("extract-manifest.json", "review-manifest.json"):
                data = read_json(path)
                del data["generated_at"]
                comparable[path.relative_to(out)] = data
            elif path.is_file():
                comparable[path.relative_to(out)] = path.read_bytes()
        return result.extract_id, review.package_id, comparable

    baseline = snapshot()
    data = read_json(manifest_path)
    data["slides"][0]["ocr_path"] = None
    write_json(manifest_path, data)
    assert snapshot() == baseline

    ex = load_extracted(out)
    assert "ocr_path" not in ex["meta"]["manifest"]["slides"][0]
    assert "slides_ocr" not in ex["meta"]["inputs"]
    assert "pages_from_ocr" not in ex["slides_index"][PDF_ID]
    assert all("text_origin" not in row for row in ex["slides"])


@pytest.mark.parametrize(("pptx", "sid", "unit"), [(False, PDF_ID, "trang"), (True, PPTX_ID, "slide")])
def test_review_and_export_ocr_source(tmp_path, pptx, sid, unit):
    if pptx:
        pytest.importorskip("pptx")
    manifest_path = _manifest_path(tmp_path, pptx=pptx)
    text = "Mốc giả lập là 5 ngày."
    _configure_ocr(manifest_path, f"<!-- page: 3 -->\n{text}")
    manifest = load_manifest(manifest_path)
    out = tmp_path / "out"
    run_extract(manifest, out, log=lambda _: None)
    review = run_prepare_review(manifest, out, log=lambda _: None)
    page = next(row for row in load_extracted(out)["slides"] if row["pdf_page"] == 3)
    assert page["note"] == f"chữ lấy từ OCR (ocr.md), cần đối chiếu ảnh {unit}"
    package = review.parts[0].read_text(encoding="utf-8")
    assert (f"#### `{sid}` · {unit} 3\n"
            f"[Chữ của {unit} này lấy từ OCR, có thể sai chữ hoặc số. "
            f"Số liệu, thời hạn, điều luật trích từ {unit} này phải có verification_flags. "
            f'Trích nguồn {unit} này bằng "pdf_page": 3, kể cả khi chữ OCR ghi số slide khác.]\n{text}') in package
    assert f"; {unit} lấy chữ từ OCR: [3])" in package
    assert Context.load(out).slides[sid]["from_ocr"] == {3}

    source = {"type": "slide", "source_id": sid, "pdf_page": 3}
    input_path = tmp_path / "reviewed.json"
    write_json(input_path, {
        "schema_version": "1.0", "package_id": review.package_id, "subject_id": manifest.subject_id,
        "session_id": manifest.session_id,
        "knowledge_points": [{
            "local_id": "kp-001", "title": "Mốc giả lập", "summary": text,
            "subject_id": manifest.subject_id, "session_id": manifest.session_id,
            "chapter_id": None, "chapter_id_reason": "Gói giả lập không có giáo trình.",
            "existing_knowledge_point_id": None, "existing_match_reason": None,
            "sources": [source, source | {"pdf_page": 1}],
            "verification_flags": [{"kind": "deadline", "text": "5 ngày", "sources": [source]}],
            "conflicts": [], "review_status": "pending_review", "review_notes": "",
        }],
    })
    exported = run_validate_export([input_path], out, log=lambda _: None)
    assert exported.ok
    report = read_json(exported.export_dir / "validation-report.json")
    assert all(issue["code"] != "page_needs_ocr" for issue in report["issues"])
    kp = read_json(exported.export_dir / "knowledge-points.json")["knowledge_points"][0]
    ocr, native = kp["sources"]
    assert ocr["label"] == f"{sid} · {unit} 3 (chữ OCR)"
    assert native["label"] == f"{sid} · {unit} 1"
    assert ocr["needs_ocr"] is False
    assert ocr.keys() == native.keys()
    assert kp["verification_flags"][0]["sources"][0] == ocr
