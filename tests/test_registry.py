from collections import Counter

import pytest
import yaml

from learning_ingest.errors import IngestError
from learning_ingest.registry import load_registry, program_names, programs_for, subject


def test_subject_registry():
    registry = load_registry()
    assert load_registry() is registry
    assert len(registry["subjects"]) == 8
    assert sorted(s["order"] for s in registry["subjects"]) == list(range(1, 9))
    assert Counter(pid for s in registry["subjects"] for pid in s["programs"]) == {
        "moi-gioi-chung-khoan": 4, "phan-tich-tai-chinh": 6, "quan-ly-quy": 7,
    }
    assert list(program_names().values()) == ["Môi giới chứng khoán", "Phân tích tài chính", "Quản lý quỹ"]
    assert programs_for("chung-khoan-phai-sinh") == []
    assert subject("chung-khoan-phai-sinh")["supplementary"] == (
        "Bổ sung để hành nghề nghiệp vụ phái sinh tương ứng"
    )


@pytest.mark.parametrize(("table", "row", "key", "value", "match"), [
    ("subjects", 1, "subject_id", "phap-luat-chung-khoan", "subject_id.*trùng"),
    ("programs", 1, "program_id", "moi-gioi-chung-khoan", "program_id.*trùng"),
    ("subjects", 1, "programs", ["unknown-program"], "unknown-program"),
    ("programs", 0, "required_subjects", 5, "moi-gioi-chung-khoan.*5.*4"),
    ("subjects", 1, "order", 1, "order"),
    ("subjects", 1, "order", 9, "order"),
])
def test_broken_registry(tmp_path, table, row, key, value, match):
    data = yaml.safe_load(yaml.safe_dump(load_registry(), allow_unicode=True))
    data[table][row][key] = value
    path = tmp_path / "subjects.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(IngestError, match=match):
        load_registry(path)
