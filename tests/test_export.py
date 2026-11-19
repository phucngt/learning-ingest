import pytest

from learning_ingest.export import _md_source


@pytest.mark.parametrize(("source_type", "title", "prefix"), [
    ("video", "  video bài giảng  ", "video bài giảng"),
    ("slide", "  SLIDE bài giảng  ", "SLIDE bài giảng"),
    ("syllabus", "  giáo trình Luật Mẫu  ", "giáo trình Luật Mẫu"),
    ("syllabus", "Luật Mẫu", "Giáo trình Luật Mẫu"),
])
def test_markdown_source_prefix_once(source_type, title, prefix):
    source = {
        "type": source_type, "title": title, "link_kind": "none",
        "timestamp": "00:01:02", "segment_id": "seg-example", "pdf_page": 1,
    }
    assert _md_source(source).startswith(prefix + ", ")
