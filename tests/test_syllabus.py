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
