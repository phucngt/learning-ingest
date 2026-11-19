from pathlib import Path

import pytest

from learning_ingest.documents import extract_docx
from learning_ingest.slides import extract_pptx
from learning_ingest.syllabus import parse_syllabus

DOCS = Path(__file__).parent / "fixtures" / "docs-fake"


def test_pdf_syllabus_toc_and_running_header_do_not_steal_chapters():
    chapters = [{"chapter_id": "c1", "heading_match": r"Chuong\s+I\b"},
                {"chapter_id": "c2", "heading_match": r"Chuong\s+II\b"}]
    sy = parse_syllabus(DOCS / "fake-giao-trinh-muc-luc.pdf", "gt", None, chapters)
    by_id = {c["chapter_id"]: c for c in sy["chapters"]}
    assert (by_id["c1"]["pdf_page_start"], by_id["c1"]["pdf_page_end"]) == (2, 4)
    assert (by_id["c2"]["pdf_page_start"], by_id["c2"]["pdf_page_end"]) == (5, 6)
    sections = {s["heading"]: s for s in sy["sections"]}
    assert sections["Chuong I Tong quan (gia lap)"]["chapter_id"] == "c1"
    assert sections["Chuong II Ho so (gia lap)"]["chapter_id"] == "c2"
    assert sections["(Mở đầu)"]["chapter_id"] is None            # trang mục lục
    # đầu trang chạy vẫn nằm trong nội dung, chỉ không thành tiêu đề
    assert not any("GT mau" in s["heading"] for s in sy["sections"])
    assert any("GT mau" in s["text"] for s in sy["sections"])


def test_pptx_image_only_slide_with_notes_needs_ocr(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.notes_slide.notes_text_frame.text = "Ghi chú giả lập dài hơn hai mươi ký tự để vượt ngưỡng"
    path = tmp_path / "a.pptx"
    prs.save(str(path))
    page = extract_pptx(path, "s")["pages"][0]
    assert page["needs_ocr"] is True
    assert page["text"].startswith("Ghi chú: ")


def _docx(tmp_path, build):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    build(doc)
    path = tmp_path / "d.docx"
    doc.save(str(path))
    return path


def _bold(doc, text):
    doc.add_paragraph().add_run(text).bold = True


def test_docx_bold_heading_fallback(tmp_path):
    def build(doc):
        doc.add_paragraph("Đoạn mở đầu thường (giả lập).")
        _bold(doc, "QUY CHẾ GIẢ LẬP")
        _bold(doc, "PHẦN MỘT")                       # tiêu đề xuống dòng: gộp
        doc.add_paragraph("Nội dung phần một (giả lập).")
        _bold(doc, "Phần hai")
        doc.add_paragraph("Nội dung phần hai (giả lập).")
    res = extract_docx(_docx(tmp_path, build), "d")
    assert res["heading_mode"] == "bold"
    assert [s["heading"] for s in res["sections"]] == ["(Mở đầu)", "QUY CHẾ GIẢ LẬP PHẦN MỘT", "Phần hai"]
    assert res["sections"][1]["level"] == 1 and "Nội dung phần một" in res["sections"][1]["text"]


def test_docx_styles_win_over_bold(tmp_path):
    def build(doc):
        doc.add_heading("Điều 1 giả lập", level=1)
        _bold(doc, "Dòng đậm không phải tiêu đề")
        doc.add_paragraph("Nội dung (giả lập).")
    res = extract_docx(_docx(tmp_path, build), "d")
    assert res["heading_mode"] == "styles"
    assert [s["heading"] for s in res["sections"]] == ["Điều 1 giả lập"]
    assert "Dòng đậm không phải tiêu đề" in res["sections"][0]["text"]


def test_docx_none_mode(tmp_path):
    res = extract_docx(_docx(tmp_path, lambda d: d.add_paragraph("Chỉ có chữ thường (giả lập).")), "d")
    assert res["heading_mode"] == "none" and res["section_count"] == 1
