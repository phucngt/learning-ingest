import pytest
import yaml

from learning_ingest.errors import IngestError
from learning_ingest.manifest import load_manifest
from learning_ingest.registry import load_registry

SUBJECT_ID = "phap-luat-chung-khoan"
SUBJECT_NAME = "Pháp luật về chứng khoán và thị trường chứng khoán"
PROGRAMS = ["moi-gioi-chung-khoan", "phan-tich-tai-chinh", "quan-ly-quy"]


def write_manifest(tmp_path, **overrides):
    data = {
        "schema_version": 1,
        "subject_id": SUBJECT_ID,
        "course_id": "luat-2025",
        "session_id": "luat-2025-buoi-02",
        "session_label": "Buổi 02",
        "video": {"source_id": "video-ngay-2", "path": "video.mp4"},
        **overrides,
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_unknown_subject_lists_registry_ids(tmp_path):
    with pytest.raises(IngestError, match="unknown-subject") as error:
        load_manifest(write_manifest(tmp_path, subject_id="unknown-subject"))
    assert all(s["subject_id"] in str(error.value) for s in load_registry()["subjects"])


@pytest.mark.parametrize("programs", [[], ["moi-gioi-chung-khoan"]])
def test_manifest_programs_mismatch_lists_both_values(tmp_path, programs):
    with pytest.raises(IngestError, match="programs.*không khớp") as error:
        load_manifest(write_manifest(tmp_path, programs=programs))
    assert str(programs) in str(error.value)
    assert str(PROGRAMS) in str(error.value)


@pytest.mark.parametrize("overrides", [{}, {"programs": PROGRAMS[::-1], "subject_name": SUBJECT_NAME}])
def test_manifest_uses_canonical_metadata(tmp_path, overrides):
    manifest = load_manifest(write_manifest(tmp_path, **overrides))
    assert manifest.programs == PROGRAMS
    assert manifest.subject_name == SUBJECT_NAME
    assert manifest.subject_order == 1
    assert manifest.subject_id_status == "confirmed"
    public = manifest.public_dict()
    assert {key: public[key] for key in ("programs", "subject_name", "subject_order", "subject_id_status")} == {
        "programs": PROGRAMS, "subject_name": SUBJECT_NAME, "subject_order": 1, "subject_id_status": "confirmed",
    }


@pytest.mark.parametrize("name", [None, "Tên khác"])
def test_manifest_subject_name_mismatch(tmp_path, name):
    with pytest.raises(IngestError, match="subject_name.*không khớp"):
        load_manifest(write_manifest(tmp_path, subject_name=name))


def test_manifest_supplementary_subject_has_no_program(tmp_path):
    manifest = load_manifest(write_manifest(tmp_path, subject_id="chung-khoan-phai-sinh", programs=[]))
    assert manifest.programs == []
    assert manifest.subject_order == 8
    assert manifest.subject_id_status == "proposed"
