"""Tạo slide .pptx, văn bản .docx và giáo trình PDF giả lập cho test gói tài liệu.

    python tests/fixtures/docs-fake/make_fake_office.py

Cần python-pptx và python-docx (pip install -e ".[office]"). Toàn bộ nội dung là
dữ liệu giả lập. PDF dùng bộ tạo PDF thuần Python của make_fake_pdfs.py (font
chuẩn không có dấu tiếng Việt nên chữ trong PDF viết không dấu).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from make_fake_pdfs import make_pdf  # noqa: E402


def make_pptx(path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    title_only, blank = prs.slide_layouts[5], prs.slide_layouts[6]

    s1 = prs.slides.add_slide(title_only)
    s1.shapes.title.text = "Tổng quan gói tài liệu (giả lập)"
    box = s1.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1))
    box.text_frame.text = "Vốn điều lệ tối thiểu là 99 tỷ đồng (giả lập)"
    s1.notes_slide.notes_text_frame.text = "Nhắc người học đọc kỹ điều kiện (giả lập)"

    s2 = prs.slides.add_slide(title_only)
    s2.shapes.title.text = "Bảng và nhóm hình (giả lập)"
    table = s2.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(6), Inches(1)).table
    for r, row in enumerate([["Chỉ tiêu", "Giá trị"], ["Thời hạn xem xét", "45 ngày (giả lập)"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    group = s2.shapes.add_group_shape()
    inner = group.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    inner.text_frame.text = "Chữ nằm trong nhóm hình (giả lập)"

    prs.slides.add_slide(blank)           # slide trống: needs_ocr

    s4 = prs.slides.add_slide(title_only)
    s4.shapes.title.text = "Slide ẩn có chữ đủ dài (giả lập)"
    s4._element.set("show", "0")
    prs.save(str(path))


def make_docx(path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("Đoạn mở đầu của văn bản (giả lập).")
    doc.add_heading("Điều 1. Phạm vi áp dụng (giả lập)", level=1)
    doc.add_paragraph("Quy định này áp dụng cho mọi nhân sự (giả lập).")
    table = doc.add_table(rows=2, cols=2)
    for r, row in enumerate([["Hạng mục", "Mức"], ["Thời hạn nộp hồ sơ", "30 ngày (giả lập)"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.add_heading("Điều 2. Thời hạn (giả lập)", level=1)
    doc.add_paragraph("Hồ sơ được xử lý trong 10 ngày làm việc (giả lập).")
    doc.save(str(path))


def main() -> None:
    make_pptx(HERE / "fake-slides.pptx")
    make_docx(HERE / "fake-van-ban.docx")
    make_pdf(HERE / "fake-giao-trinh.pdf", [
        ["GIAO TRINH MAU (gia lap)", "Chuong I Tong quan (gia lap)", "Noi dung tong quan dai du de co lop chu"],
        ["Tiep noi chuong I (gia lap)", "Dieu kien chao ban: von toi thieu 99 ty dong"],
        ["Chuong II Ho so (gia lap)", "Thoi han xem xet ho so la 45 ngay (gia lap)"],
    ])
    make_pdf(HERE / "fake-giao-trinh-scan.pdf", [None, None, None])
    run = "Chuong I Tong quan - GT mau (gia lap)"       # đầu trang chạy, lặp ở mọi trang chương
    make_pdf(HERE / "fake-giao-trinh-muc-luc.pdf", [
        ["MUC LUC (gia lap)", "Chuong I Tong quan (gia lap) ........ 2", "Chuong II Ho so (gia lap) ........ 5"],
        ["Chuong I Tong quan (gia lap)", run, "Noi dung chuong mot trang dau (gia lap)"],
        [run, "Noi dung chuong mot trang hai (gia lap)"],
        [run, "Noi dung chuong mot trang ba (gia lap)"],
        ["Chuong II Ho so (gia lap)", run, "Noi dung chuong hai trang dau (gia lap)"],
        [run, "Noi dung chuong hai trang hai (gia lap)"],
    ])


if __name__ == "__main__":
    main()
