import pytest

from learning_ingest.errors import IngestError
from learning_ingest.syllabus import parse_syllabus
from conftest import FIXTURES


def test_fixture_page_boundaries_and_chapters():
    result = parse_syllabus(FIXTURES / "giao-trinh-fake.md", "giao-trinh-luat")
    assert result["pages_found"] == [40, 41, 42, 80, 81, 100]
    sections = result["sections"]
    assert sections[0]["pdf_pages"] == []
    assert sections[0]["chapter_id"] is None
    expected = [([40], "plck-c03"), ([40], "plck-c03"), ([41], "plck-c03"),
                ([42], "plck-c03"), ([80], "plck-c05"), ([80], "plck-c05"),
                ([81], "plck-c05"), ([100], None), ([100], None)]
    assert [(s["pdf_pages"], s["chapter_id"]) for s in sections[1:]] == expected
    assert "[trang 41]" in sections[2]["text"]


def test_marker_cursor_inline_and_unassociated_markers(tmp_path):
    path = tmp_path / "syllabus.md"
    path.write_text("<!-- page: 1 -->\n<!-- page: 2 -->\n# Topic\nText <!-- page: 3 --> more <!-- page: 4 --> text\n<!-- page: 5 --><!-- page: 6 -->\n## Next\nDone\n<!-- page: 7 -->", encoding="utf-8")
    result = parse_syllabus(path, "sy")
    assert result["pages_found"] == list(range(1, 8))
    topic = next(s for s in result["sections"] if s["heading"] == "Topic")
    following = next(s for s in result["sections"] if s["heading"] == "Next")
    assert topic["pdf_pages"] == [2, 3, 4]
    assert following["pdf_pages"] == [6]
    assert "[trang 3]" in topic["text"]


def test_front_matter_without_chapters_and_explicit_heading_id(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text("---\ntitle: Sample\n---\n<!-- page: 1 -->\n# Chương I. Nội dung {#c1}\nText\n", encoding="utf-8")
    result = parse_syllabus(path, "sy")
    assert result["chapters"][0]["chapter_id"] == "c1"
    assert result["sections"][-1]["chapter_id"] == "c1"


def test_no_markers_warning(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text("# Topic\nText", encoding="utf-8")
    result = parse_syllabus(path, "sy")
    assert result["pages_found"] == []
    assert any("không có mốc trang" in w for w in result["warnings"])


def test_custom_marker_and_invalid_pattern(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text("[[p12]]\n# Topic\nText", encoding="utf-8")
    result = parse_syllabus(path, "sy", r"\[\[p(\d+)\]\]")
    assert result["pages_found"] == [12]
    assert result["sections"][-1]["pdf_pages"] == [12]
    with pytest.raises(IngestError, match="nhóm"):
        parse_syllabus(path, "sy", r"page \d+")


REAL_STYLE = """## Trang PDF 1
### LỜI NÓI ĐẦU
Lời giới thiệu.
### DANH MỤC TỪ VIẾT TẮT
Danh sách.
## Trang PDF 2
### Chương I KHÁI QUÁT
Mở đầu chương.
#### 1.1. Tiểu mục
Nội dung ở trang 2.
## trang pdf 3
Nội dung tiếp theo.
## Trang PDF 4
### CHƯƠNG II CÔNG TY ĐẠI CHÚNG
#### 2.1. Tiểu mục
Nội dung ở trang 4.
## Trang PDF 431
### Chương I. KHÁI QUÁT
Dòng mục lục.
"""
MANIFEST_CHAPTERS = [
    {"chapter_id": "plck-c01", "heading_match": r"^Chương\s+I\b", "title": "Khái quát", "id_status": "proposed"},
    {"chapter_id": "plck-c02", "heading_match": r"^Chương\s+II\b", "id_status": "confirmed"},
]


def test_parse_real_syllabus_format(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text(REAL_STYLE, encoding="utf-8")
    result = parse_syllabus(path, "sy", chapters=MANIFEST_CHAPTERS)
    assert result["front_matter"] == {}
    assert result["pages_found"] == [1, 2, 3, 4, 431]
    assert [(s["heading"], s["chapter_id"], s["pdf_pages"]) for s in result["sections"]] == [
        ("LỜI NÓI ĐẦU", None, [1]),
        ("DANH MỤC TỪ VIẾT TẮT", None, [1]),
        ("Chương I KHÁI QUÁT", "plck-c01", [2]),
        ("1.1. Tiểu mục", "plck-c01", [2, 3]),
        ("CHƯƠNG II CÔNG TY ĐẠI CHÚNG", "plck-c02", [4]),
        ("2.1. Tiểu mục", "plck-c02", [4]),
        ("Chương I. KHÁI QUÁT", None, [431]),
    ]
    assert [(c["title"], c["id_status"], c["pdf_page_start"], c["pdf_page_end"]) for c in result["chapters"]] == [
        ("Khái quát", "proposed", 2, 3),
        ("CHƯƠNG II CÔNG TY ĐẠI CHÚNG", "confirmed", 4, 4),
    ]
    assert all("[trang " not in s["text"] for s in result["sections"])
    assert result["chapter_candidates"] == [
        {"heading": "Chương I KHÁI QUÁT", "level": 3, "pdf_page": 2, "occurrence": 1},
        {"heading": "CHƯƠNG II CÔNG TY ĐẠI CHÚNG", "level": 3, "pdf_page": 4, "occurrence": 1},
        {"heading": "Chương I. KHÁI QUÁT", "level": 3, "pdf_page": 431, "occurrence": 2},
    ]


def test_manifest_chapter_patterns_cannot_overlap(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text(REAL_STYLE, encoding="utf-8")
    chapters = [*MANIFEST_CHAPTERS, {"chapter_id": "overlap", "heading_match": r"khái quát"}]
    with pytest.raises(IngestError, match="plck-c01.*overlap"):
        parse_syllabus(path, "sy", chapters=chapters)


def test_manifest_chapters_override_front_matter(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text(
        "---\nchapters:\n  - chapter_id: old-id\n    title: Chương I KHÁI QUÁT\n---\n" + REAL_STYLE,
        encoding="utf-8",
    )
    chapters = [*MANIFEST_CHAPTERS, {"chapter_id": "missing", "heading_match": r"^Chương\s+III\b"}]
    result = parse_syllabus(path, "sy", chapters=chapters)
    assert [c["chapter_id"] for c in result["chapters"]] == ["plck-c01", "plck-c02", "missing"]
    assert any("manifest" in w and "front matter" in w for w in result["warnings"])
    assert any("missing" in w for w in result["warnings"])


def test_custom_marker_replaces_both_defaults(tmp_path):
    path = tmp_path / "sy.md"
    path.write_text("<!-- page: 1 -->\n## Trang PDF 2\n[[p3]]\n### Topic\nText\n", encoding="utf-8")
    result = parse_syllabus(path, "sy", r"\[\[p(\d+)\]\]")
    assert result["pages_found"] == [3]
    assert result["sections"][-1]["pdf_pages"] == [3]
